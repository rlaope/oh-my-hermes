from __future__ import annotations

from ..skills.catalog import (
    SkillDefinition,
    capability_definitions,
    primary_harness_for_skill,
    skill_exposure_payload,
)
from ..plugin_bundle.omh.awareness import awareness_lane_examples, awareness_primer_payload
from .schema import PREPARED_NOT_OBSERVED, SKILL_CAPABILITY_SCHEMA_VERSION


def skill_capabilities() -> list[dict[str, object]]:
    awareness = awareness_primer_payload()
    lane_by_skill = _awareness_lane_by_skill(awareness)
    return [
        _skill_capability(definition, awareness, lane_by_skill)
        for definition in sorted(capability_definitions(), key=lambda item: item.name)
    ]


def _skill_capability(
    definition: SkillDefinition,
    awareness: dict[str, object],
    lane_by_skill: dict[str, dict[str, object]],
) -> dict[str, object]:
    harness = primary_harness_for_skill(definition.name)
    exposure = skill_exposure_payload(definition.name)
    lane = lane_by_skill.get(definition.name)
    lane_id = str(lane.get("id") or "") if lane else ""
    lane_label = str(lane.get("label") or "") if lane else ""
    lane_use_for = str(lane.get("use_for") or "") if lane else ""
    return {
        "schema_version": SKILL_CAPABILITY_SCHEMA_VERSION,
        "id": definition.name,
        "display_name": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "primary_harness": harness,
        "surface_exposure": exposure["exposure"],
        "exposure": exposure["exposure"],
        "install_visibility": exposure["install_visibility"],
        "docs_visibility": exposure["docs_visibility"],
        "preferred_usage": exposure["preferred_usage"],
        "compatibility_alias": exposure["compatibility_alias"],
        "projections": exposure["projections"],
        "triggers": list(definition.triggers),
        "required_inputs": list(definition.required_inputs),
        "expected_outputs": list(definition.expected_outputs),
        "artifact_expectations": list(definition.artifact_expectations),
        "safety_rules": list(definition.safety_rules),
        "quality_tier": definition.quality_tier,
        "quality_bar": list(definition.quality_bar),
        "handoff_policy": definition.handoff_policy,
        "delegation_boundary": definition.delegation_boundary,
        "awareness_lane": lane_id,
        "awareness_lane_label": lane_label,
        "use_for": lane_use_for or definition.use_when,
        "workflow_routing_hint": _workflow_routing_hint(definition, lane_label, lane_use_for),
        "workflow_context_rule": str(awareness.get("all_skill_context_rule") or ""),
        "chat_rule": str(awareness.get("chat_rule") or ""),
        "fallback_rule": str(awareness.get("fallback_rule") or ""),
        "cross_lane_examples": awareness_lane_examples(lane_id),
        "do_not_use_when": list(definition.do_not_use_when),
        "orchestration_eligibility": _orchestration_eligibility(definition),
        "tool_requirements": {
            "derivation_status": "partial",
            "required_tools": [],
            "fallback": "No concrete tool or MCP requirement is declared by the existing skill catalog.",
        },
        "evidence_boundary": _skill_evidence_boundary(definition),
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "source_refs": ["src/omh/skills/catalog.py"],
    }


def _orchestration_eligibility(definition: SkillDefinition) -> list[str]:
    patterns = {"single_lane"}
    if definition.category in {"planning", "clarification", "strategy", "meeting", "triage"}:
        patterns.add("clarify_then_plan")
    if definition.category in {"execution", "process", "goal-loop", "delivery"}:
        patterns.add("plan_execute_verify")
    if definition.name in {"code-review", "ultraqa"} or definition.category == "review":
        patterns.add("adversarial_review")
    if definition.name in {"ultrawork", "team", "ultraprocess"}:
        patterns.add("team_staged_pipeline")
        patterns.add("worktree_isolated_workers")
    if definition.name in {"loop"}:
        patterns.add("loop_run_once")
    if definition.name == "research-department":
        patterns.add("research_department_workflow")
        patterns.add("scheduled_ops_blueprint")
    if "handoff" in definition.handoff_policy.lower() or "runtime" in definition.hermes_role:
        patterns.add("executor_session_handoff")
    if definition.category == "materials":
        patterns.add("materials_generation_handoff")
    return sorted(patterns)


def _awareness_lane_by_skill(awareness: dict[str, object]) -> dict[str, dict[str, object]]:
    lane_by_skill: dict[str, dict[str, object]] = {}
    lanes = awareness.get("lanes", [])
    if not isinstance(lanes, list):
        return lane_by_skill
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        skills = lane.get("skills", [])
        if not isinstance(skills, list):
            continue
        for skill in skills:
            lane_by_skill.setdefault(str(skill), lane)
    return lane_by_skill


def _workflow_routing_hint(definition: SkillDefinition, lane_label: str, lane_use_for: str) -> str:
    if lane_label and lane_use_for:
        return (
            f"Use `{definition.name}` when the request fits {lane_label}: {lane_use_for}. "
            "If the request crosses lanes, name the adjacent OMH workflow first."
        )
    return (
        f"Use `{definition.name}` when the request matches its catalog purpose: {definition.use_when}. "
        "If the request crosses lanes, name the adjacent OMH workflow first."
    )


def _skill_evidence_boundary(definition: SkillDefinition) -> str:
    if definition.category == "review":
        return "Review guidance or findings are not fix, verification, CI, merge-readiness, or merge evidence."
    if definition.category in {"execution", "process", "goal-loop"}:
        return "Execution-oriented workflow guidance remains prepared_not_observed until matching executor/runtime evidence exists."
    return "Skill routing and Hermes guidance are not execution evidence."
