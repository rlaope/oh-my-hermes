from __future__ import annotations

from dataclasses import dataclass

from .localization import normalized_phrase


ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
CONFIDENCE_LEVELS = ("low", "medium", "high")
EXPLICIT_INVOCATION_PREFIXES = ("$", "/", "./", "@")
_EXPLICIT_SKILL_ALIASES = {
    "ohmy": "oh-my-hermes",
}
_PREFIXED_SKILL_ALIASES = {
    "omh": "oh-my-hermes",
    "ohmy": "oh-my-hermes",
    "skills": "oh-my-hermes",
}

_CONFIDENCE_RANK = {name: index for index, name in enumerate(CONFIDENCE_LEVELS, start=1)}
_SCHEDULED_OPS_STRONG_TOKENS = frozenset(
    {
        "cron",
        "recurring",
        "repeat",
        "정기",
        "반복",
    }
)
_SCHEDULED_OPS_CADENCE_TOKENS = frozenset(
    {
        "daily",
        "weekly",
        "monthly",
        "매일",
        "매주",
        "매월",
    }
)
_SCHEDULED_OPS_CONTEXT_TOKENS = frozenset(
    {
        "check",
        "checks",
        "monitor",
        "monitoring",
        "watch",
        "watchdog",
        "digest",
        "report",
        "reports",
        "notify",
        "notification",
        "deliver",
        "delivery",
        "slack",
        "discord",
        "telegram",
        "email",
        "competitor",
        "news",
        "source",
        "sources",
        "changed",
        "changes",
        "silent",
        "silently",
        "헬스체크",
        "감시",
        "확인",
        "보고",
        "리포트",
        "요약",
        "알림",
        "슬랙",
        "디스코드",
        "텔레그램",
        "이메일",
        "경쟁사",
        "뉴스",
        "변화",
        "조용히",
    }
)
_RESEARCH_DEPARTMENT_STRONG_TOKENS = frozenset(
    {
        "research",
        "competitor",
        "competitors",
        "market",
        "industry",
        "paper",
        "papers",
        "notebooklm",
        "obsidian",
        "vault",
        "리서치",
        "조사",
        "경쟁사",
        "시장",
        "산업",
        "논문",
        "옵시디언",
    }
)
_RESEARCH_DEPARTMENT_SUPPORT_TOKENS = frozenset(
    {
        "news",
        "source",
        "sources",
        "brief",
        "briefing",
        "digest",
        "뉴스",
        "출처",
        "자료",
        "브리핑",
        "요약",
    }
)
_RESEARCH_DEPARTMENT_PHRASES = (
    "research department",
    "research ops",
    "research operations",
    "scout analyst briefer",
    "daily research",
    "weekly research",
    "competitor research",
    "market research",
    "source inbox",
    "briefing status",
    "notebooklm",
    "obsidian vault",
    "리서치 부서",
    "리서치 운영",
    "경쟁사 리서치",
    "시장 리서치",
    "수집 합성 브리핑",
)
_VISUAL_SUMMARY_MODALITY_TOKENS = frozenset(
    {
        "visual",
        "image",
        "vertical",
        "이미지",
        "세로",
    }
)
_VISUAL_SUMMARY_CARD_TOKENS = frozenset({"card", "카드"})
_VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS = frozenset(
    {
        "summary",
        "announcement",
        "briefing",
        "triage",
        "review",
        "release",
        "meeting",
        "notes",
        "pr",
        "pull",
        "request",
        "research",
        "news",
        "competitor",
        "요약",
        "브리핑",
        "발표",
        "트리아지",
        "회의",
        "회의록",
        "리서치",
        "뉴스",
        "경쟁사",
    }
)
_VISUAL_SUMMARY_PHRASES = (
    "img-summary",
    "img summary",
    "visual-summary",
    "visual summary",
    "visual prompt card",
    "image card",
    "summary image",
    "vertical card",
    "vertical summary image",
    "pr summary card",
    "pull request card",
    "issue triage card",
    "bug triage card",
    "news briefing card",
    "competitor news briefing card",
    "release announcement image",
    "release notes image",
    "회의록을 세로 요약 이미지",
    "회의록 세로 요약 이미지",
    "pr 요약 카드",
    "이슈 트리아지 카드",
    "경쟁사 뉴스 브리핑 카드",
    "릴리즈 노트 발표 이미지",
)
_SCHEDULED_OPS_PHRASES = (
    "every morning",
    "every day",
    "every week",
    "every month",
    "notify if",
    "only if changed",
    "only if something changed",
    "silent if nothing changed",
    "if nothing changed",
    "매일 아침",
    "매주",
    "매월",
    "변화 있으면",
    "변화 없으면",
    "바뀐 게 없으면",
    "조용히",
)
_ONE_OFF_TOKENS = frozenset(
    {
        "once",
        "일회성",
        "한번만",
    }
)
_ONE_OFF_PHRASES = (
    "one-off",
    "one off",
    "one-time",
    "one time",
    "single run",
    "single-use",
    "non-recurring",
    "non recurring",
    "do not repeat",
    "dont repeat",
    "no recurrence",
    "just once",
    "only once",
    "이번만",
    "한 번만",
    "한번만",
    "일회성",
)


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
VISUAL_SUMMARY_GUARD = RoutingGuardRule(
    id="img_summary_before_materials_or_delivery",
    rule="Image, card, or img-summary requests should route to img-summary before materials or PR delivery-cycle lanes.",
    matched_label="guard:img_summary",
    preferred_skills=("img-summary",),
    score_boost=30,
    why="Matched guard/trigger metadata; visual image-card requests should prepare a visual prompt card before delivery or material packaging.",
    activation_status="active",
)
SCHEDULED_OPS_BLUEPRINT_GUARD = RoutingGuardRule(
    id="scheduled_ops_blueprint_before_reliability_or_research",
    rule="Recurring schedule, delivery, or silence-policy requests should route to the scheduled ops blueprint lane before one-off review/research lanes.",
    matched_label="guard:scheduled_ops_blueprint",
    preferred_skills=("automation-blueprint",),
    score_boost=24,
    why="Matched guard/trigger metadata; recurring schedule or delivery requests should prepare a Hermes ops blueprint first.",
    activation_status="active",
)
RESEARCH_DEPARTMENT_GUARD = RoutingGuardRule(
    id="research_department_before_generic_scheduled_ops",
    rule="Recurring or durable research operations should route to the research department workflow pack before generic scheduled ops.",
    matched_label="guard:research_department",
    preferred_skills=("research-department",),
    score_boost=40,
    why="Matched guard/trigger metadata; recurring research operations should prepare a Scout/Analyst/Briefer research department plan.",
    activation_status="active",
)
ROUTING_GUARD_RULES = (
    RISKY_REFACTOR_GUARD,
    FEEDBACK_BEFORE_CODING_GUARD,
    RESEARCH_DEPARTMENT_GUARD,
    SCHEDULED_OPS_BLUEPRINT_GUARD,
    WEB_RESEARCH_BEFORE_PROCESS_GUARD,
    VISUAL_SUMMARY_GUARD,
    DELIVERY_CYCLE_GUARD,
)


def is_ambiguous_scores(first_score: int, second_score: int | None) -> bool:
    return second_score is not None and first_score > 0 and first_score == second_score


def meets_confidence_threshold(confidence: str, threshold: str) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[threshold]


def explicit_skill_invocation(message: str, names: set[str]) -> str | None:
    first = message.strip().split(maxsplit=1)[0].strip(":,").lower()
    used_prefix = False
    for prefix in sorted(EXPLICIT_INVOCATION_PREFIXES, key=len, reverse=True):
        if first.startswith(prefix):
            first = first[len(prefix) :].strip(":,")
            used_prefix = True
            break
    if first in names:
        return first
    alias = _EXPLICIT_SKILL_ALIASES.get(first)
    if alias in names:
        return alias
    if used_prefix:
        alias = _PREFIXED_SKILL_ALIASES.get(first)
        if alias in names:
            return alias
    return None


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
    delivery_cycle_applies = _delivery_cycle_guard_applies(normalized_query, query_tokens)
    research_department_applies = (
        not delivery_cycle_applies and _research_department_guard_applies(normalized_query, query_tokens)
    )
    if research_department_applies:
        rules.append(RESEARCH_DEPARTMENT_GUARD)
    if (
        not delivery_cycle_applies
        and _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens)
        and not research_department_applies
    ):
        rules.append(SCHEDULED_OPS_BLUEPRINT_GUARD)
    if _web_research_guard_applies(normalized_query, query_tokens):
        rules.append(WEB_RESEARCH_BEFORE_PROCESS_GUARD)
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        rules.append(VISUAL_SUMMARY_GUARD)
    if delivery_cycle_applies:
        rules.append(DELIVERY_CYCLE_GUARD)
    return tuple(rules)


def _risky_refactor_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if not ({"refactor", "refactoring"} & query_tokens):
        return False
    if {"risky", "dangerous", "unsafe"} & query_tokens:
        return True
    return _contains_phrase(
        normalized_query,
        (
            "feels risky",
            "seems risky",
            "위험한 리팩터링",
            "위험한 리팩토링",
            "리팩터링 위험",
            "리팩토링 위험",
        ),
    )


def _scheduled_ops_blueprint_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if is_explicit_one_off_request(normalized_query, query_tokens):
        return False
    if _SCHEDULED_OPS_STRONG_TOKENS & query_tokens:
        return True
    if _SCHEDULED_OPS_CADENCE_TOKENS & query_tokens and _SCHEDULED_OPS_CONTEXT_TOKENS & query_tokens:
        return True
    return _contains_phrase(normalized_query, _SCHEDULED_OPS_PHRASES)


def _research_department_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if is_explicit_one_off_request(normalized_query, query_tokens):
        return False
    recurring = (
        _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens)
        or bool({"ongoing", "durable", "24", "daily", "weekly", "monthly", "매일", "매주"} & query_tokens)
        or _contains_phrase(normalized_query, ("ongoing", "durable", "daily", "weekly", "monthly", "매일", "매주"))
    )
    support = bool(_RESEARCH_DEPARTMENT_SUPPORT_TOKENS & query_tokens) or _contains_phrase(
        normalized_query, _RESEARCH_DEPARTMENT_SUPPORT_TOKENS
    )
    specific_research_domain = (
        bool((_RESEARCH_DEPARTMENT_STRONG_TOKENS - {"research", "리서치", "조사"}) & query_tokens)
        or _contains_phrase(normalized_query, ("경쟁사", "시장", "논문"))
    )
    generic_research = bool({"research", "리서치", "조사"} & query_tokens)
    research = (
        specific_research_domain
        or (generic_research and support)
        or _contains_phrase(normalized_query, _RESEARCH_DEPARTMENT_PHRASES)
    )
    explicit_research_ops = _contains_phrase(normalized_query, _RESEARCH_DEPARTMENT_PHRASES)
    return recurring and research and (support or specific_research_domain or explicit_research_ops)


def is_explicit_one_off_request(normalized_query: str, query_tokens: set[str]) -> bool:
    return bool(_ONE_OFF_TOKENS & query_tokens) or _contains_phrase(normalized_query, _ONE_OFF_PHRASES)


def _web_research_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens):
        return False
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
    return _contains_phrase(
        normalized_query,
        (
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
        ),
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
    return _contains_phrase(
        normalized_query,
        (
            "open a pr",
            "prepare a pr",
            "make a pr",
            "pr ready",
            "pr-ready",
            "pull request",
            "pr까지",
        ),
    )


def _visual_summary_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if (_VISUAL_SUMMARY_MODALITY_TOKENS | _VISUAL_SUMMARY_CARD_TOKENS) & query_tokens and (
        _VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS & query_tokens
    ):
        return True
    if _VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS & query_tokens and _contains_phrase(
        normalized_query,
        ("summary image", "summary card", "briefing card", "announcement image", "요약 이미지", "요약 카드"),
    ):
        return True
    return _contains_phrase(normalized_query, _VISUAL_SUMMARY_PHRASES)


def _delivery_cycle_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    return _delivery_cycle_terms(normalized_query, query_tokens) and _contains_phrase(
        normalized_query,
        (
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
        ),
    )


def _contains_phrase(normalized_query: str, phrases: tuple[str, ...] | frozenset[str]) -> bool:
    return any(normalized_phrase(phrase) in normalized_query for phrase in phrases)
