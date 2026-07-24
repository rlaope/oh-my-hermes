from __future__ import annotations

from hashlib import sha256
import re
from typing import Mapping, Sequence

from ..ingress import compact_source_metadata
from .fanout_contracts import (
    FANOUT_CLAIM_BOUNDARY,
    FANOUT_CONTRACT_SCHEMA_VERSION,
    FANOUT_FINAL_INTEGRATION_GATE,
    FANOUT_UNIT_OWNERS,
    FanoutContractError,
    PREPARED_NOT_OBSERVED,
)

_UNIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def build_fanout_contract(
    goal: str,
    units: Sequence[Mapping[str, object]],
    *,
    source: str = "generic",
    source_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    normalized_goal = " ".join(goal.split())
    if not normalized_goal:
        raise FanoutContractError("fanout goal is required")
    normalized_units = [_normalized_unit(unit, index) for index, unit in enumerate(units)]
    validate_fanout_units(normalized_units)
    conflict_notes = detect_boundary_overlaps(normalized_units)
    order = merge_order(normalized_units)
    digest = sha256(normalized_goal.encode("utf-8")).hexdigest()
    fanout_id = f"fanout-{digest[:12]}"
    unit_ids = [str(unit["unit_id"]) for unit in normalized_units]
    contract_units = [
        _contract_unit(unit, sibling_scopes=_sibling_scopes(normalized_units, str(unit["unit_id"])), fanout_id=fanout_id)
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
    }


def _sibling_scopes(units: Sequence[Mapping[str, object]], unit_id: str) -> list[str]:
    scopes: set[str] = set()
    for unit in units:
        if str(unit["unit_id"]) == unit_id:
            continue
        scopes.update(str(path) for path in unit.get("file_scope", []))
    return sorted(scopes)


def _contract_unit(unit: Mapping[str, object], *, sibling_scopes: list[str], fanout_id: str) -> dict[str, object]:
    unit_id = str(unit["unit_id"])
    own_scope = set(str(path) for path in unit.get("file_scope", []))
    return {
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
        "handoff": {
            "schema_version": "fanout_unit_handoff/v1",
            "executor_target": str(unit.get("owner")) if unit.get("owner") else "choose",
            "dispatch_policy": "prepare_only",
            "status": PREPARED_NOT_OBSERVED,
            "claim_boundary": (
                "This per-unit handoff is prepared guidance only; record observed evidence on a run named by "
                "run_ref before any dispatch, verification, review, CI, or merge claim."
            ),
        },
        "integration_checks": [
            "unit tests covering the unit's file_scope pass",
            "no edits outside boundary.file_scope",
        ],
        "status": "prepared",
    }
