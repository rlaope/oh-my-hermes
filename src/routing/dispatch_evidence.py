"""Does a scored winner carry enough evidence of its own to dispatch?

Shortlist first. `_confidence` calls a score of 8 `high`, and a high winner
used to dispatch. Eight is three everyday words: a trigger phrase is also
credited through each of its tokens, so a sentence that merely contains
`before` and `merge` reached `verification-gate`. A dispatch on that evidence
throws away what the router does better on such a message: a shortlist that
names the right skill. (On the in-sample tuning set, BM25's top four held the
intended skill for most English messages where a token-scored winner often
did not; that is a tuning-set observation, not a held-out claim.)

So a confident winner dispatches only on strong evidence, and every other
winner becomes a clarify that carries the shortlist for Hermes to choose from.
This module does not change a score, a confidence, or an ordering. It reads
the winner's matched labels -- the record of why it scored -- and classifies
them. The caller dispatches on every class except `weak`.

Strong evidence:

- an explicit invocation, the skill's rendered label named in the message
  (`ulw-context`, `omh-code-review`), a `direct:` predicate, or a `domain:`
  signal;
- any label the generic scorer does not produce (a fast path decided it);
- the winner's own multi-word, hyphenated, or sigilled trigger phrase
  (`code review`, `ulw-context`, `$ulw`), or its multi-word name, unless
  another scored skill said as many phrases of its own and the winner's own
  evidence does not lead it by `PHRASE_LEAD` -- two even phrases are a
  choice, not a decision. A phrase that is only a cadence (`every morning`)
  counts only when the message reads as a request: it says when something
  happens, so in a report (`every morning I ...`) it names no job;
- a trusted intent guard: one that matches an intent shape and, where it was
  measured deciding dispatches, was right at least three times for every
  wrong. The table is `GUARD_DISPATCH_TRUST` in `routing/policy.py`;
- non-ASCII input, which the Routing Language Policy leaves to the frozen
  trigger tables and to model selection rather than to an English-word gate.

Weak evidence, which clarifies: trigger tokens however many or rare, a single
word of the skill's name, description words, and a context-only guard, which
fires on co-occurring topic words rather than an intent shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .policy import is_cadence_phrase, reads_as_a_request


EVIDENCE_EXPLICIT = "explicit"
EVIDENCE_DIRECT = "direct"
EVIDENCE_FAST_PATH = "fast_path"
EVIDENCE_TRIGGER_PHRASE = "trigger_phrase"
EVIDENCE_TRUSTED_GUARD = "trusted_guard"
EVIDENCE_NON_ASCII_EXEMPT = "non_ascii_exempt"
EVIDENCE_WEAK = "weak"
# The value `GUARD_DISPATCH_TRUST` gives an intent-shaped guard.
GUARD_TRUSTED = "trusted"

# The shortlist admits a scored candidate ahead of the lexical ranks only with
# this much evidence of its own: one trigger phrase, or two trigger tokens.
OWN_EVIDENCE_FLOOR = 6
# When another scored skill also said a phrase of its own, the winner still
# dispatches only if its own evidence leads by one more phrase's worth.
PHRASE_LEAD = 6

# The labels `_score_definition` and the guard reranker produce, with the score
# each one added toward the skill's OWN evidence. Anything else in a winner's
# labels was put there by a decision path this gate does not judge. A metadata
# label counts zero here although the scorer gives it +1: it is a word the
# message shares with the skill's description prose.
_SCORER_LABEL_WEIGHTS: Mapping[str, int] = {
    "trigger": 3,
    "name": 5,
    "description": 3,
    "use_when": 3,
    "category": 2,
    "phase": 2,
    "metadata": 0,
    "locale": 0,
    "guard": 0,
}
_TRIGGER_PHRASE_WEIGHT = 6
_DIRECT_PREFIXES = ("direct:", "domain:", "domain_action:")
# A sigilled trigger (`$ulw`, `/omh`) is a command the user typed, not a word
# that happened to occur; it is phrase evidence even though it has no space.
_COMMAND_SIGILS = ("$", "/", "@")
# The product's own name names OMH, not one of its skills: a question about
# whether OMH is installed or working is a doctor question, not the router.
_PRODUCT_NAME_TOKENS = frozenset({"oh-my-hermes", "oh-my", "oh-my-hermes-agent"})


def _kind(label: str) -> str:
    return label.split(":", 1)[0]


def _value(label: str) -> str:
    return label.split(":", 1)[1] if ":" in label else ""


def _labels(recommendation: Mapping[str, object]) -> list[str]:
    raw = recommendation.get("matched")
    return [str(label) for label in raw] if isinstance(raw, (list, tuple)) else []


def own_evidence_score(labels: Sequence[str]) -> int:
    """The score a candidate's trigger, name, and field-phrase labels account for.

    A lower bound on the scorer's own total: a single-word trigger that also
    matched as a phrase is credited once here, and description-word metadata
    counts zero. Guard labels count zero, which is the point -- this is what
    the skill earned before any guard boosted it.
    """
    total = 0
    for label in labels:
        kind = _kind(label)
        if kind == "trigger" and " " in _value(label):
            total += _TRIGGER_PHRASE_WEIGHT
        else:
            total += _SCORER_LABEL_WEIGHTS.get(kind, 0)
    return total


def phrase_count(labels: Sequence[str]) -> int:
    """Multi-word, hyphenated, or sigilled trigger phrases and multi-word names said.

    A hyphenated trigger (`ulw-context`, `oh-my-hermes`) is a skill's own
    compound name typed as one word, not a word that happened to occur. The
    product's own name is not a skill's.
    """
    count = 0
    for label in labels:
        kind, value = _kind(label), _value(label)
        if kind == "trigger" and value in _PRODUCT_NAME_TOKENS:
            continue
        if kind == "trigger" and (" " in value or "-" in value or value.startswith(_COMMAND_SIGILS)):
            count += 1
        elif kind == "name" and " " in value:
            count += 1
    return count


def has_own_phrase(labels: Sequence[str]) -> bool:
    return phrase_count(labels) > 0


def dispatch_evidence(
    top: Mapping[str, object],
    others: Sequence[Mapping[str, object]],
    *,
    message: str,
    guard_trust: Mapping[str, str],
    named_surface: bool = False,
) -> str:
    """Classify the evidence behind a confident scored winner.

    `others` are the rest of the scored field. `guard_trust` maps a
    `guard:<label>` to `trusted` or `context_only`; an unknown guard label is
    treated as context-only.
    """
    labels = _labels(top)
    if "explicit_invocation" in labels or named_surface:
        return EVIDENCE_EXPLICIT
    if any(label.startswith(_DIRECT_PREFIXES) for label in labels):
        return EVIDENCE_DIRECT
    fast_path_guards = [label for label in labels if _kind(label) == "guard_fast_path"]
    if fast_path_guards and message.isascii():
        # A guard fast path answers to the trust table like a scored guard.
        guard_labels = [label for label in labels if _kind(label) == "guard"]
        if not any(guard_trust.get(label) == GUARD_TRUSTED for label in guard_labels):
            return EVIDENCE_WEAK
    if any(_kind(label) not in _SCORER_LABEL_WEIGHTS for label in labels):
        return EVIDENCE_FAST_PATH
    if not message.isascii():
        return EVIDENCE_NON_ASCII_EXEMPT
    if any(guard_trust.get(label) == GUARD_TRUSTED for label in labels if _kind(label) == "guard"):
        return EVIDENCE_TRUSTED_GUARD
    phrases = phrase_count(labels)
    # The non-ASCII exemption above must stay ahead of this branch:
    # `reads_as_a_request` reads Latin words only and returns False for a
    # message with none, which would strip every Korean or Japanese cadence
    # phrase (`매일 아침`) of its evidence.
    if phrases and not reads_as_a_request(message):
        # A cadence phrase says when, never what: `every morning` is the
        # skill's own phrase in a request and a habit in a report. Without a
        # request shape it is not a phrase the skill can dispatch on.
        phrases -= sum(1 for label in labels if _kind(label) == "trigger" and is_cadence_phrase(_value(label)))
    if phrases:
        own = own_evidence_score(labels)
        if not any(
            int(other.get("score", 0) or 0) > 0
            and phrase_count(_labels(other)) >= phrases
            and own - own_evidence_score(_labels(other)) < PHRASE_LEAD
            for other in others
        ):
            return EVIDENCE_TRIGGER_PHRASE
    return EVIDENCE_WEAK


__all__ = [
    "EVIDENCE_DIRECT",
    "EVIDENCE_EXPLICIT",
    "EVIDENCE_FAST_PATH",
    "EVIDENCE_NON_ASCII_EXEMPT",
    "EVIDENCE_TRIGGER_PHRASE",
    "EVIDENCE_TRUSTED_GUARD",
    "EVIDENCE_WEAK",
    "GUARD_TRUSTED",
    "OWN_EVIDENCE_FLOOR",
    "PHRASE_LEAD",
    "dispatch_evidence",
    "has_own_phrase",
    "phrase_count",
    "own_evidence_score",
]
