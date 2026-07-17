from __future__ import annotations

from dataclasses import dataclass

from .roles import role_definitions
from ..skills.catalog import installable_skill_names


SPECIALIST_CATALOG_SCHEMA_VERSION = "specialist_catalog/v1"
SPECIALIST_RECOMMENDATION_SCHEMA_VERSION = "specialist_recommendation/v1"
SPECIALIST_EVIDENCE_BOUNDARY = (
    "A specialist profile is prepared guidance only. It is not worker dispatch, tool execution, implementation, "
    "critique completion, validation, review, CI, merge-readiness, or merge evidence."
)


@dataclass(frozen=True)
class SpecialistDefinition:
    """Describe task-phase expertise without creating a hidden runtime worker."""

    id: str
    title: str
    purpose: str
    task_phases: tuple[str, ...]
    eligible_skill_ids: tuple[str, ...]
    role_projection: str
    required_context: tuple[str, ...]
    quality_checks: tuple[str, ...]
    critique_checkpoints: tuple[str, ...]
    fallback_specialist_ids: tuple[str, ...]
    activation_policy: str
    evidence_boundary: str = SPECIALIST_EVIDENCE_BOUNDARY
    runtime_claim: str = "prepared_profile_not_runtime_agent"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "purpose": self.purpose,
            "task_phases": list(self.task_phases),
            "eligible_skill_ids": list(self.eligible_skill_ids),
            "role_projection": self.role_projection,
            "required_context": list(self.required_context),
            "quality_checks": list(self.quality_checks),
            "critique_checkpoints": list(self.critique_checkpoints),
            "fallback_specialist_ids": list(self.fallback_specialist_ids),
            "activation_policy": self.activation_policy,
            "evidence_boundary": self.evidence_boundary,
            "runtime_claim": self.runtime_claim,
        }


_SPECIALISTS = (
    SpecialistDefinition(
        id="discovery-research",
        title="Discovery Research",
        purpose="Turn an uncertain question, including AI or usability research, into bounded source-backed context before planning.",
        task_phases=("research",),
        eligible_skill_ids=("web-research", "best-practice-research", "research-brief", "source-finder", "research-department"),
        role_projection="researcher",
        required_context=("research question", "target user or task when usability matters", "usability dimension when applicable", "source boundary", "freshness requirement"),
        quality_checks=("source/inference separation", "freshness disclosure", "unknowns retained", "generalizability limits when applicable"),
        critique_checkpoints=("research-scope-review", "synthesis-claim-review"),
        fallback_specialist_ids=("product-planning",),
        activation_policy="router_suggested",
    ),
    SpecialistDefinition(
        id="product-planning",
        title="Product Planning",
        purpose="Make goals, tradeoffs, acceptance criteria, and verification strategy reviewable before handoff.",
        task_phases=("clarify", "planning"),
        eligible_skill_ids=("deep-interview", "plan", "ralplan", "loop"),
        role_projection="planner",
        required_context=("goal", "non-goals", "constraints", "acceptance criteria"),
        quality_checks=("decision-changing ambiguity resolved", "alternatives recorded", "verification shape named"),
        critique_checkpoints=("plan-critique", "handoff-readiness-review"),
        fallback_specialist_ids=("discovery-research", "implementation-handoff"),
        activation_policy="plan_selected",
    ),
    SpecialistDefinition(
        id="implementation-handoff",
        title="Implementation Handoff",
        purpose="Prepare executor-neutral coding work with explicit ownership, stages, and observed-evidence gates.",
        task_phases=("implementation", "handoff"),
        eligible_skill_ids=("ultragoal", "ultrawork", "ultraprocess", "ralph", "ai-slop-cleaner", "build-failure-triage"),
        role_projection="handoff-guide",
        required_context=("selected executor", "acceptance criteria", "verification expectations"),
        quality_checks=("executor named", "prepared/observed boundary", "worktree and review expectations"),
        critique_checkpoints=("pre-handoff-critique", "post-change-review", "completion-audit"),
        fallback_specialist_ids=("product-planning", "delivery-quality"),
        activation_policy="handoff_selected",
    ),
    SpecialistDefinition(
        id="visual-quality",
        title="Visual Quality",
        purpose="Turn UI work into observable layout, accessibility, and visual regression checks.",
        task_phases=("design", "verification"),
        eligible_skill_ids=("design-quality-gate", "visual-qa", "frontend", "accessibility-audit", "browser-operator"),
        role_projection="reviewer",
        required_context=("target surface", "reference or acceptance state", "viewport/device scope"),
        quality_checks=("visual evidence", "responsive scope", "accessibility review"),
        critique_checkpoints=("design-critique", "visual-regression-review"),
        fallback_specialist_ids=("implementation-handoff", "delivery-quality"),
        activation_policy="router_suggested",
    ),
    SpecialistDefinition(
        id="operations-data",
        title="Operations Data",
        purpose="Keep operational and structured-data work explicit about source, causality limits, and decisions.",
        task_phases=("operations", "analysis"),
        eligible_skill_ids=("data-analysis", "ops-review", "ops-observability-card", "feedback-triage"),
        role_projection="operator",
        required_context=("data source", "time window", "decision question", "causality limits"),
        quality_checks=("source scope", "correlation/cause separation", "missing-data disclosure"),
        critique_checkpoints=("analysis-design-review", "decision-claim-review"),
        fallback_specialist_ids=("discovery-research", "product-planning"),
        activation_policy="router_suggested",
    ),
    SpecialistDefinition(
        id="delivery-quality",
        title="Delivery Quality",
        purpose="Keep review, QA, and release claims tied to concrete current evidence.",
        task_phases=("review", "verification", "release"),
        eligible_skill_ids=("code-review", "ultraqa", "ask"),
        role_projection="reviewer",
        required_context=("artifact under review", "expected behavior", "evidence source"),
        quality_checks=("findings grounded", "verification is current", "residual risk stated"),
        critique_checkpoints=("adversarial-review", "completion-claim-audit"),
        fallback_specialist_ids=("implementation-handoff",),
        activation_policy="handoff_selected",
    ),
)


def specialist_definitions() -> tuple[SpecialistDefinition, ...]:
    return _SPECIALISTS


def specialist_for_skill(skill_id: str, *, phase: str = "") -> SpecialistDefinition | None:
    candidates = [profile for profile in _SPECIALISTS if skill_id in profile.eligible_skill_ids]
    if phase:
        phase_matches = [profile for profile in candidates if phase in profile.task_phases]
        return phase_matches[0] if phase_matches else None
    return candidates[0] if candidates else None


def recommend_specialist(selected_skill: str, *, task_phase: str) -> dict[str, object] | None:
    """Return an optional prepared profile recommendation without selecting an executor."""
    specialist = specialist_for_skill(selected_skill, phase=task_phase)
    if specialist is None:
        return None
    return {
        "schema_version": SPECIALIST_RECOMMENDATION_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "selected_skill": selected_skill,
        "task_phase": task_phase,
        "specialist": specialist.to_dict(),
        "claim_boundary": SPECIALIST_EVIDENCE_BOUNDARY,
    }


def validate_specialist_catalog() -> dict[str, object]:
    known_roles = {role.id for role in role_definitions()}
    known_skills = set(installable_skill_names())
    known_specialists = {profile.id for profile in _SPECIALISTS}
    errors: list[str] = []
    for profile in _SPECIALISTS:
        if profile.role_projection not in known_roles:
            errors.append(f"{profile.id}: unknown role projection {profile.role_projection}")
        for skill_id in profile.eligible_skill_ids:
            if skill_id not in known_skills:
                errors.append(f"{profile.id}: unknown skill {skill_id}")
        for fallback in profile.fallback_specialist_ids:
            if fallback not in known_specialists:
                errors.append(f"{profile.id}: unknown fallback specialist {fallback}")
        if profile.activation_policy not in {"router_suggested", "plan_selected", "handoff_selected"}:
            errors.append(f"{profile.id}: unsupported activation policy")
    return {"schema_version": SPECIALIST_CATALOG_SCHEMA_VERSION, "ok": not errors, "errors": errors}
