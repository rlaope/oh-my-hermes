"""How routing folds and splits text: one implementation for the router and the plugin bundle.

The router's `localization` and the workflow-intent classifier
(`workflow_intent`) read a message through these functions, and the bundle's
route hint runs that same classifier. Hermes loads the bundle with its own
interpreter, which often cannot import the `omh` package, so the functions live
here and `omh.routing.localization` / `omh.routing.visual_qa_cues` import them
rather than the other way round. Stdlib only.
"""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

TOKEN_RE = re.compile(r"[^\W_][^\W_'-]*(?:-[^\W_][^\W_'-]*)?", re.UNICODE)
ROUTING_STOPWORDS = frozenset(
    {
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
        "user",
        "task",
        "request",
        "workflow",
        "skill",
        "agent",
        "hermes",
    }
)


@lru_cache(maxsize=8192)
def fold_for_match(value: str) -> str:
    """NFKC, case-folded, with combining marks dropped: the fold every routing matcher compares in."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalized_phrase(value: str) -> str:
    return fold_for_match(value)


def routing_terms(value: str) -> set[str]:
    return set(_routing_terms_cached(value))


@lru_cache(maxsize=8192)
def _routing_terms_cached(value: str) -> frozenset[str]:
    folded = fold_for_match(value)
    terms: set[str] = set()
    for raw_token in TOKEN_RE.findall(folded):
        token = raw_token.strip("-")
        if token:
            terms.add(token)
            terms.update(part for part in token.split("-") if part)
    return frozenset(terms)


def routing_tokens(value: str, *, stopwords: set[str] | frozenset[str] | None = None) -> set[str]:
    stopword_key = frozenset(ROUTING_STOPWORDS if stopwords is None else stopwords)
    return set(_routing_tokens_cached(value, stopword_key))


@lru_cache(maxsize=8192)
def _routing_tokens_cached(value: str, stopwords: frozenset[str]) -> frozenset[str]:
    tokens: set[str] = set()
    for raw_token in routing_terms(value):
        for token in (raw_token, *raw_token.split("-")):
            if len(token) >= 3 and token not in stopwords:
                tokens.add(token)
    return frozenset(tokens)


def contains_cue_phrase(message: str, phrases: tuple[str, ...]) -> bool:
    """Some phrase occurs in `message`, lower-cased and accent-folded, or with every non-alphanumeric removed."""
    text = _cue_text(message)
    compact = _compact_cue_text(text)
    return any(
        _cue_text(phrase) in text or _compact_cue_text(_cue_text(phrase)) in compact
        for phrase in phrases
    )


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
