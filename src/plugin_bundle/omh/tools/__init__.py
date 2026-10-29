from __future__ import annotations

from typing import Any

# Every tool name registered by `register()` in the parent package, in
# registration order. Kept as data so a check can walk the tool surface
# without importing the Hermes registration context; parity with the
# `register()` body is a test, not a convention.
BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "lsp_definition",
    "lsp_references",
    "lsp_rename",
    "omh_agent_board",
    "omh_capabilities",
    "omh_context",
    "omh_dag",
    "omh_delegate_route",
    "omh_decision_gate",
    "omh_document_plan",
    "omh_gather_evidence",
    "omh_hud",
    "omh_jev_ask",
    "omh_interact",
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


def builtin_tool_schemas() -> tuple[dict[str, Any], ...]:
    """Return every registered omh tool schema, name-sorted.

    Imports live inside the function for the same reason `register()` does it:
    the plugin bundle is loaded by Hermes, and a module-level import graph here
    would pull every tool module in on package import.
    """
    from .agent_board_tool import OMH_AGENT_BOARD_SCHEMA
    from .capability_tool import OMH_CAPABILITIES_SCHEMA
    from .chat_tool import OMH_INTERACT_SCHEMA
    from .context_tool import OMH_CONTEXT_SCHEMA
    from .dag_tool import OMH_DAG_SCHEMA
    from .delegate_route_tool import OMH_DELEGATE_ROUTE_SCHEMA
    from .decision_gate_tool import OMH_DECISION_GATE_SCHEMA
    from .document_plan_tool import OMH_DOCUMENT_PLAN_SCHEMA
    from .evidence_tool import OMH_EVIDENCE_SCHEMA
    from .hud_tool import OMH_HUD_SCHEMA
    from .jev_ask_tool import OMH_JEV_ASK_SCHEMA
    from .loop_tool import OMH_LOOP_SCHEMA
    from .lsp_nav_tool import OMH_LSP_DEFINITION_SCHEMA, OMH_LSP_REFERENCES_SCHEMA, OMH_LSP_RENAME_SCHEMA
    from .memory_tool import OMH_MEMORY_SCHEMA
    from .probe_tool import OMH_PROBE_SCHEMA
    from .recommend_tool import OMH_RECOMMEND_SCHEMA
    from .resume_tool import OMH_RESUME_SCHEMA
    from .role_tool import OMH_ROLE_SCHEMA
    from .route_answer_tool import OMH_ROUTE_ANSWER_SCHEMA
    from .run_summary_tool import OMH_RUN_SUMMARY_SCHEMA
    from .search_tool import OMH_SEARCH_SCHEMA
    from .source_trust_tool import OMH_SOURCE_TRUST_SCHEMA
    from .status_tool import OMH_STATUS_SCHEMA
    from .team_tool import OMH_TEAM_SCHEMA
    from .todo_tool import OMH_TODO_SCHEMA

    schemas = (
        OMH_AGENT_BOARD_SCHEMA,
        OMH_CAPABILITIES_SCHEMA,
        OMH_CONTEXT_SCHEMA,
        OMH_DAG_SCHEMA,
        OMH_DELEGATE_ROUTE_SCHEMA,
        OMH_DECISION_GATE_SCHEMA,
        OMH_DOCUMENT_PLAN_SCHEMA,
        OMH_EVIDENCE_SCHEMA,
        OMH_HUD_SCHEMA,
        OMH_INTERACT_SCHEMA,
        OMH_JEV_ASK_SCHEMA,
        OMH_LOOP_SCHEMA,
        OMH_LSP_DEFINITION_SCHEMA,
        OMH_LSP_REFERENCES_SCHEMA,
        OMH_LSP_RENAME_SCHEMA,
        OMH_MEMORY_SCHEMA,
        OMH_PROBE_SCHEMA,
        OMH_RECOMMEND_SCHEMA,
        OMH_RESUME_SCHEMA,
        OMH_ROLE_SCHEMA,
        OMH_ROUTE_ANSWER_SCHEMA,
        OMH_RUN_SUMMARY_SCHEMA,
        OMH_SEARCH_SCHEMA,
        OMH_SOURCE_TRUST_SCHEMA,
        OMH_STATUS_SCHEMA,
        OMH_TEAM_SCHEMA,
        OMH_TODO_SCHEMA,
    )
    return tuple(sorted(schemas, key=lambda schema: str(schema.get("name", ""))))


__all__ = ["BUILTIN_TOOL_NAMES", "builtin_tool_schemas"]
