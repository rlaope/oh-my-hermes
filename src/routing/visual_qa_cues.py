from __future__ import annotations

from functools import lru_cache
import unicodedata


BROWSER_VISUAL_QA_PHRASES = (
    "browser qa",
    "browser interaction qa",
    "click path",
    "click-path audit",
    "dead link check",
    "console error check",
    "network failure check",
    "keyboard navigation check",
    "screenshot qa",
    "visual qa",
)
BROWSER_VISUAL_QA_COMMAND_PHRASES = (
    "browser qa",
    "browser interaction qa",
    "click path audit",
    "click-path audit",
    "dead link check",
    "console error check",
    "network failure check",
    "keyboard navigation check",
    "screenshot qa",
    "visual qa",
)
CUSTOMER_SYMPTOM_REPORT_PHRASES = (
    "customers say",
    "customers report",
    "customer says",
    "customer reports",
    "customer feedback says",
    "customer feedback reports",
    "users say",
    "users report",
    "user says",
    "user reports",
    "고객이 말",
    "고객이 제보",
    "고객 제보",
    "사용자가 말",
    "사용자가 제보",
    "사용자 제보",
)


def contains_cue_phrase(message: str, phrases: tuple[str, ...]) -> bool:
    text = _cue_text(message)
    compact = _compact_cue_text(text)
    return any(phrase in text or _compact_cue_text(phrase) in compact for phrase in phrases)


@lru_cache(maxsize=4096)
def _cue_text(message: str) -> str:
    lowered = message.strip().lower()
    folded = "".join(
        character for character in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(character)
    )
    return folded


@lru_cache(maxsize=4096)
def _compact_cue_text(text: str) -> str:
    return "".join(character for character in text if character.isalnum())
