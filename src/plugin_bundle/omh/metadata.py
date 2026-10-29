from __future__ import annotations

PROVIDED_TOOLS = (
    "lsp_definition",
    "lsp_references",
    "lsp_rename",
    "omh_agent_board",
    "omh_capabilities",
    "omh_context",
    "omh_dag",
    "omh_decision_gate",
    "omh_delegate_route",
    "omh_document_plan",
    "omh_gather_evidence",
    "omh_hud",
    "omh_interact",
    "omh_jev_ask",
    "omh_loop",
    "omh_memory",
    "omh_probe",
    "omh_recommend",
    "omh_resume",
    "omh_role",
    "omh_route_answer",
    "omh_run_summary",
    "omh_search",
    "omh_source_trust",
    "omh_status",
    "omh_team",
    "omh_todo",
)
REQUIRED_HOOKS = ("on_session_end", "pre_llm_call", "pre_tool_call")
# post_tool_call is optional for the plugin as a whole. Without it the HUD
# retains burst-only behavior and agent-board preparation names the missing
# capability; no native board action may be armed for receipt correlation.
OPTIONAL_HOOKS = (
    "on_session_start",
    "post_tool_call",
    "pre_verify",
    "subagent_start",
    "subagent_stop",
    "transform_llm_output",
    "transform_tool_result",
)
# Sorted rather than concatenated: several downstream readers (the real
# loader observation's alphabetized registration report, the plugin.yaml
# `provides_hooks` conformance check) compare against this tuple's literal
# order, and required/optional membership stays independently checkable via
# REQUIRED_HOOKS/OPTIONAL_HOOKS regardless of where a hook sorts.
PROVIDED_HOOKS = tuple(sorted(REQUIRED_HOOKS + OPTIONAL_HOOKS))

TOOL_FILE_STEMS = {
    "lsp_definition": "lsp_nav_tool",
    "lsp_references": "lsp_nav_tool",
    "lsp_rename": "lsp_nav_tool",
    "omh_agent_board": "agent_board_tool",
    "omh_capabilities": "capability_tool",
    "omh_context": "context_tool",
    "omh_dag": "dag_tool",
    "omh_decision_gate": "decision_gate_tool",
    "omh_delegate_route": "delegate_route_tool",
    "omh_document_plan": "document_plan_tool",
    "omh_gather_evidence": "evidence_tool",
    "omh_hud": "hud_tool",
    "omh_interact": "chat_tool",
    "omh_jev_ask": "jev_ask_tool",
    "omh_loop": "loop_tool",
    "omh_memory": "memory_tool",
    "omh_probe": "probe_tool",
    "omh_recommend": "recommend_tool",
    "omh_resume": "resume_tool",
    "omh_role": "role_tool",
    "omh_route_answer": "route_answer_tool",
    "omh_run_summary": "run_summary_tool",
    "omh_search": "search_tool",
    "omh_source_trust": "source_trust_tool",
    "omh_status": "status_tool",
    "omh_team": "team_tool",
    "omh_todo": "todo_tool",
}

TOOLS_REQUIRING_ROLE_CATALOG = frozenset({"omh_role"})

# The name Hermes' `memory.provider` config key must carry for OMH's provider to
# load. Hermes runs at most one external provider, so selecting it is an opt-in
# the operator makes, never something setup does on their behalf.
MEMORY_PROVIDER_NAME = "omh"
