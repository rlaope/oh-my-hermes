from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


CODEX_PROGRESS_SCHEMA_VERSION = "codex_progress_summary/v1"
CODEX_SESSION_OBSERVATION_SCHEMA_VERSION = "codex_session_observation/v1"
CODEX_RESUME_CONTRACT_SCHEMA_VERSION = "codex_resume_contract/v1"
CODEX_PROMPT_HANDLING_SCHEMA_VERSION = "codex_prompt_handling_contract/v1"

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
    "final",
    "message",
    "response",
    "response_item",
}
_TERMINAL_FAILURE_WORDS = ("error", "failed", "failure", "traceback")
_TERMINAL_SUCCESS_WORDS = ("completed", "complete", "success", "succeeded", "passed")
_MAX_VISIBLE_MESSAGE = 180


def summarize_codex_jsonl_file(
    path: str | Path,
    *,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    source = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        text = ""
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
        if not terminal_status and any(word in lowered for word in _TERMINAL_FAILURE_WORDS):
            terminal_status = "failed_or_error_observed"
        if any(word in lowered for word in _TERMINAL_SUCCESS_WORDS):
            terminal_status = "completed_or_passed_observed"
        visible = _assistant_visible_message(event)
        if visible:
            visible_decisions.append(visible)
            activity_counts["assistant_visible_decisions"] += 1
    activities = _observable_activity(activity_counts)
    status = terminal_status or ("activity_observed" if parsed_events else "no_observable_events")
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
        "evidence_refs": _compact_list(evidence_refs or []),
        "privacy": "summary_only",
        "claim_boundary": (
            "This is an observable Codex event summary. It is not raw JSONL, hidden reasoning, "
            "review evidence, CI evidence, merge-readiness evidence, or merge evidence."
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
    session_ref = (codex_session_ref or external_session_ref).strip()
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
    resume = observation.get("resume", {})
    if isinstance(resume, dict) and resume.get("available"):
        payload["resume"] = resume
    return payload


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
    if _hidden_event(event):
        return ""
    parts: list[str] = []
    _collect_safe_strings(event, parts)
    return " ".join(parts)


def _hidden_event(event: dict[str, Any]) -> bool:
    for key in ("type", "event", "role"):
        value = str(event.get(key, "")).casefold()
        if any(hidden in value for hidden in _HIDDEN_KEYS):
            return True
    return False


def _collect_safe_strings(value: Any, parts: list[str], *, parent_key: str = "") -> None:
    if parent_key.casefold() in _HIDDEN_KEYS:
        return
    if isinstance(value, str):
        parts.append(value[:500])
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
            if str(key).casefold() in _HIDDEN_KEYS:
                continue
            parts.append(str(key))
            _collect_safe_strings(item, parts, parent_key=str(key))


def _assistant_visible_message(event: dict[str, Any]) -> str:
    if _hidden_event(event):
        return ""
    event_type = str(event.get("type") or event.get("event") or event.get("role") or "").casefold()
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


def _compact_visible_message(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= _MAX_VISIBLE_MESSAGE:
        return cleaned
    return f"{cleaned[: _MAX_VISIBLE_MESSAGE - 1]}..."


def _is_inspection_event(text: str) -> bool:
    return any(token in text for token in ("read", "open", "grep", "rg ", "ripgrep", "sed ", "cat ", "ls ", "glob", "find", "inspect"))


def _is_edit_event(text: str) -> bool:
    return any(token in text for token in ("apply_patch", "patch", "write", "edit", "modified", "changed file", "diff"))


def _is_test_event(text: str) -> bool:
    return any(token in text for token in ("test", "pytest", "unittest", "compileall", "npm test", "cargo test", "go test", "uv run"))


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
    if not isinstance(values, (list, tuple)):
        return []
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_./:@+-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
