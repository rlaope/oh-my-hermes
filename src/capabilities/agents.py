from __future__ import annotations

from ..catalogs.roles import RoleDefinition, role_definitions
from .schema import AGENT_ROLE_CAPABILITY_SCHEMA_VERSION, PREPARED_NOT_OBSERVED


_TEAM_ELIGIBILITY = {
    "research-lead": "member",
    "planning-lead": "lead",
    "review-gate": "verifier",
    "coding-handoff": "lead",
}


def agent_role_capabilities() -> list[dict[str, object]]:
    return [_role_capability(role) for role in sorted(role_definitions(), key=lambda item: item.id)]


def _role_capability(role: RoleDefinition) -> dict[str, object]:
    return {
        "schema_version": AGENT_ROLE_CAPABILITY_SCHEMA_VERSION,
        "id": role.id,
        "display_name": role.title,
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
        "source_refs": ["src/catalogs/roles.py"],
    }


def _default_patterns(role: RoleDefinition) -> list[str]:
    if role.id == "research-lead":
        return ["clarify_then_plan", "fanout_synthesize"]
    if role.id == "planning-lead":
        return ["clarify_then_plan", "plan_execute_verify"]
    if role.id == "review-gate":
        return ["adversarial_review", "plan_execute_verify"]
    if role.id == "coding-handoff":
        return ["executor_session_handoff", "team_staged_pipeline", "worktree_isolated_workers"]
    return ["single_lane"]
