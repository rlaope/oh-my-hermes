from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..context_safety import (
    MAX_EVIDENCE_REFS,
    MAX_EVIDENCE_REF_CHARS,
    MAX_PROGRESS_EVENTS,
    MAX_VISIBLE_MESSAGE_CHARS,
    build_progress_event,
    compact_context_refs,
    compact_visible_text,
    context_budget_payload,
    is_user_facing_progress_noise,
    raw_output_artifact_ref,
    sanitize_user_facing_progress_text,
)


CODEX_PROGRESS_SCHEMA_VERSION = "codex_progress_summary/v1"
CODEX_SESSION_OBSERVATION_SCHEMA_VERSION = "codex_session_observation/v1"
CODEX_RESUME_CONTRACT_SCHEMA_VERSION = "codex_resume_contract/v1"
CODEX_PROMPT_HANDLING_SCHEMA_VERSION = "codex_prompt_handling_contract/v1"
CODEX_REVIEW_SUMMARY_SCHEMA_VERSION = "codex_review_summary/v1"

_HIDDEN_KEYS = {
    "analysis",
    "chain_of_thought",
    "cot",
    "hidden",
    "internal",
    "reasoning",
    "thought",
    "thinking",
}
_VISIBLE_MESSAGE_TYPES = {
    "assistant",
    "assistant_message",
    "agent_message",
    "final",
    "message",
    "response",
    "response_item",
}
_TOKEN_USAGE_KEYS = {
    "cached_input_tokens",
    "input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "usage",
}
_RAW_RUNTIME_EVENT_TYPES = {
    "turn.completed",
}
_TERMINAL_FAILURE_RE = re.compile(r"\b(error|failed|failure|traceback)\b")
_TERMINAL_SUCCESS_RE = re.compile(r"\b(completed|complete|success|succeeded|passed)\b")
_CODEX_REVIEW_STATUSES = ("not_observed", "pending", "passed", "failed", "blocked", "changes_requested", "commented")


def summarize_codex_jsonl_file(
    path: str | Path,
    *,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    source = str(path)
    text = Path(path).read_text(encoding="utf-8")
    return summarize_codex_jsonl_text(text, evidence_refs=evidence_refs, source=source)


def summarize_codex_jsonl_text(
    text: str,
    *,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    source: str = "stdin",
) -> dict[str, object]:
    parsed_events: list[dict[str, Any]] = []
    malformed_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed_count += 1
            item = {"type": "process_output", "message": line}
        if isinstance(item, dict):
            parsed_events.append(item)
        else:
            parsed_events.append({"type": "process_output", "message": str(item)})
    activity_counts: dict[str, int] = {
        "inspecting": 0,
        "editing": 0,
        "testing": 0,
        "waiting_review": 0,
        "assistant_visible_decisions": 0,
    }
    visible_decisions: list[str] = []
    terminal_status = ""
    for event in parsed_events:
        searchable = _safe_search_text(event)
        lowered = searchable.casefold()
        if _is_inspection_event(lowered):
            activity_counts["inspecting"] += 1
        if _is_edit_event(lowered):
            activity_counts["editing"] += 1
        if _is_test_event(lowered):
            activity_counts["testing"] += 1
        if _is_waiting_review_event(lowered):
            activity_counts["waiting_review"] += 1
        if not terminal_status and _TERMINAL_FAILURE_RE.search(lowered):
            terminal_status = "failed_or_error_observed"
        if _terminal_success_observed(lowered):
            terminal_status = "completed_or_passed_observed"
        visible = _assistant_visible_message(event)
        if visible:
            visible_decisions.append(visible)
            activity_counts["assistant_visible_decisions"] += 1
    activities = _observable_activity(activity_counts)
    status = terminal_status or ("activity_observed" if activities or visible_decisions else "no_observable_events")
    compact_refs, omitted_refs = compact_context_refs(evidence_refs or [])
    raw_artifact = raw_output_artifact_ref(
        text,
        source=source,
        evidence_refs=compact_refs,
        omitted_evidence_ref_count=omitted_refs,
    )
    progress_events, omitted_progress_events = _progress_events(parsed_events, raw_artifact)
    return {
        "schema_version": CODEX_PROGRESS_SCHEMA_VERSION,
        "source": source,
        "status": status,
        "event_count": len(parsed_events),
        "malformed_event_count": malformed_count,
        "activity_counts": activity_counts,
        "observable_activity": activities,
        "assistant_visible_messages": visible_decisions[:3],
        "latest_assistant_visible_message": visible_decisions[-1] if visible_decisions else "",
        "chat_summary": _chat_summary(status, activities, visible_decisions),
        "progress_reporting": _progress_reporting_contract(),
        "progress_events": progress_events,
        "latest_progress_event": progress_events[-1] if progress_events else {},
        "evidence_refs": compact_refs,
        "raw_output_artifact": raw_artifact,
        "context_budget": context_budget_payload(),
        "omitted": {
            "assistant_visible_message_count": max(0, len(visible_decisions) - 3),
            "evidence_ref_count": omitted_refs,
            "progress_event_count": omitted_progress_events,
            "max_visible_message_chars": MAX_VISIBLE_MESSAGE_CHARS,
            "max_progress_events": MAX_PROGRESS_EVENTS,
            "max_evidence_refs": MAX_EVIDENCE_REFS,
            "max_evidence_ref_chars": MAX_EVIDENCE_REF_CHARS,
        },
        "privacy": "summary_only",
        "claim_boundary": (
            "This is an observable Codex event summary. It is not raw JSONL, hidden reasoning, "
            "review evidence, CI evidence, merge-readiness evidence, or merge evidence; raw output should stay in artifacts."
        ),
    }


def build_codex_session_observation(
    *,
    selected_executor_profile: str,
    external_session_ref: str = "",
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    progress_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    if selected_executor_profile != "codex":
        return {}
    progress = progress_summary if isinstance(progress_summary, dict) else {}
    session_ref = codex_session_ref.strip()
    thread_ref = (codex_thread_ref or external_session_ref).strip()
    observed = bool(session_ref or thread_ref or progress.get("event_count"))
    resume = build_codex_resume_contract(session_ref)
    return {
        "schema_version": CODEX_SESSION_OBSERVATION_SCHEMA_VERSION,
        "observed": observed,
        "external_session_ref": external_session_ref.strip(),
        "session_ref": session_ref,
        "thread_ref": thread_ref,
        "status": str(progress.get("status") or ("attached" if observed else "not_observed")),
        "event_count": int(progress.get("event_count", 0) or 0),
        "observable_activity": list(progress.get("observable_activity", [])) if isinstance(progress.get("observable_activity"), list) else [],
        "latest_assistant_visible_message": str(progress.get("latest_assistant_visible_message", "")),
        "latest_progress_event": progress.get("latest_progress_event", {}) if isinstance(progress.get("latest_progress_event"), dict) else {},
        "evidence_refs": _compact_list([*(evidence_refs or []), *progress.get("evidence_refs", [])])
        if isinstance(progress.get("evidence_refs", []), list)
        else _compact_list(evidence_refs or []),
        "resume": resume,
        "claim_boundary": (
            "Codex session references and event counts are observed wrapper metadata. They do not prove unrecorded "
            "execution result, verification, review, CI, merge readiness, or merge."
        ),
    }


def build_codex_resume_contract(session_ref: str) -> dict[str, object]:
    available = bool(session_ref.strip())
    argv = ["codex", "exec", "resume", session_ref.strip()] if available else []
    return {
        "schema_version": CODEX_RESUME_CONTRACT_SCHEMA_VERSION,
        "available": available,
        "argv_template": argv,
        "shell_command_template": f"codex exec resume {_shell_quote(session_ref.strip())}" if available else "",
        "execution_policy": "copyable_instruction_only",
        "backend_action_owner": "wrapper",
        "not_omh_backend_execution": True,
        "claim_boundary": (
            "The resume command is a wrapper/operator launch contract only. The wrapper backend does not launch Codex or "
            "claim resumed work until it records observed session or result evidence."
        ),
    }


def build_codex_prompt_handling_contract(
    *,
    new_prompt: str,
    progress_summary: dict[str, object] | None = None,
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    external_session_ref: str = "",
    wrapper_session_id: str = "",
    same_goal: bool = False,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    codex_review_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    progress = progress_summary if isinstance(progress_summary, dict) else {}
    observation = build_codex_session_observation(
        selected_executor_profile="codex",
        external_session_ref=external_session_ref,
        codex_session_ref=codex_session_ref,
        codex_thread_ref=codex_thread_ref,
        evidence_refs=evidence_refs or [],
        progress_summary=progress,
    )
    session_ref = str(observation.get("session_ref", "")).strip()
    same_session_scope = bool(session_ref and (same_goal or wrapper_session_id))
    recommendation = _prompt_recommendation(session_ref=session_ref, same_session_scope=same_session_scope)
    payload = {
        "schema_version": CODEX_PROMPT_HANDLING_SCHEMA_VERSION,
        "new_prompt": {
            "sha256": hashlib.sha256(new_prompt.encode("utf-8")).hexdigest(),
            "length": len(new_prompt),
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
        },
        "active_codex": {
            "observed": bool(observation.get("observed")),
            "session_ref": session_ref,
            "thread_ref": str(observation.get("thread_ref", "")).strip(),
            "event_count": int(observation.get("event_count", 0) or 0),
            "latest_progress": progress,
        },
        "recommendation": recommendation,
        "adapter_contract": {
            "metadata_only": True,
            "raw_logs_exposed": False,
            "hidden_reasoning_exposed": False,
            "core_launches_codex": False,
            "claim_boundary": (
                "This contract summarizes observed Codex session metadata and recommends prompt handling. It is not "
                "execution, review, CI, merge-readiness, merge, or hidden think-log evidence."
            ),
        },
        "claim_boundary": (
            "Codex follow-up handling is wrapper/operator metadata only. The core backend does not launch Codex, append "
            "prompts, expose raw logs, or claim review/CI/merge evidence."
        ),
    }
    if isinstance(codex_review_summary, dict) and codex_review_summary:
        payload["codex_review"] = codex_review_summary
    resume = observation.get("resume", {})
    if isinstance(resume, dict) and resume.get("available"):
        payload["resume"] = resume
    return payload


def build_codex_review_summary(
    *,
    review_status: str = "not_observed",
    reviewer: str = "codex",
    summary: str = "",
    finding_count: int | None = None,
    progress_summary: dict[str, object] | None = None,
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    external_session_ref: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    normalized_status = _normalize_review_status(review_status, summary=summary)
    progress = progress_summary if isinstance(progress_summary, dict) else {}
    observation = build_codex_session_observation(
        selected_executor_profile="codex",
        external_session_ref=external_session_ref,
        codex_session_ref=codex_session_ref,
        codex_thread_ref=codex_thread_ref,
        evidence_refs=evidence_refs or [],
        progress_summary=progress,
    )
    observed = normalized_status != "not_observed" or bool(summary.strip()) or bool(evidence_refs)
    requires_fixes = normalized_status in {"failed", "blocked", "changes_requested"}
    resume = observation.get("resume", {}) if isinstance(observation.get("resume"), dict) else {}
    return {
        "schema_version": CODEX_REVIEW_SUMMARY_SCHEMA_VERSION,
        "observed": observed,
        "reviewer": reviewer.strip() or "codex",
        "status": normalized_status,
        "satisfied": normalized_status == "passed",
        "requires_fixes": requires_fixes,
        "finding_count": max(0, int(finding_count)) if finding_count is not None else 0,
        "finding_count_observed": finding_count is not None,
        "human_summary": _compact_visible_message(summary) if summary.strip() else _default_review_summary(normalized_status),
        "codex_session": observation,
        "progress_context": _progress_context(progress),
        "evidence_refs": _compact_list(evidence_refs or []),
        "handback": {
            "can_resume_for_fixes": bool(requires_fixes and resume.get("available")),
            "resume": resume if resume.get("available") else {},
            "recommended_action": "resume_codex_for_review_fixes" if requires_fixes else "record_review_context_only",
            "core_launches_codex": False,
            "raw_finding_logs_required": False,
            "claim_boundary": (
                "Review findings can be handed back to a wrapper/operator-managed Codex session. OMH core does not launch "
                "Codex or claim fixes until observed executor evidence is recorded."
            ),
        },
        "adapter_contract": {
            "metadata_only": True,
            "human_readable_summary_only": True,
            "raw_logs_exposed": False,
            "raw_review_events_exposed": False,
            "hidden_reasoning_exposed": False,
            "core_launches_codex": False,
            "claim_boundary": (
                "This is an observed Codex review context summary for Hermes narration. It is not raw JSONL, hidden "
                "reasoning, CI evidence, merge-readiness evidence, or merge evidence."
            ),
        },
        "claim_boundary": (
            "A Codex review summary is review-context metadata only. It does not prove review fixes, CI, merge readiness, "
            "or merge unless separate observed evidence is recorded."
        ),
    }


def _prompt_recommendation(*, session_ref: str, same_session_scope: bool) -> dict[str, object]:
    if session_ref and same_session_scope:
        return {
            "action": "append_followup_to_observed_codex_session",
            "can_append_to_existing_session": True,
            "requires_clarification": False,
            "reason": "An observed Codex session_ref exists for the same wrapper session or confirmed same goal.",
            "next_step": "Use the wrapper/operator resume path and append the follow-up prompt to the observed Codex session.",
            "not_evidence": ["execution_result", "review", "ci", "merge_readiness", "merge"],
        }
    if session_ref:
        return {
            "action": "clarify_before_append_or_route_new",
            "can_append_to_existing_session": False,
            "requires_clarification": True,
            "reason": "A Codex session_ref exists, but the new prompt is not confirmed to belong to the same goal/session.",
            "next_step": "Ask whether to append to the observed Codex session or start/route a separate task.",
            "not_evidence": ["execution_result", "review", "ci", "merge_readiness", "merge"],
        }
    return {
        "action": "route_new_or_clarify",
        "can_append_to_existing_session": False,
        "requires_clarification": True,
        "reason": "No observed Codex session_ref is available for safe resume or append handling.",
        "next_step": "Route the prompt as a new task or ask one clarification before dispatch.",
        "not_evidence": ["execution_result", "review", "ci", "merge_readiness", "merge"],
    }


def _safe_search_text(event: dict[str, Any]) -> str:
    if _hidden_event(event) or _raw_runtime_event(event):
        return ""
    parts: list[str] = []
    _collect_safe_strings(event, parts)
    return " ".join(parts)


def _hidden_event(event: dict[str, Any]) -> bool:
    return _hidden_marker(event)


def _hidden_marker(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key in ("type", "event", "role"):
        marker = str(value.get(key, "")).casefold()
        if any(hidden in marker for hidden in _HIDDEN_KEYS):
            return True
    return False


def _collect_safe_strings(value: Any, parts: list[str], *, parent_key: str = "") -> None:
    if parent_key.casefold() in _HIDDEN_KEYS | _TOKEN_USAGE_KEYS:
        return
    if _hidden_marker(value) or _raw_runtime_event(value):
        return
    if isinstance(value, str):
        cleaned = sanitize_user_facing_progress_text(value, max_chars=500)
        if cleaned:
            parts.append(cleaned)
        return
    if isinstance(value, (int, float, bool)):
        parts.append(str(value))
        return
    if isinstance(value, list):
        for item in value[:20]:
            _collect_safe_strings(item, parts, parent_key=parent_key)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _HIDDEN_KEYS | _TOKEN_USAGE_KEYS:
                continue
            if _hidden_marker(item) or _raw_runtime_event(item):
                continue
            parts.append(str(key))
            _collect_safe_strings(item, parts, parent_key=str(key))


def _assistant_visible_message(event: dict[str, Any]) -> str:
    if _hidden_event(event) or _raw_runtime_event(event):
        return ""
    for key in ("data", "item", "payload"):
        payload = event.get(key)
        if _hidden_marker(payload):
            return ""
    event_type = str(event.get("type") or event.get("event") or event.get("role") or "").casefold()
    if event_type == "item.completed" and isinstance(event.get("item"), dict):
        return _assistant_visible_message(event["item"])
    if event_type not in _VISIBLE_MESSAGE_TYPES and str(event.get("role", "")).casefold() != "assistant":
        return ""
    if any(hidden in event_type for hidden in _HIDDEN_KEYS):
        return ""
    for key in ("message", "content", "text", "summary"):
        if key in event and isinstance(event[key], str):
            return _compact_visible_message(event[key])
    payload = event.get("data")
    if isinstance(payload, dict):
        for key in ("message", "content", "text", "summary"):
            if key in payload and isinstance(payload[key], str):
                return _compact_visible_message(payload[key])
    return ""


def _raw_runtime_event(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    event_type = str(value.get("type") or value.get("event") or "").casefold()
    if event_type in _RAW_RUNTIME_EVENT_TYPES:
        return True
    visible_content_keys = {"message", "content", "text", "summary"}
    if visible_content_keys & {str(key).casefold() for key in value}:
        return False
    for nested_key in ("data", "item", "payload"):
        nested = value.get(nested_key)
        if isinstance(nested, dict) and not _raw_runtime_event(nested):
            return False
    return any(str(key).casefold() in _TOKEN_USAGE_KEYS for key in value)


def _normalize_review_status(status: str, *, summary: str = "") -> str:
    normalized = status.strip().casefold().replace("-", "_").replace(" ", "_") or "not_observed"
    aliases = {
        "approved": "passed",
        "approve": "passed",
        "request_changes": "changes_requested",
        "requested_changes": "changes_requested",
        "needs_changes": "changes_requested",
        "comment": "commented",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized == "not_observed" and summary.strip():
        normalized = "commented"
    if normalized not in _CODEX_REVIEW_STATUSES:
        raise ValueError(f"Codex review status must be one of: {', '.join(_CODEX_REVIEW_STATUSES)}")
    return normalized


def _default_review_summary(status: str) -> str:
    if status == "passed":
        return "Codex review passed."
    if status == "changes_requested":
        return "Codex review requested changes."
    if status == "failed":
        return "Codex review failed."
    if status == "blocked":
        return "Codex review is blocked."
    if status == "pending":
        return "Codex review is pending."
    if status == "commented":
        return "Codex review produced human-readable context."
    return "Codex review has not been observed."


def _progress_context(progress: dict[str, object]) -> dict[str, object]:
    if not progress:
        return {}
    return {
        "schema_version": str(progress.get("schema_version", "")),
        "status": str(progress.get("status", "")),
        "event_count": int(progress.get("event_count", 0) or 0),
        "observable_activity": list(progress.get("observable_activity", [])) if isinstance(progress.get("observable_activity"), list) else [],
        "chat_summary": str(progress.get("chat_summary", "")),
        "latest_progress_event": progress.get("latest_progress_event", {}) if isinstance(progress.get("latest_progress_event"), dict) else {},
        "evidence_refs": _compact_list(progress.get("evidence_refs", [])),
        "claim_boundary": str(progress.get("claim_boundary", "")),
    }


def _terminal_success_observed(text: str) -> bool:
    for match in _TERMINAL_SUCCESS_RE.finditer(text):
        prefix = text[max(0, match.start() - 80) : match.start()]
        if re.search(r"\b(no|not|never|without|pending|awaiting)\b", prefix):
            continue
        if re.search(r"\b(will|would|should|could|may|might|planning to|going to|about to)\b", prefix):
            continue
        return True
    return False


def _compact_visible_message(value: str) -> str:
    if is_user_facing_progress_noise(value):
        return ""
    return compact_visible_text(
        sanitize_user_facing_progress_text(value) or value,
        max_chars=MAX_VISIBLE_MESSAGE_CHARS,
    )


def _progress_events(parsed_events: list[dict[str, Any]], raw_artifact: dict[str, object]) -> tuple[list[dict[str, object]], int]:
    events: list[dict[str, object]] = []
    for event in parsed_events:
        searchable = _safe_search_text(event)
        visible = _assistant_visible_message(event)
        summary = visible or _tool_progress_summary(searchable)
        if not summary:
            continue
        event_type = _progress_event_type(searchable)
        if not event_type:
            continue
        status, severity = _progress_status_and_severity(event_type)
        events.append(
            build_progress_event(
                event_type,
                summary,
                status=status,
                severity=severity,
                file_refs=_file_refs(searchable),
                artifact_refs=[raw_artifact],
            )
        )
    if len(events) <= MAX_PROGRESS_EVENTS:
        return events, 0
    return events[-MAX_PROGRESS_EVENTS:], len(events) - MAX_PROGRESS_EVENTS


def _progress_reporting_contract() -> dict[str, object]:
    return {
        "schema_version": "omh_progress_reporting/v1",
        "mode": "event_triggered",
        "timed_polling_required": False,
        "preferred_triggers": [
            "bug_or_failure_discovered",
            "root_cause_identified",
            "fix_strategy_selected",
            "files_or_area_chosen",
            "targeted_tests_pass_or_fail",
            "full_tests_start_pass_or_fail",
            "commit_or_pr_created_or_updated",
            "blocker_encountered",
        ],
        "human_update_policy": "one_or_two_sentence_summary_only",
        "raw_output_policy": "store_raw_output_as_artifact_and_emit_refs_only",
    }


def _progress_event_type(text: str) -> str:
    lowered = text.casefold()
    if "root cause" in lowered:
        return "root_cause_identified"
    if "fix strategy" in lowered or "strategy selected" in lowered or "selected strategy" in lowered:
        return "fix_strategy_selected"
    if "bug discovered" in lowered:
        return "bug_discovered"
    if "blocker" in lowered or "blocked" in lowered:
        return "blocker_encountered"
    if "full tests" in lowered and "start" in lowered:
        return "full_tests_started"
    if "full tests" in lowered and _terminal_success_observed(lowered):
        return "full_tests_passed"
    if "full tests" in lowered and _TERMINAL_FAILURE_RE.search(lowered):
        return "full_tests_failed"
    if "targeted tests" in lowered and _terminal_success_observed(lowered):
        return "targeted_tests_passed"
    if "targeted tests" in lowered and _TERMINAL_FAILURE_RE.search(lowered):
        return "targeted_tests_failed"
    if "test" in lowered and _terminal_success_observed(lowered):
        return "targeted_tests_passed"
    if "test" in lowered and _TERMINAL_FAILURE_RE.search(lowered):
        return "targeted_tests_failed"
    if "commit" in lowered and any(token in lowered for token in ("created", "committed")):
        return "commit_created"
    if ("pull request" in lowered or " pr " in lowered) and "created" in lowered:
        return "pr_created"
    if ("pull request" in lowered or " pr " in lowered) and "updated" in lowered:
        return "pr_updated"
    if _file_refs(text) and any(token in lowered for token in ("file", "files", "area", "chosen", "selected", "editing", "touching")):
        return "files_area_chosen"
    if "failure" in lowered or "failed" in lowered or "error" in lowered:
        return "failure_discovered"
    return ""


def _progress_status_and_severity(event_type: str) -> tuple[str, str]:
    if event_type.endswith("_passed") or event_type in {"commit_created", "pr_created", "pr_updated", "workflow_completed"}:
        return "passed", "success"
    if event_type.endswith("_failed") or event_type in {"failure_discovered", "bug_discovered"}:
        return "failed", "error"
    if event_type == "blocker_encountered":
        return "blocked", "blocked"
    if event_type.endswith("_started"):
        return "running", "info"
    if event_type in {"root_cause_identified", "fix_strategy_selected", "files_area_chosen"}:
        return "observed", "warning" if event_type == "root_cause_identified" else "info"
    return "observed", "info"


def _tool_progress_summary(text: str) -> str:
    if not text:
        return ""
    event_type = _progress_event_type(text)
    if event_type.endswith("_passed"):
        return "Tests passed."
    if event_type.endswith("_failed"):
        return "Tests failed."
    if event_type.endswith("_started"):
        return "Tests started."
    if event_type == "commit_created":
        return "Commit created."
    if event_type == "pr_created":
        return "Pull request created."
    if event_type == "pr_updated":
        return "Pull request updated."
    if event_type == "blocker_encountered":
        return "Blocker encountered."
    if event_type == "files_area_chosen":
        refs = _file_refs(text)
        return f"Work area chosen: {', '.join(refs[:3])}."
    return ""


def _file_refs(text: str) -> list[str]:
    matches = re.findall(r"\b[\w./-]+\.(?:py|md|json|jsonl|toml|yaml|yml|ts|tsx|js|jsx|sh)\b", text)
    compact, _omitted = compact_context_refs(matches)
    return compact


def _is_inspection_event(text: str) -> bool:
    return any(token in text for token in ("read", "open", "grep", "rg ", "ripgrep", "sed ", "cat ", "ls ", "glob", "find", "inspect"))


def _is_edit_event(text: str) -> bool:
    if re.search(r"\bbefore\s+(?:editing|edit|writing|changing|patching)\b", text):
        return False
    if re.search(r"\b(?:will|going to|planning to|about to)\s+(?:edit|write|change|patch|modify)\b", text):
        return False
    return any(token in text for token in ("apply_patch", "patch", "write", "edit", "modified", "changed file", "diff"))


def _is_test_event(text: str) -> bool:
    if any(token in text for token in ("pytest", "unittest", "compileall", "npm test", "cargo test", "go test", "uv run")):
        return True
    return bool(
        re.search(r"\btests?\s+(?:started|running|passed|failed|pass|fail)\b", text)
        or re.search(r"\b(?:run|running|ran)\s+tests?\b", text)
    )


def _is_waiting_review_event(text: str) -> bool:
    return any(token in text for token in ("waiting on review", "needs review", "review requested", "pull request", " pr ", "ci "))


def _observable_activity(activity_counts: dict[str, int]) -> list[str]:
    labels = []
    if activity_counts.get("inspecting"):
        labels.append("Codex is inspecting files/tests.")
    if activity_counts.get("editing"):
        labels.append("Codex changed files.")
    if activity_counts.get("testing"):
        labels.append("Codex is running tests.")
    if activity_counts.get("waiting_review"):
        labels.append("Codex is waiting on review.")
    if activity_counts.get("assistant_visible_decisions"):
        labels.append("Codex produced assistant-visible decision or status text.")
    return labels


def _chat_summary(status: str, activities: list[str], visible_decisions: list[str]) -> str:
    if not activities and not visible_decisions:
        return "No observable Codex activity was summarized."
    parts = [*activities]
    if visible_decisions:
        parts.append(f"Codex decided via assistant-visible message: {visible_decisions[-1]}")
    return " ".join(parts) + f" Status: {status}."


def _compact_list(values: Any) -> list[str]:
    return compact_context_refs(values)[0]


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_./:@+-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
