from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias, assert_never

StateValue: TypeAlias = (
    None | bool | int | float | str | Sequence["StateValue"] | Mapping[str, "StateValue"]
)
JourneyState: TypeAlias = Literal[
    "executor_blocked",
    "executor_cancelled",
    "executor_failed",
    "execution_observed",
    "invalid_runtime_evidence",
    "runtime_recovery_blocked",
    "runtime_execution_observed",
    "runtime_running_observed",
    "executor_dispatched",
    "handoff_prepared",
]
ResumeStatus: TypeAlias = Literal["not_started", "conversation_safe", "reattach", "blocked"]


def journey_state(
    runtime_status: Mapping[str, StateValue],
    runtime_observation: Mapping[str, StateValue],
    session_status: Mapping[str, StateValue],
) -> JourneyState:
    """Derive the existing Mission Control journey state from recorded evidence."""
    execution = json_mapping(runtime_status.get("execution"))
    result = str(execution.get("status", ""))
    if execution.get("observed") is True:
        observed_states: dict[str, JourneyState] = {
            "blocked": "executor_blocked",
            "cancelled": "executor_cancelled",
            "failed": "executor_failed",
            "completed": "execution_observed",
        }
        return observed_states.get(result, "invalid_runtime_evidence")
    if result not in {"", "not_observed", "unknown"}:
        return "invalid_runtime_evidence"
    observed_events = json_strings(runtime_observation.get("observed_events"))
    failed_events = json_strings(runtime_observation.get("failed_events"))
    blocked_events = json_strings(runtime_observation.get("blocked_events"))
    if failed_events or blocked_events:
        return "runtime_recovery_blocked"
    if "worker_result" in observed_events:
        return "runtime_execution_observed"
    if "worker_dispatch" in observed_events or "runtime_start" in observed_events:
        return "runtime_running_observed"
    wrapper = json_mapping(runtime_status.get("wrapper"))
    if wrapper.get("prompt_dispatched") is True:
        return "executor_dispatched"
    if str(session_status.get("session_status", "")) in {
        "prompt_handoff_prepared",
        "runtime_handoff_prepared",
        "handoff_prepared",
    }:
        return "handoff_prepared"
    return "handoff_prepared"


def resume_status_from_evidence(evidence: Mapping[str, StateValue]) -> ResumeStatus:
    """Map existing session evidence to fail-closed conversational continuity."""
    errors = evidence.get("evidence_errors")
    if errors not in (None, []) or _malformed_mapping(evidence, "runtime_status"):
        return "blocked"
    if _malformed_mapping(evidence, "runtime_observation") or _malformed_mapping(
        evidence, "executor_status"
    ):
        return "blocked"
    runtime_status = json_mapping(evidence.get("runtime_status"))
    runtime_observation = json_mapping(evidence.get("runtime_observation"))
    executor_status = json_mapping(evidence.get("executor_status"))
    session_value = evidence.get("session_status", "")
    if not isinstance(session_value, str):
        return "blocked"
    if "execution" in runtime_status and not isinstance(runtime_status.get("execution"), Mapping):
        return "blocked"
    if any(
        json_strings(runtime_observation.get(key))
        for key in ("cancelled_events", "terminal_events")
    ):
        return "blocked"

    executor_result = executor_status.get("result", "not_observed")
    if not isinstance(executor_result, str) or executor_result not in {
        "not_observed",
        "completed",
        "blocked",
        "cancelled",
        "failed",
    }:
        return "blocked"
    projected_status: dict[str, StateValue] = dict(runtime_status)
    execution = json_mapping(projected_status.get("execution"))
    if executor_result != "not_observed" and execution.get("observed") is not True:
        projected_status["execution"] = {"observed": True, "status": executor_result}
    if executor_status.get("dispatch") == "observed" and not projected_status.get("wrapper"):
        projected_status["wrapper"] = {"prompt_dispatched": True}

    state = journey_state(
        projected_status,
        runtime_observation,
        {"session_status": session_value},
    )
    match state:
        case "handoff_prepared":
            return "not_started"
        case "executor_dispatched" | "runtime_running_observed":
            return "reattach"
        case "execution_observed" | "runtime_execution_observed":
            return "conversation_safe"
        case (
            "executor_blocked"
            # A cancelled run is not conversation-safe and not reattachable:
            # nothing is still running to reattach to, and no result was
            # reached to continue from. It needs a re-dispatch decision, which
            # is what `blocked` means on this axis.
            | "executor_cancelled"
            | "executor_failed"
            | "runtime_recovery_blocked"
            | "invalid_runtime_evidence"
        ):
            return "blocked"
        case unreachable:
            assert_never(unreachable)


def json_mapping(value: StateValue | None) -> Mapping[str, StateValue]:
    return value if isinstance(value, Mapping) else {}


def json_strings(value: StateValue | None) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _malformed_mapping(evidence: Mapping[str, StateValue], key: str) -> bool:
    return key in evidence and not isinstance(evidence.get(key), Mapping)
