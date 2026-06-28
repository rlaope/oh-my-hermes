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
    "omh누락",
    "워크플로누락",
    "라우팅누락",
    "잘못라우팅",
)


def has_missed_omh_workflow_context(message: str) -> bool:
    normalized = normalized_phrase(message)
    if _contains_phrase(normalized, OMH_MISSED_WORKFLOW_PHRASES):
        return True
    return ("omh" in normalized or "oh-my-hermes" in normalized) and _contains_phrase(
        normalized,
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


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in _normalized_phrases(phrases))


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
