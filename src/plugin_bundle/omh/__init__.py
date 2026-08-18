from __future__ import annotations

from importlib import import_module

_TOOLSET = "omh"


def _host_supports_hook(hook_name: str) -> bool:
    try:
        hermes_plugins = import_module("hermes_cli.plugins")
    except ModuleNotFoundError as exc:
        if exc.name in {"hermes_cli", "hermes_cli.plugins"}:
            return True
        raise
    valid_hooks = getattr(hermes_plugins, "VALID_HOOKS", None)
    if not isinstance(valid_hooks, (list, tuple, set, frozenset)):
        return True
    return hook_name in valid_hooks


def _register_optional_surface(ctx, method_name: str, *args: object) -> None:
    """Call a host registration method when this host offers one.

    OMH must not assume a Hermes context shape: assuming one is what silently
    unregistered every tool and hook. A host without the method is a host that
    does not want that surface, not an error.
    """
    method = getattr(ctx, method_name, None)
    if not callable(method):
        return
    try:
        method(*args)
    except (TypeError, ValueError):
        return


def _register_optional_hook(ctx, hook_name: str, callback: object) -> None:
    if not _host_supports_hook(hook_name):
        return
    try:
        ctx.register_hook(hook_name, callback)
    except ValueError:
        return


def register(ctx):
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
    from .memory_provider import OmhMemoryProvider

    _register_optional_surface(ctx, "register_memory_provider", OmhMemoryProvider())

    from .hooks.llm_hooks import pre_llm_call
    from .hooks.session_hooks import on_session_end
    from .hooks.tool_hooks import pre_tool_call
    from .hooks.verify_hooks import pre_verify
    from .tools.capability_tool import OMH_CAPABILITIES_SCHEMA, omh_capabilities_handler
    from .tools.chat_tool import OMH_INTERACT_SCHEMA, omh_interact_handler
    from .tools.context_tool import OMH_CONTEXT_SCHEMA, omh_context_handler
    from .tools.delegate_route_tool import OMH_DELEGATE_ROUTE_SCHEMA, omh_delegate_route_handler
    from .tools.evidence_tool import OMH_EVIDENCE_SCHEMA, omh_evidence_handler
    from .tools.hud_tool import OMH_HUD_SCHEMA, omh_hud_handler
    from .tools.memory_tool import OMH_MEMORY_SCHEMA, omh_memory_handler
    from .tools.probe_tool import OMH_PROBE_SCHEMA, omh_probe_handler
    from .tools.recommend_tool import OMH_RECOMMEND_SCHEMA, omh_recommend_handler
    from .tools.role_tool import OMH_ROLE_SCHEMA, omh_role_handler
    from .tools.source_trust_tool import OMH_SOURCE_TRUST_SCHEMA, omh_source_trust_handler
    from .tools.status_tool import OMH_STATUS_SCHEMA, omh_status_handler
    from .tools.todo_tool import OMH_TODO_SCHEMA, omh_todo_handler

    ctx.register_tool(
        "omh_capabilities",
        _TOOLSET,
        OMH_CAPABILITIES_SCHEMA,
        omh_capabilities_handler,
        description=OMH_CAPABILITIES_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_context",
        _TOOLSET,
        OMH_CONTEXT_SCHEMA,
        omh_context_handler,
        description=OMH_CONTEXT_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_delegate_route",
        _TOOLSET,
        OMH_DELEGATE_ROUTE_SCHEMA,
        omh_delegate_route_handler,
        description=OMH_DELEGATE_ROUTE_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_gather_evidence",
        _TOOLSET,
        OMH_EVIDENCE_SCHEMA,
        omh_evidence_handler,
        description=OMH_EVIDENCE_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_hud",
        _TOOLSET,
        OMH_HUD_SCHEMA,
        omh_hud_handler,
        description=OMH_HUD_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_interact",
        _TOOLSET,
        OMH_INTERACT_SCHEMA,
        omh_interact_handler,
        description=OMH_INTERACT_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_memory",
        _TOOLSET,
        OMH_MEMORY_SCHEMA,
        omh_memory_handler,
        description=OMH_MEMORY_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_probe",
        _TOOLSET,
        OMH_PROBE_SCHEMA,
        omh_probe_handler,
        description=OMH_PROBE_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_recommend",
        _TOOLSET,
        OMH_RECOMMEND_SCHEMA,
        omh_recommend_handler,
        description=OMH_RECOMMEND_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_role",
        _TOOLSET,
        OMH_ROLE_SCHEMA,
        omh_role_handler,
        description=OMH_ROLE_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_source_trust",
        _TOOLSET,
        OMH_SOURCE_TRUST_SCHEMA,
        omh_source_trust_handler,
        description=OMH_SOURCE_TRUST_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_status",
        _TOOLSET,
        OMH_STATUS_SCHEMA,
        omh_status_handler,
        description=OMH_STATUS_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_todo",
        _TOOLSET,
        OMH_TODO_SCHEMA,
        omh_todo_handler,
        description=OMH_TODO_SCHEMA["description"],
    )
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    _register_optional_hook(ctx, "pre_verify", pre_verify)
