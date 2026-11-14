"""The live region's height budget and the order its parts stack in.

Top to bottom the region holds:

    streaming tail  the last rows of the live transcript block
    pad rows        blank rows that keep a region on the screen's last row from shrinking
    working rows    the tail's last rows that say a turn runs (`tail_floor`), drawn under the pad rows
    slot            panel, completion menu or server-request prompt (one at a time); under a
                    panel or menu, or alone, the app's rows for the queued prompts
    top rule        the full-width rule above the composer
    composer        1..composer_cap(rows) input rows, the caret parked here
    bottom rule     the full-width rule under the composer
    menu below      the completion menu, where the app draws it under the composer instead of in the slot
    info line       the input mode or the keys that matter now, then model, context and effort
    agent view      the subagents (or the delegation tree) while there are any, always expanded

The budget is a pure function of the terminal size, the content sizes and
`min_height`. With `min_height` 0 the region is exactly as tall as its
content, so the region (drawn right under the output, `screen.LiveRegion`)
follows the content and the composer moves with what is above and below it.
The app passes the region's height as `min_height` once the region's last row
is the screen's last row: content that shrinks there becomes pad rows under
the live block and above the working rows, so the composer never moves up (it
moves down as the agent view under it shrinks), the working row and its tip
stay on it, and the live block stays right under the transcript it continues
(pad rows at the region's top pushed it down, leaving a band of blank rows
between the two until output filled it, the owner's report of 2026-10-25).
What the tail adds or the next flushed lines push down takes the pad rows. There
the app gives the agent view a row that comes free (the working row's, once a
turn ends) only when the view wants more rows than it did
(`agent_view.AgentViewMixin._held_view_rows`).
The one frame where the composer rises there is the one a turn ends with: the
row only a running turn had and nothing in that frame takes (the blank row
over the plan) is left out of `min_height`, since a pad row for it would stand
between the turn's done line and the composer (the owner's report of 2026-10-28; `App._render`).

- The region is never taller than `rows - 1`. `LiveRegion` moves only
  relative to its own top and cursor-up stops at the top of the screen, so a
  region taller than the screen loses its bookkeeping; the spare row keeps the
  region clear of that edge.
- Composer and info line are placed first, so they always fit: the composer
  gets `min(input rows, max(1, rows // 4))`, at least one row whenever the
  screen has two; the info line comes next.
- Then the bottom rule, by the terminal's height alone: from
  `BOTTOM_RULE_MIN_ROWS` rows, so a slot still gets its full cap on a shorter
  terminal.
- Then the top rule, then the menu below (at most `rows // 3`), then the
  slot (at most `rows // 3` less the menu below's rows), then the agent view
  (its producer sizes it to `agent_view_cap`), leaving the tail its last
  `tail_floor` rows (the working row while a turn runs), and the tail takes whatever
  remains, keeping its last rows. So a question or a picker keeps its whole
  cap beside the agent view, and the tail gives way first, never below its
  floor.
- Below `MIN_ROWS` rows or `MIN_COLS` columns only composer and info line are
  drawn, and, while a question answered with text is open (`text_question`),
  one slot row above them for its label when a row is left. No agent view.
- Pad rows fill the region up to `min_height`, never past `rows - 1`, and
  only where the content needs fewer rows.
- With the composer hidden (`composer_hidden`: the person picks from a list,
  so nothing is typed) the region draws no top rule, no input rows and no
  bottom rule, and the slot stands right above the info line, taking up to
  `choice_cap` rows: its own cap and the rows a one-row composer frame takes
  at that size. The info line keeps its row, and the agent view its rows.
  A picker that wants the screen (`/resume`'s session cards) passes
  `slot_limit` up to `tall_cap`: every row but the info line's and a few of
  transcript above it.
- While the agent list under the info line has the keys the composer frame
  keeps its rows and the frame draws them blank (`frame.build_frame`'s
  `composer_blank`), so nothing above or below it moves while the list is
  open.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .style import Line

MIN_ROWS = 6
MIN_COLS = 20
# The bottom rule under the composer, kept only where the slot still gets its full cap beside it.
BOTTOM_RULE_MIN_ROWS = 7
# The agent view's usual most rows: main and six agents (or main, five and a `+N` row), as the agent list had.
AGENT_VIEW_ROWS = 7
# The transcript rows a picker that takes the screen (`tall_cap`) leaves above itself.
TALL_CONTEXT_ROWS = 2

BLANK: Line = ()


@dataclass(frozen=True)
class Budget:
    tail: int
    slot: int
    rule: int
    composer: int
    bottom_rule: int
    info: int
    pad: int = 0
    floor: int = 0  # the tail's last rows, the working rows, drawn under the pad rows
    below: int = 0  # the menu below: between the bottom rule and the info line
    agents: int = 0  # the agent view: under the info line, the region's last rows
    gaps: tuple[int, int] = (0, 0)  # blank rows above the slot and under it

    @property
    def total(self) -> int:
        return (
            self.pad
            + self.tail
            + self.slot
            + self.rule
            + self.composer
            + self.bottom_rule
            + self.below
            + self.info
            + self.agents
            + sum(self.gaps)
        )

    @property
    def slot_top(self) -> int:
        """Region row of the slot's first row."""
        return self.pad + self.tail + self.gaps[0]

    @property
    def composer_top(self) -> int:
        """Region row of the composer's first row."""
        return self.slot_top + self.slot + self.gaps[1] + self.rule


def max_height(rows: int) -> int:
    """The tallest region a terminal of `rows` rows may hold."""
    return max(rows - 1, 0)


def is_tiny(rows: int, cols: int) -> bool:
    """True when the terminal is too small for anything but composer and info line."""
    return rows < MIN_ROWS or cols < MIN_COLS


def under_composer(rows: int, cols: int) -> int:
    """The bottom rule's rows (0 or 1): what lies between the composer and the info line, by terminal size alone."""
    return 0 if is_tiny(rows, cols) else int(rows >= BOTTOM_RULE_MIN_ROWS)


def composer_cap(rows: int) -> int:
    """The most rows the composer may show; render it with this as `max_rows`."""
    room = max_height(rows)
    if room >= 2:
        room -= 1  # the info line
    room -= int(rows >= BOTTOM_RULE_MIN_ROWS)
    return min(max(1, rows // 4), room)


def slot_cap(rows: int, cols: int) -> int:
    """The most rows a slot may take; slot producers size their content to it."""
    return 0 if is_tiny(rows, cols) else rows // 3


def choice_cap(rows: int, cols: int) -> int:
    """The most rows a slot may take while the composer is hidden: `slot_cap` and a one-row composer frame's rows.

    The frame is the top rule, its one input row and the bottom rule where the
    terminal draws them; below `MIN_ROWS` rows or `MIN_COLS` columns it is the
    input row alone.
    """
    frame = min(1, composer_cap(rows))
    if not is_tiny(rows, cols):
        frame += 1 + under_composer(rows, cols)
    return slot_cap(rows, cols) + frame


def tall_cap(rows: int, cols: int) -> int:
    """The most rows a picker that wants the screen may take (the `/resume` session cards): every row but the info
    line's and `TALL_CONTEXT_ROWS` of transcript above it, so the last output stays in sight. None on a tiny
    terminal."""
    return 0 if is_tiny(rows, cols) else max(max_height(rows) - 1 - TALL_CONTEXT_ROWS, 0)


def agent_view_cap(rows: int, cols: int, keep: int = 0) -> int:
    """The most rows the agent view under the info line may take; its producer sizes the view to this.

    `min(AGENT_VIEW_ROWS, rows // 4)`, so on the bottom rows, with the view
    at that cap, a one-row composer's input row is row 16 of 24, 21 of 30 and
    31 of 40 (the owner's complaint about Ink, 2026-10-13, was that the
    prompt went too far up).
    `keep` is the rows the view needs to show every running agent (with its
    header and `+N` row): it raises the cap to that, never past `rows // 3`.
    None on a tiny terminal.
    """
    if is_tiny(rows, cols):
        return 0
    return max(min(AGENT_VIEW_ROWS, rows // 4), min(keep, rows // 3))


def allocate(
    rows: int,
    cols: int,
    *,
    tail_rows: int,
    slot_rows: int,
    composer_rows: int,
    min_height: int = 0,
    composer_hidden: bool = False,
    text_question: bool = False,
    below_rows: int = 0,
    agents_rows: int = 0,
    tail_floor: int = 0,
    gaps: tuple[bool, bool] = (False, False),
    gap_reserve: int = 0,
    slot_limit: int = 0,
) -> Budget:
    """Rows for each part of the region (see the module docstring for the rules). `slot_limit`, with the composer
    hidden, raises the slot's cap past `choice_cap` for a picker that takes the screen (`tall_cap`)."""
    room = max_height(rows)
    composer = min(max(composer_rows, 1), composer_cap(rows))
    info = min(1, room - composer)
    bottom_rule = under_composer(rows, cols)
    if composer_hidden:
        composer = bottom_rule = 0  # their rows, and the top rule's, go to the slot (`choice_cap`)
    left = room - composer - info - bottom_rule
    rule = slot = tail = below = agents = 0
    spaced = (0, 0)
    if composer_hidden:
        slot = min(max(slot_rows, 0), max(choice_cap(rows, cols), slot_limit), left)
        left -= slot
    elif text_question and is_tiny(rows, cols):
        slot = min(max(slot_rows, 0), 1, left)
        left -= slot
    if not is_tiny(rows, cols):
        if not composer_hidden:
            rule = min(1, left)
            left -= rule
            below = min(max(below_rows, 0), slot_cap(rows, cols), left)
            left -= below
            slot = min(max(slot_rows, 0), slot_cap(rows, cols) - below, left)
            left -= slot
        agents = min(max(agents_rows, 0), max(left - min(max(tail_floor, 0), tail_rows), 0))
        left -= agents
        # The blank rows asked for above and under a slot that has rows: only from what the slot, the agent view and
        # the whole tail leave, so they give way before any of those does and never cost a live tool row (#2342
        # review). They stand above the composer, so on the bottom rows they push the transcript up, never the
        # composer. (None goes above the agent view: there one would move the composer up or cost the view a row.)
        # `gap_reserve` is the working rows' room whether or not a turn runs, so a gap never appears as a turn ends
        # and moves the slot.
        floor = max(min(max(tail_floor, 0), tail_rows), gap_reserve, max(tail_rows, 0))
        spare = max(left - floor, 0)
        above = int(gaps[0] and slot > 0 and spare > 0)
        spaced = (above, int(gaps[1] and slot > 0 and spare > above))
        left -= sum(spaced)
        tail = min(max(tail_rows, 0), left)
    content = tail + slot + rule + composer + bottom_rule + below + info + agents + sum(spaced)
    return Budget(
        pad=min(max(min_height - content, 0), room - content),
        floor=min(max(tail_floor, 0), tail),
        tail=tail,
        slot=slot,
        rule=rule,
        composer=composer,
        bottom_rule=bottom_rule,
        info=info,
        below=below,
        agents=agents,
        gaps=spaced,
    )


def _last(lines: Sequence[Line], count: int) -> list[Line]:
    """The last `count` lines, blank rows on top when there are fewer."""
    kept = list(lines)[max(len(lines) - count, 0) :] if count > 0 else []
    return [BLANK] * (count - len(kept)) + kept


def _first(lines: Sequence[Line], count: int) -> list[Line]:
    """The first `count` lines, blank rows on top when there are fewer."""
    kept = list(lines)[:count] if count > 0 else []
    return [BLANK] * (count - len(kept)) + kept


def compose(
    budget: Budget,
    *,
    tail: Sequence[Line],
    slot: Sequence[Line],
    rule: Line,
    composer: Sequence[Line],
    bottom_rule: Line,
    info: Line,
    below: Sequence[Line] = (),
    agents: Sequence[Line] = (),
) -> list[Line]:
    """The region's rows, exactly `budget.total` of them, top to bottom.

    The tail keeps its last rows, the pad rows going in above its last
    `budget.floor`; the slot, the composer and the agent view keep their first
    rows (their producers size them to `slot_cap`, `composer_cap` and
    `agent_view_cap`).
    """
    region: list[Line] = []
    shown = _last(tail, budget.tail)
    split = len(shown) - budget.floor
    region.extend([*shown[:split], *[BLANK] * budget.pad, *shown[split:]])
    region.extend([BLANK] * budget.gaps[0])
    region.extend(_first(slot, budget.slot))
    region.extend([BLANK] * budget.gaps[1])
    if budget.rule:
        region.append(rule)
    composer_rows = list(composer)[: budget.composer]
    region.extend(composer_rows + [BLANK] * (budget.composer - len(composer_rows)))
    if budget.bottom_rule:
        region.append(bottom_rule)
    region.extend(list(below)[: budget.below])
    if budget.info:
        region.append(info)
    region.extend(list(agents)[: budget.agents])
    return region


def caret_row(budget: Budget, composer_caret_row: int) -> int:
    """The region row of the composer's caret row."""
    last = max(budget.composer - 1, 0)
    return budget.composer_top + min(max(composer_caret_row, 0), last)
