from __future__ import annotations

PROVIDED_TOOLS = ("omh_capabilities", "omh_gather_evidence", "omh_hud", "omh_role", "omh_status")
PROVIDED_HOOKS = ("on_session_end", "pre_llm_call", "pre_tool_call")

TOOL_FILE_STEMS = {
    "omh_capabilities": "capability_tool",
    "omh_gather_evidence": "evidence_tool",
    "omh_hud": "hud_tool",
    "omh_role": "role_tool",
    "omh_status": "status_tool",
}

TOOLS_REQUIRING_ROLE_CATALOG = frozenset({"omh_role"})
