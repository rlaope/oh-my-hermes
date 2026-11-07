"""Per-turn text budgets: each slot's character limit, its history, and its text.

A slot is OMH text the host can send the model on a turn: the awareness
primer (`primer`, and the markdown form `primer_markdown`), a workflow's
awareness context (`workflow_context`), a role context (`role_context`), and
the fenced `pre_llm_call` context, on a host that rendered the awareness
system prompt section (`pre_llm_call`) and on one that did not
(`pre_llm_call_fallback`). The limit for each lives here with the history of
every change to it, next to the bundle text it bounds, so a wording edit and
the budget it spends are read in one module.

The limits are re-exported from `src/maintenance/release.py` under the same
names and listed in `budget_metrics()` (`src/maintenance/drift.py`). Measuring
stays in the control plane: `src/maintenance/per_turn_context.py` runs the
named `pre_llm_call` scenarios and reports every slot's live size and
headroom (`budget_report()`, `headroom()`), because the workflow and role
contexts are enumerated from the skill and role catalogs, which this bundle
cannot import. `render()` is the seam for the slots whose text is the same on
every turn; the hooks reach the primer through it.

This module imports nothing from `omh` (`tests/test_plugin_bundle_standalone.py`).
"""

from __future__ import annotations

from .awareness import awareness_primer_context, awareness_primer_markdown

# 900 -> 1050 and 3210 -> 3400: the primers gain one line about the reply
# itself -- written in the user's words and the host's own voice, with these
# lines and OMH's record vocabulary never quoted to the user. The compact
# rail measured 897 and the markdown 3168 before the line; a model that
# echoed the rail produced replies such as "this is an evidence-bounded
# surface", and the persona belongs to the host's SOUL.md. Re-derived from
# the producers (1044 and 3316 measured, after the review's carve-out for a
# user who asks about a term) with standing headroom restored.
# 1050 -> 1260: one line scoping OMH's own skills to work the user asks for
# and naming the everyday questions that need none. Measured live (GPT-6
# Luna, one turn per message, 2026-09-26) an everyday message loaded an OMH
# skill 39-59% of the time on main; the index lists skills such as
# `omh-live-info` and `omh-decide` whose words match everyday chat. The
# compact rail measured 1253 after the line (re-derived from the producer,
# standing headroom kept as above). Paid once per session, in the system
# prompt section.
# 1260 -> 1440 and 3400 -> 3520: the reply line names what the persona owns
# -- the reply language, tone, speech level and sentence endings, progress
# updates included, with the user's language only where the persona sets
# none -- and says OMH shapes structure and content only. "The
# host's own voice" alone named none of them, and a casual-register Korean
# persona (miku, deepseek-v4.1-flash-ultrafast, 2026-09-30) kept its voice in
# the final answer while 13 of 17 interim progress lines in one session came
# out in English. The compact rail measured 1434 and the markdown 3509
# (re-derived from the producers, standing headroom kept as above).
# 1440 -> 1560 and 3520 -> 3630: the reply line gains one sentence carrying the
# human-voice pass into every session (result first, no chatbot openers or
# closers, staged contrasts, or decoration); the full pass is the on-demand
# `omh-routing/references/human-voice.md`. Owners read OMH-guided replies that
# opened with praise and closed with offers while the persona held. The compact
# rail measured 1550 and the markdown 3619 (re-derived from the producers,
# standing headroom kept as above).
# 3630 -> 3685: the markdown's generic-tool checkpoint names each skill by its
# full catalog name (`accessibility-audit`, not `a11y`), because the shorthand
# was nothing a model could load. It measured 3677 (standing headroom kept as
# above); the compact rail does not carry the line.
# 3685 -> 3734: the same line writes each target as the label `skill_view`
# loads (`omh-accessibility-audit`, `ulw-research`), because a catalog name
# reaches the model through this primer with no render pass and is not a name
# it can load either. It measured 3726 (standing headroom kept as above).
AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT = 1560
AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT = 3734
AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT = 1500
ROLE_CONTEXT_CHAR_LIMIT = 2600
# Per-request budgets, zero-slack: each is the value its producer measured,
# and moves only with the reason written beside it.
# The largest fenced `pre_llm_call` context over the named scenario set in
# `src/maintenance/per_turn_context.py` (the `all_surfaces` scenario). Hermes
# replays each turn's injection from `api_content` on every later turn, so this
# accumulates in history. `AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT` above still
# bounds the primer alone.
# 6260 -> 5214: the awareness primer (1044 chars plus its "\n\n" join) leaves
# the fenced context for the `omh.awareness` system prompt section, which
# every admitted host (Hermes >= 0.20.2) freezes into a new session's system
# prompt. The scenarios now measure that host; the primer's own limit above
# bounds the section, far under the host's 4,000-char per-section cap.
# Re-derived from the producer.
# 5214 -> 5544: the skill candidate line (`skill_shortlist.py`), up to three
# skills named with their situations on a turn whose request reads as work.
# The routed request in `all_surfaces` gets one too (the line stands down only
# for a workflow the person named), +330. Measured live, the line took the
# intended-skill load from 78% to 90% (own work set) and 69% to 95% (tuning
# work set). Per-turn cost: about 330-470 characters (the `skill_candidates`
# scenario is 468 with the fence), paid on a turn whose request reads as work
# and whose candidate set differs from the last one this session was shown;
# a repeat of the same set costs nothing. Re-derived from the producer.
# 5544 -> 5647: the line names the exact call form, skill_view(name="...")
# with no category prefix, because a model that guesses the category
# (`operator/omh-x` for a skill filed under `reviewer/`) gets "not found";
# Hermes does resolve a correct `category/name` in external dirs (+103). The line is now about 430-580 characters on a turn that
# carries it. Re-derived from the producer.
# 5647 -> 5662: the work-context skill openings reach the route hint's
# context card (+15 on the routed request). Re-derived from the producer.
# 5662 unchanged: the `done_unverified_plan` scenario joins the set so the plan
# line's evidence clause and `TODO_EVIDENCE_RULE` are measured (1044 on a turn
# a finished background process opened). It is under `all_surfaces`, which
# still sets the maximum, and the fallback maximum is unchanged with it.
# Re-derived from the producer.
# 5662 -> 5781: the route hint's `plan_todo` line now says which ONE tool holds
# the run's steps -- omh_todo for a planning run or an accepted plan, else
# Hermes' todo_list where it is present (OMH mirrors it), else omh_todo (+119
# on the routed request, after dropping its "so the Hermes TUI shows the
# person" clause). It rides only a turn routed to one of the six checklist
# workflows. The alternative, leaving it naming omh_todo alone, is how a
# session came to declare one plan in both tools. The plan line's
# reconciliation clause stopped naming omh_todo and the evidence rule started
# (one +14, one -14), so the `done_unverified_plan` scenario is unchanged.
# Re-derived from the producer.
# 5781 unchanged: the `held_native_write` scenario joins the set so the
# one-time line a held todo_list write leaves for the next turn is measured
# beside the plan line (1180). It is under `all_surfaces`, which still sets
# the maximum, and the fallback maximum is unchanged with it. Re-derived from
# the producer.
# 5781 -> 5780: the `plan_todo` line names all three plans only omh_todo can
# hold -- a planning run, an accepted plan or a code-story template
# (`OMH_TODO_HELD_PLANS`, the set a native write is held for) -- so a
# checklist workflow such as `ultraqa` running a code-story template is no
# longer pointed at todo_list, whose write would then be held. Its "(they
# carry plan_stage)" reason is dropped to pay for the third plan (-1 on the
# routed request). Re-derived from the producer.
# 5780 -> 5786: the pi-family runtime's profile was renamed, and the routed
# coding handoff policy names it in its runtime list ("OMX/pi-family/OMC",
# +6). Re-derived from the producer.
# 5786 -> 5632 (2026-10-28): the route hint stops repeating itself. A hint's
# `adjacent_workflows=` line equal to the block's top-level one is dropped
# (-81 on the routed request's largest role, `handoff-guide`), and a
# fallback label that only respells the action's underscores is dropped
# (-73). Re-derived from the producer.
# 5632 unchanged: the `plan_acceptance` scenario joins the set so the plan
# follow-on line (`plan_follow_on`, 479 with its join) is measured on the turn
# that accepts a plan Hermes' `/plan` just wrote, beside the route hint and
# the active plan line (2759). It rides at most once per plan made, and on
# `/plan`'s own turn (410 fenced alone), so it is under `all_surfaces`, which still sets the maximum,
# and the fallback maximum is unchanged with it. Re-derived from the producer.
# 5632 -> 6041 (2026-11-05): the console choices line (`console_choices`, 407
# plus its join) asks a console session (cli, tui, desktop) to put a choice
# its reply stops on through Hermes' `clarify` picker rather than a prose
# list, with its context in the reply text, a one-sentence question and
# `label — clause` choices the TUI draws as a label and a dim description. It
# rides the session's first turn, so `all_surfaces` now runs as a
# console session's first turn (`platform="tui"`) and carries it (+409); a
# messaging platform's turn renders exactly what it rendered before. Its
# re-ask variant (255) rides only the person's turn after a clarify timed
# out, measured alone by the new `clarify_timed_out` scenario (374 fenced),
# under `all_surfaces`. Re-derived from the producer.
# 6041 -> 5977: the delegation prompt rule drops its rationale tail (-64) in the coding-core audit round.
PRE_LLM_CALL_CONTEXT_CHAR_LIMIT = 5977
# The same scenario set on the fallback: a session the awareness section did
# not render for (a restart resume, a legacy id-rotating compaction, a refused
# section, an older host) still gets the primer in the fenced context, so its
# largest turn is `all_surfaces_without_section`. Landed at the value the
# producer measured (6260, the pre-section ceiling), so the fallback cannot
# grow unseen behind the lower section-host limit above.
# 6260 -> 6799: the candidate line above (+330) and the primer's scope line
# (+209 with its join), which rides the fenced context on this fallback.
# Re-derived from the producer.
# 6799 -> 6902: the same exact-call-form wording (+103). Re-derived from the
# producer.
# 6902 -> 6917: the same +15 from the work-context openings. Re-derived
# from the producer.
# 6917 -> 7098: the primer's reply line, replaced in place, now gives the
# persona the reply language, speech level, endings, and progress updates,
# with the user's language as the fallback (+193 measured, 6905 -> 7098), and
# it rides the fenced context on this fallback. The 12 characters of slack
# main carried are absorbed, so the ceiling is zero-slack again. The
# section-host limit above does not move: nothing new is injected per turn
# there. Re-derived from the producer.
# 7098 -> 7217: the same `plan_todo` wording (+119). Re-derived from the
# producer.
# 7217 -> 7216: the same `plan_todo` change (-1). Re-derived from the
# producer.
# 7216 -> 7222: the same runtime-list rename (+6). Re-derived from the
# producer.
# 7222 -> 7338: the primer's reply line gains its human-voice sentence (+116),
# and it rides the fenced context on this fallback. The section-host limit
# above does not move. Re-derived from the producer.
# 7338 -> 7184 (2026-10-28): the same route-hint dedup (-154). Re-derived
# from the producer.
# 7184 -> 7593 (2026-11-05): the same console choices line on the same
# console first turn (+409). Re-derived from the producer.
# 7593 -> 7529: the same rule, same -64.
PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT = 7529

SLOT_LIMITS: dict[str, int] = {
    "primer": AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
    "primer_markdown": AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
    "workflow_context": AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
    "role_context": ROLE_CONTEXT_CHAR_LIMIT,
    "pre_llm_call": PRE_LLM_CALL_CONTEXT_CHAR_LIMIT,
    "pre_llm_call_fallback": PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT,
}

# The slots `render()` produces: their text does not depend on the turn.
RENDERED_SLOTS = ("primer", "primer_markdown")


def render(surface: str) -> str:
    """The text of a slot whose text is the same on every turn."""
    if surface == "primer":
        return awareness_primer_context()
    if surface == "primer_markdown":
        return awareness_primer_markdown()
    raise KeyError(f"no rendered text for slot {surface!r}; rendered slots: {', '.join(RENDERED_SLOTS)}")


__all__ = [
    "AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT",
    "AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT",
    "AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT",
    "PRE_LLM_CALL_CONTEXT_CHAR_LIMIT",
    "PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT",
    "RENDERED_SLOTS",
    "ROLE_CONTEXT_CHAR_LIMIT",
    "SLOT_LIMITS",
    "render",
]
