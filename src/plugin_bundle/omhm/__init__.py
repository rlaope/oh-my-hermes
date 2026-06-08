from __future__ import annotations

_TOOLSET = "omhm"


def register(ctx):
    """Register the OMHM thin native bridge with Hermes."""
    from .hooks.llm_hooks import pre_llm_call
    from .tools.status_tool import OMHM_STATUS_SCHEMA, omhm_status_handler

    ctx.register_tool(
        "omhm_status",
        _TOOLSET,
        OMHM_STATUS_SCHEMA,
        omhm_status_handler,
        description=OMHM_STATUS_SCHEMA["description"],
    )
    ctx.register_hook("pre_llm_call", pre_llm_call)
