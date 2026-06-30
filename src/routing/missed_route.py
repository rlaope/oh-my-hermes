from __future__ import annotations

from functools import lru_cache

from .localization import normalized_phrase


OMH_MISSED_WORKFLOW_PHRASES = (
    "did not use omh",
    "didn't use omh",
    "didnt use omh",
    "omh was not used",
    "not using omh",
    "not use omh",
    "without omh",
    "missed omh",
    "skipped omh",
    "skipped omh for",
    "hermes skipped omh",
    "forgot omh",
    "not aware of omh",
    "did not know omh",
    "didn't know omh",
    "why omh was not used",
    "why did not use omh",
    "omh 안 쓰고",
    "omh 안 썼",
    "omh를 안 썼",
    "omh를 안 써",
    "omh 기능을 안 썼",
    "omh 기능 안 썼",
    "omh 기능을 모르는",
    "omh 기능 모르",
    "omh context를 못 보",
    "omh context 못 보",
    "omh 컨텍스트를 못 보",
    "omh 컨텍스트 못 보",
    "omh가 자꾸 일반 답변",
    "omh 일반 답변",
)
MISSED_WORKFLOW_ACTION_PHRASES = (
    "did not use",
    "didn't use",
    "didnt use",
    "does not use",
    "doesn't use",
    "doesnt use",
    "not using",
    "not use",
    "without",
    "missed",
    "skipped",
    "forgot",
    "not aware",
    "did not know",
    "didn't know",
    "does not know",
    "몰랐",
    "모르",
    "안 썼",
    "안 써",
    "안쓰",
    "안 쓰",
    "놓쳤",
    "빠졌",
    "빠져",
    "일반 답변",
    "잘못 고른",
    "잘못 골",
    "못 보",
)
MISSED_ROUTE_FEEDBACK_PHRASES = (
    "missed route",
    "missed workflow",
    "missing route",
    "wrong route",
    "wrong workflow",
    "did not use omh",
    "didn't use omh",
    "didnt use omh",
    "not use omh",
    "skipped omh",
    "omh was not used",
    "omh was skipped",
    "expected omh",
    "expected workflow",
    "why omh was not used",
    "why did not use omh",
    "안 썼는데 다음엔",
    "안 썼는데 다음에는",
    "안 쓴 것 같은데 다음엔",
    "안 쓴 것 같은데 다음에는",
    "안 쓴 것 같아",
    "안 쓴 것 같아 다음엔",
    "안 쓴 것 같아 다음에는",
    "안 쓰고 그냥 답했어",
    "안썼는데 다음엔",
    "안썼는데 다음에는",
    "안쓴것같은데다음엔",
    "안쓴것같은데다음에는",
    "안쓴것같아",
    "안쓴것같아다음엔",
    "안쓴것같아다음에는",
    "안쓰고그냥답했어",
    "다음엔 쓰게 해줘",
    "다음에는 쓰게 해줘",
    "다음엔 쓰게 고쳐",
    "다음에는 쓰게 고쳐",
    "다음엔 쓰게 개선",
    "다음에는 쓰게 개선",
    "다음엔 보내줘",
    "다음에는 보내줘",
    "general answer instead of omh",
    "generic answer instead of omh",
    "omh became a generic answer",
    "omh keeps falling back to a generic answer",
    "agent does not know omh",
    "agent cannot see omh context",
    "agent can't see omh context",
    "router chose the wrong workflow",
    "router picked the wrong workflow",
    "omh가 자꾸 일반 답변",
    "일반 답변으로 빠져",
    "일반 답변으로 빠짐",
    "라우터가 잘못 고른",
    "라우터가 잘못 골",
    "omh 기능을 모르는",
    "omh 기능 모르",
    "omh context를 못 보는",
    "omh context 못 보는",
    "omh 컨텍스트를 못 보는",
    "omh 컨텍스트 못 보는",
    "지금 omh가 안 쓰여",
    "omh가 안 쓰여",
)
MISSED_ROUTE_COMPACT_PHRASES = (
    "omh안썼",
    "omh안썻",
    "omh안썼어",
    "omh안썻어",
    "omh안쓰",
    "omh를안썼",
    "omh를안썻",
    "omh를안쓰",
    "omh기능을안썼",
    "omh기능을안썻",
    "omh기능안썼",
    "omh기능안썻",
    "omh기능안쓰",
    "omh안씀",
    "안썼는데다음엔",
    "안썻는데다음엔",
    "안썼는데다음에는",
    "안썻는데다음에는",
    "안쓴것같은데다음엔",
    "안쓴것같은데다음에는",
    "안쓰고그냥답했어",
    "다음엔쓰게해줘",
    "다음에는쓰게해줘",
    "다음엔쓰게고쳐",
    "다음에는쓰게고쳐",
    "다음엔보내줘",
    "다음에는보내줘",
    "omh누락",
    "워크플로누락",
    "라우팅누락",
    "잘못라우팅",
    "omh일반답변",
    "일반답변으로빠져",
    "일반답변으로빠짐",
    "라우터가잘못고른",
    "라우터가잘못골",
    "omh기능모르",
    "omhcontext못보",
    "omh컨텍스트못보",
    "omh가안쓰여",
)


def has_missed_omh_workflow_context(message: str) -> bool:
    return has_normalized_missed_omh_workflow_context(normalized_phrase(message))


def has_normalized_missed_omh_workflow_context(normalized_message: str) -> bool:
    has_omh_context = "omh" in normalized_message or "oh-my-hermes" in normalized_message
    if not has_omh_context:
        return False
    if _contains_phrase(normalized_message, OMH_MISSED_WORKFLOW_PHRASES):
        return True
    return _contains_phrase(
        normalized_message,
        MISSED_WORKFLOW_ACTION_PHRASES,
    )


def is_missed_route_feedback(message: str) -> bool:
    normalized = normalized_phrase(message)
    if not normalized:
        return False
    if _contains_phrase(normalized, MISSED_ROUTE_FEEDBACK_PHRASES):
        return True
    return _contains_compact_phrase(normalized, MISSED_ROUTE_COMPACT_PHRASES)


def is_missed_omh_workflow_feedback(message: str) -> bool:
    normalized = normalized_phrase(message)
    if not normalized or "omh" not in normalized:
        return False
    return is_missed_route_feedback(normalized)


@lru_cache(maxsize=4096)
def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in _normalized_phrases(phrases))


@lru_cache(maxsize=4096)
def _contains_compact_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    compact = text.replace(" ", "")
    return any(phrase in compact for phrase in _normalized_compact_phrases(phrases))


@lru_cache(maxsize=16)
def _normalized_phrases(phrases: tuple[str, ...]) -> tuple[str, ...]:
    normalized_phrases: list[str] = []
    for phrase in phrases:
        normalized = normalized_phrase(phrase)
        if normalized:
            normalized_phrases.append(normalized)
    return tuple(normalized_phrases)


@lru_cache(maxsize=16)
def _normalized_compact_phrases(phrases: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(phrase.replace(" ", "") for phrase in _normalized_phrases(phrases))
