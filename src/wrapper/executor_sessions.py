from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ..executors import CODING_EXECUTOR_TARGETS, executor_label
from ..local_store import atomic_write_json, ensure_dir, ensure_file, read_json_object, utc_now
from ..paths import OmhPaths
from ..runtime.artifacts import (
    read_runtime_observations_result,
    runtime_observations_for_target,
    summarize_runtime_observation_status,
    write_runtime_observation,
)
from ..runtime.records import build_event_record
from .lifecycle import (
    CodingLifecycleError,
    record_codex_dispatch,
    record_codex_result,
    report_codex_delegation_lifecycle,
)


EXECUTOR_SESSION_SCHEMA_VERSION = "executor_session/v1"
EXECUTOR_SESSION_STATUS_SCHEMA_VERSION = "executor_session_status/v1"
EXECUTOR_SESSION_RECORD_TYPE = "executor_session"
EXECUTOR_SESSION_STATUSES = ("not_started", "prepared", "running", "completed", "blocked", "failed")
EXECUTOR_SESSION_RESULTS = ("not_observed", "completed", "blocked", "failed")
EXECUTOR_SESSION_VERIFICATION_STATUSES = ("not_requested", "requested", "observed")
EXECUTOR_SESSION_ACTION_IDS = (
    "open_executor_session",
    "attach_executor_session",
    "refresh_executor_status",
    "record_executor_completed",
    "record_executor_blocked",
    "record_executor_failed",
    "ask_hermes_verify",
)


class ExecutorSessionError(ValueError):
    pass


def build_executor_session_status(
    paths: OmhPaths,
    session: dict[str, Any],
    *,
    linked_status: dict[str, Any] | None = None,
    runtime_status: dict[str, Any] | None = None,
) -> dict[str, object]:
    session_id = str(session.get("session_id", ""))
    record, record_error = read_executor_session_result(_session_dir(paths, session_id))
    record_found = record is not None and record_error is None
    record = record if record_found else _default_executor_session(session)
    if linked_status is None:
        linked_status, linked_status_error = _linked_status_result(paths, session)
    else:
        linked_status_error = None
    if runtime_status is None:
        runtime_status = _runtime_status(paths, session)
    dispatch_observed = _dispatch_observed(record, linked_status, runtime_status, linked_status_error=linked_status_error)
    result_status = _result_status(record, linked_status, linked_status_error=linked_status_error)
    verification_status = _verification_status(record, linked_status, linked_status_error=linked_status_error)
    agent_state = _agent_state(record, dispatch_observed, result_status)
    executor = _selected_executor(session, record)
    attached = bool(record.get("attached", False))
    status_blocker = record_error or linked_status_error or ""
    status = {
        "schema_version": EXECUTOR_SESSION_STATUS_SCHEMA_VERSION,
        "session_id": session_id,
        "selected_executor_profile": executor,
        "executor_label": executor_label(executor),
        "session_kind": _session_kind(session),
        "coding_agent": f"{agent_state}({executor})",
        "executor_session": "attached" if attached else "not_attached",
        "handoff": _handoff_state(session),
        "dispatch": "observed" if dispatch_observed else "not_observed",
        "result": result_status,
        "verification": verification_status,
        "external_session_ref": str(record.get("external_session_ref", "")),
        "actions": build_executor_session_actions(
            session,
            record,
            dispatch_observed=dispatch_observed,
            result_status=result_status,
            status_blocker=status_blocker,
        ),
        "status_lines": [
            f"coding-agent: {agent_state}({executor})",
            f"executor-session: {'attached' if attached else 'not_attached'}",
            f"handoff: {_handoff_state(session)}",
            f"dispatch: {'observed' if dispatch_observed else 'not_observed'}",
            f"result: {result_status}",
            f"verification: {verification_status}",
        ],
        "display_status_lines": _display_status_lines(
            executor=executor,
            agent_state=agent_state,
            attached=attached,
            handoff_state=_handoff_state(session),
            dispatch_observed=dispatch_observed,
            result_status=result_status,
            verification_status=verification_status,
            status_blocker=status_blocker,
        ),
        "claim_boundary": (
            "Executor session status is wrapper/operator metadata. It does not prove execution, "
            "result, verification, review, CI, or merge unless the matching observed evidence is recorded."
        ),
    }
    if record_found and record.get("schema_version") == EXECUTOR_SESSION_SCHEMA_VERSION:
        status["record"] = record
    if record_error:
        status["executor_session_error"] = record_error
    if linked_status_error:
        status["linked_lifecycle_error"] = linked_status_error
    if linked_status:
        status["linked_lifecycle_status"] = {
            "run_id": linked_status.get("run_id", ""),
            "next_action": linked_status.get("next_action", ""),
            "lifecycle_status": linked_status.get("lifecycle_status", ""),
        }
    if runtime_status:
        status["runtime_observation"] = runtime_status
    return status


def build_executor_session_actions(
    session: dict[str, Any],
    record: dict[str, Any] | None = None,
    *,
    dispatch_observed: bool | None = None,
    result_status: str | None = None,
    status_blocker: str = "",
) -> list[dict[str, object]]:
    record = record or _default_executor_session(session)
    executor = _selected_executor(session, record)
    session_id = str(session.get("session_id", ""))
    attached = bool(record.get("attached", False))
    if dispatch_observed is None:
        dispatch_observed = bool(record.get("dispatch_observed", False))
    result_status = result_status or str(record.get("result", "not_observed"))
    base_payload = {
        "schema_version": "executor_session_action/v1",
        "session_id": session_id,
        "selected_executor_profile": executor,
        "executor_label": executor_label(executor),
        "claim_boundary": "The wrapper must call the backend action after it observes the corresponding user or executor event.",
    }
    return [
        _action(
            "open_executor_session",
            _open_label(executor),
            "primary",
            enabled=(
                not status_blocker
                and _handoff_state(session) == "prepared"
                and result_status == "not_observed"
                and not attached
                and not dispatch_observed
            ),
            payload={**base_payload, "backend_action": "open-executor", "disabled_reason": status_blocker},
        ),
        _action(
            "attach_executor_session",
            "Attach existing session",
            "secondary",
            enabled=not status_blocker and _handoff_state(session) == "prepared" and result_status == "not_observed",
            payload={
                **base_payload,
                "backend_action": "attach-executor",
                "disabled_reason": status_blocker,
                "input_schema": {
                    "type": "object",
                    "required": ["external_session_ref"],
                    "properties": {
                        "external_session_ref": {
                            "type": "string",
                            "title": "Executor session reference",
                            "description": "Codex thread id, Claude Code session id, tmux pane, or another operator-visible executor reference.",
                        },
                        "evidence_ref": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional evidence refs showing where the wrapper observed the attachment.",
                        },
                    },
                },
            },
        ),
        _action(
            "refresh_executor_status",
            "Refresh status",
            "secondary",
            enabled=True,
            payload={**base_payload, "backend_action": "status"},
        ),
        _action(
            "record_executor_completed",
            "Record completed",
            "secondary",
            enabled=not status_blocker and bool(attached or dispatch_observed) and result_status == "not_observed",
            payload={**base_payload, "backend_action": "record-executor", "result": "completed", "disabled_reason": status_blocker},
        ),
        _action(
            "record_executor_blocked",
            "Record blocked",
            "secondary",
            enabled=not status_blocker and bool(attached or dispatch_observed) and result_status == "not_observed",
            payload={**base_payload, "backend_action": "record-executor", "result": "blocked", "disabled_reason": status_blocker},
        ),
        _action(
            "record_executor_failed",
            "Record failed",
            "secondary",
            enabled=not status_blocker and bool(attached or dispatch_observed) and result_status == "not_observed",
            payload={**base_payload, "backend_action": "record-executor", "result": "failed", "disabled_reason": status_blocker},
        ),
        _action(
            "ask_hermes_verify",
            "Ask Hermes to verify",
            "secondary",
            enabled=not status_blocker and result_status == "completed",
            payload={**base_payload, "backend_action": "request-verification", "disabled_reason": status_blocker},
        ),
    ]


def read_executor_session(paths: OmhPaths, session_id: str) -> dict[str, Any] | None:
    record, error = read_executor_session_result(_session_dir(paths, session_id))
    return None if error else record


def open_executor_session(
    paths: OmhPaths,
    session_id: str,
    *,
    observed: bool = False,
    external_session_ref: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    summary: str = "",
) -> dict[str, object]:
    if external_session_ref.strip() and not observed:
        raise ExecutorSessionError("open-executor --external-session-ref requires --observed")
    session = _existing_session(paths, session_id)
    _require_prepared_handoff(session)
    _require_no_observed_result(paths, session)
    patch = {
        "status": "running" if observed else "prepared",
        "open_action": "observed" if observed else "prepared",
        "attached": bool(observed and external_session_ref),
        "external_session_ref": external_session_ref,
        "dispatch_observed": observed,
        "evidence_refs": list(evidence_refs or []),
        "summary": summary or _open_summary(session, observed=observed),
    }
    record = _build_executor_session_record(paths, session, patch)
    if observed:
        _observe_dispatch(paths, session, record, summary=summary, evidence_refs=list(evidence_refs or []))
    record = _write_executor_session(paths, record)
    _append_executor_event(paths, session_id, "executor_session_opened", record)
    return {"schema_version": "executor_session_result/v1", "executor_session": record, "status": build_executor_session_status(paths, session)}


def attach_executor_session(
    paths: OmhPaths,
    session_id: str,
    *,
    external_session_ref: str,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    summary: str = "",
) -> dict[str, object]:
    if not external_session_ref.strip():
        raise ExecutorSessionError("attach-executor requires --external-session-ref")
    session = _existing_session(paths, session_id)
    _require_prepared_handoff(session)
    _require_no_observed_result(paths, session)
    record = _build_executor_session_record(
        paths,
        session,
        {
            "status": "running",
            "open_action": "observed",
            "attached": True,
            "external_session_ref": external_session_ref,
            "dispatch_observed": True,
            "evidence_refs": list(evidence_refs or []),
            "summary": summary or "Wrapper attached an observed executor session reference.",
        },
    )
    _observe_dispatch(paths, session, record, summary=summary, evidence_refs=list(evidence_refs or []))
    record = _write_executor_session(paths, record)
    _append_executor_event(paths, session_id, "executor_session_attached", record)
    return {"schema_version": "executor_session_result/v1", "executor_session": record, "status": build_executor_session_status(paths, session)}


def record_executor_session_result(
    paths: OmhPaths,
    session_id: str,
    *,
    result: str,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    summary: str = "",
) -> dict[str, object]:
    if result not in {"completed", "blocked", "failed"}:
        raise ExecutorSessionError("executor result must be completed, blocked, or failed")
    session = _existing_session(paths, session_id)
    _require_prepared_handoff(session)
    current = read_executor_session(paths, session_id) or _default_executor_session(session)
    linked_status, linked_status_error = _linked_status_result(paths, session)
    if linked_status_error:
        raise ExecutorSessionError(linked_status_error)
    if not _dispatch_observed(current, linked_status, _runtime_status(paths, session)) and not bool(current.get("attached", False)):
        raise ExecutorSessionError("cannot record executor result before an executor session is opened or attached")
    refs = list(evidence_refs or [])
    if str(session.get("current_run_id", "")):
        _record_codex_result_if_needed(paths, session, result=result, evidence_refs=refs)
    record = _merge_executor_session(
        paths,
        session,
        {
            "status": result,
            "result": result,
            "result_observed": True,
            "evidence_refs": refs,
            "summary": summary or f"Wrapper recorded executor result: {result}.",
        },
    )
    _append_executor_event(paths, session_id, f"executor_session_{result}", record)
    return {"schema_version": "executor_session_result/v1", "executor_session": record, "status": build_executor_session_status(paths, session)}


def request_executor_session_verification(
    paths: OmhPaths,
    session_id: str,
    *,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    summary: str = "",
) -> dict[str, object]:
    session = _existing_session(paths, session_id)
    _require_prepared_handoff(session)
    current = read_executor_session(paths, session_id) or _default_executor_session(session)
    linked_status, linked_status_error = _linked_status_result(paths, session)
    if linked_status_error:
        raise ExecutorSessionError(linked_status_error)
    if _result_status(current, linked_status) != "completed":
        raise ExecutorSessionError("cannot request Hermes verification before executor completion is recorded")
    record = _merge_executor_session(
        paths,
        session,
        {
            "verification": "requested",
            "verification_requested": True,
            "evidence_refs": list(evidence_refs or []),
            "summary": summary or "Hermes verification was requested; verification evidence is not observed yet.",
        },
    )
    _append_executor_event(paths, session_id, "executor_session_verification_requested", record)
    return {"schema_version": "executor_session_result/v1", "executor_session": record, "status": build_executor_session_status(paths, session)}


def enhance_chat_response_with_executor_session(
    response: dict[str, object],
    executor_status: dict[str, object],
) -> dict[str, object]:
    updated = dict(response)
    state = dict(updated.get("state", {})) if isinstance(updated.get("state"), dict) else {}
    state["executor_session_status"] = {
        "schema_version": executor_status.get("schema_version", EXECUTOR_SESSION_STATUS_SCHEMA_VERSION),
        "coding_agent": executor_status.get("coding_agent", ""),
        "executor_session": executor_status.get("executor_session", ""),
        "dispatch": executor_status.get("dispatch", ""),
        "result": executor_status.get("result", ""),
        "verification": executor_status.get("verification", ""),
    }
    updated["state"] = state
    actions = [action for action in updated.get("actions", []) if isinstance(action, dict)]
    action_ids = {str(action.get("id", "")) for action in actions}
    for action in executor_status.get("actions", []):
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("id", ""))
        if action_id in action_ids:
            continue
        actions.append(action)
        action_ids.add(action_id)
    updated["actions"] = actions
    status_lines = executor_status.get("status_lines")
    if isinstance(status_lines, list):
        updated["executor_status_lines"] = status_lines
    status_card = updated.get("status_card")
    if isinstance(status_card, dict):
        updated["status_card"] = enhance_status_card_with_executor_session(status_card, executor_status)
    return updated


def enhance_status_card_with_executor_session(
    status_card: dict[str, object],
    executor_status: dict[str, object],
) -> dict[str, object]:
    updated = dict(status_card)
    updated["executor_session_status"] = _executor_status_summary(executor_status)
    updated["executor_status_lines"] = list(executor_status.get("status_lines", [])) if isinstance(executor_status.get("status_lines"), list) else []
    updated["executor_display_status_lines"] = (
        list(executor_status.get("display_status_lines", [])) if isinstance(executor_status.get("display_status_lines"), list) else []
    )
    executor_next_action = _next_executor_action(executor_status)
    updated["executor_next_action"] = executor_next_action
    updated["executor_next_action_label"] = _executor_action_label(executor_status, executor_next_action)
    updated["executor_actions"] = [action for action in executor_status.get("actions", []) if isinstance(action, dict)]
    return updated


def build_executor_session_status_card(executor_status: dict[str, object]) -> dict[str, object]:
    result = str(executor_status.get("result", "not_observed"))
    dispatch = str(executor_status.get("dispatch", "not_observed"))
    verification = str(executor_status.get("verification", "not_requested"))
    next_action = _next_executor_action(executor_status)
    next_action_label = _executor_action_label(executor_status, next_action)
    card = {
        "schema_version": "status_card/v1",
        "run_id": "",
        "kind": "executor_session",
        "severity": _executor_status_card_severity(result, verification),
        "headline": "Executor session status",
        "summary": "Hermes can show the selected coding-agent session without claiming unobserved execution, verification, review, CI, or merge.",
        "next_action": next_action,
        "next_action_label": next_action_label,
        "primary_action": next_action,
        "primary_action_label": next_action_label,
        "steps": [
            _card_step("handoff", "Handoff", "complete" if executor_status.get("handoff") == "prepared" else "pending", "Executor handoff prepared by Hermes."),
            _card_step("dispatch", "Dispatch", "complete" if dispatch == "observed" else "pending", "Observed wrapper open or attach event."),
            _card_step("result", "Result", _result_step_state(result), "Observed executor result."),
            _card_step("verification", "Verification", _verification_step_state(verification), "Hermes verification request or observed verification evidence."),
        ],
        "claim_boundary": executor_status.get("claim_boundary", _claim_boundary()),
    }
    return enhance_status_card_with_executor_session(card, executor_status)


def _existing_session(paths: OmhPaths, session_id: str) -> dict[str, Any]:
    session = read_json_object(paths.runtime_wrapper_sessions_dir / session_id / "session.json")
    if not session:
        raise FileNotFoundError(session_id)
    return session


def _default_executor_session(session: dict[str, Any]) -> dict[str, Any]:
    executor = str(session.get("selected_executor_profile") or "choose")
    return {
        "schema_version": EXECUTOR_SESSION_SCHEMA_VERSION,
        "record_type": EXECUTOR_SESSION_RECORD_TYPE,
        "session_id": str(session.get("session_id", "")),
        "updated_at": str(session.get("updated_at", "")) or utc_now(),
        "selected_executor_profile": executor,
        "session_kind": _session_kind(session),
        "status": "prepared" if _handoff_state(session) == "prepared" else "not_started",
        "open_action": "not_observed",
        "attached": False,
        "external_session_ref": "",
        "dispatch_observed": False,
        "result": "not_observed",
        "result_observed": False,
        "verification": "not_requested",
        "verification_requested": False,
        "evidence_refs": [],
        "summary": "",
        "claim_boundary": _claim_boundary(),
    }


def _merge_executor_session(paths: OmhPaths, session: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    record = _build_executor_session_record(paths, session, patch)
    return _write_executor_session(paths, record)


def _build_executor_session_record(paths: OmhPaths, session: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    session_id = str(session.get("session_id", ""))
    current = read_executor_session(paths, session_id) or _default_executor_session(session)
    merged = {
        **current,
        **patch,
        "schema_version": EXECUTOR_SESSION_SCHEMA_VERSION,
        "record_type": EXECUTOR_SESSION_RECORD_TYPE,
        "session_id": session_id,
        "selected_executor_profile": _selected_executor(session, current),
        "session_kind": _session_kind(session),
        "updated_at": utc_now(),
        "claim_boundary": _claim_boundary(),
    }
    merged["evidence_refs"] = _compact_list(merged.get("evidence_refs", []))
    errors = validate_executor_session_record(merged)
    if errors:
        raise ExecutorSessionError(errors[0])
    return merged


def _write_executor_session(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(_executor_session_path(paths, str(record["session_id"])), record, private=True)
    return record


def validate_executor_session_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "schema_version",
        "record_type",
        "session_id",
        "updated_at",
        "selected_executor_profile",
        "session_kind",
        "status",
        "open_action",
        "attached",
        "external_session_ref",
        "dispatch_observed",
        "result",
        "result_observed",
        "verification",
        "verification_requested",
        "evidence_refs",
        "summary",
        "claim_boundary",
    }
    extra = sorted(set(record) - allowed)
    if extra:
        errors.append(f"executor_session has unsupported keys: {extra}")
    if record.get("schema_version") != EXECUTOR_SESSION_SCHEMA_VERSION:
        errors.append("executor_session schema_version is invalid")
    if record.get("record_type") != EXECUTOR_SESSION_RECORD_TYPE:
        errors.append("executor_session record_type is invalid")
    for key in (
        "session_id",
        "updated_at",
        "selected_executor_profile",
        "session_kind",
        "status",
        "open_action",
        "external_session_ref",
        "result",
        "verification",
        "summary",
        "claim_boundary",
    ):
        if not isinstance(record.get(key), str):
            errors.append(f"executor_session {key} must be a string")
    if not str(record.get("session_id", "")).startswith("ws-"):
        errors.append("executor_session session_id must start with ws-")
    if record.get("selected_executor_profile") not in CODING_EXECUTOR_TARGETS:
        errors.append(f"executor_session selected_executor_profile is invalid: {record.get('selected_executor_profile')!r}")
    if record.get("status") not in EXECUTOR_SESSION_STATUSES:
        errors.append(f"executor_session status is invalid: {record.get('status')!r}")
    if record.get("result") not in EXECUTOR_SESSION_RESULTS:
        errors.append(f"executor_session result is invalid: {record.get('result')!r}")
    if record.get("verification") not in EXECUTOR_SESSION_VERIFICATION_STATUSES:
        errors.append(f"executor_session verification is invalid: {record.get('verification')!r}")
    for key in ("attached", "dispatch_observed", "result_observed", "verification_requested"):
        if not isinstance(record.get(key), bool):
            errors.append(f"executor_session {key} must be boolean")
    if not isinstance(record.get("evidence_refs"), list):
        errors.append("executor_session evidence_refs must be a list")
    else:
        for index, value in enumerate(record["evidence_refs"]):
            if not isinstance(value, str):
                errors.append(f"executor_session evidence_refs[{index}] must be a string")
    if record.get("result") != "not_observed" and record.get("result_observed") is not True:
        errors.append("executor_session observed result requires result_observed=true")
    if record.get("verification") == "requested" and record.get("verification_requested") is not True:
        errors.append("executor_session requested verification requires verification_requested=true")
    return errors


def read_executor_session_result(session_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = session_dir / "executor_session.json"
    try:
        record = read_json_object(path)
    except (OSError, JSONDecodeError, ValueError) as exc:
        return None, f"{path}: {exc}"
    if not record:
        return None, None
    errors = validate_executor_session_record(record)
    return record, f"{path}: {errors[0]}" if errors else None


def _observe_dispatch(
    paths: OmhPaths,
    session: dict[str, Any],
    record: dict[str, Any],
    *,
    summary: str,
    evidence_refs: list[str],
) -> None:
    run_id = str(session.get("current_run_id", ""))
    if run_id:
        try:
            status = report_codex_delegation_lifecycle(paths, run_id)
            if status.get("next_action") == "dispatch_to_executor":
                record_codex_dispatch(paths, run_id)
        except (CodingLifecycleError, FileNotFoundError) as exc:
            raise ExecutorSessionError(str(exc)) from exc
        return
    if session.get("status") != "runtime_handoff_prepared":
        return
    runtime_profile = _selected_executor(session, record)
    target_dir = _session_dir(paths, str(session.get("session_id", "")))
    observations, _errors = read_runtime_observations_result(target_dir)
    runtime_start = [
        item
        for item in runtime_observations_for_target(observations, "wrapper_session", str(session.get("session_id", "")))
        if item.get("event_type") == "runtime_start" and item.get("status") == "observed"
    ]
    if runtime_start:
        return
    write_runtime_observation(
        target_dir,
        {
            "target_type": "wrapper_session",
            "target_id": str(session.get("session_id", "")),
            "runtime_profile": runtime_profile,
            "event_type": "runtime_start",
            "status": "observed",
            "participants": [runtime_profile],
            "evidence_refs": evidence_refs,
            "summary": summary or "Wrapper observed the runtime session open action.",
        },
    )


def _record_codex_result_if_needed(
    paths: OmhPaths,
    session: dict[str, Any],
    *,
    result: str,
    evidence_refs: list[str],
) -> None:
    run_id = str(session.get("current_run_id", ""))
    if not run_id:
        return
    try:
        status = report_codex_delegation_lifecycle(paths, run_id)
    except FileNotFoundError as exc:
        raise ExecutorSessionError(f"linked runtime run not found: {run_id}") from exc
    next_action = str(status.get("next_action", ""))
    if next_action == "dispatch_to_executor":
        raise ExecutorSessionError("cannot record Codex result before dispatch is observed")
    if next_action != "wait_for_executor_evidence":
        return
    try:
        record_codex_result(paths, run_id, result=result, participants=["codex"], evidence_refs=evidence_refs)
    except CodingLifecycleError as exc:
        raise ExecutorSessionError(str(exc)) from exc


def _linked_status_result(paths: OmhPaths, session: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    run_id = str(session.get("current_run_id", ""))
    if not run_id:
        return {}, None
    try:
        return report_codex_delegation_lifecycle(paths, run_id), None
    except FileNotFoundError:
        return {}, f"linked runtime run not found: {run_id}"


def _runtime_status(paths: OmhPaths, session: dict[str, Any]) -> dict[str, Any]:
    if session.get("status") != "runtime_handoff_prepared":
        return {}
    observations, _errors = read_runtime_observations_result(_session_dir(paths, str(session.get("session_id", ""))))
    return summarize_runtime_observation_status(
        runtime_observations_for_target(observations, "wrapper_session", str(session.get("session_id", "")))
    )


def _dispatch_observed(
    record: dict[str, Any],
    linked_status: dict[str, Any],
    runtime_status: dict[str, Any],
    *,
    linked_status_error: str | None = None,
) -> bool:
    if linked_status_error:
        return False
    if bool(record.get("dispatch_observed", False)):
        return True
    if linked_status and str(linked_status.get("next_action", "")) != "dispatch_to_executor":
        return True
    if runtime_status and "runtime_start" in runtime_status.get("observed_events", []):
        return True
    return False


def _result_status(record: dict[str, Any], linked_status: dict[str, Any], *, linked_status_error: str | None = None) -> str:
    if linked_status_error:
        return "not_observed"
    linked_execution = linked_status.get("execution", {}) if linked_status else {}
    if isinstance(linked_execution, dict) and linked_execution.get("observed"):
        return str(linked_execution.get("status", "not_observed"))
    return str(record.get("result", "not_observed"))


def _verification_status(record: dict[str, Any], linked_status: dict[str, Any], *, linked_status_error: str | None = None) -> str:
    if linked_status_error:
        return "not_requested"
    linked_verification = linked_status.get("verification", {}) if linked_status else {}
    if isinstance(linked_verification, dict) and linked_verification.get("observed"):
        return "observed"
    return str(record.get("verification", "not_requested"))


def _agent_state(record: dict[str, Any], dispatch_observed: bool, result_status: str) -> str:
    if result_status in {"completed", "blocked", "failed"}:
        return result_status
    if dispatch_observed or bool(record.get("attached", False)):
        return "running"
    if str(record.get("status", "")) == "not_started":
        return "idle"
    return "prepared"


def _selected_executor(session: dict[str, Any], record: dict[str, Any]) -> str:
    return str(record.get("selected_executor_profile") or session.get("selected_executor_profile") or "choose")


def _handoff_state(session: dict[str, Any]) -> str:
    return "prepared" if session.get("status") in {"handoff_prepared", "prompt_handoff_prepared", "runtime_handoff_prepared"} else "not_prepared"


def _session_kind(session: dict[str, Any]) -> str:
    if session.get("current_run_id"):
        return "codex_lifecycle"
    if session.get("status") == "runtime_handoff_prepared":
        return "runtime_handoff"
    if session.get("status") == "prompt_handoff_prepared":
        return "prompt_only"
    return "wrapper_session"


def _require_prepared_handoff(session: dict[str, Any]) -> None:
    if _handoff_state(session) != "prepared":
        raise ExecutorSessionError("executor session actions require a prepared handoff")


def _require_no_observed_result(paths: OmhPaths, session: dict[str, Any]) -> None:
    current = read_executor_session(paths, str(session.get("session_id", ""))) or _default_executor_session(session)
    linked_status, linked_status_error = _linked_status_result(paths, session)
    if linked_status_error:
        raise ExecutorSessionError(linked_status_error)
    if _result_status(current, linked_status) != "not_observed":
        raise ExecutorSessionError("cannot open or attach an executor session after executor result is recorded")


def _open_label(executor: str) -> str:
    if executor == "codex":
        return "Open in Codex"
    if executor == "claude-code":
        return "Open in Claude Code"
    if executor == "hermes":
        return "Open Hermes coding"
    return f"Open {executor_label(executor)}"


def _open_summary(session: dict[str, Any], *, observed: bool) -> str:
    if observed:
        return "Wrapper observed an executor open action. This records dispatch/open only, not executor result."
    return "Wrapper prepared an executor open action. No executor dispatch/open is observed yet."


def _display_status_lines(
    *,
    executor: str,
    agent_state: str,
    attached: bool,
    handoff_state: str,
    dispatch_observed: bool,
    result_status: str,
    verification_status: str,
    status_blocker: str,
) -> list[str]:
    lines = [
        f"Coding agent is {agent_state} in {executor_label(executor)}.",
        "Executor session is attached." if attached else "Executor session is not attached yet.",
        "Handoff is ready." if handoff_state == "prepared" else "Handoff is not ready yet.",
        "Dispatch/open has been observed." if dispatch_observed else "Dispatch/open has not been observed yet.",
        _result_display_line(result_status),
        _verification_display_line(verification_status),
    ]
    if status_blocker:
        lines.append(f"Action is blocked until OMH can read valid evidence: {status_blocker}")
    return lines


def _result_display_line(result_status: str) -> str:
    if result_status == "completed":
        return "Executor result is recorded as completed."
    if result_status == "blocked":
        return "Executor result is blocked."
    if result_status == "failed":
        return "Executor result is failed."
    return "Executor result has not been observed yet."


def _verification_display_line(verification_status: str) -> str:
    if verification_status == "observed":
        return "Hermes verification evidence is observed."
    if verification_status == "requested":
        return "Hermes verification has been requested."
    return "Hermes verification has not been requested yet."


def _claim_boundary() -> str:
    return (
        "Executor session records are metadata-only wrapper/operator observations. "
        "They never prove unrecorded code execution, verification, review, CI, merge readiness, or merge."
    )


def _compact_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value) for value in values if str(value)]


def _action(action_id: str, label: str, style: str, *, enabled: bool = True, payload: dict[str, object] | None = None) -> dict[str, object]:
    if action_id not in EXECUTOR_SESSION_ACTION_IDS:
        raise ValueError(f"unsupported executor session action: {action_id}")
    return {"id": action_id, "label": label, "style": style, "enabled": enabled, "payload": payload or {}}


def _executor_status_summary(executor_status: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": executor_status.get("schema_version", EXECUTOR_SESSION_STATUS_SCHEMA_VERSION),
        "coding_agent": executor_status.get("coding_agent", ""),
        "executor_session": executor_status.get("executor_session", ""),
        "handoff": executor_status.get("handoff", ""),
        "dispatch": executor_status.get("dispatch", ""),
        "result": executor_status.get("result", ""),
        "verification": executor_status.get("verification", ""),
    }


def _next_executor_action(executor_status: dict[str, object]) -> str:
    dispatch = str(executor_status.get("dispatch", "not_observed"))
    result = str(executor_status.get("result", "not_observed"))
    verification = str(executor_status.get("verification", "not_requested"))
    if dispatch != "observed":
        return "open_executor_session"
    if result == "not_observed":
        return "refresh_executor_status"
    if result == "completed" and verification == "not_requested":
        return "ask_hermes_verify"
    return "show_status"


def _executor_action_label(executor_status: dict[str, object], action_id: str) -> str:
    for action in executor_status.get("actions", []):
        if isinstance(action, dict) and action.get("id") == action_id:
            return str(action.get("label") or action_id)
    if action_id == "show_status":
        return "Show status"
    return action_id.replace("_", " ").title()


def _executor_status_card_severity(result: str, verification: str) -> str:
    if result in {"blocked", "failed"}:
        return "blocked"
    if result == "completed" and verification == "observed":
        return "success"
    if result == "completed":
        return "attention"
    return "neutral"


def _card_step(step_id: str, label: str, state: str, detail: str) -> dict[str, object]:
    return {"id": step_id, "label": label, "state": state, "detail": detail}


def _result_step_state(result: str) -> str:
    if result in {"blocked", "failed"}:
        return "blocked"
    if result == "completed":
        return "complete"
    return "pending"


def _verification_step_state(verification: str) -> str:
    if verification == "observed":
        return "complete"
    if verification == "requested":
        return "ready"
    return "pending"


def _append_executor_event(paths: OmhPaths, session_id: str, event: str, record: dict[str, Any]) -> None:
    session_dir = _session_dir(paths, session_id)
    events_path = session_dir / "events.jsonl"
    ensure_dir(session_dir, private=True)
    ensure_file(events_path, private=True)
    item = build_event_record(
        {
            "event": event,
            "level": "info",
            "message": f"executor session {record.get('status', 'unknown')}",
            "data": {
                "selected_executor_profile": record.get("selected_executor_profile", ""),
                "dispatch_observed": record.get("dispatch_observed", False),
                "result": record.get("result", "not_observed"),
            },
        }
    )
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")


def _executor_session_path(paths: OmhPaths, session_id: str) -> Path:
    return _session_dir(paths, session_id) / "executor_session.json"


def _session_dir(paths: OmhPaths, session_id: str) -> Path:
    return paths.runtime_wrapper_sessions_dir / session_id
