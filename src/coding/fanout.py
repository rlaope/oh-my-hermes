from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import re
from typing import Mapping, Sequence

from ..ingress import compact_source_metadata
from .fanout_contracts import (
    FANOUT_CLAIM_BOUNDARY,
    FANOUT_CONTRACT_SCHEMA_VERSION,
    FANOUT_FINAL_INTEGRATION_GATE,
    FANOUT_SPAWN_PLAN_CLAIM_BOUNDARY,
    FANOUT_SPAWN_PLAN_FIELDS,
    FANOUT_SPAWN_PLAN_SCHEMA_VERSION,
    FANOUT_SPAWN_PLAN_THRESHOLD,
    FANOUT_UNIT_OWNERS,
    FanoutContractError,
    MAX_SPAWN_PLAN_FIELD_CHARS,
    MAX_UNIT_VERIFICATION_COMMAND_CHARS,
    MAX_UNIT_VERIFICATION_COMMANDS,
    PREPARED_NOT_OBSERVED,
    verification_command_argv,
)
from .executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    complete_executor_capability_snapshot,
    prepared_executor_capability_snapshot,
)
from .model_routing import model_route_for_unit

_UNIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FROZEN_CAPABILITY_SNAPSHOT_POLICY = "frozen_required"


def build_fanout_contract(
    goal: str,
    units: Sequence[Mapping[str, object]],
    *,
    source: str = "generic",
    source_metadata: Mapping[str, object] | None = None,
    local_catalogs: Mapping[str, Mapping[str, object]] | None = None,
    capability_snapshots: Mapping[str, Mapping[str, object]] | None = None,
    spawn_plan: Mapping[str, object] | None = None,
) -> dict[str, object]:
    normalized_goal = " ".join(goal.split())
    if not normalized_goal:
        raise FanoutContractError("fanout goal is required")
    normalized_units = [_normalized_unit(unit, index) for index, unit in enumerate(units)]
    validate_fanout_units(normalized_units)
    validated_capability_snapshots = _validated_capability_snapshots(
        capability_snapshots,
        normalized_units,
    )
    conflict_notes = detect_boundary_overlaps(normalized_units)
    order = merge_order(normalized_units)
    # Last, after every structural check. A split with overlapping boundaries
    # or a dependency cycle can never be frozen no matter what justifies it,
    # and asking for four paragraphs first means the operator writes them for
    # a decomposition they then have to throw away. Structure is cheaper to
    # fix and is a precondition for the justification being worth anything.
    accepted_spawn_plan = require_spawn_plan(len(normalized_units), spawn_plan)
    digest = sha256(normalized_goal.encode("utf-8")).hexdigest()
    fanout_id = f"fanout-{digest[:12]}"
    safety_revision = _frozen_safety_profile_revision()
    unit_ids = [str(unit["unit_id"]) for unit in normalized_units]
    contract_units = [
        _contract_unit(
            unit,
            sibling_scopes=_sibling_scopes(normalized_units, str(unit["unit_id"])),
            fanout_id=fanout_id,
            local_catalogs=local_catalogs,
            capability_snapshots=validated_capability_snapshots,
        )
        for unit in normalized_units
    ]
    return {
        "schema_version": FANOUT_CONTRACT_SCHEMA_VERSION,
        "fanout_id": fanout_id,
        "status": PREPARED_NOT_OBSERVED,
        "source": source,
        "source_metadata": compact_source_metadata(source_metadata),
        "goal": {
            "summary": f"Fanout request ({len(normalized_goal)} chars, sha256:{digest[:12]})",
            "summary_kind": "digest_reference",
            "input_chars": len(normalized_goal),
            "sha256": digest,
            "raw_prompt_stored": False,
        },
        # Frozen beside the goal digest and for the same reason: the contract
        # records what it was prepared under so a later boundary can re-prove
        # it. `fanout_dispatch.verify_safety_profile_matches_contract` refuses
        # dispatch when the live profile no longer matches this value.
        # Optional and additive under `fanout_contract/v1`: an absent key means
        # "not gated", which is what contracts frozen before this field carry
        # and what the dispatch re-check already treats as a pass.
        **({"safety_profile_revision": safety_revision} if safety_revision else {}),
        # Optional and additive for the same reason the safety revision is: a
        # contract at or below the threshold carries no plan and stays
        # byte-identical to one frozen before this gate existed.
        **(
            {
                "spawn_plan": {
                    "schema_version": FANOUT_SPAWN_PLAN_SCHEMA_VERSION,
                    **accepted_spawn_plan,
                    "unit_count": len(normalized_units),
                    "threshold": FANOUT_SPAWN_PLAN_THRESHOLD,
                    "claim_boundary": FANOUT_SPAWN_PLAN_CLAIM_BOUNDARY,
                }
            }
            if accepted_spawn_plan
            else {}
        ),
        "units": contract_units,
        "merge_plan": {
            "merge_order": order,
            "final_integration_gate": list(FANOUT_FINAL_INTEGRATION_GATE),
            "conflict_risk_notes": conflict_notes,
        },
        "board_projection": {
            "schema_version": "agent_board_card/v1",
            "unit_ids": unit_ids,
            "status_by_unit": {unit_id: "prepared" for unit_id in unit_ids},
        },
        "observed_evidence_required": [
            "per-unit run records for dispatch, worker result, verification, review, CI, merge-readiness, and merge",
        ],
        "claim_boundary": FANOUT_CLAIM_BOUNDARY,
    }


def _validated_capability_snapshots(
    snapshots: Mapping[str, Mapping[str, object]] | None,
    units: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]] | None:
    owners = sorted(
        {
            str(unit.get("owner"))
            for unit in units
            if unit.get("owner") is not None
        }
    )
    if snapshots is None:
        return {
            owner: prepared_executor_capability_snapshot(owner)
            for owner in owners
        }
    validated: dict[str, dict[str, object]] = {}
    for owner in owners:
        snapshot = snapshots.get(owner)
        if not isinstance(snapshot, Mapping):
            raise FanoutContractError(
                f"executor capability snapshot for {owner} must be a mapping"
            )
        if snapshot.get("executor") != owner:
            raise FanoutContractError(
                f"executor capability snapshot for {owner} does not match its owner"
            )
        try:
            validated[owner] = complete_executor_capability_snapshot(snapshot)
        except ExecutorCapabilitySnapshotError as exc:
            raise FanoutContractError(
                f"executor capability snapshot for {owner} is invalid: {exc}"
            ) from exc
    return validated


def _frozen_safety_profile_revision() -> str:
    """The live safety-profile revision, or "" when that lane is not installed.

    Bound lazily for the reason `fanout_dispatch._live_safety_profile_revision`
    is: the contract builder must keep working in an install that does not ship
    the preflight evaluator. An empty answer freezes no revision at all rather
    than freezing a placeholder that would later read as drift.
    """
    try:
        from ..quality.safety_preflight import safety_profile_revision
    except ImportError:
        return ""
    return safety_profile_revision()


def validate_fanout_units(units: Sequence[Mapping[str, object]]) -> None:
    if len(units) < 2:
        raise FanoutContractError(
            "fanout requires at least two units; route a single unit through `omh coding delegate` instead"
        )
    seen: set[str] = set()
    known = {str(unit.get("unit_id", "")) for unit in units}
    for unit in units:
        unit_id = str(unit.get("unit_id", ""))
        if not _UNIT_ID_RE.match(unit_id):
            raise FanoutContractError(f"unit_id must be a lowercase slug: {unit_id!r}")
        if unit_id in seen:
            raise FanoutContractError(f"duplicate unit_id: {unit_id}")
        seen.add(unit_id)
        owner = unit.get("owner")
        if owner is not None and str(owner) not in FANOUT_UNIT_OWNERS:
            raise FanoutContractError(
                f"unit {unit_id} owner {owner!r} is not one of {', '.join(FANOUT_UNIT_OWNERS)} (or null for unassigned)"
            )
        file_scope = unit.get("file_scope", [])
        if not isinstance(file_scope, (list, tuple)) or not [str(path) for path in file_scope if str(path).strip()]:
            raise FanoutContractError(f"unit {unit_id} requires a non-empty file_scope boundary")
        for dependency in unit.get("depends_on", []) or []:
            if str(dependency) not in known:
                raise FanoutContractError(f"unit {unit_id} depends on unknown unit {dependency!r}")
            if str(dependency) == unit_id:
                raise FanoutContractError(f"unit {unit_id} cannot depend on itself")


def spawn_plan_required(unit_count: int) -> bool:
    """Whether a split this wide has to carry an operator justification."""
    return unit_count > FANOUT_SPAWN_PLAN_THRESHOLD


def normalized_spawn_plan(plan: Mapping[str, object] | None) -> dict[str, object] | None:
    """Collapse a proposed spawn plan to its stored shape, or None when absent.

    Shape failures raise; a field that is merely blank does not. Blank is the
    answer `missing_spawn_plan_fields` reports by name, which is a better
    error than a generic "invalid plan".
    """
    if plan is None:
        return None
    if not isinstance(plan, Mapping):
        raise FanoutContractError("spawn_plan must be an object")
    normalized: dict[str, object] = {}
    for field in FANOUT_SPAWN_PLAN_FIELDS:
        value = plan.get(field, "")
        # A justification has to be prose an operator wrote. `str(value)` would
        # accept a list, a dict, or a bool and freeze its Python repr into the
        # contract as if it were an answer — single quotes and all — which is
        # exactly the "answer nobody wrote" this gate exists to refuse.
        if value is not None and not isinstance(value, str):
            raise FanoutContractError(
                f"spawn_plan {field} must be a string; got {type(value).__name__}"
            )
        text = " ".join(str(value or "").split())
        if len(text) > MAX_SPAWN_PLAN_FIELD_CHARS:
            raise FanoutContractError(
                f"spawn_plan {field} must be at most {MAX_SPAWN_PLAN_FIELD_CHARS} chars"
            )
        normalized[field] = text
    return normalized


def missing_spawn_plan_fields(plan: Mapping[str, object] | None) -> list[str]:
    """Plan fields still unanswered, in declaration order.

    Answers the *blank* question only. Over-length and wrong-typed fields are
    shape failures that `normalized_spawn_plan` raises on, so call this on a
    normalized plan to get a complete verdict.
    """
    if plan is None:
        return list(FANOUT_SPAWN_PLAN_FIELDS)
    return [field for field in FANOUT_SPAWN_PLAN_FIELDS if not str(plan.get(field, "") or "").strip()]


def require_spawn_plan(
    unit_count: int,
    plan: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Return the plan to freeze, refusing an unjustified wide split.

    One rule, so there is no silent path: a plan that is supplied at all must
    be complete, and above the threshold one must be supplied. A half-filled
    receipt is worse than none — it reads as an answer — and freezing one
    would also add a `spawn_plan` key to contracts that used to have none,
    which is exactly the drift this gate must not cause.
    """
    normalized = normalized_spawn_plan(plan)
    required = spawn_plan_required(unit_count)
    if normalized is None:
        if required:
            raise FanoutContractError(
                f"a {unit_count}-unit split exceeds the {FANOUT_SPAWN_PLAN_THRESHOLD}-unit spawn-plan "
                f"threshold; add a spawn_plan to the units payload answering: "
                f"{', '.join(FANOUT_SPAWN_PLAN_FIELDS)}"
            )
        return None
    missing = missing_spawn_plan_fields(normalized)
    if not missing:
        return normalized
    # A plan IS present here, so neither branch tells the operator to add one —
    # they are looking straight at it. Above the threshold the plan is also
    # mandatory, so the only remedy offered is completing it.
    if required:
        raise FanoutContractError(
            f"the supplied spawn_plan is incomplete; answer {', '.join(missing)} "
            f"(a {unit_count}-unit split exceeds the {FANOUT_SPAWN_PLAN_THRESHOLD}-unit threshold, "
            f"so the plan is required)"
        )
    raise FanoutContractError(
        f"the supplied spawn_plan is incomplete; answer {', '.join(missing)} or remove the spawn_plan "
        f"entirely (a {unit_count}-unit split does not require one)"
    )


def detect_boundary_overlaps(units: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    notes: list[dict[str, object]] = []
    indexed = [(str(unit["unit_id"]), {str(path) for path in unit.get("file_scope", [])}) for unit in units]
    edges = {
        (str(unit["unit_id"]), str(dependency))
        for unit in units
        for dependency in unit.get("depends_on", []) or []
    }
    for position, (first_id, first_scope) in enumerate(indexed):
        for second_id, second_scope in indexed[position + 1 :]:
            shared = sorted(first_scope & second_scope)
            if not shared:
                continue
            if (first_id, second_id) not in edges and (second_id, first_id) not in edges:
                raise FanoutContractError(
                    f"units {first_id} and {second_id} share files {shared} without a depends_on edge; "
                    "make one depend on the other or split the boundary"
                )
            notes.append(
                {
                    "units": sorted((first_id, second_id)),
                    "shared_files": shared,
                    "resolution": "ordered by depends_on edge; merge strictly in merge_order",
                }
            )
    return notes


def merge_order(units: Sequence[Mapping[str, object]]) -> list[str]:
    remaining = {
        str(unit["unit_id"]): {str(dependency) for dependency in unit.get("depends_on", []) or []}
        for unit in units
    }
    order: list[str] = []
    while remaining:
        ready = sorted(unit_id for unit_id, deps in remaining.items() if not deps)
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise FanoutContractError(f"depends_on contains a cycle among units: {cycle}")
        for unit_id in ready:
            order.append(unit_id)
            del remaining[unit_id]
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def is_degenerate_single_unit(units: Sequence[Mapping[str, object]]) -> bool:
    return len(units) == 1


def single_unit_redirect(units: Sequence[Mapping[str, object]]) -> dict[str, object]:
    unit = dict(units[0]) if units else {}
    return {
        "schema_version": "fanout_redirect/v1",
        "status": "redirect_to_delegate",
        "reason": "A single work unit does not need a fanout contract.",
        "next_command": "omh coding delegate",
        "unit_id": str(unit.get("unit_id", "")),
    }


def _normalized_unit(unit: Mapping[str, object], index: int) -> dict[str, object]:
    if not isinstance(unit, Mapping):
        raise FanoutContractError(f"unit at index {index} must be an object")
    file_scope = [str(path).strip() for path in unit.get("file_scope", []) or [] if str(path).strip()]
    depends_on = [str(dependency).strip() for dependency in unit.get("depends_on", []) or [] if str(dependency).strip()]
    owner = unit.get("owner")
    return {
        "unit_id": str(unit.get("unit_id", "")).strip(),
        "title": " ".join(str(unit.get("title", "")).split()),
        "owner": str(owner) if owner is not None and str(owner).strip() else None,
        "file_scope": sorted(set(file_scope)),
        "depends_on": sorted(set(depends_on)),
        "model": str(unit.get("model", "") or "").strip(),
        "reasoning_effort": str(unit.get("reasoning_effort", "") or "").strip(),
        "role": str(unit.get("role", "") or "").strip(),
        "domain": str(unit.get("domain", "") or "").strip(),
        "depth": str(unit.get("depth", "") or "").strip(),
        # None (key absent) and [] (declared empty) are different answers: absent
        # means "arrange from discovery at dispatch time", [] means "the operator
        # chose the pure prompt". Order is preserved — a sequence is a sequence.
        "skill_sequence": _normalized_skill_sequence(unit.get("skill_sequence"), index),
        # Prose `integration_checks` say what "verified" means; these say how a
        # dispatcher could observe it. An empty answer is the default and means
        # the contract names no command anyone can run for this unit.
        "verification_commands": _normalized_verification_commands(
            unit.get("verification_commands"), index
        ),
    }


# Declared skill invocations are the one operator-typed string that reaches
# executor-facing prompt text verbatim, so they get an explicit shape gate:
# bounded, single-line, and free of the backticks the prompt wraps them in.
_MAX_SKILL_SEQUENCE_STEPS = 8
_MAX_SKILL_INVOCATION_CHARS = 80


def _normalized_skill_sequence(value: object, index: int) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise FanoutContractError(f"unit at index {index} skill_sequence must be a list of invocation strings")
    entries = [str(entry).strip() for entry in value]
    entries = [entry for entry in entries if entry]
    if len(entries) > _MAX_SKILL_SEQUENCE_STEPS:
        raise FanoutContractError(
            f"unit at index {index} skill_sequence must have at most {_MAX_SKILL_SEQUENCE_STEPS} steps"
        )
    for entry in entries:
        if len(entry) > _MAX_SKILL_INVOCATION_CHARS or "`" in entry or "\n" in entry or "\r" in entry:
            raise FanoutContractError(
                f"unit at index {index} skill_sequence entries must be single-line, "
                f"at most {_MAX_SKILL_INVOCATION_CHARS} chars, and contain no backticks"
            )
    return entries


def _normalized_verification_commands(value: object, index: int) -> list[str]:
    """Collapse a unit's declared verification commands to their stored shape.

    Blank entries raise rather than being dropped: a command the operator meant
    to write and left empty is a hole in the evidence they are asking the
    dispatcher to produce, and silently shortening the list would hide it.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise FanoutContractError(
            f"unit at index {index} verification_commands must be a list of command strings"
        )
    if len(value) > MAX_UNIT_VERIFICATION_COMMANDS:
        raise FanoutContractError(
            f"unit at index {index} verification_commands must have at most "
            f"{MAX_UNIT_VERIFICATION_COMMANDS} commands"
        )
    commands: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise FanoutContractError(
                f"unit at index {index} verification_commands entries must be non-empty strings; "
                f"got {entry!r}"
            )
        command = " ".join(entry.split())
        if len(command) > MAX_UNIT_VERIFICATION_COMMAND_CHARS:
            raise FanoutContractError(
                f"unit at index {index} verification_commands entries must be at most "
                f"{MAX_UNIT_VERIFICATION_COMMAND_CHARS} chars"
            )
        # Parsed at freeze time so a command no dispatcher could run fails here,
        # where the operator is still holding it, rather than mid-dispatch.
        verification_command_argv(command)
        commands.append(command)
    return commands


def _sibling_scopes(units: Sequence[Mapping[str, object]], unit_id: str) -> list[str]:
    scopes: set[str] = set()
    for unit in units:
        if str(unit["unit_id"]) == unit_id:
            continue
        scopes.update(str(path) for path in unit.get("file_scope", []))
    return sorted(scopes)


def _contract_unit(
    unit: Mapping[str, object],
    *,
    sibling_scopes: list[str],
    fanout_id: str,
    local_catalogs: Mapping[str, Mapping[str, object]] | None = None,
    capability_snapshots: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    unit_id = str(unit["unit_id"])
    own_scope = set(str(path) for path in unit.get("file_scope", []))
    executor_target = str(unit.get("owner")) if unit.get("owner") else "choose"
    local_catalog = (local_catalogs or {}).get(executor_target)
    model_route = model_route_for_unit(unit, executor_target, local_catalog)
    handoff: dict[str, object] = {
        "schema_version": "fanout_unit_handoff/v1",
        "executor_target": executor_target,
        "dispatch_policy": "prepare_only",
        "status": PREPARED_NOT_OBSERVED,
        "claim_boundary": (
            "This per-unit handoff is prepared guidance only; record observed evidence on a run named by "
            "run_ref before any dispatch, verification, review, CI, or merge claim."
        ),
    }
    if model_route is not None:
        handoff["model_route"] = model_route
    capability_snapshot = (capability_snapshots or {}).get(executor_target)
    if capability_snapshots is not None and executor_target != "choose":
        handoff["executor_capability_snapshot_policy"] = _FROZEN_CAPABILITY_SNAPSHOT_POLICY
    if isinstance(capability_snapshot, Mapping):
        handoff["executor_capability_snapshot"] = deepcopy(dict(capability_snapshot))
    contract_unit: dict[str, object] = {
        "unit_id": unit_id,
        "title": str(unit.get("title") or unit_id),
        "owner": unit.get("owner"),
        "boundary": {
            "file_scope": sorted(own_scope),
            "do_not_touch": [path for path in sibling_scopes if path not in own_scope],
        },
        "branch_suggestion": f"agent/{unit_id}",
        "depends_on": list(unit.get("depends_on", [])),
        "run_ref": f"{fanout_id}-{unit_id}",
        "handoff": handoff,
        "integration_checks": [
            "unit tests covering the unit's file_scope pass",
            "no edits outside boundary.file_scope",
        ],
        "status": "prepared",
    }
    # Only a declared answer rides the contract; absence keeps existing
    # contracts byte-identical and means "arrange from discovery at dispatch".
    if unit.get("skill_sequence") is not None:
        contract_unit["skill_sequence"] = list(unit["skill_sequence"])
    # Same additive rule: a unit that declared no runnable command carries no
    # key, so contracts frozen before this field stay byte-identical.
    if unit.get("verification_commands"):
        contract_unit["verification_commands"] = list(unit["verification_commands"])
    return contract_unit
