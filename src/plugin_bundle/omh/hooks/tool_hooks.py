from __future__ import annotations

from .. import runtime_paths

import json
from typing import Protocol, TypeGuard

from ..degradation import runtime_binding_degradation
from ..approval_bypass import record_approval_bypass
from ..host_observation import observe_plugin_hook_call
from ..omh_roles import extract_role_marker, resolve_role_name, role_aliases, role_names
from ..tool_bursts import record_tool_call, record_tool_call_close
from ..toolcall_rules import toolcall_rule_directive


def pre_tool_call(**kwargs: object) -> dict[str, object] | None:
    """Return only host-supported pre-tool directives or role warnings."""
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True)
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as exc:
        # A missing rules owner cannot safely authorize the tool. This is the
        # native host's supported veto, not a swallowed rule failure.
        return {**runtime_binding_degradation(exc), "action": "block",
                "message": "OMH runtime binding unavailable; tool rules could not be checked. Tool call blocked."}
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
    rule_directive = toolcall_rule_directive(
        tool_name=kwargs.get("tool_name"),
        tool_input=kwargs.get("tool_input") if "tool_input" in kwargs else kwargs.get("args"),
        session_id=str(kwargs.get("session_id", "") or kwargs.get("task_id", "") or ""),
        omh_home=omh_home,
    )
    if rule_directive is not None:
        # A blocked call never dispatches, so it must not tick the
        # parallel-shot burst ledger (its claim boundary is "the host
        # dispatched the calls as one batch").
        return dict(rule_directive)
    # Only the normal host loop invokes native Kanban tools. Correlation runs
    # after OMH's user veto; it never dispatches or grants a native permission.
    try:
        from ..agent_board_bridge import pre_agent_board
    except ModuleNotFoundError as error:
        if error.name is None or not (error.name == "omh" or error.name.startswith("omh.")):
            raise
    else:
        board_directive = pre_agent_board(kwargs)
        if board_directive is not None:
            return board_directive
    # Tick the parallel-shot ledger and, when the host supplies a
    # tool_call_id, open the in-flight entry post_tool_call closes. This is
    # the only place OMH can see either fact.
    record_tool_call(
        kwargs.get("tool_name"),
        omh_home=omh_home,
        tool_call_id=kwargs.get("tool_call_id"),
        turn_id=kwargs.get("turn_id"),
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
    """
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True)
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as exc:
        return runtime_binding_degradation(exc)
    _ = observe_plugin_hook_call("post_tool_call", kwargs)
    try:
        from ..agent_board_bridge import post_agent_board
    except ModuleNotFoundError as error:
        if error.name is None or not (error.name == "omh" or error.name.startswith("omh.")):
            raise
    else:
        post_agent_board(kwargs)
    record_tool_call_close(
        kwargs.get("tool_call_id"),
        omh_home=omh_home,
    )
    return None


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
