from __future__ import annotations

import hashlib
from typing import Any

from ..coding_contracts import (
    CODING_EXECUTOR_HANDOFF_TARGETS,
    CODING_RUNTIME_HANDOFF_TARGETS,
    EXECUTOR_HANDOFF_SCHEMA_VERSION,
    PROMPT_HANDOFF_SCHEMA_VERSION,
    RUNTIME_HANDOFF_SCHEMA_VERSION,
)
from ..executors import (
    DISPATCH_POLICIES,
    EXECUTOR_PROFILES,
    HERMES_CODING_TEAM_START_MODE_IDS,
    HERMES_CODING_TEAM_STATUS_LADDER,
    HERMES_CODING_TEAM_WRAPPER_ACTIONS,
    WORK_OWNER_MODES,
)
from ..harness_quality import HARNESS_QUALITY_KEYS, HARNESS_QUALITY_SCHEMA_VERSION
from ..isolation import ISOLATION_SCHEMA_VERSION
from ..local_store import utc_now
from ..memory import validate_handoff_context_blocked, validate_handoff_context_pack


SCHEMA_VERSION = 1
RUN_STATUSES = ("started", "prepared", "completed", "blocked", "failed", "unknown")
PRIVACY_MODES = ("metadata_only",)
RUN_ARTIFACT_KINDS = ("workflow_run", "prepared_coding_delegation")
RUN_PHASES = ("runtime", "prepared", "unknown")
RUN_OBSERVATION_STATUSES = ("unknown", "observed", "not_observed", "prepared_not_observed")
DELEGATION_RESULTS = ("completed", "blocked", "failed", "not_available", "not_observed")
OBSERVED_RESULTS = ("completed", "blocked", "failed")
UNOBSERVED_RESULTS = ("not_available", "not_observed")
EVENT_LEVELS = ("debug", "info", "warning", "error")
WRAPPER_COMPLETION_STATUSES = ("started", "completed", "blocked", "failed", "unknown")
REVIEW_STATUSES = ("not_required", "pending", "passed", "failed", "blocked", "not_observed")
CI_STATUSES = ("not_required", "pending", "passed", "failed", "blocked", "not_observed")
CI_CHECK_STATUSES = ("passed", "failed", "blocked", "pending", "not_required")
MERGE_STATUSES = ("not_ready", "ready", "merged", "blocked", "not_observed")
RUNTIME_OBSERVATION_SCHEMA_VERSION = "runtime_observation/v1"
RUNTIME_OBSERVATION_RECORD_TYPE = "runtime_observation"
RUNTIME_OBSERVATION_TARGET_TYPES = ("run", "wrapper_session")
RUNTIME_OBSERVATION_EVENTS = (
    "runtime_start",
    "worktree_creation",
    "worker_dispatch",
    "worker_result",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)
RUNTIME_OBSERVATION_STATUSES = ("observed", "blocked", "failed", "not_observed")
RUNTIME_OBSERVATION_RECORD_KEYS = (
    "schema_version",
    "record_type",
    "target_type",
    "target_id",
    "updated_at",
    "runtime_profile",
    "event_type",
    "status",
    "observed",
    "participants",
    "worktree_ref",
    "worker_ref",
    "evidence_refs",
    "summary",
    "claim_boundary",
)
ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
ROUTE_CONFIDENCES = ("low", "medium", "high")
ROUTING_RECOMMENDATION_KEYS = ("skill", "score", "confidence", "matched")
CODING_DELEGATION_SCHEMA_VERSION = "coding_delegation/v1"
CODING_DELEGATION_RECORD_TYPE = "coding_delegation"
CODING_DELEGATION_ACTIONS = ("delegate", "clarify", "fallback")
CODING_DELEGATION_INTENTS = ("coding", "cleanup", "review", "planning", "diagnostics", "docs", "unknown")
CODING_DELEGATION_STATUSES = ("prepared_not_observed",)
CODING_WORK_OWNER_MODES = WORK_OWNER_MODES
CODING_SELECTED_EXECUTOR_PROFILES = EXECUTOR_PROFILES
CODING_DISPATCH_POLICIES = DISPATCH_POLICIES
TARGET_SOURCE_METADATA_KEYS = (
    "agent_ref",
    "target_ref",
    "runtime_ref",
    "hermes_home",
    "agent_count",
    "target_count",
)
CODING_SOURCE_METADATA_KEYS = (
    "source_event_id",
    "channel_ref",
    "user_ref",
    "timestamp",
    "render_profile",
    "plan_artifact_path",
    "plan_artifact_sha256",
    "plan_artifact_status",
    "plan_task_sha256",
    "plan_task_length",
    *TARGET_SOURCE_METADATA_KEYS,
)
CODING_RECOMMENDATION_KEYS = ("skill", "score", "confidence", "matched")
CODING_EXECUTOR_SELECTION_KEYS = ("status", "choice_required", "options")
CODING_EXECUTOR_SELECTION_STATUSES = (
    "retained_hermes",
    "executor_choice_required",
    "handoff_prepared",
    "runtime_handoff_prepared",
    "prompt_handoff_prepared",
)
CODING_DELEGATION_RECORD_KEYS = (
    "schema_version",
    "record_type",
    "updated_at",
    "source",
    "action",
    "intent",
    "recommended_workflow",
    "recommended_harness",
    "executor_profile",
    "work_owner_mode",
    "selected_executor_profile",
    "dispatch_policy",
    "dispatchable",
    "executor_selection",
    "review_required",
    "review_workflow",
    "message_sha256",
    "message_length",
    "source_metadata",
    "recommendation_evidence",
    "harness_quality",
    "executor_handoff",
    "runtime_handoff",
    "prompt_handoff",
    "isolation_plan",
    "acceptance_criteria",
    "verification",
    "plan_artifact",
    "status",
)
CODING_PLAN_ARTIFACT_KEYS = (
    "path",
    "kind",
    "schema_version",
    "status",
    "sha256",
    "task_statement_sha256",
    "task_statement_length",
)
ISOLATION_STRATEGIES = ("same_workspace_ok", "worktree_recommended", "worktree_required")
ISOLATION_STATUSES = ("prepared_not_observed",)
ISOLATION_RISK_LEVELS = ("low", "medium", "high")
ISOLATION_PLAN_KEYS = (
    "schema_version",
    "status",
    "strategy",
    "risk_level",
    "reason_codes",
    "workspace_policy",
    "session_binding",
    "required_before",
    "recommended_when",
    "wrapper_actions",
    "observation_events",
    "not_observed_by_omh",
    "claim_boundary",
)
CODING_EXECUTOR_HANDOFF_SCHEMA_VERSION = EXECUTOR_HANDOFF_SCHEMA_VERSION
CODING_RUNTIME_HANDOFF_SCHEMA_VERSION = RUNTIME_HANDOFF_SCHEMA_VERSION
CODING_PROMPT_HANDOFF_SCHEMA_VERSION = PROMPT_HANDOFF_SCHEMA_VERSION
CODING_EXECUTOR_TARGETS = CODING_EXECUTOR_HANDOFF_TARGETS
CODING_RUNTIME_TARGETS = CODING_RUNTIME_HANDOFF_TARGETS
CODING_EXECUTOR_HANDOFF_KEYS = (
    "schema_version",
    "work_owner_mode",
    "selected_executor_profile",
    "dispatch_policy",
    "dispatchable",
    "executor_target",
    "handoff_mode",
    "send_action",
    "codex_skill",
    "codex_invocation",
    "executor_local_capability_strategy",
    "status",
    "recording_contract",
    "dispatch_contract",
    "prompt_template",
    "execution_brief",
    "isolation_plan",
    "scope",
    "non_goals",
    "acceptance_criteria",
    "verification",
    "review",
    "report_contract",
    "evidence_contract",
    "executor_readiness",
    "harness_quality",
    "context_pack",
    "context_pack_blocked",
)
CODING_PROMPT_HANDOFF_KEYS = (
    "schema_version",
    "work_owner_mode",
    "selected_executor_profile",
    "dispatchable",
    "invocation",
    "executor_local_capability_strategy",
    "status",
    "recording_contract",
    "dispatch_contract",
    "prompt_template",
    "isolation_plan",
    "scope",
    "non_goals",
    "acceptance_criteria",
    "verification",
    "review",
    "evidence_contract",
    "executor_readiness",
    "harness_quality",
    "context_pack",
    "context_pack_blocked",
)
CODING_RUNTIME_HANDOFF_KEYS = (
    "schema_version",
    "work_owner_mode",
    "selected_executor_profile",
    "runtime_profile",
    "dispatchable",
    "invocation",
    "executor_local_capability_strategy",
    "status",
    "recording_contract",
    "dispatch_contract",
    "prompt_template",
    "runtime_brief",
    "isolation_plan",
    "runtime_templates",
    "team_contract",
    "worktree_contract",
    "observation_contract",
    "scope",
    "non_goals",
    "acceptance_criteria",
    "verification",
    "review",
    "evidence_contract",
    "executor_readiness",
    "harness_quality",
    "hermes_coding_team_path",
    "context_pack",
    "context_pack_blocked",
)
CODING_PROMPT_HANDOFF_INVOCATION_KEYS = (
    "mode",
    "tool_label",
    "dispatch_text_template",
    "message_placeholder",
    "wrapper_note",
)
CODING_RUNTIME_HANDOFF_INVOCATION_KEYS = CODING_PROMPT_HANDOFF_INVOCATION_KEYS
CODING_RUNTIME_PROFILE_KEYS = (
    "profile",
    "label",
    "runtime_family",
    "underlying_agent",
    "supports_team_swarm",
    "supports_tmux_workers",
    "supports_worker_protocol",
    "supports_worktree_guidance",
    "supports_hermes_coding_team_path",
    "requires_operator_runtime",
)
CODING_RUNTIME_TEMPLATE_KEYS = ("label", "syntax", "command_template", "when_to_use", "observed_event")
CODING_RUNTIME_OBSERVATION_CONTRACT_KEYS = (
    "record_schema",
    "record_with",
    "allowed_events",
    "status_ladder",
    "claim_boundary",
)
EXECUTOR_LOCAL_CAPABILITY_STRATEGY_SCHEMA_VERSION = "executor_local_capability_strategy/v1"
EXECUTOR_LOCAL_CAPABILITY_STRATEGY_KEYS = (
    "schema_version",
    "profile",
    "mode",
    "installation_observed",
    "execution_observed",
    "preferred_sources",
    "stage_guidance",
    "examples_if_available",
    "selection_rule",
    "fallback",
    "claim_boundary",
)
EXECUTOR_READINESS_SCHEMA_VERSION = "executor_readiness/v1"
EXECUTOR_READINESS_STATUSES = ("choice_required", "not_observed", "not_applicable", "missing", "blocked", "ready")
CODING_RUNTIME_EVIDENCE_CONTRACT_KEYS = ("prepared_is_not", "observed_required_for")
CODING_RUNTIME_PREPARED_BOUNDARIES = (
    "runtime_start",
    "worktree_creation",
    "worker_dispatch",
    "implementation",
    "verification",
    "review",
    "ci",
    "merge",
)
CODING_RUNTIME_OBSERVED_BOUNDARIES = (
    "runtime_start",
    "worktree_creation",
    "worker_dispatch",
    "worker_result",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)
WRAPPER_SESSION_SCHEMA_VERSION = "wrapper_session/v1"
WRAPPER_SESSION_RECORD_TYPE = "wrapper_session"
WRAPPER_SESSION_STATUSES = (
    "plan_presented",
    "clarifying",
    "routed",
    "plan_accepted",
    "revision_requested",
    "cancelled",
    "executor_choice_required",
    "executor_selected",
    "prompt_handoff_prepared",
    "runtime_handoff_prepared",
    "handoff_prepared",
)
WRAPPER_SESSION_DECISIONS = ("none", "plan_accepted", "plan_revision_requested", "plan_cancelled")
WRAPPER_SESSION_SOURCE_METADATA_KEYS = CODING_SOURCE_METADATA_KEYS
WRAPPER_SESSION_ROUTE_KEYS = ("action", "selected_skill", "selected_harness", "confidence", "score")
WRAPPER_SESSION_PLAN_KEYS = ("status", "recommended_workflow", "recommended_harness", "coding_delegate_available")
WRAPPER_SESSION_PROVENANCE_SCHEMA_VERSION = "wrapper_session_provenance/v1"
WRAPPER_SESSION_PRODUCERS = ("wrapper_backend", "plugin_tool")
WRAPPER_SESSION_PROVENANCE_KEYS = (
    "schema_version",
    "producer",
    "producer_detail",
    "observed_by_host",
    "claim_boundary",
)
WRAPPER_SESSION_AUTHORITY_SESSION_OWNS = (
    "chat_continuity",
    "route_summary",
    "plan_decision",
    "linked_run_id",
)
WRAPPER_SESSION_AUTHORITY_RUN_LEDGER_OWNS = (
    "prepared_handoff",
    "dispatch",
    "executor_result",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)
WRAPPER_SESSION_STATUS_DECISIONS = {
    "plan_presented": "none",
    "clarifying": "none",
    "routed": "none",
    "plan_accepted": "plan_accepted",
    "executor_choice_required": "plan_accepted",
    "executor_selected": "plan_accepted",
    "prompt_handoff_prepared": "plan_accepted",
    "runtime_handoff_prepared": "plan_accepted",
    "revision_requested": "plan_revision_requested",
    "cancelled": "plan_cancelled",
    "handoff_prepared": "plan_accepted",
}
WRAPPER_SESSION_RECORD_KEYS = (
    "schema_version",
    "record_type",
    "session_id",
    "thread_key",
    "source",
    "source_metadata",
    "message_sha256",
    "message_length",
    "created_at",
    "updated_at",
    "status",
    "decision",
    "route",
    "plan",
    "work_owner_mode",
    "selected_executor_profile",
    "dispatch_policy",
    "prompt_handoff",
    "runtime_handoff",
    "current_run_id",
    "record_provenance",
    "redaction_policy",
    "authority",
)


def build_run_record(metadata: dict[str, Any], run_id: str) -> dict[str, Any]:
    status = metadata.get("status", "unknown")
    if status not in RUN_STATUSES:
        raise ValueError(f"unsupported run status: {status}")
    privacy = metadata.get("privacy", "metadata_only")
    if privacy not in PRIVACY_MODES:
        raise ValueError(f"unsupported privacy mode: {privacy}")
    skill = str(metadata.get("skill", "unknown"))
    harness = str(metadata.get("harness", "unknown"))
    created_at = str(metadata.get("created_at") or utc_now())
    artifact_kind = str(metadata.get("artifact_kind", "workflow_run"))
    phase = str(metadata.get("phase", "runtime"))
    observation_status = str(metadata.get("observation_status", "unknown"))
    if artifact_kind not in RUN_ARTIFACT_KINDS:
        raise ValueError(f"unsupported run artifact_kind: {artifact_kind}")
    if phase not in RUN_PHASES:
        raise ValueError(f"unsupported run phase: {phase}")
    if observation_status not in RUN_OBSERVATION_STATUSES:
        raise ValueError(f"unsupported run observation_status: {observation_status}")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "skill": skill,
        "harness": harness,
        "trigger": metadata.get("trigger", ""),
        "status": status,
        "artifact_kind": artifact_kind,
        "phase": phase,
        "observation_status": observation_status,
        "privacy": privacy,
        "inputs_summary": metadata.get("inputs_summary", ""),
        "outputs_summary": metadata.get("outputs_summary", ""),
        "verification_summary": metadata.get("verification_summary", ""),
    }


def build_event_record(event: dict[str, Any]) -> dict[str, Any]:
    item = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": event.get("timestamp") or utc_now(),
        "event": event.get("event", "event"),
        "level": event.get("level", "info"),
        "message": event.get("message", ""),
    }
    if "data" in event:
        item["data"] = event["data"]
    return item


def validate_delegation_result(observed: bool, result: str) -> None:
    if observed and result not in OBSERVED_RESULTS:
        raise ValueError("observed delegation requires result completed, blocked, or failed")
    if not observed and result not in UNOBSERVED_RESULTS:
        raise ValueError("unobserved delegation requires result not_available or not_observed")


def build_delegation_record(delegation: dict[str, Any]) -> dict[str, Any]:
    result = delegation.get("result", "not_observed")
    if result not in DELEGATION_RESULTS:
        raise ValueError(f"unsupported delegation result: {result}")
    observed = bool(delegation.get("observed", False))
    validate_delegation_result(observed, result)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "requested": bool(delegation.get("requested", False)),
        "observed": observed,
        "participants": list(delegation.get("participants", [])),
        "result": result,
        "evidence_refs": list(delegation.get("evidence_refs", [])),
        "message": delegation.get("message", ""),
    }


def build_wrapper_record(wrapper: dict[str, Any]) -> dict[str, Any]:
    status = wrapper.get("completion_status", "unknown")
    if status not in WRAPPER_COMPLETION_STATUSES:
        raise ValueError(f"unsupported wrapper completion status: {status}")
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "prompt_dispatched": bool(wrapper.get("prompt_dispatched", False)),
        "hermes_response_observed": bool(wrapper.get("hermes_response_observed", False)),
        "verification_observed": bool(wrapper.get("verification_observed", False)),
        "completion_status": status,
        "unobserved_gaps": list(wrapper.get("unobserved_gaps", [])),
        "message": wrapper.get("message", ""),
    }


def build_review_record(review: dict[str, Any]) -> dict[str, Any]:
    status = str(review.get("status", "not_observed"))
    if status not in REVIEW_STATUSES:
        raise ValueError(f"unsupported review status: {status}")
    required = bool(review.get("required", status != "not_required"))
    observed = bool(review.get("observed", status not in {"pending", "not_observed"}))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(review.get("run_id", "")),
        "updated_at": str(review.get("updated_at") or utc_now()),
        "required": required,
        "observed": observed,
        "status": status,
        "reviewer": str(review.get("reviewer", "")),
        "evidence_refs": _compact_string_list(review.get("evidence_refs", [])),
        "summary": str(review.get("summary", "")),
    }
    errors = validate_review_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_ci_record(ci: dict[str, Any]) -> dict[str, Any]:
    status = str(ci.get("status", "not_observed"))
    if status not in CI_STATUSES:
        raise ValueError(f"unsupported CI status: {status}")
    required = bool(ci.get("required", status != "not_required"))
    observed = bool(ci.get("observed", status not in {"pending", "not_observed"}))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(ci.get("run_id", "")),
        "updated_at": str(ci.get("updated_at") or utc_now()),
        "required": required,
        "observed": observed,
        "status": status,
        "provider": str(ci.get("provider", "")),
        "checks": _compact_ci_checks(ci.get("checks", [])),
        "evidence_refs": _compact_string_list(ci.get("evidence_refs", [])),
        "summary": str(ci.get("summary", "")),
    }
    errors = validate_ci_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_merge_record(merge: dict[str, Any]) -> dict[str, Any]:
    status = str(merge.get("status", "not_observed"))
    if status not in MERGE_STATUSES:
        raise ValueError(f"unsupported merge status: {status}")
    observed = bool(merge.get("observed", status in {"ready", "merged", "blocked"}))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(merge.get("run_id", "")),
        "updated_at": str(merge.get("updated_at") or utc_now()),
        "observed": observed,
        "ready": bool(merge.get("ready", status in {"ready", "merged"})),
        "merged": bool(merge.get("merged", status == "merged")),
        "status": status,
        "target_branch": str(merge.get("target_branch", "")),
        "merge_commit": str(merge.get("merge_commit", "")),
        "evidence_refs": _compact_string_list(merge.get("evidence_refs", [])),
        "summary": str(merge.get("summary", "")),
    }
    errors = validate_merge_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_runtime_observation_record(observation: dict[str, Any]) -> dict[str, Any]:
    target_type = str(observation.get("target_type", "run"))
    event_type = str(observation.get("event_type", "runtime_start"))
    status = str(observation.get("status", "observed"))
    record = {
        "schema_version": RUNTIME_OBSERVATION_SCHEMA_VERSION,
        "record_type": RUNTIME_OBSERVATION_RECORD_TYPE,
        "target_type": target_type,
        "target_id": str(observation.get("target_id", "")),
        "updated_at": str(observation.get("updated_at") or utc_now()),
        "runtime_profile": str(observation.get("runtime_profile", "")),
        "event_type": event_type,
        "status": status,
        "observed": status != "not_observed",
        "participants": _compact_string_list(observation.get("participants", [])),
        "worktree_ref": str(observation.get("worktree_ref", "")),
        "worker_ref": str(observation.get("worker_ref", "")),
        "evidence_refs": _compact_string_list(observation.get("evidence_refs", [])),
        "summary": str(observation.get("summary", "")),
        "claim_boundary": (
            "Runtime observation records only describe events the wrapper/operator reports. "
            "They do not prove unrecorded work, review, CI, merge, worker, or worktree steps."
        ),
    }
    errors = validate_runtime_observation_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_routing_record(routing: dict[str, Any]) -> dict[str, Any]:
    action = routing.get("action", "fallback")
    if action not in ROUTE_ACTIONS:
        raise ValueError(f"unsupported routing action: {action}")
    confidence = routing.get("confidence", "low")
    if confidence not in ROUTE_CONFIDENCES:
        raise ValueError(f"unsupported routing confidence: {confidence}")
    threshold = routing.get("threshold", "high")
    if threshold not in ROUTE_CONFIDENCES:
        raise ValueError(f"unsupported routing threshold: {threshold}")
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "source": str(routing.get("source", "generic")),
        "action": action,
        "selected_skill": str(routing.get("selected_skill", "oh-my-hermes")),
        "selected_harness": str(routing.get("selected_harness", "coding-handling")),
        "candidate_skill": str(routing.get("candidate_skill", "")),
        "candidate_harness": str(routing.get("candidate_harness", "")),
        "confidence": confidence,
        "score": int(routing.get("score", 0)),
        "threshold": threshold,
        "explicit": bool(routing.get("explicit", False)),
        "ambiguous": bool(routing.get("ambiguous", False)),
        "reason": str(routing.get("reason", "")),
        "message_sha256": str(routing.get("message_sha256", "")),
        "message_length": int(routing.get("message_length", 0)),
        "source_event_id": str(routing.get("source_event_id", "")),
        "channel_ref": str(routing.get("channel_ref", "")),
        "user_ref": str(routing.get("user_ref", "")),
        "recommendations": _compact_routing_recommendations(routing.get("recommendations", [])),
    }


def build_coding_delegation_record(delegation: dict[str, Any]) -> dict[str, Any]:
    nested = delegation.get("delegation", {})
    if not isinstance(nested, dict):
        nested = {}
    message = delegation.get("message", "")
    message_text = message if isinstance(message, str) else ""
    record = {
        "schema_version": CODING_DELEGATION_SCHEMA_VERSION,
        "record_type": CODING_DELEGATION_RECORD_TYPE,
        "updated_at": utc_now(),
        "source": str(delegation.get("source", "generic")),
        "action": str(nested.get("action", delegation.get("action", "fallback"))),
        "intent": str(nested.get("intent", delegation.get("intent", "unknown"))),
        "recommended_workflow": str(nested.get("recommended_workflow", delegation.get("recommended_workflow", "oh-my-hermes"))),
        "recommended_harness": str(nested.get("recommended_harness", delegation.get("recommended_harness", "coding-handling"))),
        "executor_profile": str(nested.get("executor_profile", delegation.get("executor_profile", "router"))),
        "work_owner_mode": str(delegation.get("work_owner_mode", "retained_hermes")),
        "selected_executor_profile": _optional_string(delegation.get("selected_executor_profile")),
        "dispatch_policy": str(delegation.get("dispatch_policy", "prepare_only")),
        "dispatchable": bool(delegation.get("dispatchable", False)),
        "executor_selection": _compact_executor_selection(delegation.get("executor_selection", {})),
        "review_required": bool(nested.get("review_required", delegation.get("review_required", False))),
        "review_workflow": _optional_string(nested.get("review_workflow", delegation.get("review_workflow"))),
        "message_sha256": str(delegation.get("message_sha256", "")),
        "message_length": int(delegation.get("message_length", len(message_text))),
        "source_metadata": _compact_source_metadata(delegation.get("source_metadata", {})),
        "recommendation_evidence": _compact_coding_recommendations(
            delegation.get("recommendation_evidence", delegation.get("recommendations", []))
        ),
        "acceptance_criteria": _compact_string_list(nested.get("acceptance_criteria", delegation.get("acceptance_criteria", []))),
        "verification": _compact_string_list(nested.get("verification", delegation.get("verification", []))),
        "status": str(delegation.get("status", "prepared_not_observed")),
    }
    harness_quality = _compact_harness_quality(delegation.get("harness_quality", {}))
    if harness_quality:
        record["harness_quality"] = harness_quality
    executor_handoff = _compact_executor_handoff(delegation.get("executor_handoff"))
    if executor_handoff:
        record["executor_handoff"] = executor_handoff
    runtime_handoff = _compact_runtime_handoff(delegation.get("runtime_handoff"))
    if runtime_handoff:
        record["runtime_handoff"] = runtime_handoff
    prompt_handoff = _compact_prompt_handoff(delegation.get("prompt_handoff"))
    if prompt_handoff:
        record["prompt_handoff"] = prompt_handoff
    isolation_plan = _compact_isolation_plan(delegation.get("isolation_plan"))
    if isolation_plan:
        record["isolation_plan"] = isolation_plan
    plan_artifact = _compact_plan_artifact(delegation.get("plan_artifact"))
    if plan_artifact:
        record["plan_artifact"] = plan_artifact
    if not record["message_sha256"] and message_text:
        record["message_sha256"] = hashlib.sha256(message_text.encode("utf-8")).hexdigest()
    errors = validate_coding_delegation_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_wrapper_session_record(session: dict[str, Any]) -> dict[str, Any]:
    status = str(session.get("status", "plan_presented"))
    if status not in WRAPPER_SESSION_STATUSES:
        raise ValueError(f"unsupported wrapper session status: {status}")
    decision = str(session.get("decision", "none"))
    if decision not in WRAPPER_SESSION_DECISIONS:
        raise ValueError(f"unsupported wrapper session decision: {decision}")
    created_at = str(session.get("created_at") or utc_now())
    record = {
        "schema_version": WRAPPER_SESSION_SCHEMA_VERSION,
        "record_type": WRAPPER_SESSION_RECORD_TYPE,
        "session_id": str(session.get("session_id", "")),
        "thread_key": str(session.get("thread_key", "")),
        "source": str(session.get("source", "generic")),
        "source_metadata": _compact_wrapper_session_source_metadata(session.get("source_metadata", {})),
        "message_sha256": str(session.get("message_sha256", "")),
        "message_length": int(session.get("message_length", 0)),
        "created_at": created_at,
        "updated_at": str(session.get("updated_at") or utc_now()),
        "status": status,
        "decision": decision,
        "route": _compact_wrapper_session_route(session.get("route", {})),
        "plan": _compact_wrapper_session_plan(session.get("plan", {})),
        "work_owner_mode": str(session.get("work_owner_mode", "external_executor")),
        "selected_executor_profile": _optional_string(session.get("selected_executor_profile")),
        "dispatch_policy": str(session.get("dispatch_policy", "ask_before_dispatch")),
        "prompt_handoff": _compact_prompt_handoff(session.get("prompt_handoff")),
        "runtime_handoff": _compact_runtime_handoff(session.get("runtime_handoff")),
        "current_run_id": str(session.get("current_run_id", "")),
        "record_provenance": _compact_wrapper_session_provenance(session.get("record_provenance", {})),
        "redaction_policy": "metadata_only",
        "authority": {
            "session_owns": list(WRAPPER_SESSION_AUTHORITY_SESSION_OWNS),
            "run_ledger_owns": list(WRAPPER_SESSION_AUTHORITY_RUN_LEDGER_OWNS),
        },
    }
    errors = validate_wrapper_session_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def _compact_routing_recommendations(recommendations: Any) -> list[dict[str, Any]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        matched = item.get("matched", [])
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": int(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
            }
        )
    return compact


def _compact_coding_recommendations(recommendations: Any) -> list[dict[str, Any]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        matched = item.get("matched", [])
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": int(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
            }
        )
    return compact


def _compact_source_metadata(metadata: Any) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    return {key: str(metadata[key]) for key in CODING_SOURCE_METADATA_KEYS if key in metadata and str(metadata[key])}


def _compact_wrapper_session_source_metadata(metadata: Any) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: str(metadata[key])
        for key in WRAPPER_SESSION_SOURCE_METADATA_KEYS
        if key in metadata and str(metadata[key])
    }


def _compact_wrapper_session_route(route: Any) -> dict[str, Any]:
    if not isinstance(route, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in WRAPPER_SESSION_ROUTE_KEYS:
        if key not in route:
            continue
        compact[key] = int(route[key]) if key == "score" else str(route[key])
    return compact


def _compact_wrapper_session_plan(plan: Any) -> dict[str, str]:
    if not isinstance(plan, dict):
        return {}
    return {key: str(plan[key]) for key in WRAPPER_SESSION_PLAN_KEYS if key in plan and str(plan[key])}


def _compact_wrapper_session_provenance(provenance: Any) -> dict[str, Any]:
    if not isinstance(provenance, dict):
        provenance = {}
    producer = str(provenance.get("producer") or "wrapper_backend")
    if producer not in WRAPPER_SESSION_PRODUCERS:
        producer = "wrapper_backend"
    producer_detail = str(provenance.get("producer_detail") or "omh wrapper session backend")
    return {
        "schema_version": WRAPPER_SESSION_PROVENANCE_SCHEMA_VERSION,
        "producer": producer,
        "producer_detail": producer_detail[:160],
        "observed_by_host": bool(provenance.get("observed_by_host", False)),
        "claim_boundary": (
            "Record provenance identifies who wrote this metadata-only wrapper session. "
            "It is not executor dispatch, implementation, verification, review, CI, or merge evidence."
        ),
    }


def _compact_executor_selection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "retained_hermes", "choice_required": False, "options": []}
    options = value.get("options", [])
    compact_options: list[dict[str, Any]] = []
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            compact_options.append(
                {
                    "profile": str(option.get("profile", "")),
                    "label": str(option.get("label", "")),
                    "work_owner_mode": str(option.get("work_owner_mode", "")),
                    "dispatchable": bool(option.get("dispatchable", False)),
                    "recommended_for": str(option.get("recommended_for", "")),
                }
            )
    return {
        "status": str(value.get("status", "retained_hermes")),
        "choice_required": bool(value.get("choice_required", False)),
        "options": compact_options,
    }


def _compact_string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value) for value in values if str(value)]


def _compact_ci_checks(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, (list, tuple)):
        return []
    checks: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, dict):
            name = str(value.get("name", ""))
            status = str(value.get("status", "pending"))
        else:
            text = str(value)
            name, _, status = text.partition(":")
            status = status or "pending"
        checks.append({"name": name, "status": status})
    return checks


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _compact_executor_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    compact: dict[str, Any] = {
        "schema_version": str(value.get("schema_version", "")),
        "work_owner_mode": str(value.get("work_owner_mode", "")),
        "selected_executor_profile": str(value.get("selected_executor_profile", "")),
        "dispatch_policy": str(value.get("dispatch_policy", "")),
        "dispatchable": bool(value.get("dispatchable", False)),
        "executor_target": str(value.get("executor_target", "")),
        "handoff_mode": str(value.get("handoff_mode", "")),
        "send_action": str(value.get("send_action", "")),
        "codex_skill": str(value.get("codex_skill", "")),
        "codex_invocation": _compact_codex_invocation(value.get("codex_invocation", {})),
        "status": str(value.get("status", "")),
        "recording_contract": str(value.get("recording_contract", "")),
        "dispatch_contract": str(value.get("dispatch_contract", "")),
        "prompt_template": str(value.get("prompt_template", "")),
        "execution_brief": _compact_execution_brief(value.get("execution_brief", {})),
        "isolation_plan": _compact_isolation_plan(value.get("isolation_plan")),
        "scope": _compact_string_list(value.get("scope", [])),
        "non_goals": _compact_string_list(value.get("non_goals", [])),
        "acceptance_criteria": _compact_string_list(value.get("acceptance_criteria", [])),
        "verification": _compact_string_list(value.get("verification", [])),
        "report_contract": _compact_report_contract(value.get("report_contract", {})),
        "evidence_contract": _compact_evidence_contract(value.get("evidence_contract", {})),
    }
    strategy = _compact_optional_executor_local_capability_strategy(value)
    if strategy:
        compact["executor_local_capability_strategy"] = strategy
    harness_quality = _compact_harness_quality(value.get("harness_quality", {}))
    if harness_quality:
        compact["harness_quality"] = harness_quality
    readiness = _compact_executor_readiness(value.get("executor_readiness"))
    if readiness:
        compact["executor_readiness"] = readiness
    review = value.get("review")
    if isinstance(review, dict):
        compact["review"] = {
            "required": bool(review.get("required", False)),
            "workflow": _optional_string(review.get("workflow")),
            "evidence_required": str(review.get("evidence_required", "")),
        }
    context_pack = _compact_context_pack(value.get("context_pack"))
    if context_pack:
        compact["context_pack"] = context_pack
    context_pack_blocked = _compact_context_pack_blocked(value.get("context_pack_blocked"))
    if context_pack_blocked:
        compact["context_pack_blocked"] = context_pack_blocked
    return compact


def _compact_prompt_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    compact: dict[str, Any] = {
        "schema_version": str(value.get("schema_version", "")),
        "work_owner_mode": str(value.get("work_owner_mode", "")),
        "selected_executor_profile": str(value.get("selected_executor_profile", "")),
        "dispatchable": bool(value.get("dispatchable", False)),
        "invocation": _compact_prompt_invocation(value.get("invocation", {})),
        "status": str(value.get("status", "")),
        "recording_contract": str(value.get("recording_contract", "")),
        "dispatch_contract": str(value.get("dispatch_contract", "")),
        "prompt_template": str(value.get("prompt_template", "")),
        "isolation_plan": _compact_isolation_plan(value.get("isolation_plan")),
        "scope": _compact_string_list(value.get("scope", [])),
        "non_goals": _compact_string_list(value.get("non_goals", [])),
        "acceptance_criteria": _compact_string_list(value.get("acceptance_criteria", [])),
        "verification": _compact_string_list(value.get("verification", [])),
        "evidence_contract": _compact_evidence_contract(value.get("evidence_contract", {})),
    }
    strategy = _compact_optional_executor_local_capability_strategy(value)
    if strategy:
        compact["executor_local_capability_strategy"] = strategy
    harness_quality = _compact_harness_quality(value.get("harness_quality", {}))
    if harness_quality:
        compact["harness_quality"] = harness_quality
    readiness = _compact_executor_readiness(value.get("executor_readiness"))
    if readiness:
        compact["executor_readiness"] = readiness
    review = value.get("review")
    if isinstance(review, dict):
        compact["review"] = {
            "required": bool(review.get("required", False)),
            "workflow": _optional_string(review.get("workflow")),
            "evidence_required": str(review.get("evidence_required", "")),
        }
    context_pack = _compact_context_pack(value.get("context_pack"))
    if context_pack:
        compact["context_pack"] = context_pack
    context_pack_blocked = _compact_context_pack_blocked(value.get("context_pack_blocked"))
    if context_pack_blocked:
        compact["context_pack_blocked"] = context_pack_blocked
    return compact


def _compact_runtime_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    compact: dict[str, Any] = {
        "schema_version": str(value.get("schema_version", "")),
        "work_owner_mode": str(value.get("work_owner_mode", "")),
        "selected_executor_profile": str(value.get("selected_executor_profile", "")),
        "runtime_profile": _compact_runtime_profile(value.get("runtime_profile", {})),
        "dispatchable": bool(value.get("dispatchable", False)),
        "invocation": _compact_runtime_invocation(value.get("invocation", {})),
        "status": str(value.get("status", "")),
        "recording_contract": str(value.get("recording_contract", "")),
        "dispatch_contract": str(value.get("dispatch_contract", "")),
        "prompt_template": str(value.get("prompt_template", "")),
        "runtime_brief": _compact_runtime_brief(value.get("runtime_brief", {})),
        "isolation_plan": _compact_isolation_plan(value.get("isolation_plan")),
        "runtime_templates": _compact_runtime_templates(value.get("runtime_templates", [])),
        "team_contract": _compact_team_contract(value.get("team_contract", {})),
        "worktree_contract": _compact_worktree_contract(value.get("worktree_contract", {})),
        "observation_contract": _compact_runtime_observation_contract(value.get("observation_contract", {})),
        "scope": _compact_string_list(value.get("scope", [])),
        "non_goals": _compact_string_list(value.get("non_goals", [])),
        "acceptance_criteria": _compact_string_list(value.get("acceptance_criteria", [])),
        "verification": _compact_string_list(value.get("verification", [])),
        "evidence_contract": _compact_evidence_contract(value.get("evidence_contract", {})),
    }
    strategy = _compact_optional_executor_local_capability_strategy(value)
    if strategy:
        compact["executor_local_capability_strategy"] = strategy
    harness_quality = _compact_harness_quality(value.get("harness_quality", {}))
    if harness_quality:
        compact["harness_quality"] = harness_quality
    readiness = _compact_executor_readiness(value.get("executor_readiness"))
    if readiness:
        compact["executor_readiness"] = readiness
    review = value.get("review")
    if isinstance(review, dict):
        compact["review"] = {
            "required": bool(review.get("required", False)),
            "workflow": _optional_string(review.get("workflow")),
            "evidence_required": str(review.get("evidence_required", "")),
        }
    context_pack = _compact_context_pack(value.get("context_pack"))
    if context_pack:
        compact["context_pack"] = context_pack
    context_pack_blocked = _compact_context_pack_blocked(value.get("context_pack_blocked"))
    if context_pack_blocked:
        compact["context_pack_blocked"] = context_pack_blocked
    team_path = _compact_hermes_coding_team_path(value.get("hermes_coding_team_path"))
    if team_path:
        compact["hermes_coding_team_path"] = team_path
    return compact


def _compact_executor_readiness(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    compact: dict[str, Any] = {
        "schema_version": str(value.get("schema_version", "")),
        "profile": str(value.get("profile", "")),
        "status": str(value.get("status", "")),
        "first_use_only": bool(value.get("first_use_only", False)),
        "cache_key": str(value.get("cache_key", "")),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }
    for key in ("label", "ready_action", "next_action", "cache_status", "summary", "command_path", "state_error"):
        if key in value:
            compact[key] = str(value.get(key, ""))
    for key in ("available", "observed_once", "first_use_skipped"):
        if key in value:
            compact[key] = bool(value.get(key, False))
    if "exit_code" in value:
        try:
            compact["exit_code"] = int(value.get("exit_code", 0))
        except (TypeError, ValueError):
            compact["exit_code"] = 0
    probe = value.get("probe")
    if isinstance(probe, dict):
        compact["probe"] = {
            "kind": str(probe.get("kind", "")),
            "command": str(probe.get("command", "")),
            "args": _compact_string_list(probe.get("args", [])),
            "timeout_seconds": int(probe.get("timeout_seconds", 0) or 0),
            "captures": _compact_string_list(probe.get("captures", [])),
        }
    fallback = value.get("fallback_policy")
    if isinstance(fallback, dict):
        compact["fallback_policy"] = {
            "when_missing": str(fallback.get("when_missing", "")),
            "retry_after_state_change": bool(fallback.get("retry_after_state_change", False)),
            "retry_limit": int(fallback.get("retry_limit", 0) or 0),
        }
        if "suggested_actions" in fallback:
            compact["fallback_policy"]["suggested_actions"] = _compact_string_list(fallback.get("suggested_actions", []))
    if "not_evidence" in value:
        compact["not_evidence"] = _compact_string_list(value.get("not_evidence", []))
    profiles = value.get("profiles")
    if isinstance(profiles, list):
        compact["profiles"] = [_compact_executor_readiness(profile) for profile in profiles if isinstance(profile, dict)]
    return compact


def _compact_optional_executor_local_capability_strategy(value: dict[str, Any]) -> dict[str, Any]:
    strategy = value.get("executor_local_capability_strategy")
    if not isinstance(strategy, dict) or not strategy:
        return {}
    return _compact_executor_local_capability_strategy(strategy)


def _compact_executor_local_capability_strategy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    examples = value.get("examples_if_available", {})
    compact_examples = {
        str(key): _compact_string_list(items)
        for key, items in examples.items()
        if isinstance(items, list)
    } if isinstance(examples, dict) else {}
    stage_guidance = value.get("stage_guidance", {})
    compact_stage_guidance = {
        str(key): str(item)
        for key, item in stage_guidance.items()
    } if isinstance(stage_guidance, dict) else {}
    return {
        "schema_version": str(value.get("schema_version", "")),
        "profile": str(value.get("profile", "")),
        "mode": str(value.get("mode", "")),
        "installation_observed": bool(value.get("installation_observed", False)),
        "execution_observed": bool(value.get("execution_observed", False)),
        "preferred_sources": _compact_string_list(value.get("preferred_sources", [])),
        "stage_guidance": compact_stage_guidance,
        "examples_if_available": compact_examples,
        "selection_rule": str(value.get("selection_rule", "")),
        "fallback": str(value.get("fallback", "")),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }


def _compact_prompt_invocation(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        "mode": str(value.get("mode", "")),
        "tool_label": str(value.get("tool_label", "")),
        "dispatch_text_template": str(value.get("dispatch_text_template", "")),
        "message_placeholder": str(value.get("message_placeholder", "")),
        "wrapper_note": str(value.get("wrapper_note", "")),
    }


def _compact_runtime_invocation(value: Any) -> dict[str, str]:
    return _compact_prompt_invocation(value)


def _compact_runtime_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "profile": str(value.get("profile", "")),
        "label": str(value.get("label", "")),
        "runtime_family": str(value.get("runtime_family", "")),
        "underlying_agent": str(value.get("underlying_agent", "")),
        "supports_team_swarm": bool(value.get("supports_team_swarm", False)),
        "supports_tmux_workers": bool(value.get("supports_tmux_workers", value.get("supports_worker_protocol", False))),
        "supports_worker_protocol": bool(value.get("supports_worker_protocol", False)),
        "supports_worktree_guidance": bool(value.get("supports_worktree_guidance", False)),
        "supports_hermes_coding_team_path": bool(value.get("supports_hermes_coding_team_path", False)),
        "requires_operator_runtime": bool(value.get("requires_operator_runtime", False)),
    }


def _compact_hermes_coding_team_path(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    return {
        "schema_version": str(value.get("schema_version", "")),
        "profile": str(value.get("profile", "")),
        "status": str(value.get("status", "")),
        "purpose": str(value.get("purpose", "")),
        "start_modes": [
            {
                "id": str(mode.get("id", "")),
                "label": str(mode.get("label", "")),
                "use_when": str(mode.get("use_when", "")),
                "entrypoint": str(mode.get("entrypoint", "")),
                "first_observed_event": str(mode.get("first_observed_event", "")),
            }
            for mode in value.get("start_modes", [])
            if isinstance(mode, dict)
        ],
        "leader_contract": _compact_string_list(value.get("leader_contract", [])),
        "worker_contract": _compact_string_list(value.get("worker_contract", [])),
        "status_ladder": _compact_string_list(value.get("status_ladder", [])),
        "wrapper_actions": _compact_string_list(value.get("wrapper_actions", [])),
        "not_observed_by_omh": _compact_string_list(value.get("not_observed_by_omh", [])),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }


def _compact_runtime_brief(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "task_source": str(value.get("task_source", "")),
        "recommended_workflow": str(value.get("recommended_workflow", "")),
        "recommended_harness": str(value.get("recommended_harness", "")),
        "intent": str(value.get("intent", "")),
        "runtime_owns": _compact_string_list(value.get("runtime_owns", [])),
        "hermes_owns": _compact_string_list(value.get("hermes_owns", [])),
    }


def _compact_runtime_templates(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    templates: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        templates.append(
            {
                "label": str(item.get("label", "")),
                "syntax": str(item.get("syntax", "")),
                "command_template": str(item.get("command_template", "")),
                "when_to_use": str(item.get("when_to_use", "")),
                "observed_event": str(item.get("observed_event", "")),
            }
        )
    return templates


def _compact_team_contract(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        "modes": _compact_string_list(value.get("modes", [])),
        "leader_owns": _compact_string_list(value.get("leader_owns", [])),
        "worker_protocol": _compact_string_list(value.get("worker_protocol", [])),
        "fanout_when": _compact_string_list(value.get("fanout_when", [])),
        "do_not_fanout_when": _compact_string_list(value.get("do_not_fanout_when", [])),
    }


def _compact_runtime_observation_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "record_schema": str(value.get("record_schema", "")),
        "record_with": str(value.get("record_with", "")),
        "allowed_events": _compact_string_list(value.get("allowed_events", [])),
        "status_ladder": _compact_string_list(value.get("status_ladder", [])),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }


def _compact_worktree_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "policy": str(value.get("policy", "")),
        "isolation": str(value.get("isolation", "")),
        "required_before": _compact_string_list(value.get("required_before", [])),
        "not_observed_by_omh": _compact_string_list(value.get("not_observed_by_omh", [])),
    }


def _compact_isolation_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "schema_version": str(value.get("schema_version", "")),
        "status": str(value.get("status", "")),
        "strategy": str(value.get("strategy", "")),
        "risk_level": str(value.get("risk_level", "")),
        "reason_codes": _compact_string_list(value.get("reason_codes", [])),
        "workspace_policy": str(value.get("workspace_policy", "")),
        "session_binding": str(value.get("session_binding", "")),
        "required_before": _compact_string_list(value.get("required_before", [])),
        "recommended_when": _compact_string_list(value.get("recommended_when", [])),
        "wrapper_actions": _compact_string_list(value.get("wrapper_actions", [])),
        "observation_events": _compact_string_list(value.get("observation_events", [])),
        "not_observed_by_omh": _compact_string_list(value.get("not_observed_by_omh", [])),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }


def _compact_codex_invocation(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        "syntax": str(value.get("syntax", "")),
        "skill": str(value.get("skill", "")),
        "dispatch_text_template": str(value.get("dispatch_text_template", "")),
        "message_placeholder": str(value.get("message_placeholder", "")),
        "wrapper_note": str(value.get("wrapper_note", "")),
    }


def _compact_execution_brief(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "task_source": str(value.get("task_source", "")),
        "recommended_workflow": str(value.get("recommended_workflow", "")),
        "recommended_harness": str(value.get("recommended_harness", "")),
        "intent": str(value.get("intent", "")),
        "codex_owns": _compact_string_list(value.get("codex_owns", [])),
        "hermes_owns": _compact_string_list(value.get("hermes_owns", [])),
    }


def _compact_report_contract(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        "allowed_statuses": _compact_string_list(value.get("allowed_statuses", [])),
        "required_fields": _compact_string_list(value.get("required_fields", [])),
        "review_fields": _compact_string_list(value.get("review_fields", [])),
    }


def _compact_evidence_contract(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        "prepared_is_not": _compact_string_list(value.get("prepared_is_not", [])),
        "observed_required_for": _compact_string_list(value.get("observed_required_for", [])),
    }


def _compact_context_pack(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "schema_version": str(value.get("schema_version", "")),
        "executor_target": str(value.get("executor_target", "")),
        "session_id": str(value.get("session_id", "")),
        "scope": _compact_context_scope(value.get("scope", {})),
        "source_refs": _compact_context_dict_list(value.get("source_refs", [])),
        "included_context": _compact_context_dict_list(value.get("included_context", [])),
        "excluded_context": _compact_context_dict_list(value.get("excluded_context", [])),
        "blocked_by_conflicts": _compact_context_dict_list(value.get("blocked_by_conflicts", [])),
        "redaction_policy": str(value.get("redaction_policy", "")),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }


def _compact_context_pack_blocked(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "schema_version": str(value.get("schema_version", "")),
        "blocked_by_conflicts": _compact_context_dict_list(value.get("blocked_by_conflicts", [])),
        "claim_boundary": str(value.get("claim_boundary", "")),
    }


def _compact_plan_artifact(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "path": str(value.get("path", "")),
        "kind": str(value.get("kind", "hermes_plan")),
        "schema_version": str(value.get("schema_version", "")),
        "status": str(value.get("status", "")),
        "sha256": str(value.get("sha256", "")),
        "task_statement_sha256": str(value.get("task_statement_sha256", "")),
        "task_statement_length": int(value.get("task_statement_length", 0) or 0),
    }


def _compact_context_scope(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {"kind": str(value.get("kind", "")), "ref": str(value.get("ref", ""))}


def _compact_context_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        compact.append(_stringify_context_dict(item))
    return compact


def _stringify_context_dict(value: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            compact[str(key)] = _stringify_context_dict(item)
        elif isinstance(item, list):
            compact[str(key)] = _compact_string_list(item)
        elif isinstance(item, bool):
            compact[str(key)] = item
        elif isinstance(item, int):
            compact[str(key)] = item
        elif item is None:
            compact[str(key)] = ""
        else:
            compact[str(key)] = str(item)
    return compact


def _require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def validate_run_record(run: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(run.get("schema_version") == SCHEMA_VERSION, errors, "run schema_version is invalid")
    for key in ("run_id", "created_at", "updated_at", "skill", "harness", "status", "privacy"):
        _require(isinstance(run.get(key), str) if key != "schema_version" else True, errors, f"run {key} must be a string")
    _require(run.get("status") in RUN_STATUSES, errors, f"run status is invalid: {run.get('status')!r}")
    _require(run.get("privacy") in PRIVACY_MODES, errors, f"run privacy is invalid: {run.get('privacy')!r}")
    if "artifact_kind" in run:
        _require(isinstance(run.get("artifact_kind"), str), errors, "run artifact_kind must be a string")
        _require(run.get("artifact_kind") in RUN_ARTIFACT_KINDS, errors, f"run artifact_kind is invalid: {run.get('artifact_kind')!r}")
    if "phase" in run:
        _require(isinstance(run.get("phase"), str), errors, "run phase must be a string")
        _require(run.get("phase") in RUN_PHASES, errors, f"run phase is invalid: {run.get('phase')!r}")
    if "observation_status" in run:
        _require(isinstance(run.get("observation_status"), str), errors, "run observation_status must be a string")
        _require(
            run.get("observation_status") in RUN_OBSERVATION_STATUSES,
            errors,
            f"run observation_status is invalid: {run.get('observation_status')!r}",
        )
    if run.get("artifact_kind") == "prepared_coding_delegation":
        _require(run.get("status") == "prepared", errors, "prepared coding delegation run status must be prepared")
        _require(run.get("phase") == "prepared", errors, "prepared coding delegation run phase must be prepared")
        _require(
            run.get("observation_status") == "prepared_not_observed",
            errors,
            "prepared coding delegation run observation_status must be prepared_not_observed",
        )
    for key in ("trigger", "inputs_summary", "outputs_summary", "verification_summary"):
        _require(isinstance(run.get(key, ""), str), errors, f"run {key} must be a string")
    return errors


def validate_event_record(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(event.get("schema_version") == SCHEMA_VERSION, errors, "event schema_version is invalid")
    for key in ("timestamp", "event", "level", "message"):
        _require(isinstance(event.get(key), str), errors, f"event {key} must be a string")
    _require(event.get("level") in EVENT_LEVELS, errors, f"event level is invalid: {event.get('level')!r}")
    if "data" in event:
        _require(isinstance(event["data"], dict), errors, "event data must be an object")
    return errors


def validate_delegation_record(delegation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(delegation.get("schema_version") == SCHEMA_VERSION, errors, "delegation schema_version is invalid")
    _require(isinstance(delegation.get("requested"), bool), errors, "delegation requested must be boolean")
    _require(isinstance(delegation.get("observed"), bool), errors, "delegation observed must be boolean")
    _require(delegation.get("result") in DELEGATION_RESULTS, errors, f"delegation result is invalid: {delegation.get('result')!r}")
    _require(isinstance(delegation.get("participants"), list), errors, "delegation participants must be a list")
    _require(isinstance(delegation.get("evidence_refs"), list), errors, "delegation evidence_refs must be a list")
    try:
        validate_delegation_result(bool(delegation.get("observed")), str(delegation.get("result")))
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_wrapper_record(wrapper: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(wrapper.get("schema_version") == SCHEMA_VERSION, errors, "wrapper schema_version is invalid")
    for key in ("prompt_dispatched", "hermes_response_observed", "verification_observed"):
        _require(isinstance(wrapper.get(key), bool), errors, f"wrapper {key} must be boolean")
    _require(
        wrapper.get("completion_status") in WRAPPER_COMPLETION_STATUSES,
        errors,
        f"wrapper completion_status is invalid: {wrapper.get('completion_status')!r}",
    )
    _require(isinstance(wrapper.get("unobserved_gaps"), list), errors, "wrapper unobserved_gaps must be a list")
    _require(isinstance(wrapper.get("message", ""), str), errors, "wrapper message must be a string")
    return errors


def validate_review_record(review: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(
        set(review)
        - {"schema_version", "run_id", "updated_at", "required", "observed", "status", "reviewer", "evidence_refs", "summary"}
    )
    _require(not extra_keys, errors, f"review has unsupported keys: {extra_keys}")
    _require(review.get("schema_version") == SCHEMA_VERSION, errors, "review schema_version is invalid")
    for key in ("run_id", "updated_at", "status", "reviewer", "summary"):
        _require(isinstance(review.get(key), str), errors, f"review {key} must be a string")
    _require(isinstance(review.get("required"), bool), errors, "review required must be boolean")
    _require(isinstance(review.get("observed"), bool), errors, "review observed must be boolean")
    _require(review.get("status") in REVIEW_STATUSES, errors, f"review status is invalid: {review.get('status')!r}")
    _require(isinstance(review.get("evidence_refs"), list), errors, "review evidence_refs must be a list")
    for index, value in enumerate(review.get("evidence_refs", []) if isinstance(review.get("evidence_refs"), list) else []):
        _require(isinstance(value, str), errors, f"review evidence_refs[{index}] must be a string")
    if review.get("status") == "not_required":
        _require(review.get("required") is False, errors, "review not_required status requires required=false")
        _require(review.get("observed") is True, errors, "review not_required status must be observed")
    if review.get("observed") is False:
        _require(review.get("status") in {"pending", "not_observed"}, errors, "review observed=false requires pending or not_observed")
    if review.get("status") == "passed":
        _require(review.get("observed") is True, errors, "review passed status requires observed=true")
    return errors


def validate_ci_record(ci: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(
        set(ci)
        - {"schema_version", "run_id", "updated_at", "required", "observed", "status", "provider", "checks", "evidence_refs", "summary"}
    )
    _require(not extra_keys, errors, f"ci has unsupported keys: {extra_keys}")
    _require(ci.get("schema_version") == SCHEMA_VERSION, errors, "ci schema_version is invalid")
    for key in ("run_id", "updated_at", "status", "provider", "summary"):
        _require(isinstance(ci.get(key), str), errors, f"ci {key} must be a string")
    _require(isinstance(ci.get("required"), bool), errors, "ci required must be boolean")
    _require(isinstance(ci.get("observed"), bool), errors, "ci observed must be boolean")
    _require(ci.get("status") in CI_STATUSES, errors, f"ci status is invalid: {ci.get('status')!r}")
    _require(isinstance(ci.get("checks"), list), errors, "ci checks must be a list")
    checks = ci.get("checks", []) if isinstance(ci.get("checks"), list) else []
    for index, check in enumerate(checks):
        _require(isinstance(check, dict), errors, f"ci checks[{index}] must be an object")
        if not isinstance(check, dict):
            continue
        _require(set(check) == {"name", "status"}, errors, f"ci checks[{index}] must contain only name and status")
        _require(isinstance(check.get("name"), str), errors, f"ci checks[{index}].name must be a string")
        _require(bool(str(check.get("name", "")).strip()), errors, f"ci checks[{index}].name must not be empty")
        _require(check.get("status") in CI_CHECK_STATUSES, errors, f"ci checks[{index}].status is invalid: {check.get('status')!r}")
    _require(isinstance(ci.get("evidence_refs"), list), errors, "ci evidence_refs must be a list")
    for index, value in enumerate(ci.get("evidence_refs", []) if isinstance(ci.get("evidence_refs"), list) else []):
        _require(isinstance(value, str), errors, f"ci evidence_refs[{index}] must be a string")
    if ci.get("status") == "not_required":
        _require(ci.get("required") is False, errors, "ci not_required status requires required=false")
        _require(ci.get("observed") is True, errors, "ci not_required status must be observed")
        invalid_checks = [check for check in checks if isinstance(check, dict) and check.get("status") != "not_required"]
        _require(not invalid_checks, errors, "ci not_required status requires checks to be empty or not_required")
    if ci.get("observed") is False:
        _require(ci.get("status") in {"pending", "not_observed"}, errors, "ci observed=false requires pending or not_observed")
    if ci.get("status") == "passed":
        _require(ci.get("observed") is True, errors, "ci passed status requires observed=true")
        _require(bool(checks), errors, "ci passed status requires at least one check")
        failed = [check for check in checks if isinstance(check, dict) and check.get("status") != "passed"]
        _require(not failed, errors, "ci passed status requires all checks to be passed")
    return errors


def validate_merge_record(merge: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(
        set(merge)
        - {
            "schema_version",
            "run_id",
            "updated_at",
            "observed",
            "ready",
            "merged",
            "status",
            "target_branch",
            "merge_commit",
            "evidence_refs",
            "summary",
        }
    )
    _require(not extra_keys, errors, f"merge has unsupported keys: {extra_keys}")
    _require(merge.get("schema_version") == SCHEMA_VERSION, errors, "merge schema_version is invalid")
    for key in ("run_id", "updated_at", "status", "target_branch", "merge_commit", "summary"):
        _require(isinstance(merge.get(key), str), errors, f"merge {key} must be a string")
    for key in ("observed", "ready", "merged"):
        _require(isinstance(merge.get(key), bool), errors, f"merge {key} must be boolean")
    _require(merge.get("status") in MERGE_STATUSES, errors, f"merge status is invalid: {merge.get('status')!r}")
    _require(isinstance(merge.get("evidence_refs"), list), errors, "merge evidence_refs must be a list")
    for index, value in enumerate(merge.get("evidence_refs", []) if isinstance(merge.get("evidence_refs"), list) else []):
        _require(isinstance(value, str), errors, f"merge evidence_refs[{index}] must be a string")
    if merge.get("status") == "not_observed":
        _require(merge.get("observed") is False, errors, "merge not_observed status requires observed=false")
        _require(merge.get("ready") is False, errors, "merge not_observed status requires ready=false")
        _require(merge.get("merged") is False, errors, "merge not_observed status requires merged=false")
    if merge.get("status") == "not_ready":
        _require(merge.get("ready") is False, errors, "merge not_ready status requires ready=false")
        _require(merge.get("merged") is False, errors, "merge not_ready status requires merged=false")
    if merge.get("status") == "blocked":
        _require(merge.get("observed") is True, errors, "merge blocked status requires observed=true")
        _require(merge.get("ready") is False, errors, "merge blocked status requires ready=false")
        _require(merge.get("merged") is False, errors, "merge blocked status requires merged=false")
    if merge.get("observed") is False:
        _require(merge.get("status") in {"not_ready", "not_observed"}, errors, "merge observed=false requires not_ready or not_observed")
    if merge.get("status") == "ready":
        _require(merge.get("observed") is True, errors, "merge ready status requires observed=true")
        _require(merge.get("ready") is True, errors, "merge ready status requires ready=true")
        _require(merge.get("merged") is False, errors, "merge ready status requires merged=false")
    if merge.get("status") == "merged":
        _require(merge.get("observed") is True, errors, "merge merged status requires observed=true")
        _require(merge.get("ready") is True, errors, "merge merged status requires ready=true")
        _require(merge.get("merged") is True, errors, "merge merged status requires merged=true")
        _require(
            bool(str(merge.get("merge_commit", ""))) or bool(merge.get("evidence_refs")),
            errors,
            "merge merged status requires merge_commit or evidence_refs",
        )
    return errors


def validate_runtime_observation_record(observation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(set(observation) - set(RUNTIME_OBSERVATION_RECORD_KEYS))
    _require(not extra_keys, errors, f"runtime_observation has unsupported keys: {extra_keys}")
    _require(
        observation.get("schema_version") == RUNTIME_OBSERVATION_SCHEMA_VERSION,
        errors,
        "runtime_observation schema_version is invalid",
    )
    _require(observation.get("record_type") == RUNTIME_OBSERVATION_RECORD_TYPE, errors, "runtime_observation record_type is invalid")
    for key in (
        "target_type",
        "target_id",
        "updated_at",
        "runtime_profile",
        "event_type",
        "status",
        "worktree_ref",
        "worker_ref",
        "summary",
        "claim_boundary",
    ):
        _require(isinstance(observation.get(key), str), errors, f"runtime_observation {key} must be a string")
    _require(observation.get("target_type") in RUNTIME_OBSERVATION_TARGET_TYPES, errors, "runtime_observation target_type is invalid")
    _require(bool(str(observation.get("target_id", "")).strip()), errors, "runtime_observation target_id is required")
    _require(observation.get("runtime_profile") in CODING_RUNTIME_TARGETS, errors, "runtime_observation runtime_profile is invalid")
    _require(observation.get("event_type") in RUNTIME_OBSERVATION_EVENTS, errors, "runtime_observation event_type is invalid")
    _require(observation.get("status") in RUNTIME_OBSERVATION_STATUSES, errors, "runtime_observation status is invalid")
    _require(isinstance(observation.get("observed"), bool), errors, "runtime_observation observed must be boolean")
    _require(isinstance(observation.get("participants"), list), errors, "runtime_observation participants must be a list")
    _require(isinstance(observation.get("evidence_refs"), list), errors, "runtime_observation evidence_refs must be a list")
    for key in ("participants", "evidence_refs"):
        values = observation.get(key, []) if isinstance(observation.get(key), list) else []
        for index, value in enumerate(values):
            _require(isinstance(value, str), errors, f"runtime_observation {key}[{index}] must be a string")
    if observation.get("status") == "not_observed":
        _require(observation.get("observed") is False, errors, "runtime_observation not_observed status requires observed=false")
    else:
        _require(observation.get("observed") is True, errors, "runtime_observation observed status requires observed=true")
        has_evidence = bool(observation.get("evidence_refs")) or bool(str(observation.get("summary", "")).strip())
        _require(has_evidence, errors, "runtime_observation observed/blocked/failed status requires summary or evidence_refs")
    if observation.get("event_type") in {"worktree_creation"} and observation.get("status") == "observed":
        _require(bool(str(observation.get("worktree_ref", "")).strip()), errors, "runtime_observation worktree_creation requires worktree_ref")
    if observation.get("event_type") in {"worker_dispatch", "worker_result"} and observation.get("status") == "observed":
        _require(bool(str(observation.get("worker_ref", "")).strip()), errors, "runtime_observation worker event requires worker_ref")
    return errors


def validate_routing_record(routing: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(routing.get("schema_version") == SCHEMA_VERSION, errors, "routing schema_version is invalid")
    for key in (
        "updated_at",
        "source",
        "action",
        "selected_skill",
        "selected_harness",
        "candidate_skill",
        "candidate_harness",
        "confidence",
        "threshold",
        "reason",
        "message_sha256",
        "source_event_id",
        "channel_ref",
        "user_ref",
    ):
        _require(isinstance(routing.get(key), str), errors, f"routing {key} must be a string")
    _require(routing.get("action") in ROUTE_ACTIONS, errors, f"routing action is invalid: {routing.get('action')!r}")
    _require(routing.get("confidence") in ROUTE_CONFIDENCES, errors, f"routing confidence is invalid: {routing.get('confidence')!r}")
    _require(routing.get("threshold") in ROUTE_CONFIDENCES, errors, f"routing threshold is invalid: {routing.get('threshold')!r}")
    _require(isinstance(routing.get("score"), int), errors, "routing score must be an integer")
    _require(isinstance(routing.get("message_length"), int), errors, "routing message_length must be an integer")
    _require(isinstance(routing.get("explicit"), bool), errors, "routing explicit must be boolean")
    _require(isinstance(routing.get("ambiguous"), bool), errors, "routing ambiguous must be boolean")
    _require(isinstance(routing.get("recommendations"), list), errors, "routing recommendations must be a list")
    for index, recommendation in enumerate(routing.get("recommendations", [])):
        _require(isinstance(recommendation, dict), errors, f"routing recommendations[{index}] must be an object")
        if not isinstance(recommendation, dict):
            continue
        extra_keys = sorted(set(recommendation) - set(ROUTING_RECOMMENDATION_KEYS))
        _require(not extra_keys, errors, f"routing recommendations[{index}] has unsupported keys: {extra_keys}")
        _require(isinstance(recommendation.get("skill"), str), errors, f"routing recommendations[{index}].skill must be a string")
        _require(isinstance(recommendation.get("score"), int), errors, f"routing recommendations[{index}].score must be an integer")
        _require(isinstance(recommendation.get("confidence"), str), errors, f"routing recommendations[{index}].confidence must be a string")
        _require(isinstance(recommendation.get("matched"), list), errors, f"routing recommendations[{index}].matched must be a list")
    return errors


def validate_coding_delegation_record(delegation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(set(delegation) - set(CODING_DELEGATION_RECORD_KEYS))
    _require(not extra_keys, errors, f"coding_delegation has unsupported keys: {extra_keys}")
    _require(
        delegation.get("schema_version") == CODING_DELEGATION_SCHEMA_VERSION,
        errors,
        "coding_delegation schema_version is invalid",
    )
    _require(delegation.get("record_type") == CODING_DELEGATION_RECORD_TYPE, errors, "coding_delegation record_type is invalid")
    for key in (
        "updated_at",
        "source",
        "action",
        "intent",
        "recommended_workflow",
        "recommended_harness",
        "executor_profile",
        "work_owner_mode",
        "dispatch_policy",
        "message_sha256",
        "status",
    ):
        _require(isinstance(delegation.get(key), str), errors, f"coding_delegation {key} must be a string")
    _require(delegation.get("action") in CODING_DELEGATION_ACTIONS, errors, f"coding_delegation action is invalid: {delegation.get('action')!r}")
    _require(delegation.get("intent") in CODING_DELEGATION_INTENTS, errors, f"coding_delegation intent is invalid: {delegation.get('intent')!r}")
    _require(delegation.get("status") in CODING_DELEGATION_STATUSES, errors, f"coding_delegation status is invalid: {delegation.get('status')!r}")
    _require(delegation.get("work_owner_mode") in CODING_WORK_OWNER_MODES, errors, f"coding_delegation work_owner_mode is invalid: {delegation.get('work_owner_mode')!r}")
    _require(delegation.get("dispatch_policy") in CODING_DISPATCH_POLICIES, errors, f"coding_delegation dispatch_policy is invalid: {delegation.get('dispatch_policy')!r}")
    _require(isinstance(delegation.get("dispatchable"), bool), errors, "coding_delegation dispatchable must be boolean")
    selected = delegation.get("selected_executor_profile")
    _require(
        selected is None or selected in CODING_SELECTED_EXECUTOR_PROFILES,
        errors,
        f"coding_delegation selected_executor_profile is invalid: {selected!r}",
    )
    errors.extend(validate_executor_selection(delegation.get("executor_selection", {}), "coding_delegation executor_selection"))
    _require(isinstance(delegation.get("review_required"), bool), errors, "coding_delegation review_required must be boolean")
    _require(
        delegation.get("review_workflow") is None or isinstance(delegation.get("review_workflow"), str),
        errors,
        "coding_delegation review_workflow must be a string or null",
    )
    _require(isinstance(delegation.get("message_length"), int), errors, "coding_delegation message_length must be an integer")
    if isinstance(delegation.get("message_length"), int):
        _require(delegation["message_length"] >= 0, errors, "coding_delegation message_length must be non-negative")
    _require(_is_sha256(str(delegation.get("message_sha256", ""))), errors, "coding_delegation message_sha256 must be a sha256 hex digest")
    _require(isinstance(delegation.get("source_metadata"), dict), errors, "coding_delegation source_metadata must be an object")
    metadata = delegation.get("source_metadata", {})
    if isinstance(metadata, dict):
        extra_metadata_keys = sorted(set(metadata) - set(CODING_SOURCE_METADATA_KEYS))
        _require(not extra_metadata_keys, errors, f"coding_delegation source_metadata has unsupported keys: {extra_metadata_keys}")
        for key, value in metadata.items():
            _require(isinstance(value, str), errors, f"coding_delegation source_metadata.{key} must be a string")
    _require(isinstance(delegation.get("recommendation_evidence"), list), errors, "coding_delegation recommendation_evidence must be a list")
    for index, recommendation in enumerate(delegation.get("recommendation_evidence", [])):
        _require(isinstance(recommendation, dict), errors, f"coding_delegation recommendation_evidence[{index}] must be an object")
        if not isinstance(recommendation, dict):
            continue
        extra_keys = sorted(set(recommendation) - set(CODING_RECOMMENDATION_KEYS))
        _require(not extra_keys, errors, f"coding_delegation recommendation_evidence[{index}] has unsupported keys: {extra_keys}")
        _require(isinstance(recommendation.get("skill"), str), errors, f"coding_delegation recommendation_evidence[{index}].skill must be a string")
        _require(isinstance(recommendation.get("score"), int), errors, f"coding_delegation recommendation_evidence[{index}].score must be an integer")
        _require(isinstance(recommendation.get("confidence"), str), errors, f"coding_delegation recommendation_evidence[{index}].confidence must be a string")
        _require(isinstance(recommendation.get("matched"), list), errors, f"coding_delegation recommendation_evidence[{index}].matched must be a list")
    for key in ("acceptance_criteria", "verification"):
        _require(isinstance(delegation.get(key), list), errors, f"coding_delegation {key} must be a list")
        if not isinstance(delegation.get(key), list):
            continue
        for index, value in enumerate(delegation[key]):
            _require(isinstance(value, str), errors, f"coding_delegation {key}[{index}] must be a string")
    if "executor_handoff" in delegation:
        errors.extend(validate_coding_executor_handoff(delegation["executor_handoff"]))
    if "runtime_handoff" in delegation:
        errors.extend(validate_coding_runtime_handoff(delegation["runtime_handoff"]))
    if "prompt_handoff" in delegation:
        errors.extend(validate_coding_prompt_handoff(delegation["prompt_handoff"]))
    if "isolation_plan" in delegation:
        errors.extend(validate_isolation_plan(delegation["isolation_plan"], "coding_delegation isolation_plan"))
    if "harness_quality" in delegation:
        errors.extend(validate_harness_quality(delegation["harness_quality"], "coding_delegation harness_quality"))
    if "plan_artifact" in delegation:
        errors.extend(validate_coding_plan_artifact(delegation["plan_artifact"]))
    errors.extend(validate_coding_handoff_combination(delegation, "coding_delegation"))
    return errors


def validate_coding_plan_artifact(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["coding_delegation plan_artifact must be an object"]
    extra_keys = sorted(set(value) - set(CODING_PLAN_ARTIFACT_KEYS))
    _require(not extra_keys, errors, f"coding_delegation plan_artifact has unsupported keys: {extra_keys}")
    for key in ("path", "kind", "schema_version", "status", "sha256", "task_statement_sha256"):
        _require(isinstance(value.get(key), str), errors, f"coding_delegation plan_artifact.{key} must be a string")
    _require(value.get("kind") == "hermes_plan", errors, "coding_delegation plan_artifact.kind must be hermes_plan")
    _require(
        value.get("schema_version") == "hermes_plan/v1",
        errors,
        "coding_delegation plan_artifact.schema_version must be hermes_plan/v1",
    )
    if value.get("sha256"):
        _require(_is_sha256(str(value.get("sha256", ""))), errors, "coding_delegation plan_artifact.sha256 must be a sha256 hex digest")
    if value.get("task_statement_sha256"):
        _require(
            _is_sha256(str(value.get("task_statement_sha256", ""))),
            errors,
            "coding_delegation plan_artifact.task_statement_sha256 must be a sha256 hex digest",
        )
    _require(
        isinstance(value.get("task_statement_length"), int),
        errors,
        "coding_delegation plan_artifact.task_statement_length must be an integer",
    )
    return errors


def validate_wrapper_session_record(session: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(set(session) - set(WRAPPER_SESSION_RECORD_KEYS))
    _require(not extra_keys, errors, f"wrapper_session has unsupported keys: {extra_keys}")
    _require(session.get("schema_version") == WRAPPER_SESSION_SCHEMA_VERSION, errors, "wrapper_session schema_version is invalid")
    _require(session.get("record_type") == WRAPPER_SESSION_RECORD_TYPE, errors, "wrapper_session record_type is invalid")
    for key in ("session_id", "thread_key", "source", "message_sha256", "created_at", "updated_at", "status", "decision"):
        _require(isinstance(session.get(key), str), errors, f"wrapper_session {key} must be a string")
    _require(str(session.get("session_id", "")).startswith("ws-"), errors, "wrapper_session session_id must start with ws-")
    _require(bool(str(session.get("thread_key", ""))), errors, "wrapper_session thread_key is required")
    _require(session.get("status") in WRAPPER_SESSION_STATUSES, errors, f"wrapper_session status is invalid: {session.get('status')!r}")
    _require(session.get("decision") in WRAPPER_SESSION_DECISIONS, errors, f"wrapper_session decision is invalid: {session.get('decision')!r}")
    if session.get("status") in WRAPPER_SESSION_STATUS_DECISIONS:
        _require(
            session.get("decision") == WRAPPER_SESSION_STATUS_DECISIONS[session["status"]],
            errors,
            "wrapper_session decision must match status",
        )
    _require(isinstance(session.get("message_length"), int), errors, "wrapper_session message_length must be an integer")
    if isinstance(session.get("message_length"), int):
        _require(session["message_length"] >= 0, errors, "wrapper_session message_length must be non-negative")
    _require(_is_sha256(str(session.get("message_sha256", ""))), errors, "wrapper_session message_sha256 must be a sha256 hex digest")
    _require(session.get("redaction_policy") == "metadata_only", errors, "wrapper_session redaction_policy must be metadata_only")
    metadata = session.get("source_metadata")
    _require(isinstance(metadata, dict), errors, "wrapper_session source_metadata must be an object")
    if isinstance(metadata, dict):
        extra_metadata_keys = sorted(set(metadata) - set(WRAPPER_SESSION_SOURCE_METADATA_KEYS))
        _require(not extra_metadata_keys, errors, f"wrapper_session source_metadata has unsupported keys: {extra_metadata_keys}")
        for key, value in metadata.items():
            _require(isinstance(value, str), errors, f"wrapper_session source_metadata.{key} must be a string")
    route = session.get("route")
    _require(isinstance(route, dict), errors, "wrapper_session route must be an object")
    if isinstance(route, dict):
        extra_route_keys = sorted(set(route) - set(WRAPPER_SESSION_ROUTE_KEYS))
        _require(not extra_route_keys, errors, f"wrapper_session route has unsupported keys: {extra_route_keys}")
        if "score" in route:
            _require(isinstance(route["score"], int), errors, "wrapper_session route.score must be an integer")
    plan = session.get("plan")
    _require(isinstance(plan, dict), errors, "wrapper_session plan must be an object")
    if isinstance(plan, dict):
        extra_plan_keys = sorted(set(plan) - set(WRAPPER_SESSION_PLAN_KEYS))
        _require(not extra_plan_keys, errors, f"wrapper_session plan has unsupported keys: {extra_plan_keys}")
        for key, value in plan.items():
            _require(isinstance(value, str), errors, f"wrapper_session plan.{key} must be a string")
    _require(session.get("work_owner_mode") in CODING_WORK_OWNER_MODES, errors, f"wrapper_session work_owner_mode is invalid: {session.get('work_owner_mode')!r}")
    _require(session.get("dispatch_policy") in CODING_DISPATCH_POLICIES, errors, f"wrapper_session dispatch_policy is invalid: {session.get('dispatch_policy')!r}")
    selected = session.get("selected_executor_profile")
    _require(
        selected is None or selected in CODING_SELECTED_EXECUTOR_PROFILES,
        errors,
        f"wrapper_session selected_executor_profile is invalid: {selected!r}",
    )
    if session.get("prompt_handoff"):
        errors.extend(validate_coding_prompt_handoff(session["prompt_handoff"]))
    if session.get("runtime_handoff"):
        errors.extend(validate_coding_runtime_handoff(session["runtime_handoff"]))
    _require(isinstance(session.get("current_run_id"), str), errors, "wrapper_session current_run_id must be a string")
    run_id = str(session.get("current_run_id", ""))
    if session.get("status") == "handoff_prepared":
        _require(bool(run_id), errors, "wrapper_session handoff_prepared requires current_run_id")
        _require(session.get("selected_executor_profile") == "codex", errors, "wrapper_session handoff_prepared requires selected_executor_profile=codex")
        _require(session.get("work_owner_mode") == "external_executor", errors, "wrapper_session handoff_prepared requires external_executor mode")
    elif session.get("status") == "prompt_handoff_prepared":
        _require(not run_id, errors, "wrapper_session prompt_handoff_prepared must not have current_run_id")
        _require(bool(session.get("prompt_handoff")), errors, "wrapper_session prompt_handoff_prepared requires prompt_handoff")
        _require(session.get("work_owner_mode") == "prompt_only_handoff", errors, "wrapper_session prompt_handoff_prepared requires prompt_only_handoff mode")
    elif session.get("status") == "runtime_handoff_prepared":
        _require(not run_id, errors, "wrapper_session runtime_handoff_prepared must not have current_run_id")
        _require(bool(session.get("runtime_handoff")), errors, "wrapper_session runtime_handoff_prepared requires runtime_handoff")
        _require(session.get("work_owner_mode") == "runtime_handoff", errors, "wrapper_session runtime_handoff_prepared requires runtime_handoff mode")
    elif session.get("status") == "executor_choice_required":
        _require(not run_id, errors, "wrapper_session executor_choice_required must not have current_run_id")
        _require(session.get("selected_executor_profile") is None, errors, "wrapper_session executor_choice_required must not select an executor")
    elif isinstance(session.get("current_run_id"), str):
        _require(not run_id, errors, "wrapper_session current_run_id is only allowed for handoff_prepared")
    provenance = session.get("record_provenance")
    _require(isinstance(provenance, dict), errors, "wrapper_session record_provenance must be an object")
    if isinstance(provenance, dict):
        extra_provenance_keys = sorted(set(provenance) - set(WRAPPER_SESSION_PROVENANCE_KEYS))
        _require(
            not extra_provenance_keys,
            errors,
            f"wrapper_session record_provenance has unsupported keys: {extra_provenance_keys}",
        )
        _require(
            provenance.get("schema_version") == WRAPPER_SESSION_PROVENANCE_SCHEMA_VERSION,
            errors,
            "wrapper_session record_provenance schema_version is invalid",
        )
        _require(
            provenance.get("producer") in WRAPPER_SESSION_PRODUCERS,
            errors,
            f"wrapper_session record_provenance producer is invalid: {provenance.get('producer')!r}",
        )
        _require(
            isinstance(provenance.get("producer_detail"), str),
            errors,
            "wrapper_session record_provenance.producer_detail must be a string",
        )
        _require(
            isinstance(provenance.get("observed_by_host"), bool),
            errors,
            "wrapper_session record_provenance.observed_by_host must be a boolean",
        )
        _require(
            isinstance(provenance.get("claim_boundary"), str) and bool(provenance.get("claim_boundary")),
            errors,
            "wrapper_session record_provenance.claim_boundary must be a string",
        )
    authority = session.get("authority")
    _require(isinstance(authority, dict), errors, "wrapper_session authority must be an object")
    if isinstance(authority, dict):
        _require(isinstance(authority.get("session_owns"), list), errors, "wrapper_session authority.session_owns must be a list")
        _require(isinstance(authority.get("run_ledger_owns"), list), errors, "wrapper_session authority.run_ledger_owns must be a list")
        forbidden = {"dispatch", "executor_result", "verification", "review", "ci", "merge_readiness", "merge"}
        session_owns = set(authority.get("session_owns", [])) if isinstance(authority.get("session_owns"), list) else set()
        _require(not (session_owns & forbidden), errors, "wrapper_session authority must not assign execution evidence to session")
        _require(
            session_owns == set(WRAPPER_SESSION_AUTHORITY_SESSION_OWNS),
            errors,
            "wrapper_session authority.session_owns must match the wrapper session authority contract",
        )
        run_ledger_owns = set(authority.get("run_ledger_owns", [])) if isinstance(authority.get("run_ledger_owns"), list) else set()
        _require(
            run_ledger_owns == set(WRAPPER_SESSION_AUTHORITY_RUN_LEDGER_OWNS),
            errors,
            "wrapper_session authority.run_ledger_owns must match the run ledger authority contract",
        )
    return errors


def validate_coding_executor_handoff(handoff: Any) -> list[str]:
    errors: list[str] = []
    _require(isinstance(handoff, dict), errors, "coding_delegation executor_handoff must be an object")
    if not isinstance(handoff, dict):
        return errors
    extra_keys = sorted(set(handoff) - set(CODING_EXECUTOR_HANDOFF_KEYS))
    _require(not extra_keys, errors, f"coding_delegation executor_handoff has unsupported keys: {extra_keys}")
    _require(
        handoff.get("schema_version") == CODING_EXECUTOR_HANDOFF_SCHEMA_VERSION,
        errors,
        "coding_delegation executor_handoff schema_version is invalid",
    )
    _require(handoff.get("work_owner_mode") == "external_executor", errors, "coding_delegation executor_handoff work_owner_mode must be external_executor")
    _require(handoff.get("selected_executor_profile") == "codex", errors, "coding_delegation executor_handoff selected_executor_profile must be codex")
    _require(handoff.get("dispatch_policy") == "ask_before_dispatch", errors, "coding_delegation executor_handoff dispatch_policy must be ask_before_dispatch")
    _require(handoff.get("dispatchable") is True, errors, "coding_delegation executor_handoff dispatchable must be true")
    _require(
        handoff.get("executor_target") in CODING_EXECUTOR_TARGETS,
        errors,
        f"coding_delegation executor_handoff executor_target is invalid: {handoff.get('executor_target')!r}",
    )
    for key in ("handoff_mode", "send_action", "codex_skill", "status", "recording_contract", "dispatch_contract", "prompt_template"):
        _require(isinstance(handoff.get(key), str), errors, f"coding_delegation executor_handoff {key} must be a string")
    _require(handoff.get("send_action") == "send_to_executor", errors, "coding_delegation executor_handoff send_action must be send_to_executor")
    _require(str(handoff.get("codex_skill", "")).startswith("$"), errors, "coding_delegation executor_handoff codex_skill must start with $")
    _require(
        handoff.get("status") == "prepared_not_observed",
        errors,
        "coding_delegation executor_handoff status must be prepared_not_observed",
    )
    _require(
        "{message}" in str(handoff.get("prompt_template", "")),
        errors,
        "coding_delegation executor_handoff prompt_template must keep {message} placeholder",
    )
    invocation = handoff.get("codex_invocation")
    _require(isinstance(invocation, dict), errors, "coding_delegation executor_handoff codex_invocation must be an object")
    if isinstance(invocation, dict):
        for key in ("syntax", "skill", "dispatch_text_template", "message_placeholder", "wrapper_note"):
            _require(isinstance(invocation.get(key), str), errors, f"coding_delegation executor_handoff codex_invocation.{key} must be a string")
        _require(invocation.get("syntax") == "$skill", errors, "coding_delegation executor_handoff codex_invocation.syntax must be $skill")
        _require(invocation.get("skill") == handoff.get("codex_skill"), errors, "coding_delegation executor_handoff codex_invocation.skill must match codex_skill")
        _require(
            "{message}" in str(invocation.get("dispatch_text_template", "")),
            errors,
            "coding_delegation executor_handoff codex_invocation.dispatch_text_template must keep {message} placeholder",
        )
    errors.extend(
        validate_optional_executor_local_capability_strategy(
            handoff,
            "coding_delegation executor_handoff executor_local_capability_strategy",
            expected_profile="codex",
        )
    )
    brief = handoff.get("execution_brief")
    _require(isinstance(brief, dict), errors, "coding_delegation executor_handoff execution_brief must be an object")
    if isinstance(brief, dict):
        for key in ("task_source", "recommended_workflow", "recommended_harness", "intent"):
            _require(isinstance(brief.get(key), str), errors, f"coding_delegation executor_handoff execution_brief.{key} must be a string")
        for key in ("codex_owns", "hermes_owns"):
            _require(isinstance(brief.get(key), list), errors, f"coding_delegation executor_handoff execution_brief.{key} must be a list")
            if isinstance(brief.get(key), list):
                for index, value in enumerate(brief[key]):
                    _require(isinstance(value, str), errors, f"coding_delegation executor_handoff execution_brief.{key}[{index}] must be a string")
    for key in ("scope", "non_goals", "acceptance_criteria", "verification"):
        _require(isinstance(handoff.get(key), list), errors, f"coding_delegation executor_handoff {key} must be a list")
        if isinstance(handoff.get(key), list):
            for index, value in enumerate(handoff[key]):
                _require(isinstance(value, str), errors, f"coding_delegation executor_handoff {key}[{index}] must be a string")
    review = handoff.get("review")
    _require(isinstance(review, dict), errors, "coding_delegation executor_handoff review must be an object")
    if isinstance(review, dict):
        _require(isinstance(review.get("required"), bool), errors, "coding_delegation executor_handoff review.required must be boolean")
        _require(
            review.get("workflow") is None or isinstance(review.get("workflow"), str),
            errors,
            "coding_delegation executor_handoff review.workflow must be a string or null",
        )
        _require(
            isinstance(review.get("evidence_required"), str),
            errors,
            "coding_delegation executor_handoff review.evidence_required must be a string",
        )
    for key in ("report_contract", "evidence_contract"):
        contract = handoff.get(key)
        _require(isinstance(contract, dict), errors, f"coding_delegation executor_handoff {key} must be an object")
        if isinstance(contract, dict):
            for nested_key, nested_value in contract.items():
                _require(isinstance(nested_value, list), errors, f"coding_delegation executor_handoff {key}.{nested_key} must be a list")
                if isinstance(nested_value, list):
                    for index, item in enumerate(nested_value):
                        _require(isinstance(item, str), errors, f"coding_delegation executor_handoff {key}.{nested_key}[{index}] must be a string")
    if "harness_quality" in handoff:
        errors.extend(validate_harness_quality(handoff["harness_quality"], "coding_delegation executor_handoff harness_quality"))
    if "executor_readiness" in handoff:
        errors.extend(
            validate_executor_readiness(
                handoff["executor_readiness"],
                "coding_delegation executor_handoff executor_readiness",
                expected_profile=str(handoff.get("selected_executor_profile", "")),
            )
        )
    errors.extend(validate_isolation_plan(handoff.get("isolation_plan"), "coding_delegation executor_handoff isolation_plan"))
    errors.extend(validate_handoff_context_pack_fields(handoff, "coding_delegation executor_handoff"))
    return errors


def validate_executor_selection(selection: Any, label: str) -> list[str]:
    errors: list[str] = []
    _require(isinstance(selection, dict), errors, f"{label} must be an object")
    if not isinstance(selection, dict):
        return errors
    extra_keys = sorted(set(selection) - set(CODING_EXECUTOR_SELECTION_KEYS))
    _require(not extra_keys, errors, f"{label} has unsupported keys: {extra_keys}")
    _require(selection.get("status") in CODING_EXECUTOR_SELECTION_STATUSES, errors, f"{label} status is invalid: {selection.get('status')!r}")
    _require(isinstance(selection.get("choice_required"), bool), errors, f"{label} choice_required must be boolean")
    _require(isinstance(selection.get("options"), list), errors, f"{label} options must be a list")
    for index, option in enumerate(selection.get("options", []) if isinstance(selection.get("options"), list) else []):
        _require(isinstance(option, dict), errors, f"{label} options[{index}] must be an object")
        if not isinstance(option, dict):
            continue
        expected = {"profile", "label", "work_owner_mode", "dispatchable", "recommended_for", "readiness_probe"}
        _require(not (set(option) - expected), errors, f"{label} options[{index}] has unsupported keys: {sorted(set(option) - expected)}")
        _require(option.get("profile") in (*CODING_SELECTED_EXECUTOR_PROFILES, "hermes"), errors, f"{label} options[{index}].profile is invalid: {option.get('profile')!r}")
        _require(option.get("work_owner_mode") in CODING_WORK_OWNER_MODES, errors, f"{label} options[{index}].work_owner_mode is invalid")
        _require(isinstance(option.get("dispatchable"), bool), errors, f"{label} options[{index}].dispatchable must be boolean")
        if "readiness_probe" in option:
            errors.extend(
                validate_executor_readiness(
                    option["readiness_probe"],
                    f"{label} options[{index}].readiness_probe",
                    expected_profile=str(option.get("profile", "")),
                )
            )
    return errors


def validate_executor_local_capability_strategy(strategy: Any, label: str, *, expected_profile: str) -> list[str]:
    errors: list[str] = []
    _require(isinstance(strategy, dict), errors, f"{label} must be an object")
    if not isinstance(strategy, dict):
        return errors
    extra_keys = sorted(set(strategy) - set(EXECUTOR_LOCAL_CAPABILITY_STRATEGY_KEYS))
    missing_keys = sorted(set(EXECUTOR_LOCAL_CAPABILITY_STRATEGY_KEYS) - set(strategy))
    _require(not extra_keys, errors, f"{label} has unsupported keys: {extra_keys}")
    _require(not missing_keys, errors, f"{label} is missing keys: {missing_keys}")
    _require(
        strategy.get("schema_version") == EXECUTOR_LOCAL_CAPABILITY_STRATEGY_SCHEMA_VERSION,
        errors,
        f"{label} schema_version is invalid",
    )
    _require(strategy.get("profile") == expected_profile, errors, f"{label} profile must match selected executor")
    _require(strategy.get("mode") == "discover_then_use_when_helpful", errors, f"{label} mode is invalid")
    _require(strategy.get("installation_observed") is False, errors, f"{label} installation_observed must be false")
    _require(strategy.get("execution_observed") is False, errors, f"{label} execution_observed must be false")
    for key in ("preferred_sources",):
        _require(isinstance(strategy.get(key), list), errors, f"{label} {key} must be a list")
        if isinstance(strategy.get(key), list):
            for index, value in enumerate(strategy[key]):
                _require(isinstance(value, str), errors, f"{label} {key}[{index}] must be a string")
    stage_guidance = strategy.get("stage_guidance")
    _require(isinstance(stage_guidance, dict), errors, f"{label} stage_guidance must be an object")
    if isinstance(stage_guidance, dict):
        for key, value in stage_guidance.items():
            _require(isinstance(key, str), errors, f"{label} stage_guidance keys must be strings")
            _require(isinstance(value, str), errors, f"{label} stage_guidance.{key} must be a string")
    examples = strategy.get("examples_if_available")
    _require(isinstance(examples, dict), errors, f"{label} examples_if_available must be an object")
    if isinstance(examples, dict):
        for key, values in examples.items():
            _require(isinstance(key, str), errors, f"{label} examples_if_available keys must be strings")
            _require(isinstance(values, list), errors, f"{label} examples_if_available.{key} must be a list")
            if isinstance(values, list):
                for index, value in enumerate(values):
                    _require(isinstance(value, str), errors, f"{label} examples_if_available.{key}[{index}] must be a string")
    for key in ("selection_rule", "fallback", "claim_boundary"):
        _require(isinstance(strategy.get(key), str), errors, f"{label} {key} must be a string")
    _require("not evidence" in str(strategy.get("claim_boundary", "")).lower(), errors, f"{label} claim_boundary must preserve evidence boundary")
    return errors


def validate_optional_executor_local_capability_strategy(
    handoff: dict[str, Any],
    label: str,
    *,
    expected_profile: str,
) -> list[str]:
    if "executor_local_capability_strategy" not in handoff:
        return []
    return validate_executor_local_capability_strategy(
        handoff["executor_local_capability_strategy"],
        label,
        expected_profile=expected_profile,
    )


def validate_coding_runtime_handoff(handoff: Any) -> list[str]:
    errors: list[str] = []
    _require(isinstance(handoff, dict), errors, "coding_delegation runtime_handoff must be an object")
    if not isinstance(handoff, dict):
        return errors
    extra_keys = sorted(set(handoff) - set(CODING_RUNTIME_HANDOFF_KEYS))
    _require(not extra_keys, errors, f"coding_delegation runtime_handoff has unsupported keys: {extra_keys}")
    _require(
        handoff.get("schema_version") == CODING_RUNTIME_HANDOFF_SCHEMA_VERSION,
        errors,
        "coding_delegation runtime_handoff schema_version is invalid",
    )
    _require(handoff.get("work_owner_mode") == "runtime_handoff", errors, "coding_delegation runtime_handoff work_owner_mode must be runtime_handoff")
    _require(handoff.get("selected_executor_profile") in CODING_RUNTIME_TARGETS, errors, "coding_delegation runtime_handoff selected_executor_profile is invalid")
    _require(handoff.get("dispatchable") is False, errors, "coding_delegation runtime_handoff dispatchable must be false")
    for key in ("status", "recording_contract", "dispatch_contract", "prompt_template"):
        _require(isinstance(handoff.get(key), str), errors, f"coding_delegation runtime_handoff {key} must be a string")
    _require(handoff.get("status") == "prepared_not_observed", errors, "coding_delegation runtime_handoff status must be prepared_not_observed")
    _require(handoff.get("recording_contract") == "runtime_prepared_not_started", errors, "coding_delegation runtime_handoff recording_contract is invalid")
    _require(
        handoff.get("dispatch_contract") == "wrapper_or_user_starts_runtime; omh_does_not_execute_runtime",
        errors,
        "coding_delegation runtime_handoff dispatch_contract is invalid",
    )
    _require("{message}" in str(handoff.get("prompt_template", "")), errors, "coding_delegation runtime_handoff prompt_template must keep {message} placeholder")
    forbidden = ("codex_skill", "codex_invocation", "executor_handoff", "prompt_handoff", "run_id")
    for key in forbidden:
        _require(key not in handoff, errors, f"coding_delegation runtime_handoff must not contain {key}")

    runtime_profile = handoff.get("runtime_profile")
    _require(isinstance(runtime_profile, dict), errors, "coding_delegation runtime_handoff runtime_profile must be an object")
    if isinstance(runtime_profile, dict):
        extra_profile_keys = sorted(set(runtime_profile) - set(CODING_RUNTIME_PROFILE_KEYS))
        _require(not extra_profile_keys, errors, f"coding_delegation runtime_handoff runtime_profile has unsupported keys: {extra_profile_keys}")
        for key in ("profile", "label", "runtime_family", "underlying_agent"):
            _require(isinstance(runtime_profile.get(key), str), errors, f"coding_delegation runtime_handoff runtime_profile.{key} must be a string")
        _require(runtime_profile.get("profile") == handoff.get("selected_executor_profile"), errors, "coding_delegation runtime_handoff runtime_profile.profile must match selected executor")
        for key in (
            "supports_team_swarm",
            "supports_worker_protocol",
            "supports_worktree_guidance",
            "supports_hermes_coding_team_path",
            "requires_operator_runtime",
        ):
            _require(isinstance(runtime_profile.get(key), bool), errors, f"coding_delegation runtime_handoff runtime_profile.{key} must be boolean")
        if "supports_tmux_workers" in runtime_profile:
            _require(isinstance(runtime_profile.get("supports_tmux_workers"), bool), errors, "coding_delegation runtime_handoff runtime_profile.supports_tmux_workers must be boolean")
            _require(runtime_profile.get("supports_tmux_workers") is True, errors, "coding_delegation runtime_handoff must support tmux-style worker guidance")
        _require(runtime_profile.get("supports_team_swarm") is True, errors, "coding_delegation runtime_handoff must support team/swarm guidance")
        _require(runtime_profile.get("supports_worker_protocol") is True, errors, "coding_delegation runtime_handoff must support worker protocol")
        _require(runtime_profile.get("supports_worktree_guidance") is True, errors, "coding_delegation runtime_handoff must support worktree guidance")

    invocation = handoff.get("invocation")
    _require(isinstance(invocation, dict), errors, "coding_delegation runtime_handoff invocation must be an object")
    if isinstance(invocation, dict):
        extra_invocation_keys = sorted(set(invocation) - set(CODING_RUNTIME_HANDOFF_INVOCATION_KEYS))
        _require(not extra_invocation_keys, errors, f"coding_delegation runtime_handoff invocation has unsupported keys: {extra_invocation_keys}")
        for key in CODING_RUNTIME_HANDOFF_INVOCATION_KEYS:
            _require(isinstance(invocation.get(key), str), errors, f"coding_delegation runtime_handoff invocation.{key} must be a string")
        _require("{message}" in str(invocation.get("dispatch_text_template", "")), errors, "coding_delegation runtime_handoff invocation.dispatch_text_template must keep {message}")
    errors.extend(
        validate_optional_executor_local_capability_strategy(
            handoff,
            "coding_delegation runtime_handoff executor_local_capability_strategy",
            expected_profile=str(handoff.get("selected_executor_profile", "")),
        )
    )

    brief = handoff.get("runtime_brief")
    _require(isinstance(brief, dict), errors, "coding_delegation runtime_handoff runtime_brief must be an object")
    if isinstance(brief, dict):
        for key in ("task_source", "recommended_workflow", "recommended_harness", "intent"):
            _require(isinstance(brief.get(key), str), errors, f"coding_delegation runtime_handoff runtime_brief.{key} must be a string")
        for key in ("runtime_owns", "hermes_owns"):
            _require(isinstance(brief.get(key), list), errors, f"coding_delegation runtime_handoff runtime_brief.{key} must be a list")
            if isinstance(brief.get(key), list):
                for index, value in enumerate(brief[key]):
                    _require(isinstance(value, str), errors, f"coding_delegation runtime_handoff runtime_brief.{key}[{index}] must be a string")

    templates = handoff.get("runtime_templates")
    _require(isinstance(templates, list), errors, "coding_delegation runtime_handoff runtime_templates must be a list")
    if isinstance(templates, list):
        _require(bool(templates), errors, "coding_delegation runtime_handoff runtime_templates must not be empty")
        for index, template in enumerate(templates):
            _require(isinstance(template, dict), errors, f"coding_delegation runtime_handoff runtime_templates[{index}] must be an object")
            if not isinstance(template, dict):
                continue
            extra_template_keys = sorted(set(template) - set(CODING_RUNTIME_TEMPLATE_KEYS))
            _require(
                not extra_template_keys,
                errors,
                f"coding_delegation runtime_handoff runtime_templates[{index}] has unsupported keys: {extra_template_keys}",
            )
            for key in CODING_RUNTIME_TEMPLATE_KEYS:
                _require(isinstance(template.get(key), str), errors, f"coding_delegation runtime_handoff runtime_templates[{index}].{key} must be a string")
            _require(
                "{message}" in str(template.get("command_template", "")),
                errors,
                f"coding_delegation runtime_handoff runtime_templates[{index}].command_template must keep {{message}}",
            )
            _require(
                template.get("observed_event") in RUNTIME_OBSERVATION_EVENTS,
                errors,
                f"coding_delegation runtime_handoff runtime_templates[{index}].observed_event is invalid",
            )

    team_contract = handoff.get("team_contract")
    _require(isinstance(team_contract, dict), errors, "coding_delegation runtime_handoff team_contract must be an object")
    if isinstance(team_contract, dict):
        expected = {"modes", "leader_owns", "worker_protocol", "fanout_when", "do_not_fanout_when"}
        _require(not (set(team_contract) - expected), errors, f"coding_delegation runtime_handoff team_contract has unsupported keys: {sorted(set(team_contract) - expected)}")
        for key in expected:
            _require(isinstance(team_contract.get(key), list), errors, f"coding_delegation runtime_handoff team_contract.{key} must be a list")
            if isinstance(team_contract.get(key), list):
                for index, value in enumerate(team_contract[key]):
                    _require(isinstance(value, str), errors, f"coding_delegation runtime_handoff team_contract.{key}[{index}] must be a string")
        _require("team" in team_contract.get("modes", []), errors, "coding_delegation runtime_handoff team_contract.modes must include team")
        _require("swarm" in team_contract.get("modes", []), errors, "coding_delegation runtime_handoff team_contract.modes must include swarm")

    worktree_contract = handoff.get("worktree_contract")
    _require(isinstance(worktree_contract, dict), errors, "coding_delegation runtime_handoff worktree_contract must be an object")
    if isinstance(worktree_contract, dict):
        expected = {"policy", "isolation", "required_before", "not_observed_by_omh"}
        _require(not (set(worktree_contract) - expected), errors, f"coding_delegation runtime_handoff worktree_contract has unsupported keys: {sorted(set(worktree_contract) - expected)}")
        for key in ("policy", "isolation"):
            _require(isinstance(worktree_contract.get(key), str), errors, f"coding_delegation runtime_handoff worktree_contract.{key} must be a string")
        for key in ("required_before", "not_observed_by_omh"):
            _require(isinstance(worktree_contract.get(key), list), errors, f"coding_delegation runtime_handoff worktree_contract.{key} must be a list")
            if isinstance(worktree_contract.get(key), list):
                for index, value in enumerate(worktree_contract[key]):
                    _require(isinstance(value, str), errors, f"coding_delegation runtime_handoff worktree_contract.{key}[{index}] must be a string")

    observation_contract = handoff.get("observation_contract")
    _require(isinstance(observation_contract, dict), errors, "coding_delegation runtime_handoff observation_contract must be an object")
    if isinstance(observation_contract, dict):
        extra_observation_keys = sorted(set(observation_contract) - set(CODING_RUNTIME_OBSERVATION_CONTRACT_KEYS))
        missing_observation_keys = sorted(set(CODING_RUNTIME_OBSERVATION_CONTRACT_KEYS) - set(observation_contract))
        _require(not extra_observation_keys, errors, f"coding_delegation runtime_handoff observation_contract has unsupported keys: {extra_observation_keys}")
        _require(not missing_observation_keys, errors, f"coding_delegation runtime_handoff observation_contract is missing keys: {missing_observation_keys}")
        for key in ("record_schema", "record_with", "claim_boundary"):
            _require(isinstance(observation_contract.get(key), str), errors, f"coding_delegation runtime_handoff observation_contract.{key} must be a string")
        _require(
            observation_contract.get("record_schema") == RUNTIME_OBSERVATION_SCHEMA_VERSION,
            errors,
            "coding_delegation runtime_handoff observation_contract.record_schema is invalid",
        )
        for key in ("allowed_events", "status_ladder"):
            _require(isinstance(observation_contract.get(key), list), errors, f"coding_delegation runtime_handoff observation_contract.{key} must be a list")
            values = observation_contract.get(key, []) if isinstance(observation_contract.get(key), list) else []
            for index, value in enumerate(values):
                _require(isinstance(value, str), errors, f"coding_delegation runtime_handoff observation_contract.{key}[{index}] must be a string")
            missing_values = sorted(set(RUNTIME_OBSERVATION_EVENTS) - {value for value in values if isinstance(value, str)})
            _require(
                not missing_values,
                errors,
                f"coding_delegation runtime_handoff observation_contract.{key} must include required events: {missing_values}",
            )

    for key in ("scope", "non_goals", "acceptance_criteria", "verification"):
        _require(isinstance(handoff.get(key), list), errors, f"coding_delegation runtime_handoff {key} must be a list")
        if isinstance(handoff.get(key), list):
            for index, value in enumerate(handoff[key]):
                _require(isinstance(value, str), errors, f"coding_delegation runtime_handoff {key}[{index}] must be a string")
    review = handoff.get("review")
    _require(isinstance(review, dict), errors, "coding_delegation runtime_handoff review must be an object")
    if isinstance(review, dict):
        _require(isinstance(review.get("required"), bool), errors, "coding_delegation runtime_handoff review.required must be boolean")
        _require(review.get("workflow") is None or isinstance(review.get("workflow"), str), errors, "coding_delegation runtime_handoff review.workflow must be a string or null")
        _require(isinstance(review.get("evidence_required"), str), errors, "coding_delegation runtime_handoff review.evidence_required must be a string")
    contract = handoff.get("evidence_contract")
    _require(isinstance(contract, dict), errors, "coding_delegation runtime_handoff evidence_contract must be an object")
    if isinstance(contract, dict):
        extra_contract_keys = sorted(set(contract) - set(CODING_RUNTIME_EVIDENCE_CONTRACT_KEYS))
        missing_contract_keys = sorted(set(CODING_RUNTIME_EVIDENCE_CONTRACT_KEYS) - set(contract))
        _require(not extra_contract_keys, errors, f"coding_delegation runtime_handoff evidence_contract has unsupported keys: {extra_contract_keys}")
        _require(not missing_contract_keys, errors, f"coding_delegation runtime_handoff evidence_contract is missing keys: {missing_contract_keys}")
        for nested_key in CODING_RUNTIME_EVIDENCE_CONTRACT_KEYS:
            nested_value = contract.get(nested_key)
            _require(isinstance(nested_value, list), errors, f"coding_delegation runtime_handoff evidence_contract.{nested_key} must be a list")
            if isinstance(nested_value, list):
                _require(len(nested_value) >= 1, errors, f"coding_delegation runtime_handoff evidence_contract.{nested_key} must not be empty")
                for index, item in enumerate(nested_value):
                    _require(isinstance(item, str), errors, f"coding_delegation runtime_handoff evidence_contract.{nested_key}[{index}] must be a string")
                required = CODING_RUNTIME_PREPARED_BOUNDARIES if nested_key == "prepared_is_not" else CODING_RUNTIME_OBSERVED_BOUNDARIES
                values = {item for item in nested_value if isinstance(item, str)}
                missing_values = sorted(set(required) - values)
                _require(
                    not missing_values,
                    errors,
                    f"coding_delegation runtime_handoff evidence_contract.{nested_key} must include required boundaries: {missing_values}",
                )
    if "hermes_coding_team_path" in handoff:
        errors.extend(validate_hermes_coding_team_path(handoff["hermes_coding_team_path"], selected=str(handoff.get("selected_executor_profile", ""))))
    if "harness_quality" in handoff:
        errors.extend(validate_harness_quality(handoff["harness_quality"], "coding_delegation runtime_handoff harness_quality"))
    if "executor_readiness" in handoff:
        errors.extend(
            validate_executor_readiness(
                handoff["executor_readiness"],
                "coding_delegation runtime_handoff executor_readiness",
                expected_profile=str(handoff.get("selected_executor_profile", "")),
            )
        )
    errors.extend(validate_isolation_plan(handoff.get("isolation_plan"), "coding_delegation runtime_handoff isolation_plan"))
    errors.extend(validate_handoff_context_pack_fields(handoff, "coding_delegation runtime_handoff"))
    return errors


def validate_hermes_coding_team_path(path: Any, *, selected: str) -> list[str]:
    errors: list[str] = []
    _require(isinstance(path, dict), errors, "coding_delegation runtime_handoff hermes_coding_team_path must be an object")
    if not isinstance(path, dict):
        return errors
    allowed_keys = {
        "schema_version",
        "profile",
        "status",
        "purpose",
        "start_modes",
        "leader_contract",
        "worker_contract",
        "status_ladder",
        "wrapper_actions",
        "not_observed_by_omh",
        "claim_boundary",
    }
    extra_keys = sorted(set(path) - allowed_keys)
    _require(not extra_keys, errors, f"coding_delegation runtime_handoff hermes_coding_team_path has unsupported keys: {extra_keys}")
    _require(selected == "hermes", errors, "coding_delegation runtime_handoff hermes_coding_team_path is only valid for hermes")
    _require(path.get("schema_version") == "hermes_coding_team_path/v1", errors, "coding_delegation runtime_handoff hermes_coding_team_path schema_version is invalid")
    _require(path.get("profile") == "hermes", errors, "coding_delegation runtime_handoff hermes_coding_team_path profile must be hermes")
    _require(path.get("status") == "prepared_not_observed", errors, "coding_delegation runtime_handoff hermes_coding_team_path status must be prepared_not_observed")
    for key in ("purpose", "claim_boundary"):
        _require(isinstance(path.get(key), str), errors, f"coding_delegation runtime_handoff hermes_coding_team_path.{key} must be a string")
    for key in ("leader_contract", "worker_contract", "status_ladder", "wrapper_actions", "not_observed_by_omh"):
        _require(isinstance(path.get(key), list), errors, f"coding_delegation runtime_handoff hermes_coding_team_path.{key} must be a list")
        if isinstance(path.get(key), list):
            for index, value in enumerate(path[key]):
                _require(isinstance(value, str), errors, f"coding_delegation runtime_handoff hermes_coding_team_path.{key}[{index}] must be a string")
    start_modes = path.get("start_modes")
    _require(isinstance(start_modes, list), errors, "coding_delegation runtime_handoff hermes_coding_team_path.start_modes must be a list")
    if isinstance(start_modes, list):
        mode_ids = set()
        for index, mode in enumerate(start_modes):
            _require(isinstance(mode, dict), errors, f"coding_delegation runtime_handoff hermes_coding_team_path.start_modes[{index}] must be an object")
            if not isinstance(mode, dict):
                continue
            mode_ids.add(str(mode.get("id", "")))
            for key in ("id", "label", "use_when", "entrypoint", "first_observed_event"):
                _require(isinstance(mode.get(key), str), errors, f"coding_delegation runtime_handoff hermes_coding_team_path.start_modes[{index}].{key} must be a string")
            first_event = mode.get("first_observed_event")
            if isinstance(first_event, str):
                _require(
                    first_event in RUNTIME_OBSERVATION_EVENTS,
                    errors,
                    (
                        "coding_delegation runtime_handoff hermes_coding_team_path."
                        f"start_modes[{index}].first_observed_event is unsupported: {first_event}"
                    ),
                )
        missing_modes = sorted(set(HERMES_CODING_TEAM_START_MODE_IDS) - mode_ids)
        unsupported_modes = sorted(mode_ids - set(HERMES_CODING_TEAM_START_MODE_IDS))
        _require(
            not missing_modes,
            errors,
            f"coding_delegation runtime_handoff hermes_coding_team_path.start_modes must include required modes: {missing_modes}",
        )
        _require(
            not unsupported_modes,
            errors,
            f"coding_delegation runtime_handoff hermes_coding_team_path.start_modes has unsupported modes: {unsupported_modes}",
        )
        if not missing_modes and not unsupported_modes:
            _require(
                len(mode_ids) == len([mode for mode in start_modes if isinstance(mode, dict)]),
                errors,
                "coding_delegation runtime_handoff hermes_coding_team_path.start_modes must not duplicate ids",
            )
    status_ladder = path.get("status_ladder", [])
    if isinstance(status_ladder, list):
        string_ladder = [event for event in status_ladder if isinstance(event, str)]
        _require(
            string_ladder == list(HERMES_CODING_TEAM_STATUS_LADDER),
            errors,
            "coding_delegation runtime_handoff hermes_coding_team_path.status_ladder must match the full Hermes coding team ladder",
        )
    wrapper_actions = path.get("wrapper_actions", [])
    if isinstance(wrapper_actions, list):
        string_actions = [action for action in wrapper_actions if isinstance(action, str)]
        _require(
            string_actions == list(HERMES_CODING_TEAM_WRAPPER_ACTIONS),
            errors,
            "coding_delegation runtime_handoff hermes_coding_team_path.wrapper_actions must match the Hermes coding team action contract",
        )
    return errors


def validate_coding_prompt_handoff(handoff: Any) -> list[str]:
    errors: list[str] = []
    _require(isinstance(handoff, dict), errors, "coding_delegation prompt_handoff must be an object")
    if not isinstance(handoff, dict):
        return errors
    extra_keys = sorted(set(handoff) - set(CODING_PROMPT_HANDOFF_KEYS))
    _require(not extra_keys, errors, f"coding_delegation prompt_handoff has unsupported keys: {extra_keys}")
    _require(
        handoff.get("schema_version") == CODING_PROMPT_HANDOFF_SCHEMA_VERSION,
        errors,
        "coding_delegation prompt_handoff schema_version is invalid",
    )
    _require(handoff.get("work_owner_mode") == "prompt_only_handoff", errors, "coding_delegation prompt_handoff work_owner_mode must be prompt_only_handoff")
    _require(handoff.get("selected_executor_profile") in CODING_SELECTED_EXECUTOR_PROFILES, errors, "coding_delegation prompt_handoff selected_executor_profile is invalid")
    _require(handoff.get("selected_executor_profile") != "codex", errors, "coding_delegation prompt_handoff must not target codex")
    _require(handoff.get("selected_executor_profile") not in CODING_RUNTIME_TARGETS, errors, "coding_delegation prompt_handoff must not target a runtime profile")
    _require(handoff.get("dispatchable") is False, errors, "coding_delegation prompt_handoff dispatchable must be false")
    for key in ("status", "recording_contract", "dispatch_contract", "prompt_template"):
        _require(isinstance(handoff.get(key), str), errors, f"coding_delegation prompt_handoff {key} must be a string")
    _require(handoff.get("status") == "prepared_not_observed", errors, "coding_delegation prompt_handoff status must be prepared_not_observed")
    _require(handoff.get("recording_contract") == "prompt_prepared_not_dispatched", errors, "coding_delegation prompt_handoff recording_contract is invalid")
    _require(handoff.get("dispatch_contract") == "prompt_only_no_dispatch", errors, "coding_delegation prompt_handoff dispatch_contract is invalid")
    _require("{message}" in str(handoff.get("prompt_template", "")), errors, "coding_delegation prompt_handoff prompt_template must keep {message} placeholder")
    forbidden = ("codex_skill", "codex_invocation", "executor_handoff", "run_id")
    for key in forbidden:
        _require(key not in handoff, errors, f"coding_delegation prompt_handoff must not contain {key}")
    invocation = handoff.get("invocation")
    _require(isinstance(invocation, dict), errors, "coding_delegation prompt_handoff invocation must be an object")
    if isinstance(invocation, dict):
        extra_invocation_keys = sorted(set(invocation) - set(CODING_PROMPT_HANDOFF_INVOCATION_KEYS))
        _require(not extra_invocation_keys, errors, f"coding_delegation prompt_handoff invocation has unsupported keys: {extra_invocation_keys}")
        for key in CODING_PROMPT_HANDOFF_INVOCATION_KEYS:
            _require(isinstance(invocation.get(key), str), errors, f"coding_delegation prompt_handoff invocation.{key} must be a string")
        _require(invocation.get("mode") == "copy_prompt", errors, "coding_delegation prompt_handoff invocation.mode must be copy_prompt")
        _require("{message}" in str(invocation.get("dispatch_text_template", "")), errors, "coding_delegation prompt_handoff invocation.dispatch_text_template must keep {message}")
    errors.extend(
        validate_optional_executor_local_capability_strategy(
            handoff,
            "coding_delegation prompt_handoff executor_local_capability_strategy",
            expected_profile=str(handoff.get("selected_executor_profile", "")),
        )
    )
    for key in ("scope", "non_goals", "acceptance_criteria", "verification"):
        _require(isinstance(handoff.get(key), list), errors, f"coding_delegation prompt_handoff {key} must be a list")
        if isinstance(handoff.get(key), list):
            for index, value in enumerate(handoff[key]):
                _require(isinstance(value, str), errors, f"coding_delegation prompt_handoff {key}[{index}] must be a string")
    review = handoff.get("review")
    _require(isinstance(review, dict), errors, "coding_delegation prompt_handoff review must be an object")
    if isinstance(review, dict):
        _require(isinstance(review.get("required"), bool), errors, "coding_delegation prompt_handoff review.required must be boolean")
        _require(review.get("workflow") is None or isinstance(review.get("workflow"), str), errors, "coding_delegation prompt_handoff review.workflow must be a string or null")
        _require(isinstance(review.get("evidence_required"), str), errors, "coding_delegation prompt_handoff review.evidence_required must be a string")
    contract = handoff.get("evidence_contract")
    _require(isinstance(contract, dict), errors, "coding_delegation prompt_handoff evidence_contract must be an object")
    if isinstance(contract, dict):
        for nested_key, nested_value in contract.items():
            _require(isinstance(nested_value, list), errors, f"coding_delegation prompt_handoff evidence_contract.{nested_key} must be a list")
            if isinstance(nested_value, list):
                for index, item in enumerate(nested_value):
                    _require(isinstance(item, str), errors, f"coding_delegation prompt_handoff evidence_contract.{nested_key}[{index}] must be a string")
    if "harness_quality" in handoff:
        errors.extend(validate_harness_quality(handoff["harness_quality"], "coding_delegation prompt_handoff harness_quality"))
    if "executor_readiness" in handoff:
        errors.extend(
            validate_executor_readiness(
                handoff["executor_readiness"],
                "coding_delegation prompt_handoff executor_readiness",
                expected_profile=str(handoff.get("selected_executor_profile", "")),
            )
        )
    errors.extend(validate_isolation_plan(handoff.get("isolation_plan"), "coding_delegation prompt_handoff isolation_plan"))
    errors.extend(validate_handoff_context_pack_fields(handoff, "coding_delegation prompt_handoff"))
    return errors


def validate_isolation_plan(value: Any, label: str) -> list[str]:
    errors: list[str] = []
    _require(isinstance(value, dict), errors, f"{label} must be an object")
    if not isinstance(value, dict):
        return errors
    extra_keys = sorted(set(value) - set(ISOLATION_PLAN_KEYS))
    missing_keys = sorted(set(ISOLATION_PLAN_KEYS) - set(value))
    _require(not extra_keys, errors, f"{label} has unsupported keys: {extra_keys}")
    _require(not missing_keys, errors, f"{label} is missing keys: {missing_keys}")
    _require(value.get("schema_version") == ISOLATION_SCHEMA_VERSION, errors, f"{label} schema_version is invalid")
    _require(value.get("status") in ISOLATION_STATUSES, errors, f"{label} status is invalid: {value.get('status')!r}")
    _require(value.get("strategy") in ISOLATION_STRATEGIES, errors, f"{label} strategy is invalid: {value.get('strategy')!r}")
    _require(value.get("risk_level") in ISOLATION_RISK_LEVELS, errors, f"{label} risk_level is invalid: {value.get('risk_level')!r}")
    for key in ("workspace_policy", "session_binding", "claim_boundary"):
        _require(isinstance(value.get(key), str), errors, f"{label} {key} must be a string")
    _require("not proof" in str(value.get("claim_boundary", "")).lower(), errors, f"{label} claim_boundary must preserve observed-evidence boundary")
    for key in ("reason_codes", "required_before", "recommended_when", "wrapper_actions", "observation_events", "not_observed_by_omh"):
        _require(isinstance(value.get(key), list), errors, f"{label} {key} must be a list")
        if isinstance(value.get(key), list):
            for index, item in enumerate(value[key]):
                _require(isinstance(item, str), errors, f"{label} {key}[{index}] must be a string")
    if value.get("strategy") != "same_workspace_ok":
        actions = value.get("wrapper_actions", [])
        _require("prepare_worktree" in actions, errors, f"{label} wrapper_actions must include prepare_worktree when isolation is recommended")
    _require(
        "open_executor_session" in value.get("wrapper_actions", []),
        errors,
        f"{label} wrapper_actions must include open_executor_session",
    )
    _require(
        "git worktree creation" in value.get("not_observed_by_omh", []),
        errors,
        f"{label} not_observed_by_omh must include git worktree creation",
    )
    return errors


def validate_executor_readiness(value: Any, label: str, *, expected_profile: str = "") -> list[str]:
    errors: list[str] = []
    _require(isinstance(value, dict), errors, f"{label} must be an object")
    if not isinstance(value, dict):
        return errors
    allowed_keys = {
        "schema_version",
        "profile",
        "label",
        "status",
        "first_use_only",
        "cache_key",
        "probe",
        "ready_action",
        "fallback_policy",
        "not_evidence",
        "claim_boundary",
        "profiles",
        "next_action",
        "cache_status",
        "first_use_skipped",
        "state_error",
        "available",
        "observed_once",
        "exit_code",
        "command_path",
        "summary",
    }
    extra_keys = sorted(set(value) - allowed_keys)
    _require(not extra_keys, errors, f"{label} has unsupported keys: {extra_keys}")
    _require(value.get("schema_version") == EXECUTOR_READINESS_SCHEMA_VERSION, errors, f"{label} schema_version is invalid")
    profile = str(value.get("profile", ""))
    _require(profile in ("choose", *CODING_SELECTED_EXECUTOR_PROFILES), errors, f"{label} profile is invalid: {profile!r}")
    if expected_profile:
        _require(profile == expected_profile, errors, f"{label} profile must match selected executor")
    _require(value.get("status") in EXECUTOR_READINESS_STATUSES, errors, f"{label} status is invalid")
    _require(isinstance(value.get("first_use_only"), bool), errors, f"{label} first_use_only must be boolean")
    for key in ("cache_key", "claim_boundary"):
        _require(isinstance(value.get(key), str), errors, f"{label} {key} must be a string")
    _require("not dispatch" in str(value.get("claim_boundary", "")).lower(), errors, f"{label} claim_boundary must preserve dispatch boundary")
    if "probe" in value:
        probe = value.get("probe")
        _require(isinstance(probe, dict), errors, f"{label} probe must be an object")
        if isinstance(probe, dict):
            expected_probe_keys = {"kind", "command", "args", "timeout_seconds", "captures"}
            _require(not (set(probe) - expected_probe_keys), errors, f"{label} probe has unsupported keys: {sorted(set(probe) - expected_probe_keys)}")
            for key in ("kind", "command"):
                _require(isinstance(probe.get(key), str), errors, f"{label} probe.{key} must be a string")
            _require(isinstance(probe.get("timeout_seconds"), int), errors, f"{label} probe.timeout_seconds must be an integer")
            for key in ("args", "captures"):
                _require(isinstance(probe.get(key), list), errors, f"{label} probe.{key} must be a list")
                if isinstance(probe.get(key), list):
                    for index, item in enumerate(probe[key]):
                        _require(isinstance(item, str), errors, f"{label} probe.{key}[{index}] must be a string")
    fallback = value.get("fallback_policy")
    _require(isinstance(fallback, dict), errors, f"{label} fallback_policy must be an object")
    if isinstance(fallback, dict):
        expected_fallback_keys = {"when_missing", "retry_after_state_change", "retry_limit", "suggested_actions"}
        _require(not (set(fallback) - expected_fallback_keys), errors, f"{label} fallback_policy has unsupported keys: {sorted(set(fallback) - expected_fallback_keys)}")
        _require(isinstance(fallback.get("when_missing"), str), errors, f"{label} fallback_policy.when_missing must be a string")
        _require(isinstance(fallback.get("retry_after_state_change"), bool), errors, f"{label} fallback_policy.retry_after_state_change must be boolean")
        _require(isinstance(fallback.get("retry_limit"), int), errors, f"{label} fallback_policy.retry_limit must be an integer")
        if "suggested_actions" in fallback:
            _require(isinstance(fallback.get("suggested_actions"), list), errors, f"{label} fallback_policy.suggested_actions must be a list")
    if "not_evidence" in value:
        _require(isinstance(value.get("not_evidence"), list), errors, f"{label} not_evidence must be a list")
        not_evidence = value.get("not_evidence") if isinstance(value.get("not_evidence"), list) else []
        _require("execution" in not_evidence and "merge" in not_evidence, errors, f"{label} not_evidence must include execution and merge")
    profiles = value.get("profiles")
    if profiles is not None:
        _require(isinstance(profiles, list), errors, f"{label} profiles must be a list")
        if isinstance(profiles, list):
            for index, profile_value in enumerate(profiles):
                errors.extend(validate_executor_readiness(profile_value, f"{label} profiles[{index}]"))
    return errors


def validate_handoff_context_pack_fields(handoff: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    has_pack = "context_pack" in handoff
    has_blocked = "context_pack_blocked" in handoff
    _require(not (has_pack and has_blocked), errors, f"{label} must not contain both context_pack and context_pack_blocked")
    if has_pack:
        errors.extend(validate_handoff_context_pack(handoff.get("context_pack"), require_conflict_free=True, label=f"{label} context_pack"))
    if has_blocked:
        errors.extend(validate_handoff_context_blocked(handoff.get("context_pack_blocked"), label=f"{label} context_pack_blocked"))
    return errors


def validate_coding_handoff_combination(delegation: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    mode = delegation.get("work_owner_mode")
    selected = delegation.get("selected_executor_profile")
    dispatchable = delegation.get("dispatchable")
    has_executor = "executor_handoff" in delegation
    has_runtime = "runtime_handoff" in delegation
    has_prompt = "prompt_handoff" in delegation
    choice_required = bool(delegation.get("executor_selection", {}).get("choice_required")) if isinstance(delegation.get("executor_selection"), dict) else False
    if mode == "retained_hermes":
        _require(not has_executor, errors, f"{label} retained_hermes must not include executor_handoff")
        _require(not has_runtime, errors, f"{label} retained_hermes must not include runtime_handoff")
        _require(not has_prompt, errors, f"{label} retained_hermes must not include prompt_handoff")
        _require(dispatchable is False, errors, f"{label} retained_hermes must not be dispatchable")
    if mode == "prompt_only_handoff":
        _require(has_prompt, errors, f"{label} prompt_only_handoff requires prompt_handoff")
        _require(not has_executor, errors, f"{label} prompt_only_handoff must not include executor_handoff")
        _require(not has_runtime, errors, f"{label} prompt_only_handoff must not include runtime_handoff")
        _require(dispatchable is False, errors, f"{label} prompt_only_handoff must not be dispatchable")
        _require(selected != "codex", errors, f"{label} prompt_only_handoff must not select codex")
    if mode == "runtime_handoff":
        _require(has_runtime, errors, f"{label} runtime_handoff requires runtime_handoff")
        _require(not has_executor, errors, f"{label} runtime_handoff must not include executor_handoff")
        _require(not has_prompt, errors, f"{label} runtime_handoff must not include prompt_handoff")
        _require(dispatchable is False, errors, f"{label} runtime_handoff must not be dispatchable")
        _require(selected in CODING_RUNTIME_TARGETS, errors, f"{label} runtime_handoff selected executor is invalid")
    if mode == "external_executor":
        if choice_required:
            _require(not has_executor and not has_runtime and not has_prompt, errors, f"{label} executor_choice_required must not include a handoff")
            _require(selected is None, errors, f"{label} executor_choice_required must not select an executor")
            _require(dispatchable is False, errors, f"{label} executor_choice_required must not be dispatchable")
        else:
            _require(selected == "codex", errors, f"{label} external_executor is Codex-only in phase 1")
            _require(has_executor, errors, f"{label} external_executor requires executor_handoff")
            _require(not has_runtime, errors, f"{label} external_executor must not include runtime_handoff")
            _require(not has_prompt, errors, f"{label} external_executor must not include prompt_handoff")
            _require(dispatchable is True, errors, f"{label} external_executor must be dispatchable")
    return errors


def _compact_harness_quality(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in HARNESS_QUALITY_KEYS:
        if key not in value:
            continue
        if key in {"quality_bar", "evidence_ladder", "wrapper_actions", "overclaim_guards"}:
            compact[key] = _compact_string_list(value.get(key, []))
        else:
            compact[key] = str(value.get(key, ""))
    return compact


def validate_harness_quality(value: Any, label: str = "harness_quality") -> list[str]:
    errors: list[str] = []
    _require(isinstance(value, dict), errors, f"{label} must be an object")
    if not isinstance(value, dict):
        return errors
    extra_keys = sorted(set(value) - set(HARNESS_QUALITY_KEYS))
    _require(not extra_keys, errors, f"{label} has unsupported keys: {extra_keys}")
    _require(value.get("schema_version") == HARNESS_QUALITY_SCHEMA_VERSION, errors, f"{label} schema_version is invalid")
    for key in ("harness", "quality_tier"):
        _require(isinstance(value.get(key), str), errors, f"{label} {key} must be a string")
        _require(bool(str(value.get(key, ""))), errors, f"{label} {key} is required")
    for key in ("quality_bar", "evidence_ladder", "wrapper_actions", "overclaim_guards"):
        _require(isinstance(value.get(key), list), errors, f"{label} {key} must be a list")
        if not isinstance(value.get(key), list):
            continue
        _require(len(value[key]) >= 1, errors, f"{label} {key} must not be empty")
        for index, item in enumerate(value[key]):
            _require(isinstance(item, str), errors, f"{label} {key}[{index}] must be a string")
    return errors


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


OPTIONAL_RECORD_VALIDATORS = (
    ("routing.json", validate_routing_record),
    ("coding_delegation.json", validate_coding_delegation_record),
    ("delegation.json", validate_delegation_record),
    ("wrapper.json", validate_wrapper_record),
    ("review.json", validate_review_record),
    ("ci.json", validate_ci_record),
    ("merge.json", validate_merge_record),
)
