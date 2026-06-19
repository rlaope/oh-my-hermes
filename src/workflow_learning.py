from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .local_store import atomic_write_json, ensure_dir, read_json_object, utc_now
from .paths import OmhPaths
from .runtime.artifacts import show_run


WORKFLOW_LEARNING_TRACE_SCHEMA_VERSION = "workflow_learning_trace/v1"
WORKFLOW_EVAL_RESULT_SCHEMA_VERSION = "workflow_eval_result/v1"
IMPROVEMENT_CANDIDATE_SCHEMA_VERSION = "improvement_candidate/v1"
REGRESSION_CASE_SCHEMA_VERSION = "regression_case/v1"
WORKFLOW_LEARNING_INDEX_SCHEMA_VERSION = "workflow_learning_index/v1"
WORKFLOW_LEARNING_EXPORT_SCHEMA_VERSION = "workflow_learning_export/v1"
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
_OBSERVED_STATES = {"observed", "verified", "complete", "completed", "ready", "merged"}
_LEARNING_OUTCOMES = {"unknown", "useful", "not_useful", "blocked", "failed"}


class WorkflowLearningError(ValueError):
    pass


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
        explanation.get("selected_workflow"),
        usage_trace.get("selected_workflow"),
        state.get("selected_workflow"),
        route.get("selected_skill"),
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


def write_workflow_eval(paths: OmhPaths, result: dict[str, Any]) -> dict[str, Any]:
    validate_workflow_eval_result(result)
    atomic_write_json(eval_path(paths, str(result["eval_id"])), result, private=True)
    _update_learning_index(paths, result, "eval")
    return result


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
    validate_improvement_candidate(candidate)
    return candidate


def write_improvement_candidate(paths: OmhPaths, candidate: dict[str, Any]) -> dict[str, Any]:
    validate_improvement_candidate(candidate)
    atomic_write_json(candidate_path(paths, str(candidate["candidate_id"])), candidate, private=True)
    _update_learning_index(paths, candidate, "candidate")
    return candidate


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
            "source_regression_case_count": len(regression_cases),
            "canonical_learning_index_includes_exports": False,
            "source_payloads_projected": True,
        },
        "summary": _learning_export_summary(
            traces=traces,
            evals=evals,
            candidates=candidates,
            regression_cases=regression_cases,
        ),
        "study_cards": [
            _learning_study_card(
                trace,
                evals=[record for record in evals if record.get("trace_id") == trace.get("trace_id")],
                candidates=[record for record in candidates if record.get("trace_id") == trace.get("trace_id")],
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
            "regression_cases": regression_cases,
        },
        "operator_notes": [
            "Use this bundle to review process quality, routing decisions, evidence gaps, and improvement candidates.",
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


def validate_improvement_candidate(candidate: dict[str, Any]) -> None:
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


def trace_path(paths: OmhPaths, trace_id: str) -> Path:
    return paths.learning_traces_dir / f"{_safe_id(trace_id)}.json"


def eval_path(paths: OmhPaths, eval_id: str) -> Path:
    return paths.learning_evals_dir / f"{_safe_id(eval_id)}.json"


def candidate_path(paths: OmhPaths, candidate_id: str) -> Path:
    return paths.learning_candidates_dir / f"{_safe_id(candidate_id)}.json"


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
    regression_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "counts": {
            "traces": len(traces),
            "evals": len(evals),
            "candidates": len(candidates),
            "regression_cases": len(regression_cases),
        },
        "workflows": sorted({str(_nested(trace, "workflow", "selected_workflow")) for trace in traces if _nested(trace, "workflow", "selected_workflow")}),
        "evidence_states": sorted({str(_nested(trace, "status", "evidence_state")) for trace in traces if _nested(trace, "status", "evidence_state")}),
        "outcomes": sorted({str(_nested(trace, "status", "outcome")) for trace in traces if _nested(trace, "status", "outcome")}),
        "eval_statuses": sorted({str(result.get("status", "")) for result in evals if result.get("status")}),
        "candidate_statuses": sorted({str(candidate.get("status", "")) for candidate in candidates if candidate.get("status")}),
    }


def _learning_study_card(
    trace: dict[str, Any],
    *,
    evals: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
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
    from .wrapper.contract import build_chat_interaction_payload

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
