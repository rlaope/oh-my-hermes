from __future__ import annotations

from .loopability import assess_loopability


GOAL_QUALITY_COACHING_CARD_SCHEMA = "goal_quality_coaching_card/v1"
_UPSTREAM_GOAL_DEFAULT_MAX_TURNS = 20
_GOAL_CLASSIFIED_MIN_UNCLEAR_LENGTH = 12


def is_goal_classified_message(message: str) -> bool:
    """True when this message reads as an open-ended goal rather than a bounded
    direct task or a pure external-wait request.

    Reuses `workflows.loopability.assess_loopability` -- the same classifier
    OMH's own /loop routing already relies on to decide whether a chat message
    is goal-shaped -- instead of re-implementing goal detection here. The
    ambiguous "no signal at all" bucket (loopability needs_reframe with
    goal_kind project) is intentionally excluded to avoid flagging ordinary
    short questions as goals.
    """
    text = str(message).strip()
    if not text:
        return False
    try:
        assessment = assess_loopability(text, expose_goal=False)
    except ValueError:
        return False
    loopability = str(assessment.get("loopability", ""))
    goal_kind = str(assessment.get("goal_kind", ""))
    if loopability == "loopable":
        return True
    if loopability == "needs_reframe" and goal_kind == "ambition":
        return True
    if loopability == "needs_clarification" and goal_kind == "unclear":
        return len(text) >= _GOAL_CLASSIFIED_MIN_UNCLEAR_LENGTH
    return False
