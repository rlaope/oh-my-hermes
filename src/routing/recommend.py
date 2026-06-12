from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from ..skills.catalog import SkillDefinition, builtin_definitions


_TOKEN_RE = re.compile(r"[a-z0-9가-힣][a-z0-9가-힣-]*")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "when",
    "use",
    "task",
    "request",
    "workflow",
    "skill",
    "agent",
    "hermes",
}
_FALLBACK_SKILLS = ("oh-my-hermes", "plan", "deep-interview")
_FALLBACK_WHY = "No strong catalog metadata match; start with general routing/planning guidance."


@dataclass(frozen=True)
class RecommendationPolicy:
    next_action: str
    evidence_boundary: str
    wrapper_guidance: str


_DEFAULT_POLICY = RecommendationPolicy(
    next_action="show_workflow_guidance",
    evidence_boundary="Routing guidance is not execution evidence.",
    wrapper_guidance="Route conservatively and show the missing decision before claiming work started.",
)
_SKILL_POLICIES = {
    "cancel": RecommendationPolicy(
        next_action="cancel",
        evidence_boundary="Cancellation is observed only after the wrapper records the state change.",
        wrapper_guidance="Stop the active workflow state in the wrapper; do not create a plan, handoff, or execution claim.",
    ),
    "operating-rhythm": RecommendationPolicy(
        next_action="prepare_operating_record",
        evidence_boundary="An operating rhythm record is not evidence that a meeting, scrum, sprint, retro, decision, or action item happened.",
        wrapper_guidance="Prepare or update the local operations artifact; mark decisions and actions as prepared until supplied notes or acceptance are observed.",
    ),
    "report-package": RecommendationPolicy(
        next_action="prepare_report_package",
        evidence_boundary="A report package or PPT-ready outline is not source-review completion, stakeholder approval, presentation delivery, or binary PPTX export evidence.",
        wrapper_guidance="Prepare a Markdown/JSON report outline from supplied inputs; keep missing numbers and approvals explicit.",
    ),
    "reliability-review": RecommendationPolicy(
        next_action="prepare_reliability_review",
        evidence_boundary="A reliability review is not SLO pass, healthy error-budget, incident closure, remediation completion, verification, review, CI, or merge evidence.",
        wrapper_guidance="Collect service, SLO, incident, metric, and reference boundaries; create remediation handoffs only after an accepted fix direction exists.",
    ),
}
_CATEGORY_POLICIES = {
    "planning": RecommendationPolicy(
        next_action="present_plan",
        evidence_boundary="A recommendation or draft plan is not execution evidence.",
        wrapper_guidance="Show an Accept plan / Revise plan choice; keep Prepare handoff disabled until the plan is accepted.",
    ),
    "clarification": RecommendationPolicy(
        next_action="ask_clarification",
        evidence_boundary="A clarification question is not routing, planning, or execution evidence.",
        wrapper_guidance="Ask one blocking question in the same thread before selecting a workflow.",
    ),
    "research": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary="Research guidance is not implementation or verification evidence.",
        wrapper_guidance="Keep this in Hermes as source-backed research and summarize evidence before any later handoff.",
    ),
    "strategy": RecommendationPolicy(
        next_action="prepare_strategy_brief",
        evidence_boundary="A strategy brief is not an accepted decision or implementation evidence.",
        wrapper_guidance=(
            "Prepare options, tradeoffs, and decision notes in Hermes; keep implementation handoff disabled "
            "until a decision creates explicit code work."
        ),
    ),
    "meeting": RecommendationPolicy(
        next_action="prepare_meeting_brief",
        evidence_boundary="A meeting brief is not evidence that a meeting happened or decisions were accepted.",
        wrapper_guidance=(
            "Prepare agenda, prompts, and a record template in Hermes; do not treat preparation as observed "
            "meeting outcomes."
        ),
    ),
    "triage": RecommendationPolicy(
        next_action="triage_feedback",
        evidence_boundary="Feedback triage is not a roadmap, implementation plan, or coding handoff by default.",
        wrapper_guidance=(
            "Cluster feedback and recommend the next workflow; do not create a coding handoff unless code work "
            "is explicit."
        ),
    ),
    "operations": RecommendationPolicy(
        next_action="prepare_ops_review",
        evidence_boundary="An ops review is not implementation, release, CI, review, or merge evidence.",
        wrapper_guidance="Summarize observed status, risks, blockers, and follow-ups; keep unknowns explicit.",
    ),
    "delivery": RecommendationPolicy(
        next_action="present_app_delivery_loop",
        evidence_boundary="An app delivery loop is not implementation, deploy, monitoring, rollback, or completion evidence.",
        wrapper_guidance=(
            "Show the idea, decision, plan, handoff, verification, deploy, and monitoring stages; keep executor "
            "and deploy actions disabled until the matching acceptance or observation exists."
        ),
    ),
    "leadership": RecommendationPolicy(
        next_action="run_cto_loop",
        evidence_boundary="A CTO loop brief is not an accepted decision, implementation, deploy, or monitoring evidence.",
        wrapper_guidance=(
            "Keep roadmap, architecture, risk, delivery, and release-readiness decisions in Hermes; convert accepted "
            "implementation follow-ups into explicit executor-neutral handoffs and record status only from observed evidence."
        ),
    ),
    "monitoring": RecommendationPolicy(
        next_action="prepare_deploy_monitor_plan",
        evidence_boundary="A deploy and monitor plan is not deploy, health-check, rollback, or incident evidence.",
        wrapper_guidance=(
            "Show deploy checklist, health signals, rollback gates, and post-deploy status; record only observed "
            "deploy or monitoring evidence."
        ),
    ),
    "goal-loop": RecommendationPolicy(
        next_action="start_goal_loop",
        evidence_boundary=(
            "A goal loop is orchestration state only; it is not implementation, review, CI, merge, external "
            "publication, market response, or goal completion evidence."
        ),
        wrapper_guidance=(
            "Start the loop interview, ask for or apply a permission profile, then cycle research -> plan -> "
            "handoff -> feedback only inside that authority envelope. Record external outcomes as waiting until observed."
        ),
    ),
    "process": RecommendationPolicy(
        next_action="start_ultraprocess",
        evidence_boundary=(
            "An Ultraprocess route is process orchestration only; it is not implementation, review, docs sync, "
            "CI, PR creation, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Show the plan -> implementation handoff -> code review -> docs sync -> PR stages, ask for or apply "
            "an executor owner before code work, and keep every stage prepared_not_observed until matching evidence exists."
        ),
    ),
    "review": RecommendationPolicy(
        next_action="prepare_review_or_followup_handoff",
        evidence_boundary="A review recommendation is not a completed review or fix evidence.",
        wrapper_guidance="Surface findings separately from any code changes; fixes need their own executor evidence.",
    ),
    "operator": RecommendationPolicy(
        next_action="run_local_operator_check",
        evidence_boundary="Local operator guidance is not a completed health check until command output is observed.",
        wrapper_guidance="Run or display the local check result directly; record only observed command evidence.",
    ),
    "router": RecommendationPolicy(
        next_action="clarify_or_route",
        evidence_boundary="Routing guidance is not execution evidence.",
        wrapper_guidance="Route conservatively and show the missing decision before claiming work started.",
    ),
}
_HERMES_ROLE_POLICIES = {
    "codex-handoff-guidance": RecommendationPolicy(
        next_action="prepare_coding_handoff",
        evidence_boundary=(
            "A prepared coding handoff is not execution, review, CI, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Ask for or apply the selected executor/runtime profile, expose executor-neutral handoff/status actions, "
            "and mark prepared work as prepared_not_observed."
        ),
    ),
    "runtime-handoff-guidance": RecommendationPolicy(
        next_action="prepare_coding_runtime_handoff",
        evidence_boundary=(
            "A prepared coding runtime handoff is not runtime start, worker dispatch, worktree creation, execution, "
            "review, CI, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Ask for or apply the selected runtime profile, expose runtime/team/worktree/status actions, "
            "and mark prepared work as prepared_not_observed until observed runtime evidence exists."
        ),
    ),
}


@dataclass(frozen=True)
class Recommendation:
    skill: str
    description: str
    category: str
    phase: str
    hermes_role: str
    handoff_policy: str
    score: int
    confidence: str
    matched: tuple[str, ...]
    why: str
    next_action: str
    evidence_boundary: str
    wrapper_guidance: str
    suggested_prompt: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["matched"] = list(self.matched)
        return data


def recommend_skills(query: str, *, limit: int = 5) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("recommend --limit must be at least 1")

    normalized_query = query.strip().lower()
    query_tokens = _tokens(normalized_query)
    definitions = list(builtin_definitions())
    scored = [_score_definition(definition, normalized_query, query_tokens, query) for definition in definitions]
    matches = [recommendation for recommendation in scored if recommendation.score > 0]
    if not matches:
        matches = _fallback_recommendations(definitions, query)
        return [recommendation.to_dict() for recommendation in matches[:limit]]
    matches.sort(key=lambda recommendation: (-recommendation.score, recommendation.skill))
    return [recommendation.to_dict() for recommendation in matches[:limit]]


def _score_definition(
    definition: SkillDefinition,
    normalized_query: str,
    query_tokens: set[str],
    original_query: str,
) -> Recommendation:
    score = 0
    matched: set[str] = set()

    for trigger in definition.triggers:
        trigger_normalized = trigger.lower()
        if _phrase_match(normalized_query, trigger_normalized):
            score += 6
            matched.add(f"trigger:{trigger_normalized}")

    name_normalized = definition.name.lower()
    if _phrase_match(normalized_query, name_normalized):
        score += 5
        matched.add(f"name:{name_normalized}")

    description_normalized = definition.description.lower()
    if _phrase_match(normalized_query, description_normalized):
        score += 3
        matched.add("description:phrase")

    use_when_normalized = definition.use_when.lower()
    if _phrase_match(normalized_query, use_when_normalized):
        score += 3
        matched.add("use_when:phrase")

    for field_name, value in (("category", definition.category), ("phase", definition.phase)):
        normalized_value = value.lower()
        if _phrase_match(normalized_query, normalized_value):
            score += 2
            matched.add(f"{field_name}:{normalized_value}")

    trigger_tokens = _tokens(" ".join(definition.triggers))
    for token in sorted(query_tokens & trigger_tokens):
        score += 3
        matched.add(f"trigger:{token}")

    metadata_tokens = _tokens(" ".join((definition.name, definition.description, definition.use_when)))
    for token in sorted(query_tokens & metadata_tokens):
        score += 1
        matched.add(f"metadata:{token}")

    matched_tuple = tuple(sorted(matched))
    return Recommendation(
        skill=definition.name,
        description=definition.description,
        category=definition.category,
        phase=definition.phase,
        hermes_role=definition.hermes_role,
        handoff_policy=definition.handoff_policy,
        score=score,
        confidence=_confidence(score),
        matched=matched_tuple,
        why=_why(matched_tuple),
        next_action=_next_action(definition),
        evidence_boundary=_evidence_boundary(definition),
        wrapper_guidance=_wrapper_guidance(definition),
        suggested_prompt=_suggested_prompt(definition.name, original_query),
    )


def _fallback_recommendations(definitions: list[SkillDefinition], query: str) -> list[Recommendation]:
    by_name = {definition.name: definition for definition in definitions}
    recommendations = []
    for name in _FALLBACK_SKILLS:
        definition = by_name.get(name)
        if definition is None:
            continue
        recommendations.append(
            Recommendation(
                skill=definition.name,
                description=definition.description,
                category=definition.category,
                phase=definition.phase,
                hermes_role=definition.hermes_role,
                handoff_policy=definition.handoff_policy,
                score=0,
                confidence="low",
                matched=(),
                why=_FALLBACK_WHY,
                next_action=_next_action(definition),
                evidence_boundary=_evidence_boundary(definition),
                wrapper_guidance=_wrapper_guidance(definition),
                suggested_prompt=_suggested_prompt(definition.name, query),
            )
        )
    return recommendations


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in _TOKEN_RE.findall(value.lower()):
        for token in (raw_token, *raw_token.split("-")):
            if len(token) >= 3 and token not in _STOPWORDS:
                tokens.add(token)
    return tokens


def _phrase_match(query: str, value: str) -> bool:
    return bool(query and value and (query in value or value in query))


def _confidence(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _why(matched: tuple[str, ...]) -> str:
    if not matched:
        return _FALLBACK_WHY
    sources = sorted({item.split(":", 1)[0] for item in matched})
    return f"Matched {'/'.join(sources)} metadata for this task."


def _suggested_prompt(skill: str, query: str) -> str:
    return f"Use {skill} for: {query}"


def _policy_for(definition: SkillDefinition) -> RecommendationPolicy:
    return (
        _SKILL_POLICIES.get(definition.name)
        or _CATEGORY_POLICIES.get(definition.category)
        or _HERMES_ROLE_POLICIES.get(definition.hermes_role)
        or _DEFAULT_POLICY
    )


def _next_action(definition: SkillDefinition) -> str:
    return _policy_for(definition).next_action


def _evidence_boundary(definition: SkillDefinition) -> str:
    return _policy_for(definition).evidence_boundary


def _wrapper_guidance(definition: SkillDefinition) -> str:
    return _policy_for(definition).wrapper_guidance
