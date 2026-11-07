"""Hand an undecidable route to model selection instead of degrading it.

The deterministic router resolves confident requests well, and it should keep
doing that. What it does badly is the undecided case. Measured on a 24-message
natural-language sample, 8 turns ended in a picker and 2 in a bare fallback,
and 6 produced a score tie the scorer could not break. A user who wrote "PR
리뷰 좀 해줘" got a picker because two skills scored 9 apiece; a user who wrote
"ビルドが失敗した理由を教えて" got nothing because the trigger tables carry no
Kana. In both cases the router had the information needed to shortlist, and
threw it away to ask the user to do the routing instead.

This module turns that dead end into a handoff. When the route is undecidable,
OMH emits the candidates it did find -- each with the reason it matched, its
next action, and its evidence boundary -- and asks the model to choose. Hermes
already understands every language OMH targets and can read a shortlist of four
descriptions; that is the part it is good at.

OMH makes no LLM call here. It assembles candidates and a question; the
selection happens in Hermes. `docs/DIRECTION.md`'s "not an LLM router" boundary
holds, and the payload stays reproducible: the same message yields the same
candidate set and the same digest, so a routing decision remains auditable.
"""

from __future__ import annotations

import hashlib

from .domain_signals import (
    RELEVANCE_POLICY,
    ClarificationRelevance,
    classify_clarification_relevance,
)
from .dispatch_evidence import OWN_EVIDENCE_FLOOR, offered_ahead_of_words, own_evidence_score
from .input_language import SUPPORT_MODEL_SELECTION_REQUIRED
from .lexical_shortlist import LEXICAL_SCORE_FLOOR, lexical_anchor_terms, lexical_ranking, only_held_back_overlap
from .policy import skill_is_negated
from .query import RoutingQuery
from .recommend import recommendation_for_definition
from ..skills.catalog import routable_definitions
from ..workflows.hermes_planning import is_coding_shaped_task


CANDIDATE_HANDOFF_SCHEMA_VERSION = "model_selection_candidates/v1"

# The workflows that actually deliver implementation work. Observed live: an
# implementation-shaped request ("...백엔드 구현해줘") reached model selection
# carrying instinct-ledger, materials-package, and memory-new at score 3 --
# decomposed-token noise -- while the picker in the same session offered
# idea-to-deploy and planning flows. The engines that do the work (ultraprocess,
# team, ultragoal) never surfaced, because nothing connected "this is coding"
# to "these are the coding candidates".
CODING_LANE_CANDIDATES = (
    ("ultrawork", "prepare_coding_handoff"),
    ("executor-runtime-readiness", "check_executor_readiness"),
)

# Matches the router's own specific-capability minimum: below this, a match is
# decomposition noise, not a signal worth showing over the coding lane.
CODING_LANE_SCORE_FLOOR = 6

# Below this score gap the scorer is not discriminating between the top two
# candidates, it is picking one arbitrarily. Measured ties (gap 0) and near-ties
# (gap 1) both produced wrong winners on the sample corpus.
DECIDING_SCORE_GAP = 5

MAX_CANDIDATES = 4

REASON_LOW_CONFIDENCE = "low_confidence"
REASON_NARROW_SCORE_GAP = "narrow_score_gap"
REASON_NO_TRIGGER_COVERAGE = "no_trigger_coverage"
# A high score the winner's own labels do not account for; see
# `routing/dispatch_evidence.py`. The route carries it as `ambiguity_kind`.
WEAK_DISPATCH_EVIDENCE = "weak_dispatch_evidence"

# A clarify shortlist keeps at most this many scored candidates, and only ones
# whose own labels reach `OWN_EVIDENCE_FLOOR` (one trigger phrase or two
# trigger tokens). A scored candidate below it is the everyday-word overlap the
# dispatch gate refused; its slot goes to the lexical ranking, which reads the
# catalog's situations and descriptions instead of the trigger tables.
MAX_SCORED_CANDIDATES = 2
# Where a handoff's candidates came from: the scored field alone, or scored
# candidates with evidence of their own followed by the lexical ranking.
SHORTLIST_SCORED = "scored"
SHORTLIST_LEXICAL = "scored_then_lexical"
SCORED_OWN_EVIDENCE_FLOOR = OWN_EVIDENCE_FLOOR
LEXICAL_WHY = (
    "Shares content words with this workflow's situations, triggers, and description; "
    "a lexical shortlist entry, not a trigger match."
)

CLAIM_BOUNDARY = (
    "A candidate set is routing input for model selection, not a routing decision. "
    "It is not execution, review, CI, merge, or evidence that any candidate ran."
)

_UNDECIDED_ACTIONS = ("clarify", "fallback")


def _score_gap(recommendations: list[dict[str, object]]) -> int | None:
    if len(recommendations) < 2:
        return None
    return int(recommendations[0].get("score", 0) or 0) - int(recommendations[1].get("score", 0) or 0)


def candidate_handoff_reasons(route: dict[str, object]) -> tuple[str, ...]:
    """Why this route cannot be decided deterministically, in stable order."""
    if str(route.get("action", "")) not in _UNDECIDED_ACTIONS:
        return ()

    reasons: list[str] = []
    if str(route.get("ambiguity_kind", "")) == WEAK_DISPATCH_EVIDENCE:
        reasons.append(WEAK_DISPATCH_EVIDENCE)
    input_language = route.get("input_language")
    if isinstance(input_language, dict):
        if input_language.get("trigger_support") == SUPPORT_MODEL_SELECTION_REQUIRED:
            reasons.append(REASON_NO_TRIGGER_COVERAGE)

    recommendations = [item for item in route.get("recommendations", []) if isinstance(item, dict)]
    gap = _score_gap(recommendations)
    if gap is not None and gap < DECIDING_SCORE_GAP:
        reasons.append(REASON_NARROW_SCORE_GAP)
    if str(route.get("confidence", "")) == "low":
        reasons.append(REASON_LOW_CONFIDENCE)
    return tuple(reasons)


def _coding_lane_applies(candidates: list[dict[str, object]], message: str) -> bool:
    """Should the coding lane replace what scoring found?

    Only when the message is implementation-shaped AND every scored candidate
    is below the floor. A strong match -- memory-sync at 31, ultraprocess at a
    real trigger score -- keeps its shortlist; the lane replaces noise, never
    signal.
    """
    if not message or not is_coding_shaped_task(message):
        return False
    return all(int(candidate.get("score", 0) or 0) < CODING_LANE_SCORE_FLOOR for candidate in candidates)


def _coding_lane() -> list[dict[str, object]]:
    definitions = {definition.name: definition for definition in routable_definitions()}
    lane: list[dict[str, object]] = []
    for name, next_action in CODING_LANE_CANDIDATES:
        definition = definitions.get(name)
        if definition is None:
            continue
        lane.append(
            {
                "skill": definition.name,
                "description": definition.description,
                "reasoning_demand": definition.reasoning_demand,
                "why_it_matched": (
                    "The request is implementation-shaped; this is one of the workflows that "
                    "actually delivers coding work."
                ),
                "matched": ["coding_shaped_task"],
                "score": 0,
                "confidence": "low",
                "next_action": next_action,
                "evidence_boundary": (
                    "A candidate is routing input only; nothing has been planned, dispatched, "
                    "implemented, or verified."
                ),
            }
        )
    return lane[:MAX_CANDIDATES]


def _domain_candidate(skill: str, message: str) -> dict[str, object] | None:
    definition = next((item for item in routable_definitions() if item.name == skill), None)
    if definition is None:
        return None
    recommendation = recommendation_for_definition(
        definition,
        message,
        matched=(f"domain:{definition.name}",),
        score=0,
        why="The request and candidate share a canonical specialist-domain signal.",
    )
    return _candidate(recommendation)


def _relevant_candidates(
    candidates: list[dict[str, object]],
    relevance: ClarificationRelevance,
    message: str,
) -> list[dict[str, object]]:
    relevant_skills = relevance.skills
    if relevant_skills is None:
        return candidates
    by_skill = {str(candidate.get("skill") or ""): candidate for candidate in candidates}
    relevant: list[dict[str, object]] = []
    for skill in relevant_skills:
        candidate = by_skill.get(skill) or _domain_candidate(skill, message)
        if candidate is not None:
            relevant.append(candidate)
    return relevant[:MAX_CANDIDATES]


def _lexical_shortlist(
    recommendations: list[dict[str, object]], message: str, *, declined_dispatch: bool = False, shielded: bool = False
) -> list[dict[str, object]]:
    """The declined winner, scored candidates with evidence of their own, then lexical ranks.

    Only for a `clarify`: the router already decided it cannot dispatch, and
    the shortlist is what Hermes chooses from. After a declined dispatch the
    declined winner always leads, whatever its own-evidence score. The first
    entry becomes the route's `candidate_skill`. A `jev-*` skill never enters by word overlap --
    it sends data off the machine and is reached only through
    `routing/jev_addressing.py`.
    """
    candidates: list[dict[str, object]] = []
    for index, recommendation in enumerate(offered_ahead_of_words(recommendations)):
        if len(candidates) >= MAX_SCORED_CANDIDATES:
            break
        labels = recommendation.get("matched")
        if skill_is_negated(message, str(recommendation.get("skill") or "")):
            continue
        # The winner the gate declined to dispatch always leads: the router
        # was confident in it, and declining means asking, not dropping it.
        own = own_evidence_score([str(label) for label in labels or ()])
        declined_winner = declined_dispatch and index == 0 and int(recommendation.get("score", 0) or 0) > 0
        if declined_winner or own >= SCORED_OWN_EVIDENCE_FLOOR:
            candidates.append(_candidate(recommendation))
    named = {str(candidate.get("skill") or "") for candidate in candidates}
    definitions = {definition.name: definition for definition in routable_definitions()}
    # Built on the first skill that needs it, then shared by every later one.
    query: RoutingQuery | None = None
    for skill, score in lexical_ranking(message):
        if len(candidates) >= MAX_CANDIDATES or score < LEXICAL_SCORE_FLOOR:
            break
        definition = definitions.get(skill)
        # A skill the user named in order to decline it ("don't use ultraqa")
        # is not offered back.
        if definition is None or skill in named or skill.startswith("jev-") or skill_is_negated(message, skill):
            continue
        # A skill whose only shared words are an everyday-English phrase of
        # its own is not offered back by word overlap either; see
        # `EVERYDAY_SENSE_PHRASES` in `policy.py`.
        query = query or RoutingQuery.from_message(message, shielded=shielded)
        if query.everyday_sense_withheld(skill):
            continue
        # After a declined dispatch the ranking is admitted as it stands --
        # the router was confident enough to have dispatched, and the ranking
        # is what corrects it -- except a skill whose only shared words are
        # ones the router credits to it only inside a whole phrase
        # ("large pdf" is not long-document-reading). An ordinary clarify
        # also needs an anchor word and the skill's offers-itself precondition.
        if declined_dispatch:
            if only_held_back_overlap(message, skill) or query.offers_itself_withheld(skill):
                continue
        elif not lexical_anchor_terms(message, skill) or query.offers_itself_withheld(skill):
            continue
        named.add(skill)
        candidates.append(
            _candidate(
                recommendation_for_definition(
                    definition,
                    message,
                    matched=("lexical_shortlist",),
                    score=0,
                    why=LEXICAL_WHY,
                )
            )
        )
    return candidates


def _situation(description: object) -> str:
    """The situation a skill's description opens on: "[omh] <situation>: <output>"."""
    text = str(description or "").removeprefix("[omh]").strip()
    head, colon, _rest = text.partition(":")
    return head.strip() if colon else text


def shortlist_clarification(candidates: list[dict[str, object]]) -> str:
    """One plain instruction for the model: pick the workflow the user's situation fits.

    Each candidate is named with the situation its description opens on, so the
    model compares situations rather than skill names it may not know.
    """
    options = "; ".join(
        f"`{candidate.get('skill')}` ({_situation(candidate.get('description'))})"
        for candidate in candidates
        if candidate.get("skill")
    )
    return (
        f"Pick the workflow whose situation matches what the user described: {options}. "
        "If one clearly fits, use it; if two could, ask the user one short question that names both; "
        "if none fits, answer directly without a workflow."
    )


def _candidate(recommendation: dict[str, object]) -> dict[str, object]:
    return {
        "skill": recommendation.get("skill"),
        "description": recommendation.get("description"),
        "reasoning_demand": _candidate_reasoning_demand(recommendation),
        "why_it_matched": recommendation.get("why"),
        "matched": list(recommendation.get("matched", []) or []),
        "score": recommendation.get("score"),
        "confidence": recommendation.get("confidence"),
        "next_action": recommendation.get("next_action"),
        "evidence_boundary": recommendation.get("evidence_boundary"),
    }


def _candidate_reasoning_demand(recommendation: dict[str, object]) -> str:
    value = recommendation.get("reasoning_demand")
    if value in {"light", "standard", "heavy"}:
        return str(value)
    skill = str(recommendation.get("skill") or "")
    return next(
        (definition.reasoning_demand for definition in routable_definitions() if definition.name == skill),
        "standard",
    )


def candidate_handoff_digest(candidates: list[dict[str, object]], reasons: tuple[str, ...]) -> str:
    """Reproducible identity for this candidate set.

    Keyed on the candidate skills and the reasons, not on scores, so the digest
    survives score tuning while still changing when the shortlist changes.
    """
    # Joined fields, not json.dumps: this now runs inside the public payload
    # path, and the efficiency contract forbids JSON serialization during the
    # quality demos that walk every routing case. The identity content is
    # unchanged -- schema version, reasons, skills, in order -- and the unit
    # separator cannot occur in any of them.
    encoded = "\x1f".join(
        [
            CANDIDATE_HANDOFF_SCHEMA_VERSION,
            *[str(reason) for reason in reasons],
            *[str(candidate.get("skill")) for candidate in candidates],
        ]
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_candidate_handoff(
    route: dict[str, object],
    message: str = "",
    *,
    relevance: ClarificationRelevance | None = None,
    shielded: bool = False,
) -> dict[str, object] | None:
    """Build the model-selection handoff, or None when the route is decidable."""
    if relevance is None:
        relevance = classify_clarification_relevance(message)
    reasons = candidate_handoff_reasons(route)
    if (
        not reasons
        and relevance.applies
        and str(route.get("action") or "") in _UNDECIDED_ACTIONS
    ):
        reasons = ("domain_relevance_required",)
    if not reasons:
        return None

    recommendations = [item for item in route.get("recommendations", []) if isinstance(item, dict)]
    scored = [_candidate(recommendation) for recommendation in recommendations[:MAX_CANDIDATES]]
    # The lexical index is English catalog text. A non-ASCII request keeps the
    # scored shortlist: the Routing Language Policy leaves its intent to the
    # frozen trigger tables and to model selection, not to English word overlap.
    lexical = str(route.get("action") or "") == "clarify" and message.isascii()
    candidates = (
        _lexical_shortlist(
            recommendations, message, declined_dispatch=WEAK_DISPATCH_EVIDENCE in reasons, shielded=shielded
        )
        if lexical
        else scored
    )

    if _coding_lane_applies(scored, message):
        lane = _coding_lane()
        if lexical:
            # The lane leads; the lexical ranks keep the remaining slots, so a
            # request whose situation names a specialist skill still offers it
            # beside the delivery engines.
            lane_skills = {str(candidate.get("skill") or "") for candidate in lane}
            candidates = [*lane, *[c for c in candidates if c.get("skill") not in lane_skills]][:MAX_CANDIDATES]
        else:
            candidates = lane
        reasons = (*reasons, "implementation_shaped_request")

    candidates = _relevant_candidates(candidates, relevance, message)
    selection_mode = "candidate_selection" if candidates else "open_clarification"
    payload: dict[str, object] = {
        "schema_version": CANDIDATE_HANDOFF_SCHEMA_VERSION,
        "selection_mode": selection_mode,
        "relevance_policy": RELEVANCE_POLICY,
        "reasons": list(reasons),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "shortlist_source": SHORTLIST_LEXICAL if lexical else SHORTLIST_SCORED,
        "selector": "hermes",
        "digest": candidate_handoff_digest(candidates, reasons),
        "claim_boundary": CLAIM_BOUNDARY,
    }

    if "implementation_shaped_request" in reasons:
        payload["question"] = (
            "The request is implementation-shaped but no workflow matched strongly. The leading "
            "candidates are the coding-delivery workflows; choose the one that fits the delivery grain, or ask "
            "one clarifying question. Do not route implementation work to planning-only flows."
        )
    elif candidates:
        payload["question"] = (
            "Which of these workflows fits the request? Choose one, say why in one line, "
            "and carry its evidence boundary forward. If none fit, ask one clarifying question."
        )
    elif relevance.applies:
        payload["question"] = (
            "No relevant candidate shares a canonical domain signal with this request. "
            "Ask what outcome the user wants, or present the workflow picker without naming a skill."
        )
    else:
        payload["question"] = (
            "No deterministic candidate matched this request. Shortlist from the installed "
            "`references/catalog-index.md`, confirm with a bounded `omh recommend` query, and "
            "name the chosen workflow with its evidence boundary."
        )
        payload["catalog_reference"] = "references/catalog-index.md"

    return payload
