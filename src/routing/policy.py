from __future__ import annotations

from dataclasses import dataclass


ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
CONFIDENCE_LEVELS = ("low", "medium", "high")
EXPLICIT_INVOCATION_PREFIXES = ("$", "/", "./", "@")

_CONFIDENCE_RANK = {name: index for index, name in enumerate(CONFIDENCE_LEVELS, start=1)}


@dataclass(frozen=True)
class RoutingGuardRule:
    id: str
    rule: str
    matched_label: str
    preferred_skills: tuple[str, ...]
    score_boost: int
    why: str
    activation_status: str


RISKY_REFACTOR_GUARD = RoutingGuardRule(
    id="risky_refactor_before_cleanup",
    rule="Risky refactor language should route to planning/review before cleanup unless explicit invocation overrides.",
    matched_label="guard:risky_refactor_before_cleanup",
    preferred_skills=("plan", "ralplan"),
    score_boost=20,
    why="Matched guard/trigger metadata; risky code-change requests should get a reviewed plan before cleanup.",
    activation_status="active",
)
FEEDBACK_BEFORE_CODING_GUARD = RoutingGuardRule(
    id="feedback_before_coding",
    rule="Product feedback and bug reports should route through triage/investigation before coding handoff unless code work is explicit.",
    matched_label="guard:feedback_before_coding",
    preferred_skills=("feedback-triage",),
    score_boost=0,
    why="Product feedback and bug reports should get triage/investigation before coding handoff.",
    activation_status="cataloged",
)
WEB_RESEARCH_BEFORE_PROCESS_GUARD = RoutingGuardRule(
    id="web_research_before_process",
    rule="Plain web/source/current-evidence requests should route to web research before one-cycle delivery.",
    matched_label="guard:web_research_before_process",
    preferred_skills=("web-research",),
    score_boost=14,
    why="Matched guard/trigger metadata; web, source, or freshness requests should start with source-backed Hermes research.",
    activation_status="active",
)
DELIVERY_CYCLE_GUARD = RoutingGuardRule(
    id="delivery_cycle_before_research_only",
    rule="Requests that ask for PR or delivery-cycle completion should route to Ultraprocess before research-only lanes.",
    matched_label="guard:delivery_cycle_before_research_only",
    preferred_skills=("ultraprocess",),
    score_boost=12,
    why="Matched guard/trigger metadata; PR or delivery-cycle requests need the one-cycle process lane rather than research-only routing.",
    activation_status="active",
)
ROUTING_GUARD_RULES = (
    RISKY_REFACTOR_GUARD,
    FEEDBACK_BEFORE_CODING_GUARD,
    WEB_RESEARCH_BEFORE_PROCESS_GUARD,
    DELIVERY_CYCLE_GUARD,
)


def is_ambiguous_scores(first_score: int, second_score: int | None) -> bool:
    return second_score is not None and first_score > 0 and first_score == second_score


def meets_confidence_threshold(confidence: str, threshold: str) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[threshold]


def explicit_skill_invocation(message: str, names: set[str]) -> str | None:
    first = message.strip().split(maxsplit=1)[0].strip(":,").lower()
    for prefix in sorted(EXPLICIT_INVOCATION_PREFIXES, key=len, reverse=True):
        if first.startswith(prefix):
            first = first[len(prefix) :].strip(":,")
            break
    return first if first in names else None


def active_routing_guard_rules(
    normalized_query: str,
    query_tokens: set[str],
    *,
    explicit_skill: str | None = None,
) -> tuple[RoutingGuardRule, ...]:
    if explicit_skill:
        return ()
    rules: list[RoutingGuardRule] = []
    if _risky_refactor_guard_applies(normalized_query, query_tokens):
        rules.append(RISKY_REFACTOR_GUARD)
    if _web_research_guard_applies(normalized_query, query_tokens):
        rules.append(WEB_RESEARCH_BEFORE_PROCESS_GUARD)
    if _delivery_cycle_guard_applies(normalized_query, query_tokens):
        rules.append(DELIVERY_CYCLE_GUARD)
    return tuple(rules)


def _risky_refactor_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if not ({"refactor", "refactoring"} & query_tokens):
        return False
    if {"risky", "dangerous", "unsafe"} & query_tokens:
        return True
    return any(
        phrase in normalized_query
        for phrase in (
            "feels risky",
            "seems risky",
            "위험한 리팩터링",
            "위험한 리팩토링",
            "리팩터링 위험",
            "리팩토링 위험",
        )
    )


def _web_research_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _delivery_cycle_terms(normalized_query, query_tokens):
        return False
    if {
        "web",
        "search",
        "sources",
        "source",
        "citation",
        "citations",
        "links",
        "latest",
        "current",
        "freshness",
        "official",
        "upstream",
    } & query_tokens:
        return True
    return any(
        phrase in normalized_query
        for phrase in (
            "web search",
            "search the web",
            "internet search",
            "find sources",
            "current sources",
            "source backed",
            "웹서치",
            "웹 서치",
            "웹 검색",
            "인터넷 검색",
            "검색해서",
            "검색해줘",
            "찾아봐",
            "최신 자료",
            "최신 출처",
            "자료 찾아",
        )
    )


def _delivery_cycle_terms(normalized_query: str, query_tokens: set[str]) -> bool:
    if {
        "implement",
        "implementation",
        "code",
        "coding",
        "review",
        "docs",
        "documentation",
        "pull",
        "merge",
        "구현",
        "리뷰",
        "문서",
    } & query_tokens:
        return True
    return any(
        phrase in normalized_query
        for phrase in (
            "open a pr",
            "prepare a pr",
            "make a pr",
            "pr ready",
            "pr-ready",
            "pull request",
            "pr까지",
        )
    )


def _delivery_cycle_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    return _delivery_cycle_terms(normalized_query, query_tokens) and any(
        phrase in normalized_query
        for phrase in (
            "prepare a pr",
            "open a pr",
            "make a pr",
            "pr-ready",
            "pr ready",
            "pull request",
            "plan implement review docs",
            "research plan implement",
            "계획 구현 리뷰 문서",
            "기획 구현 리뷰 문서",
            "pr까지",
        )
    )
