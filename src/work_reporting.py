from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .context_safety import (
    MAX_EVIDENCE_REFS,
    MAX_PROGRESS_EVENTS,
    compact_context_refs,
    compact_progress_events,
    compact_visible_text,
)


WORK_OBSERVATION_SUMMARY_SCHEMA_VERSION = "work_observation_summary/v1"
WORK_REPORT_MARKDOWN_EXPORT_SCHEMA_VERSION = "work_report_markdown_export/v1"
WORK_OBSERVATION_EVENT_REF_SCHEMA_VERSION = "work_observation_event_ref/v1"
REPORT_KINDS = ("progress", "completion", "blocker", "status")
REPORT_STATUSES = ("prepared_not_observed", "in_progress", "completed", "blocked", "failed", "unknown")
MAX_TITLE_CHARS = 120
MAX_LEARNING_NOTE_CHARS = 180
MAX_BLOCKERS = 5
MAX_OBSERVATION_EVENTS = 12
_DEFAULT_NOT_EVIDENCE = (
    "prepared_not_observed",
    "execution",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
    "raw logs",
)
_FORBIDDEN_RAW_KEYS = {
    "message",
    "source_message",
    "raw_message",
    "prompt",
    "raw_prompt",
    "prompt_body",
    "body_text",
    "raw_text",
    "raw_logs",
    "stdout",
    "stderr",
    "transcript",
    "conversation",
}
_POST_PREPARED_NEXT_ACTIONS = {
    "wait_for_executor_evidence",
    "record_verification_evidence",
    "record_review_evidence",
    "record_ci_evidence",
    "record_merge_readiness",
}
_VERIFICATION_SUCCESS_STATUSES = {"passed", "satisfied", "completed", "verified"}
_NON_PROGRESS_STATUSES = {"", "not_observed", "not_required", "pending"}
_OBSERVATION_EVENT_STATUSES = ("observed", "blocked", "failed", "not_observed")
_OBSERVATION_EVENT_EVIDENCE_STATUSES = {"observed", "blocked", "failed"}


def build_work_observation_summary(
    *,
    work_id: str,
    title: str,
    report_kind: str = "status",
    status: str = "unknown",
    workflow: str = "",
    harness: str = "",
    owner: str = "hermes",
    source_kind: str = "work",
    source_ref: str = "",
    source_message: str = "",
    source_metadata: dict[str, Any] | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    prepared_refs: list[str] | tuple[str, ...] | None = None,
    artifact_refs: list[str] | tuple[str, ...] | None = None,
    observed_events: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    progress_events: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    blockers: list[str] | tuple[str, ...] | None = None,
    next_action: str = "",
    safe_summary: str = "",
    not_evidence_until_observed: list[str] | tuple[str, ...] | None = None,
    learning_candidate: bool = False,
    learning_notes: str = "",
    updated_at: str = "",
) -> dict[str, Any]:
    """Build a metadata-only summary for Hermes-facing work reports."""

    event_evidence_refs = _event_evidence_refs(observed_events or [])
    compact_evidence, omitted_evidence = compact_context_refs([*(evidence_refs or []), *event_evidence_refs])
    compact_prepared, omitted_prepared = compact_context_refs(prepared_refs or [])
    compact_artifacts, omitted_artifacts = compact_context_refs(artifact_refs or [])
    compact_events, omitted_events = _compact_observation_events(observed_events or [])
    compact_progress, omitted_progress = compact_progress_events(progress_events or [])
    compact_blockers, omitted_blockers = _compact_strings(blockers or [], max_items=MAX_BLOCKERS, max_chars=180)
    boundary_items, omitted_boundary = compact_context_refs(
        [*_DEFAULT_NOT_EVIDENCE, *(not_evidence_until_observed or [])],
        max_items=16,
        max_chars=80,
    )
    report_kind = _choice(report_kind, REPORT_KINDS, "status")
    status = _choice(status, REPORT_STATUSES, "unknown")
    work_id = compact_visible_text(work_id or "unknown-work", max_chars=160)
    title = compact_visible_text(_strip_code_fences(title or "Work report"), max_chars=MAX_TITLE_CHARS)
    summary_ref = _summary_ref(work_id, title, report_kind, status)
    source = _source_summary(
        source_kind=source_kind,
        source_ref=source_ref,
        source_message=source_message,
        source_metadata=source_metadata or {},
    )
    summary = {
        "schema_version": WORK_OBSERVATION_SUMMARY_SCHEMA_VERSION,
        "record_type": "work_observation_summary",
        "summary_ref": summary_ref,
        "work_id": work_id,
        "title": title,
        "report_kind": report_kind,
        "status": status,
        "updated_at": compact_visible_text(updated_at, max_chars=80),
        "scope": {
            "workflow": _token(workflow or "unknown"),
            "harness": _token(harness or "unknown"),
            "owner": _token(owner or "hermes"),
        },
        "source": source,
        "privacy": {
            "mode": "metadata_only",
            "metadata_only": True,
            "raw_prompt_stored": False,
            "raw_message_stored": False,
            "raw_logs_stored": False,
            "raw_output_stored_in_summary": False,
            "stored_fields": [
                "work id",
                "message hash and length",
                "workflow and harness ids",
                "bounded evidence references",
                "bounded observation events",
                "bounded progress events",
                "claim boundaries",
            ],
        },
        "observations": {
            "schema_version": "work_observation_refs/v1",
            "observed_events": [event["event_type"] for event in compact_events if event["status"] == "observed"],
            "blocked_events": [event["event_type"] for event in compact_events if event["status"] == "blocked"],
            "failed_events": [event["event_type"] for event in compact_events if event["status"] == "failed"],
            "not_observed_events": [event["event_type"] for event in compact_events if event["status"] == "not_observed"],
            "events": compact_events,
            "evidence_refs": compact_evidence,
            "prepared_refs": compact_prepared,
            "artifact_refs": compact_artifacts,
            "raw_content_included": False,
            "omitted": {
                "event_count": omitted_events,
                "evidence_ref_count": omitted_evidence,
                "prepared_ref_count": omitted_prepared,
                "artifact_ref_count": omitted_artifacts,
            },
        },
        "progress": {
            "schema_version": "work_progress_digest/v1",
            "events": compact_progress,
            "latest_event": compact_progress[-1] if compact_progress else {},
            "safe_summary": compact_visible_text(_strip_code_fences(safe_summary), max_chars=240),
            "omitted": {
                "progress_event_count": omitted_progress,
                "max_progress_events": MAX_PROGRESS_EVENTS,
            },
        },
        "blockers": compact_blockers,
        "omitted_blocker_count": omitted_blockers,
        "next_action": _token(next_action or "show_status"),
        "evidence_boundary": {
            "schema_version": "work_evidence_boundary/v1",
            "not_evidence_until_observed": boundary_items,
            "omitted_not_evidence_count": omitted_boundary,
            "claim_boundary": (
                "This report summarizes metadata and observed references only. Prepared handoffs and summaries are not "
                "execution, verification, review, CI, merge-readiness, or merge evidence until matching observations exist."
            ),
        },
        "user_report": {
            "default_format": "plain_text",
            "json_default": False,
            "code_block_default": False,
            "plain_text_renderers": ["progress", "completion", "blocker", "status"],
            "machine_readable_payload": "internal_or_opt_in",
        },
        "exports": {
            "markdown": {
                "available": True,
                "default": False,
                "intended_surface": "wiki_or_markdown",
                "schema_version": WORK_REPORT_MARKDOWN_EXPORT_SCHEMA_VERSION,
            },
            "json": {
                "available": True,
                "default": False,
                "intended_surface": "api_debug_or_internal",
            },
        },
        "learning": _learning_hint(
            summary_ref=summary_ref,
            candidate=learning_candidate,
            workflow=workflow,
            harness=harness,
            notes=learning_notes,
            evidence_refs=compact_evidence,
            omitted_evidence_ref_count=omitted_evidence,
        ),
        "overclaim_guard": [
            "Plain text is the default user experience.",
            "Structured JSON is internal or opt-in.",
            "Markdown export is a durable knowledge surface, not the default chat report.",
            "Learning receives selected metadata-only summaries, not raw prompt or log dumps.",
        ],
    }
    errors = validate_work_observation_summary(summary)
    if errors:
        raise ValueError("; ".join(errors))
    return summary


def build_work_observation_summary_from_status(
    status_payload: dict[str, Any],
    *,
    report_kind: str = "status",
    title: str = "",
) -> dict[str, Any]:
    """Project an existing delegated/runtime status payload into the report contract."""

    prepared = _object(status_payload.get("prepared"))
    execution = _object(status_payload.get("execution"))
    verification = _object(status_payload.get("verification"))
    review = _object(status_payload.get("review"))
    ci = _object(status_payload.get("ci"))
    merge = _object(status_payload.get("merge"))
    runtime_observation = _object(status_payload.get("runtime_observation"))
    run_id = str(status_payload.get("run_id") or "unknown-run")
    status = _status_from_status_payload(status_payload)
    evidence_refs = [
        *_observed_stage_evidence_refs(execution),
        *_observed_stage_evidence_refs(verification),
        *_observed_stage_evidence_refs(review),
        *_observed_stage_evidence_refs(ci),
        *_observed_stage_evidence_refs(merge),
    ]
    observed_events = _runtime_observation_events(runtime_observation)
    progress_events = _string_items(status_payload.get("safe_summary"))
    return build_work_observation_summary(
        work_id=run_id,
        title=title or f"Work status for {run_id}",
        report_kind=report_kind,
        status=status,
        workflow=str(prepared.get("workflow") or status_payload.get("workflow") or "unknown"),
        harness=str(prepared.get("harness") or status_payload.get("harness") or "unknown"),
        source_kind="delegated_coding_status",
        source_ref=f"runtime:{run_id}",
        evidence_refs=evidence_refs,
        prepared_refs=[f"delegated_coding_status/v1:{run_id}"],
        observed_events=observed_events,
        progress_events=[
            {"event_type": "status_update", "status": "observed", "summary": item}
            for item in progress_events
        ],
        safe_summary=str(status_payload.get("safe_summary", "")),
        next_action=str(status_payload.get("next_action") or "show_status"),
        not_evidence_until_observed=[
            "execution" if execution.get("observed") is not True else "",
            "verification" if verification.get("observed") is not True else "",
            "review" if str(review.get("status", "not_observed")) in {"not_observed", "pending"} else "",
            "ci" if str(ci.get("status", "not_observed")) in {"not_observed", "pending"} else "",
            "merge" if str(merge.get("status", "not_observed")) in {"not_observed", "pending", "not_ready"} else "",
        ],
    )


def render_progress_report(summary: dict[str, Any]) -> str:
    validate = validate_work_observation_summary(summary)
    if validate:
        raise ValueError("; ".join(validate))
    title = str(summary["title"])
    status = _status_phrase(str(summary.get("status", "unknown")))
    lines = [f"Progress: {title} is {status}."]
    latest = _object(_object(summary.get("progress")).get("latest_event"))
    safe_summary = str(_object(summary.get("progress")).get("safe_summary", ""))
    if latest.get("summary"):
        lines.append(str(latest["summary"]))
    elif safe_summary:
        lines.append(safe_summary)
    lines.extend(_evidence_lines(summary))
    next_action = str(summary.get("next_action", "show_status"))
    if next_action:
        lines.append(f"Next: {next_action}.")
    lines.append(_boundary_line(summary))
    return _plain(lines)


def render_status_report(summary: dict[str, Any]) -> str:
    return render_progress_report(summary)


def render_completion_report(summary: dict[str, Any]) -> str:
    validate = validate_work_observation_summary(summary)
    if validate:
        raise ValueError("; ".join(validate))
    title = str(summary["title"])
    if summary.get("status") == "completed":
        lines = [f"Completed: {title}."]
    else:
        lines = [f"Completion is not observed yet for {title}."]
    observed = _string_items(_object(summary.get("observations")).get("observed_events"))
    if observed:
        lines.append(f"Observed: {', '.join(observed[:5])}.")
    lines.extend(_evidence_lines(summary))
    lines.append(_boundary_line(summary))
    return _plain(lines)


def render_blocker_report(summary: dict[str, Any]) -> str:
    validate = validate_work_observation_summary(summary)
    if validate:
        raise ValueError("; ".join(validate))
    title = str(summary["title"])
    blockers = _string_items(summary.get("blockers"))
    lines = [f"Blocked: {title}."]
    if blockers:
        lines.append(f"Reason: {'; '.join(blockers[:3])}.")
    else:
        lines.append("Reason: required evidence is not observed.")
    next_action = str(summary.get("next_action", "show_status"))
    if next_action:
        lines.append(f"Next: {next_action}.")
    lines.extend(_evidence_lines(summary))
    lines.append(_boundary_line(summary))
    return _plain(lines)


def build_markdown_export(summary: dict[str, Any]) -> dict[str, Any]:
    validate = validate_work_observation_summary(summary)
    if validate:
        raise ValueError("; ".join(validate))
    markdown = _markdown_for_summary(summary)
    export = {
        "schema_version": WORK_REPORT_MARKDOWN_EXPORT_SCHEMA_VERSION,
        "record_type": "work_report_markdown_export",
        "export_mode": "opt_in",
        "source_schema_version": summary["schema_version"],
        "source_summary_ref": summary["summary_ref"],
        "markdown": markdown,
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "raw_logs_stored": False,
        },
        "claim_boundary": "Markdown export is a secondary durable knowledge surface. It is not the default chat UX.",
    }
    errors = validate_markdown_export(export)
    if errors:
        raise ValueError("; ".join(errors))
    return export


def validate_markdown_export(export: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(export, dict):
        return ["markdown export must be an object"]
    _require(
        export.get("schema_version") == WORK_REPORT_MARKDOWN_EXPORT_SCHEMA_VERSION,
        errors,
        "schema_version must be work_report_markdown_export/v1",
    )
    _require(export.get("export_mode") == "opt_in", errors, "markdown export must be opt_in")
    _require(isinstance(export.get("markdown"), str), errors, "markdown export must include markdown text")
    _require("```" not in str(export.get("markdown", "")), errors, "markdown export must not use code fences")
    privacy = _object(export.get("privacy"))
    _require(privacy.get("mode") == "metadata_only", errors, "markdown export privacy mode must be metadata_only")
    _require(privacy.get("raw_prompt_stored") is False, errors, "markdown export must not store raw prompts")
    _require(privacy.get("raw_logs_stored") is False, errors, "markdown export must not store raw logs")
    _require("not the default" in str(export.get("claim_boundary", "")).lower(), errors, "markdown export boundary must be explicit")
    _reject_forbidden_raw_keys(export, errors)
    return errors


def validate_work_observation_summary(summary: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(summary, dict):
        return ["summary must be an object"]
    _require(summary.get("schema_version") == WORK_OBSERVATION_SUMMARY_SCHEMA_VERSION, errors, "schema_version must be work_observation_summary/v1")
    for key in ("record_type", "summary_ref", "work_id", "title", "report_kind", "status", "scope", "source", "privacy", "observations", "progress", "evidence_boundary", "user_report", "exports", "learning"):
        _require(key in summary, errors, f"missing {key}")
    _require(summary.get("report_kind") in REPORT_KINDS, errors, "report_kind is unsupported")
    _require(summary.get("status") in REPORT_STATUSES, errors, "status is unsupported")
    privacy = _object(summary.get("privacy"))
    _require(privacy.get("metadata_only") is True, errors, "privacy.metadata_only must be true")
    _require(privacy.get("raw_prompt_stored") is False, errors, "raw prompts must not be stored")
    _require(privacy.get("raw_logs_stored") is False, errors, "raw logs must not be stored")
    source = _object(summary.get("source"))
    sha = str(source.get("message_sha256", ""))
    if sha:
        _require(bool(re.fullmatch(r"[0-9a-f]{64}", sha)), errors, "source.message_sha256 must be sha256 hex")
    _require(source.get("raw_message_stored") is False, errors, "source raw message must not be stored")
    observations = _object(summary.get("observations"))
    _require(observations.get("raw_content_included") is False, errors, "observations must not include raw content")
    for key in ("evidence_refs", "prepared_refs", "artifact_refs", "events"):
        _require(isinstance(observations.get(key), list), errors, f"observations.{key} must be a list")
    boundary = _object(summary.get("evidence_boundary"))
    _require(isinstance(boundary.get("not_evidence_until_observed"), list), errors, "evidence boundary must list non-evidence")
    _require("not" in str(boundary.get("claim_boundary", "")).lower(), errors, "claim boundary must preserve non-evidence language")
    user_report = _object(summary.get("user_report"))
    _require(user_report.get("default_format") == "plain_text", errors, "default user report format must be plain_text")
    _require(user_report.get("json_default") is False, errors, "JSON must not be default user UX")
    _require(user_report.get("code_block_default") is False, errors, "code blocks must not be default user UX")
    exports = _object(summary.get("exports"))
    markdown = _object(exports.get("markdown"))
    _require(markdown.get("default") is False, errors, "markdown export must be opt-in")
    json_export = _object(exports.get("json"))
    _require(json_export.get("default") is False, errors, "json export must be opt-in")
    learning = _object(summary.get("learning"))
    _require(learning.get("raw_prompt_included") is False, errors, "learning hints must not include raw prompt")
    _require(learning.get("raw_logs_included") is False, errors, "learning hints must not include raw logs")
    _require(len(str(learning.get("notes", ""))) <= MAX_LEARNING_NOTE_CHARS, errors, "learning notes must be bounded")
    _require(len(_string_items(learning.get("evidence_refs"))) <= MAX_EVIDENCE_REFS, errors, "learning evidence refs must be bounded")
    _reject_forbidden_raw_keys(summary, errors)
    return errors


def _source_summary(
    *,
    source_kind: str,
    source_ref: str,
    source_message: str,
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    message = source_message or ""
    encoded = message.encode("utf-8")
    return {
        "kind": _token(source_kind or "work"),
        "source_ref": compact_visible_text(source_ref, max_chars=160),
        "message_sha256": hashlib.sha256(encoded).hexdigest() if message else "",
        "message_length": len(message),
        "source_metadata_keys": sorted(_token(key) for key in source_metadata.keys()),
        "raw_message_stored": False,
    }


def _learning_hint(
    *,
    summary_ref: str,
    candidate: bool,
    workflow: str,
    harness: str,
    notes: str,
    evidence_refs: list[str],
    omitted_evidence_ref_count: int,
) -> dict[str, Any]:
    compact_refs, extra_omitted = compact_context_refs(evidence_refs)
    return {
        "schema_version": "work_report_learning_hint/v1",
        "candidate": bool(candidate),
        "selection": "selected" if candidate else "not_selected",
        "summary_ref": summary_ref,
        "workflow": _token(workflow or "unknown"),
        "harness": _token(harness or "unknown"),
        "notes": compact_visible_text(_strip_code_fences(notes), max_chars=MAX_LEARNING_NOTE_CHARS),
        "evidence_refs": compact_refs,
        "raw_prompt_included": False,
        "raw_logs_included": False,
        "export_policy": "selected_sanitized_summary_only",
        "omitted": {
            "evidence_ref_count": omitted_evidence_ref_count + extra_omitted,
            "max_note_chars": MAX_LEARNING_NOTE_CHARS,
            "max_evidence_refs": MAX_EVIDENCE_REFS,
        },
        "claim_boundary": "Learning hints are candidates for later review; they are not skill patches or raw transcript exports.",
    }


def _compact_observation_events(events: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[list[dict[str, Any]], int]:
    compacted: list[dict[str, Any]] = []
    omitted = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        if len(compacted) >= MAX_OBSERVATION_EVENTS:
            omitted += 1
            continue
        status = _observation_event_status(event)
        refs = event.get("evidence_refs", []) if status in _OBSERVATION_EVENT_EVIDENCE_STATUSES else []
        evidence_refs, omitted_refs = compact_context_refs(refs)
        compacted.append(
            {
                "schema_version": WORK_OBSERVATION_EVENT_REF_SCHEMA_VERSION,
                "event_type": _token(str(event.get("event_type") or "status_update")),
                "status": status,
                "summary": compact_visible_text(_strip_code_fences(event.get("summary", "")), max_chars=180),
                "evidence_refs": evidence_refs,
                "raw_content_included": False,
                "omitted": {"evidence_ref_count": omitted_refs},
            }
        )
    return compacted, omitted


def _event_evidence_refs(events: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[str]:
    refs: list[str] = []
    for event in events:
        if isinstance(event, dict) and _observation_event_status(event) in _OBSERVATION_EVENT_EVIDENCE_STATUSES:
            refs.extend(_string_items(event.get("evidence_refs")))
    return refs


def _observation_event_status(event: dict[str, Any]) -> str:
    return _choice(str(event.get("status") or "observed"), _OBSERVATION_EVENT_STATUSES, "observed")


def _compact_strings(values: list[str] | tuple[str, ...], *, max_items: int, max_chars: int) -> tuple[list[str], int]:
    compacted: list[str] = []
    omitted = 0
    for value in values:
        text = compact_visible_text(_strip_code_fences(value), max_chars=max_chars)
        if not text:
            continue
        if len(compacted) >= max_items:
            omitted += 1
            continue
        compacted.append(text)
    return compacted, omitted


def _markdown_for_summary(summary: dict[str, Any]) -> str:
    observations = _object(summary.get("observations"))
    evidence_refs = _string_items(observations.get("evidence_refs"))
    prepared_refs = _string_items(observations.get("prepared_refs"))
    boundary = _string_items(_object(summary.get("evidence_boundary")).get("not_evidence_until_observed"))
    lines = [
        f"# {summary['title']}",
        "",
        f"- Work: {summary['work_id']}",
        f"- Status: {summary['status']}",
        f"- Report: {summary['report_kind']}",
        f"- Next: {summary.get('next_action', 'show_status')}",
        "",
        "## Summary",
        _plain([str(_object(summary.get("progress")).get("safe_summary") or _default_summary(summary))]),
        "",
        "## Evidence",
    ]
    lines.extend([f"- {item}" for item in evidence_refs] or ["- No evidence references recorded."])
    if prepared_refs:
        lines.extend(["", "## Prepared References", *[f"- {item}" for item in prepared_refs]])
    lines.extend(["", "## Evidence Boundary", *[f"- {item}" for item in boundary[:8]]])
    learning = _object(summary.get("learning"))
    if learning.get("candidate"):
        lines.extend(["", "## Learning Hint", f"- {learning.get('notes') or 'Selected metadata-only summary.'}"])
    return "\n".join(lines).strip() + "\n"


def _evidence_lines(summary: dict[str, Any]) -> list[str]:
    refs = _string_items(_object(summary.get("observations")).get("evidence_refs"))
    if not refs:
        return []
    return [f"Evidence: {', '.join(refs[:4])}."]


def _boundary_line(summary: dict[str, Any]) -> str:
    items = _string_items(_object(summary.get("evidence_boundary")).get("not_evidence_until_observed"))
    return f"Not evidence until observed: {', '.join(items[:5])}."


def _default_summary(summary: dict[str, Any]) -> str:
    latest = _object(_object(summary.get("progress")).get("latest_event"))
    if latest.get("summary"):
        return str(latest["summary"])
    return f"{summary.get('report_kind', 'status')} report for {summary.get('work_id', 'unknown-work')}."


def _plain(lines: list[str]) -> str:
    cleaned = [compact_visible_text(_strip_code_fences(line), max_chars=320) for line in lines if str(line).strip()]
    return "\n".join(cleaned).strip()


def _status_from_status_payload(status_payload: dict[str, Any]) -> str:
    prepared = _object(status_payload.get("prepared"))
    wrapper = _object(status_payload.get("wrapper"))
    execution = _object(status_payload.get("execution"))
    verification = _object(status_payload.get("verification"))
    review = _object(status_payload.get("review"))
    ci = _object(status_payload.get("ci"))
    merge = _object(status_payload.get("merge"))
    next_action = str(status_payload.get("next_action", ""))
    lifecycle = str(status_payload.get("lifecycle_status", ""))
    terminal_requested = lifecycle in {"reportable", "merge_ready", "merged"} or next_action in {
        "report_completion_with_evidence",
        "report_merge_ready",
        "report_merged",
    }
    failed_or_blocked = _failed_or_blocked_status(execution, verification, review, ci, merge)
    if failed_or_blocked:
        return failed_or_blocked
    if terminal_requested and _terminal_evidence_satisfied(execution, verification, review, ci, merge):
        return "completed"
    if next_action.startswith("surface_") or "blocker" in next_action:
        return "blocked"
    if str(prepared.get("status", "")) == "prepared_not_observed" and not _post_prepared_work_observed(
        next_action=next_action,
        wrapper=wrapper,
        execution=execution,
        verification=verification,
        review=review,
        ci=ci,
        merge=merge,
    ):
        return "prepared_not_observed"
    return "in_progress"


def _terminal_evidence_satisfied(
    execution: dict[str, Any],
    verification: dict[str, Any],
    review: dict[str, Any],
    ci: dict[str, Any],
    merge: dict[str, Any],
) -> bool:
    return (
        execution.get("observed") is True
        and str(execution.get("status", "")) == "completed"
        and _verification_satisfied(verification)
        and _gate_satisfied(review)
        and _gate_satisfied(ci)
        and _gate_satisfied(merge)
    )


def _verification_satisfied(verification: dict[str, Any]) -> bool:
    if verification.get("satisfied") is True:
        return True
    return verification.get("observed") is True and str(verification.get("status", "")) in _VERIFICATION_SUCCESS_STATUSES


def _gate_satisfied(stage: dict[str, Any]) -> bool:
    if not stage:
        return True
    if stage.get("satisfied") is True:
        return True
    required = stage.get("required") is True
    status = str(stage.get("status", ""))
    observed = stage.get("observed") is True
    if not required and status in {"", "not_required", "not_observed"}:
        return True
    return observed and status in {"passed", "ready", "merged"}


def _observed_stage_evidence_refs(stage: dict[str, Any]) -> list[str]:
    if not isinstance(stage, dict):
        return []
    if stage.get("observed") is True or stage.get("satisfied") is True:
        return _string_items(stage.get("evidence_refs"))
    return []


def _runtime_observation_events(runtime_observation: dict[str, Any]) -> list[dict[str, Any]]:
    latest = _object(runtime_observation.get("latest"))
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field, fallback_status in (
        ("observed_events", "observed"),
        ("blocked_events", "blocked"),
        ("failed_events", "failed"),
        ("not_observed_events", "not_observed"),
        ("missing_events", "not_observed"),
    ):
        for event_type in _string_items(runtime_observation.get(field)):
            event_key = _token(event_type)
            if event_key in seen:
                continue
            seen.add(event_key)
            events.append(_runtime_observation_event(latest, event_type, fallback_status))
    return events


def _runtime_observation_event(latest: dict[str, Any], event_type: str, fallback_status: str) -> dict[str, Any]:
    record = _object(latest.get(event_type))
    status = fallback_status if fallback_status == "not_observed" else str(record.get("status") or fallback_status)
    event: dict[str, Any] = {
        "event_type": str(record.get("event_type") or event_type),
        "status": status,
    }
    if record:
        event["summary"] = str(record.get("summary") or "")
        event["evidence_refs"] = _string_items(record.get("evidence_refs"))
    return event


def _failed_or_blocked_status(*stages: dict[str, Any]) -> str:
    blocked = False
    for stage in stages:
        status = str(stage.get("status", ""))
        if status == "failed":
            return "failed"
        if status == "blocked":
            blocked = True
    return "blocked" if blocked else ""


def _post_prepared_work_observed(
    *,
    next_action: str,
    wrapper: dict[str, Any],
    execution: dict[str, Any],
    verification: dict[str, Any],
    review: dict[str, Any],
    ci: dict[str, Any],
    merge: dict[str, Any],
) -> bool:
    if next_action in _POST_PREPARED_NEXT_ACTIONS:
        return True
    if wrapper.get("prompt_dispatched") is True or wrapper.get("hermes_response_observed") is True:
        return True
    return any(_stage_has_observed_progress(stage) for stage in (execution, verification, review, ci, merge))


def _stage_has_observed_progress(stage: dict[str, Any]) -> bool:
    if not stage:
        return False
    status = str(stage.get("status", ""))
    if status in _NON_PROGRESS_STATUSES:
        return False
    return stage.get("observed") is True or stage.get("satisfied") is True or bool(_string_items(stage.get("evidence_refs")))


def _status_phrase(status: str) -> str:
    return {
        "prepared_not_observed": "prepared but not observed",
        "in_progress": "in progress",
        "completed": "completed",
        "blocked": "blocked",
        "failed": "failed",
        "unknown": "at an unknown status",
    }.get(status, status.replace("_", " "))


def _summary_ref(work_id: str, title: str, report_kind: str, status: str) -> str:
    payload = json.dumps({"work_id": work_id, "title": title, "report_kind": report_kind, "status": status}, sort_keys=True)
    return f"omh-work-observation:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _choice(value: str, allowed: tuple[str, ...], fallback: str) -> str:
    normalized = _token(value)
    return normalized if normalized in allowed else fallback


def _token(value: Any) -> str:
    return re.sub(r"[^a-z0-9_./:-]+", "_", str(value).strip().casefold().replace("-", "_").replace(" ", "_")).strip("_")


def _strip_code_fences(value: Any) -> str:
    return str(value).replace("```", " ")


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def _reject_forbidden_raw_keys(value: Any, errors: list[str], *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _token(key)
            if normalized in _FORBIDDEN_RAW_KEYS:
                errors.append(f"forbidden raw field: {path}{key}")
            _reject_forbidden_raw_keys(child, errors, path=f"{path}{key}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_raw_keys(child, errors, path=f"{path}{index}.")
