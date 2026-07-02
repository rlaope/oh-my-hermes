from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from ..local_store import atomic_write_json, ensure_dir, read_json_object, utc_now
from ..paths import OmhPaths
from ..runtime.artifacts import show_run
from .self_improvement_store_contract import (
    SELF_IMPROVEMENT_DESTINATION_DETAILS,
    SELF_IMPROVEMENT_DESTINATION_PRIORITY,
    SELF_IMPROVEMENT_STORE_ROUTING_SCHEMA_VERSION,
    self_improvement_store_destination_details,
    self_improvement_store_destinations,
)
from .workflow_learning_errors import WorkflowLearningError


WORKFLOW_LEARNING_TRACE_SCHEMA_VERSION = "workflow_learning_trace/v1"
WORKFLOW_EVAL_RESULT_SCHEMA_VERSION = "workflow_eval_result/v1"
IMPROVEMENT_CANDIDATE_SCHEMA_VERSION = "improvement_candidate/v1"
IMPROVEMENT_CANDIDATE_REVIEW_CARD_SCHEMA_VERSION = "improvement_candidate_review_card/v1"
IMPROVEMENT_PATCH_PROPOSAL_SCHEMA_VERSION = "improvement_patch_proposal/v1"
WORKFLOW_LEARNING_REVIEW_QUEUE_SCHEMA_VERSION = "workflow_learning_review_queue/v1"
REGRESSION_CASE_SCHEMA_VERSION = "regression_case/v1"
WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION = "workflow_learning_index/v1"
WORKFLOW_LEARNING_EXPORT_SCHEMA_VERSION = "workflow_learning_export/v1"
WORKFLOW_LEARNING_AUDIT_SCHEMA_VERSION = "workflow_learning_audit/v1"
LEARNING_AUDIT_CARD_SCHEMA_VERSION = "learning_audit_card/v1"
MISSED_ROUTE_RESULT_SCHEMA_VERSION = "learning_missed_route_result/v1"
TRACE_REF_PREFIX = "omh-learning-trace"
EXPORT_REF_PREFIX = "omh-learning-export"
PRIVACY_MODE = "metadata_only"
LEARNING_EVENT_KIND = "workflow_learning"
LEARNING_INDEX_MAX_RECORDS = 500
FORBIDDEN_TRACE_KEYS = {
    "message",
    "raw_message",
    "prompt",
    "raw_prompt",
    "prompt_body",
    "body_text",
    "body_preview",
    "routing_prompt",
    "dispatch_text_template",
    "fixture_text",
    "redacted_message",
}
EXPORT_ALLOWED_RAW_FLAG_KEYS = {
    "raw_prompt_stored",
    "raw_platform_event_stored",
}
EXPORT_FORBIDDEN_PAYLOAD_KEYS = FORBIDDEN_TRACE_KEYS | {
    "raw_text",
    "rawText",
    "raw_payload",
    "rawPayload",
    "raw_platform_event",
    "rawPlatformEvent",
    "platform_event",
    "platformEvent",
    "event_json",
    "eventJson",
    "transcript",
    "conversation",
    "stdout",
    "stderr",
}
_SELF_IMPROVEMENT_ALLOWED_RAW_TEXT_STORED_PATH = "signal.raw_text_stored"
_SELF_IMPROVEMENT_FORBIDDEN_NORMALIZED_PAYLOAD_KEYS = {
    re.sub(r"[^a-z0-9]+", "", key.casefold()) for key in EXPORT_FORBIDDEN_PAYLOAD_KEYS
} | {"rawtextstored"}
_OBSERVED_STATES = {"observed", "verified", "complete", "completed", "ready", "merged"}
_LEARNING_OUTCOMES = {"unknown", "useful", "not_useful", "blocked", "failed"}
_PRIVATE_OR_RAW_SIGNAL_TERMS = (
    "secret-token",
    "api token",
    "api key",
    "password",
    "credential",
    "private key",
    "raw transcript",
    "raw prompt",
    "raw log",
)
_TRANSIENT_SIGNAL_TERMS = (
    "temporary",
    "temp shell",
    "local session only",
    "this local session",
    "this shell",
    "path was wrong",
    "missing binary",
    "not installed locally",
    "one-off",
)
_AUTOMATION_RECURRING_TERMS = (
    "daily",
    "weekly",
    "monthly",
    "every day",
    "every week",
    "cron",
    "schedule",
    "recurring",
    "background self-improvement",
    "매일",
    "매주",
    "주기적",
)
_AUTOMATION_ACTION_TERMS = (
    "suggest",
    "create",
    "run",
    "review",
    "remind",
    "notify",
    "돌려",
    "알림",
    "제안",
)
_WIKI_SIGNAL_TERMS = (
    "according to",
    "docs",
    "documentation",
    "source-backed",
    "citation",
    "paper",
    "research",
    "wiki",
    "schema.md",
    "index.md",
    "api reference",
    "standard",
    "출처",
    "문서",
    "위키",
)
_FAILURE_SIGNAL_TERMS = (
    "ci failed",
    "test failed",
    "failed",
    "failure",
    "root cause",
    "postmortem",
    "retrospective",
    "regression",
    "blocked",
    "broke",
    "incident",
    "실패",
    "회고",
    "원인",
)
_SKILL_SIGNAL_TERMS = (
    "workflow",
    "skill",
    "agent",
    "subagent",
    "handoff",
    "route",
    "routing",
    "clarify",
    "question",
    "reviewer",
    "builder",
    "interviewer",
    "codex",
    "hermes",
    "omh",
    "스킬",
    "워크플로",
    "에이전트",
)
_SKILL_BEHAVIOR_TERMS = (
    "should",
    "must",
    "instead",
    "always",
    "never",
    "when",
    "ask",
    "물어",
    "자주",
    "애매",
)
_MEMORY_SIGNAL_TERMS = (
    "i prefer",
    "my preference",
    "please remember i",
    "remember i",
    "call me",
    "reply to me",
    "i like",
    "내가 선호",
    "나는",
    "내 취향",
    "기억해",
)


def learning_trace_ref(trace_id: str) -> str:
    return f"{TRACE_REF_PREFIX}:{trace_id}"


def learning_export_ref(export_id: str) -> str:
    return f"{EXPORT_REF_PREFIX}:{export_id}"


def build_trace_from_chat_interaction(
    interaction: dict[str, Any],
    *,
    source_ref: str = "",
    outcome: str = "unknown",
    feedback_summary: str = "",
    trace_id: str | None = None,
) -> dict[str, Any]:
    if interaction.get("schema_version") != "chat_interaction/v1":
        raise WorkflowLearningError("learning trace requires chat_interaction/v1")
    if outcome not in _LEARNING_OUTCOMES:
        raise WorkflowLearningError(f"unsupported learning outcome: {outcome}")

    route = _object(interaction.get("route"))
    chat_response = _object(interaction.get("chat_response"))
    state = _object(chat_response.get("state"))
    explanation = _object(state.get("workflow_explanation"))
    usage_trace = _object(chat_response.get("usage_trace"))
    selected_workflow = _first_nonempty(
        route.get("selected_skill"),
        explanation.get("selected_workflow"),
        usage_trace.get("selected_workflow"),
        state.get("selected_workflow"),
        "unknown",
    )
    selected_harness = _first_nonempty(
        explanation.get("selected_harness"),
        usage_trace.get("selected_harness"),
        route.get("selected_harness"),
        "unknown",
    )
    evidence_state = _first_nonempty(
        usage_trace.get("evidence_state"),
        state.get("observation_status"),
        _nested(interaction, "delegation", "status"),
        "prepared_not_observed",
    )
    now = utc_now()
    source = {
        "kind": "chat_interaction",
        "source": str(interaction.get("source", "generic")),
        "source_ref": source_ref,
        "thread_key": str(interaction.get("thread_key", "")),
        "message_sha256": str(interaction.get("message_sha256", "")),
        "message_length": int(interaction.get("message_length", 0) or 0),
        "source_metadata": _safe_metadata(_object(interaction.get("source_metadata"))),
    }
    seed = json.dumps(
        {
            "source": source,
            "workflow": selected_workflow,
            "harness": selected_harness,
            "next_action": interaction.get("next_action", ""),
            "source_ref": source_ref,
        },
        sort_keys=True,
    )
    trace = {
        "schema_version": WORKFLOW_LEARNING_TRACE_SCHEMA_VERSION,
        "record_type": "workflow_learning_trace",
        "trace_id": trace_id or _id("wlt", seed),
        "created_at": now,
        "updated_at": now,
        "privacy": {
            "mode": PRIVACY_MODE,
            "raw_prompt_stored": False,
            "raw_platform_event_stored": False,
            "redaction_policy": str(interaction.get("redaction_policy", PRIVACY_MODE)),
            "stored_fields": [
                "message hash",
                "message length",
                "source metadata",
                "route summary",
                "workflow explanation",
                "evidence references",
            ],
        },
        "source": source,
        "route": {
            "action": str(route.get("action", "")),
            "selected_workflow": str(selected_workflow),
            "selected_harness": str(selected_harness),
            "confidence": str(route.get("confidence", "")),
            "score": route.get("score", 0),
            "matched": _list(route.get("matched")),
        },
        "workflow": {
            "selected_workflow": str(selected_workflow),
            "selected_harness": str(selected_harness),
            "workflow_context_id": str(explanation.get("workflow_context_id") or usage_trace.get("workflow_context_id") or ""),
            "phase": str(usage_trace.get("phase") or state.get("phase") or ""),
            "next_action": str(interaction.get("next_action") or usage_trace.get("next_action") or state.get("next_action") or ""),
        },
        "reasoning_summary": {
            "why_this_workflow": str(explanation.get("why_this_workflow", "")),
            "next_action": str(explanation.get("next_action") or state.get("next_action") or interaction.get("next_action") or ""),
            "not_evidence_yet": _strings(explanation.get("not_evidence_yet") or state.get("evidence_not_observed") or []),
            "claim_boundary": str(explanation.get("claim_boundary") or chat_response.get("claim_boundary") or ""),
        },
        "prepared_refs": _prepared_refs(interaction),
        "observed_refs": [],
        "status": {
            "evidence_state": str(evidence_state),
            "learning_state": "recorded",
            "outcome": outcome,
            "feedback_summary": feedback_summary,
        },
        "improvement": {
            "candidate_available": False,
            "candidate_refs": [],
            "regression_case_refs": [],
        },
        "overclaim_guard": _strings(interaction.get("overclaim_guard"))
        or [
            "Prepared workflow artifacts are not observed execution evidence.",
            "Learning traces are review material, not automatic skill patches.",
        ],
    }
    validate_workflow_learning_trace(trace)
    return trace


def build_trace_from_runtime_run(
    paths: OmhPaths,
    run_id: str,
    *,
    outcome: str = "unknown",
    feedback_summary: str = "",
    trace_id: str | None = None,
) -> dict[str, Any]:
    if outcome not in _LEARNING_OUTCOMES:
        raise WorkflowLearningError(f"unsupported learning outcome: {outcome}")
    shown = show_run(paths, run_id)
    run = _object(shown.get("run"))
    routing = _object(shown.get("routing"))
    coding = _object(shown.get("coding_delegation"))
    wrapper = _object(shown.get("wrapper"))
    observations = [record for record in _list(shown.get("runtime_observations")) if isinstance(record, dict)]
    selected_workflow = _first_nonempty(coding.get("recommended_workflow"), routing.get("selected_skill"), run.get("skill"), "unknown")
    selected_harness = _first_nonempty(coding.get("recommended_harness"), routing.get("selected_harness"), run.get("harness"), "unknown")
    evidence_state = str(run.get("observation_status") or coding.get("status") or "prepared_not_observed")
    observed_refs = [
        {
            "kind": "runtime_observation",
            "ref": f"runtime:{run_id}:{record.get('event_type', 'unknown')}",
            "event_type": str(record.get("event_type", "")),
            "status": str(record.get("status", "")),
            "evidence_refs": _strings(record.get("evidence_refs")),
        }
        for record in observations
    ]
    if any(ref["status"] == "observed" for ref in observed_refs):
        evidence_state = "observed"
    now = utc_now()
    trace = {
        "schema_version": WORKFLOW_LEARNING_TRACE_SCHEMA_VERSION,
        "record_type": "workflow_learning_trace",
        "trace_id": trace_id or _id("wlt", f"runtime:{run_id}:{selected_workflow}:{selected_harness}"),
        "created_at": now,
        "updated_at": now,
        "privacy": {
            "mode": PRIVACY_MODE,
            "raw_prompt_stored": False,
            "raw_platform_event_stored": False,
            "redaction_policy": PRIVACY_MODE,
            "stored_fields": ["run id", "route summary", "runtime observation refs", "evidence refs"],
        },
        "source": {
            "kind": "runtime_run",
            "source": str(coding.get("source") or run.get("trigger") or "runtime"),
            "source_ref": f"runtime:{run_id}",
            "thread_key": "",
            "message_sha256": str(coding.get("message_sha256") or routing.get("message_sha256") or ""),
            "message_length": int(coding.get("message_length") or routing.get("message_length") or 0),
            "source_metadata": _safe_metadata(_object(coding.get("source_metadata") or routing.get("source_metadata"))),
        },
        "route": {
            "action": str(coding.get("action") or routing.get("action") or ""),
            "selected_workflow": str(selected_workflow),
            "selected_harness": str(selected_harness),
            "confidence": str(routing.get("confidence", "")),
            "score": routing.get("score", 0),
            "matched": _strings(routing.get("matched")),
        },
        "workflow": {
            "selected_workflow": str(selected_workflow),
            "selected_harness": str(selected_harness),
            "workflow_context_id": "",
            "phase": str(run.get("phase") or "runtime"),
            "next_action": "show_status",
        },
        "reasoning_summary": {
            "why_this_workflow": "Projected from a local runtime run artifact.",
            "next_action": "review_trace_or_record_more_evidence",
            "not_evidence_yet": _runtime_not_evidence_yet(shown),
            "claim_boundary": (
                "Runtime traces include only observed runtime_observation/v1 records. "
                "Missing ladder steps remain unobserved."
            ),
        },
        "prepared_refs": _runtime_prepared_refs(run_id, shown),
        "observed_refs": observed_refs,
        "status": {
            "evidence_state": evidence_state,
            "learning_state": "recorded",
            "outcome": outcome,
            "feedback_summary": feedback_summary or str(wrapper.get("summary", "")),
        },
        "improvement": {
            "candidate_available": False,
            "candidate_refs": [],
            "regression_case_refs": [],
        },
        "overclaim_guard": [
            "Runtime traces do not prove missing review, CI, merge-readiness, or merge events.",
            "Learning traces are review material, not automatic skill patches.",
        ],
    }
    validate_workflow_learning_trace(trace)
    return trace


def write_learning_trace(paths: OmhPaths, trace: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_learning_trace(trace)
    path = trace_path(paths, str(trace["trace_id"]))
    atomic_write_json(path, trace, private=True)
    _update_learning_index(paths, trace, "trace")
    return trace


def list_learning_traces(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    indexed = [_trace_summary(trace) for trace in _records_from_index(paths, "trace", trace_path, validate_workflow_learning_trace)]
    if indexed:
        return _apply_limit(indexed, limit)
    if not paths.learning_traces_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(paths.learning_traces_dir.glob("*.json")):
        item = read_json_object(path)
        if item:
            validate_workflow_learning_trace(item)
            records.append(_trace_summary(item))
    return _apply_limit(records, limit)


def show_learning_trace(paths: OmhPaths, trace_id: str) -> dict[str, Any]:
    trace = read_json_object(trace_path(paths, trace_id))
    if not trace:
        raise FileNotFoundError(trace_id)
    validate_workflow_learning_trace(trace)
    return trace


def build_workflow_eval_result(
    trace: dict[str, Any],
    *,
    rubric_id: str = "default",
    eval_id: str | None = None,
) -> dict[str, Any]:
    validate_workflow_learning_trace(trace)
    checks = [
        _check(
            "schema_valid",
            "passed",
            "workflow_learning_trace/v1 validated.",
            [learning_trace_ref(str(trace["trace_id"]))],
        ),
        _privacy_check(trace),
        _routing_check(trace),
        _boundary_check(trace),
        _workflow_specific_check(trace),
    ]
    failed = any(check["status"] == "failed" for check in checks)
    warnings = [check for check in checks if check["status"] == "warning"]
    now = utc_now()
    result = {
        "schema_version": WORKFLOW_EVAL_RESULT_SCHEMA_VERSION,
        "record_type": "workflow_eval_result",
        "eval_id": eval_id or _id("wle", f"{trace['trace_id']}:{rubric_id}:{now}"),
        "trace_id": str(trace["trace_id"]),
        "created_at": now,
        "rubric_id": rubric_id,
        "status": "failed" if failed else ("warning" if warnings else "passed"),
        "checks": checks,
        "summary": _eval_summary(failed=failed, warnings=warnings),
        "claim_boundary": "Workflow evals judge recorded metadata and evidence refs only; they do not execute workflows or patch skills.",
    }
    validate_workflow_eval_result(result)
    return result


def build_self_improvement_store_routing(
    signal_text: str,
    *,
    source_kind: str = "operator_feedback",
    observed_refs: list[str] | None = None,
) -> dict[str, Any]:
    classification = _classify_self_improvement_store(signal_text)
    payload = {
        "schema_version": SELF_IMPROVEMENT_STORE_ROUTING_SCHEMA_VERSION,
        "status": "prepared",
        "generated_at": utc_now(),
        "signal": {
            "source_kind": _safe_store_route_token(source_kind) or "operator_feedback",
            "sha256": hashlib.sha256(str(signal_text or "").encode("utf-8")).hexdigest(),
            "length": len(str(signal_text or "")),
            "raw_text_stored": False,
        },
        "classification": classification,
        "review_gate": {
            "required": True,
            "decision": "pending",
            "allowed_decisions": ["approve_destination", "change_destination", "discard"],
            "reason": "Prepared routing separates self-improvement stores before any durable write.",
        },
        "observed_ref_hashes": _export_ref_values(observed_refs or []),
        "writes_observed": False,
        "next_action": str(classification["next_action"]),
        "wrapper_actions": [
            "review_self_improvement_store_route",
            "prepare_memory_curation_review",
            "review_improvement",
            "prepare_wiki_guidance",
            "record_workflow_learning_trace",
            "prepare_automation_blueprint",
            "do_not_store",
            "show_status",
        ],
        "not_evidence_yet": [
            "memory write",
            "skill patch",
            "wiki write",
            "failure retrospective accepted",
            "automation created",
            "external connector write",
            "model training",
        ],
        "claim_boundary": (
            "Self-improvement store routing is prepared classification only. It does not write Hermes memory, "
            "patch skills, update a wiki, create automation, accept a retrospective, or prove future behavior changed."
        ),
    }
    validate_self_improvement_store_routing(payload)
    return payload


def write_workflow_eval(paths: OmhPaths, result: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_eval_result(result)
    atomic_write_json(eval_path(paths, str(result["eval_id"])), result, private=True)
    _update_learning_index(paths, result, "eval")
    return result


def latest_workflow_eval_result(paths: OmhPaths, trace_id: str, *, rubric_id: str = "default") -> dict[str, Any] | None:
    matches = [
        result
        for result in _read_valid_learning_records(paths.learning_evals_dir, validate_workflow_eval_result)
        if str(result.get("trace_id", "")) == trace_id and str(result.get("rubric_id", "")) == rubric_id
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: (str(item.get("created_at", "")), str(item.get("eval_id", ""))))[-1]


def build_improvement_candidate(
    trace: dict[str, Any],
    eval_result: dict[str, Any],
    *,
    candidate_id: str | None = None,
    target_type: str = "workflow_rubric",
    title: str = "",
) -> dict[str, Any]:
    validate_workflow_learning_trace(trace)
    validate_workflow_eval_result(eval_result)
    failed_or_warned = [check for check in _list(eval_result.get("checks")) if isinstance(check, dict) and check.get("status") in {"failed", "warning"}]
    now = utc_now()
    candidate = {
        "schema_version": IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
        "record_type": "improvement_candidate",
        "candidate_id": candidate_id or _id("wic", f"{trace['trace_id']}:{eval_result['eval_id']}:{now}"),
        "trace_id": str(trace["trace_id"]),
        "eval_id": str(eval_result["eval_id"]),
        "created_at": now,
        "target_type": target_type,
        "target_ref": _candidate_target_ref(target_type, trace, eval_result),
        "title": title or _candidate_title(trace, failed_or_warned),
        "status": "proposed",
        "human_gate": {
            "required": True,
            "decision": "pending",
            "allowed_decisions": ["approve", "revise", "reject"],
        },
        "proposal": {
            "problem_summary": _candidate_problem_summary(failed_or_warned),
            "suggested_change": _candidate_suggested_change(trace, failed_or_warned),
            "regression_case_recommended": True,
        },
        "diff_preview": {
            "available": False,
            "reason": "v1 records a reviewable candidate only; it does not mutate skill files or routing tables.",
        },
        "claim_boundary": "Improvement candidates are review material. They do not apply patches until a later explicit human-approved workflow exists.",
    }
    candidate["review_card"] = build_improvement_candidate_review_card(candidate)
    validate_improvement_candidate(candidate)
    return candidate


def build_improvement_candidate_review_card(candidate: dict[str, Any]) -> dict[str, Any]:
    _validate_improvement_candidate_core(candidate)
    gate = _object(candidate.get("human_gate"))
    proposal = _object(candidate.get("proposal"))
    diff_preview = _object(candidate.get("diff_preview"))
    decision = str(gate.get("decision", "pending"))
    status = _improvement_review_status(decision)
    card = {
        "schema_version": IMPROVEMENT_CANDIDATE_REVIEW_CARD_SCHEMA_VERSION,
        "record_type": "improvement_candidate_review_card",
        "candidate_id": str(candidate.get("candidate_id", "")),
        "trace_id": str(candidate.get("trace_id", "")),
        "eval_id": str(candidate.get("eval_id", "")),
        "status": status,
        "severity": _improvement_review_severity(status),
        "headline": _improvement_review_headline(status),
        "summary": _improvement_review_summary(candidate),
        "target": {
            "type": str(candidate.get("target_type", "")),
            "ref": str(candidate.get("target_ref", "")),
        },
        "review_gate": {
            "required": gate.get("required") is True,
            "decision": decision,
            "allowed_decisions": _strings(gate.get("allowed_decisions")),
            "human_approval_required": True,
        },
        "problem_statement": str(proposal.get("problem_summary", "")),
        "proposed_change_summary": str(proposal.get("suggested_change", "")),
        "diff_preview": {
            "available": diff_preview.get("available") is True,
            "reason": str(diff_preview.get("reason", "")),
        },
        "review_questions": [
            "Does the problem statement match the recorded eval failure or warning?",
            "Is the target surface the right source of truth for this workflow issue?",
            "Should a regression case exist before approving any future source change?",
        ],
        "steps": _improvement_review_steps(candidate),
        "primary_action": _improvement_review_primary_action(status),
        "wrapper_actions": [
            "review_improvement",
            "approve_improvement",
            "revise_improvement",
            "reject_improvement",
            "add_regression_case",
            "show_learning_eval",
            "audit_learning_readiness",
            "export_learning_bundle",
            "show_status",
        ],
        "not_evidence_yet": [
            "source patch applied",
            "skill or routing behavior changed",
            "regression case recorded",
            "regression replay passed",
            "future workflow behavior fixed",
            "model training",
            "workflow execution",
        ],
        "claim_boundary": str(candidate.get("claim_boundary", "")),
    }
    validate_improvement_candidate_review_card(card, candidate=candidate)
    return card


def write_improvement_candidate(paths: OmhPaths, candidate: dict[str, Any]) -> dict[str, Any]:
    validate_improvement_candidate(candidate)
    atomic_write_json(candidate_path(paths, str(candidate["candidate_id"])), candidate, private=True)
    _update_learning_index(paths, candidate, "candidate")
    return candidate


def show_improvement_candidate(paths: OmhPaths, candidate_id: str) -> dict[str, Any]:
    candidate = read_json_object(candidate_path(paths, candidate_id))
    if not candidate:
        raise FileNotFoundError(candidate_id)
    validate_improvement_candidate(candidate)
    return candidate


def review_improvement_candidate(
    paths: OmhPaths,
    candidate_id: str,
    *,
    decision: str,
    reviewer_ref: str = "operator",
    review_note: str = "",
) -> dict[str, Any]:
    if decision not in {"approve", "revise", "reject"}:
        raise WorkflowLearningError("candidate review decision must be approve, revise, or reject")
    candidate = show_improvement_candidate(paths, candidate_id)
    reviewed = json.loads(json.dumps(candidate))
    now = utc_now()
    gate = _object(reviewed.get("human_gate"))
    gate["decision"] = decision
    gate["reviewed_at"] = now
    gate["reviewer_ref"] = reviewer_ref or "operator"
    gate.pop("review_note_sha256", None)
    gate.pop("review_note_length", None)
    if review_note:
        gate["review_note_sha256"] = hashlib.sha256(review_note.encode("utf-8")).hexdigest()
        gate["review_note_length"] = len(review_note)
    reviewed["human_gate"] = gate
    reviewed["updated_at"] = now
    reviewed["status"] = {
        "approve": "accepted",
        "revise": "proposed",
        "reject": "rejected",
    }[decision]
    reviewed["review_card"] = build_improvement_candidate_review_card(reviewed)
    write_improvement_candidate(paths, reviewed)
    return reviewed


def build_improvement_patch_proposal(
    paths: OmhPaths,
    candidate: dict[str, Any],
    *,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    validate_improvement_candidate(candidate)
    trace_id = str(candidate.get("trace_id", ""))
    related_regressions = _read_related_regression_cases(paths, trace_id)
    replay = _replay_related_regression_cases(related_regressions)
    decision = str(_nested(candidate, "human_gate", "decision") or "pending")
    status = _patch_proposal_status(
        decision=decision,
        regression_count=len(related_regressions),
        replay_status=str(replay.get("status", "")),
    )
    now = utc_now()
    target_type = str(candidate.get("target_type", ""))
    target_ref = str(candidate.get("target_ref", ""))
    regression_snapshot = _patch_regression_snapshot(related_regressions, replay)
    seed = json.dumps(
        {
            "candidate_id": str(candidate.get("candidate_id", "")),
            "decision": decision,
            "target_ref": target_ref,
            "replay_status": replay.get("status", ""),
            "regression_snapshot": regression_snapshot,
        },
        sort_keys=True,
    )
    proposal = {
        "schema_version": IMPROVEMENT_PATCH_PROPOSAL_SCHEMA_VERSION,
        "record_type": "improvement_patch_proposal",
        "proposal_id": proposal_id or _id("wlp", seed),
        "candidate_id": str(candidate.get("candidate_id", "")),
        "trace_id": trace_id,
        "eval_id": str(candidate.get("eval_id", "")),
        "created_at": now,
        "status": status,
        "target": {
            "type": target_type,
            "ref": target_ref,
            "source_files": _patch_target_files(target_type, target_ref),
        },
        "source_refs": {
            "candidate_ref": _record_ref("candidate", str(candidate.get("candidate_id", ""))),
            "trace_ref": learning_trace_ref(trace_id),
            "eval_ref": _record_ref("eval", str(candidate.get("eval_id", ""))),
            "regression_case_refs": [
                _record_ref("regression_case", str(case.get("case_id", ""))) for case in related_regressions
            ],
        },
        "review_gate": {
            "candidate_decision": decision,
            "human_approval_required": True,
            "ready_for_patch_work": status == "ready_for_human_patch",
        },
        "problem_statement": str(_nested(candidate, "proposal", "problem_summary") or ""),
        "proposed_change_summary": str(_nested(candidate, "proposal", "suggested_change") or ""),
        "patch_scope": {
            "mode": "proposal_only",
            "apply_path_available": False,
            "allowed_target_types": ["skill", "routing", "workflow_rubric", "docs", "validator", "playbook"],
            "change_owner": "future explicit human-approved PR or executor handoff",
        },
        "regression_gate": {
            "required": True,
            "case_count": len(related_regressions),
            "replay_status": str(replay.get("status", "")),
            "passed": replay.get("status") == "passed",
            "snapshot": regression_snapshot,
            "results": _patch_replay_results(replay),
        },
        "required_gates": _patch_required_gates(status),
        "verification_commands": [
            "PYTHONPATH=tests uv run python -m unittest tests/test_workflow_learning.py tests/test_cli.py tests/test_wrapper_contract.py -v",
            "uv run python -m compileall -q src tests",
            "uv run python -m omh.cli docs workflows --check",
            "uv run python -m omh.cli harness validate",
            "git diff --check",
        ],
        "steps": _patch_proposal_steps(status),
        "primary_action": _patch_proposal_primary_action(status),
        "wrapper_actions": [
            "show_patch_proposal",
            "copy_patch_handoff",
            "add_regression_case",
            "replay_regression_cases",
            "review_improvement",
            "approve_improvement",
            "audit_learning_readiness",
            "show_status",
        ],
        "not_evidence_yet": [
            "source patch applied",
            "generated skill updated",
            "routing behavior changed",
            "regression replay after patch",
            "code review passed",
            "CI passed",
            "future workflow behavior fixed",
            "model training",
        ],
        "claim_boundary": (
            "Improvement patch proposals are review and handoff material only. "
            "They do not edit source files, regenerate skills, run tests, pass review, or prove future behavior changed."
        ),
    }
    validate_improvement_patch_proposal(proposal, candidate=candidate)
    return proposal


def write_improvement_patch_proposal(paths: OmhPaths, proposal: dict[str, Any]) -> dict[str, Any]:
    validate_improvement_patch_proposal(proposal)
    atomic_write_json(patch_proposal_path(paths, str(proposal["proposal_id"])), proposal, private=True)
    _update_learning_index(paths, proposal, "patch_proposal")
    return proposal


def build_regression_case_from_trace(
    trace: dict[str, Any],
    *,
    case_id: str | None = None,
    redacted_message: str = "",
    expected_workflow: str | None = None,
    expected_harness: str | None = None,
    expected_next_action: str | None = None,
) -> dict[str, Any]:
    validate_workflow_learning_trace(trace)
    workflow = _object(trace.get("workflow"))
    reasoning = _object(trace.get("reasoning_summary"))
    source = _object(trace.get("source"))
    fixture_text = redacted_message
    fixture_sha256 = hashlib.sha256(fixture_text.encode("utf-8")).hexdigest() if fixture_text else ""
    expected = {
        "selected_workflow": expected_workflow or str(workflow.get("selected_workflow", "")),
        "selected_harness": expected_harness or str(workflow.get("selected_harness", "")),
        "next_action": expected_next_action or str(workflow.get("next_action", "")),
        "claim_boundary_contains": _first_sentence(str(reasoning.get("claim_boundary", ""))),
        "not_evidence_yet_includes": _strings(reasoning.get("not_evidence_yet"))[:5],
    }
    case_seed = json.dumps(
        {
            "trace_id": str(trace["trace_id"]),
            "fixture_sha256": fixture_sha256,
            "expected": expected,
        },
        sort_keys=True,
    )
    now = utc_now()
    case = {
        "schema_version": REGRESSION_CASE_SCHEMA_VERSION,
        "record_type": "regression_case",
        "case_id": case_id or _id("wrc", case_seed),
        "trace_id": str(trace["trace_id"]),
        "created_at": now,
        "fixture": {
            "source": str(source.get("source", "generic")),
            "fixture_text": fixture_text,
            "fixture_sha256": fixture_sha256,
            "message_sha256": str(source.get("message_sha256", "")),
            "message_length": int(source.get("message_length", 0) or 0),
            "privacy": {
                "mode": "operator_provided_minimized_fixture" if fixture_text else "missing_fixture",
                "raw_prompt_stored": False,
                "operator_must_redact_private_content": True,
                "redaction_provable_by_omh": False,
            },
        },
        "expected": expected,
        "replay_policy": {
            "mode": "deterministic_router",
            "requires_fixture_text": True,
            "skip_reason": "" if fixture_text else "No operator-provided minimized fixture was provided.",
        },
        "claim_boundary": (
            "Regression cases replay only operator-provided minimized fixture text. "
            "OMH cannot prove that the fixture is redacted, and it must not be treated "
            "as raw prompt storage or observed workflow execution."
        ),
    }
    validate_regression_case(case)
    return case


def write_regression_case(paths: OmhPaths, case: dict[str, Any]) -> dict[str, Any]:
    validate_regression_case(case)
    atomic_write_json(regression_case_path(paths, str(case["case_id"])), case, private=True)
    _update_learning_index(paths, case, "regression_case")
    return case


def record_missed_route(
    paths: OmhPaths,
    interaction: dict[str, Any],
    *,
    source_ref: str = "",
    expected_workflow: str | None = None,
    expected_harness: str | None = None,
    expected_next_action: str | None = None,
    fixture_message: str = "",
    rubric_id: str = "missed-route",
    target_type: str = "routing",
    title: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    trace = build_trace_from_chat_interaction(
        interaction,
        source_ref=source_ref,
        outcome="failed",
        feedback_summary="Operator reported that Hermes did not use the intended OMH workflow.",
    )
    eval_result = build_workflow_eval_result(trace, rubric_id=rubric_id)
    regression_case = build_regression_case_from_trace(
        trace,
        redacted_message=fixture_message,
        expected_workflow=expected_workflow,
        expected_harness=expected_harness,
        expected_next_action=expected_next_action,
    )
    candidate = build_improvement_candidate(
        trace,
        eval_result,
        target_type=target_type,
        title=title or "Review missed OMH workflow route",
    )
    if not dry_run:
        write_learning_trace(paths, trace)
        write_workflow_eval(paths, eval_result)
        write_regression_case(paths, regression_case)
        write_improvement_candidate(paths, candidate)
    replay_ready = bool(fixture_message)
    expected = _object(regression_case.get("expected"))
    return {
        "schema_version": MISSED_ROUTE_RESULT_SCHEMA_VERSION,
        "recorded": not dry_run,
        "dry_run": dry_run,
        "source_kind": "chat_interaction",
        "status": "review_ready" if replay_ready else "needs_regression_fixture",
        "learning_trace_ref": learning_trace_ref(str(trace["trace_id"])),
        "records": {
            "trace_id": trace["trace_id"],
            "eval_id": eval_result["eval_id"],
            "regression_case_id": regression_case["case_id"],
            "candidate_id": candidate["candidate_id"],
        },
        "selected": {
            "workflow": trace["workflow"]["selected_workflow"],
            "harness": trace["workflow"]["selected_harness"],
            "next_action": trace["workflow"]["next_action"],
            "confidence": trace["route"]["confidence"],
            "matched": trace["route"]["matched"],
        },
        "expected": {
            "workflow": expected.get("selected_workflow", ""),
            "harness": expected.get("selected_harness", ""),
            "next_action": expected.get("next_action", ""),
        },
        "regression_case": {
            "case_id": regression_case["case_id"],
            "replay_ready": replay_ready,
            "fixture_sha256": regression_case["fixture"]["fixture_sha256"],
            "privacy": regression_case["fixture"]["privacy"],
        },
        "eval": {
            "eval_id": eval_result["eval_id"],
            "status": eval_result["status"],
            "rubric_id": eval_result["rubric_id"],
            "check_ids": [check["id"] for check in eval_result["checks"]],
        },
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "status": candidate["status"],
            "target_type": candidate["target_type"],
            "target_ref": candidate["target_ref"],
            "primary_action": candidate["review_card"]["primary_action"],
        },
        "next_action": "review_improvement_candidate" if replay_ready else "add_regression_fixture",
        "wrapper_actions": [
            "show_learning_eval",
            "review_improvement",
            "add_regression_fixture",
            "replay_regression_cases",
            "export_learning_bundle",
            "show_status",
        ],
        "not_evidence_yet": [
            "Hermes route changed",
            "skill or routing patch applied",
            "regression replay after a future patch",
            "workflow execution",
            "future behavior fixed",
        ],
        "claim_boundary": (
            "Missed-route capture records local metadata, eval, a regression placeholder, "
            "and a human-review candidate only. It does not prove the route was wrong, "
            "patch skills, execute workflows, or prove future Hermes behavior changed."
        ),
    }


def replay_regression_cases(paths: OmhPaths, *, limit: int | None = None) -> dict[str, Any]:
    cases = _apply_limit(_read_regression_cases(paths), limit)
    results = [_replay_regression_case(case) for case in cases]
    failed = [item for item in results if item["status"] == "failed"]
    skipped = [item for item in results if item["status"] == "skipped"]
    passed = [item for item in results if item["status"] == "passed"]
    return {
        "schema_version": "workflow_regression_replay/v1",
        "status": _regression_replay_status(total=len(results), failed=len(failed), skipped=len(skipped)),
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "results": results,
        "claim_boundary": "Replay checks deterministic routing contracts only; it does not execute workflows, call networks, or patch skills.",
    }


def check_learning_index(paths: OmhPaths) -> dict[str, Any]:
    scanned = _scan_learning_records(paths)
    current = read_json_object(paths.learning_index_path)
    if not current:
        status = (
            "failed"
            if scanned["invalid_records"]
            else ("no_records" if not scanned["entries"] else "missing")
        )
        return _learning_index_check_payload(paths, scanned=scanned, status=status, current_records=[])
    if current.get("schema_version") != WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION:
        return _learning_index_check_payload(
            paths,
            scanned=scanned,
            status="failed",
            current_records=[],
            schema_error="unexpected index schema",
        )
    current_records = [_normal_index_entry(item) for item in _list(current.get("records")) if isinstance(item, dict)]
    return _learning_index_check_payload(paths, scanned=scanned, current_records=current_records)


def rebuild_learning_index(paths: OmhPaths, *, dry_run: bool = False) -> dict[str, Any]:
    scanned = _scan_learning_records(paths)
    index = _learning_index_from_entries(scanned["entries"])
    status = "failed" if scanned["invalid_records"] else ("dry_run" if dry_run else "rebuilt")
    if status == "rebuilt":
        atomic_write_json(paths.learning_index_path, index, private=True)
    return {
        "schema_version": "workflow_learning_index_rebuild/v1",
        "status": status,
        "dry_run": dry_run,
        "wrote": status == "rebuilt",
        "would_write": status == "dry_run",
        "index_path": str(paths.learning_index_path),
        "records_total": len(index["records"]),
        "counts": scanned["counts"],
        "invalid_records": scanned["invalid_records"],
        "index": index,
        "claim_boundary": (
            "Index rebuild scans local workflow-learning metadata records only. "
            "It does not replay workflows, call networks, patch skills, or add observed execution evidence."
        ),
    }


def build_learning_export_bundle(
    paths: OmhPaths,
    *,
    trace_ids: list[str] | None = None,
    limit: int | None = 20,
    export_id: str | None = None,
) -> dict[str, Any]:
    scanned = _scan_learning_records(paths)
    if scanned["invalid_records"]:
        invalid = "; ".join(f"{item['kind']}:{item['path']}" for item in scanned["invalid_records"][:5])
        raise WorkflowLearningError(f"cannot export while invalid learning records exist: {invalid}")

    traces = [_export_trace_projection(trace) for trace in _select_export_traces(paths, trace_ids=trace_ids or [], limit=limit)]
    trace_id_set = {str(trace["trace_id"]) for trace in traces}
    evals = [
        _export_eval_projection(record)
        for record in _related_export_records(paths, "eval", validate_workflow_eval_result, trace_id_set)
    ]
    candidates = [
        _export_candidate_projection(record)
        for record in _related_export_records(paths, "candidate", validate_improvement_candidate, trace_id_set)
    ]
    patch_proposals = [
        _export_patch_proposal_projection(record)
        for record in _related_export_records(paths, "patch_proposal", validate_improvement_patch_proposal, trace_id_set)
    ]
    regression_cases = [
        _redacted_regression_case(case)
        for case in _related_export_records(paths, "regression_case", validate_regression_case, trace_id_set)
    ]
    now = utc_now()
    seed = json.dumps({"trace_ids": sorted(trace_id_set), "created_at": now}, sort_keys=True)
    resolved_export_id = export_id or _id("wlex", seed)
    bundle = {
        "schema_version": WORKFLOW_LEARNING_EXPORT_SCHEMA_VERSION,
        "record_type": "workflow_learning_export",
        "export_id": resolved_export_id,
        "created_at": now,
        "status": "ready" if traces else "no_records",
        "privacy": {
            "mode": PRIVACY_MODE,
            "raw_prompt_stored": False,
            "raw_platform_event_stored": False,
            "fixture_text_stored": False,
            "stored_fields": [
                "message hash",
                "message length",
                "workflow route summary",
                "evidence references",
                "eval checks",
                "candidate review state",
                "regression case expectations without fixture text",
            ],
        },
        "scope": {
            "trace_ids": sorted(trace_id_set),
            "requested_trace_ids": trace_ids or [],
            "limit": "all" if limit is None else limit,
            "related_records": True,
        },
        "provenance": {
            "learning_export_ref": learning_export_ref(resolved_export_id),
            "source_trace_count": len(traces),
            "source_eval_count": len(evals),
            "source_candidate_count": len(candidates),
            "source_patch_proposal_count": len(patch_proposals),
            "source_regression_case_count": len(regression_cases),
            "canonical_learning_index_includes_exports": False,
            "source_payloads_projected": True,
        },
        "summary": _learning_export_summary(
            traces=traces,
            evals=evals,
            candidates=candidates,
            patch_proposals=patch_proposals,
            regression_cases=regression_cases,
        ),
        "study_cards": [
            _learning_study_card(
                trace,
                evals=[record for record in evals if record.get("trace_id") == trace.get("trace_id")],
                candidates=[record for record in candidates if record.get("trace_id") == trace.get("trace_id")],
                patch_proposals=[record for record in patch_proposals if record.get("trace_id") == trace.get("trace_id")],
                regression_cases=[
                    record for record in regression_cases if record.get("trace_id") == trace.get("trace_id")
                ],
            )
            for trace in traces
        ],
        "records": {
            "traces": traces,
            "evals": evals,
            "candidates": candidates,
            "patch_proposals": patch_proposals,
            "regression_cases": regression_cases,
        },
        "operator_notes": [
            "Use this bundle to review process quality, routing decisions, evidence gaps, and improvement candidates.",
            "Use patch proposals as human-reviewed handoff material; they do not apply source edits.",
            "Use regression cases to replay deterministic routing expectations before applying future changes.",
            "Review candidate proposals manually; this bundle does not apply patches.",
        ],
        "claim_boundary": (
            "Workflow learning exports are redacted review bundles. They are not model training, "
            "automatic GEPA improvement, skill mutation, workflow execution, review, CI, merge, or future-behavior proof."
        ),
    }
    validate_workflow_learning_export(bundle)
    return bundle


def write_learning_export(paths: OmhPaths, bundle: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_learning_export(bundle)
    if bundle.get("status") != "ready":
        raise WorkflowLearningError("only ready learning export bundles can be written")
    atomic_write_json(learning_export_path(paths, str(bundle["export_id"])), bundle, private=True)
    return bundle


def build_workflow_learning_audit(paths: OmhPaths, *, limit: int | None = 20) -> dict[str, Any]:
    scanned = _scan_learning_records(paths)
    index_check = check_learning_index(paths)
    traces = _apply_limit(_read_valid_learning_records(paths.learning_traces_dir, validate_workflow_learning_trace), limit)
    evals = _read_valid_learning_records(paths.learning_evals_dir, validate_workflow_eval_result)
    candidates = _read_valid_learning_records(paths.learning_candidates_dir, validate_improvement_candidate)
    patch_proposals = _read_valid_learning_records(paths.learning_patch_proposals_dir, validate_improvement_patch_proposal)
    regression_cases = _read_valid_learning_records(paths.learning_regressions_dir, validate_regression_case)
    exports = _read_valid_learning_records(paths.learning_exports_dir, validate_workflow_learning_export)
    replay = (
        _learning_audit_replay_blocked(scanned)
        if scanned["invalid_records"]
        else replay_regression_cases(paths)
    )

    trace_ids = {str(trace.get("trace_id", "")) for trace in traces if trace.get("trace_id")}
    eval_trace_ids = {str(result.get("trace_id", "")) for result in evals if result.get("trace_id")}
    candidate_trace_ids = {str(candidate.get("trace_id", "")) for candidate in candidates if candidate.get("trace_id")}
    regression_trace_ids = {str(case.get("trace_id", "")) for case in regression_cases if case.get("trace_id")}
    failed_evals = [result for result in evals if result.get("status") == "failed"]
    warning_evals = [result for result in evals if result.get("status") == "warning"]
    problem_eval_trace_ids = {str(result.get("trace_id", "")) for result in failed_evals + warning_evals if result.get("trace_id")}
    pending_candidates = [
        candidate
        for candidate in candidates
        if _nested(candidate, "human_gate", "decision") == "pending"
    ]
    missing_eval = sorted(trace_id for trace_id in trace_ids if trace_id not in eval_trace_ids)
    missing_regression = sorted(trace_id for trace_id in trace_ids if trace_id not in regression_trace_ids)
    missing_candidate = sorted(
        trace_id
        for trace_id in problem_eval_trace_ids
        if trace_id not in candidate_trace_ids
    )
    blocking_issues = _learning_audit_blocking_issues(scanned=scanned, index_check=index_check, failed_evals=failed_evals)
    warnings = _learning_audit_warnings(
        missing_eval=missing_eval,
        missing_regression=missing_regression,
        missing_candidate=missing_candidate,
        warning_evals=warning_evals,
        pending_candidates=pending_candidates,
        replay=replay,
        exports=exports,
    )
    status = _learning_audit_status(
        traces_total=len(traces),
        blocking_issues=blocking_issues,
        warnings=warnings,
        replay=replay,
    )
    payload = {
        "schema_version": WORKFLOW_LEARNING_AUDIT_SCHEMA_VERSION,
        "status": status,
        "ok": status in {"ready", "no_records"},
        "generated_at": utc_now(),
        "scope": {
            "limit": "all" if limit is None else limit,
            "learning_dir": str(paths.learning_dir),
            "index_path": str(paths.learning_index_path),
        },
        "counts": {
            "traces": len(traces),
            "evals": len(evals),
            "candidates": len(candidates),
            "patch_proposals": len(patch_proposals),
            "regression_cases": len(regression_cases),
            "exports": len(exports),
            "invalid_records": len(scanned["invalid_records"]),
        },
        "coverage": {
            "traces_with_eval": len(trace_ids & eval_trace_ids),
            "traces_with_regression_case": len(trace_ids & regression_trace_ids),
            "traces_with_candidate": len(trace_ids & candidate_trace_ids),
            "eval_coverage_percent": _coverage_percent(len(trace_ids & eval_trace_ids), len(trace_ids)),
            "regression_coverage_percent": _coverage_percent(len(trace_ids & regression_trace_ids), len(trace_ids)),
            "candidate_coverage_percent": _coverage_percent(len(trace_ids & candidate_trace_ids), len(trace_ids)),
        },
        "index": {
            "status": index_check.get("status", ""),
            "ok": index_check.get("ok") is True,
            "missing_records": len(_list(index_check.get("missing_records"))),
            "extra_records": len(_list(index_check.get("extra_records"))),
            "schema_mismatches": len(_list(index_check.get("schema_mismatches"))),
            "repair_hint": str(index_check.get("repair_hint", "")),
        },
        "regression_replay": {
            "status": replay.get("status", ""),
            "total": int(replay.get("total", 0) or 0),
            "passed": int(replay.get("passed", 0) or 0),
            "failed": int(replay.get("failed", 0) or 0),
            "skipped": int(replay.get("skipped", 0) or 0),
        },
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "next_actions": _learning_audit_next_actions(
            status=status,
            missing_eval=missing_eval,
            missing_regression=missing_regression,
            missing_candidate=missing_candidate,
            pending_candidates=pending_candidates,
            index_check=index_check,
            exports=exports,
        ),
        "recent_traces": [_trace_summary(trace) for trace in traces],
        "claim_boundary": (
            "Workflow learning audit reads local metadata-only learning records. "
            "It does not train a model, patch skills, execute workflows, call networks, "
            "or upgrade prepared artifacts into observed evidence."
        ),
    }
    payload["learning_audit_card"] = build_learning_audit_card(payload)
    return payload


def build_workflow_learning_review_queue(paths: OmhPaths, *, limit: int | None = 20) -> dict[str, Any]:
    from .self_improvement_routes import store_route_review_queue_entries

    scanned = _scan_learning_records(paths)
    candidates = _read_valid_learning_records(paths.learning_candidates_dir, validate_improvement_candidate)
    patch_proposals = _read_valid_learning_records(paths.learning_patch_proposals_dir, validate_improvement_patch_proposal)
    proposals_by_candidate = _patch_proposals_by_candidate(patch_proposals)
    entries: list[dict[str, Any]] = []

    for invalid in _list(scanned.get("invalid_records")):
        if not isinstance(invalid, dict):
            continue
        entries.append(
            _learning_review_queue_entry(
                kind="invalid_record",
                status="blocked",
                severity="blocking",
                priority=0,
                title="Repair invalid learning record",
                detail=str(invalid.get("error", "")),
                primary_action="check_learning_index",
                next_command="omh learning index check",
                refs=[str(invalid.get("path", ""))],
                created_at=f"invalid:{invalid.get('path', '')}",
            )
        )

    candidate_ids = {str(candidate.get("candidate_id", "")) for candidate in candidates}
    for candidate in sorted(candidates, key=lambda item: (str(item.get("created_at", "")), str(item.get("candidate_id", "")))):
        candidate_id = str(candidate.get("candidate_id", ""))
        decision = str(_nested(candidate, "human_gate", "decision") or "pending")
        latest_proposal = _latest_patch_proposal(proposals_by_candidate.get(candidate_id, []))
        entry = _candidate_review_queue_entry(candidate, decision=decision, latest_proposal=latest_proposal)
        if entry:
            entries.append(entry)

    for proposal in sorted(patch_proposals, key=lambda item: (str(item.get("created_at", "")), str(item.get("proposal_id", "")))):
        candidate_id = str(proposal.get("candidate_id", ""))
        if candidate_id not in candidate_ids:
            entries.append(
                _learning_review_queue_entry(
                    kind="orphan_patch_proposal",
                    status="blocked",
                    severity="blocking",
                    priority=1,
                    title="Patch proposal has no valid candidate",
                    detail="Repair or remove the orphan proposal before treating the learning corpus as review-ready.",
                    primary_action="check_learning_index",
                    next_command="omh learning index check",
                    refs=[_record_ref("patch_proposal", str(proposal.get("proposal_id", "")))],
                    created_at=str(proposal.get("created_at", "")),
                    candidate_id=candidate_id,
                    proposal_id=str(proposal.get("proposal_id", "")),
                    trace_id=str(proposal.get("trace_id", "")),
                )
            )

    entries.extend(store_route_review_queue_entries(paths))

    entries = sorted(entries, key=lambda item: (int(item.get("priority", 99)), str(item.get("created_at", "")), str(item.get("entry_id", ""))))
    limited_entries = entries if limit is None else entries[: max(limit, 0)]
    payload = {
        "schema_version": WORKFLOW_LEARNING_REVIEW_QUEUE_SCHEMA_VERSION,
        "status": _learning_review_queue_status(entries),
        "generated_at": utc_now(),
        "scope": {
            "limit": "all" if limit is None else limit,
            "learning_dir": str(paths.learning_dir),
        },
        "summary": {
            "open_items": len(entries),
            "returned_items": len(limited_entries),
            "pending_candidates": sum(1 for item in entries if item.get("status") == "needs_candidate_review"),
            "pending_store_routes": sum(1 for item in entries if item.get("status") == "needs_store_route_review"),
            "approved_without_proposal": sum(1 for item in entries if item.get("status") == "needs_patch_proposal"),
            "ready_patch_proposals": sum(1 for item in entries if item.get("status") == "ready_for_human_patch"),
            "blocked_items": sum(1 for item in entries if item.get("severity") == "blocking"),
            "resolved_candidates": sum(
                1
                for candidate in candidates
                if str(_nested(candidate, "human_gate", "decision")) in {"reject"}
            ),
        },
        "entries": limited_entries,
        "primary_action": str(_object(limited_entries[0]).get("primary_action", "record_workflow_learning_trace")) if limited_entries else "record_workflow_learning_trace",
        "wrapper_actions": [
            "record_workflow_learning_trace",
            "show_learning_review_queue",
            "review_self_improvement_store_route",
            "approve_store_route",
            "change_store_route_destination",
            "discard_store_route",
            "review_improvement",
            "approve_improvement",
            "revise_improvement",
            "reject_improvement",
            "prepare_patch_proposal",
            "show_patch_proposal",
            "copy_patch_handoff",
            "add_regression_case",
            "replay_regression_cases",
            "audit_learning_readiness",
            "export_learning_bundle",
            "check_learning_index",
            "show_status",
        ],
        "not_evidence_yet": [
            "source patch applied",
            "skill or routing behavior changed",
            "regression replay after a future patch",
            "future workflow behavior fixed",
            "model training",
            "workflow execution",
            "review approval beyond recorded human gate",
            "destination artifact write after store-route approval",
            "CI",
            "merge",
        ],
        "claim_boundary": (
            "Workflow learning review queues summarize local candidates, patch proposals, and store-route review records. "
            "They do not apply source edits, execute workflows, train models, pass CI, or prove future behavior changed."
        ),
    }
    validate_workflow_learning_review_queue(payload)
    return payload


def build_learning_audit_card(audit: dict[str, Any]) -> dict[str, Any]:
    status = str(audit.get("status", "needs_attention"))
    blocking = [] if status == "no_records" else _list(audit.get("blocking_issues"))
    warnings = [] if status == "no_records" else _list(audit.get("warnings"))
    card = {
        "schema_version": LEARNING_AUDIT_CARD_SCHEMA_VERSION,
        "status": status,
        "severity": _learning_audit_card_severity(status),
        "headline": _learning_audit_card_headline(status),
        "summary": _learning_audit_card_summary(audit),
        "primary_action": _learning_audit_primary_action(audit),
        "steps": _learning_audit_card_steps(audit),
        "counts": _object(audit.get("counts")),
        "coverage": _object(audit.get("coverage")),
        "regression_replay": _object(audit.get("regression_replay")),
        "blocking_issue_count": len(blocking),
        "warning_count": len(warnings),
        "next_actions": _list(audit.get("next_actions")),
        "wrapper_actions": [
            "record_workflow_learning_trace",
            "show_learning_eval",
            "propose_skill_improvement",
            "review_improvement",
            "approve_improvement",
            "revise_improvement",
            "reject_improvement",
            "add_regression_case",
            "audit_learning_readiness",
            "export_learning_bundle",
            "replay_regression_cases",
            "check_learning_index",
            "rebuild_learning_index",
            "show_status",
        ],
        "not_evidence_yet": [
            "model training",
            "automatic skill patch",
            "workflow execution",
            "future behavior fixed",
            "review approval",
            "CI",
            "merge",
        ],
        "claim_boundary": str(audit.get("claim_boundary", "")),
    }
    validate_learning_audit_card(card)
    return card


def attach_learning_trace_ref_to_interaction(interaction: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_learning_trace(trace)
    enriched = json.loads(json.dumps(interaction))
    ref = learning_trace_ref(str(trace["trace_id"]))
    enriched["learning_trace_ref"] = ref
    chat_response = _object(enriched.get("chat_response"))
    state = _object(chat_response.get("state"))
    state["learning_trace_ref"] = ref
    chat_response["state"] = state
    enriched["chat_response"] = chat_response
    return enriched


def validate_workflow_learning_trace(trace: dict[str, Any]) -> None:
    _require_schema(trace, WORKFLOW_LEARNING_TRACE_SCHEMA_VERSION)
    _require_string(trace, "trace_id")
    _require_string(trace, "created_at")
    _require_string(trace, "updated_at")
    for key in ("privacy", "source", "route", "workflow", "reasoning_summary", "status"):
        if not isinstance(trace.get(key), dict):
            raise WorkflowLearningError(f"trace.{key} must be an object")
    privacy = _object(trace["privacy"])
    if privacy.get("mode") != PRIVACY_MODE:
        raise WorkflowLearningError("trace privacy mode must be metadata_only")
    if privacy.get("raw_prompt_stored") is not False or privacy.get("raw_platform_event_stored") is not False:
        raise WorkflowLearningError("learning traces must not store raw prompts or platform events")
    source = _object(trace["source"])
    if str(source.get("kind", "")) not in {"chat_interaction", "runtime_run"}:
        raise WorkflowLearningError("trace source.kind must be chat_interaction or runtime_run")
    workflow = _object(trace["workflow"])
    if not workflow.get("selected_workflow"):
        raise WorkflowLearningError("trace workflow.selected_workflow is required")
    status = _object(trace["status"])
    if status.get("outcome") not in _LEARNING_OUTCOMES:
        raise WorkflowLearningError("trace status.outcome is invalid")
    _reject_forbidden_payload_keys(trace)


def validate_learning_audit_card(card: dict[str, Any]) -> None:
    _require_schema(card, LEARNING_AUDIT_CARD_SCHEMA_VERSION)
    if card.get("status") not in {"ready", "no_records", "needs_attention", "blocked"}:
        raise WorkflowLearningError("learning audit card status is invalid")
    if card.get("severity") not in {"ok", "empty", "warning", "blocking"}:
        raise WorkflowLearningError("learning audit card severity is invalid")
    for key in ("headline", "summary", "primary_action", "claim_boundary"):
        _require_string(card, key)
    for key in ("counts", "coverage", "regression_replay"):
        if not isinstance(card.get(key), dict):
            raise WorkflowLearningError(f"learning audit card {key} must be an object")
    for key in ("blocking_issue_count", "warning_count"):
        if not isinstance(card.get(key), int) or card.get(key) < 0:
            raise WorkflowLearningError(f"learning audit card {key} must be a non-negative integer")
    steps = _list(card.get("steps"))
    if not steps:
        raise WorkflowLearningError("learning audit card steps must be a non-empty list")
    for step in steps:
        item = _object(step)
        for key in ("id", "label", "state", "detail"):
            _require_string(item, key)
        if item.get("state") not in {"ready", "missing", "blocked"}:
            raise WorkflowLearningError("learning audit card step state is invalid")
    wrapper_actions = _list(card.get("wrapper_actions"))
    if not wrapper_actions or any(not isinstance(action, str) or not action for action in wrapper_actions):
        raise WorkflowLearningError("learning audit card wrapper_actions must be non-empty strings")
    if str(card.get("primary_action", "")) not in set(wrapper_actions):
        raise WorkflowLearningError("learning audit card primary_action must be listed in wrapper_actions")
    not_evidence_yet = _list(card.get("not_evidence_yet"))
    if not not_evidence_yet or any(not isinstance(item, str) or not item for item in not_evidence_yet):
        raise WorkflowLearningError("learning audit card not_evidence_yet must be non-empty strings")
    _reject_forbidden_payload_keys(card)


def validate_workflow_learning_review_queue(queue: dict[str, Any]) -> None:
    _require_schema(queue, WORKFLOW_LEARNING_REVIEW_QUEUE_SCHEMA_VERSION)
    if queue.get("status") not in {"ready", "empty", "needs_review", "blocked"}:
        raise WorkflowLearningError("workflow learning review queue status is invalid")
    for key in ("generated_at", "primary_action", "claim_boundary"):
        _require_string(queue, key)
    if not isinstance(queue.get("scope"), dict) or not isinstance(queue.get("summary"), dict):
        raise WorkflowLearningError("workflow learning review queue scope and summary must be objects")
    summary = _object(queue.get("summary"))
    for key in ("open_items", "returned_items", "pending_candidates", "ready_patch_proposals", "blocked_items"):
        if not isinstance(summary.get(key), int) or summary.get(key) < 0:
            raise WorkflowLearningError(f"workflow learning review queue summary.{key} must be non-negative integer")
    entries = _list(queue.get("entries"))
    if summary.get("returned_items") != len(entries):
        raise WorkflowLearningError("workflow learning review queue returned_items must match entries")
    allowed_kinds = {
        "invalid_record",
        "candidate_review",
        "candidate_revision",
        "candidate_patch_gap",
        "patch_proposal",
        "orphan_patch_proposal",
        "self_improvement_store_route",
    }
    allowed_statuses = {
        "blocked",
        "needs_candidate_review",
        "needs_store_route_review",
        "needs_revision",
        "needs_patch_proposal",
        "needs_regression_case",
        "needs_regression_replay",
        "ready_for_human_patch",
        "rejected",
    }
    allowed_severities = {"blocking", "review", "warning", "ready"}
    for entry in entries:
        item = _object(entry)
        for key in ("entry_id", "kind", "status", "severity", "title", "detail", "primary_action", "next_command"):
            _require_string(item, key)
        if item.get("kind") not in allowed_kinds:
            raise WorkflowLearningError("workflow learning review queue entry kind is invalid")
        if item.get("status") not in allowed_statuses:
            raise WorkflowLearningError("workflow learning review queue entry status is invalid")
        if item.get("severity") not in allowed_severities:
            raise WorkflowLearningError("workflow learning review queue entry severity is invalid")
        if not isinstance(item.get("priority"), int) or item.get("priority") < 0:
            raise WorkflowLearningError("workflow learning review queue entry priority must be non-negative integer")
        refs = _list(item.get("refs"))
        if any(not isinstance(ref, str) or not ref for ref in refs):
            raise WorkflowLearningError("workflow learning review queue entry refs must be strings")
    wrapper_actions = _list(queue.get("wrapper_actions"))
    if not wrapper_actions or any(not isinstance(action, str) or not action for action in wrapper_actions):
        raise WorkflowLearningError("workflow learning review queue wrapper_actions must be non-empty strings")
    if str(queue.get("primary_action", "")) not in set(_strings(queue.get("wrapper_actions"))):
        raise WorkflowLearningError("workflow learning review queue primary_action must be listed in wrapper_actions")
    not_evidence_yet = _list(queue.get("not_evidence_yet"))
    if not not_evidence_yet or any(not isinstance(item, str) or not item for item in not_evidence_yet):
        raise WorkflowLearningError("workflow learning review queue not_evidence_yet must be non-empty strings")
    _reject_forbidden_payload_keys(queue)


def validate_workflow_eval_result(result: dict[str, Any]) -> None:
    _require_schema(result, WORKFLOW_EVAL_RESULT_SCHEMA_VERSION)
    _require_string(result, "eval_id")
    _require_string(result, "trace_id")
    if result.get("status") not in {"passed", "warning", "failed"}:
        raise WorkflowLearningError("eval status must be passed, warning, or failed")
    checks = result.get("checks")
    if not isinstance(checks, list) or not checks:
        raise WorkflowLearningError("eval checks must be a non-empty list")
    for check in checks:
        if not isinstance(check, dict):
            raise WorkflowLearningError("eval check must be an object")
        if check.get("status") not in {"passed", "warning", "failed", "not_applicable"}:
            raise WorkflowLearningError("eval check status is invalid")


def validate_self_improvement_store_routing(payload: dict[str, Any]) -> None:
    _require_schema(payload, SELF_IMPROVEMENT_STORE_ROUTING_SCHEMA_VERSION)
    if payload.get("status") != "prepared":
        raise WorkflowLearningError("self-improvement store routing status must be prepared")
    for key in ("generated_at", "next_action", "claim_boundary"):
        _require_string(payload, key)
    signal = _object(payload.get("signal"))
    if signal.get("raw_text_stored") is not False:
        raise WorkflowLearningError("self-improvement store routing must not store raw signal text")
    for key in ("source_kind", "sha256"):
        _require_string(signal, key)
    if not isinstance(signal.get("length"), int) or signal.get("length") < 0:
        raise WorkflowLearningError("self-improvement store routing signal.length must be a non-negative integer")
    classification = _object(payload.get("classification"))
    destination = str(classification.get("destination", ""))
    if destination not in SELF_IMPROVEMENT_DESTINATION_DETAILS:
        raise WorkflowLearningError("self-improvement store routing destination is invalid")
    expected = SELF_IMPROVEMENT_DESTINATION_DETAILS[destination]
    for key in ("confidence", "target_workflow", "target_record_type", "next_action"):
        _require_string(classification, key)
    for key in ("target_workflow", "target_record_type", "next_action"):
        if classification.get(key) != expected[key]:
            raise WorkflowLearningError(f"self-improvement store routing classification.{key} is inconsistent")
    reasons = _strings(classification.get("routing_reasons"))
    if not reasons:
        raise WorkflowLearningError("self-improvement store routing requires routing reasons")
    alternatives = _strings(classification.get("alternative_destinations"))
    if any(destination == item or item not in SELF_IMPROVEMENT_DESTINATION_DETAILS for item in alternatives):
        raise WorkflowLearningError("self-improvement store routing alternatives are invalid")
    gate = _object(payload.get("review_gate"))
    if gate.get("required") is not True or gate.get("decision") != "pending":
        raise WorkflowLearningError("self-improvement store routing requires a pending review gate")
    if not _strings(gate.get("allowed_decisions")):
        raise WorkflowLearningError("self-improvement store routing review gate decisions must be non-empty")
    wrapper_actions = _strings(payload.get("wrapper_actions"))
    if not wrapper_actions:
        raise WorkflowLearningError("self-improvement store routing wrapper_actions must be non-empty")
    if payload.get("next_action") not in set(wrapper_actions):
        raise WorkflowLearningError("self-improvement store routing next_action must be listed in wrapper_actions")
    if payload.get("writes_observed") is not False:
        raise WorkflowLearningError("self-improvement store routing cannot claim observed writes")
    if not _strings(payload.get("not_evidence_yet")):
        raise WorkflowLearningError("self-improvement store routing not_evidence_yet must be non-empty")
    if any(not isinstance(item, str) or not item for item in _list(payload.get("observed_ref_hashes"))):
        raise WorkflowLearningError("self-improvement store routing observed_ref_hashes must be strings")
    _reject_forbidden_payload_keys(payload)
    _reject_self_improvement_raw_payload_keys(payload)


def _validate_improvement_candidate_core(candidate: dict[str, Any]) -> None:
    _require_schema(candidate, IMPROVEMENT_CANDIDATE_SCHEMA_VERSION)
    _require_string(candidate, "candidate_id")
    _require_string(candidate, "trace_id")
    if candidate.get("status") not in {"proposed", "accepted", "rejected", "superseded"}:
        raise WorkflowLearningError("candidate status is invalid")
    gate = _object(candidate.get("human_gate"))
    if gate.get("required") is not True or gate.get("decision") not in {"pending", "approve", "revise", "reject"}:
        raise WorkflowLearningError("candidate human_gate must require a pending/approve/revise/reject decision")
    diff = _object(candidate.get("diff_preview"))
    if diff.get("available") is not False:
        raise WorkflowLearningError("v1 candidates must not include applied diff previews")


def validate_improvement_candidate(candidate: dict[str, Any]) -> None:
    _validate_improvement_candidate_core(candidate)
    card = candidate.get("review_card")
    if card is not None:
        validate_improvement_candidate_review_card(_object(card), candidate=candidate)
    _reject_export_payload_keys(candidate)


def validate_improvement_candidate_review_card(card: dict[str, Any], *, candidate: dict[str, Any] | None = None) -> None:
    _require_schema(card, IMPROVEMENT_CANDIDATE_REVIEW_CARD_SCHEMA_VERSION)
    for key in ("candidate_id", "trace_id", "eval_id", "headline", "summary", "primary_action", "claim_boundary"):
        _require_string(card, key)
    if card.get("status") not in {"review_required", "approved", "revision_requested", "rejected"}:
        raise WorkflowLearningError("improvement candidate review card status is invalid")
    if card.get("severity") not in {"review", "ok", "warning", "blocked"}:
        raise WorkflowLearningError("improvement candidate review card severity is invalid")
    target = _object(card.get("target"))
    _require_string(target, "type")
    _require_string(target, "ref")
    gate = _object(card.get("review_gate"))
    if gate.get("required") is not True or gate.get("human_approval_required") is not True:
        raise WorkflowLearningError("improvement review gate must require human approval")
    if gate.get("decision") not in {"pending", "approve", "revise", "reject"}:
        raise WorkflowLearningError("improvement review gate decision is invalid")
    if not _strings(gate.get("allowed_decisions")):
        raise WorkflowLearningError("improvement review gate allowed_decisions must be non-empty")
    diff = _object(card.get("diff_preview"))
    if diff.get("available") is not False:
        raise WorkflowLearningError("improvement review card must not include applied diff previews")
    for key in ("problem_statement", "proposed_change_summary"):
        _require_string(card, key)
    for key in ("review_questions", "wrapper_actions", "not_evidence_yet"):
        values = _list(card.get(key))
        if not values or any(not isinstance(item, str) or not item for item in values):
            raise WorkflowLearningError(f"improvement review card {key} must be non-empty strings")
    if str(card.get("primary_action", "")) not in set(_strings(card.get("wrapper_actions"))):
        raise WorkflowLearningError("improvement review card primary_action must be listed in wrapper_actions")
    steps = _list(card.get("steps"))
    if not steps:
        raise WorkflowLearningError("improvement review card steps must be non-empty")
    for step in steps:
        item = _object(step)
        for key in ("id", "label", "state", "detail"):
            _require_string(item, key)
        if item.get("state") not in {"pending", "ready", "blocked", "complete"}:
            raise WorkflowLearningError("improvement review card step state is invalid")
    if candidate is not None:
        for key in ("candidate_id", "trace_id", "eval_id"):
            if str(card.get(key, "")) != str(candidate.get(key, "")):
                raise WorkflowLearningError(f"improvement review card {key} must match candidate")
        if str(target.get("type", "")) != str(candidate.get("target_type", "")):
            raise WorkflowLearningError("improvement review card target.type must match candidate")
        if str(target.get("ref", "")) != str(candidate.get("target_ref", "")):
            raise WorkflowLearningError("improvement review card target.ref must match candidate")
        decision = str(_object(candidate.get("human_gate")).get("decision", "pending"))
        status = _improvement_review_status(decision)
        if gate.get("decision") != decision:
            raise WorkflowLearningError("improvement review card decision must match candidate")
        if card.get("status") != status:
            raise WorkflowLearningError("improvement review card status must match candidate decision")
        if card.get("severity") != _improvement_review_severity(status):
            raise WorkflowLearningError("improvement review card severity must match candidate decision")
        if card.get("primary_action") != _improvement_review_primary_action(status):
            raise WorkflowLearningError("improvement review card primary_action must match candidate decision")
    _reject_export_payload_keys(card)


def validate_improvement_patch_proposal(proposal: dict[str, Any], *, candidate: dict[str, Any] | None = None) -> None:
    _require_schema(proposal, IMPROVEMENT_PATCH_PROPOSAL_SCHEMA_VERSION)
    for key in (
        "proposal_id",
        "candidate_id",
        "trace_id",
        "eval_id",
        "created_at",
        "status",
        "problem_statement",
        "proposed_change_summary",
        "primary_action",
        "claim_boundary",
    ):
        _require_string(proposal, key)
    if proposal.get("status") not in {
        "needs_candidate_review",
        "needs_regression_case",
        "needs_regression_replay",
        "ready_for_human_patch",
        "rejected",
    }:
        raise WorkflowLearningError("improvement patch proposal status is invalid")
    target = _object(proposal.get("target"))
    _require_string(target, "type")
    _require_string(target, "ref")
    files = _list(target.get("source_files"))
    if not files or any(not isinstance(path, str) or not path for path in files):
        raise WorkflowLearningError("improvement patch proposal target.source_files must be non-empty strings")
    refs = _object(proposal.get("source_refs"))
    for key in ("candidate_ref", "trace_ref", "eval_ref"):
        _require_string(refs, key)
    if any(not isinstance(ref, str) or not ref for ref in _list(refs.get("regression_case_refs"))):
        raise WorkflowLearningError("improvement patch proposal regression refs must be strings")
    gate = _object(proposal.get("review_gate"))
    if gate.get("human_approval_required") is not True:
        raise WorkflowLearningError("improvement patch proposal must require human approval")
    if gate.get("candidate_decision") not in {"pending", "approve", "revise", "reject"}:
        raise WorkflowLearningError("improvement patch proposal candidate decision is invalid")
    if bool(gate.get("ready_for_patch_work")) != (proposal.get("status") == "ready_for_human_patch"):
        raise WorkflowLearningError("improvement patch proposal ready flag must match status")
    scope = _object(proposal.get("patch_scope"))
    if scope.get("apply_path_available") is not False or scope.get("mode") != "proposal_only":
        raise WorkflowLearningError("improvement patch proposal must be proposal_only and non-applying")
    regression = _object(proposal.get("regression_gate"))
    if regression.get("required") is not True:
        raise WorkflowLearningError("improvement patch proposal regression gate is required")
    if not isinstance(regression.get("case_count"), int) or regression.get("case_count") < 0:
        raise WorkflowLearningError("improvement patch proposal regression case_count must be non-negative")
    if regression.get("replay_status") not in {"passed", "failed", "skipped", "incomplete", "no_cases"}:
        raise WorkflowLearningError("improvement patch proposal regression replay status is invalid")
    if bool(regression.get("passed")) != (regression.get("replay_status") == "passed"):
        raise WorkflowLearningError("improvement patch proposal regression passed flag must match replay status")
    snapshot = _list(regression.get("snapshot"))
    if any(not isinstance(item, dict) for item in snapshot):
        raise WorkflowLearningError("improvement patch proposal regression snapshot must contain objects")
    if len(snapshot) != regression.get("case_count"):
        raise WorkflowLearningError("improvement patch proposal regression snapshot must match case_count")
    if len(_list(refs.get("regression_case_refs"))) != regression.get("case_count"):
        raise WorkflowLearningError("improvement patch proposal regression refs must match case_count")
    expected_status = _patch_proposal_status(
        decision=str(gate.get("candidate_decision", "")),
        regression_count=int(regression.get("case_count", 0) or 0),
        replay_status=str(regression.get("replay_status", "")),
    )
    if proposal.get("status") != expected_status:
        raise WorkflowLearningError("improvement patch proposal status must match review and regression gates")
    for gate_record in _list(proposal.get("required_gates")):
        item = _object(gate_record)
        for key in ("id", "state", "detail"):
            _require_string(item, key)
        if item.get("state") not in {"pending", "blocked", "complete"}:
            raise WorkflowLearningError("improvement patch proposal required gate state is invalid")
        if not isinstance(item.get("required"), bool):
            raise WorkflowLearningError("improvement patch proposal required gate required flag must be boolean")
    for key in ("verification_commands", "wrapper_actions", "not_evidence_yet"):
        values = _list(proposal.get(key))
        if not values or any(not isinstance(item, str) or not item.strip() for item in values):
            raise WorkflowLearningError(f"improvement patch proposal {key} must be non-empty strings")
    if not _list(proposal.get("required_gates")):
        raise WorkflowLearningError("improvement patch proposal required_gates must be non-empty")
    if not _list(proposal.get("steps")):
        raise WorkflowLearningError("improvement patch proposal steps must be non-empty")
    if str(proposal.get("primary_action", "")) not in set(_strings(proposal.get("wrapper_actions"))):
        raise WorkflowLearningError("improvement patch proposal primary_action must be listed in wrapper_actions")
    for step in _list(proposal.get("steps")):
        item = _object(step)
        for key in ("id", "label", "state", "detail"):
            _require_string(item, key)
        if item.get("state") not in {"pending", "ready", "blocked", "complete"}:
            raise WorkflowLearningError("improvement patch proposal step state is invalid")
    if candidate is not None:
        for key in ("candidate_id", "trace_id", "eval_id"):
            if str(proposal.get(key, "")) != str(candidate.get(key, "")):
                raise WorkflowLearningError(f"improvement patch proposal {key} must match candidate")
        if str(target.get("type", "")) != str(candidate.get("target_type", "")):
            raise WorkflowLearningError("improvement patch proposal target.type must match candidate")
        if str(target.get("ref", "")) != str(candidate.get("target_ref", "")):
            raise WorkflowLearningError("improvement patch proposal target.ref must match candidate")
        decision = str(_nested(candidate, "human_gate", "decision") or "pending")
        if gate.get("candidate_decision") != decision:
            raise WorkflowLearningError("improvement patch proposal review gate must match candidate decision")
        expected_status = _patch_proposal_status(
            decision=decision,
            regression_count=int(regression.get("case_count", 0) or 0),
            replay_status=str(regression.get("replay_status", "")),
        )
        if proposal.get("status") != expected_status:
            raise WorkflowLearningError("improvement patch proposal status must match candidate and regression gate")
    _reject_export_payload_keys(proposal)


def validate_regression_case(case: dict[str, Any]) -> None:
    _require_schema(case, REGRESSION_CASE_SCHEMA_VERSION)
    _require_string(case, "case_id")
    _require_string(case, "trace_id")
    if not isinstance(case.get("fixture"), dict) or not isinstance(case.get("expected"), dict):
        raise WorkflowLearningError("regression case fixture and expected must be objects")
    fixture = _object(case.get("fixture"))
    privacy = _object(fixture.get("privacy"))
    fixture_text = str(fixture.get("fixture_text") or fixture.get("redacted_message") or "")
    if fixture_text:
        if privacy.get("raw_prompt_stored") is not False:
            raise WorkflowLearningError("regression fixture privacy.raw_prompt_stored must be false")
        if privacy.get("operator_must_redact_private_content") is not True:
            raise WorkflowLearningError("regression fixture privacy must require operator redaction")


def validate_workflow_learning_export(bundle: dict[str, Any]) -> None:
    _require_schema(bundle, WORKFLOW_LEARNING_EXPORT_SCHEMA_VERSION)
    _require_string(bundle, "export_id")
    _require_string(bundle, "created_at")
    if bundle.get("status") not in {"ready", "no_records"}:
        raise WorkflowLearningError("learning export status must be ready or no_records")
    privacy = _object(bundle.get("privacy"))
    if privacy.get("mode") != PRIVACY_MODE:
        raise WorkflowLearningError("learning export privacy mode must be metadata_only")
    if (
        privacy.get("raw_prompt_stored") is not False
        or privacy.get("raw_platform_event_stored") is not False
        or privacy.get("fixture_text_stored") is not False
    ):
        raise WorkflowLearningError("learning exports must not store raw prompts, platform events, or fixture text")
    records = _object(bundle.get("records"))
    for trace in _list(records.get("traces")):
        if not isinstance(trace, dict):
            raise WorkflowLearningError("learning export trace record must be an object")
        validate_workflow_learning_trace(trace)
    for result in _list(records.get("evals")):
        if not isinstance(result, dict):
            raise WorkflowLearningError("learning export eval record must be an object")
        _validate_export_eval_projection(result)
    for candidate in _list(records.get("candidates")):
        if not isinstance(candidate, dict):
            raise WorkflowLearningError("learning export candidate record must be an object")
        _validate_export_candidate_projection(candidate)
    for proposal in _list(records.get("patch_proposals")):
        if not isinstance(proposal, dict):
            raise WorkflowLearningError("learning export patch proposal record must be an object")
        _validate_export_patch_proposal_projection(proposal)
    for case in _list(records.get("regression_cases")):
        if not isinstance(case, dict):
            raise WorkflowLearningError("learning export regression case record must be an object")
        validate_regression_case(case)
    _reject_export_payload_keys(bundle)


def _validate_export_eval_projection(result: dict[str, Any]) -> None:
    _require_schema(result, WORKFLOW_EVAL_RESULT_SCHEMA_VERSION)
    _require_string(result, "eval_id")
    _require_string(result, "trace_id")
    if result.get("status") not in {"passed", "warning", "failed"}:
        raise WorkflowLearningError("learning export eval status must be passed, warning, or failed")
    checks = result.get("checks")
    if not isinstance(checks, list) or not checks:
        raise WorkflowLearningError("learning export eval checks must be a non-empty list")
    for check in checks:
        if not isinstance(check, dict):
            raise WorkflowLearningError("learning export eval check must be an object")
        if check.get("status") not in {"passed", "warning", "failed", "not_applicable"}:
            raise WorkflowLearningError("learning export eval check status is invalid")


def _validate_export_candidate_projection(candidate: dict[str, Any]) -> None:
    _require_schema(candidate, IMPROVEMENT_CANDIDATE_SCHEMA_VERSION)
    _require_string(candidate, "candidate_id")
    _require_string(candidate, "trace_id")
    _require_string(candidate, "eval_id")
    if candidate.get("status") not in {"proposed", "accepted", "rejected", "superseded"}:
        raise WorkflowLearningError("learning export candidate status is invalid")
    gate = _object(candidate.get("human_gate"))
    if gate.get("required") is not True or gate.get("decision") not in {"pending", "approve", "revise", "reject"}:
        raise WorkflowLearningError("learning export candidate human_gate is invalid")
    diff = _object(candidate.get("diff_preview"))
    if not isinstance(diff.get("available"), bool):
        raise WorkflowLearningError("learning export candidate diff_preview.available must be boolean")


def _validate_export_patch_proposal_projection(proposal: dict[str, Any]) -> None:
    _require_schema(proposal, IMPROVEMENT_PATCH_PROPOSAL_SCHEMA_VERSION)
    for key in ("proposal_id", "candidate_id", "trace_id", "eval_id", "status", "primary_action", "claim_boundary"):
        _require_string(proposal, key)
    if proposal.get("status") not in {
        "needs_candidate_review",
        "needs_regression_case",
        "needs_regression_replay",
        "ready_for_human_patch",
        "rejected",
    }:
        raise WorkflowLearningError("learning export patch proposal status is invalid")
    if not isinstance(proposal.get("target"), dict):
        raise WorkflowLearningError("learning export patch proposal target must be an object")
    target = _object(proposal.get("target"))
    _require_string(target, "type")
    _require_string(target, "ref")
    if not isinstance(proposal.get("source_file_count"), int):
        raise WorkflowLearningError("learning export patch proposal source_file_count must be an integer")
    regression = _object(proposal.get("regression_gate"))
    if not isinstance(regression.get("case_count"), int):
        raise WorkflowLearningError("learning export patch proposal regression case_count must be an integer")
    if regression.get("replay_status") not in {"passed", "failed", "skipped", "incomplete", "no_cases"}:
        raise WorkflowLearningError("learning export patch proposal replay status is invalid")
    if not isinstance(regression.get("snapshot_count"), int):
        raise WorkflowLearningError("learning export patch proposal regression snapshot_count must be an integer")


def trace_path(paths: OmhPaths, trace_id: str) -> Path:
    return paths.learning_traces_dir / f"{_safe_id(trace_id)}.json"


def eval_path(paths: OmhPaths, eval_id: str) -> Path:
    return paths.learning_evals_dir / f"{_safe_id(eval_id)}.json"


def candidate_path(paths: OmhPaths, candidate_id: str) -> Path:
    return paths.learning_candidates_dir / f"{_safe_id(candidate_id)}.json"


def patch_proposal_path(paths: OmhPaths, proposal_id: str) -> Path:
    return paths.learning_patch_proposals_dir / f"{_safe_id(proposal_id)}.json"


def regression_case_path(paths: OmhPaths, case_id: str) -> Path:
    return paths.learning_regressions_dir / f"{_safe_id(case_id)}.json"


def learning_export_path(paths: OmhPaths, export_id: str) -> Path:
    return paths.learning_exports_dir / f"{_safe_id(export_id)}.json"


def _prepared_refs(interaction: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for key in (
        "chat_response",
        "plan",
        "delegation",
        "loop_start_card",
        "status_card",
        "target_notice",
        "target_topology",
    ):
        if key in interaction:
            schema = _object(interaction.get(key)).get("schema_version", "")
            if key == "plan":
                schema = _nested(interaction, "plan", "schema_version") or _nested(interaction, "plan", "plan", "schema_version")
            refs.append({"kind": key, "ref": key, "schema_version": str(schema)})
    return refs


def _runtime_prepared_refs(run_id: str, shown: dict[str, Any]) -> list[dict[str, str]]:
    refs = [{"kind": "run", "ref": f"runtime:{run_id}:run", "schema_version": str(_nested(shown, "run", "schema_version") or "")}]
    for key in ("routing", "coding_delegation", "delegation", "wrapper", "review", "ci", "merge"):
        if isinstance(shown.get(key), dict):
            refs.append({"kind": key, "ref": f"runtime:{run_id}:{key}", "schema_version": str(_nested(shown, key, "schema_version") or "")})
    return refs


def _runtime_not_evidence_yet(shown: dict[str, Any]) -> list[str]:
    missing = []
    if not shown.get("delegation"):
        missing.append("executor result")
    if not shown.get("review"):
        missing.append("review")
    if not shown.get("ci"):
        missing.append("CI")
    if not shown.get("merge"):
        missing.append("merge")
    return missing


def _privacy_check(trace: dict[str, Any]) -> dict[str, Any]:
    privacy = _object(trace.get("privacy"))
    if privacy.get("mode") == PRIVACY_MODE and privacy.get("raw_prompt_stored") is False:
        return _check("privacy_metadata_only", "passed", "Trace stores metadata and refs only.", [learning_trace_ref(str(trace["trace_id"]))])
    return _check("privacy_metadata_only", "failed", "Trace must stay metadata-only and raw_prompt_stored=false.", [])


def _routing_check(trace: dict[str, Any]) -> dict[str, Any]:
    workflow = _object(trace.get("workflow"))
    selected = str(workflow.get("selected_workflow", ""))
    if selected and selected != "unknown":
        return _check("route_selected", "passed", f"Workflow selected: {selected}.", [])
    return _check("route_selected", "warning", "No concrete workflow was selected.", [])


def _boundary_check(trace: dict[str, Any]) -> dict[str, Any]:
    state = str(_nested(trace, "status", "evidence_state"))
    observed_refs = _list(trace.get("observed_refs"))
    if state in _OBSERVED_STATES and not observed_refs:
        return _check(
            "prepared_vs_observed_boundary",
            "failed",
            f"Evidence state is {state}, but no observed evidence refs were recorded.",
            [],
        )
    return _check(
        "prepared_vs_observed_boundary",
        "passed",
        "Prepared and observed evidence remain separated.",
        [str(ref.get("ref", "")) for ref in observed_refs if isinstance(ref, dict)],
    )


def _workflow_specific_check(trace: dict[str, Any]) -> dict[str, Any]:
    selected = str(_nested(trace, "workflow", "selected_workflow"))
    reasoning = _object(trace.get("reasoning_summary"))
    not_evidence = _strings(reasoning.get("not_evidence_yet"))
    if selected in {"plan", "ralplan", "ultragoal", "ultraprocess", "loop", "idea-to-deploy"} and not not_evidence:
        return _check("workflow_rubric", "warning", "Planning/coding lanes should name what is not evidence yet.", [])
    if selected in {"img-summary", "materials-package"} and any("generated" in str(ref).lower() for ref in trace.get("observed_refs", [])):
        return _check("workflow_rubric", "passed", "Deliverable/image lane has explicit observed refs.", [])
    return _check("workflow_rubric", "passed", "Workflow-specific rubric has no blocking gap.", [])


def _check(check_id: str, status: str, summary: str, evidence_refs: list[str]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "summary": summary,
        "evidence_refs": [ref for ref in evidence_refs if ref],
    }


def _eval_summary(*, failed: bool, warnings: list[dict[str, Any]]) -> str:
    if failed:
        return "Workflow trace has a blocking learning/evidence contract issue."
    if warnings:
        return "Workflow trace is usable for learning, with non-blocking rubric warnings."
    return "Workflow trace is valid and safe to use as learning material."


def _candidate_title(trace: dict[str, Any], failed_or_warned: list[dict[str, Any]]) -> str:
    selected = str(_nested(trace, "workflow", "selected_workflow") or "workflow")
    if failed_or_warned:
        return f"Improve {selected} after {failed_or_warned[0]['id']}"
    return f"Review {selected} workflow learning signal"


def _candidate_problem_summary(failed_or_warned: list[dict[str, Any]]) -> str:
    if not failed_or_warned:
        return "No failing eval checks were found; candidate is a manual review placeholder."
    return "; ".join(str(check.get("summary", "")) for check in failed_or_warned)


def _candidate_suggested_change(trace: dict[str, Any], failed_or_warned: list[dict[str, Any]]) -> str:
    selected = str(_nested(trace, "workflow", "selected_workflow") or "workflow")
    check_ids = {str(check.get("id", "")) for check in failed_or_warned}
    if "prepared_vs_observed_boundary" in check_ids:
        return f"Tighten {selected} status copy or observation recording so prepared work cannot be reported as observed."
    if "workflow_rubric" in check_ids:
        return f"Add clearer not-evidence-yet guidance to the {selected} workflow or its wrapper response."
    if "route_selected" in check_ids:
        return "Improve routing metadata so the selected workflow and harness are always explicit."
    return f"Review the {selected} workflow for a possible routing, rubric, or status-card improvement."


def _candidate_target_ref(target_type: str, trace: dict[str, Any], eval_result: dict[str, Any]) -> str:
    selected = str(_nested(trace, "workflow", "selected_workflow") or "unknown")
    normalized = str(target_type or "").strip().lower().replace("-", "_")
    if normalized in {"skill", "workflow_skill"}:
        return f"skill:{selected}"
    if normalized in {"routing", "router", "route"}:
        return "routing:recommendation-policy"
    if normalized in {"rubric", "workflow_rubric", "eval"}:
        return f"rubric:{eval_result.get('rubric_id', 'default')}"
    if normalized == "docs":
        return f"docs:workflow:{selected}"
    if normalized == "validator":
        return "validator:workflow-learning"
    if normalized == "playbook":
        return f"playbook:{selected}"
    return f"workflow:{selected}"


def _improvement_review_status(decision: str) -> str:
    return {
        "pending": "review_required",
        "approve": "approved",
        "revise": "revision_requested",
        "reject": "rejected",
    }.get(decision, "review_required")


def _improvement_review_severity(status: str) -> str:
    return {
        "review_required": "review",
        "approved": "ok",
        "revision_requested": "warning",
        "rejected": "blocked",
    }.get(status, "review")


def _improvement_review_headline(status: str) -> str:
    return {
        "review_required": "Improvement candidate needs human review.",
        "approved": "Improvement candidate is approved for a later explicit change.",
        "revision_requested": "Improvement candidate needs revision.",
        "rejected": "Improvement candidate was rejected.",
    }.get(status, "Improvement candidate needs review.")


def _improvement_review_summary(candidate: dict[str, Any]) -> str:
    target = str(candidate.get("target_ref", "unknown"))
    title = str(candidate.get("title", "workflow improvement"))
    return f"{title} targets {target}; review is required before any source change or regression claim."


def _improvement_review_primary_action(status: str) -> str:
    if status == "approved":
        return "add_regression_case"
    if status == "revision_requested":
        return "revise_improvement"
    if status == "rejected":
        return "show_status"
    return "review_improvement"


def _improvement_review_steps(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    gate = _object(candidate.get("human_gate"))
    decision = str(gate.get("decision", "pending"))
    approved = decision == "approve"
    rejected = decision == "reject"
    revised = decision == "revise"
    return [
        _improvement_review_step(
            "eval",
            "Eval",
            "ready",
            f"Eval {candidate.get('eval_id', '')} is the source signal for this candidate.",
        ),
        _improvement_review_step(
            "proposal",
            "Proposal",
            "ready",
            "Problem and suggested change are review material only.",
        ),
        _improvement_review_step(
            "human_review",
            "Human review",
            "complete" if approved or rejected or revised else "pending",
            f"Current decision: {decision}.",
        ),
        _improvement_review_step(
            "regression",
            "Regression",
            "pending" if approved else "blocked",
            "Record or replay a regression case before treating the improvement as durable.",
        ),
        _improvement_review_step(
            "apply",
            "Apply",
            "blocked",
            "No source patch is applied by v1 candidate creation.",
        ),
    ]


def _improvement_review_step(step_id: str, label: str, state: str, detail: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "state": state,
        "detail": detail,
    }


def _patch_proposal_status(*, decision: str, regression_count: int, replay_status: str) -> str:
    if decision == "reject":
        return "rejected"
    if decision != "approve":
        return "needs_candidate_review"
    if regression_count <= 0:
        return "needs_regression_case"
    if replay_status != "passed":
        return "needs_regression_replay"
    return "ready_for_human_patch"


def _patch_target_files(target_type: str, target_ref: str) -> list[str]:
    normalized = str(target_type or "").strip().lower().replace("-", "_")
    target = str(target_ref or "")
    if normalized in {"skill", "workflow_skill"}:
        workflow = target.split(":", 1)[1] if ":" in target else target
        return ["src/skills/catalog.py", "src/skills/render.py", f"skills/{workflow}/SKILL.md", "docs/WORKFLOWS.md"]
    if normalized in {"routing", "router", "route"}:
        return ["src/routing/recommend.py", "src/routing/chat.py", "tests/test_chat_router.py", "tests/test_cli.py"]
    if normalized in {"rubric", "workflow_rubric", "eval", "validator"}:
        return ["src/workflows/workflow_learning.py", "tests/test_workflow_learning.py", "tests/test_cli.py"]
    if normalized == "docs":
        return ["README.md", "docs/WORKFLOWS.md", "docs/HARNESS_QUALITY.md"]
    if normalized == "playbook":
        return ["src/catalogs/playbooks.py", "docs/PLAYBOOKS.md", "tests/test_cli.py"]
    return ["src/skills/catalog.py", "docs/WORKFLOWS.md", "tests/test_cli.py"]


def _patch_required_gates(status: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "candidate_approval",
            "required": True,
            "state": "complete" if status in {"needs_regression_case", "needs_regression_replay", "ready_for_human_patch"} else "blocked",
            "detail": "Human approval must exist before any source patch is prepared as work.",
        },
        {
            "id": "regression_case",
            "required": True,
            "state": "complete" if status in {"needs_regression_replay", "ready_for_human_patch"} else "pending",
            "detail": "A minimized regression case should exist before changing routing, skill, rubric, docs, or validator behavior.",
        },
        {
            "id": "regression_replay",
            "required": True,
            "state": "complete" if status == "ready_for_human_patch" else "pending",
            "detail": "Replay must pass before the proposal is treated as ready for an implementation PR.",
        },
        {
            "id": "implementation_review",
            "required": True,
            "state": "pending",
            "detail": "A future PR must still run tests and code review after any source edits.",
        },
    ]


def _patch_proposal_steps(status: str) -> list[dict[str, str]]:
    return [
        _improvement_review_step(
            "review_candidate",
            "Review candidate",
            "complete" if status != "needs_candidate_review" else "pending",
            "Approve, revise, or reject the candidate before creating source work.",
        ),
        _improvement_review_step(
            "record_regression",
            "Record regression",
            "complete" if status in {"needs_regression_replay", "ready_for_human_patch"} else "pending",
            "Capture a minimized fixture so the old failure can be replayed.",
        ),
        _improvement_review_step(
            "replay_regression",
            "Replay regression",
            "complete" if status == "ready_for_human_patch" else "pending",
            "Pass the deterministic replay before treating this as PR-ready.",
        ),
        _improvement_review_step(
            "prepare_pr",
            "Prepare PR",
            "ready" if status == "ready_for_human_patch" else "blocked",
            "Use the proposal as handoff material; OMH has not edited files.",
        ),
    ]


def _patch_proposal_primary_action(status: str) -> str:
    if status == "needs_candidate_review":
        return "review_improvement"
    if status == "needs_regression_case":
        return "add_regression_case"
    if status == "needs_regression_replay":
        return "replay_regression_cases"
    if status == "ready_for_human_patch":
        return "copy_patch_handoff"
    return "show_status"


def _patch_replay_results(replay: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": str(item.get("case_id", "")),
            "status": str(item.get("status", "")),
            "failure_count": len(_list(item.get("failures"))),
        }
        for item in _list(replay.get("results"))
        if isinstance(item, dict)
    ]


def _patch_regression_snapshot(cases: list[dict[str, Any]], replay: dict[str, Any]) -> list[dict[str, Any]]:
    results_by_id = {
        str(item.get("case_id", "")): item
        for item in _list(replay.get("results"))
        if isinstance(item, dict)
    }
    snapshots: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id", ""))
        result = _object(results_by_id.get(case_id))
        snapshots.append(
            {
                "case_id": case_id,
                "expected_workflow": str(_nested(case, "expected", "selected_workflow") or ""),
                "expected_harness": str(_nested(case, "expected", "selected_harness") or ""),
                "status": str(result.get("status", "missing")),
                "failure_count": len(_list(result.get("failures"))),
            }
        )
    return snapshots


def _select_export_traces(paths: OmhPaths, *, trace_ids: list[str], limit: int | None) -> list[dict[str, Any]]:
    if trace_ids:
        traces = []
        for trace_id in trace_ids:
            try:
                traces.append(show_learning_trace(paths, trace_id))
            except FileNotFoundError as exc:
                raise WorkflowLearningError(f"learning trace not found for export: {trace_id}") from exc
        return traces
    traces = []
    if not paths.learning_traces_dir.exists():
        return []
    for path in sorted(paths.learning_traces_dir.glob("*.json")):
        record = read_json_object(path)
        if record:
            validate_workflow_learning_trace(record)
            traces.append(record)
    traces = sorted(traces, key=lambda item: (str(item.get("created_at", "")), str(item.get("trace_id", ""))))
    return _apply_limit(traces, limit)


def _related_export_records(
    paths: OmhPaths,
    kind: str,
    validator: Callable[[dict[str, Any]], None],
    trace_ids: set[str],
) -> list[dict[str, Any]]:
    if not trace_ids:
        return []
    directory = {
        "eval": paths.learning_evals_dir,
        "candidate": paths.learning_candidates_dir,
        "patch_proposal": paths.learning_patch_proposals_dir,
        "regression_case": paths.learning_regressions_dir,
        "export": paths.learning_exports_dir,
    }[kind]
    if not directory.exists():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        record = read_json_object(path)
        if not record:
            continue
        validator(record)
        if str(record.get("trace_id", "")) in trace_ids:
            records.append(record)
    return sorted(records, key=lambda item: (str(item.get("created_at", "")), _record_identifier(item, kind)))


def _redacted_regression_case(case: dict[str, Any]) -> dict[str, Any]:
    validate_regression_case(case)
    fixture = _object(case.get("fixture"))
    redacted = {
        "schema_version": REGRESSION_CASE_SCHEMA_VERSION,
        "record_type": "regression_case",
        "case_id": str(case.get("case_id", "")),
        "trace_id": str(case.get("trace_id", "")),
        "created_at": str(case.get("created_at", "")),
        "fixture": {
            "source": str(fixture.get("source", "")),
            "fixture_sha256": str(fixture.get("fixture_sha256", "")),
            "message_sha256": str(fixture.get("message_sha256", "")),
            "message_length": int(fixture.get("message_length", 0) or 0),
            "fixture_text_omitted": True,
            "fixture_text_stored_in_export": False,
            "privacy": _export_privacy_projection(_object(fixture.get("privacy"))),
        },
        "expected": _export_regression_expected(_object(case.get("expected"))),
        "replay_policy": _export_replay_policy(_object(case.get("replay_policy"))),
        "claim_boundary": "Regression case export omits fixture text and free-form claim prose.",
    }
    validate_regression_case(redacted)
    return redacted


def _export_trace_projection(trace: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_learning_trace(trace)
    source = _object(trace.get("source"))
    route = _object(trace.get("route"))
    workflow = _object(trace.get("workflow"))
    improvement = _object(trace.get("improvement"))
    status = _object(trace.get("status"))
    projection = {
        "schema_version": WORKFLOW_LEARNING_TRACE_SCHEMA_VERSION,
        "record_type": "workflow_learning_trace",
        "trace_id": str(trace.get("trace_id", "")),
        "created_at": str(trace.get("created_at", "")),
        "updated_at": str(trace.get("updated_at", "")),
        "privacy": _export_privacy_projection(_object(trace.get("privacy"))),
        "source": {
            "kind": str(source.get("kind", "")),
            "source": str(source.get("source", "")),
            "source_ref": str(source.get("source_ref", "")),
            "thread_key": str(source.get("thread_key", "")),
            "message_sha256": str(source.get("message_sha256", "")),
            "message_length": int(source.get("message_length", 0) or 0),
            "source_metadata_keys": sorted(str(key) for key in _object(source.get("source_metadata")).keys()),
        },
        "route": {
            "action": _export_token(route.get("action")),
            "selected_workflow": _export_token(route.get("selected_workflow")),
            "selected_harness": _export_token(route.get("selected_harness")),
            "confidence": _export_token(route.get("confidence")),
            "score": route.get("score", 0) if isinstance(route.get("score"), (int, float)) else 0,
            "matched_count": len(_list(route.get("matched"))),
            "matched_values_omitted": bool(_list(route.get("matched"))),
        },
        "workflow": {
            "selected_workflow": _export_token(workflow.get("selected_workflow")),
            "selected_harness": _export_token(workflow.get("selected_harness")),
            "workflow_context_id": _export_token(workflow.get("workflow_context_id")),
            "phase": _export_token(workflow.get("phase")),
            "next_action": _export_token(workflow.get("next_action")),
        },
        "reasoning_summary": _export_reasoning_summary(trace),
        "prepared_refs": _export_refs(_list(trace.get("prepared_refs"))),
        "observed_refs": _export_refs(_list(trace.get("observed_refs"))),
        "status": {
            "evidence_state": str(status.get("evidence_state", "")),
            "learning_state": str(status.get("learning_state", "")),
            "outcome": str(status.get("outcome", "")),
        },
        "improvement": {
            "candidate_available": improvement.get("candidate_available") is True,
            "candidate_ref_count": len(_strings(improvement.get("candidate_refs"))),
            "regression_case_ref_count": len(_strings(improvement.get("regression_case_refs"))),
            "free_form_values_omitted": True,
        },
        "overclaim_guard": {
            "count": len(_strings(trace.get("overclaim_guard"))),
            "values_omitted": bool(_strings(trace.get("overclaim_guard"))),
        },
    }
    validate_workflow_learning_trace(projection)
    return projection


def _export_eval_projection(result: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_eval_result(result)
    projection = {
        "schema_version": WORKFLOW_EVAL_RESULT_SCHEMA_VERSION,
        "record_type": "workflow_eval_result",
        "eval_id": str(result.get("eval_id", "")),
        "trace_id": str(result.get("trace_id", "")),
        "created_at": str(result.get("created_at", "")),
        "rubric_id": str(result.get("rubric_id", "")),
        "status": str(result.get("status", "")),
        "checks": [
            {
                "id": str(check.get("id", "")),
                "status": str(check.get("status", "")),
                "evidence_refs": _export_ref_values(_strings(check.get("evidence_refs"))),
            }
            for check in _list(result.get("checks"))
            if isinstance(check, dict)
        ],
        "claim_boundary": str(result.get("claim_boundary", "")),
    }
    _validate_export_eval_projection(projection)
    return projection


def _export_candidate_projection(candidate: dict[str, Any]) -> dict[str, Any]:
    validate_improvement_candidate(candidate)
    gate = _object(candidate.get("human_gate"))
    proposal = _object(candidate.get("proposal"))
    diff_preview = _object(candidate.get("diff_preview"))
    projection = {
        "schema_version": IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
        "record_type": "improvement_candidate",
        "candidate_id": str(candidate.get("candidate_id", "")),
        "trace_id": str(candidate.get("trace_id", "")),
        "eval_id": str(candidate.get("eval_id", "")),
        "created_at": str(candidate.get("created_at", "")),
        "target_type": str(candidate.get("target_type", "")),
        "status": str(candidate.get("status", "")),
        "human_gate": {
            "required": gate.get("required") is True,
            "decision": str(gate.get("decision", "")),
            "allowed_decisions": _strings(gate.get("allowed_decisions")),
        },
        "proposal": {
            "regression_case_recommended": proposal.get("regression_case_recommended") is True,
        },
        "diff_preview": {
            "available": diff_preview.get("available") is True,
        },
        "claim_boundary": str(candidate.get("claim_boundary", "")),
    }
    _validate_export_candidate_projection(projection)
    return projection


def _export_patch_proposal_projection(proposal: dict[str, Any]) -> dict[str, Any]:
    validate_improvement_patch_proposal(proposal)
    target = _object(proposal.get("target"))
    regression = _object(proposal.get("regression_gate"))
    projection = {
        "schema_version": IMPROVEMENT_PATCH_PROPOSAL_SCHEMA_VERSION,
        "record_type": "improvement_patch_proposal",
        "proposal_id": str(proposal.get("proposal_id", "")),
        "candidate_id": str(proposal.get("candidate_id", "")),
        "trace_id": str(proposal.get("trace_id", "")),
        "eval_id": str(proposal.get("eval_id", "")),
        "created_at": str(proposal.get("created_at", "")),
        "status": str(proposal.get("status", "")),
        "target": {
            "type": str(target.get("type", "")),
            "ref": str(target.get("ref", "")),
        },
        "source_file_count": len(_strings(target.get("source_files"))),
        "regression_gate": {
            "case_count": int(regression.get("case_count", 0) or 0),
            "replay_status": str(regression.get("replay_status", "")),
            "passed": regression.get("passed") is True,
            "snapshot_count": len(_list(regression.get("snapshot"))),
        },
        "required_gate_count": len(_list(proposal.get("required_gates"))),
        "verification_command_count": len(_strings(proposal.get("verification_commands"))),
        "primary_action": str(proposal.get("primary_action", "")),
        "claim_boundary": str(proposal.get("claim_boundary", "")),
    }
    _validate_export_patch_proposal_projection(projection)
    return projection


def _export_privacy_projection(privacy: dict[str, Any]) -> dict[str, Any]:
    projected = _sanitize_export_record(privacy)
    projected.setdefault("mode", PRIVACY_MODE)
    if "raw_prompt_stored" in privacy:
        projected["raw_prompt_stored"] = privacy.get("raw_prompt_stored") is True
    if "raw_platform_event_stored" in privacy:
        projected["raw_platform_event_stored"] = privacy.get("raw_platform_event_stored") is True
    if "fixture_text_stored" in privacy:
        projected["fixture_text_stored"] = privacy.get("fixture_text_stored") is True
    return projected


def _export_reasoning_summary(trace: dict[str, Any]) -> dict[str, Any]:
    reasoning = _object(trace.get("reasoning_summary"))
    workflow = _object(trace.get("workflow"))
    not_evidence = _strings(reasoning.get("not_evidence_yet"))
    return {
        "why_this_workflow": "omitted_from_metadata_export" if reasoning.get("why_this_workflow") else "",
        "next_action": _export_token(workflow.get("next_action") or reasoning.get("next_action")),
        "not_evidence_yet": [],
        "not_evidence_yet_count": len(not_evidence),
        "not_evidence_yet_omitted": bool(not_evidence),
        "claim_boundary": "omitted_from_metadata_export" if reasoning.get("claim_boundary") else "",
        "claim_boundary_omitted": bool(reasoning.get("claim_boundary")),
    }


def _export_refs(values: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        kind = _export_token(value.get("kind") or value.get("type"))
        ref = str(value.get("ref") or value.get("path") or value.get("id") or "")
        refs.append(
            {
                "kind": kind,
                "ref_sha256": hashlib.sha256(ref.encode("utf-8")).hexdigest() if ref else "",
                "ref_length": len(ref),
                "ref_value_omitted": bool(ref),
            }
        )
    return refs


def _export_ref_values(values: list[str]) -> list[str]:
    return [f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}" for value in values if value]


def _export_regression_expected(expected: dict[str, Any]) -> dict[str, Any]:
    not_evidence = _strings(expected.get("not_evidence_yet_includes"))
    return {
        "selected_workflow": _export_token(expected.get("selected_workflow")),
        "selected_harness": _export_token(expected.get("selected_harness")),
        "next_action": _export_token(expected.get("next_action")),
        "claim_boundary_contains": "omitted_from_metadata_export"
        if expected.get("claim_boundary_contains")
        else "",
        "not_evidence_yet_includes": [],
        "not_evidence_yet_count": len(not_evidence),
        "not_evidence_yet_omitted": bool(not_evidence),
    }


def _export_replay_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": _export_token(policy.get("mode")),
        "requires_fixture_text": policy.get("requires_fixture_text") is True,
        "skip_reason": "omitted_from_metadata_export" if policy.get("skip_reason") else "",
        "skip_reason_omitted": bool(policy.get("skip_reason")),
    }


def _export_token(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", text):
        return text
    return "omitted_free_text"


def _learning_export_summary(
    *,
    traces: list[dict[str, Any]],
    evals: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    patch_proposals: list[dict[str, Any]],
    regression_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "counts": {
            "traces": len(traces),
            "evals": len(evals),
            "candidates": len(candidates),
            "patch_proposals": len(patch_proposals),
            "regression_cases": len(regression_cases),
        },
        "workflows": sorted({str(_nested(trace, "workflow", "selected_workflow")) for trace in traces if _nested(trace, "workflow", "selected_workflow")}),
        "evidence_states": sorted({str(_nested(trace, "status", "evidence_state")) for trace in traces if _nested(trace, "status", "evidence_state")}),
        "outcomes": sorted({str(_nested(trace, "status", "outcome")) for trace in traces if _nested(trace, "status", "outcome")}),
        "eval_statuses": sorted({str(result.get("status", "")) for result in evals if result.get("status")}),
        "candidate_statuses": sorted({str(candidate.get("status", "")) for candidate in candidates if candidate.get("status")}),
        "patch_proposal_statuses": sorted({str(proposal.get("status", "")) for proposal in patch_proposals if proposal.get("status")}),
    }


def _learning_study_card(
    trace: dict[str, Any],
    *,
    evals: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    patch_proposals: list[dict[str, Any]],
    regression_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_or_warned = [
        {
            "eval_id": result.get("eval_id", ""),
            "status": result.get("status", ""),
            "checks": [
                {
                    "id": check.get("id", ""),
                    "status": check.get("status", ""),
                    "summary": check.get("summary", ""),
                }
                for check in _list(result.get("checks"))
                if isinstance(check, dict) and check.get("status") in {"failed", "warning"}
            ],
        }
        for result in evals
        if result.get("status") in {"failed", "warning"}
    ]
    return {
        "schema_version": "workflow_learning_study_card/v1",
        "trace_id": trace.get("trace_id", ""),
        "learning_trace_ref": learning_trace_ref(str(trace.get("trace_id", ""))),
        "source_kind": _nested(trace, "source", "kind"),
        "selected_workflow": _nested(trace, "workflow", "selected_workflow"),
        "selected_harness": _nested(trace, "workflow", "selected_harness"),
        "why_this_workflow": "omitted_from_metadata_export",
        "next_action": _nested(trace, "workflow", "next_action"),
        "not_evidence_yet_count": int(_nested(trace, "reasoning_summary", "not_evidence_yet_count") or 0),
        "not_evidence_yet_omitted": _nested(trace, "reasoning_summary", "not_evidence_yet_omitted") is True,
        "evidence_state": _nested(trace, "status", "evidence_state"),
        "outcome": _nested(trace, "status", "outcome"),
        "eval_statuses": [str(result.get("status", "")) for result in evals],
        "failed_or_warning_checks": failed_or_warned,
        "candidate_refs": [_record_ref("candidate", str(candidate.get("candidate_id", ""))) for candidate in candidates],
        "patch_proposal_refs": [
            _record_ref("patch_proposal", str(proposal.get("proposal_id", ""))) for proposal in patch_proposals
        ],
        "regression_case_refs": [
            _record_ref("regression_case", str(case.get("case_id", ""))) for case in regression_cases
        ],
        "reflection_questions": [
            "Was the selected workflow the right lane for the original request?",
            "Did the response clearly separate prepared work from observed evidence?",
            "Which candidate or regression case should a human review before changing a skill or routing rule?",
        ],
    }


def _read_regression_cases(paths: OmhPaths) -> list[dict[str, Any]]:
    indexed = _records_from_index(paths, "regression_case", regression_case_path, validate_regression_case)
    if indexed:
        return indexed
    if not paths.learning_regressions_dir.exists():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(paths.learning_regressions_dir.glob("*.json")):
        case = read_json_object(path)
        if case:
            validate_regression_case(case)
            cases.append(case)
    return cases


def _read_related_regression_cases(paths: OmhPaths, trace_id: str) -> list[dict[str, Any]]:
    return sorted(
        [case for case in _read_regression_cases(paths) if str(case.get("trace_id", "")) == trace_id],
        key=lambda case: str(case.get("case_id", "")),
    )


def _replay_related_regression_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [_replay_regression_case(case) for case in cases]
    failed = [item for item in results if item["status"] == "failed"]
    skipped = [item for item in results if item["status"] == "skipped"]
    passed = [item for item in results if item["status"] == "passed"]
    return {
        "schema_version": "workflow_regression_replay/v1",
        "status": _regression_replay_status(total=len(results), failed=len(failed), skipped=len(skipped)),
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "results": results,
        "claim_boundary": "Related regression replay checks deterministic routing contracts only; it does not execute workflows or patch skills.",
    }


def _read_valid_learning_records(
    directory: Path,
    validator: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = read_json_object(path)
            if not record:
                continue
            validator(record)
            records.append(record)
        except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError):
            continue
    return records


def _learning_audit_blocking_issues(
    *,
    scanned: dict[str, Any],
    index_check: dict[str, Any],
    failed_evals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for invalid in _list(scanned.get("invalid_records")):
        if not isinstance(invalid, dict):
            continue
        issues.append(
            {
                "id": "invalid_learning_record",
                "severity": "blocking",
                "kind": str(invalid.get("kind", "")),
                "path": str(invalid.get("path", "")),
                "summary": str(invalid.get("error", "")),
                "next_action": "repair_or_remove_invalid_record",
            }
        )
    if index_check.get("ok") is not True:
        issues.append(
            {
                "id": "learning_index_not_clean",
                "severity": "blocking",
                "summary": f"Learning index status is {index_check.get('status', 'unknown')}.",
                "next_action": "omh learning index rebuild",
            }
        )
    for result in failed_evals:
        issues.append(
            {
                "id": "failed_workflow_eval",
                "severity": "blocking",
                "trace_id": str(result.get("trace_id", "")),
                "eval_id": str(result.get("eval_id", "")),
                "summary": "A workflow eval failed; review the trace before treating it as learning-ready.",
                "next_action": "omh learning candidate <trace-id>",
            }
        )
    return issues


def _learning_audit_warnings(
    *,
    missing_eval: list[str],
    missing_regression: list[str],
    missing_candidate: list[str],
    warning_evals: list[dict[str, Any]],
    pending_candidates: list[dict[str, Any]],
    replay: dict[str, Any],
    exports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if missing_eval:
        warnings.append(
            {
                "id": "trace_without_eval",
                "count": len(missing_eval),
                "trace_ids": missing_eval[:10],
                "summary": "Some traces have not been checked by deterministic rubrics.",
                "next_action": "omh learning eval <trace-id>",
            }
        )
    if missing_regression:
        warnings.append(
            {
                "id": "trace_without_regression_case",
                "count": len(missing_regression),
                "trace_ids": missing_regression[:10],
                "summary": "Some traces cannot be replayed as future regression cases yet.",
                "next_action": "omh learning regression add <trace-id> --fixture-message <redacted fixture>",
            }
        )
    if missing_candidate:
        warnings.append(
            {
                "id": "evaluated_trace_without_candidate",
                "count": len(missing_candidate),
                "trace_ids": missing_candidate[:10],
                "summary": "Evaluated traces have no reviewable improvement candidate.",
                "next_action": "omh learning candidate <trace-id>",
            }
        )
    if warning_evals:
        warnings.append(
            {
                "id": "warning_workflow_eval",
                "count": len(warning_evals),
                "eval_ids": [str(result.get("eval_id", "")) for result in warning_evals[:10]],
                "summary": "Some workflow evals passed with rubric warnings.",
                "next_action": "review_warning_eval",
            }
        )
    if pending_candidates:
        warnings.append(
            {
                "id": "pending_improvement_candidate",
                "count": len(pending_candidates),
                "candidate_ids": [str(candidate.get("candidate_id", "")) for candidate in pending_candidates[:10]],
                "summary": "Improvement candidates still need human review before any source changes.",
                "next_action": "review_improvement_candidate",
            }
        )
    if replay.get("status") in {"failed", "skipped", "incomplete"}:
        warnings.append(
            {
                "id": "regression_replay_not_clean",
                "status": str(replay.get("status", "")),
                "summary": "Regression replay is not clean across the local corpus.",
                "next_action": "fix_or_minimize_regression_cases",
            }
        )
    if not exports:
        warnings.append(
            {
                "id": "no_learning_export_bundle",
                "summary": "No redacted learning export bundle has been written for external review.",
                "next_action": "omh learning export",
            }
        )
    return warnings


def _learning_audit_status(
    *,
    traces_total: int,
    blocking_issues: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    replay: dict[str, Any],
) -> str:
    if blocking_issues:
        return "blocked"
    if traces_total == 0:
        return "no_records"
    if warnings or replay.get("status") not in {"passed", "no_cases"}:
        return "needs_attention"
    return "ready"


def _learning_audit_card_severity(status: str) -> str:
    return {
        "ready": "ok",
        "no_records": "empty",
        "needs_attention": "warning",
        "blocked": "blocking",
    }.get(status, "warning")


def _learning_audit_card_headline(status: str) -> str:
    return {
        "ready": "Workflow learning is ready for review.",
        "no_records": "No workflow learning records yet.",
        "needs_attention": "Workflow learning needs one more step.",
        "blocked": "Workflow learning is blocked.",
    }.get(status, "Workflow learning needs review.")


def _learning_audit_card_summary(audit: dict[str, Any]) -> str:
    counts = _object(audit.get("counts"))
    coverage = _object(audit.get("coverage"))
    replay = _object(audit.get("regression_replay"))
    status = str(audit.get("status", "needs_attention"))
    if status == "no_records":
        return "Record a metadata-only trace before evaluating, replaying, or exporting workflow learning material."
    if status == "blocked":
        return "Repair invalid records, failed evals, or the learning index before treating this corpus as learning-ready."
    return (
        f"{int(counts.get('traces', 0) or 0)} trace(s), "
        f"{int(coverage.get('eval_coverage_percent', 0) or 0)}% eval coverage, "
        f"{int(coverage.get('regression_coverage_percent', 0) or 0)}% regression coverage, "
        f"replay {replay.get('status', 'unknown')}."
    )


def _learning_audit_primary_action(audit: dict[str, Any]) -> str:
    status = str(audit.get("status", "needs_attention"))
    if status == "no_records":
        return "record_workflow_learning_trace"
    next_actions = _list(audit.get("next_actions"))
    if next_actions:
        action_id = str(_object(next_actions[0]).get("id", ""))
        return {
            "rebuild_learning_index": "rebuild_learning_index",
            "evaluate_trace": "show_learning_eval",
            "add_regression_case": "add_regression_case",
            "create_candidate": "propose_skill_improvement",
            "review_candidate": "review_improvement",
            "write_learning_export": "export_learning_bundle",
        }.get(action_id, "audit_learning_readiness")
    return "audit_learning_readiness"


def _learning_audit_card_steps(audit: dict[str, Any]) -> list[dict[str, Any]]:
    counts = _object(audit.get("counts"))
    coverage = _object(audit.get("coverage"))
    index = _object(audit.get("index"))
    replay = _object(audit.get("regression_replay"))
    warnings = {str(item.get("id", "")) for item in _list(audit.get("warnings")) if isinstance(item, dict)}
    blocking = {str(item.get("id", "")) for item in _list(audit.get("blocking_issues")) if isinstance(item, dict)}
    trace_count = int(counts.get("traces", 0) or 0)
    return [
        _learning_audit_step(
            "trace",
            "Trace",
            "ready" if trace_count else "missing",
            f"{trace_count} metadata-only trace(s).",
        ),
        _learning_audit_step(
            "eval",
            "Eval",
            _learning_audit_step_state("trace_without_eval", warnings, blocking, int(coverage.get("eval_coverage_percent", 0) or 0)),
            f"{int(coverage.get('eval_coverage_percent', 0) or 0)}% of summarized traces have evals.",
        ),
        _learning_audit_step(
            "regression",
            "Regression",
            _learning_audit_step_state("trace_without_regression_case", warnings, blocking, int(coverage.get("regression_coverage_percent", 0) or 0)),
            f"{int(coverage.get('regression_coverage_percent', 0) or 0)}% of summarized traces have replay cases.",
        ),
        _learning_audit_step(
            "index",
            "Index",
            "ready" if index.get("ok") is True else "blocked",
            f"Index status: {index.get('status', 'unknown')}.",
        ),
        _learning_audit_step(
            "replay",
            "Replay",
            "ready" if replay.get("status") in {"passed", "no_cases"} else "blocked",
            f"Replay status: {replay.get('status', 'unknown')}.",
        ),
        _learning_audit_step(
            "export",
            "Export",
            "missing" if "no_learning_export_bundle" in warnings else "ready",
            f"{int(counts.get('exports', 0) or 0)} redacted review export(s).",
        ),
    ]


def _learning_audit_step_state(issue_id: str, warnings: set[str], blocking: set[str], coverage_percent: int) -> str:
    if issue_id in blocking:
        return "blocked"
    if issue_id in warnings:
        return "missing"
    if coverage_percent >= 100:
        return "ready"
    return "missing"


def _learning_audit_step(step_id: str, label: str, state: str, detail: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "state": state,
        "detail": detail,
    }


def _learning_audit_replay_blocked(scanned: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "workflow_regression_replay/v1",
        "status": "blocked",
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "results": [],
        "invalid_records": scanned["invalid_records"],
        "claim_boundary": "Regression replay was not run because invalid local learning records need repair first.",
    }


def _learning_audit_next_actions(
    *,
    status: str,
    missing_eval: list[str],
    missing_regression: list[str],
    missing_candidate: list[str],
    pending_candidates: list[dict[str, Any]],
    index_check: dict[str, Any],
    exports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if index_check.get("ok") is not True:
        actions.append({"id": "rebuild_learning_index", "command": "omh learning index rebuild"})
    if missing_eval:
        actions.append({"id": "evaluate_trace", "trace_id": missing_eval[0], "command": f"omh learning eval {missing_eval[0]}"})
    if missing_regression:
        actions.append(
            {
                "id": "add_regression_case",
                "trace_id": missing_regression[0],
                "command": f"omh learning regression add {missing_regression[0]} --fixture-message <redacted fixture>",
            }
        )
    if missing_candidate:
        actions.append({"id": "create_candidate", "trace_id": missing_candidate[0], "command": f"omh learning candidate {missing_candidate[0]}"})
    if pending_candidates:
        actions.append(
            {
                "id": "review_candidate",
                "candidate_id": str(pending_candidates[0].get("candidate_id", "")),
                "command": "review the candidate before applying any source change",
            }
        )
    if not exports and status != "no_records":
        actions.append({"id": "write_learning_export", "command": "omh learning export"})
    if not actions:
        actions.append({"id": "continue_recording", "command": "omh learning record <message or --from-runtime-run>"})
    return actions


def _patch_proposals_by_candidate(proposals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        candidate_id = str(proposal.get("candidate_id", ""))
        if not candidate_id:
            continue
        grouped.setdefault(candidate_id, []).append(proposal)
    for candidate_id, items in list(grouped.items()):
        grouped[candidate_id] = sorted(
            items,
            key=lambda item: (
                str(item.get("created_at", "")),
                _patch_proposal_progress_rank(str(item.get("status", ""))),
                str(item.get("proposal_id", "")),
            ),
        )
    return grouped


def _latest_patch_proposal(proposals: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not proposals:
        return None
    return proposals[-1]


def _patch_proposal_progress_rank(status: str) -> int:
    return {
        "needs_candidate_review": 0,
        "needs_regression_case": 1,
        "needs_regression_replay": 2,
        "ready_for_human_patch": 3,
        "rejected": 4,
    }.get(status, -1)


def _candidate_review_queue_entry(
    candidate: dict[str, Any],
    *,
    decision: str,
    latest_proposal: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidate_id = str(candidate.get("candidate_id", ""))
    trace_id = str(candidate.get("trace_id", ""))
    eval_id = str(candidate.get("eval_id", ""))
    title = str(candidate.get("title", "Workflow improvement candidate"))
    target_ref = str(candidate.get("target_ref", ""))
    if decision == "pending":
        return _learning_review_queue_entry(
            kind="candidate_review",
            status="needs_candidate_review",
            severity="review",
            priority=10,
            title=title,
            detail=f"Human review is required before changing {target_ref}.",
            primary_action="review_improvement",
            next_command=f"omh learning review-candidate {candidate_id} --decision approve|revise|reject",
            refs=[
                _record_ref("candidate", candidate_id),
                learning_trace_ref(trace_id),
                _record_ref("eval", eval_id),
            ],
            created_at=str(candidate.get("created_at", "")),
            candidate_id=candidate_id,
            trace_id=trace_id,
            eval_id=eval_id,
        )
    if decision == "revise":
        return _learning_review_queue_entry(
            kind="candidate_revision",
            status="needs_revision",
            severity="warning",
            priority=15,
            title=title,
            detail=f"The improvement candidate needs revision before it can target {target_ref}.",
            primary_action="revise_improvement",
            next_command=f"omh learning candidate {trace_id} --target-type {candidate.get('target_type', 'workflow_rubric')}",
            refs=[
                _record_ref("candidate", candidate_id),
                learning_trace_ref(trace_id),
                _record_ref("eval", eval_id),
            ],
            created_at=str(candidate.get("created_at", "")),
            candidate_id=candidate_id,
            trace_id=trace_id,
            eval_id=eval_id,
        )
    if decision == "approve":
        if latest_proposal is None:
            return _learning_review_queue_entry(
                kind="candidate_patch_gap",
                status="needs_patch_proposal",
                severity="warning",
                priority=20,
                title=title,
                detail="The candidate is approved, but no patch proposal snapshot has been prepared yet.",
                primary_action="prepare_patch_proposal",
                next_command=f"omh learning proposal {candidate_id}",
                refs=[
                    _record_ref("candidate", candidate_id),
                    learning_trace_ref(trace_id),
                    _record_ref("eval", eval_id),
                ],
                created_at=str(candidate.get("created_at", "")),
                candidate_id=candidate_id,
                trace_id=trace_id,
                eval_id=eval_id,
            )
        return _patch_proposal_queue_entry(latest_proposal, candidate_title=title)
    return None


def _patch_proposal_queue_entry(proposal: dict[str, Any], *, candidate_title: str = "") -> dict[str, Any]:
    status = str(proposal.get("status", "needs_candidate_review"))
    severity = {
        "ready_for_human_patch": "ready",
        "needs_candidate_review": "review",
        "needs_regression_case": "warning",
        "needs_regression_replay": "warning",
        "rejected": "blocking",
    }.get(status, "warning")
    priority = {
        "ready_for_human_patch": 30,
        "needs_candidate_review": 10,
        "needs_regression_case": 20,
        "needs_regression_replay": 25,
        "rejected": 90,
    }.get(status, 40)
    title = candidate_title or str(proposal.get("problem_statement", "Workflow learning patch proposal"))
    primary_action = str(proposal.get("primary_action", "show_patch_proposal"))
    next_command = {
        "review_improvement": f"omh learning review-candidate {proposal.get('candidate_id', '')} --decision approve|revise|reject",
        "add_regression_case": f"omh learning regression add {proposal.get('trace_id', '')} --fixture-message <redacted fixture>",
        "replay_regression_cases": "omh learning regression replay",
        "copy_patch_handoff": f"omh learning proposal {proposal.get('candidate_id', '')}",
    }.get(primary_action, "omh learning audit")
    return _learning_review_queue_entry(
        kind="patch_proposal",
        status=status,
        severity=severity,
        priority=priority,
        title=title,
        detail=str(proposal.get("proposed_change_summary", "")) or "Patch proposal is review material only.",
        primary_action=primary_action,
        next_command=next_command,
        refs=[
            _record_ref("patch_proposal", str(proposal.get("proposal_id", ""))),
            _record_ref("candidate", str(proposal.get("candidate_id", ""))),
            learning_trace_ref(str(proposal.get("trace_id", ""))),
        ],
        created_at=str(proposal.get("created_at", "")),
        candidate_id=str(proposal.get("candidate_id", "")),
        proposal_id=str(proposal.get("proposal_id", "")),
        trace_id=str(proposal.get("trace_id", "")),
        eval_id=str(proposal.get("eval_id", "")),
    )


def _learning_review_queue_entry(
    *,
    kind: str,
    status: str,
    severity: str,
    priority: int,
    title: str,
    detail: str,
    primary_action: str,
    next_command: str,
    refs: list[str],
    created_at: str = "",
    candidate_id: str = "",
    proposal_id: str = "",
    trace_id: str = "",
    eval_id: str = "",
) -> dict[str, Any]:
    seed = json.dumps(
        {
            "kind": kind,
            "status": status,
            "candidate_id": candidate_id,
            "proposal_id": proposal_id,
            "trace_id": trace_id,
            "eval_id": eval_id,
            "refs": refs,
        },
        sort_keys=True,
    )
    return {
        "entry_id": _id("wlq", seed),
        "kind": kind,
        "status": status,
        "severity": severity,
        "priority": priority,
        "created_at": created_at or utc_now(),
        "title": title,
        "detail": detail,
        "primary_action": primary_action,
        "next_command": next_command,
        "refs": refs,
        "candidate_id": candidate_id,
        "proposal_id": proposal_id,
        "trace_id": trace_id,
        "eval_id": eval_id,
    }


def _learning_review_queue_status(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "empty"
    if any(entry.get("severity") == "blocking" for entry in entries):
        return "blocked"
    if any(entry.get("status") != "ready_for_human_patch" for entry in entries):
        return "needs_review"
    return "ready"


def _coverage_percent(covered: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((covered / total) * 100)


def _replay_regression_case(case: dict[str, Any]) -> dict[str, Any]:
    fixture = _object(case.get("fixture"))
    expected = _object(case.get("expected"))
    fixture_text = str(fixture.get("fixture_text") or fixture.get("redacted_message") or "")
    if not fixture_text:
        return {
            "case_id": case["case_id"],
            "status": "skipped",
            "reason": "No operator-provided minimized fixture was provided.",
        }
    from ..wrapper.contract import build_chat_interaction_payload

    payload = build_chat_interaction_payload(fixture_text, source=str(fixture.get("source", "generic")))
    actual_workflow = str(_nested(payload, "chat_response", "state", "selected_workflow") or _nested(payload, "route", "selected_skill"))
    actual_harness = str(_nested(payload, "route", "selected_harness") or _nested(payload, "chat_response", "usage_trace", "selected_harness"))
    actual_next_action = str(payload.get("next_action", ""))
    failures = []
    if expected.get("selected_workflow") and actual_workflow != expected.get("selected_workflow"):
        failures.append(f"selected_workflow expected {expected.get('selected_workflow')} got {actual_workflow}")
    if expected.get("selected_harness") and actual_harness != expected.get("selected_harness"):
        failures.append(f"selected_harness expected {expected.get('selected_harness')} got {actual_harness}")
    if expected.get("next_action") and actual_next_action != expected.get("next_action"):
        failures.append(f"next_action expected {expected.get('next_action')} got {actual_next_action}")
    return {
        "case_id": case["case_id"],
        "status": "failed" if failures else "passed",
        "actual": {
            "selected_workflow": actual_workflow,
            "selected_harness": actual_harness,
            "next_action": actual_next_action,
        },
        "failures": failures,
    }


def _regression_replay_status(*, total: int, failed: int, skipped: int) -> str:
    if failed:
        return "failed"
    if total == 0:
        return "no_cases"
    if skipped == total:
        return "skipped"
    if skipped:
        return "incomplete"
    return "passed"


def _records_from_index(
    paths: OmhPaths,
    kind: str,
    path_for_id: Callable[[OmhPaths, str], Path],
    validator: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    index = read_json_object(paths.learning_index_path) or {}
    if index.get("schema_version") != WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION:
        return []
    records: list[dict[str, Any]] = []
    for entry in _list(index.get("records")):
        if not isinstance(entry, dict) or entry.get("kind") != kind:
            continue
        identifier = str(entry.get("id", ""))
        if not identifier:
            continue
        payload = read_json_object(path_for_id(paths, identifier))
        if payload:
            validator(payload)
            records.append(payload)
    return records


def _apply_limit(records: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return records
    if limit <= 0:
        return []
    return records[-limit:]


def _update_learning_index(paths: OmhPaths, record: dict[str, Any], kind: str) -> None:
    current = read_json_object(paths.learning_index_path) or _empty_learning_index()
    records = [item for item in _list(current.get("records")) if isinstance(item, dict)]
    identifier = _record_identifier(record, kind)
    entry = _index_entry(record, kind, updated_at=utc_now())
    records = [item for item in records if not (item.get("kind") == kind and item.get("id") == identifier)]
    records.append(entry)
    index = {
        "schema_version": WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION,
        "updated_at": entry["updated_at"],
        "records": records[-LEARNING_INDEX_MAX_RECORDS:],
    }
    atomic_write_json(paths.learning_index_path, index, private=True)


def _empty_learning_index() -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION,
        "updated_at": "",
        "records": [],
    }


def _learning_index_from_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION,
        "updated_at": utc_now(),
        "records": sorted(entries, key=lambda item: (item["kind"], item["id"]))[-LEARNING_INDEX_MAX_RECORDS:],
    }


def _scan_learning_records(paths: OmhPaths) -> dict[str, Any]:
    specs = [
        ("trace", paths.learning_traces_dir, validate_workflow_learning_trace),
        ("eval", paths.learning_evals_dir, validate_workflow_eval_result),
        ("candidate", paths.learning_candidates_dir, validate_improvement_candidate),
        ("patch_proposal", paths.learning_patch_proposals_dir, validate_improvement_patch_proposal),
        ("regression_case", paths.learning_regressions_dir, validate_regression_case),
    ]
    entries: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    counts = {kind: 0 for kind, _, _ in specs}
    for kind, directory, validator in specs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                record = read_json_object(path)
                if not record:
                    raise WorkflowLearningError("record is empty")
                validator(record)
                identifier = _record_identifier(record, kind)
                if not identifier:
                    raise WorkflowLearningError(f"{kind} record is missing its identifier")
                entries.append(_index_entry(record, kind, path=path))
                counts[kind] += 1
            except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError) as exc:
                invalid.append({"kind": kind, "path": str(path), "error": str(exc)})
    return {
        "entries": entries,
        "counts": counts,
        "invalid_records": invalid,
    }


def _index_entry(
    record: dict[str, Any],
    kind: str,
    *,
    updated_at: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    identifier = _record_identifier(record, kind)
    entry = {
        "kind": kind,
        "id": identifier,
        "schema_version": str(record.get("schema_version", "")),
        "updated_at": updated_at or str(record.get("updated_at") or record.get("created_at") or ""),
        "ref": _record_ref(kind, identifier),
    }
    if path is not None:
        entry["path"] = str(path)
    return entry


def _normal_index_entry(entry: dict[str, Any]) -> dict[str, str]:
    return {
        "kind": str(entry.get("kind", "")),
        "id": str(entry.get("id", "")),
        "schema_version": str(entry.get("schema_version", "")),
        "ref": str(entry.get("ref", "")),
    }


def _learning_index_check_payload(
    paths: OmhPaths,
    *,
    scanned: dict[str, Any],
    current_records: list[dict[str, str]],
    status: str | None = None,
    schema_error: str = "",
) -> dict[str, Any]:
    expected_records = [_normal_index_entry(entry) for entry in scanned["entries"]]
    current_keys = {(item["kind"], item["id"]) for item in current_records if item["kind"] and item["id"]}
    expected_keys = {(item["kind"], item["id"]) for item in expected_records if item["kind"] and item["id"]}
    missing = [item for item in expected_records if (item["kind"], item["id"]) not in current_keys]
    extra = [item for item in current_records if (item["kind"], item["id"]) not in expected_keys]
    schema_mismatches = [
        expected
        for expected in expected_records
        for current in current_records
        if expected["kind"] == current["kind"]
        and expected["id"] == current["id"]
        and expected["schema_version"] != current["schema_version"]
    ]
    if status is None:
        if scanned["invalid_records"]:
            status = "failed"
        elif missing or extra or schema_mismatches:
            status = "stale"
        else:
            status = "passed"
    return {
        "schema_version": "workflow_learning_index_check/v1",
        "status": status,
        "ok": status in {"passed", "no_records"},
        "index_path": str(paths.learning_index_path),
        "counts": scanned["counts"],
        "records_total": len(expected_records),
        "current_records_total": len(current_records),
        "missing_records": missing,
        "extra_records": extra,
        "schema_mismatches": schema_mismatches,
        "invalid_records": scanned["invalid_records"],
        "schema_error": schema_error,
        "repair_hint": (
            "Run `omh learning index rebuild` to rewrite the local learning index."
            if status in {"missing", "stale", "failed"}
            else ""
        ),
        "claim_boundary": "Index checks validate local metadata pointers only; they do not prove workflow execution or skill improvement.",
    }


def _classify_self_improvement_store(signal_text: str) -> dict[str, Any]:
    text = _normalize_store_signal(signal_text)
    matches: list[tuple[str, str]] = []
    if not text:
        return _self_improvement_classification(
            "manual_review_candidate",
            ["ambiguous_or_empty_signal"],
            [],
        )
    if _store_signal_contains_any(text, _PRIVATE_OR_RAW_SIGNAL_TERMS):
        matches.append(("discard_transient", "private_or_raw_content"))
    if _store_signal_contains_any(text, _TRANSIENT_SIGNAL_TERMS):
        matches.append(("discard_transient", "transient_local_state"))
    if _has_automation_store_signal(text):
        matches.append(("automation_suggestion_candidate", "recurring_automation"))
    if _store_signal_contains_any(text, _WIKI_SIGNAL_TERMS):
        matches.append(("wiki_candidate", "source_backed_knowledge"))
    if _store_signal_contains_any(text, _FAILURE_SIGNAL_TERMS):
        matches.append(("failure_retrospective_candidate", "failure_or_regression"))
    if _has_skill_store_signal(text):
        matches.append(("skill_update_candidate", "workflow_behavior"))
    if _store_signal_contains_any(text, _MEMORY_SIGNAL_TERMS):
        matches.append(("memory_candidate", "user_preference"))
    if not matches:
        return _self_improvement_classification(
            "manual_review_candidate",
            ["ambiguous_or_empty_signal"],
            [],
        )
    destination = _prioritized_store_destination(matches)
    reasons = [reason for matched_destination, reason in matches if matched_destination == destination]
    alternatives = _unique_destinations(
        matched_destination for matched_destination, _reason in matches if matched_destination != destination
    )
    return _self_improvement_classification(destination, reasons, alternatives)


def _self_improvement_classification(
    destination: str,
    reasons: list[str],
    alternatives: list[str],
) -> dict[str, Any]:
    details = SELF_IMPROVEMENT_DESTINATION_DETAILS[destination]
    return {
        "destination": destination,
        "confidence": str(details["confidence"]),
        "target_workflow": str(details["target_workflow"]),
        "target_record_type": str(details["target_record_type"]),
        "next_action": str(details["next_action"]),
        "routing_reasons": reasons,
        "alternative_destinations": alternatives,
    }


def _prioritized_store_destination(matches: list[tuple[str, str]]) -> str:
    destinations = {destination for destination, _reason in matches}
    for destination in SELF_IMPROVEMENT_DESTINATION_PRIORITY:
        if destination in destinations:
            return destination
    return matches[0][0]


def _unique_destinations(destinations: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for destination in destinations:
        text = str(destination)
        if text and text not in unique:
            unique.append(text)
    return unique


def _has_automation_store_signal(text: str) -> bool:
    return _store_signal_contains_any(text, _AUTOMATION_RECURRING_TERMS) and _store_signal_contains_any(
        text,
        _AUTOMATION_ACTION_TERMS,
    )


def _has_skill_store_signal(text: str) -> bool:
    return _store_signal_contains_any(text, _SKILL_SIGNAL_TERMS) and _store_signal_contains_any(
        text,
        _SKILL_BEHAVIOR_TERMS,
    )


def _normalize_store_signal(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _store_signal_contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text for term in terms)


def _safe_store_route_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or "").strip())[:80]


def _record_ref(kind: str, identifier: str) -> str:
    if kind == "trace":
        return learning_trace_ref(identifier)
    return f"omh-learning-{kind}:{identifier}"


def _record_identifier(record: dict[str, Any], kind: str) -> str:
    if kind == "trace":
        return str(record.get("trace_id", ""))
    if kind == "eval":
        return str(record.get("eval_id", ""))
    if kind == "candidate":
        return str(record.get("candidate_id", ""))
    if kind == "patch_proposal":
        return str(record.get("proposal_id", ""))
    if kind == "regression_case":
        return str(record.get("case_id", ""))
    return str(record.get("id", ""))


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "workflow_learning_trace_summary/v1",
        "trace_id": trace.get("trace_id", ""),
        "created_at": trace.get("created_at", ""),
        "source_kind": _nested(trace, "source", "kind"),
        "source": _nested(trace, "source", "source"),
        "selected_workflow": _nested(trace, "workflow", "selected_workflow"),
        "selected_harness": _nested(trace, "workflow", "selected_harness"),
        "evidence_state": _nested(trace, "status", "evidence_state"),
        "outcome": _nested(trace, "status", "outcome"),
        "learning_trace_ref": learning_trace_ref(str(trace.get("trace_id", ""))),
    }


def _id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "-", value).strip("-")[:120] or "record"


def _first_nonempty(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return ""


def _first_sentence(value: str) -> str:
    return value.split(".", 1)[0].strip() if value else ""


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _nested(data: object, *keys: str) -> object:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current


def _safe_metadata(value: dict[str, Any]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, raw in value.items():
        key_text = str(key)
        if key_text.startswith("raw") or key_text in FORBIDDEN_TRACE_KEYS:
            continue
        safe[key_text] = str(raw)
    return safe


def _require_schema(payload: dict[str, Any], expected: str) -> None:
    if payload.get("schema_version") != expected:
        raise WorkflowLearningError(f"expected {expected}")


def _require_string(payload: dict[str, Any], key: str) -> None:
    if not isinstance(payload.get(key), str) or not payload[key]:
        raise WorkflowLearningError(f"{key} is required")


def _reject_forbidden_payload_keys(value: object, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_TRACE_KEYS:
                raise WorkflowLearningError(f"learning trace contains forbidden raw field: {path + key_text}")
            _reject_forbidden_payload_keys(child, path=f"{path}{key_text}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_payload_keys(child, path=f"{path}{index}.")


def _reject_self_improvement_raw_payload_keys(value: object, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            current_path = f"{path}{key_text}"
            normalized = re.sub(r"[^a-z0-9]+", "", key_text.casefold())
            if current_path == _SELF_IMPROVEMENT_ALLOWED_RAW_TEXT_STORED_PATH:
                if child is not False:
                    raise WorkflowLearningError(
                        f"self-improvement store routing contains invalid raw flag: {current_path}"
                    )
            elif normalized.startswith("raw") or normalized in _SELF_IMPROVEMENT_FORBIDDEN_NORMALIZED_PAYLOAD_KEYS:
                raise WorkflowLearningError(f"self-improvement store routing contains forbidden raw field: {current_path}")
            _reject_self_improvement_raw_payload_keys(child, path=f"{current_path}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_self_improvement_raw_payload_keys(child, path=f"{path}{index}.")


def _sanitize_export_record(value: object) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if _is_export_raw_payload_key(key_text):
                continue
            sanitized[key_text] = _sanitize_export_record(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_export_record(item) for item in value]
    return value


def _reject_export_payload_keys(value: object, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if _is_export_raw_payload_key(key_text):
                raise WorkflowLearningError(f"learning export contains forbidden raw field: {path + key_text}")
            _reject_export_payload_keys(child, path=f"{path}{key_text}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_export_payload_keys(child, path=f"{path}{index}.")


def _is_export_raw_payload_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", key.lower())
    allowed = {re.sub(r"[^a-z0-9]+", "", item.lower()) for item in EXPORT_ALLOWED_RAW_FLAG_KEYS}
    forbidden = {re.sub(r"[^a-z0-9]+", "", item.lower()) for item in EXPORT_FORBIDDEN_PAYLOAD_KEYS}
    if normalized in allowed:
        return False
    return normalized in forbidden or normalized.startswith("raw")


from .self_improvement_routes import (  # noqa: E402
    build_self_improvement_store_route_record,
    list_self_improvement_store_routes,
    review_self_improvement_store_route,
    self_improvement_store_route_path,
    self_improvement_store_route_ref,
    show_self_improvement_store_route,
    validate_self_improvement_store_route_record,
    write_self_improvement_store_route,
)
