from __future__ import annotations

_TOOLSET = "omh"


def register(ctx):
    """Register the OMH thin native bridge with Hermes."""
    from .hooks.llm_hooks import pre_llm_call
    from .hooks.session_hooks import on_session_end
    from .hooks.tool_hooks import pre_tool_call
    from .tools.hud_tool import OMH_HUD_SCHEMA, omh_hud_handler
    from .tools.role_tool import OMH_ROLE_SCHEMA, omh_role_handler
    from .tools.status_tool import OMH_STATUS_SCHEMA, omh_status_handler

    ctx.register_tool(
        "omh_hud",
        _TOOLSET,
        OMH_HUD_SCHEMA,
        omh_hud_handler,
        description=OMH_HUD_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_role",
        _TOOLSET,
        OMH_ROLE_SCHEMA,
        omh_role_handler,
        description=OMH_ROLE_SCHEMA["description"],
    )
    ctx.register_tool(
        "omh_status",
        _TOOLSET,
        OMH_STATUS_SCHEMA,
        omh_status_handler,
        description=OMH_STATUS_SCHEMA["description"],
    )
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
