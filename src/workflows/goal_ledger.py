from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..hashutil import sha256_text
from ..local_store import atomic_write_json, ensure_dir, read_json_object, utc_now
from ..paths import OmhPaths
from ..runtime.artifacts import summarize_delegated_coding_status


GOAL_LEDGER_SCHEMA = "goal_ledger/v1"
GOAL_COMPLETION_GATE_SCHEMA = "goal_completion_gate/v1"
GOAL_CONTINUATION_SCHEMA = "goal_continuation/v1"
GOAL_STATUS_CARD_SCHEMA = "goal_status_card/v1"

GOAL_STATUSES = {"active", "blocked", "failed", "complete"}
CRITERION_STATUSES = {"pending", "satisfied"}
CHECKPOINT_STATUSES = {"pending", "in_progress", "done", "blocked", "failed"}
BLOCKER_STATUSES = {"active", "resolved"}
QUALITY_GATE_STATUSES = {"pending", "passed", "failed", "blocked"}
STORAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
RUNTIME_COMPLETION_ACTIONS = {"report_completion_with_evidence", "report_merge_ready", "report_merged"}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "goal")[:48].strip("-") or "goal"


def _stamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_item_id(prefix: str) -> str:
    return f"{prefix}-{_stamp().lower()}-{secrets.token_hex(3)}"


def new_goal_id(objective: str, now: datetime | None = None) -> str:
    return f"{_stamp(now).lower()}-{_slugify(objective)}-{secrets.token_hex(3)}"


def _storage_id(value: str, kind: str) -> str:
    item = str(value).strip()
    if not STORAGE_ID_RE.fullmatch(item):
        raise ValueError(f"{kind} must match {STORAGE_ID_RE.pattern}")
    if item in {".", ".."} or ".." in item or "/" in item or "\\" in item:
        raise ValueError(f"{kind} must be a storage id, not a path")
    return item


def _goal_dir(paths: OmhPaths, goal_id: str) -> Path:
    safe_goal_id = _storage_id(goal_id, "goal_id")
    root = paths.goals_dir.resolve()
    path = (root / safe_goal_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("goal_id escapes goals directory") from exc
    return path


def goal_ledger_path(paths: OmhPaths, goal_id: str) -> Path:
    return _goal_dir(paths, goal_id) / "goal.json"


def _safe_summary(value: str, *, limit: int = 240) -> str:
    summary = re.sub(r"\s+", " ", value).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "..."


def _objective_summary(objective: str, explicit_summary: str | None) -> str:
    if explicit_summary:
        return _safe_summary(explicit_summary)
    digest = sha256_text(objective)[:12]
    return f"Objective stored by sha256 metadata ({digest})."


def _criteria_objects(criteria: Iterable[str | dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, criterion in enumerate(criteria, start=1):
        if isinstance(criterion, dict):
            summary = _safe_summary(str(criterion.get("summary", "")).strip())
            criterion_id = str(criterion.get("id") or f"AC{index:03d}")
            required = bool(criterion.get("required", True))
        else:
            summary = _safe_summary(str(criterion).strip())
            criterion_id = f"AC{index:03d}"
            required = True
        if not summary:
            raise ValueError(f"acceptance criterion {criterion_id} requires a summary")
        result.append(
            {
                "id": criterion_id,
                "summary": summary,
                "required": required,
                "status": "pending",
                "evidence_refs": [],
            }
        )
    if not result:
        raise ValueError("at least one acceptance criterion is required")
    return result


def _evidence_refs(values: Iterable[str] | None) -> list[str]:
    return [_safe_summary(str(value), limit=320) for value in values or [] if str(value).strip()]


def _linked_runtime_runs(values: Iterable[str] | None) -> list[str]:
    return sorted({_storage_id(str(value), "linked_runtime_run_id") for value in values or [] if str(value).strip()})


def _read_goal(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    data = read_json_object(goal_ledger_path(paths, goal_id))
    if data is None:
        raise FileNotFoundError(goal_ledger_path(paths, goal_id))
    return data


def _write_goal(paths: OmhPaths, goal: dict[str, Any]) -> dict[str, Any]:
    goal["updated_at"] = utc_now()
    atomic_write_json(goal_ledger_path(paths, str(goal["goal_id"])), goal, private=True)
    return goal


def create_goal_ledger(
    paths: OmhPaths,
    objective: str,
    acceptance_criteria: Iterable[str | dict[str, Any]],
    *,
    source: str = "omh",
    goal_id: str | None = None,
    objective_summary: str | None = None,
    linked_runtime_runs: Iterable[str] | None = None,
) -> dict[str, Any]:
    if not objective.strip():
        raise ValueError("objective is required")
    goal_id = _storage_id(goal_id or new_goal_id(objective), "goal_id")
    now = utc_now()
    goal = {
        "schema_version": GOAL_LEDGER_SCHEMA,
        "goal_id": goal_id,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "source": _safe_summary(source, limit=120),
        "objective_storage": "sha256",
        "objective_hash": sha256_text(objective),
        "objective_summary": _objective_summary(objective, objective_summary),
        "acceptance_criteria": _criteria_objects(acceptance_criteria),
        "checkpoints": [],
        "current_checkpoint": None,
        "blockers": [],
        "quality_gates": [],
        "linked_runtime_runs": _linked_runtime_runs(linked_runtime_runs),
    }
    validation = validate_goal_ledger(goal)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    ensure_dir(_goal_dir(paths, goal_id), private=True)
    ensure_dir(_goal_dir(paths, goal_id) / "evidence", private=True)
    atomic_write_json(goal_ledger_path(paths, goal_id), goal, private=True)
    return goal


def read_goal_ledger(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = _read_goal(paths, goal_id)
    validation = validate_goal_ledger(goal)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    return goal


def list_goal_ledgers(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.goals_dir.exists():
        return []
    ledgers: list[dict[str, Any]] = []
    for goal_json in sorted(paths.goals_dir.glob("*/goal.json")):
        data = read_json_object(goal_json)
        if isinstance(data, dict):
            ledgers.append(data)
    return ledgers


def record_goal_checkpoint(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    criteria_refs: Iterable[str] | None = None,
    status: str = "done",
    evidence_refs: Iterable[str] | None = None,
    notes_summary: str = "",
    linked_runtime_run_id: str = "",
) -> dict[str, Any]:
    if status not in CHECKPOINT_STATUSES:
        raise ValueError(f"unsupported checkpoint status: {status}")
    if not summary.strip():
        raise ValueError("checkpoint summary is required")
    goal = read_goal_ledger(paths, goal_id)
    criterion_ids = {str(criterion["id"]) for criterion in goal["acceptance_criteria"]}
    refs = [str(ref).strip() for ref in criteria_refs or [] if str(ref).strip()]
    unknown_refs = [ref for ref in refs if ref not in criterion_ids]
    if unknown_refs:
        raise ValueError(f"unknown acceptance criteria: {', '.join(unknown_refs)}")
    evidence = _evidence_refs(evidence_refs)
    linked_runtime_ref = (
        _storage_id(linked_runtime_run_id, "linked_runtime_run_id") if linked_runtime_run_id.strip() else ""
    )
    checkpoint = {
        "checkpoint_id": _new_item_id("checkpoint"),
        "created_at": utc_now(),
        "status": status,
        "summary": _safe_summary(summary),
        "criteria_refs": refs,
        "evidence_refs": evidence,
        "notes_summary": _safe_summary(notes_summary) if notes_summary.strip() else "",
        "linked_runtime_run_id": linked_runtime_ref,
    }
    goal["checkpoints"].append(checkpoint)
    goal["current_checkpoint"] = checkpoint["checkpoint_id"]
    if status == "done":
        if refs and not evidence:
            raise ValueError("done checkpoints that satisfy criteria require evidence_refs")
        for criterion in goal["acceptance_criteria"]:
            if criterion["id"] in refs:
                criterion["status"] = "satisfied"
                criterion["evidence_refs"] = sorted(set(criterion["evidence_refs"] + evidence))
    if linked_runtime_ref:
        runs = set(goal.get("linked_runtime_runs", []))
        runs.add(linked_runtime_ref)
        goal["linked_runtime_runs"] = sorted(runs)
    return _write_goal(paths, goal)


def record_goal_blocker(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    attempted_recovery: str = "",
    missing_authority: str = "",
    evidence_refs: Iterable[str] | None = None,
    mark_goal_blocked: bool = False,
) -> dict[str, Any]:
    if not summary.strip():
        raise ValueError("blocker summary is required")
    goal = read_goal_ledger(paths, goal_id)
    goal["blockers"].append(
        {
            "blocker_id": _new_item_id("blocker"),
            "created_at": utc_now(),
            "status": "active",
            "summary": _safe_summary(summary),
            "attempted_recovery": _safe_summary(attempted_recovery) if attempted_recovery.strip() else "",
            "missing_authority": _safe_summary(missing_authority) if missing_authority.strip() else "",
            "evidence_refs": _evidence_refs(evidence_refs),
        }
    )
    if mark_goal_blocked:
        goal["status"] = "blocked"
    return _write_goal(paths, goal)


def record_goal_quality_gate(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    status: str = "passed",
    evidence_refs: Iterable[str] | None = None,
) -> dict[str, Any]:
    if status not in QUALITY_GATE_STATUSES:
        raise ValueError(f"unsupported quality gate status: {status}")
    if not summary.strip():
        raise ValueError("quality gate summary is required")
    goal = read_goal_ledger(paths, goal_id)
    goal["quality_gates"].append(
        {
            "quality_gate_id": _new_item_id("quality-gate"),
            "created_at": utc_now(),
            "status": status,
            "summary": _safe_summary(summary),
            "evidence_refs": _evidence_refs(evidence_refs),
        }
    )
    return _write_goal(paths, goal)


def validate_goal_ledger(goal: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if goal.get("schema_version") != GOAL_LEDGER_SCHEMA:
        errors.append("schema_version must be goal_ledger/v1")
    if "objective" in goal:
        errors.append("raw objective field is not allowed")
    if not str(goal.get("goal_id", "")).strip():
        errors.append("goal_id is required")
    else:
        try:
            _storage_id(str(goal.get("goal_id", "")), "goal_id")
        except ValueError as exc:
            errors.append(str(exc))
    if goal.get("status") not in GOAL_STATUSES:
        errors.append("status must be active, blocked, failed, or complete")
    objective_hash = str(goal.get("objective_hash", ""))
    if len(objective_hash) != 64 or not re.fullmatch(r"[0-9a-f]+", objective_hash):
        errors.append("objective_hash must be a sha256 hex digest")
    if goal.get("objective_storage") != "sha256":
        errors.append("objective_storage must be sha256")
    _validate_criteria(goal.get("acceptance_criteria"), errors)
    _validate_checkpoints(goal.get("checkpoints"), errors)
    _validate_blockers(goal.get("blockers"), errors)
    _validate_quality_gates(goal.get("quality_gates"), errors)
    if not isinstance(goal.get("linked_runtime_runs"), list):
        errors.append("linked_runtime_runs must be a list")
    else:
        for index, run_id in enumerate(goal.get("linked_runtime_runs", []), start=1):
            try:
                _storage_id(str(run_id), "linked_runtime_run_id")
            except ValueError as exc:
                errors.append(f"linked_runtime_runs[{index}]: {exc}")
    return {"ok": not errors, "errors": errors}


def build_goal_completion_gate(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = read_goal_ledger(paths, goal_id)
    missing_required = [
        {
            "id": criterion["id"],
            "summary": criterion["summary"],
        }
        for criterion in goal["acceptance_criteria"]
        if criterion["required"] and (criterion["status"] != "satisfied" or not criterion["evidence_refs"])
    ]
    active_blockers = [
        {
            "id": blocker["blocker_id"],
            "summary": blocker["summary"],
        }
        for blocker in goal["blockers"]
        if blocker.get("status") == "active"
    ]
    runtime_checks = [_linked_runtime_check(paths, run_id) for run_id in goal.get("linked_runtime_runs", [])]
    runtime_gaps = [check for check in runtime_checks if not check["satisfied"]]
    status_gaps = []
    if goal["status"] == "blocked":
        status_gaps.append("goal status is blocked")
    if goal["status"] == "failed":
        status_gaps.append("goal status is failed")
    ready = not missing_required and not active_blockers and not runtime_gaps and not status_gaps
    return {
        "schema_version": GOAL_COMPLETION_GATE_SCHEMA,
        "goal_id": goal_id,
        "goal_status": goal["status"],
        "ready": ready,
        "summary": _completion_gate_summary(
            missing_required=missing_required,
            active_blockers=active_blockers,
            runtime_gaps=runtime_gaps,
            status_gaps=status_gaps,
        ),
        "missing_required_criteria": missing_required,
        "active_blockers": active_blockers,
        "linked_runtime_checks": runtime_checks,
        "next_action": _completion_next_action(
            missing_required=missing_required,
            active_blockers=active_blockers,
            runtime_gaps=runtime_gaps,
            status_gaps=status_gaps,
        ),
    }


def complete_goal_ledger(
    paths: OmhPaths,
    goal_id: str,
    *,
    evidence_refs: Iterable[str] | None = None,
) -> dict[str, Any]:
    gate = build_goal_completion_gate(paths, goal_id)
    goal = read_goal_ledger(paths, goal_id)
    if not gate["ready"]:
        return {"completed": False, "goal": goal, "completion_gate": gate}
    evidence = _evidence_refs(evidence_refs)
    if not evidence:
        gate = {
            **gate,
            "ready": False,
            "summary": "Completion requires final evidence_refs.",
            "next_action": "record_completion",
        }
        return {"completed": False, "goal": goal, "completion_gate": gate}
    if goal["status"] != "complete":
        goal["status"] = "complete"
        goal["quality_gates"].append(
            {
                "quality_gate_id": _new_item_id("quality-gate"),
                "created_at": utc_now(),
                "status": "passed",
                "summary": "Completion gate passed.",
                "evidence_refs": evidence,
            }
        )
        goal = _write_goal(paths, goal)
    return {"completed": True, "goal": goal, "completion_gate": build_goal_completion_gate(paths, goal_id)}


def build_goal_continuation(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = read_goal_ledger(paths, goal_id)
    status_card = build_goal_status_card(paths, goal_id)
    actions = _allowed_goal_actions(status_card["completion_gate"])
    return {
        "schema_version": GOAL_CONTINUATION_SCHEMA,
        "goal_id": goal_id,
        "goal_status": goal["status"],
        "objective_summary": goal["objective_summary"],
        "next_action": status_card["next_action"],
        "actions": actions,
        "safe_copy": status_card["safe_copy"],
        "status_card": status_card,
        "action_plan": _goal_action_plan(goal_id, actions, status_card),
    }


def build_goal_status_card(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = read_goal_ledger(paths, goal_id)
    gate = build_goal_completion_gate(paths, goal_id)
    progress = _goal_progress(goal)
    return {
        "schema_version": GOAL_STATUS_CARD_SCHEMA,
        "goal_id": goal_id,
        "goal_status": goal["status"],
        "objective_summary": goal["objective_summary"],
        "progress": progress,
        "missing_criteria": gate["missing_required_criteria"],
        "active_blockers": gate["active_blockers"],
        "linked_runtime_checks": gate["linked_runtime_checks"],
        "next_action": gate["next_action"],
        "allowed_actions": _allowed_goal_actions(gate),
        "safe_copy": _goal_safe_copy(goal, gate, progress),
        "completion_gate": gate,
    }


def _linked_runtime_check(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    run_id = _storage_id(run_id, "linked_runtime_run_id")
    return _goal_runtime_evidence_check(run_id, _delegated_runtime_status(paths, run_id))


def _delegated_runtime_status(paths: OmhPaths, run_id: str) -> dict[str, Any] | None:
    try:
        return summarize_delegated_coding_status(paths, run_id)
    except FileNotFoundError:
        return None


def _goal_runtime_evidence_check(run_id: str, status: dict[str, Any] | None) -> dict[str, Any]:
    if status is None:
        return {
            "schema_version": "goal_runtime_evidence_check/v1",
            "run_id": run_id,
            "satisfied": False,
            "summary": "Linked runtime run was not found.",
            "next_action": "record_runtime_evidence",
        }
    next_action = str(status.get("next_action", "unknown"))
    satisfied = next_action in RUNTIME_COMPLETION_ACTIONS
    return {
        "schema_version": "goal_runtime_evidence_check/v1",
        "run_id": run_id,
        "satisfied": satisfied,
        "summary": str(status.get("safe_summary") or f"Runtime next action is {next_action}."),
        "next_action": next_action,
    }


def _completion_gate_summary(
    *,
    missing_required: list[dict[str, Any]],
    active_blockers: list[dict[str, Any]],
    runtime_gaps: list[dict[str, Any]],
    status_gaps: list[str],
) -> str:
    if not missing_required and not active_blockers and not runtime_gaps and not status_gaps:
        return "Goal is ready for completion."
    parts = []
    if missing_required:
        parts.append(f"{len(missing_required)} required acceptance criteria remain pending")
    if active_blockers:
        parts.append(f"{len(active_blockers)} active blockers remain")
    if runtime_gaps:
        parts.append(f"{len(runtime_gaps)} linked runtime runs still need observed evidence")
    if status_gaps:
        parts.append("; ".join(status_gaps))
    return "; ".join(parts) + "."


def _completion_next_action(
    *,
    missing_required: list[dict[str, Any]],
    active_blockers: list[dict[str, Any]],
    runtime_gaps: list[dict[str, Any]],
    status_gaps: list[str],
) -> str:
    if active_blockers or status_gaps:
        return "record_blocker"
    if missing_required:
        return "record_checkpoint"
    if runtime_gaps:
        return "show_status"
    return "record_completion"


def _goal_progress(goal: dict[str, Any]) -> dict[str, Any]:
    criteria = goal["acceptance_criteria"]
    required = [criterion for criterion in criteria if criterion["required"]]
    satisfied = [criterion for criterion in criteria if criterion["status"] == "satisfied"]
    required_satisfied = [criterion for criterion in required if criterion["status"] == "satisfied"]
    active_blockers = [blocker for blocker in goal["blockers"] if blocker.get("status") == "active"]
    percent = 100 if not required else int((len(required_satisfied) / len(required)) * 100)
    return {
        "criteria_total": len(criteria),
        "criteria_satisfied": len(satisfied),
        "required_total": len(required),
        "required_satisfied": len(required_satisfied),
        "active_blockers": len(active_blockers),
        "percent_required_satisfied": percent,
    }


def _allowed_goal_actions(gate: dict[str, Any]) -> list[str]:
    actions = ["continue_goal", "show_status"]
    if gate["missing_required_criteria"]:
        actions.append("record_checkpoint")
    actions.append("record_blocker")
    if gate["ready"]:
        actions.append("record_completion")
    return actions


def _goal_safe_copy(goal: dict[str, Any], gate: dict[str, Any], progress: dict[str, Any]) -> dict[str, str]:
    if gate["ready"]:
        next_step = "Record completion with the final verification evidence."
    elif gate["active_blockers"] or goal["status"] == "blocked":
        next_step = "Resolve or update the active blocker before claiming completion."
    elif gate["missing_required_criteria"]:
        ids = ", ".join(item["id"] for item in gate["missing_required_criteria"])
        next_step = f"Record a checkpoint for the missing acceptance criteria: {ids}."
    elif gate["linked_runtime_checks"]:
        next_step = "Observe the explicitly linked runtime run before claiming completion."
    else:
        next_step = "Continue the goal and record fresh evidence."
    return {
        "headline": f"Goal {goal['goal_id']} is {goal['status']}.",
        "progress": f"{progress['required_satisfied']}/{progress['required_total']} required criteria satisfied.",
        "next_step": next_step,
    }


def _goal_action_plan(goal_id: str, actions: list[str], status_card: dict[str, Any]) -> list[dict[str, str]]:
    commands = {
        "continue_goal": f"omh goal continue --goal {goal_id}",
        "show_status": f"omh goal status --goal {goal_id}",
        "record_checkpoint": f"omh goal checkpoint --goal {goal_id} --summary \"<summary>\" --criterion <AC-id> --evidence-ref <evidence>",
        "record_blocker": f"omh goal blocker --goal {goal_id} --summary \"<blocker>\" --evidence-ref <evidence>",
        "record_completion": f"omh goal complete --goal {goal_id} --evidence-ref <evidence>",
    }
    descriptions = {
        "continue_goal": status_card["safe_copy"]["next_step"],
        "show_status": "Show the current goal card without changing state.",
        "record_checkpoint": "Record work evidence and satisfy one or more acceptance criteria.",
        "record_blocker": "Record a blocker when progress cannot safely continue.",
        "record_completion": "Mark the goal complete only when the completion gate is ready.",
    }
    return [{"action": action, "command": commands[action], "summary": descriptions[action]} for action in actions]


def _validate_criteria(criteria: Any, errors: list[str]) -> None:
    if not isinstance(criteria, list) or not criteria:
        errors.append("acceptance_criteria must be a non-empty list")
        return
    seen: set[str] = set()
    for index, criterion in enumerate(criteria, start=1):
        if not isinstance(criterion, dict):
            errors.append(f"acceptance_criteria[{index}] must be an object")
            continue
        criterion_id = str(criterion.get("id", "")).strip()
        if not criterion_id:
            errors.append(f"acceptance_criteria[{index}].id is required")
        if criterion_id in seen:
            errors.append(f"duplicate acceptance criterion id: {criterion_id}")
        seen.add(criterion_id)
        if not str(criterion.get("summary", "")).strip():
            errors.append(f"acceptance_criteria[{index}].summary is required")
        if not isinstance(criterion.get("required"), bool):
            errors.append(f"acceptance_criteria[{index}].required must be boolean")
        if criterion.get("status") not in CRITERION_STATUSES:
            errors.append(f"acceptance_criteria[{index}].status is invalid")
        if not isinstance(criterion.get("evidence_refs"), list):
            errors.append(f"acceptance_criteria[{index}].evidence_refs must be a list")


def _validate_checkpoints(checkpoints: Any, errors: list[str]) -> None:
    if not isinstance(checkpoints, list):
        errors.append("checkpoints must be a list")
        return
    for index, checkpoint in enumerate(checkpoints, start=1):
        if not isinstance(checkpoint, dict):
            errors.append(f"checkpoints[{index}] must be an object")
            continue
        if checkpoint.get("status") not in CHECKPOINT_STATUSES:
            errors.append(f"checkpoints[{index}].status is invalid")
        if not str(checkpoint.get("summary", "")).strip():
            errors.append(f"checkpoints[{index}].summary is required")
        if not isinstance(checkpoint.get("criteria_refs"), list):
            errors.append(f"checkpoints[{index}].criteria_refs must be a list")
        if not isinstance(checkpoint.get("evidence_refs"), list):
            errors.append(f"checkpoints[{index}].evidence_refs must be a list")


def _validate_blockers(blockers: Any, errors: list[str]) -> None:
    if not isinstance(blockers, list):
        errors.append("blockers must be a list")
        return
    for index, blocker in enumerate(blockers, start=1):
        if not isinstance(blocker, dict):
            errors.append(f"blockers[{index}] must be an object")
            continue
        if blocker.get("status") not in BLOCKER_STATUSES:
            errors.append(f"blockers[{index}].status is invalid")
        if not str(blocker.get("summary", "")).strip():
            errors.append(f"blockers[{index}].summary is required")
        if not isinstance(blocker.get("evidence_refs"), list):
            errors.append(f"blockers[{index}].evidence_refs must be a list")


def _validate_quality_gates(quality_gates: Any, errors: list[str]) -> None:
    if not isinstance(quality_gates, list):
        errors.append("quality_gates must be a list")
        return
    for index, gate in enumerate(quality_gates, start=1):
        if not isinstance(gate, dict):
            errors.append(f"quality_gates[{index}] must be an object")
            continue
        if gate.get("status") not in QUALITY_GATE_STATUSES:
            errors.append(f"quality_gates[{index}].status is invalid")
        if not str(gate.get("summary", "")).strip():
            errors.append(f"quality_gates[{index}].summary is required")
        if not isinstance(gate.get("evidence_refs"), list):
            errors.append(f"quality_gates[{index}].evidence_refs must be a list")
