from __future__ import annotations

_TOOLSET = "omh"


def register(ctx):
    """Register the OMH thin native bridge with Hermes."""
    from .hooks.llm_hooks import pre_llm_call
    from .tools.status_tool import OMH_STATUS_SCHEMA, omh_status_handler

    ctx.register_tool(
        "omh_status",
        _TOOLSET,
        OMH_STATUS_SCHEMA,
        omh_status_handler,
        description=OMH_STATUS_SCHEMA["description"],
    )
    ctx.register_hook("pre_llm_call", pre_llm_call)
