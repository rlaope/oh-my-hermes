"""Completion-driven waiting discipline for long-running work.

`context_safety.build_coding_progress_reporting_policy` already declares
`mode: event_triggered` and `timed_polling_rejected: true`, and the observe
surfaces already bound and de-duplicate a repeated status payload. Both act
AFTER a poll happened: the model turn that replayed the conversation is already
spent by the time an unchanged projection comes back.

This module is the piece that runs BEFORE the work starts. It selects, from the
host capabilities actually observed, which completion primitive a wait binds to,
records the handle it is bound to, and fixes the hard deadline, cancellation
path, and fallback up front. Everything here is metadata-only and deterministic:
no clock is read, no process is started, nothing is dispatched. A selected
strategy is prepared context, never evidence that anything ran.

Executor-neutral by construction. No mechanism names a tool, CLI, or host: a
caller passes the capabilities it observed and gets back the best rung of a
fixed ladder that those capabilities support, plus an honest record of what was
missing when it had to degrade.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .context_safety import (
    MAX_EVIDENCE_REFS,
    MAX_SUMMARY_CHARS,
    compact_context_refs,
    compact_visible_text,
    sanitize_user_facing_progress_text,
)


EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION = "omh_execution_wait_strategy/v1"
EXECUTION_WAIT_BINDING_SCHEMA_VERSION = "omh_execution_wait_binding/v1"
EXECUTION_WAIT_TRACE_SCHEMA_VERSION = "omh_execution_wait_trace/v1"

MAX_WAIT_CONDITION_CHARS = 160
MAX_WAIT_HANDLE_REF_CHARS = 120
MAX_WAIT_REASON_CHARS = 160

# The kinds of work a model-driven wait can be bound to. Internal OS lock
# acquisition and short in-process synchronization are deliberately absent:
# those never cost a model turn, so they are out of this contract's scope.
WAIT_WORK_KINDS = (
    "command",
    "delegated_lane",
    "ci_pr_deploy",
    "file_port_log",
    "external_session",
)

# How long the work is expected to take, in the only granularity that changes
# the mechanism. A caller that does not know says so; `unknown` degrades to the
# conservative end of the ladder rather than guessing a foreground call.
WAIT_DURATION_CLASSES = (
    "within_one_call",
    "minutes",
    "long_running",
    "unknown",
)

# Closed mechanism vocabulary, ordered from the primitive that costs the fewest
# model turns to the last-resort one that costs the most. `adaptive_backoff_
# fallback` is last because it is the only rung that spends wall time without a
# host primitive behind it; it is still bounded by the wait's hard deadline.
WAIT_MECHANISMS = (
    "foreground_bounded_call",
    "background_completion_notification",
    "delegated_result_delivery",
    "host_monitor_subscription",
    "bounded_background_watcher",
    "adaptive_backoff_fallback",
)

# What the recorded handle points at. A handle is a reference the host can act
# on -- stop it, resume it, ask about it -- never a log, a transcript, or an
# output buffer.
WAIT_HANDLE_KINDS = (
    "foreground_call",
    "background_process",
    "delegated_task",
    "monitor_subscription",
    "watcher_process",
    "external_session",
)

# The value recorded into executor-progress metadata so a reader can tell how a
# binding learns that its work finished. One per mechanism, by construction.
WAIT_OBSERVATION_MODES = (
    "single_foreground_return",
    "event_triggered_completion",
    "delivered_result",
    "subscribed_condition",
    "bounded_watcher",
    "adaptive_backoff",
)

# The host capabilities a caller reports observing. A capability that is not in
# this list is recorded as unrecognized rather than silently treated as absent,
# for the same reason `context_safety` records a refused event name: "we did not
# understand this" and "the host does not have it" are different facts.
WAIT_HOST_CAPABILITIES = (
    "foreground_timeout",
    "background_completion_notification",
    "delegated_result_delivery",
    "host_monitor_subscription",
    "background_watcher",
)

# Every armed wait ends in exactly one of these. `lost_handle` is separate from
# `failed` on purpose: the work may well have succeeded, and the recovery action
# is to re-observe rather than to re-run.
WAIT_TERMINAL_STATES = ("completed", "failed", "cancelled", "timed_out", "lost_handle")
WAIT_BINDING_STATES = ("armed", *WAIT_TERMINAL_STATES)

# One decision-changing peek. Not zero, because a midpoint check that changes
# what happens next is real diagnosis; not more than one, because the second one
# is how a peek becomes the wait mechanism.
MIDPOINT_PEEK_BUDGET = 1

# The recorded call shapes a no-poll trace is checked against. A user-requested
# status read is its own word because it is never charged against the peek
# budget: the user asking is not the agent waiting.
WAIT_TRACE_CALLS = (
    "launch",
    "completion_event",
    "agent_status_read",
    "user_requested_status_read",
    "cancellation",
    "deadline_expiry",
)

_WAIT_TERMINAL_TRACE_CALLS = ("completion_event", "cancellation", "deadline_expiry")

_MECHANISM_OBSERVATION_MODES = {
    "foreground_bounded_call": "single_foreground_return",
    "background_completion_notification": "event_triggered_completion",
    "delegated_result_delivery": "delivered_result",
    "host_monitor_subscription": "subscribed_condition",
    "bounded_background_watcher": "bounded_watcher",
    "adaptive_backoff_fallback": "adaptive_backoff",
}

# The one host capability each mechanism cannot run without. The empty string is
# the terminal rung: adaptive backoff needs no host primitive, which is exactly
# why it is the last resort rather than a default.
_MECHANISM_REQUIRED_CAPABILITY = {
    "foreground_bounded_call": "foreground_timeout",
    "background_completion_notification": "background_completion_notification",
    "delegated_result_delivery": "delegated_result_delivery",
    "host_monitor_subscription": "host_monitor_subscription",
    "bounded_background_watcher": "background_watcher",
    "adaptive_backoff_fallback": "",
}

# Hard deadlines by expected duration. A caller may pass its own; what it may
# not do is arm a wait with no deadline, so these exist to make the default
# path bounded rather than to be authoritative.
DEFAULT_DEADLINE_SECONDS = {
    "within_one_call": 120,
    "minutes": 900,
    "long_running": 3600,
    "unknown": 3600,
}

_COMMAND_LADDER_SHORT = (
    "foreground_bounded_call",
    "background_completion_notification",
    "bounded_background_watcher",
    "adaptive_backoff_fallback",
)
_COMMAND_LADDER_LONG = (
    "background_completion_notification",
    "bounded_background_watcher",
    "adaptive_backoff_fallback",
)
_DELEGATED_LADDER = (
    "delegated_result_delivery",
    "background_completion_notification",
    "bounded_background_watcher",
    "adaptive_backoff_fallback",
)
_EXTERNAL_CONDITION_LADDER = (
    "host_monitor_subscription",
    "bounded_background_watcher",
    "adaptive_backoff_fallback",
)

WAIT_STRATEGY_CLAIM_BOUNDARY = (
    "A selected wait strategy is prepared metadata about how this session will learn that work finished. "
    "It is not dispatch, execution, verification, review, CI, merge-readiness, or merge evidence, and "
    "arming a wait does not start, observe, or complete any work."
)

_WAIT_TRACE_CLAIM_BOUNDARY = (
    "A wait trace judges how a session waited, not what the work produced. A clean trace is not "
    "execution, verification, review, CI, merge-readiness, or merge evidence."
)

WAIT_BINDING_CLAIM_BOUNDARY = (
    "A wait binding records how this session learned that its bound handle reached a terminal state. The "
    "terminal state and its bounded evidence refs are not execution, verification, review, CI, "
    "merge-readiness, or merge evidence unless separate observed records say so."
)


def wait_mechanism_ladder(work_kind: Any, expected_duration_class: Any) -> tuple[str, ...]:
    """The mechanisms this work shape may use, best first.

    The ladder is a property of the work, not of the host: a host with no
    primitives still walks the same rungs, it just falls further down them.
    """
    kind = _normalize_choice(work_kind, WAIT_WORK_KINDS, "command")
    duration = _normalize_choice(expected_duration_class, WAIT_DURATION_CLASSES, "unknown")
    if kind == "delegated_lane":
        return _DELEGATED_LADDER
    if kind in ("ci_pr_deploy", "file_port_log", "external_session"):
        return _EXTERNAL_CONDITION_LADDER
    if duration == "within_one_call":
        return _COMMAND_LADDER_SHORT
    return _COMMAND_LADDER_LONG


def select_wait_mechanism(
    *,
    work_kind: Any,
    expected_duration_class: Any,
    host_capabilities: Sequence[Any] = (),
) -> dict[str, object]:
    """Map (work kind, duration class, observed host capabilities) to a mechanism.

    Returns the selected rung, the next supported rung as the fallback, the
    observation mode the selection implies, and -- when the best rung was not
    available -- which capability was missing. Degrading is recorded, never
    silent: a caller that reads `capability_degraded` learns that this host
    cannot do the cheap thing, instead of believing it chose the cheap thing.
    """
    ladder = wait_mechanism_ladder(work_kind, expected_duration_class)
    observed, unrecognized = _observed_capabilities(host_capabilities)
    supported = [rung for rung in ladder if _mechanism_supported(rung, observed)]
    # The last rung requires nothing, so `supported` is never empty; keep the
    # guard anyway so a future ladder edit fails loudly rather than by index.
    mechanism = supported[0] if supported else "adaptive_backoff_fallback"
    fallback = supported[1] if len(supported) > 1 else ""
    missing = [
        _MECHANISM_REQUIRED_CAPABILITY[rung]
        for rung in ladder[: ladder.index(mechanism)]
        if _MECHANISM_REQUIRED_CAPABILITY[rung]
    ]
    selection: dict[str, object] = {
        "work_kind": _normalize_choice(work_kind, WAIT_WORK_KINDS, "command"),
        "expected_duration_class": _normalize_choice(expected_duration_class, WAIT_DURATION_CLASSES, "unknown"),
        "mechanism_ladder": list(ladder),
        "mechanism": mechanism,
        "fallback_mechanism": fallback,
        "observation_mode": _MECHANISM_OBSERVATION_MODES[mechanism],
        "host_capabilities_observed": sorted(observed),
        "capability_degraded": bool(missing),
        "missing_capabilities": missing,
        "selection_reason": _selection_reason(mechanism, missing),
    }
    if fallback == "":
        selection["fallback_reason"] = "no_further_mechanism_available_deadline_is_terminal"
    if unrecognized:
        selection["unrecognized_host_capabilities"] = unrecognized
    return selection


def diagnostic_peek_policy() -> dict[str, object]:
    """What may be inspected during a wait without becoming the wait itself."""
    return {
        "midpoint_peek_budget": MIDPOINT_PEEK_BUDGET,
        "midpoint_peek_condition": "only_when_the_result_changes_a_decision",
        "user_requested_status_check": "always_allowed_and_never_charged_to_the_budget",
        "may_become_a_loop": False,
        "loop_violation": "polling_loop_detected",
    }


def build_execution_wait_strategy(
    *,
    work_kind: str,
    expected_duration_class: str,
    handle_kind: str,
    handle_ref: str,
    condition: str,
    host_capabilities: Sequence[Any] = (),
    deadline_seconds: int = 0,
    cancellation_path: str = "",
) -> dict[str, object]:
    """Build the `omh_execution_wait_strategy/v1` payload for one wait.

    `handle_ref` is bounded and carries a reference only -- a process id, a task
    id, a subscription id, a session id. Raw logs, prompts, and output buffers
    never enter this payload, so it stays safe to attach to a chat-facing
    progress record.
    """
    selection = select_wait_mechanism(
        work_kind=work_kind,
        expected_duration_class=expected_duration_class,
        host_capabilities=host_capabilities,
    )
    duration = str(selection["expected_duration_class"])
    resolved_deadline = int(deadline_seconds) if _positive_int(deadline_seconds) else DEFAULT_DEADLINE_SECONDS[duration]
    cancellation = compact_visible_text(cancellation_path, max_chars=MAX_WAIT_HANDLE_REF_CHARS)
    payload: dict[str, object] = {
        "schema_version": EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION,
        "work_kind": selection["work_kind"],
        "expected_duration_class": duration,
        "handle": {
            "kind": _normalize_choice(handle_kind, WAIT_HANDLE_KINDS, "background_process"),
            "reference": compact_visible_text(handle_ref, max_chars=MAX_WAIT_HANDLE_REF_CHARS),
            "raw_content_included": False,
        },
        "condition": compact_visible_text(
            sanitize_user_facing_progress_text(condition) or "unnamed_completion_condition",
            max_chars=MAX_WAIT_CONDITION_CHARS,
        ),
        "mechanism": selection["mechanism"],
        "fallback_mechanism": selection["fallback_mechanism"],
        "observation_mode": selection["observation_mode"],
        "deadline_seconds": resolved_deadline,
        "deadline_is_hard": True,
        "cancellation": {
            "available": bool(cancellation),
            "path": cancellation or "cancellation_path_not_named",
        },
        "selection": selection,
        "diagnostic_peek_policy": diagnostic_peek_policy(),
        "terminal_states": list(WAIT_TERMINAL_STATES),
        "binding_state": "armed",
        "timed_polling_rejected": True,
        "raw_content_included": False,
        "claim_boundary": WAIT_STRATEGY_CLAIM_BOUNDARY,
    }
    unmapped = _unmapped_wait_sources(
        work_kind=work_kind,
        expected_duration_class=expected_duration_class,
        handle_kind=handle_kind,
    )
    if unmapped:
        payload["omitted"] = unmapped
    return payload


def validate_execution_wait_strategy(strategy: Any) -> list[str]:
    """Every way an armed wait can be unbounded, unowned, or unrecoverable."""
    if not isinstance(strategy, dict):
        return ["execution wait strategy must be an object"]
    errors: list[str] = []
    if strategy.get("schema_version") != EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION:
        errors.append("execution wait strategy schema_version is invalid")
    if strategy.get("work_kind") not in WAIT_WORK_KINDS:
        errors.append("execution wait strategy work_kind is not in the closed vocabulary")
    if strategy.get("expected_duration_class") not in WAIT_DURATION_CLASSES:
        errors.append("execution wait strategy expected_duration_class is not in the closed vocabulary")
    mechanism = strategy.get("mechanism")
    if mechanism not in WAIT_MECHANISMS:
        errors.append("execution wait strategy mechanism is not in the closed vocabulary")
    fallback = strategy.get("fallback_mechanism")
    if fallback not in ("", *WAIT_MECHANISMS):
        errors.append("execution wait strategy fallback_mechanism is not in the closed vocabulary")
    if fallback and fallback == mechanism:
        errors.append("execution wait strategy fallback_mechanism must differ from the selected mechanism")
    observation_mode = strategy.get("observation_mode")
    if observation_mode not in WAIT_OBSERVATION_MODES:
        errors.append("execution wait strategy observation_mode is not in the closed vocabulary")
    elif mechanism in WAIT_MECHANISMS and observation_mode != _MECHANISM_OBSERVATION_MODES[mechanism]:
        errors.append("execution wait strategy observation_mode does not match its mechanism")
    handle = strategy.get("handle")
    if not isinstance(handle, dict):
        errors.append("execution wait strategy handle must be an object")
    else:
        if handle.get("kind") not in WAIT_HANDLE_KINDS:
            errors.append("execution wait strategy handle kind is not in the closed vocabulary")
        if not str(handle.get("reference", "")).strip():
            errors.append("execution wait strategy handle must carry an observed reference")
    if not _positive_int(strategy.get("deadline_seconds")):
        errors.append("execution wait strategy must carry a positive hard deadline")
    cancellation = strategy.get("cancellation")
    if not isinstance(cancellation, dict) or not cancellation.get("available"):
        errors.append("execution wait strategy must name a cancellation path")
    if strategy.get("binding_state") not in WAIT_BINDING_STATES:
        errors.append("execution wait strategy binding_state is invalid")
    if list(strategy.get("terminal_states", [])) != list(WAIT_TERMINAL_STATES):
        errors.append("execution wait strategy must carry the canonical terminal states")
    if strategy.get("raw_content_included") is not False:
        errors.append("execution wait strategy must not carry raw content")
    return errors


def arm_wait_binding(strategy: Mapping[str, Any]) -> dict[str, object]:
    """Open the binding a completion event will later close, exactly once."""
    handle = strategy.get("handle") if isinstance(strategy.get("handle"), dict) else {}
    return {
        "schema_version": EXECUTION_WAIT_BINDING_SCHEMA_VERSION,
        "binding_state": "armed",
        "completion_consumed": False,
        "mechanism": str(strategy.get("mechanism", "")),
        "fallback_mechanism": str(strategy.get("fallback_mechanism", "")),
        "observation_mode": str(strategy.get("observation_mode", "")),
        "handle": {
            "kind": str(handle.get("kind", "")),
            "reference": str(handle.get("reference", "")),
        },
        "deadline_seconds": int(strategy.get("deadline_seconds", 0) or 0),
        "condition": str(strategy.get("condition", "")),
        "terminal_evidence": {},
        "raw_content_included": False,
        "claim_boundary": WAIT_BINDING_CLAIM_BOUNDARY,
    }


def consume_wait_completion(
    binding: Mapping[str, Any],
    *,
    outcome: str,
    summary: Any = "",
    evidence_refs: Sequence[Any] = (),
    recovery_action: str = "",
) -> dict[str, object]:
    """Close an armed binding into exactly one terminal state.

    A second completion for the same binding is recorded as ignored rather than
    applied. A notification delivered twice must not reopen a closed wait, and a
    second, different outcome must not silently overwrite the first one.
    """
    closed = dict(binding)
    if closed.get("completion_consumed"):
        closed["duplicate_completion_ignored"] = True
        return closed
    state = _normalize_choice(outcome, WAIT_TERMINAL_STATES, "failed")
    compact_refs, omitted_refs = compact_context_refs(list(evidence_refs), max_items=MAX_EVIDENCE_REFS)
    closed.update(
        {
            "binding_state": state,
            "completion_consumed": True,
            "terminal_evidence": {
                "summary": compact_visible_text(
                    sanitize_user_facing_progress_text(summary) or _default_terminal_summary(state),
                    max_chars=MAX_SUMMARY_CHARS,
                ),
                "evidence_refs": compact_refs,
                "omitted_evidence_ref_count": omitted_refs,
                "recovery_action": compact_visible_text(recovery_action, max_chars=MAX_WAIT_REASON_CHARS)
                or _default_recovery_action(state),
                "raw_content_included": False,
            },
        }
    )
    unmapped = _unmapped_choice_source(outcome, WAIT_TERMINAL_STATES)
    if unmapped:
        closed["unmapped_source_outcome"] = unmapped
    return closed


def evaluate_wait_trace(calls: Sequence[Any]) -> dict[str, object]:
    """Judge a recorded call sequence against the no-poll contract.

    One launch followed by one completion event passes. A launch followed by
    repeated agent-initiated status reads before the completion is the exact
    failure this contract exists to stop, and is reported as
    `polling_loop_detected` rather than as a stylistic note.

    Each entry is a mapping with a `call` from `WAIT_TRACE_CALLS`; an
    `agent_status_read` may carry `decision_changing: true` to spend the single
    midpoint peek.
    """
    if not isinstance(calls, (list, tuple)):
        return {
            "schema_version": EXECUTION_WAIT_TRACE_SCHEMA_VERSION,
            "call_count": 0,
            "launch_count": 0,
            "agent_status_read_count": 0,
            "decision_changing_peek_count": 0,
            "user_requested_status_read_count": 0,
            "terminal_call": "",
            "midpoint_peek_budget": MIDPOINT_PEEK_BUDGET,
            "violations": ["trace_is_not_a_recorded_call_sequence"],
            "no_poll": False,
            "claim_boundary": _WAIT_TRACE_CLAIM_BOUNDARY,
        }
    violations: list[str] = []
    launch_count = 0
    agent_reads = 0
    decision_changing_peeks = 0
    user_reads = 0
    terminal_call = ""
    for index, entry in enumerate(calls):
        call = _normalize_choice(
            entry.get("call") if isinstance(entry, Mapping) else entry,
            set(WAIT_TRACE_CALLS),
            "",
        )
        if not call:
            violations.append("unrecognized_trace_call")
            continue
        if terminal_call and call not in ("user_requested_status_read",):
            violations.append("calls_after_terminal_state")
            continue
        if call == "launch":
            launch_count += 1
            if index != 0:
                violations.append("launch_is_not_the_first_call")
            if launch_count > 1:
                violations.append("duplicate_launch")
            continue
        if call == "user_requested_status_read":
            user_reads += 1
            continue
        if call == "agent_status_read":
            agent_reads += 1
            decision_changing = bool(isinstance(entry, Mapping) and entry.get("decision_changing"))
            if decision_changing:
                decision_changing_peeks += 1
            else:
                violations.append("non_decision_changing_peek")
            if agent_reads > MIDPOINT_PEEK_BUDGET:
                violations.append("polling_loop_detected")
            continue
        terminal_call = call
    if launch_count == 0:
        violations.append("missing_launch")
    if not terminal_call:
        violations.append("unterminated_wait")
    return {
        "schema_version": EXECUTION_WAIT_TRACE_SCHEMA_VERSION,
        "call_count": len(calls),
        "launch_count": launch_count,
        "agent_status_read_count": agent_reads,
        "decision_changing_peek_count": decision_changing_peeks,
        "user_requested_status_read_count": user_reads,
        "terminal_call": terminal_call,
        "midpoint_peek_budget": MIDPOINT_PEEK_BUDGET,
        "violations": _dedupe(violations),
        "no_poll": not violations,
        "claim_boundary": _WAIT_TRACE_CLAIM_BOUNDARY,
    }


def wait_strategy_policy_reference(
    *,
    mechanism: Any = "",
    observation_mode: Any = "",
) -> dict[str, object]:
    """The wait-strategy block carried inside the coding progress policy.

    `mechanism` and `observation_mode` are the selection a live dispatch made,
    when it made one. Both are normalized against the closed vocabularies and an
    unrecognized value is recorded as refused rather than dropped, so "nothing
    was selected" stays distinguishable from "something we do not understand was
    selected".
    """
    normalized_mechanism = _normalize_choice(mechanism, set(WAIT_MECHANISMS), "")
    normalized_mode = _normalize_choice(observation_mode, set(WAIT_OBSERVATION_MODES), "")
    if normalized_mechanism and not normalized_mode:
        normalized_mode = _MECHANISM_OBSERVATION_MODES[normalized_mechanism]
    reference: dict[str, object] = {
        "schema_version": EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION,
        "precondition": "select_and_arm_the_wait_strategy_before_starting_long_running_work",
        "binds_to": "host_completion_primitive_observed_at_dispatch",
        "mechanisms": list(WAIT_MECHANISMS),
        "observation_modes": list(WAIT_OBSERVATION_MODES),
        "work_kinds": list(WAIT_WORK_KINDS),
        "host_capabilities": list(WAIT_HOST_CAPABILITIES),
        "terminal_states": list(WAIT_TERMINAL_STATES),
        "completion_consumed_once": True,
        "deadline_required": True,
        "cancellation_path_required": True,
        "fallback_required_when_capability_absent": True,
        "diagnostic_peek_policy": diagnostic_peek_policy(),
        "selected_mechanism": normalized_mechanism,
        "selected_observation_mode": normalized_mode,
    }
    refused = {
        "unmapped_source_mechanism": _unmapped_choice_source(mechanism, set(WAIT_MECHANISMS)),
        "unmapped_source_observation_mode": _unmapped_choice_source(observation_mode, set(WAIT_OBSERVATION_MODES)),
    }
    omitted = {key: value for key, value in refused.items() if value}
    if omitted:
        reference["omitted"] = omitted
    return reference


def _observed_capabilities(values: Sequence[Any]) -> tuple[set[str], list[str]]:
    observed: set[str] = set()
    unrecognized: list[str] = []
    for value in values or ():
        normalized = _normalize_token(value)
        if normalized in WAIT_HOST_CAPABILITIES:
            observed.add(normalized)
        elif normalized:
            text = compact_visible_text(value, max_chars=MAX_WAIT_REASON_CHARS)
            if text and text not in unrecognized:
                unrecognized.append(text)
    return observed, unrecognized


def _mechanism_supported(mechanism: str, observed: set[str]) -> bool:
    required = _MECHANISM_REQUIRED_CAPABILITY[mechanism]
    return not required or required in observed


def _selection_reason(mechanism: str, missing: list[str]) -> str:
    if not missing:
        return f"host_supports_{mechanism}"
    return f"degraded_to_{mechanism}_because_host_lacks_{'_and_'.join(missing)}"


def _default_terminal_summary(state: str) -> str:
    return {
        "completed": "Bound handle reported completion; evidence stayed in artifacts.",
        "failed": "Bound handle reported failure; evidence stayed in artifacts.",
        "cancelled": "Wait was cancelled through its recorded cancellation path.",
        "timed_out": "Wait reached its hard deadline without a completion signal.",
        "lost_handle": "Bound handle became unobservable before a completion signal arrived.",
    }[state]


def _default_recovery_action(state: str) -> str:
    return {
        "completed": "read_the_referenced_result_evidence",
        "failed": "report_the_failure_and_choose_the_next_action",
        "cancelled": "confirm_the_handle_stopped_then_report",
        "timed_out": "report_the_deadline_and_re_arm_or_stop_explicitly",
        "lost_handle": "re_observe_the_handle_once_then_report_it_as_unobservable",
    }[state]


def _unmapped_wait_sources(*, work_kind: Any, expected_duration_class: Any, handle_kind: Any) -> dict[str, object]:
    refused = {
        "unmapped_source_work_kind": _unmapped_choice_source(work_kind, set(WAIT_WORK_KINDS)),
        "unmapped_source_duration_class": _unmapped_choice_source(expected_duration_class, set(WAIT_DURATION_CLASSES)),
        "unmapped_source_handle_kind": _unmapped_choice_source(handle_kind, set(WAIT_HANDLE_KINDS)),
    }
    return {key: value for key, value in refused.items() if value}


def _unmapped_choice_source(value: Any, allowed: set[str] | tuple[str, ...]) -> str:
    normalized = _normalize_token(value)
    if not normalized or normalized in allowed:
        return ""
    return compact_visible_text(value, max_chars=MAX_WAIT_REASON_CHARS)


def _normalize_choice(value: Any, allowed: set[str] | tuple[str, ...], fallback: str) -> str:
    normalized = _normalize_token(value)
    return normalized if normalized in allowed else fallback


def _normalize_token(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
