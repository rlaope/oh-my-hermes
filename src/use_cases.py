from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


USE_CASE_CATALOG_SCHEMA_VERSION = "omh_use_case_catalog/v1"
USE_CASE_RECOMMENDATION_SCHEMA_VERSION = "omh_use_case_recommendation/v1"


@dataclass(frozen=True)
class UseCase:
    goal: str
    id: str
    title: str
    situation: str
    example_request: str
    primary_skill: str
    playbook: str
    harness: str
    next_action: str
    user_value: str
    evidence_boundary: str
    proof_surfaces: tuple[str, ...]
    keywords: tuple[str, ...]


USE_CASES: tuple[UseCase, ...] = (
    UseCase(
        goal="G1",
        id="startup-product-triage",
        title="Startup product triage",
        situation="A small SaaS team receives customer feedback, bugs, and feature asks in Hermes chat.",
        example_request="Payment failures keep showing up from customers.",
        primary_skill="feedback-triage",
        playbook="feedback-triage",
        harness="customer-insight-triage",
        next_action="triage_feedback",
        user_value="Hermes separates investigate, reproduce, handoff, and verification instead of pretending the bug is already fixed.",
        evidence_boundary="A triage record is not reproduction, code execution, customer confirmation, or incident closure.",
        proof_surfaces=("omh recommend", "omh chat interact", "omh runtime status"),
        keywords=("payment", "결제", "failure", "feedback", "customer", "triage", "bug", "repro"),
    ),
    UseCase(
        goal="G2",
        id="issue-to-pr-readiness",
        title="Issue to PR readiness",
        situation="An open-source maintainer wants Hermes to turn a loose issue into a reviewable PR unit.",
        example_request="Turn this issue into a PR-ready implementation plan.",
        primary_skill="ultraprocess",
        playbook="request-to-handoff",
        harness="goal-execution",
        next_action="start_ultraprocess",
        user_value="Hermes produces acceptance criteria, verification commands, and executor-ready handoff instead of a vague coding prompt.",
        evidence_boundary="A prepared handoff is not executor dispatch, code result, review, CI, or merge evidence.",
        proof_surfaces=("omh playbook recommend", "omh chat interact", "omh coding delegate"),
        keywords=("issue", "PR", "pull request", "implementation", "acceptance", "handoff", "이슈"),
    ),
    UseCase(
        goal="G3",
        id="agent-product-qa",
        title="Real-world agent product QA",
        situation="A team validates whether an AI agent product handles realistic user scenarios safely.",
        example_request="Check whether our agent handles a Kubernetes outage diagnosis scenario well.",
        primary_skill="ultraqa",
        playbook="reliability-incident-review",
        harness="qa-specialist",
        next_action="prepare_adversarial_qa",
        user_value="Hermes shapes scenarios, expected behavior, checks, and observed gaps without mixing expectations with evidence.",
        evidence_boundary="A QA scenario is not a passed test, production diagnosis, or verified remediation until observed results are recorded.",
        proof_surfaces=("omh recommend", "omh ops reliability", "omh runtime record"),
        keywords=("QA", "scenario", "test", "outage", "kubernetes", "diagnosis", "검증", "장애"),
    ),
    UseCase(
        goal="G4",
        id="chat-to-workflow-routing",
        title="Chat to workflow routing",
        situation="A development organization works in Hermes chat and expects natural messages to become the right workflow.",
        example_request="This feels like a risky refactor before release.",
        primary_skill="oh-my-hermes",
        playbook="safe-feature-change",
        harness="planning",
        next_action="route_or_clarify",
        user_value="Hermes routes to clarify, plan, research, handoff, review, or status without making users memorize commands.",
        evidence_boundary="A routing decision is advisory wrapper guidance, not an accepted plan or execution result.",
        proof_surfaces=("omh chat route", "omh recommend", "omh playbook recommend"),
        keywords=("route", "workflow", "risky", "refactor", "release", "chat", "라우팅", "위험"),
    ),
    UseCase(
        goal="G5",
        id="ai-coding-safety",
        title="AI coding safety boundary",
        situation="A company adopts Codex, Claude Code, or another coding executor but needs clear evidence boundaries.",
        example_request="Prepare this for a coding agent, but show what is only prepared versus observed.",
        primary_skill="code-review",
        playbook="request-to-handoff",
        harness="coding-handling",
        next_action="prepare_executor_handoff",
        user_value="Hermes keeps prepared handoff, dispatch, result, verification, review, CI, and merge status separate.",
        evidence_boundary="Prepared coding context is not dispatch, execution, verification, review, CI, merge readiness, or merge.",
        proof_surfaces=("omh coding delegate", "omh runtime delegation-status", "omh coding lifecycle report"),
        keywords=("coding agent", "codex", "claude", "executor", "observed", "evidence", "코딩", "검증"),
    ),
    UseCase(
        goal="G6",
        id="feature-shaping",
        title="Product feature shaping",
        situation="A product person describes a fuzzy improvement that should not go straight to implementation.",
        example_request="I want onboarding to feel smoother.",
        primary_skill="deep-interview",
        playbook="deep-interview-to-plan",
        harness="deep-interview",
        next_action="ask_one_clarifying_question",
        user_value="Hermes turns fuzzy intent into goals, non-goals, user value, acceptance criteria, and then handoff only when ready.",
        evidence_boundary="A shaped feature brief is not user validation, implementation, or release evidence.",
        proof_surfaces=("omh chat interact", "omh hermes plan", "omh recommend"),
        keywords=("feature", "onboarding", "smooth", "product", "shape", "clarify", "기획", "온보딩"),
    ),
    UseCase(
        goal="G7",
        id="release-gate",
        title="Release gate and README claim check",
        situation="A maintainer wants Hermes to verify release readiness and public claims before shipping.",
        example_request="Before release, check that README claims match commands and tests.",
        primary_skill="deploy-and-monitor",
        playbook="deploy-and-monitor",
        harness="app-delivery-loop",
        next_action="prepare_release_gate",
        user_value="Hermes separates checklist, observed tests, docs claims, review status, and release readiness.",
        evidence_boundary="A release checklist is not a published release, deployment, monitoring result, or user adoption signal.",
        proof_surfaces=("omh release checklist", "omh doctor", "omh runtime status"),
        keywords=("release", "README", "claim", "doctor", "checklist", "deploy", "릴리즈", "배포"),
    ),
    UseCase(
        goal="G8",
        id="refactor-standardization",
        title="Repeatable refactor workflow",
        situation="A team repeatedly refactors legacy code and wants a standard safety loop.",
        example_request="This risky refactor needs plan, implementation, review, and docs sync.",
        primary_skill="ultraprocess",
        playbook="safe-feature-change",
        harness="goal-execution",
        next_action="start_single_cycle_plan_to_pr",
        user_value="Hermes applies research, plan, implementation handoff, code review, docs sync, and PR discipline as one cycle.",
        evidence_boundary="A refactor plan is not behavior preservation, test pass, code review approval, or merge evidence.",
        proof_surfaces=("omh recommend", "omh chat interact", "omh runtime status"),
        keywords=("refactor", "legacy", "plan", "review", "docs", "sync", "리팩터링", "레거시"),
    ),
    UseCase(
        goal="G9",
        id="multi-agent-work-hub",
        title="Multi-agent work hub",
        situation="A power user coordinates Hermes, Codex-like executors, plugin runtimes, reviews, and PR status.",
        example_request="What is the current coding-agent status and what did we decide in the interview?",
        primary_skill="team",
        playbook="local-pipeline-buildout",
        harness="goal-execution",
        next_action="summarize_work_hub_status",
        user_value="Hermes reports current plan context, attached executor session, evidence ladder, and next action without forcing CLI spelunking.",
        evidence_boundary="A hub status card is not new execution, dispatch, review, CI, or merge evidence.",
        proof_surfaces=("omh capabilities inspect", "omh runtime delegation-status", "omh chat session status"),
        keywords=("multi-agent", "status", "session", "team", "executor", "interview", "에이전트", "상태"),
    ),
    UseCase(
        goal="G10",
        id="scheduled-ops-blueprint",
        title="Scheduled ops blueprint",
        situation="An operator wants Hermes to prepare recurring research, monitoring, digest, or reporting work.",
        example_request="Every morning, check competitor news and send a Slack digest only if something changed.",
        primary_skill="automation-blueprint",
        playbook="scheduled-ops-blueprint",
        harness="scheduled-ops-blueprint",
        next_action="prepare_scheduled_ops_blueprint",
        user_value="Hermes prepares schedule, delivery, silence policy, skill chain, and missing evidence before any host automation claim.",
        evidence_boundary="A scheduled ops blueprint is not cron creation, source retrieval, gateway delivery, plugin load, or no-agent execution.",
        proof_surfaces=("omh ops blueprint", "omh ops blueprint-list", "omh ops validate"),
        keywords=("every morning", "daily", "weekly", "digest", "slack", "competitor", "scheduled", "매일", "정기"),
    ),
)


def list_use_cases() -> dict[str, Any]:
    return {
        "schema_version": USE_CASE_CATALOG_SCHEMA_VERSION,
        "count": len(USE_CASES),
        "use_cases": [_public_case(case) for case in USE_CASES],
    }


def inspect_use_case(case_id: str) -> dict[str, Any]:
    case = _find_case(case_id)
    if case is None:
        raise KeyError(case_id)
    return {
        "schema_version": USE_CASE_CATALOG_SCHEMA_VERSION,
        "use_case": _public_case(case),
    }


def recommend_use_cases(query: str, *, limit: int = 3) -> dict[str, Any]:
    clean_query = " ".join(query.split())
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not clean_query:
        raise ValueError("task description must not be empty")
    tokens = _tokens(clean_query)
    scored: list[tuple[int, int, UseCase]] = []
    for case in USE_CASES:
        score = _score_case(case, tokens, clean_query)
        if score:
            scored.append((score, int(case.goal[1:]), case))
    if not scored:
        scored = [(1, index, case) for index, case in enumerate((USE_CASES[3], USE_CASES[5], USE_CASES[1]))]
    scored.sort(key=lambda item: (-item[0], item[1]))
    recommendations = []
    for score, _, case in scored[:limit]:
        payload = _public_case(case)
        payload["score"] = score
        payload["confidence"] = _confidence(score)
        recommendations.append(payload)
    return {
        "schema_version": USE_CASE_RECOMMENDATION_SCHEMA_VERSION,
        "query": clean_query,
        "recommendations": recommendations,
        "boundary": "Use-case recommendations are routing and product-fit guidance, not accepted plans, runtime execution, or observed evidence.",
    }


def _public_case(case: UseCase) -> dict[str, Any]:
    payload = asdict(case)
    payload["proof_surfaces"] = list(case.proof_surfaces)
    payload["keywords"] = list(case.keywords)
    return payload


def _find_case(case_id: str) -> UseCase | None:
    normalized = case_id.strip().casefold()
    for case in USE_CASES:
        if normalized in {case.goal.casefold(), case.id.casefold(), f"{case.goal}-{case.id}".casefold()}:
            return case
    return None


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9가-힣_+-]+", value)}


def _score_case(case: UseCase, tokens: set[str], query: str) -> int:
    lowered = query.casefold()
    score = 0
    for keyword in case.keywords:
        key = keyword.casefold()
        if " " in key:
            if key in lowered:
                score += 3
        elif key in tokens:
            score += 2
        elif key and key in lowered:
            score += 1
    if case.primary_skill.casefold() in lowered or case.playbook.casefold() in lowered:
        score += 4
    return score


def _confidence(score: int) -> str:
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"
