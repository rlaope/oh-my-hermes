from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, ensure_dir, ensure_file, read_json_object, read_jsonl_objects, utc_now
from ..paths import OmhPaths
from .context_safety import sanitize_user_facing_progress_text


EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION = "omh_executor_progress_binding/v1"
EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION = "omh_progress_event/v1"
EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION = "omh_progress_report/v1"

ALLOWED_EXECUTOR_PROFILES = ("codex", "claude_code", "hermes_local")
TARGET_TYPES = ("run", "wrapper_session")
BINDING_STATES = ("active", "stale", "expired", "closed")
PROGRESS_EVENT_TYPES = (
    "executor_dispatched",
    "repo_exploration",
    "running_no_diff_observed",
    "diff_started",
    "tests_started",
    "tests_failed",
    "tests_passed",
    "executor_completed",
    "executor_blocked",
    "executor_failed",
    "progress_observed",
)
TERMINAL_EVENT_TYPES = {"executor_completed", "executor_blocked", "executor_failed", "tests_failed", "tests_passed"}
DEFAULT_FRESHNESS_SECONDS = 900
DEFAULT_EXPIRY_SECONDS = 86400
DEFAULT_MINIMUM_REPEAT_INTERVAL_SECONDS = 120
CLAIM_BOUNDARY = (
    "Executor progress is metadata-only observed activity. It is not result, verification, "
    "review, CI, merge-readiness, or merge evidence."
)

_RAW_OR_HIDDEN_KEYS = {
    "analysis",
    "chain_of_thought",
    "cot",
    "hidden",
    "hidden_reasoning",
    "raw",
    "raw_log",
    "raw_logs",
    "raw_output",
    "reasoning",
    "think",
    "thinking",
    "transcript",
}


class ExecutorProgressError(ValueError):
    pass


def normalize_executor_profile(value: str, *, observed_hermes_execution: bool = False) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    aliases = {
        "codex": "codex",
        "claude": "claude_code",
        "claude-code": "claude_code",
        "claude-code-cli": "claude_code",
        "claude_code": "claude_code",
    }
    if normalized == "hermes":
        if observed_hermes_execution:
            return "hermes_local"
        raise ExecutorProgressError("Hermes orchestration is not an active executor; use hermes_local only for observed local execution")
    if normalized in {"hermes-local", "hermes_local"}:
        if observed_hermes_execution:
            return "hermes_local"
        raise ExecutorProgressError("hermes_local requires explicit observed local execution evidence")
    profile = aliases.get(normalized, "")
    if profile not in ALLOWED_EXECUTOR_PROFILES:
        raise ExecutorProgressError(f"unsupported executor profile for progress: {value}")
    return profile


def progress_dir_for_target(paths: OmhPaths, target_type: str, target_id: str) -> Path:
    if target_type == "run":
        return paths.runtime_runs_dir / target_id / "executor_progress"
    if target_type == "wrapper_session":
        return paths.runtime_wrapper_sessions_dir / target_id / "executor_progress"
    raise ExecutorProgressError(f"unsupported progress target type: {target_type}")


def binding_id_for(target_type: str, target_id: str, executor_profile: str) -> str:
    return f"{target_type}:{target_id}:{executor_profile}"


def progress_instance_id_for(binding_id: str) -> str:
    return f"{binding_id}:{uuid.uuid4().hex[:16]}"


def build_progress_binding(
    *,
    target_type: str,
    target_id: str,
    executor_profile: str,
    now: str | None = None,
    state: str = "active",
    existing_correlation_root: str = "",
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    claude_session_ref: str = "",
    process_session_id: str = "",
    worktree: str = "",
    branch: str = "",
    pid: int | str | None = None,
    source: str = "",
    channel_ref: str = "",
    thread_ref: str = "",
    delivery_target: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    observed_hermes_execution: bool = False,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    minimum_repeat_interval_seconds: int = DEFAULT_MINIMUM_REPEAT_INTERVAL_SECONDS,
) -> dict[str, Any]:
    target_type = target_type.strip()
    target_id = target_id.strip()
    if target_type not in TARGET_TYPES:
        raise ExecutorProgressError(f"target_type must be one of {', '.join(TARGET_TYPES)}")
    if not target_id:
        raise ExecutorProgressError("target_id is required")
    profile = normalize_executor_profile(executor_profile, observed_hermes_execution=observed_hermes_execution)
    timestamp = now or utc_now()
    binding_id = binding_id_for(target_type, target_id, profile)
    instance_id = progress_instance_id_for(binding_id)
    aliases = _correlation_aliases(
        codex_session_ref=codex_session_ref,
        codex_thread_ref=codex_thread_ref,
        claude_session_ref=claude_session_ref,
        process_session_id=process_session_id,
        worktree=worktree,
        branch=branch,
    )
    binding = {
        "schema_version": EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION,
        "binding_id": binding_id,
        "instance_id": instance_id,
        "target": {"type": target_type, "id": target_id},
        "target_type": target_type,
        "target_id": target_id,
        "executor": profile,
        "executor_profile": profile,
        "correlation_root": existing_correlation_root
        or correlation_root_for(
            binding_id=binding_id,
            instance_id=instance_id,
            codex_session_ref=codex_session_ref,
            codex_thread_ref=codex_thread_ref,
            claude_session_ref=claude_session_ref,
            process_session_id=process_session_id,
            worktree=worktree,
            branch=branch,
        ),
        "correlation_aliases": aliases,
        "process": _clean_object(
            {
                "process_session_id": process_session_id.strip(),
                "pid": _optional_pid(pid),
                "worktree": worktree.strip(),
                "branch": branch.strip(),
            }
        ),
        "delivery": _clean_object(
            {
                "source": source.strip(),
                "channel_ref": channel_ref.strip(),
                "thread_ref": thread_ref.strip(),
                "delivery_target": delivery_target.strip(),
            }
        ),
        "state": state,
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_observed_at": timestamp,
        "last_reported_at": "",
        "last_observed_signal_hash": "",
        "last_observed_event_count": 0,
        "last_observed_artifact_sha256": "",
        "freshness_seconds": int(freshness_seconds),
        "expiry_seconds": int(expiry_seconds),
        "last_transition_fingerprint": "",
        "last_reported_event_type": "",
        "last_reported_state": "",
        "last_reported_summary_hash": "",
        "last_reported_artifact_sha256": "",
        "report_count": 0,
        "suppressed_duplicate_count": 0,
        "minimum_repeat_interval_seconds": int(minimum_repeat_interval_seconds),
        "evidence_refs": _compact_strings(evidence_refs or []),
        "privacy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    _require_valid("binding", validate_progress_binding(binding))
    return binding


def correlation_root_for(
    *,
    binding_id: str,
    instance_id: str = "",
    existing_correlation_root: str = "",
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    claude_session_ref: str = "",
    process_session_id: str = "",
    worktree: str = "",
    branch: str = "",
) -> str:
    if existing_correlation_root.strip():
        return existing_correlation_root.strip()
    if claude_session_ref.strip():
        return f"claude_session:{claude_session_ref.strip()}"
    if codex_session_ref.strip():
        return f"codex_session:{codex_session_ref.strip()}"
    if codex_thread_ref.strip():
        return f"codex_thread:{codex_thread_ref.strip()}"
    if process_session_id.strip():
        return f"process_session:{process_session_id.strip()}"
    if instance_id.strip():
        return f"binding_instance:{instance_id.strip()}"
    return f"binding:{binding_id}"


def write_progress_binding(paths: OmhPaths, binding: dict[str, Any]) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    target = _binding_target(binding)
    progress_dir = progress_dir_for_target(paths, target["type"], target["id"])
    ensure_dir(progress_dir, private=True)
    atomic_write_json(progress_dir / "binding.json", binding, private=True)
    return binding


def read_progress_binding(paths: OmhPaths, target_type: str, target_id: str) -> dict[str, Any] | None:
    binding = read_json_object(progress_dir_for_target(paths, target_type, target_id) / "binding.json")
    if not binding:
        return None
    _require_valid("binding", validate_progress_binding(binding))
    return binding


def list_progress_bindings(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for root, target_type in (
        (paths.runtime_runs_dir, "run"),
        (paths.runtime_wrapper_sessions_dir, "wrapper_session"),
    ):
        if not root.exists():
            continue
        for binding_path in sorted(root.glob("*/executor_progress/binding.json")):
            try:
                binding = read_json_object(binding_path)
                if not binding:
                    continue
                _require_valid("binding", validate_progress_binding(binding))
            except (OSError, ValueError, ExecutorProgressError):
                continue
            target = _binding_target(binding)
            if target["type"] == target_type:
                bindings.append(binding)
    bindings.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    if limit is not None:
        return bindings[: max(0, limit)]
    return bindings


def build_progress_event(
    binding: dict[str, Any],
    *,
    event_type: str,
    status: str = "",
    summary: str = "",
    observed_at: str | None = None,
    severity: str = "info",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    if event_type not in PROGRESS_EVENT_TYPES:
        raise ExecutorProgressError(f"unsupported progress event type: {event_type}")
    timestamp = observed_at or utc_now()
    event = {
        "schema_version": EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION,
        "binding_id": str(binding["binding_id"]),
        "instance_id": str(binding["instance_id"]),
        "target": dict(binding["target"]),
        "target_type": binding["target_type"],
        "target_id": binding["target_id"],
        "executor": binding["executor_profile"],
        "executor_profile": binding["executor_profile"],
        "correlation_root": binding["correlation_root"],
        "event_type": event_type,
        "status": status or _status_for_event_type(event_type),
        "severity": severity,
        "summary": _compact_text(
            _sanitize_progress_copy(summary) or _summary_for_event_type(event_type),
            280,
        ),
        "observed_at": timestamp,
        "evidence_refs": _compact_strings(evidence_refs or binding.get("evidence_refs", [])),
        "signal": _safe_signal(signal or {}),
        "privacy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    event["transition_fingerprint"] = transition_fingerprint(event)
    _require_valid("event", validate_progress_event(event))
    return event


def build_safe_progress_signal(
    *,
    executor_profile: str,
    process_status: str = "",
    codex_progress_summary: dict[str, Any] | None = None,
    profile_progress_summary: dict[str, Any] | None = None,
    git_status_short: str = "",
    git_diff_stat: str = "",
    explicit_event_type: str = "",
    explicit_summary: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    observed_hermes_execution: bool = False,
) -> dict[str, Any]:
    profile = normalize_executor_profile(executor_profile, observed_hermes_execution=observed_hermes_execution)
    progress = _safe_progress_summary(
        codex_progress_summary if profile == "codex" else profile_progress_summary,
        codex_profile=profile == "codex",
    )
    explicit = explicit_event_type.strip()
    if explicit and explicit not in PROGRESS_EVENT_TYPES:
        raise ExecutorProgressError(f"unsupported explicit event type: {explicit}")
    signal = {
        "executor_profile": profile,
        "process_status": _compact_text(process_status, 80),
        "git_status_hash": _hash_if_present(git_status_short),
        "git_diff_stat_hash": _hash_if_present(git_diff_stat),
        "progress_status": progress.get("status", ""),
        "progress_event_count": progress.get("event_count", 0),
        "latest_progress_event_type": progress.get("latest_progress_event_type", ""),
        "observable_activity": progress.get("observable_activity", []),
        "assistant_visible_summary": progress.get("assistant_visible_summary", ""),
        "progress_snapshot_hash": progress.get("summary_hash", ""),
        "codex_artifact_sha256": progress.get("artifact_sha256", "") if profile == "codex" else "",
        "codex_artifact_byte_count": progress.get("artifact_byte_count", 0) if profile == "codex" else 0,
        "codex_malformed_event_count": progress.get("malformed_event_count", 0) if profile == "codex" else 0,
        "explicit_event_type": explicit,
        "explicit_summary": _compact_text(_sanitize_progress_copy(explicit_summary), 280),
        "evidence_ref_count": len(evidence_refs or []),
    }
    return _safe_signal(signal)


def infer_progress_event_type(signal: dict[str, Any]) -> str:
    explicit = str(signal.get("explicit_event_type", ""))
    if explicit:
        return explicit
    progress_status = str(signal.get("progress_status", ""))
    latest = str(signal.get("latest_progress_event_type", ""))
    activity = set(signal.get("observable_activity", []) if isinstance(signal.get("observable_activity"), list) else [])
    process_status = str(signal.get("process_status", "")).casefold()
    test_activity = bool(activity.intersection({"Codex ran tests.", "Codex is running tests."}))
    inspect_activity = bool(activity.intersection({"Codex inspected the repo.", "Codex is inspecting files/tests."}))
    if latest == "blocker_encountered" or progress_status == "blocked" or process_status in {"blocked", "blocker"}:
        return "executor_blocked"
    if progress_status == "failed_or_error_observed" or latest in {"targeted_tests_failed", "full_tests_failed", "tests_failed"}:
        return "tests_failed" if test_activity or latest in {"targeted_tests_failed", "full_tests_failed", "tests_failed"} else "executor_failed"
    if latest == "failure_discovered" or process_status in {"failed", "failure", "error", "errored", "exited_nonzero"}:
        return "executor_failed"
    if progress_status == "completed_or_passed_observed":
        return "tests_passed" if (test_activity or latest in {"targeted_tests_passed", "full_tests_passed", "tests_passed"}) else "executor_completed"
    if latest in {"targeted_tests_passed", "full_tests_passed", "tests_passed"}:
        return "tests_passed"
    if latest in {"targeted_tests_started", "full_tests_started", "tests_started"} or test_activity:
        return "tests_started"
    if latest in {"diff_started", "file_changed"} or signal.get("git_diff_stat_hash") or signal.get("git_status_hash"):
        return "diff_started"
    if "Codex changed files." in activity:
        return "diff_started"
    if inspect_activity:
        return "repo_exploration"
    if process_status in {"completed", "complete", "done", "success", "succeeded", "exited_zero"}:
        return "executor_completed"
    if process_status in {"dispatched", "launched", "started", "spawned"}:
        return "executor_dispatched"
    if process_status in {"running", "active", "in_progress", "working"}:
        return "running_no_diff_observed"
    return "progress_observed"


def summary_for_signal(signal: dict[str, Any], event_type: str) -> str:
    explicit = str(signal.get("explicit_summary", "")).strip()
    if explicit:
        return _sanitize_progress_copy(explicit) or _summary_for_event_type(event_type)
    visible = str(signal.get("assistant_visible_summary", "")).strip()
    if visible and event_type in {
        "repo_exploration",
        "diff_started",
        "tests_started",
        "tests_failed",
        "tests_passed",
        "executor_completed",
        "executor_blocked",
        "executor_failed",
    }:
        return _compact_text(_sanitize_progress_copy(visible) or _summary_for_event_type(event_type), 240)
    return _summary_for_event_type(event_type)


def observe_executor_progress(
    paths: OmhPaths,
    binding: dict[str, Any],
    signal: dict[str, Any],
    *,
    source_language: str = "",
    observed_at: str | None = None,
) -> dict[str, Any]:
    event_type = infer_progress_event_type(signal)
    event = build_progress_event(
        binding,
        event_type=event_type,
        summary=summary_for_signal(signal, event_type),
        observed_at=observed_at,
        evidence_refs=binding.get("evidence_refs", []),
        signal=signal,
    )
    should_report, reason = should_report_event(binding, event, now=observed_at)
    if not should_report:
        updated = update_binding_reporter_state(binding, event, reported=False, reported_at=observed_at)
        write_progress_binding(paths, updated)
        return {
            "schema_version": "omh_executor_progress_observation/v1",
            "binding": updated,
            "event": {},
            "report": {},
            "reported": False,
            "suppressed_reason": reason,
            "reporting_action": "suppress",
            "chat_report": "",
            "claim_boundary": CLAIM_BOUNDARY,
        }
    append_progress_event(paths, binding, event)
    report = build_progress_report(binding, event, source_language=source_language, reported_at=observed_at)
    append_progress_report(paths, binding, report)
    updated = update_binding_reporter_state(binding, event, reported=True, reported_at=report["reported_at"])
    write_progress_binding(paths, updated)
    return {
        "schema_version": "omh_executor_progress_observation/v1",
        "binding": updated,
        "event": event,
        "report": report,
        "reported": True,
        "suppressed_reason": "",
        "reporting_action": "send_report",
        "chat_report": report["summary"],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def append_progress_event(paths: OmhPaths, binding: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    target = _binding_target(binding)
    progress_dir = progress_dir_for_target(paths, target["type"], target["id"])
    ensure_dir(progress_dir, private=True)
    events_path = progress_dir / "events.jsonl"
    ensure_file(events_path, private=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def latest_progress_event(paths: OmhPaths, binding: dict[str, Any]) -> dict[str, Any]:
    target = _binding_target(binding)
    events, _errors = read_jsonl_objects(progress_dir_for_target(paths, target["type"], target["id"]) / "events.jsonl")
    valid = [event for event in events if not validate_progress_event(event) and _payload_matches_binding_instance(event, binding)]
    return valid[-1] if valid else {}


def build_progress_report(
    binding: dict[str, Any],
    event: dict[str, Any],
    *,
    source_language: str = "",
    reported_at: str | None = None,
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    sentence = _report_sentence(event, source_language=source_language)
    report = {
        "schema_version": EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION,
        "binding_id": binding["binding_id"],
        "instance_id": str(binding["instance_id"]),
        "target": dict(binding["target"]),
        "target_type": binding["target_type"],
        "target_id": binding["target_id"],
        "executor": binding["executor_profile"],
        "executor_profile": binding["executor_profile"],
        "correlation_root": binding["correlation_root"],
        "event_type": event["event_type"],
        "status": event["status"],
        "summary": sentence,
        "reported_at": reported_at or utc_now(),
        "event_ref": {
            "event_type": event["event_type"],
            "observed_at": event["observed_at"],
            "transition_fingerprint": event["transition_fingerprint"],
        },
        "privacy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    _require_valid("report", validate_progress_report(report))
    return report


def append_progress_report(paths: OmhPaths, binding: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("report", validate_progress_report(report))
    target = _binding_target(binding)
    progress_dir = progress_dir_for_target(paths, target["type"], target["id"])
    ensure_dir(progress_dir, private=True)
    reports_path = progress_dir / "reports.jsonl"
    ensure_file(reports_path, private=True)
    with reports_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    return report


def latest_progress_report(paths: OmhPaths, binding: dict[str, Any]) -> dict[str, Any]:
    target = _binding_target(binding)
    reports, _errors = read_jsonl_objects(progress_dir_for_target(paths, target["type"], target["id"]) / "reports.jsonl")
    valid = [report for report in reports if not validate_progress_report(report) and _payload_matches_binding_instance(report, binding)]
    return valid[-1] if valid else {}


def should_report_event(binding: dict[str, Any], event: dict[str, Any], *, now: str | None = None) -> tuple[bool, str]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    fingerprint = str(event.get("transition_fingerprint", ""))
    if fingerprint and fingerprint == str(binding.get("last_transition_fingerprint", "")):
        return False, "duplicate_transition"
    event_type = str(event.get("event_type", ""))
    if event_type in TERMINAL_EVENT_TYPES:
        return True, "terminal_or_blocker"
    last_type = str(binding.get("last_reported_event_type", ""))
    if last_type == event_type and not _minimum_interval_elapsed(
        str(binding.get("last_reported_at", "")),
        now or utc_now(),
        int(binding.get("minimum_repeat_interval_seconds", DEFAULT_MINIMUM_REPEAT_INTERVAL_SECONDS) or 0),
    ):
        return False, "repeat_interval"
    return True, "meaningful_transition"


def update_binding_reporter_state(
    binding: dict[str, Any],
    event: dict[str, Any],
    *,
    reported: bool,
    reported_at: str | None = None,
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    updated = dict(binding)
    now = reported_at or utc_now()
    signal = event.get("signal", {}) if isinstance(event.get("signal"), dict) else {}
    updated["updated_at"] = now
    updated["last_observed_at"] = str(event.get("observed_at", now))
    updated["last_observed_signal_hash"] = _signal_fingerprint(signal)
    updated["last_observed_event_count"] = _safe_int(signal.get("progress_event_count"), 0)
    updated["last_observed_artifact_sha256"] = str(signal.get("codex_artifact_sha256", ""))
    if str(event.get("event_type", "")) in {"executor_completed", "executor_blocked", "executor_failed"}:
        updated["state"] = "closed"
    else:
        updated["state"] = "active"
    if reported:
        updated["last_reported_at"] = now
        updated["last_transition_fingerprint"] = str(event.get("transition_fingerprint", ""))
        updated["last_reported_event_type"] = str(event.get("event_type", ""))
        updated["last_reported_state"] = str(event.get("status", ""))
        updated["last_reported_summary_hash"] = hashlib.sha256(str(event.get("summary", "")).encode("utf-8")).hexdigest()
        updated["last_reported_artifact_sha256"] = str(signal.get("codex_artifact_sha256", ""))
        updated["report_count"] = int(updated.get("report_count", 0) or 0) + 1
    else:
        updated["suppressed_duplicate_count"] = int(updated.get("suppressed_duplicate_count", 0) or 0) + 1
    _require_valid("binding", validate_progress_binding(updated))
    return updated


def refresh_binding_freshness(
    binding: dict[str, Any],
    *,
    now: str | None = None,
    result_status: str = "",
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    updated = dict(binding)
    if result_status in {"completed", "blocked", "failed"} or updated.get("state") == "closed":
        updated["state"] = "closed"
        return updated
    reference = str(updated.get("last_observed_at") or updated.get("updated_at") or updated.get("created_at") or "")
    age = _seconds_between(reference, now or utc_now())
    if age is None:
        updated["state"] = "stale"
    elif age > int(updated.get("expiry_seconds", DEFAULT_EXPIRY_SECONDS) or DEFAULT_EXPIRY_SECONDS):
        updated["state"] = "expired"
    elif age > int(updated.get("freshness_seconds", DEFAULT_FRESHNESS_SECONDS) or DEFAULT_FRESHNESS_SECONDS):
        updated["state"] = "stale"
    else:
        updated["state"] = "active"
    return updated


def project_active_executor_status(paths: OmhPaths, *, limit: int | None = 50, now: str | None = None) -> dict[str, Any]:
    bindings = [
        refresh_binding_freshness(binding, now=now, result_status=_terminal_result_status(paths, binding))
        for binding in list_progress_bindings(paths, limit=limit)
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        if str(binding.get("state", "")) == "expired":
            continue
        groups.setdefault(str(binding.get("correlation_root", "")), []).append(binding)

    active_rows: list[dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []
    latest_events: list[dict[str, Any]] = []
    for group in groups.values():
        primary = _choose_primary_binding(group)
        event = _latest_group_payload(paths, group, kind="event")
        report = _latest_group_payload(paths, group, kind="report")
        if not event and not report:
            continue
        if event:
            latest_events.append(_compact_event_projection(event, primary))
        row = _project_binding_row(primary, group, event=event, report=report)
        if str(primary.get("state")) == "active":
            active_rows.append(row)
        elif str(primary.get("state")) == "stale":
            stale_rows.append(row)
    active_rows.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    stale_rows.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    latest_events.sort(key=lambda item: str(item.get("observed_at", "")), reverse=True)
    return {
        "schema_version": "omh_executor_progress_projection/v1",
        "active_executors": active_rows,
        "stale_executors": stale_rows,
        "latest_progress_events": latest_events[: limit or len(latest_events)],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def validate_progress_binding(record: dict[str, Any]) -> list[str]:
    errors = _raw_or_hidden_errors(record)
    if record.get("schema_version") != EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION:
        errors.append("schema_version must be omh_executor_progress_binding/v1")
    target = record.get("target")
    if not isinstance(target, dict):
        errors.append("target must be an object")
        target = {}
    target_type = str(record.get("target_type") or target.get("type") or "")
    target_id = str(record.get("target_id") or target.get("id") or "")
    if target_type not in TARGET_TYPES:
        errors.append("target_type must be run or wrapper_session")
    if not target_id:
        errors.append("target_id is required")
    profile = str(record.get("executor_profile") or record.get("executor") or "")
    if profile not in ALLOWED_EXECUTOR_PROFILES:
        errors.append("executor_profile must be codex, claude_code, or hermes_local")
    if str(record.get("binding_id", "")) != binding_id_for(target_type, target_id, profile):
        errors.append("binding_id must be target_type:target_id:executor_profile")
    if not str(record.get("instance_id", "")).strip():
        errors.append("instance_id is required")
    if not str(record.get("correlation_root", "")):
        errors.append("correlation_root is required")
    if str(record.get("state", "")) not in BINDING_STATES:
        errors.append("state must be active, stale, expired, or closed")
    if "result" in record or "verification" in record or "review" in record or "ci" in record or "merge" in record:
        errors.append("progress binding must not store result, verification, review, CI, or merge evidence")
    if "not result" not in str(record.get("claim_boundary", "")):
        errors.append("claim_boundary must state progress is not result/gate evidence")
    return errors


def validate_progress_event(record: dict[str, Any]) -> list[str]:
    errors = _raw_or_hidden_errors(record)
    if record.get("schema_version") != EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_progress_event/v1")
    if str(record.get("event_type", "")) not in PROGRESS_EVENT_TYPES:
        errors.append("event_type is unsupported")
    if str(record.get("executor_profile", "")) not in ALLOWED_EXECUTOR_PROFILES:
        errors.append("executor_profile must be codex, claude_code, or hermes_local")
    if not str(record.get("binding_id", "")):
        errors.append("binding_id is required")
    if not str(record.get("instance_id", "")).strip():
        errors.append("instance_id is required")
    if not str(record.get("summary", "")).strip():
        errors.append("summary is required")
    if not str(record.get("transition_fingerprint", "")):
        errors.append("transition_fingerprint is required")
    if "not result" not in str(record.get("claim_boundary", "")):
        errors.append("claim_boundary must state progress is not result/gate evidence")
    return errors


def validate_progress_report(record: dict[str, Any]) -> list[str]:
    errors = _raw_or_hidden_errors(record)
    if record.get("schema_version") != EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_progress_report/v1")
    if str(record.get("executor_profile", "")) not in ALLOWED_EXECUTOR_PROFILES:
        errors.append("executor_profile must be codex, claude_code, or hermes_local")
    if not str(record.get("binding_id", "")):
        errors.append("binding_id is required")
    if not str(record.get("instance_id", "")).strip():
        errors.append("instance_id is required")
    if not str(record.get("summary", "")).strip():
        errors.append("summary is required")
    if len(str(record.get("summary", ""))) > 360:
        errors.append("summary must be compact")
    if "not result" not in str(record.get("claim_boundary", "")):
        errors.append("claim_boundary must state progress is not result/gate evidence")
    return errors


def transition_fingerprint(event: dict[str, Any]) -> str:
    signal = event.get("signal", {}) if isinstance(event.get("signal"), dict) else {}
    payload = {
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", ""),
        "evidence_refs": event.get("evidence_refs", []),
        "signal_hashes": {
            key: signal.get(key)
            for key in (
                "git_status_hash",
                "git_diff_stat_hash",
                "progress_status",
                "progress_event_count",
                "latest_progress_event_type",
                "progress_snapshot_hash",
                "codex_artifact_sha256",
            )
            if signal.get(key) not in (None, "")
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _choose_primary_binding(group: list[dict[str, Any]]) -> dict[str, Any]:
    def key(binding: dict[str, Any]) -> tuple[int, str]:
        target_type = str(binding.get("target_type", ""))
        state = str(binding.get("state", ""))
        precedence = {
            ("wrapper_session", "active"): 5,
            ("run", "active"): 4,
            ("wrapper_session", "stale"): 3,
            ("run", "stale"): 2,
        }.get((target_type, state), 1)
        return precedence, str(binding.get("updated_at", ""))

    return sorted(group, key=key, reverse=True)[0]


def _latest_group_payload(paths: OmhPaths, group: list[dict[str, Any]], *, kind: str) -> dict[str, Any]:
    payloads = []
    for binding in group:
        payload = latest_progress_event(paths, binding) if kind == "event" else latest_progress_report(paths, binding)
        if payload:
            payloads.append(payload)
    timestamp_key = "observed_at" if kind == "event" else "reported_at"
    payloads.sort(key=lambda item: str(item.get(timestamp_key, "")), reverse=True)
    return payloads[0] if payloads else {}


def _terminal_result_status(paths: OmhPaths, binding: dict[str, Any]) -> str:
    target = _binding_target(binding)
    target_type = target["type"]
    target_id = target["id"]
    if target_type == "run":
        delegation = read_json_object(paths.runtime_runs_dir / target_id / "delegation.json") or {}
        if bool(delegation.get("observed")):
            result = str(delegation.get("result", ""))
            if result in {"completed", "blocked", "failed"}:
                return result
    if target_type == "wrapper_session":
        record = read_json_object(paths.runtime_wrapper_sessions_dir / target_id / "executor_session.json") or {}
        if bool(record.get("result_observed")):
            result = str(record.get("result", ""))
            if result in {"completed", "blocked", "failed"}:
                return result
    return ""


def _project_binding_row(
    primary: dict[str, Any],
    group: list[dict[str, Any]],
    *,
    event: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    linked = [
        {
            "binding_id": binding.get("binding_id", ""),
            "instance_id": binding.get("instance_id", ""),
            "target_type": binding.get("target_type", ""),
            "target_id": binding.get("target_id", ""),
            "correlation_root": binding.get("correlation_root", ""),
            "state": binding.get("state", ""),
        }
        for binding in group
        if binding.get("binding_id") != primary.get("binding_id")
    ]
    return {
        "primary_binding_id": primary.get("binding_id", ""),
        "primary_instance_id": primary.get("instance_id", ""),
        "binding_id": primary.get("binding_id", ""),
        "instance_id": primary.get("instance_id", ""),
        "target_type": primary.get("target_type", ""),
        "target_id": primary.get("target_id", ""),
        "executor": primary.get("executor_profile", ""),
        "executor_profile": primary.get("executor_profile", ""),
        "correlation_root": primary.get("correlation_root", ""),
        "state": primary.get("state", ""),
        "latest_event": _compact_event_projection(event, primary) if event else {},
        "latest_report": _compact_report_projection(report) if report else {},
        "latest_observed_at": str(event.get("observed_at") or primary.get("last_observed_at") or primary.get("updated_at") or ""),
        "linked_bindings": linked,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _compact_event_projection(event: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": event.get("binding_id") or binding.get("binding_id", ""),
        "instance_id": event.get("instance_id") or binding.get("instance_id", ""),
        "executor_profile": event.get("executor_profile") or binding.get("executor_profile", ""),
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", ""),
        "observed_at": event.get("observed_at", ""),
        "claim_boundary": event.get("claim_boundary", CLAIM_BOUNDARY),
    }


def _compact_report_projection(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": report.get("binding_id", ""),
        "instance_id": report.get("instance_id", ""),
        "event_type": report.get("event_type", ""),
        "status": report.get("status", ""),
        "summary": report.get("summary", ""),
        "reported_at": report.get("reported_at", ""),
        "claim_boundary": report.get("claim_boundary", CLAIM_BOUNDARY),
    }


def _binding_target(binding: dict[str, Any]) -> dict[str, str]:
    target_value = binding.get("target")
    target = target_value if isinstance(target_value, dict) else {}
    return {
        "type": str(binding.get("target_type") or target.get("type") or ""),
        "id": str(binding.get("target_id") or target.get("id") or ""),
    }


def _payload_matches_binding_instance(payload: dict[str, Any], binding: dict[str, Any]) -> bool:
    return str(payload.get("binding_id", "")) == str(binding.get("binding_id", "")) and str(
        payload.get("instance_id", "")
    ) == str(binding.get("instance_id", ""))


def _correlation_aliases(
    *,
    codex_session_ref: str,
    codex_thread_ref: str,
    claude_session_ref: str,
    process_session_id: str,
    worktree: str,
    branch: str,
) -> list[dict[str, str]]:
    aliases = []
    for kind, value in (
        ("codex_session_ref", codex_session_ref),
        ("codex_thread_ref", codex_thread_ref),
        ("claude_session_ref", claude_session_ref),
        ("process_session_id", process_session_id),
        ("worktree", worktree),
        ("branch", branch),
    ):
        if str(value).strip():
            aliases.append({"kind": kind, "value": str(value).strip()})
    return aliases


def _safe_signal(signal: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "executor_profile",
        "process_status",
        "git_status_hash",
        "git_diff_stat_hash",
        "progress_status",
        "progress_event_count",
        "latest_progress_event_type",
        "observable_activity",
        "assistant_visible_summary",
        "progress_snapshot_hash",
        "codex_artifact_sha256",
        "codex_artifact_byte_count",
        "codex_malformed_event_count",
        "evidence_ref_count",
        "explicit_event_type",
        "explicit_summary",
    }
    cleaned = {key: signal.get(key) for key in allowed if signal.get(key) not in (None, "", [], {})}
    _require_valid("signal", _raw_or_hidden_errors(cleaned))
    return cleaned


def _raw_or_hidden_errors(value: Any, *, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_string = str(key)
            lowered = key_string.casefold()
            if lowered in _RAW_OR_HIDDEN_KEYS:
                errors.append(f"{path + '.' if path else ''}{key_string} is not allowed in progress artifacts")
            errors.extend(_raw_or_hidden_errors(item, path=f"{path}.{key_string}" if path else key_string))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_raw_or_hidden_errors(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) > 2000:
            errors.append(f"{path or 'value'} is too large for metadata-only progress")
    return errors


def _require_valid(kind: str, errors: list[str]) -> None:
    if errors:
        raise ExecutorProgressError(f"invalid progress {kind}: {'; '.join(errors)}")


def _compact_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    compacted = []
    for value in values:
        text = _compact_text(str(value), 160)
        if text:
            compacted.append(text)
    return compacted[:8]


def _compact_text(value: str, limit: int) -> str:
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _sanitize_progress_copy(value: str) -> str:
    return sanitize_user_facing_progress_text(value)


def _clean_object(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}


def _optional_pid(value: int | str | None) -> int | str:
    if value in (None, ""):
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _status_for_event_type(event_type: str) -> str:
    if event_type == "executor_completed":
        return "completed"
    if event_type == "executor_blocked":
        return "blocked"
    if event_type == "executor_failed":
        return "failed"
    if event_type == "tests_failed":
        return "failed"
    if event_type == "tests_passed":
        return "passed"
    return "running"


def _safe_progress_summary(summary: dict[str, Any] | None, *, codex_profile: bool) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    _require_valid("progress summary", _raw_or_hidden_errors(summary))
    if codex_profile and summary.get("schema_version") != "codex_progress_summary/v1":
        raise ExecutorProgressError("Codex progress signals must use codex_progress_summary/v1")
    latest = summary.get("latest_progress_event", {}) if isinstance(summary.get("latest_progress_event"), dict) else {}
    raw_artifact = summary.get("raw_output_artifact", {}) if isinstance(summary.get("raw_output_artifact"), dict) else {}
    status = _compact_text(str(summary.get("status", "")), 80)
    event_count = _safe_int(summary.get("event_count"), 0)
    observable_activity = [
        _compact_text(str(item), 120)
        for item in summary.get("observable_activity", [])
        if isinstance(summary.get("observable_activity", []), list)
    ][:8]
    assistant_visible_summary = _compact_text(
        _sanitize_progress_copy(
            str(summary.get("latest_assistant_visible_message") or summary.get("chat_summary") or summary.get("summary") or "")
        ),
        240,
    )
    latest_event_type = _compact_text(str(latest.get("event_type", "")), 80)
    artifact_sha256 = _compact_text(str(raw_artifact.get("sha256", "")), 80)
    normalized = {
        "status": status,
        "event_count": event_count,
        "malformed_event_count": _safe_int(summary.get("malformed_event_count"), 0),
        "latest_progress_event_type": latest_event_type,
        "observable_activity": observable_activity,
        "assistant_visible_summary": assistant_visible_summary,
        "artifact_sha256": artifact_sha256,
        "artifact_byte_count": _safe_int(raw_artifact.get("byte_count"), 0),
    }
    normalized["summary_hash"] = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        **normalized,
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hash_if_present(value: str) -> str:
    if not value.strip():
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _signal_fingerprint(signal: dict[str, Any]) -> str:
    if not signal:
        return ""
    safe = _safe_signal(signal)
    return hashlib.sha256(json.dumps(safe, sort_keys=True).encode("utf-8")).hexdigest()


def _summary_for_event_type(event_type: str) -> str:
    summaries = {
        "executor_dispatched": "The coding executor was dispatched; no result is observed yet.",
        "repo_exploration": "The coding executor is inspecting the repository; no result is observed yet.",
        "running_no_diff_observed": "The coding executor is active, but no file diff is observed yet.",
        "diff_started": "The coding executor has started changing files; no verification result is observed yet.",
        "tests_started": "The coding executor has started verification; no test result is observed yet.",
        "tests_failed": "The coding executor observed a failing verification signal.",
        "tests_passed": "The coding executor observed a passing verification signal.",
        "executor_completed": "The coding executor reported completion, but separate result evidence is still required.",
        "executor_blocked": "The coding executor reported a blocker.",
        "executor_failed": "The coding executor reported a failure.",
        "progress_observed": "The coding executor emitted a safe progress signal.",
    }
    return summaries.get(event_type, "Executor progress was observed.")


def _report_sentence(event: dict[str, Any], *, source_language: str = "") -> str:
    summary = _compact_text(str(event.get("summary", "")), 240)
    if source_language.casefold().startswith("ko"):
        return f"코딩 실행자가 진행 중입니다: {summary}"
    return summary


def _minimum_interval_elapsed(previous: str, current: str, seconds: int) -> bool:
    if seconds <= 0 or not previous:
        return True
    age = _seconds_between(previous, current)
    return age is None or age >= seconds


def _seconds_between(previous: str, current: str) -> float | None:
    try:
        prev_dt = _parse_time(previous)
        current_dt = _parse_time(current)
    except ValueError:
        return None
    return (current_dt - prev_dt).total_seconds()


def _parse_time(value: str) -> datetime:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("empty timestamp")
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
