from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import re
from typing import Mapping, Sequence

from ..ingress import compact_source_metadata
from ..plugin_bundle.omh import dag_core
from .executors import canonical_executor_profile
from .fanout_contracts import (
    FANOUT_CLAIM_BOUNDARY,
    FANOUT_CONTRACT_SCHEMA_VERSION,
    FANOUT_FINAL_INTEGRATION_GATE,
    FANOUT_SPAWN_PLAN_CLAIM_BOUNDARY,
    FANOUT_SPAWN_PLAN_FIELDS,
    FANOUT_SPAWN_PLAN_SCHEMA_VERSION,
    FANOUT_SPAWN_PLAN_THRESHOLD,
    FANOUT_UNIT_INPUT_BUDGET_CLAIM_BOUNDARY,
    FANOUT_UNIT_INPUT_BUDGET_SCHEMA_VERSION,
    FANOUT_UNIT_KINDS,
    FANOUT_UNIT_OWNERS,
    FanoutContractError,
    MAX_CHARS_PER_TOKEN,
    MAX_SPAWN_PLAN_FIELD_CHARS,
    MAX_UNIT_VERIFICATION_CHECK_ID_CHARS,
    MAX_UNIT_VERIFICATION_CHECK_TIMEOUT,
    MAX_UNIT_VERIFICATION_COMMAND_CHARS,
    MAX_UNIT_INPUT_BUDGET_CHARS,
    MAX_UNIT_SOURCE_RANGE_DIGEST_CHARS,
    MAX_UNIT_SOURCE_RANGE_SOURCE_CHARS,
    MAX_UNIT_SOURCE_RANGE_SPAN_CHARS,
    MAX_UNIT_SOURCE_RANGES,
    MAX_UNIT_VERIFICATION_COMMANDS,
    PREPARED_NOT_OBSERVED,
    REPRODUCTION_UNIT_KIND,
    UNIT_SOURCE_RANGE_KEYS,
    VERIFICATION_CHECK_ID_PATTERN,
    VERIFICATION_CHECK_CLAIM_SCOPES,
    VERIFICATION_CHECK_RESOURCE_CLASS_PATTERN,
    is_verification_check_resource_class,
    VERIFICATION_CHECK_SAFETIES,
    VERIFICATION_CHECK_TIERS,
    verification_command_argv,
)
from .executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    complete_executor_capability_snapshot,
    prepared_executor_capability_snapshot,
)
from .fanout_review_budget import normalized_review_role
from .postconditions import normalized_task_linked_test_runner, task_linked_criterion
from .fanout_repair import normalized_max_repair_attempts
from .model_routing import MODEL_CATEGORIES, canonical_model_category, model_route_for_unit
from .media_handoff_capabilities import build_executor_modality_decision, normalize_input_representation

_UNIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_VERIFICATION_CHECK_ID_RE = re.compile(VERIFICATION_CHECK_ID_PATTERN)
# Same token shape `omh_identity_profiles/v1` uses for identity names; units
# declaring a name outside it can never resolve, so the freeze refuses them.
_IDENTITY_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_FROZEN_CAPABILITY_SNAPSHOT_POLICY = "frozen_required"


def build_fanout_contract(
    goal: str,
    units: Sequence[Mapping[str, object]],
    *,
    source: str = "generic",
    source_metadata: Mapping[str, object] | None = None,
    local_catalogs: Mapping[str, Mapping[str, object]] | None = None,
    category_config: Mapping[str, object] | None = None,
    identity_config: Mapping[str, object] | None = None,
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
            category_config=category_config,
            identity_config=identity_config,
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
    if len(units) < 1:
        raise FanoutContractError("fanout requires at least one unit")
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
        category = str(unit.get("category", "") or "").strip()
        if category and not canonical_model_category(category):
            raise FanoutContractError(
                f"unit {unit_id} category {category!r} is not one of {', '.join(MODEL_CATEGORIES)}"
            )
        identity = str(unit.get("identity", "") or "").strip()
        if identity and not _IDENTITY_NAME_RE.match(identity):
            # Same freeze-time discipline as `category`: a name that cannot
            # match the `omh_identity_profiles/v1` token shape would freeze as
            # an `unknown` route, hiding the typo inside a prepared contract.
            raise FanoutContractError(
                f"unit {unit_id} identity {identity!r} is not a valid identity name "
                "([a-z0-9_-]{1,64})"
            )
        dependencies = list(unit.get("depends_on", []) or [])
        names = [str(dependency) for dependency in dependencies]
        problem = dag_core.edge_problem(unit_id, names, known)
        if problem is not None and problem[0] == dag_core.UNKNOWN_DEPENDENCY:
            # The value as the unit gave it, as this message always quoted it.
            raise FanoutContractError(
                f"unit {unit_id} depends on unknown unit {dependencies[names.index(problem[1])]!r}"
            )
        if problem is not None:
            raise FanoutContractError(f"unit {unit_id} cannot depend on itself")
    _require_reproduction_hold_edges(units)


def _require_reproduction_hold_edges(units: Sequence[Mapping[str, object]]) -> None:
    """Refuse a debugging-shaped split an edit unit could enter unheld.

    A split is debugging-shaped exactly when it declares a reproduction unit.
    Then every other unit must reach one through `depends_on`, directly or
    through another unit: the dispatcher's hold sits on that edge, so a unit
    with no path to a reproduction would be admitted before any failure was
    observed. A split with no reproduction unit is not touched.
    """
    reproduction_ids = {
        str(unit.get("unit_id", "")) for unit in units if unit.get("kind") == REPRODUCTION_UNIT_KIND
    }
    if not reproduction_ids:
        return
    edges = {str(unit.get("unit_id", "")): [str(dep) for dep in unit.get("depends_on", []) or []] for unit in units}
    for unit_id in sorted(edges):
        if unit_id in reproduction_ids:
            continue
        seen: set[str] = set()
        frontier = list(edges[unit_id])
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(edges.get(current, []))
        if not seen & reproduction_ids:
            raise FanoutContractError(
                f"unit {unit_id} must depend on a reproduction unit ({', '.join(sorted(reproduction_ids))}), "
                "directly or through another unit: a split that declares a reproduction holds every other "
                "unit behind an observed failure"
            )


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
    scopes = [(str(unit["unit_id"]), [str(path) for path in unit.get("file_scope", [])]) for unit in units]
    for first_id, second_id, shared, joined in dag_core.shared_scope_pairs(scopes, _parents(units)):
        if not joined:
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


def _parents(units: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    return {str(unit["unit_id"]): [str(dep) for dep in unit.get("depends_on", []) or []] for unit in units}


def merge_order(units: Sequence[Mapping[str, object]]) -> list[str]:
    placed, stuck = dag_core.layer_of([str(unit["unit_id"]) for unit in units], _parents(units), strict=True)
    if stuck:
        cycle = ", ".join(sorted(stuck))
        raise FanoutContractError(f"depends_on contains a cycle among units: {cycle}")
    return sorted(placed, key=lambda unit_id: (placed[unit_id], unit_id))


def is_degenerate_single_unit(units: Sequence[Mapping[str, object]]) -> bool:
    return len(units) == 1


def single_unit_redirect(units: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """The redirect `fanout prepare` returns instead of freezing a one-unit split.

    The heavy propose/freeze ceremony this subcommand runs is built for
    multi-unit splits with boundary and dependency structure to validate; one
    unit has none of that. `omh coding run` builds and dispatches a one-unit
    fanout contract in a single call through the same engine, so it is the
    executing surface this redirect now points at (`omh coding delegate`
    still prepares a non-dispatchable handoff record for owner selection, but
    never spawns anything).
    """
    unit = dict(units[0]) if units else {}
    return {
        "schema_version": "fanout_redirect/v1",
        "status": "redirect_to_run",
        "reason": "A single work unit does not need a fanout contract.",
        "next_command": "omh coding run",
        "unit_id": str(unit.get("unit_id", "")),
    }


def _normalized_unit(unit: Mapping[str, object], index: int) -> dict[str, object]:
    if not isinstance(unit, Mapping):
        raise FanoutContractError(f"unit at index {index} must be an object")
    file_scope = [str(path).strip() for path in unit.get("file_scope", []) or [] if str(path).strip()]
    depends_on = [str(dependency).strip() for dependency in unit.get("depends_on", []) or [] if str(dependency).strip()]
    owner = unit.get("owner")
    raw_role = str(unit.get("role", "") or "").strip()
    review_role = normalized_review_role(raw_role)
    checks = _normalized_verification_checks(unit.get("verification_checks"), index)
    commands = _normalized_verification_commands(unit.get("verification_commands"), index)
    if checks is not None:
        if commands:
            raise FanoutContractError(
                f"unit at index {index} declares both verification_commands and verification_checks; "
                "declare verification_checks only — the command list is derived from it"
            )
        commands = [str(check["command"]) for check in checks]
    kind, reproduction_command = _normalized_unit_kind(unit, index)
    return {
        "unit_id": str(unit.get("unit_id", "")).strip(),
        "title": " ".join(str(unit.get("title", "")).split()),
        # '' when undeclared; `reproduction` is the only declared kind.
        "kind": kind,
        "reproduction_command": reproduction_command,
        "owner": canonical_executor_profile(str(owner)) if owner is not None and str(owner).strip() else None,
        "file_scope": sorted(set(file_scope)),
        "depends_on": sorted(set(depends_on)),
        "model": str(unit.get("model", "") or "").strip(),
        "reasoning_effort": str(unit.get("reasoning_effort", "") or "").strip(),
        "role": "review" if review_role is not None else raw_role,
        "review_role": review_role or "",
        # `category` accepts the ULW ulw-* aliases the resolver already
        # normalizes; validate_fanout_units rejects unknown vocabulary so a
        # typo fails the freeze instead of silently routing by role only.
        "category": str(unit.get("category", unit.get("model_category", "")) or "").strip(),
        # The unit's declared `omh_identity_profiles/v1` name: the explicit
        # structured-handoff field for identity routing, resolved at freeze
        # against the caller-read config so each unit's identity stays bound
        # to its own task and never to ambient profile state.
        "identity": str(unit.get("identity", "") or "").strip(),
        "scale": str(unit.get("scale", "") or "").strip(),
        "domain": str(unit.get("domain", "") or "").strip(),
        "depth": str(unit.get("depth", "") or "").strip(),
        # None (key absent) and [] (declared empty) are different answers: absent
        # means "arrange from discovery at dispatch time", [] means "the operator
        # chose the pure prompt". Order is preserved — a sequence is a sequence.
        "skill_sequence": _normalized_skill_sequence(unit.get("skill_sequence"), index),
        # Prose `integration_checks` say what "verified" means; these say how a
        # dispatcher could observe it. An empty answer is the default and means
        # the contract names no command anyone can run for this unit.
        "verification_commands": commands,
        # The structured sibling: per-check tier/safety/edges, or None when the
        # unit declared none (the key is then omitted from the frozen unit).
        "verification_checks": checks,
        "input_representation": list(normalize_input_representation(unit.get("input_representation", "text_only"))),
        "transformation": dict(unit.get("transformation") or {}),
        # How much source text the unit may read and from which ranges; None
        # when undeclared so existing contracts stay byte-identical.
        "input_budget": _normalized_input_budget(unit.get("input_budget"), index),
        # The command prefix the dispatcher runs on the tests that directly
        # import what the unit changed; '' when undeclared.
        "task_linked_test_runner": normalized_task_linked_test_runner(unit.get("task_linked_test_runner"), index),
        # How many times the dispatcher may re-dispatch this unit in its own
        # worktree after observing a declared check fail; 0 when undeclared.
        "max_repair_attempts": normalized_max_repair_attempts(unit, index),
    }


def _budget_int(mapping: Mapping[str, object], key: str, *, index: int, where: str, minimum: int, maximum: int) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise FanoutContractError(f"unit at index {index} {where} {key} must be an integer")
    if value < minimum:
        raise FanoutContractError(f"unit at index {index} {where} {key} must be at least {minimum}")
    if value > maximum:
        raise FanoutContractError(f"unit at index {index} {where} {key} is capped at {maximum}")
    return value


def _normalized_source_range(value: object, index: int, position: int) -> dict[str, object]:
    where = f"input_budget.source_ranges[{position}]"
    if not isinstance(value, Mapping):
        raise FanoutContractError(f"unit at index {index} {where} must be an object")
    unknown = sorted(str(key) for key in value if str(key) not in UNIT_SOURCE_RANGE_KEYS)
    if unknown:
        raise FanoutContractError(
            f"unit at index {index} {where} has unknown keys {unknown}; allowed: {', '.join(UNIT_SOURCE_RANGE_KEYS)}"
        )
    source = " ".join(str(value.get("source", "") or "").split())
    span = " ".join(str(value.get("span", "") or "").split())
    if not source or not span:
        raise FanoutContractError(f"unit at index {index} {where} needs a source and a span")
    if len(source) > MAX_UNIT_SOURCE_RANGE_SOURCE_CHARS or len(span) > MAX_UNIT_SOURCE_RANGE_SPAN_CHARS:
        raise FanoutContractError(f"unit at index {index} {where} source or span is over its length cap")
    normalized: dict[str, object] = {"source": source, "span": span}
    offset = _budget_int(value, "offset", index=index, where=where, minimum=1, maximum=MAX_UNIT_INPUT_BUDGET_CHARS)
    limit = _budget_int(value, "limit", index=index, where=where, minimum=1, maximum=MAX_UNIT_INPUT_BUDGET_CHARS)
    end_line = _budget_int(value, "end_line", index=index, where=where, minimum=1, maximum=MAX_UNIT_INPUT_BUDGET_CHARS)
    estimated = _budget_int(value, "estimated_chars", index=index, where=where, minimum=0, maximum=MAX_UNIT_INPUT_BUDGET_CHARS)
    if end_line is not None and offset is not None and end_line < offset:
        raise FanoutContractError(f"unit at index {index} {where} end_line is before its offset")
    for key, number in (("offset", offset), ("limit", limit), ("end_line", end_line), ("estimated_chars", estimated)):
        if number is not None:
            normalized[key] = number
    digest = str(value.get("digest", "") or "").strip()
    if digest:
        if len(digest) > MAX_UNIT_SOURCE_RANGE_DIGEST_CHARS or not digest.isalnum():
            raise FanoutContractError(f"unit at index {index} {where} digest must be a short alphanumeric id")
        normalized["digest"] = digest
    return normalized


def _normalized_input_budget(value: object, index: int) -> dict[str, object] | None:
    """The per-unit input budget in its frozen shape, or None when undeclared.

    `chars` is the ceiling; `tokens` may accompany it only inside the sanity
    window (never more tokens than characters, never fewer than one token per
    sixteen); `source_ranges` name what the unit reads and may not add up to
    more than the ceiling, or the budget would already be broken at freeze.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise FanoutContractError(f"unit at index {index} input_budget must be an object")
    unknown = sorted(str(key) for key in value if str(key) not in ("chars", "tokens", "source_ranges"))
    if unknown:
        raise FanoutContractError(
            f"unit at index {index} input_budget has unknown keys {unknown}; allowed: chars, tokens, source_ranges"
        )
    chars = _budget_int(value, "chars", index=index, where="input_budget", minimum=1, maximum=MAX_UNIT_INPUT_BUDGET_CHARS)
    if chars is None:
        raise FanoutContractError(f"unit at index {index} input_budget needs chars: the ceiling the unit may read")
    tokens = _budget_int(value, "tokens", index=index, where="input_budget", minimum=1, maximum=MAX_UNIT_INPUT_BUDGET_CHARS)
    if tokens is not None:
        if tokens > chars:
            raise FanoutContractError(
                f"unit at index {index} input_budget declares more tokens ({tokens}) than characters ({chars})"
            )
        if tokens * MAX_CHARS_PER_TOKEN < chars:
            raise FanoutContractError(
                f"unit at index {index} input_budget tokens ({tokens}) are fewer than one per "
                f"{MAX_CHARS_PER_TOKEN} characters of the {chars}-char budget"
            )
    raw_ranges = value.get("source_ranges")
    ranges: list[dict[str, object]] = []
    if raw_ranges is not None:
        if not isinstance(raw_ranges, (list, tuple)):
            raise FanoutContractError(f"unit at index {index} input_budget.source_ranges must be a list")
        if len(raw_ranges) > MAX_UNIT_SOURCE_RANGES:
            raise FanoutContractError(
                f"unit at index {index} input_budget.source_ranges is capped at {MAX_UNIT_SOURCE_RANGES} ranges"
            )
        ranges = [_normalized_source_range(item, index, position) for position, item in enumerate(raw_ranges)]
        total = sum(int(item.get("estimated_chars", 0)) for item in ranges)
        if total > chars:
            raise FanoutContractError(
                f"unit at index {index} input_budget.source_ranges estimate {total} chars, over the {chars}-char budget"
            )
    normalized: dict[str, object] = {
        "schema_version": FANOUT_UNIT_INPUT_BUDGET_SCHEMA_VERSION,
        "chars": chars,
    }
    if tokens is not None:
        normalized["tokens"] = tokens
    normalized["source_ranges"] = ranges
    normalized["claim_boundary"] = FANOUT_UNIT_INPUT_BUDGET_CLAIM_BOUNDARY
    return normalized


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


def _normalized_unit_kind(unit: Mapping[str, object], index: int) -> tuple[str, str]:
    """The unit's declared kind and reproduction command, or ('', '').

    Closed vocabulary: an unknown kind is a freeze-time refusal rather than a
    silently ordinary unit. The command is required on a reproduction unit and
    refused on any other, because on an ordinary unit nothing would run it and
    its presence would read as a hold that does not exist.
    """
    raw_kind = unit.get("kind")
    kind = "" if raw_kind is None else str(raw_kind).strip()
    if kind and kind not in FANOUT_UNIT_KINDS:
        raise FanoutContractError(
            f"unit at index {index} kind {kind!r} is not one of {', '.join(FANOUT_UNIT_KINDS)} (or absent)"
        )
    raw_command = unit.get("reproduction_command")
    if kind != REPRODUCTION_UNIT_KIND:
        if raw_command is not None:
            raise FanoutContractError(
                f"unit at index {index} declares reproduction_command without kind {REPRODUCTION_UNIT_KIND!r}"
            )
        return kind, ""
    if not isinstance(raw_command, str) or not raw_command.strip():
        raise FanoutContractError(
            f"unit at index {index} is a reproduction unit and requires a non-empty reproduction_command"
        )
    command = " ".join(raw_command.split())
    if len(command) > MAX_UNIT_VERIFICATION_COMMAND_CHARS:
        raise FanoutContractError(
            f"unit at index {index} reproduction_command must be at most "
            f"{MAX_UNIT_VERIFICATION_COMMAND_CHARS} chars"
        )
    # Parsed at freeze for the reason verification commands are: the
    # dispatcher runs it through the same argv split with `shell=False`.
    verification_command_argv(command)
    return kind, command


def _normalized_verification_checks(value: object, index: int) -> list[dict[str, object]] | None:
    """The additive per-check metadata sibling of `verification_commands`.

    Absent (or declared empty) returns None so the contract stays
    byte-identical to one frozen before the field existed. Each entry carries
    its command plus the declared tier, safety, dependency edges, and timeout
    with defaults made explicit, so the plan compiler downstream never has to
    guess which fields the operator set.
    """
    if value is None or value == []:
        return None
    if not isinstance(value, (list, tuple)):
        raise FanoutContractError(
            f"unit at index {index} verification_checks must be a list of check objects"
        )
    if len(value) > MAX_UNIT_VERIFICATION_COMMANDS:
        raise FanoutContractError(
            f"unit at index {index} verification_checks must have at most "
            f"{MAX_UNIT_VERIFICATION_COMMANDS} checks"
        )
    checks: list[dict[str, object]] = []
    ids: list[str] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise FanoutContractError(
                f"unit at index {index} verification_checks entries must be objects; got {entry!r}"
            )
        command = _normalized_verification_commands([entry.get("command")], index)[0]
        declared_id = str(entry.get("id") or f"check-{len(checks)}").strip()
        if (
            not _VERIFICATION_CHECK_ID_RE.match(declared_id)
            or len(declared_id) > MAX_UNIT_VERIFICATION_CHECK_ID_CHARS
        ):
            raise FanoutContractError(
                f"unit at index {index} verification_checks ids must match "
                f"{VERIFICATION_CHECK_ID_PATTERN} and be at most "
                f"{MAX_UNIT_VERIFICATION_CHECK_ID_CHARS} chars; got {declared_id!r}"
            )
        if declared_id in ids:
            raise FanoutContractError(
                f"unit at index {index} verification_checks ids must be unique; got {declared_id!r} twice"
            )
        tier = entry.get("tier", "unit")
        if tier not in VERIFICATION_CHECK_TIERS:
            raise FanoutContractError(
                f"unit at index {index} verification_checks tier must be one of "
                f"{', '.join(VERIFICATION_CHECK_TIERS)}; got {tier!r}"
            )
        safety = entry.get("safety", "stateful")
        if safety not in VERIFICATION_CHECK_SAFETIES:
            raise FanoutContractError(
                f"unit at index {index} verification_checks safety must be one of "
                f"{', '.join(VERIFICATION_CHECK_SAFETIES)}; got {safety!r}"
            )
        resource_class = entry.get("resource_class", "local_cpu")
        if not isinstance(resource_class, str) or not is_verification_check_resource_class(resource_class):
            raise FanoutContractError(
                f"unit at index {index} verification_checks resource_class must match "
                f"{VERIFICATION_CHECK_RESOURCE_CLASS_PATTERN}; got {resource_class!r}"
            )
        claim_scope = entry.get(
            "claim_scope", "integrated_verification" if tier == "integration" else "unit_verification"
        )
        if claim_scope not in VERIFICATION_CHECK_CLAIM_SCOPES:
            raise FanoutContractError(
                f"unit at index {index} verification_checks claim_scope must be one of "
                f"{', '.join(VERIFICATION_CHECK_CLAIM_SCOPES)}; got {claim_scope!r}"
            )
        expected_scope = "integrated_verification" if tier == "integration" else "unit_verification"
        if claim_scope != expected_scope:
            raise FanoutContractError(
                f"unit at index {index} verification_checks {tier} tier requires claim_scope "
                f"{expected_scope!r}; got {claim_scope!r}"
            )
        raw_deps = entry.get("depends_on", [])
        if not isinstance(raw_deps, (list, tuple)) or not all(isinstance(dep, str) for dep in raw_deps):
            raise FanoutContractError(
                f"unit at index {index} verification_checks depends_on must be a list of check ids"
            )
        timeout = entry.get("timeout", MAX_UNIT_VERIFICATION_CHECK_TIMEOUT)
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= MAX_UNIT_VERIFICATION_CHECK_TIMEOUT
        ):
            raise FanoutContractError(
                f"unit at index {index} verification_checks timeout must be an integer between 1 and "
                f"{MAX_UNIT_VERIFICATION_CHECK_TIMEOUT}; got {timeout!r}"
            )
        ids.append(declared_id)
        checks.append(
            {
                "command": command,
                "id": declared_id,
                "tier": tier,
                "safety": safety,
                "resource_class": resource_class,
                "claim_scope": claim_scope,
                "depends_on": [str(dep).strip() for dep in raw_deps],
                "timeout": timeout,
            }
        )
    _require_acyclic_check_edges(checks, index)
    return checks


def _require_acyclic_check_edges(checks: list[dict[str, object]], index: int) -> None:
    """Refuse unknown, self, or cyclic `depends_on` references at freeze time."""
    ids = {str(check["id"]): check for check in checks}
    for check in checks:
        for dep in check["depends_on"]:
            if dep not in ids:
                raise FanoutContractError(
                    f"unit at index {index} verification_checks depends_on references unknown check "
                    f"{dep!r}"
                )
            if dep == check["id"]:
                raise FanoutContractError(
                    f"unit at index {index} verification_checks {dep!r} depends on itself"
                )
    parents = {str(check["id"]): [str(dep) for dep in check["depends_on"]] for check in checks}
    if dag_core.layer_of(list(parents), parents, strict=True)[1]:
        raise FanoutContractError(
            f"unit at index {index} verification_checks depends_on forms a cycle"
        )


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
    category_config: Mapping[str, object] | None = None,
    identity_config: Mapping[str, object] | None = None,
    capability_snapshots: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    unit_id = str(unit["unit_id"])
    own_scope = set(str(path) for path in unit.get("file_scope", []))
    executor_target = str(unit.get("owner")) if unit.get("owner") else "choose"
    local_catalog = (local_catalogs or {}).get(executor_target)
    model_route = model_route_for_unit(
        unit, executor_target, local_catalog, category_config, identity_config
    )
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
    review_role = str(unit.get("review_role", "") or "")
    if review_role:
        handoff["review_role"] = review_role
    capability_snapshot = (capability_snapshots or {}).get(executor_target)
    if capability_snapshots is not None and executor_target != "choose":
        handoff["executor_capability_snapshot_policy"] = _FROZEN_CAPABILITY_SNAPSHOT_POLICY
    if isinstance(capability_snapshot, Mapping):
        handoff["executor_capability_snapshot"] = deepcopy(dict(capability_snapshot))
    representations = unit.get("input_representation", [])
    handoff["input_representation"] = deepcopy(representations)
    handoff["executor_modality_decision"] = build_executor_modality_decision(
        input_representation=representations,
        snapshot=capability_snapshot if isinstance(capability_snapshot, Mapping) else None,
        route=model_route if isinstance(model_route, Mapping) else None,
        transformation=unit.get("transformation") if isinstance(unit.get("transformation"), Mapping) else None,
    )
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
    # A declared runner turns the first prose check into the task-linked
    # postcondition the dispatcher observes; absence keeps the contract
    # byte-identical to one frozen before the field existed.
    runner = str(unit.get("task_linked_test_runner") or "")
    if runner:
        contract_unit["task_linked_test_runner"] = runner
        contract_unit["integration_checks"] = [
            task_linked_criterion(runner),
            "no edits outside boundary.file_scope",
        ]
    # A reproduction unit's done-means is the inverse of an edit unit's: its
    # command has to FAIL. Its first prose check says so, which is what the
    # executor's completion criteria are derived from; ordinary units carry no
    # key and stay byte-identical.
    if unit.get("kind"):
        contract_unit["kind"] = str(unit["kind"])
        contract_unit["reproduction_command"] = str(unit["reproduction_command"])
        contract_unit["integration_checks"] = [
            f"`{unit['reproduction_command']}` exits nonzero: it reproduces the reported failure before any fix",
            "no edits outside boundary.file_scope",
        ]
    # Only a declared answer rides the contract; absence keeps existing
    # contracts byte-identical and means "arrange from discovery at dispatch".
    if unit.get("skill_sequence") is not None:
        contract_unit["skill_sequence"] = list(unit["skill_sequence"])
    # Same additive rule: a unit that declared no runnable command carries no
    # key, so contracts frozen before this field stay byte-identical.
    if unit.get("verification_commands"):
        contract_unit["verification_commands"] = list(unit["verification_commands"])
    # And its structured sibling rides only when declared, for the same reason.
    if unit.get("verification_checks"):
        contract_unit["verification_checks"] = [dict(check) for check in unit["verification_checks"]]
    # The input budget rides the frozen unit only when declared, so the
    # executor prompt can state the range and the ceiling for that unit.
    if unit.get("input_budget"):
        contract_unit["input_budget"] = deepcopy(dict(unit["input_budget"]))
    # A repair budget rides only when above zero, so a contract that declares
    # none freezes byte-identically to one frozen before the field existed.
    if unit.get("max_repair_attempts"):
        contract_unit["max_repair_attempts"] = int(unit["max_repair_attempts"])  # type: ignore[call-overload]
    return contract_unit
