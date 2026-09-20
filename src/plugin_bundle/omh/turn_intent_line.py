"""The one line that asks a reply to open by saying what it is about to do.

The request, in the owner's words: the spinner cycles verbs so you can see
that the model is working, but nothing says WHAT it is working on, so a long
turn is opaque until it ends. They asked for one or two lines up front --
what was understood, and what will be looked at first -- and asked whether
OMH was suppressing such a rule. It was not, and the sweep that says so is
worth stating precisely rather than as "nothing found". Searching this
bundle and `src/skills/` for preamble, terseness and narration instructions
returns exactly one hit, and it is not a suppression: the interview skill's
body in `src/skills/render.py` fixes the shape of a clarifying QUESTION --
"one sentence, no preamble, no restating what the user just said" -- inside
a document the model must already have chosen to load. Nothing always-on
says anything in either direction. The behaviour was unasked-for, not
suppressed.

That one hit is also the only place this rule can collide with an OMH text,
and the collision is narrow: the skill governs the question sentence, this
governs how the reply opens, and a reply can carry an orientation line and
then the skill's header and question. No carve-out is written for it,
because a third clause here would be paid on every turn this fires to
settle a case that arises only inside one skill.

Four properties, and the third is the one that decides the shape.

Who gets it. Only a turn a PERSON opened, through `turn_opened_by_person` --
both halves records, neither of them the message's wording. Hermes opens
turns for its own rows too (a background process finishing, an async
delegation batch, a model switch), and a reply to a notice has no request to
restate. A delegated child is excluded the same way `engagement_nudges`
excludes one, off `subagent_start`'s `child_session_id`: a child answers its
orchestrator rather than a person, and an opening line it wrote would be read
by nobody.

What it costs. `TURN_INTENT_LINE_TURNS` person-opened turns per session and
then never again -- the same shape and the same number as
`TODO_RECONCILIATION_FULL_TURNS` next door. The budget is not a refinement,
it is the whole reason this is affordable: the audit behind
`tests/test_injected_context_pressure.py` measured one un-budgeted sentence
at 14,280 characters of a single 40-turn session, and a line asking for a
per-turn habit is exactly the shape that would repeat that. Three is also
where the instruction stops being the only thing arguing for itself: Hermes
replays each turn's `api_content` verbatim, so by the fourth person turn the
model is reading three copies of this rule and whatever it actually did on
those turns, which is a stronger prior than a fourth copy would be.

Why it cannot latch, which is the difference from every neighbour. The plan
nudge latches on a declared plan and the delegation nudge on a routed lane,
because each has a RECORD saying the thing happened. The only thing that
would end this one is the model actually opening a reply that way, and that
is prose: OMH can neither read it nor claim it. So the budget decays, and its
number is a cost decision rather than a measurement. Nothing here and nothing
in the hook's payload reports that a briefing was given.

Why there is no "is this turn big enough" gate. No record available at
`pre_llm_call` time says a turn will be long. The only thing that correlates
is the message's wording, which is the inference #1549 removed from the plan
surface for being wrong in both directions, and which the first-turn primer
beside this one already declined for the same reason -- "judging 'big enough'
is the same guess that is already failing here, and the largest request in
that set is one of the misses". So a one-line question does pay for this, at
most `TURN_INTENT_LINE_TURNS` times in a session, and that bound is the
answer instead of a heuristic.

English, like every other string this bundle injects. The locale packs in
`routing/localization` normalize the INBOUND message so triggers match in
ko/ja/zh; nothing OMH sends outbound to the model is translated, and this
text is addressed to a model rather than to a person.
"""

from __future__ import annotations

from .hooks.nudge_budget import (
    INTENT_LINE_TURNS_FIELD,
    bump_engagement_count,
    engagement_count,
    session_is_delegated,
)
from .turn_authorship import turn_opened_by_person

# A head, because the fence's own contract says so: what this hook returns is
# concatenated onto the API copy of the user's message, and the two blocks in
# this bundle that carry no `[OMH ...]` head are named in
# `tests/test_injected_context_pressure.py` as the reason the fence had to be
# added at all.
TURN_INTENT_LINE_HEAD = "[OMH Turn Opening]"

# Two sentences, addressed to a model, saying what to do and not why.
#
# What each clause is holding off. "this reply" rather than "every reply",
# because this arrives on some turns and not others and a rule that claimed
# otherwise would be false the moment the budget ran out. "short lines"
# because the ask is a sentence of orientation, not a plan document -- there
# is a plan surface and this is not it. "without waiting for an answer"
# because the failure mode of every restate-the-request instruction is a
# model that stops and asks whether it understood correctly, which is the
# opposite of what was asked for: the person wanted to see the work start,
# not to be given a checkpoint.
TURN_INTENT_LINE_RULE = (
    "Open this reply with one or two short lines: what you understood the "
    "request to be, and the first thing you will do about it. Then continue "
    "in the same reply without waiting for an answer."
)

TURN_INTENT_LINE = f"{TURN_INTENT_LINE_HEAD}\n{TURN_INTENT_LINE_RULE}"

# Person-opened turns per session that carry the rule. Deliberately not
# imported from `TODO_RECONCILIATION_FULL_TURNS`: the two agree today and
# have no reason to move together, and a shared constant would make one
# budget's revision silently revise the other's.
TURN_INTENT_LINE_TURNS = 3


def turn_intent_line(
    *,
    user_message: object,
    turn_display_kind: object = "",
    session_id: object = "",
    omh_home: str = "",
) -> str:
    """The opening-line rule for this turn, or `""` when none is owed.

    Every gate below is a record: who opened the turn, whether the host
    called this session a delegated child, and how many times this session
    has already been told. What the message SAYS is never consulted, and two
    messages with opposite meanings produce the identical answer.

    Spends one turn of the budget whenever it returns the rule, so the caller
    must be the once-per-turn hook: `pre_llm_call`, which Hermes invokes
    exactly once per turn from `build_turn_context`. That obligation rests on
    there being one caller rather than on a flag, which is the difference
    from `open_todo_reminder` next door -- it is also a read for anyone
    inspecting a plan out of band, so it had to be able to answer without
    counting, and this has no such reader. A second caller here would be a
    budget spent on something that is not a turn.
    """
    if not turn_opened_by_person(user_message, turn_display_kind):
        return ""
    # A session with no usable id holds no budget -- `bump_engagement_count`
    # refuses to share a row rather than measure one session's spend against
    # another's -- and the budget is the only thing that makes this line
    # affordable. So an unnamed session gets nothing instead of getting it on
    # every turn forever, which is the direction every budget in
    # `nudge_budget` fails in and the only case here where the other
    # direction is unbounded.
    session = session_id.strip() if isinstance(session_id, str) else ""
    if not session:
        return ""
    if session_is_delegated(session):
        return ""
    if (
        engagement_count(session, INTENT_LINE_TURNS_FIELD, omh_home=omh_home)
        >= TURN_INTENT_LINE_TURNS
    ):
        return ""
    _ = bump_engagement_count(session, INTENT_LINE_TURNS_FIELD, omh_home=omh_home)
    return TURN_INTENT_LINE
