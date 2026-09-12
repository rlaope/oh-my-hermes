from __future__ import annotations

from functools import partial
from importlib import import_module
from typing import Protocol


class _PluginContext(Protocol):
    def register_tool(self, name: str, toolset: str, schema: object, handler: object, **kwargs: object) -> object: ...
    def register_hook(self, name: str, handler: object) -> object: ...


_TOOLSET = "omh"


def _host_supports_hook(hook_name: str, *, require_declared: bool = False) -> bool:
    try:
        hermes_plugins = import_module("hermes_cli.plugins")
    except ModuleNotFoundError as exc:
        if exc.name in {"hermes_cli", "hermes_cli.plugins"}:
            return not require_declared
        raise
    valid_hooks = getattr(hermes_plugins, "VALID_HOOKS", None)
    if not isinstance(valid_hooks, (list, tuple, set, frozenset)):
        return not require_declared
    return hook_name in valid_hooks


def _register_optional_surface(ctx: object, method_name: str, *args: object) -> None:
    """Call a host registration method when this host offers one.

    OMH must not assume a Hermes context shape: assuming one is what silently
    unregistered every tool and hook. A host without the method is a host that
    does not want that surface, not an error.
    """
    method = getattr(ctx, method_name, None)
    if not callable(method):
        return
    try:
        _ = method(*args)
    except (TypeError, ValueError):
        return


def _register_optional_hook(ctx: _PluginContext, hook_name: str, callback: object) -> None:
    if not _host_supports_hook(hook_name):
        return
    try:
        _ = ctx.register_hook(hook_name, callback)
    except ValueError:
        return


def register(ctx: _PluginContext) -> None:
    """Register the OMH thin native bridge with Hermes.

    Two different loaders call this with two different contexts: the plugin
    loader, and the *memory provider* loader in ``plugins/memory/__init__.py``.
    Both now get the full registration, deliberately.

    This used to branch on ``hasattr(ctx, "register_memory_provider")`` and
    return early, assuming only the memory collector had that attribute. Hermes
    made both halves of the assumption false, and the failure was silent.
    ``PluginContext`` gained ``register_memory_provider`` -- recorded and inert
    unless ``memory.provider`` selects the plugin, added so a plugin's
    ``register()`` would stop dying on a missing attribute -- so OMH took the
    memory branch on the plugin path and returned. Meanwhile the collector's
    ``__getattr__`` began delegating every other ``register_*`` call to a real
    ``PluginContext``, so a provider "has the same registration surface as any
    other plugin". Result: every OMH tool and hook registered nowhere, while
    the plugin still reported ``enabled`` with no error. The only symptom was
    `omh_*` tools quietly absent from Hermes.

    Nothing is left to discriminate on, and nothing needs discriminating.
    Registering the provider on the plugin path is inert, and running the tool
    wiring on the memory path reaches the same registry. The early return only
    ever saved importing the tool modules on the memory path; that is the price
    of not silently registering nothing.

    Naming ``register_memory_provider`` here is also what makes this directory
    visible to Hermes' provider discovery, which text-scans ``__init__.py``.
    """
    from . import runtime_paths
    runtime_paths.note_host_registration(ctx)
    from .memory_provider import OmhMemoryProvider

    _register_optional_surface(ctx, "register_memory_provider", OmhMemoryProvider())
    # ``get_config`` is a real Hermes PluginContext API.  Disabled installs
    # neither import the guard nor import SQLite nor register its hooks.
    get_config = getattr(ctx, "get_config", None)
    activity_config = get_config("group_chat_activity", None) if callable(get_config) else None
    activity_enabled = isinstance(activity_config, dict) and activity_config.get("enabled") is True
    activity_status = None
    if activity_enabled and _host_supports_hook("on_room_member_activity", require_declared=True):
        from .tools.status_tool import group_activity_status
        try:
            from .native_activity_observer import ObserverHost, register as register_activity
            if isinstance(ctx, ObserverHost):
                activity_status = register_activity(ctx).status
            else:
                activity_status = lambda: {**group_activity_status(True), "compatibility": "unload_contract_unsupported"}
        except (OSError, ValueError, ImportError):
            # An optional observer failure must not unregister the normal bridge.
            activity_status = lambda: {**group_activity_status(True), "compatibility": "observer_setup_failed",
                                       "last_outcome": "setup_failed", "next_action": "Check OMH core availability and profile key permissions."}
    egress_config = get_config("egress_attempts", None) if callable(get_config) else None
    if isinstance(egress_config, dict) and egress_config.get("enabled") is True:
        from .egress_attempts import register as register_egress_attempts
        register_egress_attempts(ctx, egress_config)

    from .hooks.llm_hooks import pre_llm_call
    from .hooks.result_transforms import transform_tool_result
    from .hooks.session_hooks import on_session_end
    from .hooks.tool_hooks import post_tool_call, pre_tool_call
    from .hooks.verify_hooks import pre_verify
    from .tools.agent_board_tool import OMH_AGENT_BOARD_SCHEMA, omh_agent_board_handler
    from .tools.capability_tool import OMH_CAPABILITIES_SCHEMA, omh_capabilities_handler
    from .tools.chat_tool import OMH_INTERACT_SCHEMA, omh_interact_handler
    from .tools.context_tool import OMH_CONTEXT_SCHEMA, omh_context_handler
    from .tools.delegate_route_tool import OMH_DELEGATE_ROUTE_SCHEMA, omh_delegate_route_handler
    from .tools.decision_gate_tool import OMH_DECISION_GATE_SCHEMA, omh_decision_gate_handler
    from .tools.evidence_tool import OMH_EVIDENCE_SCHEMA, omh_evidence_handler
    from .tools.hud_tool import OMH_HUD_SCHEMA, omh_hud_handler
    from .tools.memory_tool import OMH_MEMORY_SCHEMA, omh_memory_handler
    from .tools.probe_tool import OMH_PROBE_SCHEMA, omh_probe_handler
    from .tools.recommend_tool import OMH_RECOMMEND_SCHEMA, omh_recommend_handler
    from .tools.role_tool import OMH_ROLE_SCHEMA, omh_role_handler
    from .tools.run_summary_tool import OMH_RUN_SUMMARY_SCHEMA, omh_run_summary_handler
    from .tools.source_trust_tool import OMH_SOURCE_TRUST_SCHEMA, omh_source_trust_handler
    from .tools.status_tool import OMH_STATUS_SCHEMA, omh_status_handler
    from .tools.todo_tool import OMH_TODO_SCHEMA, omh_todo_handler

    _ = ctx.register_tool(
        "omh_agent_board",
        _TOOLSET,
        OMH_AGENT_BOARD_SCHEMA,
        omh_agent_board_handler,
        description=OMH_AGENT_BOARD_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_capabilities",
        _TOOLSET,
        OMH_CAPABILITIES_SCHEMA,
        omh_capabilities_handler,
        description=OMH_CAPABILITIES_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_context",
        _TOOLSET,
        OMH_CONTEXT_SCHEMA,
        omh_context_handler,
        description=OMH_CONTEXT_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_delegate_route",
        _TOOLSET,
        OMH_DELEGATE_ROUTE_SCHEMA,
        omh_delegate_route_handler,
        description=OMH_DELEGATE_ROUTE_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_decision_gate",
        _TOOLSET,
        OMH_DECISION_GATE_SCHEMA,
        omh_decision_gate_handler,
        description=OMH_DECISION_GATE_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_gather_evidence",
        _TOOLSET,
        OMH_EVIDENCE_SCHEMA,
        omh_evidence_handler,
        description=OMH_EVIDENCE_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_hud",
        _TOOLSET,
        OMH_HUD_SCHEMA,
        omh_hud_handler,
        description=OMH_HUD_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_interact",
        _TOOLSET,
        OMH_INTERACT_SCHEMA,
        omh_interact_handler,
        description=OMH_INTERACT_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_memory",
        _TOOLSET,
        OMH_MEMORY_SCHEMA,
        omh_memory_handler,
        description=OMH_MEMORY_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_probe",
        _TOOLSET,
        OMH_PROBE_SCHEMA,
        omh_probe_handler,
        description=OMH_PROBE_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_recommend",
        _TOOLSET,
        OMH_RECOMMEND_SCHEMA,
        omh_recommend_handler,
        description=OMH_RECOMMEND_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_role",
        _TOOLSET,
        OMH_ROLE_SCHEMA,
        omh_role_handler,
        description=OMH_ROLE_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_run_summary",
        _TOOLSET,
        OMH_RUN_SUMMARY_SCHEMA,
        omh_run_summary_handler,
        description=OMH_RUN_SUMMARY_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_source_trust",
        _TOOLSET,
        OMH_SOURCE_TRUST_SCHEMA,
        omh_source_trust_handler,
        description=OMH_SOURCE_TRUST_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_status",
        _TOOLSET,
        OMH_STATUS_SCHEMA,
        partial(omh_status_handler, group_activity_enabled=activity_enabled, group_activity_observer=activity_status),
        description=OMH_STATUS_SCHEMA["description"],
    )
    _ = ctx.register_tool(
        "omh_todo",
        _TOOLSET,
        OMH_TODO_SCHEMA,
        omh_todo_handler,
        description=OMH_TODO_SCHEMA["description"],
    )
    _ = ctx.register_hook("on_session_end", on_session_end)
    _ = ctx.register_hook("pre_llm_call", pre_llm_call)
    _ = ctx.register_hook("pre_tool_call", pre_tool_call)
    _register_optional_hook(ctx, "post_tool_call", post_tool_call)
    _register_optional_hook(ctx, "pre_verify", pre_verify)
    _register_optional_hook(ctx, "transform_tool_result", transform_tool_result)
    get_config = getattr(ctx, "get_config", None)
    browser_config = get_config("browser_adapter", {}) if callable(get_config) else {}
    if isinstance(browser_config, dict) and browser_config.get("enabled") is True:
        from .browser_bridge import register as register_browser

        setattr(ctx, "browser_task", register_browser(ctx, browser_config))
