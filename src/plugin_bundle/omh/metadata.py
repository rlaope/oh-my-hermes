from __future__ import annotations

PROVIDED_TOOLS = (
    "omh_capabilities",
    "omh_context",
    "omh_delegate_route",
    "omh_gather_evidence",
    "omh_hud",
    "omh_interact",
    "omh_memory",
    "omh_probe",
    "omh_recommend",
    "omh_role",
    "omh_source_trust",
    "omh_status",
    "omh_todo",
)
REQUIRED_HOOKS = ("on_session_end", "pre_llm_call", "pre_tool_call")
OPTIONAL_HOOKS = ("pre_verify",)
PROVIDED_HOOKS = REQUIRED_HOOKS + OPTIONAL_HOOKS

TOOL_FILE_STEMS = {
    "omh_capabilities": "capability_tool",
    "omh_context": "context_tool",
    "omh_delegate_route": "delegate_route_tool",
    "omh_gather_evidence": "evidence_tool",
    "omh_hud": "hud_tool",
    "omh_interact": "chat_tool",
    "omh_memory": "memory_tool",
    "omh_probe": "probe_tool",
    "omh_recommend": "recommend_tool",
    "omh_role": "role_tool",
    "omh_source_trust": "source_trust_tool",
    "omh_status": "status_tool",
    "omh_todo": "todo_tool",
}

TOOLS_REQUIRING_ROLE_CATALOG = frozenset({"omh_role"})

# The name Hermes' `memory.provider` config key must carry for OMH's provider to
# load. Hermes runs at most one external provider, so selecting it is an opt-in
# the operator makes, never something setup does on their behalf.
MEMORY_PROVIDER_NAME = "omh"
