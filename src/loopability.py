from __future__ import annotations

import re
from typing import Any, Iterable

from .hashutil import sha256_text


LOOPABILITY_ASSESSMENT_SCHEMA = "loopability_assessment/v1"
LOOP_GOAL_KINDS = ("task", "project", "ambition", "external_wait_only", "unclear")
LOOPABILITY_STATES = (
    "direct_task",
    "loopable",
    "needs_reframe",
    "north_star_only",
    "external_wait_only",
    "needs_clarification",
)


def assess_loopability(goal_summary: str, *, expose_goal: bool = True) -> dict[str, Any]:
    summary = _safe_summary(goal_summary)
    if not summary:
        raise ValueError("loopability assessment requires a goal summary")
    signals = _goal_signals(summary)
    text = signals["text"]
    visible_goal = summary if expose_goal else "{message}"

    if signals["simple_delivery"]:
        return _assessment(
            goal_kind="task",
            loopability="direct_task",
            recommended_surface="direct_task_or_ultraprocess",
            recommended_next_action="route_direct_task",
            reason="The request is bounded enough that a single delivery workflow is cheaper than a persistent loop.",
            north_star="",
            bounded_arena="single bounded change",
            observable_problem="already narrow enough for direct execution",
            current_loop_goal="",
            next_verification="Run the smallest targeted check that proves the direct task is done.",
            stop_condition="The requested bounded change is implemented and verified.",
            required_inputs=[],
            goal_summary=goal_summary,
        )

    if signals["external_only"]:
        return _assessment(
            goal_kind="external_wait_only",
            loopability="external_wait_only",
            recommended_surface="research_or_waiting_state",
            recommended_next_action="record_external_wait",
            reason=(
                "The request mainly asks for an external outcome; OMH can plan internal work, "
                "but cannot observe market response until evidence arrives."
            ),
            north_star=visible_goal,
            bounded_arena="",
            observable_problem="external response is not locally observable yet",
            current_loop_goal="",
            next_verification="Name a local proxy signal or wait for external evidence.",
            stop_condition="External evidence is observed or the user selects a local proxy loop goal.",
            required_inputs=["bounded_arena", "observable_problem", "next_verification"],
            goal_summary=goal_summary,
        )

    if signals["has_ambition"] and signals["has_bounded_arena"] and signals["has_loop_signal"]:
        return _assessment(
            goal_kind="project",
            loopability="loopable",
            recommended_surface="loop_start",
            recommended_next_action="choose_permission_profile",
            reason=(
                "The request keeps a north star but includes a bounded arena or observable problem "
                "that can drive repeated discovery and verification."
            ),
            north_star=visible_goal,
            bounded_arena=_bounded_arena_for(text),
            observable_problem=_observable_problem_for(text),
            current_loop_goal=_default_loop_goal_for(summary, text, expose_goal=expose_goal),
            next_verification=_next_verification_for(text),
            stop_condition="The current loop goal passes its named verification signal or records a blocker/wait state.",
            required_inputs=[],
            goal_summary=goal_summary,
        )

    if signals["has_ambition"]:
        return _assessment(
            goal_kind="ambition",
            loopability="needs_reframe",
            recommended_surface="loop_start_after_reframe",
            recommended_next_action="reframe_north_star",
            reason=(
                "The request is a north star, not yet an execution goal; convert it into a bounded "
                "arena with observable friction and a next verification."
            ),
            north_star=visible_goal,
            bounded_arena=_bounded_arena_for(text),
            observable_problem=_observable_problem_for(text),
            current_loop_goal=_default_loop_goal_for(summary, text, expose_goal=False),
            next_verification=_next_verification_for(text),
            stop_condition="The first loop goal closes one observable gap or records why the loop must return to research.",
            required_inputs=["bounded_arena", "observable_problem", "next_verification"],
            goal_summary=goal_summary,
        )

    if signals["has_bounded_arena"] and signals["has_loop_signal"]:
        return _assessment(
            goal_kind="project",
            loopability="loopable",
            recommended_surface="loop_start",
            recommended_next_action="choose_permission_profile",
            reason="The request is concrete enough to verify and open-ended enough to benefit from iterative discovery.",
            north_star="",
            bounded_arena=_bounded_arena_for(text),
            observable_problem=_observable_problem_for(text),
            current_loop_goal=visible_goal,
            next_verification=_next_verification_for(text),
            stop_condition="The current project loop step passes its named verification signal or records a blocker.",
            required_inputs=[],
            goal_summary=goal_summary,
        )

    if signals["unclear"]:
        return _assessment(
            goal_kind="unclear",
            loopability="needs_clarification",
            recommended_surface="deep_interview",
            recommended_next_action="ask_goal_boundary",
            reason="The request is too vague to decide whether it is a task, project loop, or north-star ambition.",
            north_star=visible_goal,
            bounded_arena="",
            observable_problem="",
            current_loop_goal="",
            next_verification="",
            stop_condition="",
            required_inputs=["bounded_arena", "observable_problem", "next_verification", "stop_condition"],
            goal_summary=goal_summary,
        )

    return _assessment(
        goal_kind="project",
        loopability="needs_reframe",
        recommended_surface="loop_start_after_reframe",
        recommended_next_action="ask_goal_boundary",
        reason=(
            "The request may be loopable, but it needs a bounded arena, observable problem, "
            "and verification signal before the loop starts."
        ),
        north_star=visible_goal,
        bounded_arena="",
        observable_problem="",
        current_loop_goal="",
        next_verification="",
        stop_condition="",
        required_inputs=["bounded_arena", "observable_problem", "next_verification"],
        goal_summary=goal_summary,
    )


def validate_loopability_assessment(value: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["loopability_assessment must be an object"]
    if value.get("schema_version") != LOOPABILITY_ASSESSMENT_SCHEMA:
        errors.append(f"loopability_assessment.schema_version must be {LOOPABILITY_ASSESSMENT_SCHEMA}")
    if value.get("goal_kind") not in LOOP_GOAL_KINDS:
        errors.append("loopability_assessment.goal_kind is unsupported")
    if value.get("loopability") not in LOOPABILITY_STATES:
        errors.append("loopability_assessment.loopability is unsupported")
    for key in ("recommended_surface", "recommended_next_action", "reason", "goal_summary_hash", "claim_boundary"):
        if not isinstance(value.get(key), str) or not str(value.get(key, "")).strip():
            errors.append(f"loopability_assessment.{key} must be a non-empty string")
    required_inputs = value.get("required_inputs")
    if not isinstance(required_inputs, list) or not all(isinstance(item, str) for item in required_inputs):
        errors.append("loopability_assessment.required_inputs must be a string list")
    return errors


def _assessment(
    *,
    goal_kind: str,
    loopability: str,
    recommended_surface: str,
    recommended_next_action: str,
    reason: str,
    north_star: str,
    bounded_arena: str,
    observable_problem: str,
    current_loop_goal: str,
    next_verification: str,
    stop_condition: str,
    required_inputs: list[str],
    goal_summary: str,
) -> dict[str, Any]:
    return {
        "schema_version": LOOPABILITY_ASSESSMENT_SCHEMA,
        "goal_kind": goal_kind,
        "loopability": loopability,
        "recommended_surface": recommended_surface,
        "recommended_next_action": recommended_next_action,
        "north_star": north_star,
        "bounded_arena": bounded_arena,
        "observable_problem": observable_problem,
        "current_loop_goal": current_loop_goal,
        "next_loop_goal": current_loop_goal,
        "next_verification": next_verification,
        "stop_condition": stop_condition,
        "required_inputs": required_inputs,
        "reason": reason,
        "classification_confidence": _loopability_confidence(loopability, required_inputs),
        "goal_summary_hash": sha256_text(goal_summary),
        "claim_boundary": (
            "Loopability is deterministic routing metadata. It is not execution, verification, "
            "market response, or goal completion evidence."
        ),
    }


def _goal_signals(summary: str) -> dict[str, Any]:
    text = summary.lower()
    has_bounded_arena = _contains_any(text, _BOUNDED_ARENA_TERMS)
    has_discovery_shape = _contains_any(text, _DISCOVERY_TERMS)
    has_verification = _contains_any(text, _VERIFICATION_TERMS)
    has_observable_problem = _contains_any(text, _OBSERVABLE_PROBLEM_TERMS)
    return {
        "text": text,
        "has_ambition": _has_ambition_signal(text),
        "has_bounded_arena": has_bounded_arena,
        "has_loop_signal": has_observable_problem or has_discovery_shape or has_verification,
        "simple_delivery": _looks_like_direct_task(text),
        "external_only": _looks_like_external_wait_only(text, has_bounded_arena, has_discovery_shape, has_verification),
        "unclear": _looks_unclear_loop_goal(text),
    }


_AMBITION_TERMS = (
    "100k",
    "10k",
    "10k-star",
    "100k-star",
    "star-worthy",
    "star worthy",
    "github star",
    "github stars",
    "github 스타",
    "스타급",
    "revenue",
    "매출",
    "100억",
    "unicorn",
    "world-class",
    "market leader",
    "세계",
    "시장",
)

_BOUNDED_ARENA_TERMS = (
    "repo",
    "repository",
    "current",
    "first-run",
    "first run",
    "install",
    "installation",
    "readme",
    "docs",
    "documentation",
    "onboarding",
    "friction",
    "mvp",
    "prototype",
    "section",
    "audience",
    "user segment",
    "workflow",
    "현재",
    "레포",
    "저장소",
    "설치",
    "첫 성공",
    "마찰",
    "문서",
    "온보딩",
    "자산",
    "섹션",
    "사용자군",
    "워크플로우",
    "프로토타입",
)

_OBSERVABLE_PROBLEM_TERMS = (
    "fail",
    "failing",
    "friction",
    "slow",
    "confusing",
    "weak",
    "issue",
    "bug",
    "gap",
    "risk",
    "test",
    "verify",
    "smoke",
    "feedback",
    "실패",
    "마찰",
    "느려",
    "헷갈",
    "약한",
    "이슈",
    "버그",
    "갭",
    "위험",
    "검증",
    "테스트",
    "피드백",
)

_DISCOVERY_TERMS = (
    "discover",
    "find",
    "investigate",
    "observe",
    "reduce",
    "iterate",
    "improve",
    "one by one",
    "하나씩",
    "찾",
    "조사",
    "관찰",
    "줄",
    "반복",
    "개선",
)

_VERIFICATION_TERMS = (
    "verify",
    "verified",
    "test",
    "smoke",
    "within 10 minutes",
    "acceptance",
    "criteria",
    "evidence",
    "검증",
    "테스트",
    "10분",
    "성공 기준",
    "증거",
    "근거",
)


def _safe_summary(value: str, *, limit: int = 240) -> str:
    summary = re.sub(r"\s+", " ", str(value)).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "..."


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _has_ambition_signal(text: str) -> bool:
    return _contains_any(text, _AMBITION_TERMS) or re.search(r"\bstars?\b", text) is not None


def _looks_like_direct_task(text: str) -> bool:
    if _contains_any(
        text,
        (
            "button color",
            "change button",
            "start the dev server",
            "restart the dev server",
            "run dev server",
            "dev server",
            "fix typo",
            "spelling",
            "one-line",
            "one line",
            "single file",
            "rename",
            "버튼 색",
            "오타",
            "한 줄",
            "이름 바",
        ),
    ):
        return True
    wants_site = _contains_any(text, ("website", "site", "personal site", "개인 사이트", "웹사이트"))
    build_word = _contains_any(text, ("build", "make", "create", "만들", "제작"))
    discovery_word = _contains_any(
        text,
        (
            "identity",
            "positioning",
            "assets",
            "audience",
            "feedback",
            "section",
            "structure",
            "정체성",
            "포지셔닝",
            "자산",
            "방문자",
            "피드백",
            "섹션",
            "구조",
        ),
    )
    return wants_site and build_word and not discovery_word


def _looks_like_external_wait_only(
    text: str,
    has_bounded_arena: bool,
    has_discovery_shape: bool,
    has_verification: bool,
) -> bool:
    asks_external_response = _contains_any(
        text,
        (
            "get user response",
            "market response",
            "community response",
            "adoption",
            "viral",
            "유저 반응",
            "사용자 반응",
            "시장 반응",
            "커뮤니티 반응",
            "바이럴",
        ),
    )
    asks_revenue_only = _contains_any(text, ("revenue", "매출", "100억")) and not has_bounded_arena
    has_local_proxy = has_bounded_arena or has_discovery_shape or has_verification
    return bool((asks_external_response or asks_revenue_only) and not has_local_proxy)


def _looks_unclear_loop_goal(text: str) -> bool:
    normalized = text.strip()
    if len(normalized) < 12:
        return True
    return _contains_any(normalized, ("make it better", "improve this", "좋게", "잘 만들어", "괜찮게"))


def _default_loop_goal_for(summary: str, text: str, *, expose_goal: bool) -> str:
    if _contains_any(text, ("star", "stars", "스타", "oss", "open source", "repo", "repository", "레포", "저장소")):
        return (
            "Inspect the current repository first-run experience, identify one friction point between install and first successful value, "
            "improve it, and verify it with a clean smoke path."
        )
    if _contains_any(text, ("revenue", "매출", "100억", "saas", "mvp", "prototype", "프로토타입")):
        return (
            "Select one user segment and one observable operational workflow, produce an MVP hypothesis or demo slice, "
            "and verify it against documented response criteria."
        )
    if _contains_any(text, ("website", "site", "personal site", "개인 사이트", "웹사이트")):
        return (
            "Inspect the available identity, asset, and audience signals, improve one site section, "
            "and verify that it communicates the intended positioning."
        )
    return _safe_summary(summary) if expose_goal else "Convert the north star into one bounded loop goal with an observable problem and verification signal."


def _bounded_arena_for(text: str) -> str:
    if _contains_any(text, ("repo", "repository", "readme", "install", "first-run", "first run", "레포", "저장소", "설치")):
        return "current repository first-run experience"
    if _contains_any(text, ("website", "site", "personal site", "개인 사이트", "웹사이트", "section", "섹션")):
        return "site positioning and one visible section"
    if _contains_any(text, ("saas", "mvp", "prototype", "사용자군", "워크플로우", "프로토타입")):
        return "one user segment and one operational workflow"
    return "one bounded local arena"


def _observable_problem_for(text: str) -> str:
    if _contains_any(text, ("first-run", "first run", "install", "설치", "첫 성공", "friction", "마찰")):
        return "a user may not reach first value quickly or clearly"
    if _contains_any(text, ("onboarding", "온보딩")):
        return "the onboarding path may not communicate the next action clearly"
    if _contains_any(text, ("website", "site", "개인 사이트", "웹사이트", "positioning", "정체성")):
        return "the page may not communicate identity, audience, or proof clearly"
    if _contains_any(text, ("bug", "issue", "fail", "버그", "이슈", "실패")):
        return "the problem needs reproduction or evidence before execution"
    return "one observable friction point or missing proof"


def _next_verification_for(text: str) -> str:
    if _contains_any(text, ("10 minute", "10분", "first-run", "first run", "install", "설치")):
        return "A clean user or environment reaches first value within the named time box."
    if _contains_any(text, ("test", "smoke", "검증", "테스트")):
        return "The named focused test, smoke check, or schema validation passes with an evidence ref."
    if _contains_any(text, ("website", "site", "개인 사이트", "웹사이트")):
        return "The target section has visible content, proof, and a clear next action under review."
    return "The current loop step records a pass/fail evidence signal before the next tick."


def _loopability_confidence(loopability: str, required_inputs: list[str]) -> str:
    if loopability in {"direct_task", "loopable", "external_wait_only"} and not required_inputs:
        return "high"
    if loopability in {"needs_reframe", "north_star_only"}:
        return "medium"
    return "low"
