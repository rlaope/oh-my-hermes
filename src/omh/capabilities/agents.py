from __future__ import annotations

from ..catalogs.roles import (
    ROLE_BOUNDARY_RULE,
    ROLE_CHAT_RULE,
    ROLE_WORKFLOW_CONTEXT_RULE,
    RoleDefinition,
    role_definitions,
)
from .schema import AGENT_ROLE_CAPABILITY_SCHEMA_VERSION, PREPARED_NOT_OBSERVED


_TEAM_ELIGIBILITY = {
    "guide": "lead",
    "researcher": "member",
    "planner": "lead",
    "operator": "member",
    "memory-keeper": "member",
    "handoff-guide": "lead",
    "tracker": "member",
    "reviewer": "verifier",
}


def agent_role_capabilities() -> list[dict[str, object]]:
    return [_role_capability(role) for role in sorted(role_definitions(), key=lambda item: item.id)]


def _role_capability(role: RoleDefinition) -> dict[str, object]:
    return {
        "schema_version": AGENT_ROLE_CAPABILITY_SCHEMA_VERSION,
        "id": role.id,
        "display_name": role.title,
        "legacy_ids": list(role.legacy_ids),
        "mode": "descriptor",
        "runtime_claim": "descriptor_not_runtime_agent",
        "owns": list(role.owns),
        "does_not_own": [
            "hidden runtime execution",
            "unobserved worker dispatch",
            "unobserved worktree creation",
            "review, CI, merge-readiness, or merge evidence without matching runtime records",
        ],
        "primary_skills": list(role.primary_skills),
        "primary_harnesses": list(role.primary_harnesses),
        "allowed_wrapper_actions": list(role.wrapper_actions),
        "workflow_context_rule": ROLE_WORKFLOW_CONTEXT_RULE,
        "chat_rule": ROLE_CHAT_RULE,
        "role_boundary_rule": ROLE_BOUNDARY_RULE,
        "default_orchestration_patterns": _default_patterns(role),
        "team_eligibility": _TEAM_ELIGIBILITY.get(role.id, "not_eligible"),
        "tool_requirements": {
            "derivation_status": "partial",
            "required_tools": [],
            "reason": "Current role catalog does not declare concrete tool or MCP requirements.",
        },
        "evidence_ladder": [
            "role_descriptor_available",
            "wrapper_action_prepared",
            "runtime_observation_required_for_execution_claim",
        ],
        "evidence_boundary": role.evidence_boundary,
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "install_surface": ["generated_role_reference", "plugin_tool", "wrapper_descriptor"],
        "source_refs": ["src/omh/catalogs/roles.py"],
    }


def _default_patterns(role: RoleDefinition) -> list[str]:
    if role.id == "guide":
        return ["single_lane", "clarify_then_plan"]
    if role.id == "researcher":
        return ["clarify_then_plan", "fanout_synthesize"]
    if role.id == "planner":
        return ["clarify_then_plan", "plan_execute_verify"]
    if role.id == "operator":
        return ["single_lane", "scheduled_ops_blueprint", "materials_generation_handoff"]
    if role.id == "memory-keeper":
        return ["single_lane"]
    if role.id == "reviewer":
        return ["adversarial_review", "plan_execute_verify"]
    if role.id == "handoff-guide":
        return ["executor_session_handoff", "team_staged_pipeline", "worktree_isolated_workers"]
    if role.id == "tracker":
        return ["single_lane", "executor_session_handoff"]
    return ["single_lane"]
