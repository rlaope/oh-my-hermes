"""Name the skills a turn's request may want, from the catalog's own words.

The rule table in `awareness.py` names a workflow only when a message says one
of its cue phrases, and a person who does not know a skill's vocabulary
describes the situation instead ("our week-one retention dropped"). Measured
on a live model, that table named the intended skill for 14% of paraphrased
work requests, while a BM25 ranking over each skill's name, triggers,
situations, and description held it in its top four for most of them.

This module is that ranking, read from `tools/skill_shortlist.json`, which
`omh docs skill-shortlist` writes from the catalog. The bundle cannot import
`omh` (`tests/test_plugin_bundle_standalone.py`), so the tokenizer below
repeats `omh.routing.localization.routing_terms` and
`omh.routing.lexical_shortlist.lexical_terms` (stemmer included), and every
word list comes from the sidecar. `tests/test_skill_shortlist_sidecar.py` holds the two rankings
equal. A missing or unreadable sidecar ranks nothing, so the turn gets no line.

ASCII letter-and-digit words are ranked as above. Korean is ranked a second
way, on the syllable bigrams of the Hangul triggers the catalog already
carries (`omh.routing.lexical_shortlist.hangul_terms`, repeated here as
`hangul_terms`), with its own admission floor (`hangul_skill_candidates`); a
message the ASCII ranking admits keeps the ASCII line. Any other script is
dropped, so a message written wholly in it gets no line.

What reaches the model is one line of candidates, and only when the request
reads as work: see `skill_candidates_for_turn`. The line names skills the
model may load; it selects nothing and loads nothing. It is shown once per
session per candidate set (`claim_candidate_line`). A turn that matches no
skill and is obvious conversation gets `NO_MATCH_LINE` instead, once per run
of such turns, unless the turn already carries OMH work context
(`hooks/llm_hooks.py`).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import unicodedata

from .reference_regions import executable_routing_text

SIDECAR_PATH = Path(__file__).resolve().parent / "tools" / "skill_shortlist.json"
SCHEMA_VERSION = "omh_skill_shortlist_index/v1"

_HANGUL_RUN_RE = re.compile(r"[\uac00-\ud7a3]+")
_HANGUL_REQUEST_ENDING = "줘"
# `routing_terms`' token shape: a word, optionally hyphen-joined to one more.
_TOKEN_RE = re.compile(r"[^\W_][^\W_'-]*(?:-[^\W_][^\W_'-]*)?", re.UNICODE)

MAX_CANDIDATES = 3
# How many of the ranking's head can open the line. A skill further down that
# shares one ordinary word with the message is not evidence the message is work.
ADMISSION_HEAD = 3
# The line opens on a head skill with at least this many anchor words, or ...
ADMISSION_MIN_ANCHORS = 2
# ... with one anchor word and a score this high. Measured on the tuning sets
# (2026-09-26): everyday messages full of skill-ish words ("plan my weekend",
# "the doctor said") reach a skill on one common anchor such as `week`, `day`
# or `doctor` at scores 5-9; a work request that names its situation in one
# rare word ("postmortem", "churn") scores above 10.
ADMISSION_SINGLE_ANCHOR_SCORE = 10.0

# The Hangul line opens on a head skill of the Hangul ranking whose anchor
# bigrams sit in at least this many words of the message, at this score or
# above -- or in one word, at the single-word score. Measured on the tuning
# sets (2026-09-26, 40 Korean work requests and 40 everyday Korean messages,
# own words): everyday Korean reaches a skill on one word ("날씨", "같이",
# "감사", or "다이어트" sharing two bigrams with "다이어그램") at scores below
# 7, while a work request names its situation in two words or more ("빌드
# 실패", "고객 피드백") and scores 6.5-36.
HANGUL_ADMISSION_MIN_WORDS = 2
HANGUL_ADMISSION_SCORE_FLOOR = 6.0
HANGUL_ADMISSION_SINGLE_WORD_SCORE = 10.0

# A request this short in content words is a greeting, a thanks, or a reply.
_MIN_CONTENT_TERMS = 3
# Direct factual questions: one sentence that opens like one. A lookup the
# model answers from what it knows needs no skill line.
_FACTUAL_OPENERS = (
    "what is ",
    "what's ",
    "what are ",
    "what was ",
    "what were ",
    "what does ",
    "who is ",
    "who was ",
    "who wrote ",
    "who invented ",
    "when is ",
    "when was ",
    "when did ",
    "where is ",
    "where was ",
    "why is ",
    "why do ",
    "why does ",
    "how many ",
    "how much ",
    "how far ",
    "how old ",
    "how long ",
    "how do you say ",
)
_FACTUAL_MAX_WORDS = 14
_SENTENCE_BREAK_RE = re.compile(r"[.!?\n]\s+\S")
# Conversational requests, wherever they sit in the message: entertainment
# (a joke, a poem, a story, a movie or book to recommend) and asking for
# personal advice or support. Each is a kind of request, not a topic word, so
# "a joke about secret tokens" and "a movie about hackers and security" stay
# conversation even though their topic words reach a skill.
_CONVERSATIONAL_REQUEST_RE = re.compile(
    r"\b(?:jokes?|poems?|haikus?|riddles?|limericks?)\b"
    r"|\b(?:tell|write) me a (?:\w+ )?story\b"
    r"|\brecommend (?:me )?(?:a |an |some )?(?:\w+ ){0,2}"
    r"(?:movies?|films?|books?|novels?|songs?|albums?|podcasts?|shows?|tv series|games?|restaurants?)\b"
    r"|\bany advice\b"
    r"|\bi(?:'m| am)? feel(?:ing)? (?:so |really |a bit |kind of )?"
    r"(?:stressed|sad|lonely|anxious|tired|down|nervous|overwhelmed|bored|happy|burned out|burnt out)\b"
    r"|\bhow do i feel\b"
)

# Skills the line never names. `jev-*` skills send data off the machine and
# are reached only by naming Jev; `maestro` (`ulw-maestro`) is the lane for a
# coding owner the person already chose, never a suggestion.
_NEVER_LISTED_PREFIX = "jev-"
_NEVER_LISTED = frozenset({"maestro"})

# The route hint's id for a message that names its workflow. The person chose;
# a list of alternatives would argue with them.
_DIRECT_INVOCATION_HINT_ID = "direct_workflow_invocation"


@dataclass(frozen=True)
class _Skill:
    name: str
    label: str
    situation: str
    weights: dict[str, float]
    length: float
    anchors: frozenset[str]
    hangul: frozenset[str]
    hangul_anchors: frozenset[str]


@dataclass(frozen=True)
class _Index:
    skills: tuple[_Skill, ...]
    idf: dict[str, float]
    average_length: float
    k1: float
    b: float
    score_floor: float
    stopwords: frozenset[str]
    stem_exceptions: frozenset[str]
    hangul_idf: dict[str, float]
    hangul_average_length: float
    hangul_stopwords: frozenset[str]


# Cached, `None` included: a sidecar that is missing, unreadable, of another
# schema version, or malformed ranks nothing until the process restarts. The
# file ships inside the bundle, so the only repair is a new bundle, and an
# `omh update` comes with the Hermes restart that clears this cache.
@lru_cache(maxsize=1)
def _index() -> _Index | None:
    try:
        payload = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        skills: list[_Skill] = []
        document_frequency: dict[str, int] = {}
        hangul_frequency: dict[str, int] = {}
        for row in payload["skills"]:
            weights: dict[str, float] = {}
            for key, terms in row["terms"].items():
                for term in str(terms).split():
                    weights[term] = float(key)
            # The source sums each field's weight per term in field order; the
            # sum of the per-term totals is the same whole number.
            length = float(sum(weights.values()))
            for term in weights:
                document_frequency[term] = document_frequency.get(term, 0) + 1
            hangul = frozenset(str(row["hangul"]).split())
            for term in hangul:
                hangul_frequency[term] = hangul_frequency.get(term, 0) + 1
            skills.append(
                _Skill(
                    name=str(row["name"]),
                    label=str(row["label"]),
                    situation=str(row["situation"]),
                    weights=weights,
                    length=length,
                    anchors=frozenset(str(row["anchors"]).split()),
                    hangul=hangul,
                    hangul_anchors=frozenset(str(row["hangul_anchors"]).split()),
                )
            )
        count = len(skills)
        idf = {
            term: math.log((count - frequency + 0.5) / (frequency + 0.5) + 1.0)
            for term, frequency in document_frequency.items()
        }
        hangul_idf = {
            term: math.log((count - frequency + 0.5) / (frequency + 0.5) + 1.0)
            for term, frequency in hangul_frequency.items()
        }
        bm25 = payload["bm25"]
        return _Index(
            skills=tuple(skills),
            idf=idf,
            average_length=sum(skill.length for skill in skills) / max(count, 1),
            k1=float(bm25["k1"]),
            b=float(bm25["b"]),
            score_floor=float(payload["score_floor"]),
            stopwords=frozenset(str(payload["stopwords"]).split()),
            stem_exceptions=frozenset(str(payload["stem_exceptions"]).split()),
            hangul_idf=hangul_idf,
            hangul_average_length=sum(len(skill.hangul) for skill in skills) / max(count, 1),
            hangul_stopwords=frozenset(str(payload["hangul_stopwords"]).split()),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _routing_terms(value: str) -> set[str]:
    terms: set[str] = set()
    for raw_token in _TOKEN_RE.findall(_fold(value)):
        token = raw_token.strip("-")
        if token:
            terms.add(token)
            terms.update(part for part in token.split("-") if part)
    return terms


def _stem(token: str, exceptions: frozenset[str]) -> str:
    """`omh.routing.lexical_shortlist.stem`, repeated: the parity test holds them equal."""
    if token in exceptions:
        return token
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("sses", "xes", "zes", "ches", "shes")):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    for suffix in ("ing", "ed"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            base = token[: -len(suffix)]
            if len(base) > 2 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            token = base
            break
    if len(token) > 4 and token.endswith("e") and not token.endswith("ee"):
        token = token[:-1]
    return token


def lexical_terms(text: str) -> list[str]:
    """ASCII content words of `text`, stopworded and stemmed, in order."""
    index = _index()
    if index is None:
        return []
    terms: list[str] = []
    for raw in sorted(_routing_terms(text)):
        for part in raw.split("-"):
            if len(part) < 2 or not part.isascii() or not part.isalnum() or part in index.stopwords:
                continue
            terms.append(_stem(part, index.stem_exceptions))
    return terms


@lru_cache(maxsize=1024)
def lexical_ranking(message: str) -> tuple[tuple[str, float], ...]:
    """Every catalog skill that shares a content word with `message`, best first."""
    index = _index()
    if index is None:
        return ()
    query = set(lexical_terms(message))
    if not query:
        return ()
    scored: list[tuple[str, float]] = []
    for skill in index.skills:
        norm = index.k1 * (1.0 - index.b + index.b * skill.length / index.average_length)
        score = 0.0
        for term in sorted(query):
            frequency = skill.weights.get(term)
            if frequency:
                score += index.idf[term] * frequency * (index.k1 + 1.0) / (frequency + norm)
        if score > 0.0:
            scored.append((skill.name, round(score, 6)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return tuple(scored)


def hangul_terms(text: str) -> list[str]:
    """`omh.routing.lexical_shortlist.hangul_terms`, repeated: syllable bigrams, filler dropped."""
    index = _index()
    if index is None:
        return []
    terms: set[str] = set()
    for run in _HANGUL_RUN_RE.findall(unicodedata.normalize("NFKC", text)):
        for start in range(len(run) - 1):
            bigram = run[start : start + 2]
            if bigram[1] != _HANGUL_REQUEST_ENDING and bigram not in index.hangul_stopwords:
                terms.add(bigram)
    return sorted(terms)


@lru_cache(maxsize=1024)
def hangul_ranking(message: str) -> tuple[tuple[str, float], ...]:
    """Every skill whose Hangul triggers share a bigram with `message`, best first.

    BM25 over each skill's trigger bigrams, one count per bigram, with the
    same constants as the ASCII ranking; ties break on the skill name.
    """
    index = _index()
    if index is None:
        return ()
    query = set(hangul_terms(message))
    if not query:
        return ()
    scored: list[tuple[str, float]] = []
    for skill in index.skills:
        shared = query & skill.hangul
        if not shared:
            continue
        norm = index.k1 * (1.0 - index.b + index.b * len(skill.hangul) / index.hangul_average_length)
        score = sum(index.hangul_idf[term] * (index.k1 + 1.0) / (1.0 + norm) for term in sorted(shared))
        scored.append((skill.name, round(score, 6)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return tuple(scored)


def hangul_skill_candidates(message: str) -> tuple[tuple[str, str], ...]:
    """Up to three (skill label, situation) pairs from the Hangul ranking, or none.

    Admission: a skill in the ranking's head scores at least
    `HANGUL_ADMISSION_SCORE_FLOOR` and its anchor bigrams -- bigrams at most
    eight skills' Hangul triggers use -- sit in two words of the message, or
    in one at `HANGUL_ADMISSION_SINGLE_WORD_SCORE`. Two bigrams inside one
    word are often a spelling accident ("다이어트" and "다이어그램"). Listed are the ranked skills at that score
    with an anchor of their own, never a `_NEVER_LISTED` one.
    """
    index = _index()
    if index is None:
        return ()
    ranking = [
        (name, score)
        for name, score in hangul_ranking(message)
        if not name.startswith(_NEVER_LISTED_PREFIX) and name not in _NEVER_LISTED
    ]
    by_name = {skill.name: skill for skill in index.skills}
    words = [frozenset(hangul_terms(word)) for word in message.split()]
    terms = frozenset().union(*words) if words else frozenset()

    def anchored(name: str) -> frozenset[str]:
        return terms & by_name[name].hangul_anchors

    def anchored_words(name: str) -> int:
        return sum(1 for word in words if word & by_name[name].hangul_anchors)

    admitted = any(
        score >= HANGUL_ADMISSION_SCORE_FLOOR
        and (
            anchored_words(name) >= HANGUL_ADMISSION_MIN_WORDS
            or (anchored(name) and score >= HANGUL_ADMISSION_SINGLE_WORD_SCORE)
        )
        for name, score in ranking[:ADMISSION_HEAD]
    )
    if not admitted:
        return ()
    listed = [
        (by_name[name].label, by_name[name].situation)
        for name, score in ranking
        if score >= HANGUL_ADMISSION_SCORE_FLOOR and anchored(name)
    ]
    return tuple(listed[:MAX_CANDIDATES])


def _conversational(message: str) -> bool:
    """A greeting, a thanks, a conversational request, or a one-sentence factual question."""
    if len(set(lexical_terms(message))) < _MIN_CONTENT_TERMS:
        return True
    text = " ".join(_fold(message).replace("\u2019", "'").split())
    if _CONVERSATIONAL_REQUEST_RE.search(text):
        return True
    return (
        text.startswith(_FACTUAL_OPENERS)
        and not _SENTENCE_BREAK_RE.search(text)
        and len(text.split()) <= _FACTUAL_MAX_WORDS
    )


def skill_candidates(message: str) -> tuple[tuple[str, str], ...]:
    """Up to three (skill label, situation) pairs for a request that reads as work.

    Admission, all of it read from the catalog: the message must share an
    anchor word -- a word from a skill's name, triggers, or situations that at
    most eight skills use, minus the words the router only credits inside a
    whole phrase -- with a skill in the ranking's head, scoring at least the
    shortlist floor. One anchor is not enough on its own unless the score is
    high: everyday English shares single words with the catalog constantly.
    Listed are the ranked skills that clear the floor with an anchor of their
    own; never a `jev-*` skill or `ulw-maestro` (`_NEVER_LISTED`).
    """
    index = _index()
    if index is None:
        return ()
    ranking = [
        (name, score)
        for name, score in lexical_ranking(message)
        if not name.startswith(_NEVER_LISTED_PREFIX) and name not in _NEVER_LISTED
    ]
    if not ranking:
        return ()
    by_name = {skill.name: skill for skill in index.skills}
    terms = frozenset(lexical_terms(message))

    def anchored(name: str) -> frozenset[str]:
        return terms & by_name[name].anchors

    admitted = any(
        score >= index.score_floor
        and (
            len(anchored(name)) >= ADMISSION_MIN_ANCHORS
            or (anchored(name) and score >= ADMISSION_SINGLE_ANCHOR_SCORE)
        )
        for name, score in ranking[:ADMISSION_HEAD]
    )
    if not admitted:
        return ()
    listed = [
        (by_name[name].label, by_name[name].situation)
        for name, score in ranking
        if score >= index.score_floor and anchored(name)
    ]
    return tuple(listed[:MAX_CANDIDATES])


def skill_candidates_for_turn(
    message: str, *, route_hint_payload: dict[str, object] | None = None
) -> tuple[tuple[str, str], ...]:
    """The candidates this turn's line names, or none.

    None for a message that names its own workflow (the route hint's direct
    invocation). The ASCII line stands down for small talk, a conversational
    request, or a direct factual question; a message it does not admit is
    then read for Korean (`hangul_skill_candidates`). The conversational
    check reads ASCII words only, so it does not filter Korean: everyday
    Korean is kept out by the Hangul score and anchor floor alone, with no
    kind-based check for a Korean joke or venting request.
    """
    if not message.strip():
        return ()
    hints = (route_hint_payload or {}).get("hints")
    if isinstance(hints, list) and any(
        isinstance(hint, dict) and hint.get("id") == _DIRECT_INVOCATION_HINT_ID for hint in hints
    ):
        return ()
    text = executable_routing_text(message)
    if not _conversational(text):
        candidates = skill_candidates(text)
        if candidates:
            return candidates
    return hangul_skill_candidates(text)


# The last candidate set each session was shown, so a run of work turns that
# rank the same skills carries the line once. Process-local, the way the
# board card remembers its one-shot line (`hooks/llm_hooks.py`): the awareness
# ledger keeps one route slot per session, and that slot is the route hint's.
# A Hermes restart forgets it and the next matching turn shows the line again.
_MAX_REMEMBERED_SESSIONS = 256
_shown_lock = threading.Lock()
_shown_by_session: "OrderedDict[str, str]" = OrderedDict()


def claim_candidate_line(session_id: str, candidates: tuple[tuple[str, str], ...]) -> bool:
    """True when this session has not been shown exactly this candidate set last."""
    if not candidates:
        return False
    fingerprint = hashlib.sha256("\n".join(label for label, _ in candidates).encode("utf-8")).hexdigest()
    return _claim_line(session_id, fingerprint)


# Recorded in the same slot as a candidate set, so a run of turns that match
# nothing carries the no-match line once, and it comes back after a turn that
# showed candidates. Not a sha256 hex digest, so it cannot equal a set's.
_NO_MATCH_FINGERPRINT = "no-match"


_SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")


def names_a_skill(message: str) -> bool:
    """Whether `message` spells an installed skill's name, as in "run omh-plan"."""
    index = _index()
    if index is None:
        return False
    labels = {skill.label for skill in index.skills}
    return any(word in labels for word in _SKILL_NAME_RE.findall(message.lower()))


# A message this short, none of whose words the catalog uses anywhere, is an
# acknowledgement or a reaction ("lol ok", "고마워", "yes"). Counted in
# whitespace-separated words after executable_routing_text, so a Korean
# sentence counts its eojeol.
_ACKNOWLEDGEMENT_MAX_WORDS = 4


def obvious_conversation(message: str) -> bool:
    """A conversational request, or a short message in none of the catalog's words.

    The first is `_CONVERSATIONAL_REQUEST_RE`: a joke, a poem, a story, a
    recommendation, advice, or a feeling. The second is at most
    `_ACKNOWLEDGEMENT_MAX_WORDS` words, none of whose ASCII terms or Hangul
    bigrams appear in any skill's vocabulary, so "fix it", "continue",
    "next" and "계속" are not conversation. A message that merely ranked no
    skill is not either: a work request the ranking cannot read looks the same.
    """
    index = _index()
    if index is None:
        return False
    text = executable_routing_text(message)
    folded = " ".join(_fold(text).replace("\u2019", "'").split())
    if _CONVERSATIONAL_REQUEST_RE.search(folded):
        return True
    if not folded or len(folded.split()) > _ACKNOWLEDGEMENT_MAX_WORDS:
        return False
    if any(term in index.idf for term in lexical_terms(text)):
        return False
    return not any(bigram in index.hangul_idf for bigram in hangul_terms(text))


def claim_no_match_line(session_id: str) -> bool:
    """True when this session was not shown the no-match line last.

    Never for a turn with no session id: there is no run of turns to show it
    once in, and repeating it on every unmatched turn is the cost the claim
    exists to avoid.
    """
    if not session_id:
        return False
    return _claim_line(session_id, _NO_MATCH_FINGERPRINT)


def _claim_line(session_id: str, fingerprint: str) -> bool:
    if not session_id:
        return True
    with _shown_lock:
        if _shown_by_session.get(session_id) == fingerprint:
            return False
        _shown_by_session[session_id] = fingerprint
        _shown_by_session.move_to_end(session_id)
        while len(_shown_by_session) > _MAX_REMEMBERED_SESSIONS:
            _shown_by_session.popitem(last=False)
    return True


def reset_candidate_line_state() -> None:
    with _shown_lock:
        _shown_by_session.clear()


def skill_candidate_line(candidates: tuple[tuple[str, str], ...]) -> str:
    """One plain sentence naming the candidates by the situation each serves."""
    if not candidates:
        return ""
    options = "; ".join(f"{label} ({situation})" for label, situation in candidates)
    # The exact call form, because a model that guesses a category prefix
    # gets "not found" when the guess is wrong (`operator/omh-x` for a skill
    # filed under `reviewer/`). Hermes resolves a correct `category/name` in
    # external dirs too; the bare name is the form that cannot be wrong.
    return (
        f"Skills that may fit this request: {options}. "
        "If one matches what the user described, load it before you answer with skill_view and "
        f'the name exactly as written here, for example skill_view(name="{candidates[0][0]}"), '
        "with no category prefix; none of them may fit, and then no skill is needed."
    )


# The line for a turn that is obvious conversation (`obvious_conversation`)
# and matched no skill. It states what the ranking found and what OMH's
# skills are for; it says nothing about how the host should treat skills in
# general. Shown on every unmatched turn, it cost 2.9 points of intended
# loads on held-out work requests the ranking found nothing for (Luna, two
# runs), so it no longer fires on "nothing matched" alone.
NO_MATCH_LINE = (
    "No OMH skill matched this message. If it is conversation rather than a work request, "
    "none is needed to reply."
)


__all__ = [
    "NO_MATCH_LINE",
    "ADMISSION_HEAD",
    "ADMISSION_MIN_ANCHORS",
    "ADMISSION_SINGLE_ANCHOR_SCORE",
    "HANGUL_ADMISSION_MIN_WORDS",
    "HANGUL_ADMISSION_SCORE_FLOOR",
    "HANGUL_ADMISSION_SINGLE_WORD_SCORE",
    "MAX_CANDIDATES",
    "claim_candidate_line",
    "claim_no_match_line",
    "hangul_ranking",
    "hangul_skill_candidates",
    "hangul_terms",
    "reset_candidate_line_state",
    "lexical_ranking",
    "lexical_terms",
    "names_a_skill",
    "obvious_conversation",
    "skill_candidate_line",
    "skill_candidates",
    "skill_candidates_for_turn",
]
