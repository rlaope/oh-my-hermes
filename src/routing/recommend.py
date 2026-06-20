from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import lru_cache

from ..skills.catalog import SkillDefinition, routable_definitions
from .localization import normalized_phrase, prepare_routing_text, routing_tokens
from .policy import (
    RoutingGuardRule,
    active_routing_guard_rules,
    explicit_skill_invocation,
    is_explicit_one_off_request,
)


_STOPWORDS = {
    "the",
    "and",
    "are",
    "as",
    "for",
    "in",
    "is",
    "of",
    "or",
    "to",
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
    "해줘",
    "해주세요",
    "줘",
    "부탁",
    "정리해줘",
}
_FALLBACK_SKILLS = ("oh-my-hermes", "plan", "deep-interview")
_FALLBACK_WHY = "No strong catalog metadata match; start with general routing/planning guidance."
_GUARDRAIL_CANDIDATE_INJECTION_IDS = frozenset(
    {
        "img_summary_before_materials_or_delivery",
        "missed_workflow_research_recovery",
        "missed_workflow_operating_record_recovery",
        "product_shaping_before_ops_review",
        "workflow_learning_before_skill_management",
    }
)


@dataclass(frozen=True)
class RecommendationPolicy:
    next_action: str
    evidence_boundary: str
    wrapper_guidance: str


@dataclass(frozen=True)
class _PreparedDefinition:
    definition: SkillDefinition
    trigger_phrases: tuple[str, ...]
    trigger_tokens: frozenset[str]
    name_phrase: str
    description_phrase: str
    use_when_phrase: str
    category_phrase: str
    phase_phrase: str
    metadata_tokens: frozenset[str]


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
    "materials-package": RecommendationPolicy(
        next_action="prepare_material_package",
        evidence_boundary=(
            "A material package is not binary export, render QA, formula recalculation, stakeholder approval, "
            "delivery, or external upload evidence."
        ),
        wrapper_guidance=(
            "Prepare a material_artifact/v1 plan with target formats, source inputs, assumptions, missing inputs, "
            "QA ladder, and an executor-neutral generation handoff when a binary file is needed."
        ),
    ),
    "img-summary": RecommendationPolicy(
        next_action="prepare_visual_prompt_card",
        evidence_boundary=(
            "A prepared image-card brief is not generated image, visual QA, sharing, posting, attachment, or delivery evidence."
        ),
        wrapper_guidance=(
            "Prepare visual_prompt_card/v1 with short image-safe copy, generation prompt, negative prompt, "
            "language/aspect metadata, and visual_observation/v1 evidence requirements. Show generate action only "
            "when image_generation_capability/v1 is connected; otherwise route to image_generation_setup/v1 to choose "
            "a GPT image tool, existing Hermes connector, generic image tool, or prompt-only path."
        ),
    ),
    "workflow-learning": RecommendationPolicy(
        next_action="audit_learning_readiness",
        evidence_boundary=(
            "A workflow learning trace, eval, audit, candidate, regression case, or export is process-review evidence only; "
            "it is not model training, skill mutation, workflow execution, verification, CI, merge, or proof that future behavior is fixed."
        ),
        wrapper_guidance=(
            "Show the workflow learning card: record trace, run eval, add regression case, audit readiness, export a redacted review bundle, "
            "and keep human-reviewed improvement separate from automatic self-modification."
        ),
    ),
    "automation-blueprint": RecommendationPolicy(
        next_action="prepare_scheduled_ops_blueprint",
        evidence_boundary=(
            "A scheduled ops blueprint is not host cron creation, Hermes automation enablement, gateway delivery, "
            "source retrieval, no-agent execution, plugin load, connector invocation, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare hermes_ops_blueprint/v1 with schedule, delivery, silence, skill/context chain, and status-card "
            "copy; ask for missing runtime/delivery decisions and record observed evidence only when Hermes or the host runtime provides it."
        ),
    ),
    "research-department": RecommendationPolicy(
        next_action="prepare_research_department_plan",
        evidence_boundary=(
            "A research department plan is not observed source retrieval, synthesis-tool execution, knowledge-store writes, "
            "host cron creation, gateway delivery, conflict resolution, or verified briefing evidence."
        ),
        wrapper_guidance=(
            "Prepare research_department_plan/v1 with Scout, Analyst, and Briefer lanes, source_inbox/v1 buckets, "
            "briefing_status/v1 counts, knowledge-store and synthesis-tool preferences, and observed-only evidence requirements."
        ),
    ),
    "reliability-review": RecommendationPolicy(
        next_action="prepare_reliability_review",
        evidence_boundary="A reliability review is not SLO pass, healthy error-budget, incident closure, remediation completion, verification, review, CI, or merge evidence.",
        wrapper_guidance="Collect service, SLO, incident, metric, and reference boundaries; create remediation handoffs only after an accepted fix direction exists.",
    ),
    "web-research": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary=(
            "A web research route is not observed source retrieval, implementation, verification, "
            "or coding handoff evidence."
        ),
        wrapper_guidance=(
            "Keep this in Hermes as a source-backed research lane: ask for source boundaries, freshness, "
            "jurisdiction or version scope, source diversity, and citation confidence; report retrieval gaps "
            "before any later plan or handoff."
        ),
    ),
    "ultraqa": RecommendationPolicy(
        next_action="dispatch_to_workflow",
        evidence_boundary="A QA workflow route is not observed scenario execution, verification, fix evidence, CI, or release readiness evidence.",
        wrapper_guidance="Run the QA workflow as a Hermes-owned review lane; report scenarios, observed checks, gaps, and any follow-up handoff separately.",
    ),
}
_SKILL_POLICIES.update(
    {
        "github-event-ops": RecommendationPolicy(
            next_action="prepare_github_event_ops_card",
            evidence_boundary="A GitHub event ops card is not webhook delivery, API mutation, label application, review completion, CI rerun, or fix execution evidence.",
            wrapper_guidance="Classify PR, issue, review, and CI events into triage/review/label/fix-handoff actions; record GitHub mutations only when observed.",
        ),
        "agent-board": RecommendationPolicy(
            next_action="prepare_agent_board_card",
            evidence_boundary="An agent board card is not proof that another Hermes target accepted, worked, heartbeat-ed, or completed.",
            wrapper_guidance="Show task, handoff, heartbeat, blocker, and completion states per target/thread; require target-specific evidence before advancing.",
        ),
        "memory-curation-review": RecommendationPolicy(
            next_action="prepare_memory_curation_review",
            evidence_boundary="A memory curation review is not Hermes internal memory, MEMORY.md, USER.md, or skill-file modification evidence.",
            wrapper_guidance="Present stale/conflicting/duplicate memory candidates with approve/reject/update actions; write only after observed approval.",
        ),
        "gateway-intent-card": RecommendationPolicy(
            next_action="prepare_gateway_intent_card",
            evidence_boundary="A gateway intent card is not platform login, message send, thread mutation, attachment upload, or delivery evidence.",
            wrapper_guidance="Normalize origin, thread, delivery, silent-update, attachment, and status-update policy before any gateway action is claimed.",
        ),
        "executor-runtime-readiness": RecommendationPolicy(
            next_action="prepare_executor_runtime_readiness",
            evidence_boundary="Runtime readiness is not executor dispatch, plugin load, tool invocation, execution, review, CI, or merge evidence.",
            wrapper_guidance="Compare Codex, Claude Code, Hermes coding, and oh-my runtimes by tools, missing capabilities, credentials, and handoff mode.",
        ),
        "deliverable-package": RecommendationPolicy(
            next_action="prepare_deliverable_package",
            evidence_boundary="A deliverable package card is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.",
            wrapper_guidance="Track prepared, generated, QA, approved, attached, and delivered states separately for PPT/PDF/XLSX/DOCX/HWP/Markdown outputs.",
        ),
        "voice-operator": RecommendationPolicy(
            next_action="prepare_voice_operator_card",
            evidence_boundary="A voice operator card is not speech recognition proof, mobile notification delivery, platform action, or accepted execution evidence.",
            wrapper_guidance="Turn terse voice/mobile requests into concise clarify, plan, status, handoff, or confirmation cards; require confirmation for risky actions.",
        ),
        "toolbelt-readiness": RecommendationPolicy(
            next_action="prepare_toolbelt_readiness",
            evidence_boundary="A toolbelt readiness card is not MCP server installation, credential validation, API access, connector invocation, or successful workflow execution evidence.",
            wrapper_guidance="List required MCP/CLI/API/credential/connectors, observed availability, missing pieces, and setup or handoff next action.",
        ),
        "ops-observability-card": RecommendationPolicy(
            next_action="prepare_ops_observability_card",
            evidence_boundary="An ops observability card is not billing truth, provider quota truth, complete tracing, performance proof, or workflow completion evidence.",
            wrapper_guidance="Report token/cost/latency/run-history telemetry as wrapper-safe status with clear local-estimate vs provider-observed boundaries.",
        ),
        "agent-ops-review": RecommendationPolicy(
            next_action="prepare_agent_ops_review",
            evidence_boundary=(
                "An agent ops review card is not source retrieval, executor dispatch, coding progress, "
                "implementation, review, verification, CI, merge-readiness, merge, platform delivery, "
                "provider billing, or live runtime telemetry evidence."
            ),
            wrapper_guidance=(
                "Render a manager-facing quality and throughput card: workflow quality lanes, blockers, "
                "next actions, and throughput levers. Keep shell commands hidden from normal chat users and "
                "record only observed runtime/source/review evidence."
            ),
        ),
    }
)
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
        evidence_boundary="Research guidance is not observed source retrieval, implementation, or verification evidence.",
        wrapper_guidance=(
            "Keep this in Hermes as source-backed research, name source boundaries and freshness, summarize "
            "observed evidence with citations, and report retrieval gaps before any later handoff."
        ),
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
    "materials": RecommendationPolicy(
        next_action="prepare_material_package",
        evidence_boundary=(
            "Material packaging guidance is not binary file generation, render QA, formula recalculation, "
            "approval, delivery, or upload evidence."
        ),
        wrapper_guidance=(
            "Route the request into a material plan first; keep Hermes chat as the normal surface and use CLI "
            "artifacts only as backend/verifier state."
        ),
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
        next_action="assess_loopability",
        evidence_boundary=(
            "A goal loop is orchestration state only; it is not implementation, review, CI, merge, external "
            "publication, market response, or goal completion evidence."
        ),
        wrapper_guidance=(
            "Assess whether the request is a task, project, north-star ambition, external wait, or unclear goal before "
            "starting a loop. Only cycle research -> plan -> handoff -> feedback inside the selected authority envelope."
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
    "guide": RecommendationPolicy(
        next_action="clarify_or_route",
        evidence_boundary="Routing guidance is not plan acceptance, dispatch, execution, review, CI, or merge evidence.",
        wrapper_guidance="Route conservatively, show why the workflow was selected, and ask one focused question when confidence is low.",
    ),
    "researcher": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary="Research guidance is not observed source retrieval, implementation, or verification evidence.",
        wrapper_guidance="Keep evidence, inference, freshness, and unknowns separate before moving to planning or handoff.",
    ),
    "planner": RecommendationPolicy(
        next_action="present_plan",
        evidence_boundary="A recommendation or draft plan is not execution evidence.",
        wrapper_guidance="Show an Accept plan / Revise plan choice; keep handoff disabled until the plan is accepted.",
    ),
    "operator": RecommendationPolicy(
        next_action="prepare_operating_workflow",
        evidence_boundary="Operational workflow guidance is not meeting, delivery, file export, deploy, monitoring, or platform evidence.",
        wrapper_guidance="Prepare the business or product workflow card and keep missing observations visible.",
    ),
    "memory-keeper": RecommendationPolicy(
        next_action="prepare_memory_review",
        evidence_boundary="Memory guidance is not proof that Hermes internal memory, wiki, USER.md, MEMORY.md, or skill files changed.",
        wrapper_guidance="Present context candidates and require observed approval before applying memory or knowledge changes.",
    ),
    "handoff-guide": RecommendationPolicy(
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
    "tracker": RecommendationPolicy(
        next_action="refresh_status",
        evidence_boundary="Status guidance is not proof that a runtime, tool, MCP server, CI job, or platform action ran.",
        wrapper_guidance="Report only observed status, show missing evidence, and keep estimates separate from provider or runtime truth.",
    ),
    "reviewer": RecommendationPolicy(
        next_action="prepare_review_or_followup_handoff",
        evidence_boundary="A review recommendation is not a completed review or fix evidence.",
        wrapper_guidance="Surface findings separately from any code changes; fixes need their own executor evidence.",
    ),
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


def recommend_skills(query: str, *, limit: int = 5, apply_guardrails: bool = True) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("recommend --limit must be at least 1")

    routing_text = prepare_routing_text(query)
    normalized_query = normalized_phrase(routing_text.scoring_text)
    query_tokens = _tokens(normalized_query)
    prepared_definitions = _prepared_routable_definitions()
    definitions = [prepared.definition for prepared in prepared_definitions]
    explicit_skill = explicit_skill_invocation(query, {definition.name for definition in definitions})
    scored = [
        _score_definition(prepared, normalized_query, query_tokens, query, routing_text.locale_matches)
        for prepared in prepared_definitions
    ]
    if explicit_skill != "automation-blueprint" and is_explicit_one_off_request(normalized_query, query_tokens):
        scored = [recommendation for recommendation in scored if recommendation.skill != "automation-blueprint"]
    matches = [recommendation for recommendation in scored if recommendation.score > 0]
    if apply_guardrails:
        guards = active_routing_guard_rules(normalized_query, query_tokens, explicit_skill=explicit_skill)
        matches = _ensure_guardrail_candidates(matches, definitions, guards, query)
        matches = _apply_guardrail_reranking(
            matches,
            guards=guards,
        )
        visual_guard_active = any(guard.id == "img_summary_before_materials_or_delivery" for guard in guards)
        if explicit_skill != "img-summary" and not visual_guard_active:
            matches = [recommendation for recommendation in matches if recommendation.skill != "img-summary"]
            if not matches:
                matches = _fallback_recommendations(definitions, query)
                return [recommendation.to_dict() for recommendation in matches[:limit]]
    if not matches:
        matches = _fallback_recommendations(definitions, query)
        return [recommendation.to_dict() for recommendation in matches[:limit]]
    matches.sort(key=lambda recommendation: (-recommendation.score, recommendation.skill))
    return [recommendation.to_dict() for recommendation in matches[:limit]]


@lru_cache(maxsize=1)
def _prepared_routable_definitions() -> tuple[_PreparedDefinition, ...]:
    return tuple(_prepare_definition(definition) for definition in routable_definitions())


def _prepare_definition(definition: SkillDefinition) -> _PreparedDefinition:
    return _PreparedDefinition(
        definition=definition,
        trigger_phrases=tuple(normalized_phrase(trigger) for trigger in definition.triggers),
        trigger_tokens=frozenset(_tokens(" ".join(definition.triggers))),
        name_phrase=normalized_phrase(definition.name),
        description_phrase=normalized_phrase(definition.description),
        use_when_phrase=normalized_phrase(definition.use_when),
        category_phrase=normalized_phrase(definition.category),
        phase_phrase=normalized_phrase(definition.phase),
        metadata_tokens=frozenset(_tokens(" ".join((definition.name, definition.description, definition.use_when)))),
    )


def _score_definition(
    prepared: _PreparedDefinition,
    normalized_query: str,
    query_tokens: set[str],
    original_query: str,
    locale_matches: tuple[str, ...],
) -> Recommendation:
    definition = prepared.definition
    score = 0
    matched: set[str] = set()

    for trigger_phrase in prepared.trigger_phrases:
        if _phrase_match(normalized_query, trigger_phrase):
            score += 6
            matched.add(f"trigger:{trigger_phrase}")

    if _phrase_match(normalized_query, prepared.name_phrase):
        score += 5
        matched.add(f"name:{prepared.name_phrase}")

    if _phrase_match(normalized_query, prepared.description_phrase):
        score += 3
        matched.add("description:phrase")

    if _phrase_match(normalized_query, prepared.use_when_phrase):
        score += 3
        matched.add("use_when:phrase")

    for field_name, normalized_value in (("category", prepared.category_phrase), ("phase", prepared.phase_phrase)):
        if _phrase_match(normalized_query, normalized_value):
            score += 2
            matched.add(f"{field_name}:{normalized_value}")

    for token in sorted(query_tokens & prepared.trigger_tokens):
        score += 3
        matched.add(f"trigger:{token}")

    for token in sorted(query_tokens & prepared.metadata_tokens):
        score += 1
        matched.add(f"metadata:{token}")

    if score > 0:
        matched.update(f"locale:{match}" for match in locale_matches)

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


def _ensure_guardrail_candidates(
    recommendations: list[Recommendation],
    definitions: list[SkillDefinition],
    guards: tuple[RoutingGuardRule, ...],
    query: str,
) -> list[Recommendation]:
    injectable_guards = tuple(
        guard for guard in guards if guard.id in _GUARDRAIL_CANDIDATE_INJECTION_IDS
    )
    if not injectable_guards:
        return recommendations
    by_skill = {recommendation.skill: recommendation for recommendation in recommendations}
    by_definition = {definition.name: definition for definition in definitions}
    expanded = list(recommendations)
    for guard in injectable_guards:
        for skill_name in guard.preferred_skills:
            if skill_name in by_skill:
                continue
            definition = by_definition.get(skill_name)
            if definition is None:
                continue
            recommendation = Recommendation(
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
            by_skill[skill_name] = recommendation
            expanded.append(recommendation)
    return expanded


def _apply_guardrail_reranking(
    recommendations: list[Recommendation],
    *,
    guards: tuple[RoutingGuardRule, ...],
) -> list[Recommendation]:
    if not guards:
        return recommendations
    reranked = []
    for recommendation in recommendations:
        reranked.append(_apply_guard_rules_to_recommendation(recommendation, guards))
    return reranked


def _apply_guard_rules_to_recommendation(
    recommendation: Recommendation,
    guards: tuple[RoutingGuardRule, ...],
) -> Recommendation:
    updated = recommendation
    for guard in guards:
        if updated.skill in guard.preferred_skills:
            score = updated.score + guard.score_boost
            updated = replace(
                updated,
                score=score,
                confidence=_confidence(score),
                matched=tuple(sorted({*updated.matched, guard.matched_label})),
                why=guard.why,
            )
    return updated


def _tokens(value: str) -> set[str]:
    return routing_tokens(value, stopwords=_STOPWORDS)


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
