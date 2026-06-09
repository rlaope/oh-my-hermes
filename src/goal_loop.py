from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .goal_ledger import build_goal_completion_gate, read_goal_ledger
from .hashutil import sha256_text
from .local_store import atomic_write_json, ensure_dir, read_json_object, utc_now
from .paths import OmhPaths


LOOP_CYCLE_SCHEMA = "loop_cycle/v1"
LOOP_STATUS_CARD_SCHEMA = "loop_status_card/v1"
LOOP_RUNTIME_SCHEMA = "loop_runtime/v1"
LOOP_QUEUE_ITEM_SCHEMA = "loop_queue_item/v1"

LOOP_PHASES = {
    "interview",
    "research",
    "plan",
    "handoff",
    "execution",
    "feedback",
    "waiting",
    "blocked",
    "complete",
}
WAIT_REASONS = {
    "none",
    "waiting_external_observation",
    "permission_required",
    "context_exhausted",
    "budget_exhausted",
}
PERMISSION_PROFILES = ("observe_only", "handoff_only", "execute_with_gates", "full_loop", "custom")
LOOP_ACTIONS = (
    "research",
    "planning",
    "ultragoal_creation",
    "executor_handoff",
    "executor_dispatch",
    "repo_edit",
    "pr_creation",
    "pr_revision",
    "review_fix_loop",
    "ci_fix_loop",
    "release_note_work",
    "external_posting_prep",
    "external_posting",
    "merge",
)
LOOP_CONTROL_ACTIONS = (
    "request_permission",
    "wait_for_external_observation",
    "checkpoint_resume",
    "show_loop_status",
)
LOOP_QUEUE_STATUSES = (
    "prepared_not_observed",
    "blocked_by_permission",
    "blocked_by_wait",
    "observed",
)
STORAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

_PROFILE_ALLOWED_ACTIONS: dict[str, set[str]] = {
    "observe_only": {"research", "planning"},
    "handoff_only": {"research", "planning", "ultragoal_creation", "executor_handoff", "external_posting_prep"},
    "execute_with_gates": {
        "research",
        "planning",
        "ultragoal_creation",
        "executor_handoff",
        "executor_dispatch",
        "repo_edit",
        "pr_creation",
        "pr_revision",
        "review_fix_loop",
        "ci_fix_loop",
        "release_note_work",
        "external_posting_prep",
    },
    "full_loop": {
        "research",
        "planning",
        "ultragoal_creation",
        "executor_handoff",
        "executor_dispatch",
        "repo_edit",
        "pr_creation",
        "pr_revision",
        "review_fix_loop",
        "ci_fix_loop",
        "release_note_work",
        "external_posting_prep",
        "merge",
    },
    "custom": set(),
}


def create_loop_cycle(
    paths: OmhPaths,
    *,
    goal_summary: str,
    goal_reframe: str,
    success_criteria: Iterable[str],
    permission_profile: str = "handoff_only",
    allowed_executors: Iterable[str] | None = None,
    allow_actions: Iterable[str] | None = None,
    forbid_actions: Iterable[str] | None = None,
    linked_goal_id: str = "",
    source: str = "omh",
    loop_id: str | None = None,
) -> dict[str, Any]:
    if not goal_summary.strip():
        raise ValueError("goal summary is required")
    if not goal_reframe.strip():
        raise ValueError("goal reframe is required")
    criteria = _criteria_objects(success_criteria)
    loop_id = _storage_id(loop_id or new_loop_id(goal_summary), "loop_id")
    if linked_goal_id:
        read_goal_ledger(paths, linked_goal_id)
    now = utc_now()
    cycle = {
        "schema_version": LOOP_CYCLE_SCHEMA,
        "loop_id": loop_id,
        "created_at": now,
        "updated_at": now,
        "source": _safe_summary(source, limit=120),
        "phase": "interview",
        "wait_reason": "none",
        "goal": {
            "summary": _safe_summary(goal_summary),
            "summary_hash": sha256_text(goal_summary),
            "reframe": _safe_summary(goal_reframe, limit=360),
            "reframe_hash": sha256_text(goal_reframe),
        },
        "success_criteria": criteria,
        "authority_envelope": build_authority_envelope(
            permission_profile=permission_profile,
            allowed_executors=allowed_executors,
            allow_actions=allow_actions,
            forbid_actions=forbid_actions,
        ),
        "feedback_gate": _feedback_gate(),
        "linked_goal_id": _storage_id(linked_goal_id, "linked_goal_id") if linked_goal_id else "",
        "cycles": [],
        "runtime": _runtime_state(),
        "next_action": "continue_loop",
        "completion_claim_allowed": False,
        "claim_boundary": _claim_boundary(),
    }
    _normalize_permission_state(cycle)
    validation = validate_loop_cycle(cycle)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    ensure_dir(_loop_dir(paths, loop_id), private=True)
    atomic_write_json(loop_cycle_path(paths, loop_id), cycle, private=True)
    return cycle


def read_loop_cycle(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    data = read_json_object(loop_cycle_path(paths, loop_id))
    if data is None:
        raise FileNotFoundError(loop_cycle_path(paths, loop_id))
    validation = validate_loop_cycle(data)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    return data


def list_loop_cycles(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.loops_dir.exists():
        return []
    cycles: list[dict[str, Any]] = []
    for loop_json in sorted(paths.loops_dir.glob("*/cycle.json")):
        data = read_json_object(loop_json)
        if isinstance(data, dict):
            cycles.append(data)
    return cycles


def record_loop_feedback(
    paths: OmhPaths,
    loop_id: str,
    *,
    observed_artifacts: Iterable[str] | None = None,
    internal_gap: str = "",
    external_wait: str = "",
    context_exhausted: bool = False,
    budget_exhausted: bool = False,
) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    artifacts = [_safe_summary(value, limit=320) for value in observed_artifacts or [] if str(value).strip()]
    feedback_gate = _feedback_gate(
        observed_artifacts=artifacts,
        internal_gap=internal_gap,
        external_wait=external_wait,
    )
    if external_wait.strip():
        phase = "waiting"
        wait_reason = "waiting_external_observation"
        next_action = "record_external_wait"
    elif context_exhausted:
        phase = "waiting"
        wait_reason = "context_exhausted"
        next_action = "record_checkpoint"
    elif budget_exhausted:
        phase = "waiting"
        wait_reason = "budget_exhausted"
        next_action = "record_checkpoint"
    elif feedback_gate["clear"]:
        phase = "research"
        wait_reason = "none"
        next_action = "continue_loop"
    else:
        phase = "feedback"
        wait_reason = "none"
        next_action = "record_feedback"
    cycle["phase"] = phase
    cycle["wait_reason"] = wait_reason
    cycle["feedback_gate"] = feedback_gate
    cycle["next_action"] = next_action
    cycle["cycles"].append(
        {
            "cycle_id": _new_item_id("cycle"),
            "created_at": utc_now(),
            "phase": phase,
            "wait_reason": wait_reason,
            "observed_artifacts": artifacts,
            "internal_actionable_gap": _safe_summary(internal_gap) if internal_gap.strip() else "",
            "external_wait": _safe_summary(external_wait) if external_wait.strip() else "",
        }
    )
    return _write_loop(paths, cycle)


def update_loop_permission(
    paths: OmhPaths,
    loop_id: str,
    *,
    allow_actions: Iterable[str] | None = None,
    forbid_actions: Iterable[str] | None = None,
    allowed_executors: Iterable[str] | None = None,
) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    current = _dict_value(cycle, "authority_envelope")
    existing_allowed = _string_set(current.get("allowed_actions", []))
    existing_forbidden = _string_set(current.get("forbidden_actions", []))
    requested_allow = _valid_actions(allow_actions or [])
    requested_forbid = _valid_actions(forbid_actions or [])
    forbidden = sorted(existing_forbidden | requested_forbid)
    allowed = sorted((existing_allowed | requested_allow) - set(forbidden))
    existing_executors = _string_set(current.get("allowed_executors", []))
    requested_executors = _safe_list(allowed_executors or [], limit=120)
    cycle["authority_envelope"] = build_authority_envelope(
        permission_profile="custom",
        allowed_executors=sorted(existing_executors | set(requested_executors)),
        allow_actions=allowed,
        forbid_actions=forbidden,
    )
    _normalize_permission_state(cycle)
    return _write_loop(paths, cycle)


def tick_loop_runtime(
    paths: OmhPaths,
    loop_id: str,
    *,
    trigger: str = "manual",
    cadence: str = "",
    worktree_base: str = "",
    worktree_branch: str = "",
    subagent_role: str = "",
    connector: str = "",
    connector_action: str = "",
    note: str = "",
) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    envelope = _dict_value(cycle, "authority_envelope")
    plan = _next_runtime_plan(cycle, envelope)
    queue_item = _runtime_queue_item(
        cycle,
        envelope,
        plan,
        trigger=trigger,
        cadence=cadence,
        worktree_base=worktree_base,
        worktree_branch=worktree_branch,
        subagent_role=subagent_role,
        connector=connector,
        connector_action=connector_action,
        note=note,
    )
    runtime = _runtime_state(cycle.get("runtime"))
    runtime["heartbeat_count"] = int(runtime.get("heartbeat_count", 0)) + 1
    runtime["last_tick_at"] = queue_item["created_at"]
    runtime["last_trigger"] = queue_item["trigger"]
    runtime["last_planned_action"] = queue_item["planned_action"]
    runtime["last_queue_id"] = queue_item["queue_id"]
    runtime.setdefault("queue", []).append(queue_item)
    cycle["runtime"] = runtime
    if queue_item["status"] == "prepared_not_observed":
        cycle["phase"] = str(plan["phase"])
        cycle["wait_reason"] = "none"
        cycle["next_action"] = "observe_runtime_queue"
    else:
        cycle["next_action"] = str(plan["next_action"])
    return _write_loop(paths, cycle)


def build_loop_status_card(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    envelope = _dict_value(cycle, "authority_envelope")
    linked_goal_id = str(cycle.get("linked_goal_id", ""))
    linked_gate: dict[str, Any] | None = None
    if linked_goal_id:
        linked_gate = build_goal_completion_gate(paths, linked_goal_id)
    card = {
        "schema_version": LOOP_STATUS_CARD_SCHEMA,
        "loop_id": cycle["loop_id"],
        "phase": cycle["phase"],
        "wait_reason": cycle["wait_reason"],
        "permission_profile": envelope.get("permission_profile", "custom"),
        "authority_summary": _authority_summary(envelope),
        "allowed_actions": list(envelope.get("allowed_actions", [])),
        "blocked_actions": list(envelope.get("blocked_actions", [])),
        "approval_required_for": list(envelope.get("blocked_actions", [])),
        "allowed_executors": list(envelope.get("allowed_executors", [])),
        "feedback_gate": cycle.get("feedback_gate", _feedback_gate()),
        "runtime_summary": _runtime_summary(cycle),
        "linked_goal_completion": linked_gate or {"observed": False, "reason": "no linked goal ledger"},
        "next_action": _next_action(cycle),
        "safe_copy": _safe_status_copy(cycle, envelope),
        "completion_claim_allowed": _completion_claim_allowed(linked_gate),
        "claim_boundary": _claim_boundary(),
    }
    return card


def build_authority_envelope(
    *,
    permission_profile: str,
    allowed_executors: Iterable[str] | None = None,
    allow_actions: Iterable[str] | None = None,
    forbid_actions: Iterable[str] | None = None,
) -> dict[str, Any]:
    if permission_profile not in PERMISSION_PROFILES:
        raise ValueError(f"unsupported permission profile: {permission_profile}")
    explicitly_forbidden = _valid_actions(forbid_actions or [])
    allowed = set(_PROFILE_ALLOWED_ACTIONS[permission_profile])
    allowed.update(_valid_actions(allow_actions or []))
    allowed.difference_update(explicitly_forbidden)
    blocked = sorted(set(LOOP_ACTIONS) - allowed)
    executors = _safe_list(allowed_executors or [], limit=120)
    return {
        "permission_profile": permission_profile,
        "allowed_actions": sorted(allowed),
        "blocked_actions": blocked,
        "approval_checkpoints": blocked,
        "budget_limits": {
            "token_budget": "checkpoint_when_exhausted",
            "time_budget": "not_set",
            "external_spend": "not_allowed",
        },
        "forbidden_actions": sorted(explicitly_forbidden),
        "allowed_executors": executors,
        "approval_policy": "ask_when_exceeds_envelope",
        "resume_policy": "checkpoint_on_context_or_token_exhaustion",
        "merge_authority": "granted" if "merge" in allowed else "disabled",
        "external_action_authority": "publish_allowed" if "external_posting" in allowed else "prepare_only",
    }


def validate_loop_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if cycle.get("schema_version") != LOOP_CYCLE_SCHEMA:
        errors.append(f"schema_version must be {LOOP_CYCLE_SCHEMA}")
    loop_id = str(cycle.get("loop_id", ""))
    if not STORAGE_ID_RE.fullmatch(loop_id) or "/" in loop_id or "\\" in loop_id or ".." in loop_id:
        errors.append("loop_id must be a storage id")
    if cycle.get("phase") not in LOOP_PHASES:
        errors.append("phase is unsupported")
    if cycle.get("wait_reason") not in WAIT_REASONS:
        errors.append("wait_reason is unsupported")
    goal = cycle.get("goal")
    if not isinstance(goal, dict) or not str(goal.get("summary", "")).strip() or "raw_north_star" in goal:
        errors.append("goal summary metadata is required and raw_north_star is not allowed")
    criteria = cycle.get("success_criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("at least one success criterion is required")
    envelope = cycle.get("authority_envelope")
    if not isinstance(envelope, dict):
        errors.append("authority_envelope is required")
    else:
        profile = envelope.get("permission_profile")
        allowed_actions = envelope.get("allowed_actions")
        blocked_actions = envelope.get("blocked_actions")
        if profile not in PERMISSION_PROFILES:
            errors.append("authority_envelope.permission_profile is unsupported")
        if not isinstance(allowed_actions, list) or not all(action in LOOP_ACTIONS for action in allowed_actions):
            errors.append("authority_envelope.allowed_actions is invalid")
        if not isinstance(blocked_actions, list) or not all(action in LOOP_ACTIONS for action in blocked_actions):
            errors.append("authority_envelope.blocked_actions is invalid")
        approval_checkpoints = envelope.get("approval_checkpoints")
        forbidden_actions = envelope.get("forbidden_actions")
        budget_limits = envelope.get("budget_limits")
        if not isinstance(approval_checkpoints, list) or not all(action in LOOP_ACTIONS for action in approval_checkpoints):
            errors.append("authority_envelope.approval_checkpoints is invalid")
        if not isinstance(forbidden_actions, list) or not all(action in LOOP_ACTIONS for action in forbidden_actions):
            errors.append("authority_envelope.forbidden_actions is invalid")
        if not isinstance(budget_limits, dict):
            errors.append("authority_envelope.budget_limits is required")
    runtime = cycle.get("runtime")
    if runtime is not None:
        errors.extend(_validate_runtime(runtime))
    if cycle.get("completion_claim_allowed") is not False:
        errors.append("loop_cycle cannot directly allow goal completion claims")
    return {"ok": not errors, "errors": errors}


def new_loop_id(goal_summary: str, now: datetime | None = None) -> str:
    return f"{_stamp(now).lower()}-{_slugify(goal_summary)}-{secrets.token_hex(3)}"


def loop_cycle_path(paths: OmhPaths, loop_id: str) -> Path:
    return _loop_dir(paths, loop_id) / "cycle.json"


def _write_loop(paths: OmhPaths, cycle: dict[str, Any]) -> dict[str, Any]:
    cycle["updated_at"] = utc_now()
    validation = validate_loop_cycle(cycle)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    atomic_write_json(loop_cycle_path(paths, str(cycle["loop_id"])), cycle, private=True)
    return cycle


def _loop_dir(paths: OmhPaths, loop_id: str) -> Path:
    safe_loop_id = _storage_id(loop_id, "loop_id")
    root = paths.loops_dir.resolve()
    path = (root / safe_loop_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("loop_id escapes loops directory") from exc
    return path


def _storage_id(value: str, kind: str) -> str:
    item = str(value).strip()
    if not STORAGE_ID_RE.fullmatch(item):
        raise ValueError(f"{kind} must match {STORAGE_ID_RE.pattern}")
    if item in {".", ".."} or ".." in item or "/" in item or "\\" in item:
        raise ValueError(f"{kind} must be a storage id, not a path")
    return item


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "loop")[:48].strip("-") or "loop"


def _stamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_item_id(prefix: str) -> str:
    return f"{prefix}-{_stamp().lower()}-{secrets.token_hex(3)}"


def _safe_summary(value: str, *, limit: int = 240) -> str:
    summary = re.sub(r"\s+", " ", str(value)).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "..."


def _safe_list(values: Iterable[str], *, limit: int = 240) -> list[str]:
    return sorted({_safe_summary(str(value), limit=limit) for value in values if str(value).strip()})


def _string_set(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if str(value).strip()}


def _valid_actions(values: Iterable[str]) -> set[str]:
    actions = {str(value).strip() for value in values if str(value).strip()}
    unknown = sorted(actions - set(LOOP_ACTIONS))
    if unknown:
        raise ValueError(f"unsupported loop action(s): {', '.join(unknown)}")
    return actions


def _criteria_objects(criteria: Iterable[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, criterion in enumerate(criteria, start=1):
        summary = _safe_summary(str(criterion).strip())
        if not summary:
            raise ValueError(f"success criterion LC{index:03d} requires a summary")
        result.append({"id": f"LC{index:03d}", "summary": summary, "status": "pending", "evidence_refs": []})
    if not result:
        raise ValueError("at least one success criterion is required")
    return result


def _feedback_gate(
    *,
    observed_artifacts: Iterable[str] | None = None,
    internal_gap: str = "",
    external_wait: str = "",
) -> dict[str, Any]:
    artifacts = _safe_list(observed_artifacts or [], limit=320)
    internal_gap_summary = _safe_summary(internal_gap) if internal_gap.strip() else ""
    external_wait_summary = _safe_summary(external_wait) if external_wait.strip() else ""
    return {
        "clear": bool(artifacts and internal_gap_summary and not external_wait_summary),
        "observed_artifacts": artifacts,
        "internal_actionable_gap": internal_gap_summary,
        "external_wait": external_wait_summary,
        "evaluated_at": utc_now(),
    }


def _runtime_state(value: object | None = None) -> dict[str, Any]:
    runtime = value if isinstance(value, dict) else {}
    queue = runtime.get("queue", [])
    if not isinstance(queue, list):
        queue = []
    try:
        heartbeat_count = int(runtime.get("heartbeat_count", 0) or 0)
    except (TypeError, ValueError):
        heartbeat_count = 0
    return {
        "schema_version": LOOP_RUNTIME_SCHEMA,
        "heartbeat_count": heartbeat_count,
        "last_tick_at": str(runtime.get("last_tick_at", "")),
        "last_trigger": _safe_summary(str(runtime.get("last_trigger", "")), limit=80),
        "last_planned_action": _safe_summary(str(runtime.get("last_planned_action", "")), limit=80),
        "last_queue_id": _safe_summary(str(runtime.get("last_queue_id", "")), limit=140),
        "queue": queue,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _next_runtime_plan(cycle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    wait_reason = str(cycle.get("wait_reason", "none"))
    if wait_reason == "permission_required":
        return {
            "planned_action": "request_permission",
            "phase": "waiting",
            "status": "blocked_by_permission",
            "next_action": "request_permission",
            "reason": "The loop has no allowed action yet.",
        }
    if wait_reason == "waiting_external_observation":
        return {
            "planned_action": "wait_for_external_observation",
            "phase": "waiting",
            "status": "blocked_by_wait",
            "next_action": "record_external_wait",
            "reason": "The loop is waiting for external evidence and should not auto-continue.",
        }
    if wait_reason in {"context_exhausted", "budget_exhausted"}:
        return {
            "planned_action": "checkpoint_resume",
            "phase": "waiting",
            "status": "blocked_by_wait",
            "next_action": "record_checkpoint",
            "reason": "The loop needs a checkpoint before more context or budget is available.",
        }

    planned_action, phase = _phase_runtime_action(str(cycle.get("phase", "interview")))
    allowed = set(_string_set(envelope.get("allowed_actions", [])))
    if planned_action not in allowed:
        return {
            "planned_action": planned_action,
            "phase": str(cycle.get("phase", "interview")),
            "status": "blocked_by_permission",
            "next_action": "request_permission",
            "reason": f"`{planned_action}` is outside the current authority envelope.",
        }
    return {
        "planned_action": planned_action,
        "phase": phase,
        "status": "prepared_not_observed",
        "next_action": "observe_runtime_queue",
        "reason": "Prepared the next loop step for a wrapper, scheduler, or executor to observe.",
    }


def _phase_runtime_action(phase: str) -> tuple[str, str]:
    if phase == "research":
        return "planning", "plan"
    if phase == "plan":
        return "executor_handoff", "handoff"
    if phase == "handoff":
        return "executor_dispatch", "handoff"
    if phase == "execution":
        return "review_fix_loop", "feedback"
    if phase == "feedback":
        return "research", "research"
    return "research", "research"


def _runtime_queue_item(
    cycle: dict[str, Any],
    envelope: dict[str, Any],
    plan: dict[str, str],
    *,
    trigger: str,
    cadence: str,
    worktree_base: str,
    worktree_branch: str,
    subagent_role: str,
    connector: str,
    connector_action: str,
    note: str,
) -> dict[str, Any]:
    planned_action = plan["planned_action"]
    queue_id = _new_item_id("queue")
    branch_hint = worktree_branch.strip() or f"omh-loop/{cycle.get('loop_id', 'loop')}/{planned_action}"
    role = subagent_role.strip() or _default_subagent_role(planned_action)
    connector_name = connector.strip()
    is_prepared = plan["status"] == "prepared_not_observed"
    return {
        "schema_version": LOOP_QUEUE_ITEM_SCHEMA,
        "queue_id": queue_id,
        "created_at": utc_now(),
        "trigger": _safe_summary(trigger or "manual", limit=80),
        "cadence": _safe_summary(cadence, limit=80) if cadence.strip() else "",
        "planned_action": planned_action,
        "status": plan["status"],
        "phase": plan["phase"],
        "reason": _safe_summary(plan["reason"], limit=320),
        "worktree_plan": (
            _worktree_plan(cycle, planned_action, worktree_base, branch_hint) if is_prepared else _empty_worktree_plan()
        ),
        "subagent_plan": (
            _subagent_plan(cycle, planned_action, role, envelope) if is_prepared else _empty_subagent_plan()
        ),
        "connector_plan": (
            _connector_plan(connector_name, connector_action, planned_action)
            if is_prepared
            else _connector_plan("", "", planned_action)
        ),
        "note": _safe_summary(note, limit=240) if note.strip() else "",
        "observed": False,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _worktree_plan(cycle: dict[str, Any], planned_action: str, worktree_base: str, branch_hint: str) -> dict[str, Any]:
    base = _safe_summary(worktree_base, limit=160) if worktree_base.strip() else ".worktrees"
    loop_id = str(cycle.get("loop_id", "loop"))
    path_hint = f"{base.rstrip('/')}/omh-loop-{_slugify(loop_id)}-{_slugify(planned_action)}"
    return {
        "strategy": "planned_only",
        "path_hint": path_hint,
        "branch_hint": _safe_summary(branch_hint, limit=180),
        "created": False,
        "observed": False,
        "boundary": "OMH records the worktree plan; an authorized wrapper or executor must create and observe it.",
    }


def _empty_worktree_plan() -> dict[str, Any]:
    return {
        "strategy": "none",
        "path_hint": "",
        "branch_hint": "",
        "created": False,
        "observed": False,
        "boundary": "No worktree plan is prepared while the loop is blocked.",
    }


def _subagent_plan(
    cycle: dict[str, Any],
    planned_action: str,
    role: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    return {
        "strategy": "planned_only",
        "role": _safe_summary(role, limit=80),
        "allowed_executors": list(envelope.get("allowed_executors", [])),
        "prompt_seed": _safe_summary(
            f"Continue loop {cycle.get('loop_id', '')}: {planned_action} for {cycle.get('goal', {}).get('summary', '')}",
            limit=320,
        ),
        "dispatched": False,
        "observed": False,
        "boundary": "OMH prepares the subagent handoff; the wrapper/runtime records dispatch evidence separately.",
    }


def _empty_subagent_plan() -> dict[str, Any]:
    return {
        "strategy": "none",
        "role": "",
        "allowed_executors": [],
        "prompt_seed": "",
        "dispatched": False,
        "observed": False,
        "boundary": "No subagent plan is prepared while the loop is blocked.",
    }


def _connector_plan(connector: str, connector_action: str, planned_action: str) -> dict[str, Any]:
    if not connector:
        return {
            "strategy": "none",
            "connector": "",
            "action": "",
            "dispatched": False,
            "observed": False,
            "boundary": "No connector was requested for this tick.",
        }
    return {
        "strategy": "planned_only",
        "connector": _safe_summary(connector, limit=120),
        "action": _safe_summary(connector_action or planned_action, limit=160),
        "dispatched": False,
        "observed": False,
        "boundary": "OMH records connector intent only; connector I/O requires a separate observed wrapper action.",
    }


def _default_subagent_role(planned_action: str) -> str:
    if planned_action == "research":
        return "researcher"
    if planned_action == "planning":
        return "planner"
    if planned_action in {"executor_handoff", "executor_dispatch", "repo_edit"}:
        return "executor"
    if planned_action in {"review_fix_loop", "ci_fix_loop"}:
        return "verifier"
    return "operator"


def _runtime_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    pending = [item for item in queue if not (item.get("status") == "observed" and item.get("observed") is True)]
    last = queue[-1] if queue else {}
    return {
        "schema_version": LOOP_RUNTIME_SCHEMA,
        "heartbeat_count": runtime["heartbeat_count"],
        "last_tick_at": runtime["last_tick_at"],
        "last_trigger": runtime["last_trigger"],
        "last_planned_action": runtime["last_planned_action"],
        "pending_queue_count": len(pending),
        "last_queue_id": runtime["last_queue_id"],
        "last_queue_status": str(last.get("status", "")),
        "last_queue_reason": str(last.get("reason", "")),
        "claim_boundary": _runtime_claim_boundary(),
    }


def _validate_runtime(runtime: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(runtime, dict):
        return ["runtime must be an object"]
    if runtime.get("schema_version") != LOOP_RUNTIME_SCHEMA:
        errors.append(f"runtime.schema_version must be {LOOP_RUNTIME_SCHEMA}")
    queue = runtime.get("queue", [])
    if not isinstance(queue, list):
        errors.append("runtime.queue must be a list")
        return errors
    allowed_runtime_actions = set(LOOP_ACTIONS) | set(LOOP_CONTROL_ACTIONS)
    for index, item in enumerate(queue):
        if not isinstance(item, dict):
            errors.append(f"runtime.queue[{index}] must be an object")
            continue
        if item.get("schema_version") != LOOP_QUEUE_ITEM_SCHEMA:
            errors.append(f"runtime.queue[{index}].schema_version must be {LOOP_QUEUE_ITEM_SCHEMA}")
        if item.get("status") not in LOOP_QUEUE_STATUSES:
            errors.append(f"runtime.queue[{index}].status is unsupported")
        if item.get("planned_action") not in allowed_runtime_actions:
            errors.append(f"runtime.queue[{index}].planned_action is unsupported")
        plans: dict[str, dict[str, Any]] = {}
        for key in ("worktree_plan", "subagent_plan", "connector_plan"):
            plan = item.get(key)
            if not isinstance(plan, dict):
                errors.append(f"runtime.queue[{index}].{key} must be an object")
                continue
            plans[key] = plan
        if item.get("status") == "observed":
            if item.get("observed") is not True:
                errors.append(f"runtime.queue[{index}].observed must be true when status is observed")
            worktree_plan = plans.get("worktree_plan", {})
            if worktree_plan.get("strategy") != "none":
                if worktree_plan.get("created") is not True:
                    errors.append(f"runtime.queue[{index}].worktree_plan.created must be true when observed")
                if worktree_plan.get("observed") is not True:
                    errors.append(f"runtime.queue[{index}].worktree_plan.observed must be true when observed")
            subagent_plan = plans.get("subagent_plan", {})
            if subagent_plan.get("strategy") != "none":
                if subagent_plan.get("dispatched") is not True:
                    errors.append(f"runtime.queue[{index}].subagent_plan.dispatched must be true when observed")
                if subagent_plan.get("observed") is not True:
                    errors.append(f"runtime.queue[{index}].subagent_plan.observed must be true when observed")
            connector_plan = plans.get("connector_plan", {})
            if connector_plan.get("strategy") != "none":
                if connector_plan.get("dispatched") is not True:
                    errors.append(f"runtime.queue[{index}].connector_plan.dispatched must be true when observed")
                if connector_plan.get("observed") is not True:
                    errors.append(f"runtime.queue[{index}].connector_plan.observed must be true when observed")
        else:
            if item.get("observed") is not False:
                errors.append(f"runtime.queue[{index}].observed must be false unless status is observed")
            if plans.get("worktree_plan", {}).get("created") is not False:
                errors.append(f"runtime.queue[{index}].worktree_plan.created must be false before observation")
            if plans.get("worktree_plan", {}).get("observed") is not False:
                errors.append(f"runtime.queue[{index}].worktree_plan.observed must be false before observation")
            if plans.get("subagent_plan", {}).get("dispatched") is not False:
                errors.append(f"runtime.queue[{index}].subagent_plan.dispatched must be false before observation")
            if plans.get("subagent_plan", {}).get("observed") is not False:
                errors.append(f"runtime.queue[{index}].subagent_plan.observed must be false before observation")
            if plans.get("connector_plan", {}).get("dispatched") is not False:
                errors.append(f"runtime.queue[{index}].connector_plan.dispatched must be false before observation")
            if plans.get("connector_plan", {}).get("observed") is not False:
                errors.append(f"runtime.queue[{index}].connector_plan.observed must be false before observation")
        if item.get("status") in {"blocked_by_permission", "blocked_by_wait"}:
            for key, plan in plans.items():
                if plan.get("strategy") != "none":
                    errors.append(f"runtime.queue[{index}].{key}.strategy must be none while blocked")
    return errors


def _runtime_claim_boundary() -> str:
    return (
        "A loop runtime tick prepares local orchestration work only. It is not worktree creation, "
        "subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or goal completion evidence."
    )


def _dict_value(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def _normalize_permission_state(cycle: dict[str, Any]) -> None:
    envelope = _dict_value(cycle, "authority_envelope")
    allowed_actions = envelope.get("allowed_actions", [])
    if not isinstance(allowed_actions, list) or not allowed_actions:
        cycle["phase"] = "waiting"
        cycle["wait_reason"] = "permission_required"
        cycle["next_action"] = "request_permission"
        return
    if cycle.get("wait_reason") == "permission_required":
        cycle["wait_reason"] = "none"
        if cycle.get("phase") == "waiting":
            cycle["phase"] = "feedback" if cycle.get("cycles") else "interview"
        if cycle.get("next_action") in {"", "request_permission"}:
            cycle["next_action"] = "continue_loop"


def _next_action(cycle: dict[str, Any]) -> str:
    wait_reason = str(cycle.get("wait_reason", "none"))
    if wait_reason == "waiting_external_observation":
        return "record_external_wait"
    if wait_reason in {"context_exhausted", "budget_exhausted"}:
        return "record_checkpoint"
    if wait_reason == "permission_required":
        return "request_permission"
    explicit = str(cycle.get("next_action", ""))
    if explicit:
        return explicit
    if _dict_value(cycle, "feedback_gate").get("clear"):
        return "continue_loop"
    return "show_loop_status"


def _completion_claim_allowed(linked_gate: dict[str, Any] | None) -> bool:
    return bool(linked_gate and linked_gate.get("ready") is True)


def _authority_summary(envelope: dict[str, Any]) -> str:
    allowed = list(envelope.get("allowed_actions", []))
    blocked = list(envelope.get("blocked_actions", []))
    return (
        f"Profile {envelope.get('permission_profile', 'custom')} allows {len(allowed)} loop actions "
        f"and keeps {len(blocked)} actions behind explicit approval."
    )


def _safe_status_copy(cycle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    phase = str(cycle.get("phase", "interview"))
    wait_reason = str(cycle.get("wait_reason", "none"))
    if wait_reason == "waiting_external_observation":
        next_step = "Record external evidence when it arrives; continue internal work only when a new gap is available."
    elif wait_reason in {"context_exhausted", "budget_exhausted"}:
        next_step = "Checkpoint this loop and resume from the recorded status when context or budget is available."
    elif cycle.get("next_action") == "observe_runtime_queue":
        next_step = "Review the prepared runtime queue item, then record observed worktree, subagent, connector, or executor evidence separately."
    elif "executor_dispatch" in envelope.get("allowed_actions", []):
        next_step = "Continue the next research, plan, handoff, or gated executor step within the authority envelope."
    else:
        next_step = "Prepare the next research, plan, or handoff artifact without claiming execution."
    return {
        "headline": f"Loop `{cycle.get('loop_id', '')}` is in `{phase}`.",
        "next_step": next_step,
        "boundary": _claim_boundary(),
    }


def _claim_boundary() -> str:
    return (
        "A loop cycle is orchestration state only. Goal completion still requires goal_ledger/v1 "
        "completion evidence, and prepared handoffs are not executor execution."
    )
