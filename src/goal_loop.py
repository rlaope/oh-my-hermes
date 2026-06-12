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
LOOP_START_CARD_SCHEMA = "loop_start_card/v1"
LOOP_QUEUE_LIST_SCHEMA = "loop_queue_list/v1"
LOOP_QUEUE_HANDOFF_SCHEMA = "loop_queue_handoff/v1"
LOOP_ENGINEERING_SCHEMA = "loop_engineering/v1"
LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA = "loop_subagent_result_contract/v1"
LOOP_VERIFICATION_PLAN_SCHEMA = "loop_verification_plan/v1"
LOOP_FAILURE_MODE_SUMMARY_SCHEMA = "loop_failure_mode_summary/v1"
LOOP_SMALL_LOOP_GUIDANCE_SCHEMA = "loop_small_loop_guidance/v1"
LOOP_RUN_ONCE_RESULT_SCHEMA = "loop_run_once_result/v1"

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
    "blocked",
    "observed",
)
LOOP_PIPELINE_STEPS = (
    "task_discovery",
    "distribution",
    "execution",
    "verification",
    "next_task_decision",
)
LOOP_BUILDING_BLOCKS = (
    "automation",
    "worktree",
    "skill",
    "connector",
    "subagent",
)
LOOP_WORKFLOW_PATTERNS = (
    "single_step",
    "fan_out_synthesize",
    "adversarial_verification",
    "tournament",
    "triage_batch",
)
LOOP_VERIFICATION_TIERS = ("none", "inner", "outer")
LOOP_CONTEXT_POLICY_REF = "loop_engineering.context_policy"
LOOP_COST_POLICY_REF = "loop_engineering.cost_policy"
LOOP_EXECUTOR_OPTIONS = (
    {"id": "choose", "label": "Ask me each time", "dispatchable_by_default": False},
    {"id": "codex", "label": "Codex lifecycle handoff", "dispatchable_by_default": True},
    {"id": "claude-code", "label": "Claude Code prompt handoff", "dispatchable_by_default": False},
    {"id": "generic", "label": "Generic coding-agent prompt", "dispatchable_by_default": False},
    {"id": "omx-runtime", "label": "Plugin/runtime handoff", "dispatchable_by_default": False},
    {"id": "hermes", "label": "Hermes coding/runtime work", "dispatchable_by_default": False},
)
LOOP_EXECUTOR_OPTION_IDS = tuple(str(option["id"]) for option in LOOP_EXECUTOR_OPTIONS)
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
        "loop_engineering": _loop_engineering_template(),
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


def build_loop_start_card(
    goal_summary: str,
    *,
    include_goal: bool = False,
    source: str = "omh",
    default_permission_profile: str = "handoff_only",
    default_executor: str = "choose",
) -> dict[str, Any]:
    summary = _safe_summary(goal_summary)
    if not summary:
        raise ValueError("loop start-card requires a goal summary")
    if default_permission_profile not in PERMISSION_PROFILES:
        raise ValueError(f"unsupported permission profile: {default_permission_profile}")
    if default_executor not in LOOP_EXECUTOR_OPTION_IDS:
        raise ValueError(f"unsupported loop default executor: {default_executor}")
    return {
        "schema_version": LOOP_START_CARD_SCHEMA,
        "source": _safe_summary(source, limit=120),
        "status": "interview_required",
        "goal_summary": summary if include_goal else "{message}",
        "goal_summary_hash": sha256_text(goal_summary),
        "goal_length": len(goal_summary),
        "next_action": "choose_permission_profile",
        "default_permission_profile": default_permission_profile,
        "default_executor": _safe_summary(default_executor, limit=120),
        "permission_profiles": [_permission_profile_option(profile) for profile in PERMISSION_PROFILES if profile != "custom"],
        "executor_options": [dict(option) for option in LOOP_EXECUTOR_OPTIONS],
        "required_inputs": [
            {
                "id": "goal_reframe",
                "label": "Goal reframe",
                "prompt": "Reframe the north-star goal into implementable internal work without shrinking its ambition.",
            },
            {
                "id": "success_criteria",
                "label": "Success criteria",
                "prompt": "Name the evidence that would prove internal work progressed, plus what remains external waiting.",
            },
            {
                "id": "permission_profile",
                "label": "Permission profile",
                "prompt": "Choose how far the loop may go before it asks for explicit authority.",
            },
        ],
        "suggested_success_criteria": [
            "Comparable capability gaps are identified and closed with tests or docs.",
            "Prepared handoffs and observed executor results remain separate.",
            "External adoption or market response is recorded as waiting until evidence exists.",
        ],
        "backend_contract": {
            "operation": "loop.start",
            "required_fields": ["goal_summary", "goal_reframe", "success_criteria", "permission_profile"],
            "optional_fields": ["allowed_executors", "linked_goal_id", "source"],
            "creates_artifact": "loop_cycle/v1",
        },
        "loop_engineering": _loop_engineering_template(),
        "verification_policy": _loop_verification_policy(),
        "failure_modes": _failure_mode_definitions(),
        "small_loop_guidance": _small_loop_guidance(),
        "actions": [
            "choose_permission_profile",
            "start_loop",
            "show_loop_status",
            "cancel",
        ],
        "claim_boundary": _claim_boundary(),
        "runtime_claim_boundary": _runtime_claim_boundary(),
    }


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
    workflow_pattern: str = "single_step",
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
        workflow_pattern=workflow_pattern,
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


def run_loop_once(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    runtime = _runtime_state(cycle.get("runtime"))
    pending = [
        item
        for item in runtime.get("queue", [])
        if isinstance(item, dict) and item.get("status") == "prepared_not_observed"
    ]
    if pending:
        cycle["phase"] = str(pending[-1].get("phase", cycle.get("phase", "handoff")))
        cycle["next_action"] = "observe_runtime_queue"
        return _write_loop(paths, cycle)
    return tick_loop_runtime(
        paths,
        loop_id,
        trigger="automation",
        cadence="run-once",
        workflow_pattern="single_step",
        note=(
            "Non-daemon loop run-once prepared one queue item; no worktree, subagent, "
            "connector, executor, network, or code execution was performed by OMH."
        ),
    )


def run_loop_once_result(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    before = read_loop_cycle(paths, loop_id)
    before_runtime = _runtime_state(before.get("runtime"))
    before_queue = [item for item in before_runtime.get("queue", []) if isinstance(item, dict)]
    before_pending = [item for item in before_queue if item.get("status") == "prepared_not_observed"]
    cycle = run_loop_once(paths, loop_id)
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    if before_pending:
        queue_id = str(before_pending[-1].get("queue_id", ""))
        outcome = "pending_queue_exists"
        advanced = False
        created_queue_count = 0
    else:
        created_queue_count = max(0, len(queue) - len(before_queue))
        advanced = created_queue_count > 0
        outcome = "created_tick" if advanced else "no_eligible_tick"
        queue_id = str(queue[-1].get("queue_id", "")) if queue else ""
    return {
        "loop": cycle,
        "run_once": {
            "schema_version": LOOP_RUN_ONCE_RESULT_SCHEMA,
            "loop_id": str(cycle.get("loop_id", loop_id)),
            "outcome": outcome,
            "advanced": advanced,
            "created_queue_count": created_queue_count,
            "queue_id": queue_id,
            "pending_queue_count": sum(1 for item in queue if item.get("status") == "prepared_not_observed"),
            "next_action": str(cycle.get("next_action", "")),
            "claim_boundary": _runtime_claim_boundary(),
        },
    }


def list_loop_queue(paths: OmhPaths, loop_id: str, *, include_observed: bool = False) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    visible = [
        _queue_item_summary(item)
        for item in queue
        if include_observed or not (item.get("status") == "observed" and item.get("observed") is True)
    ]
    return {
        "schema_version": LOOP_QUEUE_LIST_SCHEMA,
        "loop_id": cycle["loop_id"],
        "include_observed": include_observed,
        "queue": visible,
        "pending_queue_count": sum(1 for item in queue if item.get("status") == "prepared_not_observed"),
        "blocked_queue_count": sum(1 for item in queue if item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"}),
        "observed_queue_count": sum(1 for item in queue if item.get("status") == "observed" and item.get("observed") is True),
        "claim_boundary": _runtime_claim_boundary(),
    }


def inspect_loop_queue_item(paths: OmhPaths, loop_id: str, queue_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    item = _queue_item_ref(cycle, queue_id)[1]
    return {
        "schema_version": LOOP_QUEUE_ITEM_SCHEMA,
        "loop_id": cycle["loop_id"],
        "queue_item": item,
        "claim_boundary": _runtime_claim_boundary(),
    }


def build_loop_queue_handoff(paths: OmhPaths, loop_id: str, queue_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    item = _queue_item_ref(cycle, queue_id)[1]
    if item.get("status") != "prepared_not_observed":
        raise ValueError("only prepared_not_observed loop queue items can render a handoff")
    text = _queue_handoff_text(cycle, item)
    return {
        "schema_version": LOOP_QUEUE_HANDOFF_SCHEMA,
        "loop_id": cycle["loop_id"],
        "queue_id": item["queue_id"],
        "planned_action": item["planned_action"],
        "phase": item["phase"],
        "status": item["status"],
        "handoff_text": text,
        "worktree_plan": item.get("worktree_plan", _empty_worktree_plan()),
        "subagent_plan": item.get("subagent_plan", _empty_subagent_plan()),
        "connector_plan": item.get("connector_plan", _connector_plan("", "", str(item.get("planned_action", "")))),
        "next_action": "observe_or_block_loop_queue",
        "actions": ["observe_loop_queue", "block_loop_queue", "show_loop_status"],
        "claim_boundary": _runtime_claim_boundary(),
    }


def observe_loop_queue_item(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    evidence_refs: Iterable[str],
    worktree_evidence_refs: Iterable[str] | None = None,
    subagent_evidence_refs: Iterable[str] | None = None,
    connector_evidence_refs: Iterable[str] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    refs = _safe_list(evidence_refs, limit=320)
    worktree_refs = _safe_list(worktree_evidence_refs or [], limit=320)
    subagent_refs = _safe_list(subagent_evidence_refs or [], limit=320)
    connector_refs = _safe_list(connector_evidence_refs or [], limit=320)
    aggregate_refs = _safe_list([*refs, *worktree_refs, *subagent_refs, *connector_refs], limit=320)
    if not aggregate_refs:
        raise ValueError("loop queue observation requires at least one evidence ref")
    cycle = read_loop_cycle(paths, loop_id)
    runtime, item = _queue_item_ref(cycle, queue_id)
    if item.get("status") != "prepared_not_observed":
        raise ValueError("only prepared_not_observed loop queue items can be observed")
    item["status"] = "observed"
    item["observed"] = True
    item["observed_at"] = utc_now()
    item["observed_evidence_refs"] = aggregate_refs
    item["observation_summary"] = _safe_summary(summary, limit=320) if summary.strip() else "Queue item observed by wrapper or operator evidence."
    _mark_queue_plans_observed(
        item,
        worktree_evidence_refs=worktree_refs,
        subagent_evidence_refs=subagent_refs,
        connector_evidence_refs=connector_refs,
    )
    runtime["last_queue_id"] = str(item["queue_id"])
    runtime["last_queue_status"] = "observed"
    cycle["runtime"] = runtime
    cycle["phase"] = "feedback"
    cycle["wait_reason"] = "none"
    cycle["next_action"] = "record_feedback"
    return _write_loop(paths, cycle)


def block_loop_queue_item(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    blocker = _safe_summary(reason, limit=320)
    if not blocker:
        raise ValueError("loop queue blocker reason is required")
    cycle = read_loop_cycle(paths, loop_id)
    runtime, item = _queue_item_ref(cycle, queue_id)
    if item.get("status") == "observed" or item.get("observed") is True:
        raise ValueError("observed loop queue items cannot be blocked")
    item["status"] = "blocked"
    item["observed"] = False
    item["blocked_at"] = utc_now()
    item["blocker_reason"] = blocker
    runtime["last_queue_id"] = str(item["queue_id"])
    runtime["last_queue_status"] = "blocked"
    cycle["runtime"] = runtime
    cycle["phase"] = "blocked"
    cycle["wait_reason"] = "none"
    cycle["next_action"] = "resolve_runtime_queue_blocker"
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
        "loop_engineering": _loop_engineering_status(cycle),
        "failure_mode_summary": _failure_mode_summary(cycle),
        "small_loop_guidance": _small_loop_guidance(),
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


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _valid_actions(values: Iterable[str]) -> set[str]:
    actions = {str(value).strip() for value in values if str(value).strip()}
    unknown = sorted(actions - set(LOOP_ACTIONS))
    if unknown:
        raise ValueError(f"unsupported loop action(s): {', '.join(unknown)}")
    return actions


def _workflow_pattern(value: str) -> str:
    pattern = _safe_summary(value or "single_step", limit=80) or "single_step"
    if pattern not in LOOP_WORKFLOW_PATTERNS:
        raise ValueError(f"unsupported loop workflow pattern: {pattern}")
    return pattern


def _loop_engineering_template() -> dict[str, Any]:
    return {
        "schema_version": LOOP_ENGINEERING_SCHEMA,
        "definition": "A loop is a local system that prompts agents through task discovery, distribution, execution, verification, and the next task decision.",
        "pipeline": [
            {
                "id": step,
                "label": step.replace("_", " "),
                "claim_boundary": "This step describes orchestration state only until observed evidence refs are recorded.",
            }
            for step in LOOP_PIPELINE_STEPS
        ],
        "building_blocks": [
            {
                "id": block,
                "label": block.replace("_", " "),
                "claim_boundary": _building_block_boundary(block),
            }
            for block in LOOP_BUILDING_BLOCKS
        ],
        "workflow_patterns": [
            {
                "id": pattern,
                "label": pattern.replace("_", " "),
                "claim_boundary": "Pattern selection changes orchestration shape only; it is not dispatch or execution evidence.",
            }
            for pattern in LOOP_WORKFLOW_PATTERNS
        ],
        "context_policy": _loop_context_policy(),
        "cost_policy": _loop_cost_policy(),
        "verification_policy": _loop_verification_policy(),
        "failure_modes": _failure_mode_definitions(),
        "small_loop_guidance": _small_loop_guidance(),
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _loop_engineering_status(cycle: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    workflow_summary = _workflow_pattern_summary(queue)
    contract = _loop_engineering_contract(cycle)
    return {
        "schema_version": LOOP_ENGINEERING_SCHEMA,
        "loop_id": str(cycle.get("loop_id", "")),
        "current_pipeline_step": _pipeline_step_for_phase(
            str(cycle.get("phase", "interview")),
            str(cycle.get("wait_reason", "none")),
        ),
        "pipeline": [
            {
                "id": step,
                "state": _pipeline_step_state(step, cycle, queue),
                "evidence_refs": _pipeline_step_evidence_refs(step, cycle, queue),
                "claim_boundary": "State is orchestration metadata unless the evidence refs point to observed wrapper/runtime artifacts.",
            }
            for step in LOOP_PIPELINE_STEPS
        ],
        "building_blocks": _building_block_statuses(cycle, queue),
        "workflow_patterns": workflow_summary,
        "context_policy": contract["context_policy"],
        "cost_policy": contract["cost_policy"],
        "verification_policy": contract.get("verification_policy") or _loop_verification_policy(),
        "failure_modes": contract.get("failure_modes") or _failure_mode_definitions(),
        "small_loop_guidance": contract.get("small_loop_guidance") or _small_loop_guidance(),
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _loop_engineering_contract(cycle: dict[str, Any]) -> dict[str, Any]:
    contract = cycle.get("loop_engineering")
    if isinstance(contract, dict) and contract.get("schema_version") == LOOP_ENGINEERING_SCHEMA:
        return {
            **contract,
            "context_policy": contract.get("context_policy") or _loop_context_policy(),
            "cost_policy": contract.get("cost_policy") or _loop_cost_policy(),
            "verification_policy": contract.get("verification_policy") or _loop_verification_policy(),
            "failure_modes": contract.get("failure_modes") or _failure_mode_definitions(),
            "small_loop_guidance": contract.get("small_loop_guidance") or _small_loop_guidance(),
        }
    return _loop_engineering_template()


def _queue_loop_engineering(planned_action: str, status: str, workflow_pattern: str) -> dict[str, Any]:
    return {
        "schema_version": LOOP_ENGINEERING_SCHEMA,
        "pipeline_step": _pipeline_step_for_action(planned_action),
        "workflow_pattern": workflow_pattern,
        "status": status,
        "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
        "cost_policy_ref": LOOP_COST_POLICY_REF,
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _subagent_result_contract(planned_action: str, workflow_pattern: str) -> dict[str, Any]:
    return {
        "schema_version": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "planned_action": _safe_summary(planned_action, limit=80),
        "workflow_pattern": workflow_pattern,
        "status_values": ["ok", "blocked", "needs_human", "failed"],
        "required_fields": ["status", "summary", "evidence_refs", "next_actions"],
        "optional_fields": ["artifacts", "changed_files", "risks", "verification"],
        "max_summary_chars": 1200,
        "parent_context_policy": "Return a bounded structured result and evidence refs; do not paste the full transcript, raw logs, or large artifacts into parent context.",
        "large_output_policy": "Store large outputs outside parent context and return a path, id, hash, or wrapper evidence ref.",
        "cost_policy": _loop_cost_policy(workflow_pattern),
        "verification_policy": _subagent_verification_policy(planned_action, workflow_pattern),
    }


def _loop_context_policy() -> dict[str, Any]:
    return {
        "read_model": "bounded_state_and_evidence_refs",
        "parent_context": "Keep the parent loop focused on decision state, summaries, evidence refs, and next actions.",
        "large_output_policy": "Reference bulky subagent, connector, test, or research output by artifact path, id, hash, or evidence ref.",
        "subagent_return": "Subagents should return structured result objects, not replay their full working context.",
        "summary_budget_chars": 1200,
    }


def _loop_cost_policy(workflow_pattern: str = "single_step") -> dict[str, Any]:
    pattern = workflow_pattern if workflow_pattern in LOOP_WORKFLOW_PATTERNS else "single_step"
    return {
        "workflow_pattern": pattern,
        "bounded_reads": True,
        "reuse_schema_scaffold": True,
        "avoid_full_rescan": True,
        "default_verifier_lanes": 1,
        "extra_verifier_policy": "Add verifier lanes only for high-risk changes, failed evidence, explicit review requests, or adversarial_verification/tournament patterns.",
        "large_output_policy": "Keep large outputs in artifacts and pass refs, not full text.",
        "summary_budget_chars": 1200,
    }


def _subagent_verification_policy(planned_action: str, workflow_pattern: str) -> str:
    if workflow_pattern == "adversarial_verification":
        return "Return independent objections, checked evidence refs, and a pass/fail/blocked verdict."
    if workflow_pattern == "tournament":
        return "Return candidate approach id, scoring criteria, tradeoffs, and evidence refs for synthesis."
    if planned_action in {"review_fix_loop", "ci_fix_loop"}:
        return "Return verification command evidence, failures, fixes required, and residual risk."
    return "Return enough evidence refs for the parent loop to decide whether to continue, block, or ask for authority."


def _pipeline_step_for_action(planned_action: str) -> str:
    if planned_action in {"research", "planning", "ultragoal_creation"}:
        return "task_discovery"
    if planned_action in {"executor_handoff", "executor_dispatch"}:
        return "distribution"
    if planned_action in {
        "repo_edit",
        "pr_creation",
        "pr_revision",
        "release_note_work",
        "external_posting_prep",
        "external_posting",
        "merge",
    }:
        return "execution"
    if planned_action in {"review_fix_loop", "ci_fix_loop"}:
        return "verification"
    return "next_task_decision"


def _pipeline_step_for_phase(phase: str, wait_reason: str) -> str:
    if wait_reason != "none" or phase in {"waiting", "blocked", "complete"}:
        return "next_task_decision"
    if phase == "handoff":
        return "distribution"
    if phase == "execution":
        return "execution"
    if phase == "feedback":
        return "verification"
    return "task_discovery"


def _pipeline_step_state(step: str, cycle: dict[str, Any], queue: list[dict[str, Any]]) -> str:
    if step == "task_discovery":
        goal = _dict_value(cycle, "goal")
        criteria = cycle.get("success_criteria")
        return "observed" if goal.get("summary") and isinstance(criteria, list) and criteria else "missing"
    if step == "verification":
        feedback = _dict_value(cycle, "feedback_gate")
        if feedback.get("observed_artifacts"):
            return "observed"
        return _queue_pipeline_state(queue, step)
    if step == "next_task_decision":
        if str(cycle.get("wait_reason", "none")) != "none":
            return "waiting"
        if str(cycle.get("next_action", "")).strip():
            return "ready"
        return "pending"
    return _queue_pipeline_state(queue, step)


def _pipeline_step_evidence_refs(step: str, cycle: dict[str, Any], queue: list[dict[str, Any]]) -> list[str]:
    loop_id = str(cycle.get("loop_id", "loop"))
    if step == "task_discovery":
        return [f"loop:{loop_id}:goal", f"loop:{loop_id}:success_criteria"]
    if step == "verification":
        refs = _string_list(_dict_value(cycle, "feedback_gate").get("observed_artifacts", []))
        return refs or _queue_pipeline_refs(queue, step)
    if step == "next_task_decision":
        return [f"loop:{loop_id}:next_action:{_next_action(cycle)}"]
    return _queue_pipeline_refs(queue, step)


def _queue_pipeline_state(queue: list[dict[str, Any]], step: str) -> str:
    relevant: list[dict[str, Any]] = []
    for item in queue:
        if _queue_item_pipeline_step(item) == step:
            relevant.append(item)
    if any(item.get("status") == "observed" and item.get("observed") is True for item in relevant):
        return "observed"
    if any(item.get("status") == "prepared_not_observed" for item in relevant):
        return "prepared_not_observed"
    if any(item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"} for item in relevant):
        return "blocked"
    return "pending"


def _queue_pipeline_refs(queue: list[dict[str, Any]], step: str) -> list[str]:
    refs: list[str] = []
    for item in queue:
        if _queue_item_pipeline_step(item) == step:
            queue_id = str(item.get("queue_id", ""))
            if queue_id:
                refs.append(f"loop_queue:{queue_id}")
    return sorted(set(refs))


def _queue_item_pipeline_step(item: dict[str, Any]) -> str:
    return str(item.get("pipeline_step", _pipeline_step_for_action(str(item.get("planned_action", "")))))


def _building_block_statuses(cycle: dict[str, Any], queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime = _runtime_state(cycle.get("runtime"))
    return [
        {
            "id": "automation",
            "state": "ticked" if int(runtime.get("heartbeat_count", 0) or 0) else "available",
            "detail": "Runtime ticks may be manual, scheduled, wrapper-driven, or automation-driven.",
            "evidence_refs": [f"runtime:heartbeat:{runtime.get('heartbeat_count', 0)}"],
            "claim_boundary": _building_block_boundary("automation"),
        },
        _plan_building_block("worktree", queue, "worktree_plan", "created"),
        {
            "id": "skill",
            "state": "available",
            "detail": "The loop skill owns visible orchestration, not hidden execution.",
            "evidence_refs": ["skill:loop"],
            "claim_boundary": _building_block_boundary("skill"),
        },
        _plan_building_block("connector", queue, "connector_plan", "dispatched"),
        _plan_building_block("subagent", queue, "subagent_plan", "dispatched"),
    ]


def _plan_building_block(block: str, queue: list[dict[str, Any]], key: str, flag: str) -> dict[str, Any]:
    plans = [_dict_value(item, key) for item in queue if isinstance(item, dict)]
    requested = [plan for plan in plans if plan.get("strategy") != "none"]
    refs: list[str] = []
    for plan in requested:
        refs.extend(_string_list(plan.get("evidence_refs", [])))
    if any(plan.get("observed") is True and plan.get(flag) is True for plan in requested):
        state = "observed"
    elif requested:
        state = "planned_not_observed"
    elif any(item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"} for item in queue):
        state = "blocked"
    else:
        state = "not_requested"
    result: dict[str, Any] = {
        "id": block,
        "state": state,
        "detail": _building_block_detail(block),
        "evidence_refs": sorted(set(refs)),
        "claim_boundary": _building_block_boundary(block),
    }
    if block == "subagent":
        result["result_contract_schema"] = LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA
    return result


def _building_block_detail(block: str) -> str:
    details = {
        "worktree": "Worktree entries are path and branch hints until a wrapper records creation evidence.",
        "connector": "Connector entries are intent only until wrapper evidence records I/O.",
        "subagent": "Subagent entries are handoff plans until dispatch and result evidence are recorded.",
    }
    return details.get(block, "")


def _building_block_boundary(block: str) -> str:
    boundaries = {
        "automation": "A tick records orchestration intent; it is not proof that downstream work happened.",
        "worktree": "A worktree plan is not worktree creation evidence.",
        "skill": "Skill routing is not plan acceptance, dispatch, execution, or completion evidence.",
        "connector": "Connector intent is not connector I/O evidence.",
        "subagent": "A subagent plan is not dispatch, execution, or result evidence.",
    }
    return boundaries.get(block, _runtime_claim_boundary())


def _workflow_pattern_summary(queue: list[dict[str, Any]]) -> dict[str, Any]:
    used: dict[str, int] = {}
    for item in queue:
        pattern = str(item.get("workflow_pattern", "")).strip()
        if pattern:
            used[pattern] = used.get(pattern, 0) + 1
    last = str(queue[-1].get("workflow_pattern", "")) if queue else ""
    return {
        "available": list(LOOP_WORKFLOW_PATTERNS),
        "used": used,
        "last": last,
        "claim_boundary": "A workflow pattern is an orchestration shape, not proof that any subagent or executor ran.",
    }


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
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }
    if wait_reason == "waiting_external_observation":
        return {
            "planned_action": "wait_for_external_observation",
            "phase": "waiting",
            "status": "blocked_by_wait",
            "next_action": "record_external_wait",
            "reason": "The loop is waiting for external evidence and should not auto-continue.",
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }
    if wait_reason in {"context_exhausted", "budget_exhausted"}:
        return {
            "planned_action": "checkpoint_resume",
            "phase": "waiting",
            "status": "blocked_by_wait",
            "next_action": "record_checkpoint",
            "reason": "The loop needs a checkpoint before more context or budget is available.",
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
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
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }
    return {
        "planned_action": planned_action,
        "phase": phase,
        "status": "prepared_not_observed",
        "next_action": "observe_runtime_queue",
        "reason": "Prepared the next loop step for a wrapper, scheduler, or executor to observe.",
        "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
        "cost_policy_ref": LOOP_COST_POLICY_REF,
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
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
    workflow_pattern: str,
    note: str,
) -> dict[str, Any]:
    planned_action = plan["planned_action"]
    queue_id = _new_item_id("queue")
    branch_hint = worktree_branch.strip() or f"omh-loop/{cycle.get('loop_id', 'loop')}/{planned_action}"
    role = subagent_role.strip() or _default_subagent_role(planned_action)
    connector_name = connector.strip()
    is_prepared = plan["status"] == "prepared_not_observed"
    pattern = _workflow_pattern(workflow_pattern)
    return {
        "schema_version": LOOP_QUEUE_ITEM_SCHEMA,
        "queue_id": queue_id,
        "created_at": utc_now(),
        "trigger": _safe_summary(trigger or "manual", limit=80),
        "cadence": _safe_summary(cadence, limit=80) if cadence.strip() else "",
        "planned_action": planned_action,
        "workflow_pattern": pattern,
        "pipeline_step": _pipeline_step_for_action(planned_action),
        "context_policy_ref": plan.get("context_policy_ref", LOOP_CONTEXT_POLICY_REF),
        "cost_policy_ref": plan.get("cost_policy_ref", LOOP_COST_POLICY_REF),
        "subagent_result_contract_schema": plan.get(
            "subagent_result_contract_schema",
            LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        ),
        "status": plan["status"],
        "phase": plan["phase"],
        "reason": _safe_summary(plan["reason"], limit=320),
        "worktree_plan": (
            _worktree_plan(cycle, planned_action, worktree_base, branch_hint) if is_prepared else _empty_worktree_plan()
        ),
        "subagent_plan": (
            _subagent_plan(cycle, planned_action, role, envelope, pattern) if is_prepared else _empty_subagent_plan()
        ),
        "connector_plan": (
            _connector_plan(connector_name, connector_action, planned_action)
            if is_prepared
            else _connector_plan("", "", planned_action)
        ),
        "verification_plan": _verification_plan(planned_action, pattern, is_prepared=is_prepared),
        "note": _safe_summary(note, limit=240) if note.strip() else "",
        "observed": False,
        "observed_at": "",
        "observed_evidence_refs": [],
        "observation_summary": "",
        "blocked_at": "",
        "blocker_reason": "",
        "loop_engineering": _queue_loop_engineering(planned_action, plan["status"], pattern),
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
        "evidence_refs": [],
        "boundary": "OMH records the worktree plan; an authorized wrapper or executor must create and observe it.",
    }


def _empty_worktree_plan() -> dict[str, Any]:
    return {
        "strategy": "none",
        "path_hint": "",
        "branch_hint": "",
        "created": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "No worktree plan is prepared while the loop is blocked.",
    }


def _subagent_plan(
    cycle: dict[str, Any],
    planned_action: str,
    role: str,
    envelope: dict[str, Any],
    workflow_pattern: str,
) -> dict[str, Any]:
    return {
        "strategy": "planned_only",
        "role": _safe_summary(role, limit=80),
        "allowed_executors": list(envelope.get("allowed_executors", [])),
        "workflow_pattern": workflow_pattern,
        "prompt_seed": _safe_summary(
            f"Continue loop {cycle.get('loop_id', '')}: {planned_action} for {cycle.get('goal', {}).get('summary', '')}",
            limit=320,
        ),
        "result_contract": _subagent_result_contract(planned_action, workflow_pattern),
        "dispatched": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "OMH prepares the subagent handoff; the wrapper/runtime records dispatch evidence separately.",
    }


def _empty_subagent_plan() -> dict[str, Any]:
    return {
        "strategy": "none",
        "role": "",
        "allowed_executors": [],
        "workflow_pattern": "",
        "prompt_seed": "",
        "result_contract": {},
        "dispatched": False,
        "observed": False,
        "evidence_refs": [],
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
            "evidence_refs": [],
            "boundary": "No connector was requested for this tick.",
        }
    return {
        "strategy": "planned_only",
        "connector": _safe_summary(connector, limit=120),
        "action": _safe_summary(connector_action or planned_action, limit=160),
        "dispatched": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "OMH records connector intent only; connector I/O requires a separate observed wrapper action.",
    }


def _verification_plan(planned_action: str, workflow_pattern: str, *, is_prepared: bool) -> dict[str, Any]:
    pattern = _workflow_pattern(workflow_pattern)
    if not is_prepared:
        return {
            "schema_version": LOOP_VERIFICATION_PLAN_SCHEMA,
            "tier": "none",
            "expected_signal": "No verification is expected while this queue item is blocked or waiting.",
            "failure_action": "do_not_advance",
            "evidence_required": [],
            "stop_signal": "The blocker, permission request, or wait state is resolved.",
            "verifier_role": "",
            "claim_boundary": _runtime_claim_boundary(),
        }
    tier = "outer" if pattern in {"fan_out_synthesize", "adversarial_verification", "tournament"} else "inner"
    if tier == "outer":
        expected_signal = (
            "Verifier review, integration-style evidence, semantic review, release gate, "
            "or human judgment returns pass/fail with evidence refs."
        )
        evidence_required = ["verifier_result_ref", "checked_evidence_ref"]
        stop_signal = "The verifier or human review returns pass with evidence refs."
        verifier_role = "verifier"
    else:
        expected_signal = (
            "Cheap focused evidence such as syntax, compile, schema validation, command smoke, "
            "or targeted test output returns pass/fail."
        )
        evidence_required = ["focused_check_ref"]
        stop_signal = "The focused check returns pass with an evidence ref."
        verifier_role = ""
    return {
        "schema_version": LOOP_VERIFICATION_PLAN_SCHEMA,
        "tier": tier,
        "expected_signal": expected_signal,
        "failure_action": "return_to_plan_or_research",
        "evidence_required": evidence_required,
        "stop_signal": stop_signal,
        "verifier_role": verifier_role,
        "claim_boundary": "Verification intent is metadata until a wrapper or operator records observed verification evidence.",
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
    pending = [item for item in queue if item.get("status") == "prepared_not_observed"]
    unobserved = [item for item in queue if not (item.get("status") == "observed" and item.get("observed") is True)]
    last = queue[-1] if queue else {}
    return {
        "schema_version": LOOP_RUNTIME_SCHEMA,
        "heartbeat_count": runtime["heartbeat_count"],
        "last_tick_at": runtime["last_tick_at"],
        "last_trigger": runtime["last_trigger"],
        "last_planned_action": runtime["last_planned_action"],
        "pending_queue_count": len(pending),
        "unobserved_queue_count": len(unobserved),
        "last_queue_id": runtime["last_queue_id"],
        "last_queue_status": str(last.get("status", "")),
        "last_queue_reason": str(last.get("reason", "")),
        "blocked_queue_count": sum(1 for item in queue if item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"}),
        "observed_queue_count": sum(1 for item in queue if item.get("status") == "observed" and item.get("observed") is True),
        "claim_boundary": _runtime_claim_boundary(),
    }


def _loop_verification_policy() -> dict[str, Any]:
    return {
        "inner_loop_checks": [
            "syntax_or_parse_check",
            "compile_or_import_check",
            "focused_unit_test",
            "command_smoke",
            "schema_validation",
        ],
        "outer_loop_checks": [
            "integration_test",
            "semantic_review",
            "adversarial_verifier",
            "release_gate",
            "human_review",
        ],
        "verifier_policy": (
            "Keep one cheap verification lane by default. Add a verifier subagent only for high-risk changes, "
            "failed evidence, explicit review requests, or fan_out_synthesize/adversarial_verification/tournament patterns."
        ),
        "stop_signal": "A loop step stops only when its expected verification signal is observed, blocked, or explicitly deferred.",
        "claim_boundary": "Verification policy is guidance until observed evidence refs are recorded.",
    }


def _failure_mode_definitions() -> list[dict[str, str]]:
    return [
        {
            "id": "verification_gap",
            "label": "verification gap",
            "meaning": "The loop has prepared or observed work but still lacks enough verification evidence to advance safely.",
        },
        {
            "id": "comprehension_debt",
            "label": "comprehension debt",
            "meaning": "The loop is accumulating delegated or generated work faster than summaries, ownership, or review evidence can explain.",
        },
        {
            "id": "cognitive_surrender",
            "label": "cognitive surrender",
            "meaning": "The loop is broad enough that a human-owned judgment, acceptance signal, or stop condition should be refreshed.",
        },
    ]


def _failure_mode_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    feedback = _dict_value(cycle, "feedback_gate")
    envelope = _dict_value(cycle, "authority_envelope")
    modes = [
        _verification_gap_mode(cycle, queue, feedback),
        _comprehension_debt_mode(cycle, queue, feedback),
        _cognitive_surrender_mode(cycle, envelope),
    ]
    warnings = [mode for mode in modes if mode["state"] == "warning"]
    return {
        "schema_version": LOOP_FAILURE_MODE_SUMMARY_SCHEMA,
        "warnings": warnings,
        "modes": modes,
        "next_action": warnings[0]["next_action"] if warnings else "continue_with_current_loop_gate",
        "claim_boundary": "Failure modes are loop safety warnings; they are not runtime execution evidence.",
    }


def _verification_gap_mode(cycle: dict[str, Any], queue: list[dict[str, Any]], feedback: dict[str, Any]) -> dict[str, str]:
    pending = [item for item in queue if item.get("status") == "prepared_not_observed"]
    observed = [item for item in queue if item.get("status") == "observed" and item.get("observed") is True]
    if pending:
        return _failure_mode(
            "verification_gap",
            "warning",
            "A prepared queue item is waiting for observed work and verification evidence before the loop can advance.",
            "observe_runtime_queue",
        )
    if observed and not _string_list(feedback.get("observed_artifacts", [])) and cycle.get("phase") == "feedback":
        return _failure_mode(
            "verification_gap",
            "warning",
            "Observed queue work exists, but feedback has not recorded verification artifacts yet.",
            "record_feedback",
        )
    return _failure_mode("verification_gap", "clear", "No verification gap is currently visible.", "continue_loop")


def _comprehension_debt_mode(
    cycle: dict[str, Any],
    queue: list[dict[str, Any]],
    feedback: dict[str, Any],
) -> dict[str, str]:
    heartbeat_count = int(_runtime_state(cycle.get("runtime")).get("heartbeat_count", 0) or 0)
    observed_count = sum(1 for item in queue if item.get("status") == "observed" and item.get("observed") is True)
    feedback_count = len(cycle.get("cycles", []) if isinstance(cycle.get("cycles"), list) else [])
    if heartbeat_count >= 3 and observed_count >= 2 and feedback_count == 0:
        return _failure_mode(
            "comprehension_debt",
            "warning",
            "Several loop ticks or observed items exist without a feedback checkpoint that explains what changed.",
            "record_feedback",
        )
    if observed_count >= 3 and not str(feedback.get("internal_actionable_gap", "")).strip():
        return _failure_mode(
            "comprehension_debt",
            "warning",
            "Multiple observed loop items exist; refresh a concise summary, owner, and next risk before continuing.",
            "record_feedback",
        )
    return _failure_mode("comprehension_debt", "clear", "Loop context is still bounded by summaries and evidence refs.", "continue_loop")


def _cognitive_surrender_mode(cycle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    allowed = set(_string_set(envelope.get("allowed_actions", [])))
    broad_actions = {"executor_dispatch", "repo_edit", "pr_creation", "merge", "external_posting"}
    if allowed & broad_actions and not str(cycle.get("linked_goal_id", "")).strip():
        return _failure_mode(
            "cognitive_surrender",
            "warning",
            "This loop can prepare broad actions; refresh human-owned judgment or link a goal ledger before treating it as self-steering.",
            "show_loop_status",
        )
    return _failure_mode("cognitive_surrender", "clear", "Authority and stop conditions are explicit enough for the current loop state.", "continue_loop")


def _failure_mode(mode_id: str, state: str, detail: str, next_action: str) -> dict[str, str]:
    return {
        "id": mode_id,
        "state": state,
        "detail": detail,
        "next_action": next_action,
    }


def _small_loop_guidance() -> dict[str, Any]:
    return {
        "schema_version": LOOP_SMALL_LOOP_GUIDANCE_SCHEMA,
        "principles": [
            {
                "id": "test_as_stop_signal",
                "label": "test as stop signal",
                "guidance": "Name the cheapest check that decides whether this step is done before the loop starts.",
            },
            {
                "id": "plan_execute_verify",
                "label": "plan -> execute -> verify",
                "guidance": "Keep each cycle shaped as one planned step, one execution or handoff step, and one verification signal.",
            },
            {
                "id": "one_task_at_a_time",
                "label": "one task at a time",
                "guidance": "Queue one concrete task per tick so failures can be traced and repaired without losing the goal.",
            },
        ],
        "claim_boundary": "Small-loop guidance is a Hermes-facing operating recipe, not proof that work ran.",
    }


def _permission_profile_option(profile: str) -> dict[str, Any]:
    allowed = sorted(_PROFILE_ALLOWED_ACTIONS[profile])
    descriptions = {
        "observe_only": "Research and plan only; no executor/runtime dispatch, repo edits, PRs, merge, or publishing.",
        "handoff_only": "Prepare research, planning, ultragoal, handoff, and external-posting drafts without observed execution claims.",
        "execute_with_gates": "Allow executor/runtime dispatch, repo edits, PRs, review, CI, and release-note work while merge and external posting stay gated.",
        "full_loop": "Allow the broadest local loop path while still requiring observed evidence and explicit external-production authority.",
    }
    return {
        "id": profile,
        "label": profile.replace("_", " "),
        "description": descriptions.get(profile, ""),
        "allowed_action_count": len(allowed),
        "allowed_actions": allowed,
    }


def _queue_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_id": str(item.get("queue_id", "")),
        "created_at": str(item.get("created_at", "")),
        "trigger": str(item.get("trigger", "")),
        "cadence": str(item.get("cadence", "")),
        "planned_action": str(item.get("planned_action", "")),
        "workflow_pattern": str(item.get("workflow_pattern", "")),
        "pipeline_step": str(item.get("pipeline_step", "")),
        "phase": str(item.get("phase", "")),
        "status": str(item.get("status", "")),
        "reason": str(item.get("reason", "")),
        "observed": bool(item.get("observed", False)),
        "observed_evidence_refs": _string_list(item.get("observed_evidence_refs", [])),
        "blocker_reason": str(item.get("blocker_reason", "")),
        "worktree_strategy": str(_dict_value(item, "worktree_plan").get("strategy", "")),
        "subagent_strategy": str(_dict_value(item, "subagent_plan").get("strategy", "")),
        "connector_strategy": str(_dict_value(item, "connector_plan").get("strategy", "")),
        "claim_boundary": str(item.get("claim_boundary", _runtime_claim_boundary())),
    }


def _queue_item_ref(cycle: dict[str, Any], queue_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    safe_queue_id = _storage_id(queue_id, "queue_id")
    runtime = _runtime_state(cycle.get("runtime"))
    queue = runtime.get("queue", [])
    for item in queue:
        if isinstance(item, dict) and str(item.get("queue_id", "")) == safe_queue_id:
            return runtime, item
    raise ValueError(f"loop queue item not found: {safe_queue_id}")


def _queue_handoff_text(cycle: dict[str, Any], item: dict[str, Any]) -> str:
    goal = _dict_value(cycle, "goal")
    worktree = _dict_value(item, "worktree_plan")
    subagent = _dict_value(item, "subagent_plan")
    connector = _dict_value(item, "connector_plan")
    lines = [
        f"Continue OMH loop `{cycle.get('loop_id', '')}`.",
        f"Goal: {goal.get('summary', '')}",
        f"Planned action: {item.get('planned_action', '')}",
        f"Workflow pattern: {item.get('workflow_pattern', 'single_step')}",
        f"Pipeline step: {_queue_item_pipeline_step(item)}",
        f"Phase: {item.get('phase', '')}",
        "",
        "Boundary:",
        _runtime_claim_boundary(),
    ]
    if worktree.get("strategy") != "none":
        lines.extend(
            [
                "",
                "Worktree plan:",
                f"- Path hint: {worktree.get('path_hint', '')}",
                f"- Branch hint: {worktree.get('branch_hint', '')}",
            ]
        )
    if subagent.get("strategy") != "none":
        lines.extend(
            [
                "",
                "Subagent plan:",
                f"- Role: {subagent.get('role', '')}",
                f"- Prompt seed: {subagent.get('prompt_seed', '')}",
                "- Result contract: return status, summary, evidence_refs, and next_actions; reference large outputs by path, hash, or evidence ref instead of pasting full context.",
            ]
        )
    if connector.get("strategy") != "none":
        lines.extend(
            [
                "",
                "Connector intent:",
                f"- Connector: {connector.get('connector', '')}",
                f"- Action: {connector.get('action', '')}",
            ]
        )
    verification = _dict_value(item, "verification_plan")
    if verification:
        lines.extend(
            [
                "",
                "Verification plan:",
                f"- Tier: {verification.get('tier', '')}",
                f"- Expected signal: {verification.get('expected_signal', '')}",
                f"- Failure action: {verification.get('failure_action', '')}",
                f"- Stop signal: {verification.get('stop_signal', '')}",
            ]
        )
    lines.extend(
        [
            "",
            "After an authorized wrapper or operator observes this work, record evidence with the loop queue observation contract. If it cannot proceed, block the queue item with a reason.",
        ]
    )
    return "\n".join(lines)


def _mark_queue_plans_observed(
    item: dict[str, Any],
    *,
    worktree_evidence_refs: list[str],
    subagent_evidence_refs: list[str],
    connector_evidence_refs: list[str],
) -> None:
    worktree = _dict_value(item, "worktree_plan")
    if worktree.get("strategy") != "none" and worktree_evidence_refs:
        worktree["created"] = True
        worktree["observed"] = True
        worktree["evidence_refs"] = list(worktree_evidence_refs)
    subagent = _dict_value(item, "subagent_plan")
    if subagent.get("strategy") != "none" and subagent_evidence_refs:
        subagent["dispatched"] = True
        subagent["observed"] = True
        subagent["evidence_refs"] = list(subagent_evidence_refs)
    connector = _dict_value(item, "connector_plan")
    if connector.get("strategy") != "none" and connector_evidence_refs:
        connector["dispatched"] = True
        connector["observed"] = True
        connector["evidence_refs"] = list(connector_evidence_refs)


def _validate_typed_plan_observation(
    errors: list[str],
    index: int,
    key: str,
    plan: dict[str, Any],
    *,
    primary_flag: str,
) -> None:
    refs = _string_list(plan.get("evidence_refs", []))
    if plan.get("strategy") == "none":
        if plan.get(primary_flag) is not False:
            errors.append(f"runtime.queue[{index}].{key}.{primary_flag} must be false when strategy is none")
        if plan.get("observed") is not False:
            errors.append(f"runtime.queue[{index}].{key}.observed must be false when strategy is none")
        if refs:
            errors.append(f"runtime.queue[{index}].{key}.evidence_refs must be empty when strategy is none")
        return
    primary_observed = plan.get(primary_flag) is True
    observed = plan.get("observed") is True
    if primary_observed != observed:
        errors.append(f"runtime.queue[{index}].{key}.{primary_flag} and observed must change together")
    if primary_observed or observed:
        if not refs:
            errors.append(f"runtime.queue[{index}].{key}.evidence_refs must include at least one typed evidence ref when observed")
        if plan.get(primary_flag) is not True:
            errors.append(f"runtime.queue[{index}].{key}.{primary_flag} must be true when typed evidence is observed")
        if plan.get("observed") is not True:
            errors.append(f"runtime.queue[{index}].{key}.observed must be true when typed evidence is observed")


def _validate_unobserved_plan(
    errors: list[str],
    index: int,
    key: str,
    plan: dict[str, Any],
    *,
    primary_flag: str,
) -> None:
    if plan.get(primary_flag) is not False:
        errors.append(f"runtime.queue[{index}].{key}.{primary_flag} must be false before observation")
    if plan.get("observed") is not False:
        errors.append(f"runtime.queue[{index}].{key}.observed must be false before observation")
    if _string_list(plan.get("evidence_refs", [])):
        errors.append(f"runtime.queue[{index}].{key}.evidence_refs must be empty before observation")


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
        pattern = str(item.get("workflow_pattern", ""))
        if pattern and pattern not in LOOP_WORKFLOW_PATTERNS:
            errors.append(f"runtime.queue[{index}].workflow_pattern is unsupported")
        pipeline_step = str(item.get("pipeline_step", ""))
        if pipeline_step and pipeline_step not in LOOP_PIPELINE_STEPS:
            errors.append(f"runtime.queue[{index}].pipeline_step is unsupported")
        engineering = item.get("loop_engineering")
        if engineering is not None:
            if not isinstance(engineering, dict):
                errors.append(f"runtime.queue[{index}].loop_engineering must be an object")
            elif engineering.get("schema_version") != LOOP_ENGINEERING_SCHEMA:
                errors.append(f"runtime.queue[{index}].loop_engineering.schema_version must be {LOOP_ENGINEERING_SCHEMA}")
        plans: dict[str, dict[str, Any]] = {}
        for key in ("worktree_plan", "subagent_plan", "connector_plan"):
            plan = item.get(key)
            if not isinstance(plan, dict):
                errors.append(f"runtime.queue[{index}].{key} must be an object")
                continue
            plans[key] = plan
            if key == "subagent_plan" and plan.get("strategy") != "none":
                contract = plan.get("result_contract")
                if not isinstance(contract, dict):
                    errors.append(f"runtime.queue[{index}].subagent_plan.result_contract must be an object")
                elif contract.get("schema_version") != LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA:
                    errors.append(
                        f"runtime.queue[{index}].subagent_plan.result_contract.schema_version must be {LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA}"
                    )
        verification_plan = item.get("verification_plan")
        if verification_plan is not None:
            _validate_verification_plan(errors, index, verification_plan)
        if item.get("status") == "observed":
            if item.get("observed") is not True:
                errors.append(f"runtime.queue[{index}].observed must be true when status is observed")
            evidence_refs = item.get("observed_evidence_refs")
            if not isinstance(evidence_refs, list) or not evidence_refs or not all(str(ref).strip() for ref in evidence_refs):
                errors.append(f"runtime.queue[{index}].observed_evidence_refs must include at least one evidence ref when observed")
            worktree_plan = plans.get("worktree_plan", {})
            _validate_typed_plan_observation(errors, index, "worktree_plan", worktree_plan, primary_flag="created")
            subagent_plan = plans.get("subagent_plan", {})
            _validate_typed_plan_observation(errors, index, "subagent_plan", subagent_plan, primary_flag="dispatched")
            connector_plan = plans.get("connector_plan", {})
            _validate_typed_plan_observation(errors, index, "connector_plan", connector_plan, primary_flag="dispatched")
        elif item.get("status") == "blocked":
            if not str(item.get("blocker_reason", "")).strip():
                errors.append(f"runtime.queue[{index}].blocker_reason is required when status is blocked")
            if item.get("observed") is not False:
                errors.append(f"runtime.queue[{index}].observed must be false unless status is observed")
            _validate_unobserved_plan(errors, index, "worktree_plan", plans.get("worktree_plan", {}), primary_flag="created")
            _validate_unobserved_plan(errors, index, "subagent_plan", plans.get("subagent_plan", {}), primary_flag="dispatched")
            _validate_unobserved_plan(errors, index, "connector_plan", plans.get("connector_plan", {}), primary_flag="dispatched")
        else:
            if item.get("observed") is not False:
                errors.append(f"runtime.queue[{index}].observed must be false unless status is observed")
            _validate_unobserved_plan(errors, index, "worktree_plan", plans.get("worktree_plan", {}), primary_flag="created")
            _validate_unobserved_plan(errors, index, "subagent_plan", plans.get("subagent_plan", {}), primary_flag="dispatched")
            _validate_unobserved_plan(errors, index, "connector_plan", plans.get("connector_plan", {}), primary_flag="dispatched")
        if item.get("status") in {"blocked_by_permission", "blocked_by_wait"}:
            for key, plan in plans.items():
                if plan.get("strategy") != "none":
                    errors.append(f"runtime.queue[{index}].{key}.strategy must be none while blocked")
    return errors


def _validate_verification_plan(errors: list[str], index: int, value: object) -> None:
    if not isinstance(value, dict):
        errors.append(f"runtime.queue[{index}].verification_plan must be an object")
        return
    if value.get("schema_version") != LOOP_VERIFICATION_PLAN_SCHEMA:
        errors.append(f"runtime.queue[{index}].verification_plan.schema_version must be {LOOP_VERIFICATION_PLAN_SCHEMA}")
    tier = str(value.get("tier", ""))
    if tier not in LOOP_VERIFICATION_TIERS:
        errors.append(f"runtime.queue[{index}].verification_plan.tier is unsupported")
    evidence = value.get("evidence_required")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        errors.append(f"runtime.queue[{index}].verification_plan.evidence_required must be a string list")
    for key in ("expected_signal", "failure_action", "stop_signal", "claim_boundary"):
        if not isinstance(value.get(key), str) or not str(value.get(key, "")).strip():
            errors.append(f"runtime.queue[{index}].verification_plan.{key} must be a non-empty string")


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
