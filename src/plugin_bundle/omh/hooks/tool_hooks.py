from __future__ import annotations

from .. import runtime_paths

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from typing import Protocol, TypeGuard, runtime_checkable

from ..degradation import runtime_binding_degradation
from ..approval_bypass import record_approval_bypass
from ..host_observation import observe_plugin_hook_call
from ..omh_roles import extract_role_marker, resolve_role_name, role_aliases, role_names
from ..tool_bursts import (
    record_repeat_refusal,
    record_tool_call,
    record_tool_call_close,
    repeat_call_directive,
    tool_args_digest,
    tool_result_digest,
)
from ..toolcall_rule_faults import record_toolcall_rule_fault
from ..toolcall_rules import toolcall_rule_directive
from .session_attendance import escalation_can_reach_a_person


@runtime_checkable
class _BoardBridge(Protocol):
    """The two names the tool-call hooks need from the board bridge."""

    def pre_agent_board(self, kwargs: Mapping[str, object]) -> dict[str, object] | None: ...
    def post_agent_board(self, kwargs: Mapping[str, object]) -> None: ...


def _agent_board_bridge() -> _BoardBridge | None:
    """Return the board bridge, or None when this host has no usable one.

    Deliberately not `except ModuleNotFoundError` with an `omh`-prefixed name
    check. Hermes' loaders keep a half-initialized module in `sys.modules`
    when `exec_module` raises, so this import can resolve to a stub that has
    the module but not the names: an `ImportError` whose `name` is the
    BUNDLE's own dotted path, never `omh`. The old check re-raised exactly
    that, and every tool call logged a hook warning while the bridge was dead
    anyway (#1623). Widening the check to `ImportError` would not have helped
    on its own -- the name it carries still is not `omh` -- so the bridge is
    taken by attribute instead: a module that cannot supply both names is no
    bridge, and one broken module must not take the hook down on every call.
    """
    try:
        from .. import agent_board_bridge
    except ImportError:
        return None
    return agent_board_bridge if isinstance(agent_board_bridge, _BoardBridge) else None


def _rule_directive_or_recorded_fault(
    *,
    tool_name: object,
    tool_input: object,
    session_id: str,
    omh_home: str,
) -> dict[str, str] | None:
    """Evaluate the person's tool-call rules; on an unexpected failure, allow and record.

    ALLOW, deliberately, and the choice is the point of this handler.

    `toolcall_rules` states its own contract as fail-open, and every failure it
    anticipated already degrades to "no intervention". This covers the ones it
    did not. Blocking instead was rejected twice over. It contradicts the
    contract the rest of that module documents, and it is the shape of #1674:
    one broken state, every tool call of every session refused.

    The narrower "block only what a rule could have matched by tool name" was
    evaluated and rejected on a fact about the schema, not on taste: `tools` is
    optional and an empty scope matches every tool, so a single unscoped rule
    -- the default shape -- makes that filter match every call. For the common
    rules file it IS "block everything", wearing a narrower name.

    What made allowing the worse surprise was that it was SILENT: the host
    logs one WARNING and then DEBUG only, so the person's blocks stop and
    nothing says so. That is what this removes. The fault is counted where
    `omh doctor` reports it, by name, with the last error.

    No context note is injected. A persistent fault fires on every tool call,
    and a banner on that path would repeat for the whole session.
    """
    try:
        return toolcall_rule_directive(
            tool_name=tool_name,
            tool_input=tool_input,
            session_id=session_id,
            omh_home=omh_home,
        )
    except Exception as exc:  # noqa: BLE001 - classified in tests/test_broad_exception_policy.py
        # Broad on purpose: the value here is catching what the rules module
        # did NOT anticipate. A narrower tuple would re-raise exactly the
        # unanticipated type this exists for, and that escape is the
        # unreported allow.
        # The TYPE only, never `str(exc)`. An exception message is free text
        # from whatever raised: a `re.error` quotes the person's own rule
        # pattern, a `KeyError` quotes a key, a handler formatting with `!r`
        # quotes an argument fragment. The record's redaction policy is
        # metadata-only, and a type name is enough for doctor to name the
        # fault.
        record_toolcall_rule_fault(
            tool_name=tool_name,
            error_type=type(exc).__name__,
            observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            omh_home=omh_home,
        )
        return None


def pre_tool_call(**kwargs: object) -> dict[str, object] | None:
    """Return only host-supported pre-tool directives or role warnings."""
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True)
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as exc:
        # DEGRADE, for every binding fault, including the ones that named a
        # store. This narrows a recorded safety decision, so the trade-off it
        # replaces is restated rather than dropped (#1733).
        #
        # #1674 removed the veto for a session no profile owns and kept it
        # everywhere else, on a reason that was sound in isolation: a refusal
        # that NAMED a store leaves a rules file possibly existing and
        # certainly unread, and an unreadable store cannot authorize a call a
        # rule in it might have blocked.
        #
        # What that reasoning could not see is the case one level down. When
        # the store DOES resolve and the rules file itself cannot be
        # evaluated -- absent, malformed, oversized, permission-denied, or
        # raising something the module never anticipated -- the call is
        # allowed, every time. `toolcall_rules` documents fail-open as its
        # contract, and #1732 rejected blocking on a rule-gate failure by
        # name, calling it the shape of #1674. So OMH allowed the case where it
        # knew exactly which rules file it had failed to read, and refused
        # the case where it could not locate one at all: least informed, most
        # severe. Degrading here makes the ladder monotone. It does not
        # weaken the rules file, which still blocks whenever it loads and
        # matches.
        #
        # What this costs, stated plainly: while a home cannot bind, no tool
        # call in it is checked against the person's rules. That window is
        # real. It is the same window a malformed rules file already opens,
        # it closes when the binding is repaired, and it is not a defence
        # against the actor it resembles -- anyone able to corrupt a profile
        # config can equally delete the rules file or point `omh_home` at an
        # empty store.
        #
        # What it buys: one control character in a profile `config.yaml` no
        # longer blocks every tool call of every session in that home. The
        # host validator OMH binds through raises on that byte, on every
        # call, for as long as it is there (measured against the installed
        # `hermes_cli.config`).
        #
        # No retry. Of the writers that can leave that config unreadable,
        # only a person's editor saving in place is transient, and its window
        # is that writer's own syscalls rather than a microsecond; Hermes and
        # OMH both replace the file atomically and cannot produce the state
        # at all. Everything else reaching here is a persistent property of a
        # config, a path or the host, where a retry would double the cost of
        # every tool call for as long as the fault lasts.
        #
        # On THIS hook the result is a SILENT allow, stated plainly rather
        # than dressed up, for two separate reasons neither of which this
        # handler can fix. Nothing is written to a store because there is no
        # store -- that is what the fault means, and writing to a fallback
        # home would be the cross-profile write this binding path exists to
        # prevent. And the returned payload is not a record either: Hermes
        # reads `action` from a `pre_tool_call` result and skips every other
        # shape (`hermes_cli/plugins.py`,
        # `_get_pre_tool_call_directive_details`), while a hook result's
        # `context` is consumed on the `pre_llm_call` path only
        # (`agent/turn_context.py`). `observe_plugin_hook_call` sits below
        # this return and is not reached.
        #
        # What an operator can still see, on the same fault. `pre_llm_call`
        # returns this same degradation and its `context` IS injected into
        # the turn, once per turn, which is the surface where naming the
        # exception type earns its place. And for the config-fault class the
        # host reports itself: a backup copy of the broken file plus a
        # stderr warning naming the YAML error and its position, once per
        # process per file signature.
        return runtime_binding_degradation(exc)
    _ = observe_plugin_hook_call("pre_tool_call", kwargs)
    # The approval-bypass ledger observes session state, not this call's
    # outcome, so it ticks before the rule gate — a blocked call still sees
    # the same Shift+Tab flag.
    record_approval_bypass(omh_home=omh_home)
    # User-authored toolcall rules intervene first: a block directive is the
    # strongest host-supported response (hermes_cli/plugins.py,
    # `_get_pre_tool_call_directive_details`: "``block`` vetoes the tool call
    # outright (the message becomes the tool result the model sees)"). The
    # host passes the tool arguments as ``args``; ``tool_input`` is accepted
    # for bundle-internal callers and tests.
    tool_input = _tool_arguments(kwargs)
    session_id = str(kwargs.get("session_id", "") or kwargs.get("task_id", "") or "")
    rule_directive = _rule_directive_or_recorded_fault(
        tool_name=kwargs.get("tool_name"),
        tool_input=tool_input,
        session_id=session_id,
        omh_home=omh_home,
    )
    if rule_directive is not None:
        # A blocked call never dispatches, so it must not tick the
        # parallel-shot burst ledger (its claim boundary is "the host
        # dispatched the calls as one batch").
        return dict(rule_directive)
    # The repeat guard runs after the user's own rules and before anything
    # that observes a dispatch, for the same reason: it intervenes on a
    # call, so nothing downstream may record that call as having happened.
    # Hashed once here and handed to the gate, the interception counter and
    # the ledger, so a tool call canonicalizes its arguments exactly once.
    # `block` at the first stage and `approve` at the second are both
    # host-supported here (hermes_cli/plugins.py,
    # `_get_pre_tool_call_directive_details`: "``{"action": "approve",
    # "message", "rule_key"?}`` (escalate ANY tool to the human-approval
    # gate; ``rule_key`` picks the ``[a]lways`` allowlist grain)").
    args_digest = tool_args_digest(tool_input)
    # Stage two asks a person. Where there is none, the host resolves the
    # gate without one -- blocking with its own wording under the `deny`
    # default, and AUTO-APPROVING under `approvals.unattended_mode: approve`,
    # which would run the very call stage one was refusing. So the escalation
    # is withheld and stage one's block stands (`session_attendance`).
    #
    # Computed once and used twice: the gate decides this call with it, and
    # the ledger records it. `escalation_can_reach_a_person` reads two
    # process-global maps, and the HUD reader is a DIFFERENT interpreter --
    # the TUI widget spawns one every two seconds -- where both maps are
    # empty and the predicate would answer "attended" for every session. So
    # the reader takes the recorded answer instead of asking again, and this
    # is the one place that answer is produced (#1687).
    escalation_allowed = escalation_can_reach_a_person(session_id)
    repeat_directive = repeat_call_directive(
        tool_name=kwargs.get("tool_name"),
        args_digest=args_digest,
        session_id=session_id,
        omh_home=omh_home,
        escalation_allowed=escalation_allowed,
    )
    if repeat_directive is not None:
        # Counted as intercepted, not as a call: it is what moves the
        # streak from the block stage to the approval stage, and it is
        # deliberately not evidence that the call ran or that the person
        # denied it. OMH never observes how the host's gate was answered.
        record_repeat_refusal(
            tool_name=kwargs.get("tool_name"),
            args_digest=args_digest,
            session_id=session_id,
            omh_home=omh_home,
        )
        return dict(repeat_directive)
    # Only the normal host loop invokes native Kanban tools. Correlation runs
    # after OMH's user veto; it never dispatches or grants a native permission.
    bridge = _agent_board_bridge()
    if bridge is not None:
        board_directive = bridge.pre_agent_board(kwargs)
        if board_directive is not None:
            return board_directive
    # Tick the parallel-shot ledger and, when the host supplies a
    # tool_call_id, open the in-flight entry post_tool_call closes. This is
    # the only place OMH can see either fact. The same write advances this
    # session's repeat streak, which is why the guard above counts only
    # calls that actually reached dispatch.
    record_tool_call(
        kwargs.get("tool_name"),
        omh_home=omh_home,
        tool_call_id=kwargs.get("tool_call_id"),
        turn_id=kwargs.get("turn_id"),
        args_digest=args_digest,
        session_id=session_id,
        escalation_allowed=escalation_allowed,
    )
    context_parts: list[str] = []
    payload: dict[str, object] = {}
    role_warning = _delegate_role_warning(kwargs)
    if role_warning:
        context_parts.append(role_warning)

    if not context_parts:
        return None
    payload["context"] = "\n\n".join(context_parts)
    return payload


def post_tool_call(**kwargs: object) -> dict[str, object] | None:
    """Close the in-flight ledger entry pre_tool_call opened for this call.

    A supported Hermes observer hook (`install/hook_integrity.py`
    `HOOK_REVIEWS["post_tool_call"]`), paired with pre_tool_call by
    tool_call_id. It never blocks or rewrites a tool result -- it only
    closes the exact in-flight state the HUD's liveness signal reads, which
    is what tells "stopped with an incomplete todo item" apart from "still
    running" and keeps the parallel-shot badge from lingering past the ring
    ceiling. A host that omits tool_call_id is a silent no-op here; the
    entry pre_tool_call never opened simply never closes early.

    It also digests what the call returned, which is the one thing
    `pre_tool_call` structurally cannot see and the whole of what tells a
    loop from a poll (#1706). The digest is metadata under the same rule
    as the argument digest -- a length and a bounded one-way hash, never
    the text -- and a result this seam cannot digest leaves the entry
    unknown, which degrades the guard to the argument comparison it
    shipped with rather than to a refusal.
    """
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True)
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as exc:
        return runtime_binding_degradation(exc)
    _ = observe_plugin_hook_call("post_tool_call", kwargs)
    bridge = _agent_board_bridge()
    if bridge is not None:
        bridge.post_agent_board(kwargs)
    record_tool_call_close(
        kwargs.get("tool_call_id"),
        omh_home=omh_home,
        session_id=str(kwargs.get("session_id", "") or kwargs.get("task_id", "") or ""),
        tool_name=kwargs.get("tool_name"),
        # The same canonicalization `pre_tool_call` applied to the same
        # dict: the host coerces a call's arguments once, before either
        # hook sees them (`model_tools.handle_function_call` runs
        # `coerce_tool_args` first), so the two digests agree. If another
        # plugin rewrote them in between with a `modify` directive they
        # will not, and the entry simply stays unknown.
        args_digest=tool_args_digest(_tool_arguments(kwargs)),
        # A blocked call's "result" is the refusal, not the tool's answer,
        # and on this guard's own blocks it is OMH's message about the
        # loop. Digesting it wrote a foreign value into the history of a
        # SIBLING call that really ran -- they match on tool and
        # arguments, which is all `_fill_result_digest` can compare -- so
        # the cycle chain broke and the ladder restarted. Measured on a
        # period-1 loop of 20 calls: dispatched two at a time the guard
        # blocked once and never escalated, where #1708 escalated at call
        # 13 at any width. The host states this in a structured field
        # rather than in the text (`model_tools.handle_function_call`
        # emits `status="blocked"` on exactly that path), so the field is
        # what is read -- never the wording of the message.
        #
        # This guard is exactly one host string wide, and the degradation
        # is silent, so it is worth naming: a `post_tool_call` that omits
        # `status`, or sends anything other than `blocked`, restores the
        # defect in full -- one block and no escalation under concurrent
        # dispatch -- and the symptom looks like a guard that is working.
        # It is correct on this host because
        # `model_tools.handle_function_call` is the only emitter and the
        # literal is lowercase `blocked`; a host that changes either
        # needs this read changed with it.
        result_digest=(
            ""
            if str(kwargs.get("status", "") or "").strip().lower() == "blocked"
            else tool_result_digest(kwargs.get("result"))
        ),
    )
    return None


def _tool_arguments(kwargs: Mapping[str, object]) -> object:
    """This call's arguments, read the same way on both tool hooks.

    The host passes them as ``args``; ``tool_input`` is the bundle-internal
    and test spelling. One order, in one place, because the two hooks
    reading it in opposite orders meant a caller supplying both digested
    two different dicts at `pre_tool_call` and `post_tool_call`, so the
    history entry stayed unknown -- degrading correctly, for the wrong
    reason, invisibly.
    """
    return kwargs.get("tool_input") if "tool_input" in kwargs else kwargs.get("args")


class _JsonDecoder(Protocol):
    def loads(self, s: str) -> object: ...


_decoder: _JsonDecoder = json


def _is_dict(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _delegate_role_warning(kwargs: dict[str, object]) -> str:
    if str(kwargs.get("tool_name", "") or "") != "delegate_task":
        return ""
    tool_input: object = kwargs.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            parsed = _decoder.loads(tool_input)
        except json.JSONDecodeError:
            return ""
        tool_input = parsed if _is_dict(parsed) else {}
    if not _is_dict(tool_input):
        return ""
    marker = extract_role_marker(str(tool_input.get("goal", "") or ""))
    if not marker:
        return ""
    available = role_names()
    aliases = role_aliases()
    if marker in available or resolve_role_name(marker) in available:
        return ""
    return (
        f"[OMH Role Warning] Unknown role '{marker}' in delegate_task goal. "
        f"Available roles: {', '.join(available) or '(none)'}. "
        f"Legacy aliases: {', '.join(sorted(aliases)) or '(none)'}. "
        "No OMH role context will be injected for that subagent."
    )
