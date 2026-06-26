from __future__ import annotations

import hashlib
import re
from typing import Any


CONTEXT_ARTIFACT_REF_SCHEMA_VERSION = "omh_context_artifact_ref/v1"
PROGRESS_EVENT_SCHEMA_VERSION = "omh_progress_event/v1"
CODING_PROGRESS_REPORTING_POLICY_SCHEMA_VERSION = "coding_progress_reporting_policy/v1"
MAX_VISIBLE_MESSAGE_CHARS = 180
MAX_SUMMARY_CHARS = 240
MAX_PROGRESS_EVENT_SUMMARY_CHARS = 220
MAX_PROGRESS_EVENTS = 6
MAX_SOURCE_REF_CHARS = 240
MAX_EVIDENCE_REFS = 8
MAX_EVIDENCE_REF_CHARS = 160
MAX_ARTIFACT_REFS = 4

_BACKGROUND_PROCESS_WRAPPER_RE = re.compile(
    r"\[?\s*\bBackground\s+process\s+\S+\s+finished\s+with\s+exit\s+code\s+\d+~?\s+"
    r"Here'?s\s+the\s+final\s+output:?\s*\]?",
    re.IGNORECASE,
)
_BACKGROUND_PROCESS_COMPLETION_LINE_RE = re.compile(
    r"^\[?\s*\bBackground\s+process\s+\S+\s+finished\s+with\s+exit\s+code\s+\d+~?\s*\]?\s*$",
    re.IGNORECASE,
)
_FINAL_OUTPUT_HEADER_LINE_RE = re.compile(r"^Here'?s\s+the\s+final\s+output:?$", re.IGNORECASE)
_FINAL_OUTPUT_HEADER_PREFIX_RE = re.compile(r"^\[?\s*Here'?s\s+the\s+final\s+output:?\s*\]?\s*", re.IGNORECASE)
_RAW_CODEX_JSONL_RE = re.compile(
    r'"type"\s*:\s*"(?:turn|item)\.completed"'
    r'|"\w*usage\w*"\s*:'
    r'|"\w*(?:input|output|reasoning|cached)_tokens\w*"\s*:',
    re.IGNORECASE,
)
_SELF_IMPROVEMENT_REVIEW_RE = re.compile(r"\bSelf-improvement\s+review\s*:", re.IGNORECASE)

CODING_PROGRESS_REPORTABLE_EVENTS = (
    "workflow_started",
    "dispatch_to_executor",
    "blocker_encountered",
    "targeted_tests_failed",
    "root_cause_identified",
    "fix_strategy_selected",
    "targeted_tests_passed",
    "full_tests_started",
    "full_tests_passed",
    "commit_created",
    "pr_updated",
    "workflow_completed",
)

_PROGRESS_EVENT_TYPES = {
    "status_update",
    "bug_discovered",
    "failure_discovered",
    "root_cause_identified",
    "fix_strategy_selected",
    "files_area_chosen",
    "targeted_tests_started",
    "targeted_tests_passed",
    "targeted_tests_failed",
    "full_tests_started",
    "full_tests_passed",
    "full_tests_failed",
    "commit_created",
    "pr_created",
    "pr_updated",
    "dispatch_to_executor",
    "blocker_encountered",
    "workflow_started",
    "workflow_completed",
}
_PROGRESS_EVENT_STATUSES = {"prepared", "observed", "running", "passed", "failed", "blocked"}
_PROGRESS_EVENT_SEVERITIES = {"info", "success", "warning", "error", "blocked"}


def compact_visible_text(value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3]}..."


def sanitize_user_facing_progress_text(value: Any, *, max_chars: int | None = None) -> str:
    """Drop raw process/JSONL maintenance noise from chat-facing progress copy."""
    text = str(value)
    if not text.strip():
        return ""
    clean_lines: list[str] = []
    for raw_line in text.splitlines() or [text]:
        line = raw_line.strip()
        if not line:
            continue
        if _raw_jsonl_or_self_review_noise_line(line):
            continue
        line = _BACKGROUND_PROCESS_WRAPPER_RE.sub(" ", line).strip()
        line = _FINAL_OUTPUT_HEADER_PREFIX_RE.sub("", line).strip()
        if _raw_progress_noise_line(line):
            continue
        clean_lines.append(line)
    cleaned = re.sub(r"\s+", " ", " ".join(clean_lines)).strip()
    if not cleaned:
        return ""
    if max_chars is None:
        return cleaned
    return compact_visible_text(cleaned, max_chars=max_chars)


def is_user_facing_progress_noise(value: Any) -> bool:
    text = str(value)
    return bool(text.strip()) and not sanitize_user_facing_progress_text(text)


def _raw_progress_noise_line(line: str) -> bool:
    return bool(
        _BACKGROUND_PROCESS_WRAPPER_RE.search(line)
        or _BACKGROUND_PROCESS_COMPLETION_LINE_RE.search(line)
        or _FINAL_OUTPUT_HEADER_LINE_RE.search(line)
        or _raw_jsonl_or_self_review_noise_line(line)
    )


def _raw_jsonl_or_self_review_noise_line(line: str) -> bool:
    return bool(_RAW_CODEX_JSONL_RE.search(line) or _SELF_IMPROVEMENT_REVIEW_RE.search(line))


def compact_context_refs(
    values: Any,
    *,
    max_items: int = MAX_EVIDENCE_REFS,
    max_chars: int = MAX_EVIDENCE_REF_CHARS,
) -> tuple[list[str], int]:
    if not isinstance(values, (list, tuple)):
        return [], 0
    seen: list[str] = []
    omitted = 0
    for value in values:
        text = compact_visible_text(value, max_chars=max_chars)
        if not text:
            continue
        if text in seen:
            continue
        if len(seen) >= max_items:
            omitted += 1
            continue
        seen.append(text)
    return seen, omitted


def build_progress_event(
    event_type: str,
    summary: Any,
    *,
    status: str = "observed",
    severity: str = "info",
    file_refs: list[str] | tuple[str, ...] | None = None,
    artifact_refs: list[object] | tuple[object, ...] | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    compact_files, omitted_files = compact_context_refs(file_refs or [])
    compact_evidence, omitted_evidence = compact_context_refs(evidence_refs or [])
    compact_artifacts, omitted_artifacts = _compact_artifact_refs(artifact_refs or [])
    return {
        "schema_version": PROGRESS_EVENT_SCHEMA_VERSION,
        "event_type": _normalize_progress_event_type(event_type),
        "status": _normalize_choice(status, _PROGRESS_EVENT_STATUSES, "observed"),
        "severity": _normalize_choice(severity, _PROGRESS_EVENT_SEVERITIES, "info"),
        "summary": compact_visible_text(
            sanitize_user_facing_progress_text(_strip_code_fences(summary))
            or "Progress observed; raw process output stayed in artifacts.",
            max_chars=MAX_PROGRESS_EVENT_SUMMARY_CHARS,
        ),
        "file_refs": compact_files,
        "artifact_refs": compact_artifacts,
        "evidence_refs": compact_evidence,
        "omitted": {
            "file_ref_count": omitted_files,
            "artifact_ref_count": omitted_artifacts,
            "evidence_ref_count": omitted_evidence,
            "max_summary_chars": MAX_PROGRESS_EVENT_SUMMARY_CHARS,
            "max_artifact_refs": MAX_ARTIFACT_REFS,
            "max_evidence_refs": MAX_EVIDENCE_REFS,
        },
        "context_policy": "event_triggered_summary_only",
        "raw_content_included": False,
        "claim_boundary": (
            "This progress event is a compact wrapper/status update. It is not execution, review, CI, "
            "merge-readiness, merge, or raw-log evidence unless separate observed evidence records say so."
        ),
    }


def build_coding_progress_reporting_policy(
    *,
    next_action: str = "",
    lifecycle_status: str = "",
) -> dict[str, object]:
    return {
        "schema_version": CODING_PROGRESS_REPORTING_POLICY_SCHEMA_VERSION,
        "mode": "event_triggered",
        "metadata_only": True,
        "raw_content_included": False,
        "timed_polling_rejected": True,
        "final_only_silence_rejected": True,
        "raw_log_dumping_rejected": True,
        "reportable_events": list(CODING_PROGRESS_REPORTABLE_EVENTS),
        "state_guidance": {
            "next_action": _normalize_token(next_action),
            "lifecycle_status": _normalize_token(lifecycle_status),
            "reportable_events": _coding_state_reportable_events(next_action),
        },
        "language_policy": {
            "style": "concise",
            "mirror_chat_language": True,
            "korean_friendly": True,
        },
        "evidence_boundary": (
            "Progress reports are concise lifecycle/status updates only. They are not execution, review, CI, "
            "merge-readiness, or merge proof unless matching observed records exist."
        ),
        "forbidden_patterns": [
            "final_only_silence_for_long_running_executor_work",
            "raw_log_dumping",
            "claiming_execution_review_ci_or_merge_without_observed_records",
        ],
    }


def _coding_state_reportable_events(next_action: str) -> list[str]:
    normalized = _normalize_token(next_action)
    events_by_next_action = {
        "dispatch_to_executor": [
            "workflow_started",
            "dispatch_to_executor",
        ],
        "wait_for_executor_evidence": [
            "blocker_encountered",
            "targeted_tests_failed",
            "root_cause_identified",
            "fix_strategy_selected",
            "targeted_tests_passed",
        ],
        "surface_executor_blocker": [
            "blocker_encountered",
            "targeted_tests_failed",
        ],
        "record_verification_evidence": [
            "targeted_tests_passed",
            "full_tests_started",
        ],
        "record_review_evidence": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
        ],
        "record_ci_evidence": [
            "full_tests_passed",
            "pr_updated",
        ],
        "record_merge_readiness": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
        ],
        "report_completion_with_evidence": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
            "workflow_completed",
        ],
        "report_merge_ready": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
            "workflow_completed",
        ],
        "report_merged": [
            "workflow_completed",
        ],
    }
    return list(events_by_next_action.get(normalized, ["workflow_started"]))


def compact_progress_events(
    events: Any,
    *,
    max_items: int = MAX_PROGRESS_EVENTS,
) -> tuple[list[dict[str, object]], int]:
    if not isinstance(events, (list, tuple)):
        return [], 0
    compacted: list[dict[str, object]] = []
    omitted = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        if len(compacted) >= max_items:
            omitted += 1
            continue
        compacted.append(
            build_progress_event(
                str(event.get("event_type", "status_update")),
                event.get("summary", ""),
                status=str(event.get("status", "observed")),
                severity=str(event.get("severity", "info")),
                file_refs=event.get("file_refs", []) if isinstance(event.get("file_refs", []), list) else [],
                artifact_refs=event.get("artifact_refs", []) if isinstance(event.get("artifact_refs", []), list) else [],
                evidence_refs=event.get("evidence_refs", []) if isinstance(event.get("evidence_refs", []), list) else [],
            )
        )
    return compacted, omitted


def context_budget_payload() -> dict[str, object]:
    return {
        "schema_version": "omh_context_budget/v1",
        "max_visible_message_chars": MAX_VISIBLE_MESSAGE_CHARS,
        "max_summary_chars": MAX_SUMMARY_CHARS,
        "max_progress_event_summary_chars": MAX_PROGRESS_EVENT_SUMMARY_CHARS,
        "max_progress_events": MAX_PROGRESS_EVENTS,
        "max_evidence_refs": MAX_EVIDENCE_REFS,
        "max_evidence_ref_chars": MAX_EVIDENCE_REF_CHARS,
        "raw_output_policy": "store_raw_output_as_artifact_and_inject_refs_and_summary_only",
    }


def raw_output_artifact_ref(
    text: str,
    *,
    source: str,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    omitted_evidence_ref_count: int = 0,
) -> dict[str, object]:
    compact_refs, extra_omitted = compact_context_refs(evidence_refs or [])
    encoded = text.encode("utf-8")
    return {
        "schema_version": CONTEXT_ARTIFACT_REF_SCHEMA_VERSION,
        "source": compact_visible_text(source or "stdin", max_chars=MAX_SOURCE_REF_CHARS),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
        "line_count": len(text.splitlines()),
        "evidence_refs": compact_refs,
        "omitted_evidence_ref_count": omitted_evidence_ref_count + extra_omitted,
        "storage_policy": "store_raw_output_as_artifact",
        "in_context_policy": "refs_and_summary_only",
        "raw_content_included": False,
        "claim_boundary": "Raw output should stay in artifacts; Hermes context receives only this reference and bounded summaries.",
    }


def _normalize_progress_event_type(value: str) -> str:
    normalized = _normalize_token(value)
    return normalized if normalized in _PROGRESS_EVENT_TYPES else "status_update"


def _normalize_choice(value: str, allowed: set[str], fallback: str) -> str:
    normalized = _normalize_token(value)
    return normalized if normalized in allowed else fallback


def _normalize_token(value: str) -> str:
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def _strip_code_fences(value: Any) -> str:
    return str(value).replace("```", " ")


def _compact_artifact_refs(values: list[object] | tuple[object, ...]) -> tuple[list[dict[str, object]], int]:
    compacted: list[dict[str, object]] = []
    omitted = 0
    for value in values:
        if len(compacted) >= MAX_ARTIFACT_REFS:
            omitted += 1
            continue
        artifact = _compact_artifact_ref(value)
        if artifact:
            compacted.append(artifact)
    return compacted, omitted


def _compact_artifact_ref(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        artifact = {
            "schema_version": compact_visible_text(value.get("schema_version", CONTEXT_ARTIFACT_REF_SCHEMA_VERSION), max_chars=80),
            "source": compact_visible_text(value.get("source", ""), max_chars=MAX_SOURCE_REF_CHARS),
            "sha256": compact_visible_text(value.get("sha256", ""), max_chars=80),
            "byte_count": max(0, int(value.get("byte_count", 0) or 0)),
            "line_count": max(0, int(value.get("line_count", 0) or 0)),
            "storage_policy": compact_visible_text(value.get("storage_policy", "store_raw_output_as_artifact"), max_chars=80),
            "in_context_policy": compact_visible_text(value.get("in_context_policy", "refs_and_summary_only"), max_chars=80),
            "raw_content_included": False,
        }
        return {key: item for key, item in artifact.items() if not _empty_artifact_field(item)}
    source = compact_visible_text(value, max_chars=MAX_SOURCE_REF_CHARS)
    if not source:
        return {}
    return {
        "schema_version": CONTEXT_ARTIFACT_REF_SCHEMA_VERSION,
        "source": source,
        "storage_policy": "store_raw_output_as_artifact",
        "in_context_policy": "refs_and_summary_only",
        "raw_content_included": False,
    }


def _empty_artifact_field(value: object) -> bool:
    return not isinstance(value, bool) and value in ("", 0)
