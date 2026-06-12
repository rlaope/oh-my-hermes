from __future__ import annotations

import hashlib
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ..ingress import CHAT_SOURCES, compact_source_metadata, extract_message_text, extract_source_metadata
from ..routing.chat import CONFIDENCE_LEVELS
from ..executors import CODING_EXECUTOR_TARGETS, executor_selection_for_target
from .lifecycle import report_codex_delegation_lifecycle, start_codex_delegation_lifecycle
from ..local_store import atomic_write_json, ensure_dir, ensure_file, read_json_object, read_jsonl_objects, utc_now
from ..paths import OmhPaths
from ..runtime.records import build_event_record, build_wrapper_session_record, validate_event_record, validate_wrapper_session_record
from .contract import build_chat_interaction_payload, build_chat_status_interaction
from ..coding_delegation import build_coding_delegation_payload


WRAPPER_SESSION_RESULT_SCHEMA_VERSION = "wrapper_session_result/v1"
PLAN_DECISION_TRANSITIONS = {
    "plan_presented": {"accept", "revise", "cancel"},
    "plan_accepted": {"accept", "revise", "cancel"},
    "executor_choice_required": {"cancel"},
    "executor_selected": {"cancel"},
    "prompt_handoff_prepared": set(),
    "runtime_handoff_prepared": set(),
    "revision_requested": {"revise", "cancel"},
    "clarifying": {"cancel"},
    "routed": {"cancel"},
    "cancelled": set(),
    "handoff_prepared": set(),
}


class WrapperSessionError(ValueError):
    pass


def session_id_for_thread_key(thread_key: str) -> str:
    if not thread_key:
        raise WrapperSessionError("wrapper session requires a thread_key")
    return f"ws-{hashlib.sha256(thread_key.encode('utf-8')).hexdigest()[:24]}"


def create_or_resume_wrapper_session(
    paths: OmhPaths,
    event_or_message: dict[str, Any] | str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
    source_metadata: dict[str, str] | None = None,
    executor_target: str = "choose",
    target_notice: dict[str, object] | None = None,
) -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise WrapperSessionError(f"unsupported wrapper session source: {source}")
    if min_confidence not in CONFIDENCE_LEVELS:
        raise WrapperSessionError(f"unsupported wrapper session confidence threshold: {min_confidence}")
    interaction = build_chat_interaction_payload(
        event_or_message,
        source=source,
        limit=limit,
        min_confidence=min_confidence,
        include_message=False,
        source_metadata=source_metadata,
        executor_target=executor_target,
        target_notice=target_notice,
    )
    thread_key = str(interaction["thread_key"])
    session_id = session_id_for_thread_key(thread_key)
    existing = read_wrapper_session(paths, session_id)
    session_dir = _session_dir(paths, session_id)
    if existing:
        append_wrapper_session_event(
            session_dir,
            {
                "event": "session_resumed",
                "message": "wrapper session resumed",
                "data": {"status": existing["status"], "thread_key": thread_key},
            },
        )
        session = existing
        resumed = True
    else:
        session = _session_from_interaction(session_id, interaction)
        write_wrapper_session(paths, session)
        append_wrapper_session_event(
            session_dir,
            {
                "event": "session_started",
                "message": "wrapper session started",
                "data": {"status": session["status"], "thread_key": thread_key},
            },
        )
        resumed = False
    return {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "resumed": resumed,
        "session": session,
        "interaction": interaction,
        "status": build_wrapper_session_status(paths, session_id),
    }


def record_plan_decision(paths: OmhPaths, session_id: str, decision: str) -> dict[str, object]:
    if decision not in {"accept", "revise", "cancel"}:
        raise WrapperSessionError("plan decision must be accept, revise, or cancel")
    session = _existing_session(paths, session_id)
    current_status = str(session["status"])
    allowed = PLAN_DECISION_TRANSITIONS.get(current_status, set())
    if decision not in allowed:
        raise WrapperSessionError(f"cannot {decision.replace('_', ' ')} a wrapper session while status is {current_status}")
    accept_status = _accepted_status_for_session(session)
    updates = {
        "accept": {"status": accept_status, "decision": "plan_accepted"},
        "revise": {"status": "revision_requested", "decision": "plan_revision_requested"},
        "cancel": {"status": "cancelled", "decision": "plan_cancelled"},
    }[decision]
    session = {**session, **updates, "updated_at": utc_now()}
    write_wrapper_session(paths, session)
    append_wrapper_session_event(
        _session_dir(paths, session_id),
        {
            "event": f"plan_{updates['decision']}",
            "message": f"wrapper recorded {updates['decision']}",
            "data": {"status": session["status"], "decision": session["decision"]},
        },
    )
    return {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "session": session,
        "status": build_wrapper_session_status(paths, session_id),
    }


def select_wrapper_session_executor(
    paths: OmhPaths,
    session_id: str,
    executor_target: str,
    *,
    dispatch_policy: str | None = None,
) -> dict[str, object]:
    if executor_target not in CODING_EXECUTOR_TARGETS:
        raise WrapperSessionError(f"unsupported wrapper session executor: {executor_target}")
    session = _existing_session(paths, session_id)
    if session["status"] not in {"plan_accepted", "executor_choice_required", "executor_selected"}:
        raise WrapperSessionError(f"cannot select executor while status is {session['status']}")
    selection = executor_selection_for_target(executor_target, action="delegate")
    if selection.choice_required:
        raise WrapperSessionError("select-executor requires a concrete executor profile, not choose")
    policy = dispatch_policy or selection.dispatch_policy
    session = {
        **session,
        "status": "executor_selected",
        "work_owner_mode": selection.work_owner_mode,
        "selected_executor_profile": selection.selected_executor_profile,
        "dispatch_policy": policy,
        "updated_at": utc_now(),
    }
    write_wrapper_session(paths, session)
    append_wrapper_session_event(
        _session_dir(paths, session_id),
        {
            "event": "executor_selected",
            "message": "wrapper session selected executor/runtime profile",
            "data": {
                "work_owner_mode": selection.work_owner_mode,
                "selected_executor_profile": selection.selected_executor_profile,
                "dispatch_policy": policy,
                "dispatchable": selection.dispatchable,
            },
        },
    )
    return {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "session": session,
        "status": build_wrapper_session_status(paths, session_id),
    }


def prepare_wrapper_session_handoff(
    paths: OmhPaths,
    session_id: str,
    event_or_message: dict[str, Any] | str,
    *,
    limit: int = 3,
    include_message: bool = False,
    source_metadata: dict[str, str] | None = None,
    executor_target: str | None = None,
    context_pack: dict[str, object] | None = None,
) -> dict[str, object]:
    session = _existing_session(paths, session_id)
    if session["status"] == "cancelled":
        raise WrapperSessionError("cannot prepare a handoff for a cancelled wrapper session")
    if session.get("current_run_id"):
        if session["status"] != "handoff_prepared":
            raise WrapperSessionError("wrapper session current_run_id is only valid after handoff preparation")
        run_id = str(session["current_run_id"])
        if _run_owned_by_other_session(paths, run_id, str(session["session_id"])):
            raise WrapperSessionError("wrapper session current_run_id is already linked to another wrapper session")
        _ensure_handoff_prepared_event(paths, session, run_id, recovered=True)
        return {
            "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
            "session": session,
            "status": build_wrapper_session_status(paths, session_id),
            "handoff": report_codex_delegation_lifecycle(paths, run_id),
        }
    if session["status"] == "prompt_handoff_prepared":
        return {
            "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
            "session": session,
            "status": build_wrapper_session_status(paths, session_id),
            "handoff": {"prompt_handoff": session.get("prompt_handoff", {})},
        }
    if session["status"] == "runtime_handoff_prepared":
        return {
            "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
            "session": session,
            "status": build_wrapper_session_status(paths, session_id),
            "handoff": _runtime_session_handoff_envelope(session.get("runtime_handoff", {})),
        }
    if session["status"] == "executor_choice_required" and not executor_target:
        raise WrapperSessionError("wrapper session requires executor selection before preparing a handoff")
    if executor_target:
        select_wrapper_session_executor(paths, session_id, executor_target)
        session = _existing_session(paths, session_id)
    if session["status"] not in {"plan_accepted", "executor_selected"}:
        raise WrapperSessionError("wrapper session plan must be accepted before preparing a handoff")
    selected_executor = str(session.get("selected_executor_profile") or "codex")
    if session.get("work_owner_mode") == "runtime_handoff" and selected_executor:
        return _prepare_runtime_session_handoff(
            paths,
            session,
            event_or_message,
            limit=limit,
            include_message=include_message,
            source_metadata=source_metadata,
            executor_target=selected_executor,
            context_pack=context_pack,
        )
    if selected_executor and selected_executor != "codex":
        return _prepare_prompt_only_session_handoff(
            paths,
            session,
            event_or_message,
            limit=limit,
            include_message=include_message,
            source_metadata=source_metadata,
            executor_target=selected_executor,
            context_pack=context_pack,
        )
    message = extract_message_text(event_or_message)
    metadata = _source_metadata(event_or_message)
    metadata.update({str(key): str(value) for key, value in (source_metadata or {}).items() if str(value)})
    metadata.update({str(key): str(value) for key, value in session.get("source_metadata", {}).items() if str(value)})
    metadata = _compact_coding_source_metadata(metadata)
    message_sha256 = hashlib.sha256(message.encode("utf-8")).hexdigest()
    recovered_run_id = _find_recoverable_prepared_handoff_run(paths, session, message_sha256, metadata)
    if recovered_run_id:
        return _link_prepared_handoff_run(paths, session, recovered_run_id, recovered=True)
    append_wrapper_session_event(
        _session_dir(paths, session_id),
        {
            "event": "handoff_prepare_started",
            "message": "wrapper session started preparing coding handoff",
            "data": {"message_sha256": message_sha256, "message_length": len(message)},
        },
    )
    lifecycle = start_codex_delegation_lifecycle(
        paths,
        message,
        source=str(session["source"]),
        source_metadata=metadata,
        limit=limit,
        include_message=include_message,
        context_pack=context_pack,
    )
    run_id = str(lifecycle["run"]["run_id"])
    linked = _link_prepared_handoff_run(paths, session, run_id, recovered=False)
    lifecycle["status"] = report_codex_delegation_lifecycle(paths, run_id)
    linked["handoff"] = lifecycle
    return linked


def _prepare_prompt_only_session_handoff(
    paths: OmhPaths,
    session: dict[str, Any],
    event_or_message: dict[str, Any] | str,
    *,
    limit: int,
    include_message: bool,
    source_metadata: dict[str, str] | None,
    executor_target: str,
    context_pack: dict[str, object] | None,
) -> dict[str, object]:
    message = extract_message_text(event_or_message)
    metadata = _source_metadata(event_or_message)
    metadata.update({str(key): str(value) for key, value in (source_metadata or {}).items() if str(value)})
    metadata.update({str(key): str(value) for key, value in session.get("source_metadata", {}).items() if str(value)})
    metadata = _compact_coding_source_metadata(metadata)
    payload = build_coding_delegation_payload(
        message,
        source=str(session["source"]),
        limit=limit,
        include_message=include_message,
        source_metadata=metadata,
        executor_target=executor_target,
        context_pack=context_pack,
    )
    prompt_handoff = payload.get("prompt_handoff")
    if not isinstance(prompt_handoff, dict):
        raise WrapperSessionError("selected executor produced no prompt handoff")
    session_id = str(session["session_id"])
    session = {
        **session,
        "status": "prompt_handoff_prepared",
        "work_owner_mode": "prompt_only_handoff",
        "selected_executor_profile": executor_target,
        "dispatch_policy": "prepare_only",
        "prompt_handoff": prompt_handoff,
        "current_run_id": "",
        "updated_at": utc_now(),
    }
    write_wrapper_session(paths, session)
    append_wrapper_session_event(
        _session_dir(paths, session_id),
        {
            "event": "prompt_handoff_prepared",
            "message": "wrapper session prepared prompt-only coding handoff",
            "data": {
                "selected_executor_profile": executor_target,
                "dispatchable": False,
                "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "message_length": len(message),
            },
        },
    )
    result: dict[str, object] = {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "session": session,
        "status": build_wrapper_session_status(paths, session_id),
        "handoff": {
            "schema_version": "prompt_only_session_handoff/v1",
            "prompt_handoff": prompt_handoff,
            "runtime": {
                "run_created": False,
                "reason": "prompt_only_handoff_is_not_lifecycle_backed",
            },
        },
    }
    if include_message and "prompt_handoff_prompt" in payload:
        result["prompt_handoff_prompt"] = payload["prompt_handoff_prompt"]
    return result


def _prepare_runtime_session_handoff(
    paths: OmhPaths,
    session: dict[str, Any],
    event_or_message: dict[str, Any] | str,
    *,
    limit: int,
    include_message: bool,
    source_metadata: dict[str, str] | None,
    executor_target: str,
    context_pack: dict[str, object] | None,
) -> dict[str, object]:
    message = extract_message_text(event_or_message)
    metadata = _source_metadata(event_or_message)
    metadata.update({str(key): str(value) for key, value in (source_metadata or {}).items() if str(value)})
    metadata.update({str(key): str(value) for key, value in session.get("source_metadata", {}).items() if str(value)})
    metadata = _compact_coding_source_metadata(metadata)
    payload = build_coding_delegation_payload(
        message,
        source=str(session["source"]),
        limit=limit,
        include_message=include_message,
        source_metadata=metadata,
        executor_target=executor_target,
        context_pack=context_pack,
    )
    runtime_handoff = payload.get("runtime_handoff")
    if not isinstance(runtime_handoff, dict):
        raise WrapperSessionError("selected runtime produced no runtime handoff")
    session_id = str(session["session_id"])
    session = {
        **session,
        "status": "runtime_handoff_prepared",
        "work_owner_mode": "runtime_handoff",
        "selected_executor_profile": executor_target,
        "dispatch_policy": "prepare_only",
        "prompt_handoff": {},
        "runtime_handoff": runtime_handoff,
        "current_run_id": "",
        "updated_at": utc_now(),
    }
    write_wrapper_session(paths, session)
    append_wrapper_session_event(
        _session_dir(paths, session_id),
        {
            "event": "runtime_handoff_prepared",
            "message": "wrapper session prepared runtime coding handoff",
            "data": {
                "selected_executor_profile": executor_target,
                "dispatchable": False,
                "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "message_length": len(message),
                "team_swarm_guidance": True,
                "worktree_guidance": True,
            },
        },
    )
    result: dict[str, object] = {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "session": session,
        "status": build_wrapper_session_status(paths, session_id),
        "handoff": _runtime_session_handoff_envelope(runtime_handoff),
    }
    if include_message and "runtime_handoff_prompt" in payload:
        result["runtime_handoff_prompt"] = payload["runtime_handoff_prompt"]
    return result


def _runtime_session_handoff_envelope(runtime_handoff: object) -> dict[str, object]:
    return {
        "schema_version": "runtime_session_handoff/v1",
        "runtime_handoff": runtime_handoff if isinstance(runtime_handoff, dict) else {},
        "runtime": {
            "run_created": False,
            "reason": "runtime_handoff_is_not_lifecycle_backed",
        },
    }


def build_wrapper_session_status(paths: OmhPaths, session_id: str) -> dict[str, object]:
    session = _existing_session(paths, session_id)
    run_id = str(session.get("current_run_id", ""))
    if run_id:
        runtime_status = report_codex_delegation_lifecycle(paths, run_id)
        interaction = build_chat_status_interaction(
            runtime_status,
            source=str(session["source"]),
            source_metadata={str(key): str(value) for key, value in session.get("source_metadata", {}).items()},
        )
        return {
            "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
            "session_id": session_id,
            "thread_key": session["thread_key"],
            "current_run_id": run_id,
            "session_status": session["status"],
            "runtime_status": runtime_status,
            "chat_response": interaction["chat_response"],
            "claim_boundary": "Execution claims come from the linked runtime run ledger, not the wrapper session.",
        }
    return {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "session_id": session_id,
        "thread_key": session["thread_key"],
        "current_run_id": "",
        "session_status": session["status"],
        "work_owner_mode": session.get("work_owner_mode", "external_executor"),
        "selected_executor_profile": session.get("selected_executor_profile"),
        "dispatch_policy": session.get("dispatch_policy", "ask_before_dispatch"),
        "prompt_handoff": session.get("prompt_handoff", {}) if session["status"] == "prompt_handoff_prepared" else {},
        "runtime_handoff": session.get("runtime_handoff", {}) if session["status"] == "runtime_handoff_prepared" else {},
        "next_action": _next_action_for_session(session),
        "chat_response": _session_chat_response(session),
        "claim_boundary": "Wrapper session state is not execution evidence.",
    }


def list_wrapper_sessions(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for session_json in sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json")):
        session = read_json_object(session_json)
        if session:
            sessions.append(session)
    return sessions


def show_wrapper_session(paths: OmhPaths, session_id: str) -> dict[str, Any]:
    session_dir = _session_dir(paths, session_id)
    session = read_json_object(session_dir / "session.json")
    if not session:
        raise FileNotFoundError(session_id)
    events, event_errors = read_wrapper_session_events_result(session_dir)
    result = {
        "session": session,
        "events": events,
    }
    if event_errors:
        result["event_errors"] = event_errors
    return result


def read_wrapper_session(paths: OmhPaths, session_id: str) -> dict[str, Any] | None:
    return read_json_object(_session_dir(paths, session_id) / "session.json")


def write_wrapper_session(paths: OmhPaths, session: dict[str, Any]) -> dict[str, Any]:
    record = build_wrapper_session_record(session)
    atomic_write_json(_session_dir(paths, str(record["session_id"])) / "session.json", record, private=True)
    return record


def append_wrapper_session_event(session_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    item = build_event_record(event)
    errors = validate_event_record(item)
    if errors:
        raise WrapperSessionError(errors[0])
    ensure_dir(session_dir, private=True)
    events_path = session_dir / "events.jsonl"
    ensure_file(events_path, private=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")
    return item


def read_wrapper_session_events(session_dir: Path) -> list[dict[str, Any]]:
    return read_wrapper_session_events_result(session_dir)[0]


def read_wrapper_session_events_result(session_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    return read_jsonl_objects(session_dir / "events.jsonl")


def validate_wrapper_sessions(paths: OmhPaths, session_id: str | None = None) -> dict[str, Any]:
    if session_id:
        session_dirs = [_session_dir(paths, session_id)]
    else:
        session_dirs = (
            sorted(path for path in paths.runtime_wrapper_sessions_dir.glob("*") if path.is_dir())
            if paths.runtime_wrapper_sessions_dir.exists()
            else []
        )
    results = [_validate_wrapper_session_dir(session_dir) for session_dir in session_dirs]
    return {"ok": all(result["ok"] for result in results), "sessions": results}


def _link_prepared_handoff_run(paths: OmhPaths, session: dict[str, Any], run_id: str, *, recovered: bool) -> dict[str, object]:
    session = {
        **session,
        "status": "handoff_prepared",
        "work_owner_mode": "external_executor",
        "selected_executor_profile": "codex",
        "dispatch_policy": "ask_before_dispatch",
        "prompt_handoff": {},
        "runtime_handoff": {},
        "current_run_id": run_id,
        "updated_at": utc_now(),
    }
    _ensure_handoff_prepared_event(paths, session, run_id, recovered=recovered)
    write_wrapper_session(paths, session)
    return {
        "schema_version": WRAPPER_SESSION_RESULT_SCHEMA_VERSION,
        "session": session,
        "status": build_wrapper_session_status(paths, str(session["session_id"])),
        "handoff": _existing_lifecycle_payload(paths, run_id),
    }


def _find_recoverable_prepared_handoff_run(
    paths: OmhPaths,
    session: dict[str, Any],
    message_sha256: str,
    expected_metadata: dict[str, str],
) -> str:
    session_dir = _session_dir(paths, str(session["session_id"]))
    if not _has_prepare_started_event(session_dir, message_sha256):
        return ""
    for run_json in sorted(paths.runtime_runs_dir.glob("*/run.json"), reverse=True):
        run = read_json_object(run_json)
        if not _is_prepared_coding_run(run):
            continue
        run_id = str(run.get("run_id") or run_json.parent.name)
        if _run_owned_by_other_session(paths, run_id, str(session["session_id"])):
            continue
        coding = read_json_object(run_json.parent / "coding_delegation.json")
        if not _is_matching_coding_handoff(coding, session, message_sha256, expected_metadata):
            continue
        return run_id
    return ""


def _has_prepare_started_event(session_dir: Path, message_sha256: str) -> bool:
    return any(
        event.get("event") == "handoff_prepare_started"
        and isinstance(event.get("data"), dict)
        and event["data"].get("message_sha256") == message_sha256
        for event in read_wrapper_session_events(session_dir)
    )


def _is_prepared_coding_run(run: Any) -> bool:
    return (
        isinstance(run, dict)
        and run.get("artifact_kind") == "prepared_coding_delegation"
        and run.get("phase") == "prepared"
        and run.get("observation_status") == "prepared_not_observed"
    )


def _is_matching_coding_handoff(
    coding: Any,
    session: dict[str, Any],
    message_sha256: str,
    expected_metadata: dict[str, str],
) -> bool:
    if not isinstance(coding, dict):
        return False
    handoff = coding.get("executor_handoff")
    if not isinstance(handoff, dict) or handoff.get("executor_target") != "codex":
        return False
    if coding.get("message_sha256") != message_sha256 or coding.get("status") != "prepared_not_observed":
        return False
    if coding.get("source") != session.get("source"):
        return False
    coding_metadata = coding.get("source_metadata", {})
    if not isinstance(coding_metadata, dict):
        return False
    compact_coding_metadata = _compact_coding_source_metadata(coding_metadata)
    return compact_coding_metadata == expected_metadata


def _ensure_handoff_prepared_event(paths: OmhPaths, session: dict[str, Any], run_id: str, *, recovered: bool) -> None:
    session_dir = _session_dir(paths, str(session["session_id"]))
    if _has_handoff_prepared_event(session_dir, run_id):
        return
    append_wrapper_session_event(
        session_dir,
        {
            "event": "handoff_prepared",
            "message": "wrapper session linked prepared coding handoff",
            "data": {"run_id": run_id, "status": "handoff_prepared", "recovered": recovered},
        },
    )


def _has_handoff_prepared_event(session_dir: Path, run_id: str) -> bool:
    return any(
        event.get("event") == "handoff_prepared" and isinstance(event.get("data"), dict) and event["data"].get("run_id") == run_id
        for event in read_wrapper_session_events(session_dir)
    )


def _run_owned_by_other_session(paths: OmhPaths, run_id: str, session_id: str) -> bool:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return False
    for session_json in sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json")):
        if session_json.parent.name == session_id:
            continue
        other = read_json_object(session_json)
        if other and other.get("current_run_id") == run_id:
            return True
    return False


def _compact_coding_source_metadata(metadata: Any) -> dict[str, str]:
    return compact_source_metadata(metadata)


def _existing_lifecycle_payload(paths: OmhPaths, run_id: str) -> dict[str, object]:
    run_dir = paths.runtime_runs_dir / run_id
    return {
        "schema_version": "coding_lifecycle/v1",
        "run": read_json_object(run_dir / "run.json"),
        "coding_delegation": read_json_object(run_dir / "coding_delegation.json"),
        "status": report_codex_delegation_lifecycle(paths, run_id),
    }


def _validate_wrapper_session_dir(session_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    session_id = session_dir.name
    session_path = session_dir / "session.json"
    try:
        session = read_json_object(session_path)
    except (OSError, JSONDecodeError, ValueError) as exc:
        session = None
        errors.append(f"{session_path}: {exc}")
    if not session:
        errors.append(f"{session_path}: missing session.json")
    else:
        errors.extend(f"{session_path}: {error}" for error in validate_wrapper_session_record(session))
        if session.get("session_id") != session_id:
            errors.append(f"{session_path}: session_id must match directory name")
    events_path = session_dir / "events.jsonl"
    if events_path.exists():
        events, event_errors = read_jsonl_objects(events_path)
        errors.extend(event_errors)
        for index, event in enumerate(events, start=1):
            errors.extend(f"{events_path}:{index}: {error}" for error in validate_event_record(event))
    else:
        errors.append(f"{events_path}: missing events.jsonl")
    return {"session_id": session_id, "ok": not errors, "errors": errors}


def _session_from_interaction(session_id: str, interaction: dict[str, object]) -> dict[str, Any]:
    route = interaction.get("route")
    route = route if isinstance(route, dict) else {}
    plan_payload = interaction.get("plan")
    plan = plan_payload.get("plan", {}) if isinstance(plan_payload, dict) else {}
    plan = plan if isinstance(plan, dict) else {}
    contract = plan_payload.get("wrapper_contract", {}) if isinstance(plan_payload, dict) else {}
    coding_delegate = contract.get("coding_delegate", {}) if isinstance(contract, dict) else {}
    work_owner_mode = str(interaction.get("work_owner_mode", "external_executor"))
    selected_executor = interaction.get("selected_executor_profile")
    dispatch_policy = str(interaction.get("dispatch_policy", "ask_before_dispatch"))
    return build_wrapper_session_record(
        {
            "session_id": session_id,
            "thread_key": interaction["thread_key"],
            "source": interaction["source"],
            "source_metadata": interaction.get("source_metadata", {}),
            "message_sha256": interaction["message_sha256"],
            "message_length": interaction["message_length"],
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "status": _status_from_interaction(interaction),
            "decision": "none",
            "route": route,
            "plan": {
                "status": plan.get("status", ""),
                "recommended_workflow": plan.get("recommended_workflow", ""),
                "recommended_harness": plan.get("recommended_harness", ""),
                "coding_delegate_available": str(bool(coding_delegate.get("available", False))).lower(),
            },
            "work_owner_mode": work_owner_mode,
            "selected_executor_profile": selected_executor if isinstance(selected_executor, str) else None,
            "dispatch_policy": dispatch_policy,
            "prompt_handoff": {},
            "runtime_handoff": {},
            "current_run_id": "",
        }
    )


def _accepted_status_for_session(session: dict[str, Any]) -> str:
    plan = session.get("plan", {})
    coding_delegate_available = isinstance(plan, dict) and str(plan.get("coding_delegate_available", "")) == "true"
    selected = session.get("selected_executor_profile")
    if coding_delegate_available and not selected:
        return "executor_choice_required"
    return "plan_accepted"


def _status_from_interaction(interaction: dict[str, object]) -> str:
    next_action = str(interaction.get("next_action", ""))
    if next_action == "cancel":
        return "cancelled"
    if next_action == "answer_clarification":
        return "clarifying"
    if next_action == "dispatch_to_workflow":
        return "routed"
    if str(interaction.get("mode", "")) == "route":
        return "routed"
    if next_action == "present_plan":
        return "plan_presented"
    return "plan_presented"


def _source_metadata(event_or_message: dict[str, Any] | str) -> dict[str, str]:
    if not isinstance(event_or_message, dict):
        return {}
    return extract_source_metadata(event_or_message)


def _session_dir(paths: OmhPaths, session_id: str) -> Path:
    return paths.runtime_wrapper_sessions_dir / session_id


def _existing_session(paths: OmhPaths, session_id: str) -> dict[str, Any]:
    session = read_wrapper_session(paths, session_id)
    if not session:
        raise FileNotFoundError(session_id)
    return session


def _next_action_for_session(session: dict[str, Any]) -> str:
    return {
        "plan_presented": "accept_or_revise_plan",
        "clarifying": "answer_clarification",
        "routed": "dispatch_to_workflow",
        "plan_accepted": "prepare_handoff",
        "executor_choice_required": "choose_executor",
        "executor_selected": "prepare_handoff",
        "prompt_handoff_prepared": "show_prompt_handoff",
        "runtime_handoff_prepared": "show_runtime_handoff",
        "revision_requested": "revise_plan",
        "cancelled": "cancelled",
        "handoff_prepared": "show_status",
    }.get(str(session.get("status")), "show_status")


def _session_chat_response(session: dict[str, Any]) -> dict[str, object]:
    status = str(session.get("status", "plan_presented"))
    thread_key = str(session.get("thread_key", ""))
    if status == "plan_presented":
        return _chat_response(
            kind="plan",
            headline="I drafted a plan for this request.",
            body="Please accept or revise the plan before any coding handoff is prepared.",
            phase="planning",
            next_action="accept_or_revise_plan",
            thread_key=thread_key,
            actions=[
                _action("accept_plan", "Accept plan", "primary"),
                _action("revise_plan", "Revise plan", "secondary"),
                _action("cancel", "Cancel", "secondary"),
            ],
            claim_boundary="A wrapper session plan is not execution evidence.",
        )
    if status == "plan_accepted":
        return _chat_response(
            kind="handoff",
            headline="The plan is accepted.",
            body="I can prepare the selected executor/runtime handoff, but no executor or runtime work is observed yet.",
            phase="plan_accepted",
            next_action="prepare_handoff",
            thread_key=thread_key,
            actions=[_action("prepare_handoff", "Prepare handoff", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="Plan acceptance is not execution evidence.",
        )
    if status == "executor_choice_required":
        return _chat_response(
            kind="handoff",
            headline="Choose who should own the coding work.",
            body="Hermes can keep shaping the work, prepare a prompt-only handoff, or prepare a Codex lifecycle handoff.",
            phase="executor_choice_required",
            next_action="choose_executor",
            thread_key=thread_key,
            actions=[_action("choose_executor", "Choose executor", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="Choosing an executor is not dispatch or implementation evidence.",
        )
    if status == "executor_selected":
        selected = str(session.get("selected_executor_profile") or "Hermes")
        if session.get("work_owner_mode") == "runtime_handoff":
            return _chat_response(
                kind="handoff",
                headline="The runtime choice is recorded.",
                body=f"I can prepare the {selected} runtime contract next. No runtime work, team, swarm, or worktree is observed yet.",
                phase="executor_selected",
                next_action="prepare_handoff",
                thread_key=thread_key,
                actions=[_action("prepare_handoff", "Prepare handoff", "primary"), _action("cancel", "Cancel", "secondary")],
                claim_boundary="Runtime selection is not runtime start, dispatch, or implementation evidence.",
            )
        return _chat_response(
            kind="handoff",
            headline="The executor choice is recorded.",
            body=f"I can prepare the {selected} handoff next. No executor work is observed yet.",
            phase="executor_selected",
            next_action="prepare_handoff",
            thread_key=thread_key,
            actions=[_action("prepare_handoff", "Prepare handoff", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="Executor selection is not dispatch evidence.",
        )
    if status == "prompt_handoff_prepared":
        selected = str(session.get("selected_executor_profile") or "executor")
        return _chat_response(
            kind="handoff",
            headline="A prompt handoff is ready.",
            body=f"The {selected} prompt is prepared for copy/pass-through only; no runtime run or executor evidence exists yet.",
            phase="prompt_handoff_prepared",
            next_action="show_prompt_handoff",
            thread_key=thread_key,
            actions=[
                _action("show_prompt_handoff", "Show prompt", "primary"),
                _action("copy_prompt_handoff", "Copy prompt", "secondary"),
                _action("show_status", "Show status", "secondary"),
            ],
            claim_boundary="Prompt handoff is not dispatch, implementation, review, CI, or merge evidence.",
        )
    if status == "runtime_handoff_prepared":
        selected = str(session.get("selected_executor_profile") or "runtime")
        primary_action = "start_hermes_coding" if selected == "hermes" else "start_runtime"
        return _chat_response(
            kind="handoff",
            headline="A runtime handoff is ready.",
            body=f"The {selected} runtime contract is prepared with team/swarm, worker-protocol, and worktree guidance; no runtime evidence exists yet.",
            phase="runtime_handoff_prepared",
            next_action="show_runtime_handoff",
            thread_key=thread_key,
            actions=[
                _action("show_runtime_handoff", "Show runtime", "primary"),
                _action(primary_action, "Start runtime", "primary", enabled=False),
                _action("prepare_worktree", "Prepare worktree", "secondary", enabled=False),
                _action("start_team", "Start team", "secondary", enabled=False),
                _action("start_swarm", "Start swarm", "secondary", enabled=False),
                _action("show_status", "Show status", "secondary"),
            ],
            claim_boundary="Runtime handoff is not runtime start, worktree creation, worker dispatch, implementation, review, CI, or merge evidence.",
        )
    if status == "revision_requested":
        return _chat_response(
            kind="clarification",
            headline="A plan revision was requested.",
            body="I will keep the request in planning until a revised plan is accepted.",
            phase="revision_requested",
            next_action="revise_plan",
            thread_key=thread_key,
            actions=[_action("revise_plan", "Revise plan", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="Revision request is not execution evidence.",
        )
    if status == "cancelled":
        return _chat_response(
            kind="status",
            headline="This wrapper session is cancelled.",
            body="No handoff or executor work should be inferred from this session.",
            phase="cancelled",
            next_action="cancelled",
            thread_key=thread_key,
            actions=[],
            claim_boundary="Cancelled session has no execution evidence.",
        )
    if status == "clarifying":
        return _chat_response(
            kind="clarification",
            headline="I need one clarification before routing this.",
            body="Please answer the clarification before any plan or handoff is prepared.",
            phase="clarifying",
            next_action="answer_clarification",
            thread_key=thread_key,
            actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="No execution has started.",
        )
    return _chat_response(
        kind="status",
        headline="I have a conservative wrapper-session status.",
        body="Session state is available, but execution claims require linked runtime evidence.",
        phase="status",
        next_action="show_status",
        thread_key=thread_key,
        actions=[],
        claim_boundary="Wrapper session state is not execution evidence.",
    )


def _chat_response(
    *,
    kind: str,
    headline: str,
    body: str,
    phase: str,
    next_action: str,
    thread_key: str,
    actions: list[dict[str, object]],
    claim_boundary: str,
) -> dict[str, object]:
    return {
        "schema_version": "chat_response/v1",
        "kind": kind,
        "visibility": "thread",
        "headline": headline,
        "body": body,
        "state": {"phase": phase, "next_action": next_action, "thread_key": thread_key},
        "actions": actions,
        "claim_boundary": claim_boundary,
    }


def _action(action_id: str, label: str, style: str, *, enabled: bool = True) -> dict[str, object]:
    return {"id": action_id, "label": label, "style": style, "enabled": enabled, "payload": {}}
