"""The live region's height budget and stacking order (`omh.tui.layout`).

`allocate` is checked as properties over a grid of terminal sizes and content
sizes, so a rule that holds at 24 rows but breaks at 7 or 80 shows up. The
hard ones: the region is never taller than `rows - 1`, composer and info line
fit before anything else, the bottom rule under the composer follows the
terminal's height alone, the caps hold, and
`min_height` is honoured with pad rows (the app passes it once the region sits
on the screen's last row), and nothing is cut while the region has room.
`compose` is checked for row order, the tail keeping its last rows, and the
exact row count. A hidden composer (a question answered by picking, a picker,
the agent list) is checked over the same grid: no rules or input rows, the
info line exactly where the composer leaves it, and the slot given its
`choice_cap`, at least one row wherever the composer had one. The frame draws
the composer between two full-width rules that never change with the mode. The agent
view under the info line takes its rows after the slot and before the tail,
none on a tiny terminal, and its cap (`agent_view_cap`) is checked against
the rows it leaves the composer.
"""

from __future__ import annotations

from dataclasses import replace
import itertools
import unittest

from _tui_lines import rule_edges, composer_row, lines_text
from omh.tui.composer import Composer
from omh.tui.frame import BROWSING_HINT, build_frame, rule_line, sticky_line
from omh.tui.frame import MODE_ACCEPT, MODE_ACCEPT_PLAN, MODE_PLAN, MODE_SHELL
from omh.tui.layout import (
    AGENT_VIEW_ROWS,
    BLANK,
    BOTTOM_RULE_MIN_ROWS,
    MIN_COLS,
    MIN_ROWS,
    Budget,
    agent_view_cap,
    allocate,
    caret_row,
    choice_cap,
    compose,
    composer_cap,
    max_height,
    slot_cap,
)
from omh.tui.style import Line, Span
from omh.tui.theme import DEFAULT_THEME, KIND_FAMILIES
from omh.tui.width import line_width

ROWS = range(1, 86)
COLS = (5, MIN_COLS - 1, MIN_COLS, 40, 120)
TAIL_ROWS = (0, 1, 5, 40, 200)
SLOT_ROWS = (0, 2, 9, 60)
COMPOSER_ROWS = (0, 1, 3, 12, 50)


def plain(*texts: str) -> list[Line]:
    return [(Span(text),) for text in texts]


class AllocateGridTests(unittest.TestCase):
    def test_budget_rules_hold_over_the_grid(self) -> None:
        checked = 0
        for rows, cols, tail_rows, slot_rows, composer_rows, sticky in itertools.product(
            ROWS, COLS, TAIL_ROWS, SLOT_ROWS, COMPOSER_ROWS, (False, True)
        ):
            budget = allocate(
                rows,
                cols,
                sticky=sticky,
                tail_rows=tail_rows,
                slot_rows=slot_rows,
                composer_rows=composer_rows,
            )
            where = (rows, cols, tail_rows, slot_rows, composer_rows, sticky, budget)
            self.check_budget(budget, rows, cols, tail_rows, slot_rows, composer_rows, sticky, where)
            checked += 1
        self.assertGreater(checked, 25_000)

    def check_budget(
        self,
        budget: Budget,
        rows: int,
        cols: int,
        tail_rows: int,
        slot_rows: int,
        composer_rows: int,
        sticky: bool,
        where: tuple[object, ...],
    ) -> None:
        room = max(rows - 1, 0)
        content = budget.total
        parts = (
            budget.sticky,
            budget.tail,
            budget.slot,
            budget.rule,
            budget.composer,
            budget.bottom_rule,
            budget.info,
        )
        # never taller than the terminal minus one row, nothing negative
        self.assertLessEqual(budget.total, room, where)
        self.assertTrue(all(part >= 0 for part in parts), where)
        # composer and info line first: the composer gets its rows up to its cap, the info line next,
        # and the cap leaves room for the bottom rule the terminal's height puts under the composer
        cap = max(1, rows // 4)
        under = int(rows >= BOTTOM_RULE_MIN_ROWS)
        self.assertEqual(
            budget.composer, min(max(composer_rows, 1), cap, (room - 1 if room >= 2 else room) - under), where
        )
        self.assertEqual(budget.info, 1 if rows >= 3 else 0, where)
        # caps
        self.assertLessEqual(budget.slot, rows // 3, where)
        self.assertLessEqual(budget.slot, slot_rows, where)
        self.assertLessEqual(budget.tail, tail_rows, where)
        self.assertLessEqual(budget.sticky, int(sticky), where)
        self.assertLessEqual(budget.rule, 1, where)
        # tiny terminals: composer and info line only
        if rows < MIN_ROWS or cols < MIN_COLS:
            self.assertEqual(
                (budget.sticky, budget.tail, budget.slot, budget.rule, budget.bottom_rule),
                (0, 0, 0, 0, 0),
                where,
            )
        else:
            self.assertEqual(budget.rule, 1, where)
            # the bottom rule depends on the height alone, whatever the content
            self.assertEqual(budget.bottom_rule, int(rows >= BOTTOM_RULE_MIN_ROWS), where)
            # nothing is cut while there is room for it
            if content < room:
                self.assertEqual(budget.tail, tail_rows, where)
                self.assertEqual(budget.slot, min(slot_rows, rows // 3), where)
                self.assertEqual(budget.sticky, int(sticky), where)
            # the sticky row is never taken while the slot is short of its cap
            if budget.sticky:
                self.assertEqual(budget.slot, min(slot_rows, rows // 3), where)


class AgentViewBudgetTests(unittest.TestCase):
    """The agent view under the info line: after the slot, before the tail, and none on a tiny terminal."""

    def test_the_view_takes_its_rows_after_the_slot_and_before_the_tail_over_the_grid(self) -> None:
        for rows, cols, tail_rows, slot_rows, composer_rows, agents_rows in itertools.product(
            range(1, 60), COLS, (0, 5, 200), (0, 9, 60), (1, 12), (0, 3, 7, 30)
        ):
            plain_budget = allocate(rows, cols, sticky=False, tail_rows=tail_rows, slot_rows=slot_rows,
                                    composer_rows=composer_rows)
            with_view = allocate(rows, cols, sticky=False, tail_rows=tail_rows, slot_rows=slot_rows,
                                 composer_rows=composer_rows, agents_rows=agents_rows)
            where = (rows, cols, tail_rows, slot_rows, composer_rows, agents_rows, with_view)
            self.assertLessEqual(with_view.total, max(rows - 1, 0), where)
            # everything from the composer up to the slot keeps what it had without the view
            for part in ("composer", "info", "rule", "bottom_rule", "slot", "below"):
                self.assertEqual(getattr(with_view, part), getattr(plain_budget, part), (part, where))
            if rows < MIN_ROWS or cols < MIN_COLS:
                self.assertEqual(with_view.agents, 0, where)
                continue
            left = max(rows - 1, 0) - (plain_budget.total - plain_budget.tail)
            self.assertEqual(with_view.agents, min(agents_rows, left), where)
            self.assertEqual(with_view.tail, min(tail_rows, left - with_view.agents), where)

    def test_the_view_leaves_the_tail_its_floor_and_takes_the_rest(self) -> None:
        # 12 rows, a full slot: seven rows after the composer frame and the info line, four of them the slot's.
        free = allocate(12, 80, sticky=False, tail_rows=5, slot_rows=9, composer_rows=1, agents_rows=4)
        floored = allocate(12, 80, sticky=False, tail_rows=5, slot_rows=9, composer_rows=1, agents_rows=4, tail_floor=1)
        self.assertEqual((free.slot, free.agents, free.tail), (4, 3, 0))
        self.assertEqual((floored.slot, floored.agents, floored.tail), (4, 2, 1))
        # A floor past the tail's own rows asks for nothing more, and room enough leaves the view whole.
        self.assertEqual(allocate(12, 80, sticky=False, tail_rows=0, slot_rows=9, composer_rows=1, agents_rows=4,
                                  tail_floor=2).agents, 3)
        self.assertEqual(allocate(40, 80, sticky=False, tail_rows=5, slot_rows=9, composer_rows=1, agents_rows=7,
                                  tail_floor=2).agents, 7)

    def test_the_view_is_the_regions_last_rows_under_the_info_line(self) -> None:
        parts = Budget(sticky=0, tail=1, slot=1, rule=1, composer=1, bottom_rule=1, info=1, agents=2)
        region = compose(
            parts, sticky=None, tail=plain("t1"), slot=plain("[Plan]"), rule=plain("──")[0], composer=plain("> a"),
            bottom_rule=plain("__")[0], info=plain("info")[0], agents=plain("● main", "⠋ agent", "cut"),
        )
        self.assertEqual(lines_text(region), ["t1", "[Plan]", "──", "> a", "__", "info", "● main", "⠋ agent"])
        self.assertEqual(len(region), parts.total)

    def test_the_cap_is_a_quarter_up_to_seven_and_running_agents_raise_it_up_to_a_third(self) -> None:
        self.assertEqual(AGENT_VIEW_ROWS, 7)
        usual = {6: 1, 8: 2, 10: 2, 12: 3, 16: 4, 20: 5, 24: 6, 28: 7, 40: 7, 80: 7}
        for rows, cap in usual.items():
            with self.subTest(rows=rows):
                self.assertEqual(agent_view_cap(rows, 80), cap)
                self.assertEqual(agent_view_cap(rows, 80, cap - 1), cap, "fewer to keep never lowers it")
                self.assertEqual(agent_view_cap(rows, 80, 99), max(cap, rows // 3))
        self.assertEqual(agent_view_cap(24, 80, 7), 7)
        for rows, cols in ((5, 80), (24, MIN_COLS - 1)):
            self.assertEqual(agent_view_cap(rows, cols, 99), 0)

    def test_a_frame_with_the_composer_blank_keeps_its_rows_and_shows_no_caret(self) -> None:
        composer = Composer(text="", caret=0)
        info, agents = (Span("keys"),), plain("● main", "▸ ⠋ agent")
        shown = build_frame(cols=40, rows=24, composer=composer, info=info, agents=agents)
        blank = build_frame(cols=40, rows=24, composer=composer, info=info, agents=agents, composer_blank=True)
        self.assertEqual(blank.height, shown.height)
        self.assertEqual(lines_text(list(blank.lines)), ["─" * 40, f"  {BROWSING_HINT}", "─" * 40, "keys", "● main", "▸ ⠋ agent"])
        self.assertIsNone(blank.cursor)
        self.assertEqual(lines_text(list(shown.lines))[3:], ["keys", "● main", "▸ ⠋ agent"])


def budget(**rows: int) -> Budget:
    """A `Budget` with every part not named at 0."""
    parts = ("sticky", "tail", "slot", "rule", "composer", "bottom_rule", "info")
    return Budget(**{part: rows.get(part, 0) for part in parts})


class AllocateExampleTests(unittest.TestCase):
    def test_an_everyday_terminal(self) -> None:
        got = allocate(24, 80, sticky=True, tail_rows=3, slot_rows=4, composer_rows=1)
        self.assertEqual(got, budget(sticky=1, tail=3, slot=4, rule=1, composer=1, bottom_rule=1, info=1))
        self.assertEqual(got.total, 12)
        self.assertEqual(got.composer_top, 9)
        # the composer's first row: its own rows plus the bottom rule and the info line from the end
        self.assertEqual(got.total - got.composer_top, got.composer + 2)

    def test_the_tail_takes_the_rest_and_the_slot_is_capped(self) -> None:
        got = allocate(24, 80, sticky=True, tail_rows=100, slot_rows=100, composer_rows=100)
        self.assertEqual(got, budget(sticky=1, tail=5, slot=8, rule=1, composer=6, bottom_rule=1, info=1))
        self.assertEqual(got.total, 23)

    def test_an_idle_region_is_its_composer_box_and_info_line_alone(self) -> None:
        got = allocate(24, 80, sticky=False, tail_rows=0, slot_rows=0, composer_rows=1)
        self.assertEqual(got, budget(rule=1, composer=1, bottom_rule=1, info=1))
        self.assertEqual(got.total, 4)

    def test_a_tiny_terminal_draws_composer_and_info_line_only(self) -> None:
        for rows, cols in ((5, 80), (24, MIN_COLS - 1)):
            with self.subTest(rows=rows, cols=cols):
                got = allocate(rows, cols, sticky=True, tail_rows=9, slot_rows=9, composer_rows=1)
                self.assertEqual(got, budget(composer=1, info=1))

    def test_a_short_terminal_drops_the_bottom_rule_and_keeps_the_info_line(self) -> None:
        shapes = {
            rows: (got.bottom_rule, got.info)
            for rows in range(MIN_ROWS, 13)
            for got in [allocate(rows, 80, sticky=False, tail_rows=0, slot_rows=0, composer_rows=1)]
        }
        self.assertEqual(
            shapes, {6: (0, 1), 7: (1, 1), 8: (1, 1), 9: (1, 1), 10: (1, 1), 11: (1, 1), 12: (1, 1)}
        )

    def test_a_full_slot_keeps_its_cap_beside_the_rows_under_the_composer(self) -> None:
        # The height the bottom rule starts at is chosen so an approval
        # still gets every row it may take: it never costs the slot a row.
        for rows in range(MIN_ROWS, 86):
            with self.subTest(rows=rows):
                got = allocate(rows, 80, sticky=False, tail_rows=0, slot_rows=999, composer_rows=999)
                self.assertEqual(got.slot, slot_cap(rows, 80))

    def test_the_smallest_terminals(self) -> None:
        two = allocate(2, 80, sticky=True, tail_rows=9, slot_rows=9, composer_rows=3)
        self.assertEqual(two, budget(composer=1))
        one = allocate(1, 80, sticky=True, tail_rows=9, slot_rows=9, composer_rows=3)
        self.assertEqual(one.total, 0)

    def test_the_caps(self) -> None:
        self.assertEqual([composer_cap(rows) for rows in (1, 2, 3, 7, 8, 24, 80)], [0, 1, 1, 1, 2, 6, 20])
        self.assertEqual([slot_cap(rows, 80) for rows in (5, 6, 24, 80)], [0, 2, 8, 26])
        self.assertEqual(slot_cap(24, MIN_COLS - 1), 0)


class GapTests(unittest.TestCase):
    """The blank rows around the plan (the owner's spacing of 2026-10-27): only from rows nothing else wants."""

    def test_a_tall_terminal_gives_both_gaps_and_the_frame_draws_them_around_the_slot(self) -> None:
        budget = allocate(40, 80, sticky=False, tail_rows=10, slot_rows=4, composer_rows=1, gaps=(True, True),
                          tail_floor=2, gap_reserve=2)
        self.assertEqual((budget.gaps, budget.slot, budget.tail), ((1, 1), 4, 10))
        slot = [(Span("[Plan]"),), (Span("[ ] a"),), (Span("[ ] b"),), (Span("[ ] c"),)]
        frame = build_frame(cols=80, rows=40, composer=Composer(), info=(Span("info"),),
                            tail=[(Span("tip"),)], slot=slot, gaps=(True, True))
        rows = lines_text(list(frame.lines))
        start = rows.index("[Plan]")
        self.assertEqual((rows[start - 1], rows[start + 4]), ("", ""))
        self.assertTrue(rows[start + 5].startswith("─"))

    def test_the_gaps_give_way_before_the_slot_the_agent_view_or_the_working_rows(self) -> None:
        for rows in range(MIN_ROWS, 30):
            with self.subTest(rows=rows):
                spaced = allocate(rows, 80, sticky=False, tail_rows=3, slot_rows=5, composer_rows=1,
                                  agents_rows=7, tail_floor=2, gaps=(True, True), gap_reserve=2)
                plain = allocate(rows, 80, sticky=False, tail_rows=3, slot_rows=5, composer_rows=1,
                                 agents_rows=7, tail_floor=2, gap_reserve=2)
                self.assertEqual((spaced.slot, spaced.agents, spaced.floor), (plain.slot, plain.agents, plain.floor))
                self.assertEqual(spaced.composer_top - sum(spaced.gaps) - spaced.tail,
                                 plain.composer_top - plain.tail)
                self.assertLessEqual(spaced.total, max_height(rows))

    def test_a_tail_that_ends_blank_is_its_own_gap_above_the_slot(self) -> None:
        frame = build_frame(cols=80, rows=40, composer=Composer(), info=(Span("info"),),
                            tail=[(Span("done"),), ()], slot=[(Span("[Plan]"),)], gaps=(True, True))
        self.assertEqual(frame.budget.gaps, (0, 1))


class GapsNeverCostALiveRowTests(unittest.TestCase):
    """#2342 review, HIGH: the plan's blank rows and the spacer over the working row once took the place of the
    running turn's tool rows on short terminals. Every tool row the layout without them showed is still shown."""

    # (rows, cols, agents): the tool rows shown before the gaps existed, measured on origin/main dc007063f.
    BEFORE = {(10, 40, False): 1, (15, 60, False): 2, (19, 80, True): 1, (20, 80, True): 2, (24, 80, False): 3,
              (24, 80, True): 3, (30, 80, True): 3, (30, 80, False): 3}  # from 30 rows: the badge row too

    def scene(self, rows: int, cols: int, agents: bool):
        from omh.tui.gateway import Event
        from omh.tui.panels import HudSnapshot
        from test_tui_agent_view import STARTS, relay
        from test_tui_modes import SID, make_app
        from test_tui_panels import hud_payload, phased_plan

        now = [100.0]
        app, _client = make_app(rows=rows, cols=cols, clock=lambda: now[0])
        app.background = "#0D1117"
        app.theme = app._themed()
        app.stored_id = "stored"
        app.hud = HudSnapshot("stored", hud_payload(phased_plan(5, phases=2, active=2)), now[0])
        for index in range(30):
            app.transcript.add_notice(f"earlier line {index}")
        app._submit_prompt("해당 프로젝트 description기반으로 작성해줘 " * 3)
        app._on_event(Event("message.start", SID, {}))
        for index in range(3):
            now[0] += 0.2
            app._on_event(Event("tool.start", SID, {"tool_id": f"t{index}", "name": "read_file",
                                                    "context": f"f{index}.py"}))
        if agents:
            relay(app, STARTS)
        app._render()
        return app.terminal.screen.lines()

    def test_every_tool_row_shown_before_the_gaps_is_still_shown(self) -> None:
        for (rows, cols, agents), before in self.BEFORE.items():
            with self.subTest(rows=rows, cols=cols, agents=agents):
                screen = self.scene(rows, cols, agents)
                shown = sum("read_file" in row for row in screen)
                self.assertGreaterEqual(shown, before, "\n".join(screen))

    def test_a_tall_terminal_still_gets_both_gaps_around_the_plan(self) -> None:
        screen = self.scene(42, 150, True)
        plan = next(index for index, row in enumerate(screen) if row.startswith("[Plan]"))
        rule = next(index for index, row in enumerate(screen) if row.startswith("─") and index > plan)
        self.assertEqual((screen[plan - 1], screen[rule - 1]), ("", ""), "\n".join(screen))

    def test_a_tall_terminal_keeps_the_spacer_over_the_working_row_when_the_tail_is_cut(self) -> None:
        """Owner, 2026-10-30: on a tall terminal during a long turn `✻ Working…` read glued to the last tool row, since
        a tail cut short gave its spacer up first. With `SPACER_LIVE_ROWS` live rows still above it the spacer stays
        and the oldest live row goes instead."""
        from omh.tui.gateway import Event
        from test_tui_modes import SID, make_app

        now = [100.0]
        app, _client = make_app(rows=30, cols=110, clock=lambda: now[0])
        for index in range(30):
            app.transcript.add_notice(f"earlier line {index}")
        app._submit_prompt("write the report")
        app._on_event(Event("message.start", SID, {}))
        for index in range(16):
            now[0] += 0.2
            app._on_event(Event("tool.start", SID, {"tool_id": f"t{index}", "name": "read_file",
                                                    "context": f"f{index}.py"}))
        app._render()
        screen = app.terminal.screen.lines()
        working = next(index for index, row in enumerate(screen) if row.startswith("✻ Working"))
        self.assertNotIn("read_file(f0.py)", "\n".join(screen))  # the tail is cut
        self.assertEqual(screen[working - 1], "", "\n".join(screen))
        self.assertIn("read_file(f15.py)", screen[working - 2], "\n".join(screen))


class HiddenComposerBudgetTests(unittest.TestCase):
    """While the person picks from a list the composer frame is not drawn and the slot takes its rows."""

    def test_the_slot_takes_the_composer_frames_rows_and_the_rows_under_it_stay(self) -> None:
        checked = 0
        for rows, cols, tail_rows, slot_rows, composer_rows, sticky in itertools.product(
            ROWS, COLS, TAIL_ROWS, SLOT_ROWS, COMPOSER_ROWS, (False, True)
        ):
            parts = dict(sticky=sticky, tail_rows=tail_rows, slot_rows=slot_rows)
            shown = allocate(rows, cols, composer_rows=composer_rows, **parts)  # type: ignore[arg-type]
            got = allocate(rows, cols, composer_rows=composer_rows, composer_hidden=True, **parts)  # type: ignore[arg-type]
            where = (rows, cols, tail_rows, slot_rows, composer_rows, sticky, got)
            self.assertEqual((got.rule, got.composer, got.bottom_rule), (0, 0, 0), where)
            self.assertEqual(got.info, shown.info, where)
            self.assertLessEqual(got.total, max(rows - 1, 0), where)
            self.assertTrue(all(part >= 0 for part in (got.sticky, got.tail, got.slot)), where)
            self.assertEqual(got.slot, min(slot_rows, choice_cap(rows, cols)), where)
            if slot_rows and shown.composer:
                self.assertGreaterEqual(got.slot, 1, where)  # the highlighted row, at least
            if rows < MIN_ROWS or cols < MIN_COLS:
                self.assertEqual((got.sticky, got.tail), (0, 0), where)
            checked += 1
        self.assertGreater(checked, 25_000)

    def test_the_cap_is_the_slots_and_a_one_row_composer_frames(self) -> None:
        sizes = (1, 2, 5, 6, 7, 9, 10, 24, 80)
        self.assertEqual([choice_cap(rows, 80) for rows in sizes], [0, 1, 1, 4, 5, 6, 6, 11, 29])
        self.assertEqual(choice_cap(24, MIN_COLS - 1), 1)  # too narrow for a slot: the composer's own row
        for rows in sizes:
            with self.subTest(rows=rows):
                frame = allocate(rows, 80, sticky=False, tail_rows=0, slot_rows=0, composer_rows=1)
                self.assertEqual(choice_cap(rows, 80), slot_cap(rows, 80) + frame.rule + frame.composer + frame.bottom_rule)

    def test_an_everyday_terminal(self) -> None:
        got = allocate(24, 80, sticky=True, tail_rows=3, slot_rows=5, composer_rows=2, composer_hidden=True)
        self.assertEqual(got, budget(sticky=1, tail=3, slot=5, info=1))
        got = allocate(24, 80, sticky=True, tail_rows=100, slot_rows=100, composer_rows=1, composer_hidden=True)
        self.assertEqual(got, budget(sticky=1, tail=10, slot=11, info=1))


class SlotCaretTests(unittest.TestCase):
    """With no composer, `slot_caret` (a row and a column within the slot) is the frame's caret: a picker's filter."""

    def test_the_caret_lands_on_its_slot_row_and_none_when_that_row_is_cut(self) -> None:
        slot = plain("header", "row 1", "row 2", " › re")
        frame = build_frame(cols=80, rows=24, composer=None, info=plain("info")[0], slot=slot,
                            slot_caret=(3, 5))
        row, col = frame.cursor  # type: ignore[misc]
        self.assertEqual(lines_text([frame.lines[row]]), [" › re"])
        self.assertEqual(col, 5)
        cut = build_frame(cols=80, rows=24, composer=None, info=plain("info")[0],
                          slot=slot + plain(*[f"more {n}" for n in range(20)]), slot_caret=(23, 5))
        self.assertIsNone(cut.cursor)  # its row is past the slot's cap
        self.assertIsNone(build_frame(cols=80, rows=24, composer=None, info=plain("info")[0],
                                      slot=slot).cursor)


class ComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule = (Span("──"),)
        self.bottom = (Span("__"),)
        self.info = (Span("info"),)

    def test_rows_stack_in_order_and_the_tail_keeps_its_last_rows(self) -> None:
        parts = budget(sticky=1, tail=2, slot=2, rule=1, composer=2, bottom_rule=1, info=1)
        region = compose(
            parts,
            sticky=(Span("↳ you: hi"),),
            tail=plain("t1", "t2", "t3", "t4"),
            slot=plain("s1", "s2", "s3"),
            rule=self.rule,
            composer=plain("> a", "  b"),
            bottom_rule=self.bottom,
            info=self.info,
        )
        self.assertEqual(
            lines_text(region),
            ["↳ you: hi", "t3", "t4", "s1", "s2", "──", "> a", "  b", "__", "info"],
        )
        self.assertEqual(len(region), parts.total)

    def test_short_parts_are_filled_with_blank_rows_to_the_exact_count(self) -> None:
        parts = budget(sticky=1, tail=3, slot=2, rule=1, composer=2, bottom_rule=1, info=1)
        region = compose(
            parts,
            sticky=None,
            tail=plain("t1"),
            slot=plain("s1"),
            rule=self.rule,
            composer=plain("> a"),
            bottom_rule=self.bottom,
            info=self.info,
        )
        self.assertEqual(lines_text(region), ["", "", "", "t1", "", "s1", "──", "> a", "", "__", "info"])
        self.assertEqual(region[0], BLANK)

    def test_pad_rows_go_under_the_live_block_and_above_the_working_rows(self) -> None:
        # Pad rows at the region's top left a band between the transcript and the live block it continues (the
        # owner's report, 2026-10-25); the working row and its tip stay on the composer.
        parts = Budget(sticky=1, tail=4, slot=0, rule=1, composer=1, bottom_rule=1, info=1, pad=3, floor=2)
        region = compose(
            parts,
            sticky=(Span("↳ you: hi"),),
            tail=plain("call", "output", "working", "tip"),
            slot=[],
            rule=self.rule,
            composer=plain("> a"),
            bottom_rule=self.bottom,
            info=self.info,
        )
        self.assertEqual(
            lines_text(region),
            ["↳ you: hi", "call", "output", "", "", "", "working", "tip", "──", "> a", "__", "info"],
        )
        self.assertEqual(len(region), parts.total)
        got = allocate(24, 80, sticky=False, tail_rows=4, slot_rows=0, composer_rows=1, min_height=12, tail_floor=2)
        self.assertEqual((got.pad, got.floor), (12 - 8, 2))
        self.assertEqual(allocate(24, 80, sticky=False, tail_rows=1, slot_rows=0, composer_rows=1, tail_floor=2).floor,
                         1)  # never more rows than the tail shows

    def test_nothing_budgeted_draws_nothing(self) -> None:
        region = compose(
            budget(composer=1, info=1),
            sticky=(Span("sticky"),),
            tail=plain("t1"),
            slot=plain("s1"),
            rule=self.rule,
            composer=plain("> a"),
            bottom_rule=self.bottom,
            info=self.info,
        )
        self.assertEqual(lines_text(region), ["> a", "info"])

    def test_caret_row_counts_everything_above_the_composer(self) -> None:
        parts = budget(sticky=1, tail=2, slot=2, rule=1, composer=3, bottom_rule=1, info=1)
        self.assertEqual([caret_row(parts, row) for row in (-1, 0, 1, 2, 7)], [6, 6, 7, 8, 8])


class FrameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.info = (Span("info"),)

    def test_a_frame_is_exactly_as_tall_as_what_it_holds(self) -> None:
        composer = Composer(text="hi", caret=2)
        frame = build_frame(cols=40, rows=10, composer=composer, info=self.info)
        self.assertEqual(frame.height, 4)
        top, bottom = rule_edges(40)
        self.assertEqual(lines_text(list(frame.lines)), [top, composer_row("❯ hi", 40), bottom, "info"])
        self.assertEqual(frame.cursor, (1, 4))  # the prompt mark and its space, two characters: no side before it

    def test_a_menu_below_sits_between_the_bottom_edge_and_the_info_line_and_shares_the_slots_cap(self) -> None:
        composer = Composer(text="/", caret=1)
        frame = build_frame(cols=40, rows=24, composer=composer, info=self.info,
                            slot=plain("⧗ queued"), below=plain("/help", "/model"))
        top, bottom = rule_edges(40)
        self.assertEqual(lines_text(list(frame.lines)),
                         ["⧗ queued", top, composer_row("❯ /", 40), bottom, "/help", "/model", "info"])
        self.assertEqual(frame.cursor, (2, 3))  # the caret's row is counted from the top, as without the menu
        self.assertEqual((frame.budget.slot, frame.budget.below), (1, 2))
        full = build_frame(cols=40, rows=24, composer=composer, info=self.info, slot=plain(*"abc"),
                           below=plain(*"0123456789"))
        self.assertEqual(full.budget.below, slot_cap(24, 40))
        self.assertEqual(full.budget.slot + full.budget.below, slot_cap(24, 40))
        hidden = build_frame(cols=40, rows=24, composer=None, info=self.info, below=plain("/help"))
        self.assertEqual(hidden.budget.below, 0)  # no composer, nothing under it

    def test_a_frame_grows_and_shrinks_with_its_content(self) -> None:
        composer = Composer()
        grown = build_frame(cols=40, rows=24, composer=composer, info=self.info, tail=plain("a", "b", "c"))
        self.assertEqual(grown.height, 7)
        self.assertEqual(lines_text(list(grown.lines))[:3], ["a", "b", "c"])
        shrunk = build_frame(cols=40, rows=24, composer=composer, info=self.info, tail=plain("c"))
        self.assertEqual((shrunk.height, lines_text(list(shrunk.lines))[0]), (5, "c"))

    def test_the_composer_is_rendered_within_its_cap(self) -> None:
        composer = Composer(text="1\n2\n3\n4\n5", caret=9)
        frame = build_frame(cols=40, rows=12, composer=composer, info=self.info)
        self.assertEqual(frame.budget.composer, 3)
        self.assertEqual(lines_text(list(frame.lines))[-5:],
                         [composer_row("  3", 40), composer_row("  4", 40), composer_row("  5", 40), rule_edges(40)[1], "info"])
        self.assertEqual(frame.cursor, (3, 3))

    def test_a_tiny_terminal_frame_is_composer_and_info_line_without_a_box(self) -> None:
        frame = build_frame(
            cols=12, rows=4, composer=Composer(), info=self.info, slot=plain("menu")
        )
        self.assertEqual(lines_text(list(frame.lines)), ["❯ ", "info"])
        self.assertEqual(frame.cursor, (0, 2))

    def test_the_rules_span_the_width_in_the_rule_colour(self) -> None:
        # The composer as Claude Code draws it now (owner, 2026-10-22): a full-width rule above and under it, no corners.
        # A gutter: it frames the composer, and a drag on the main screen never copies it.
        rule = replace(DEFAULT_THEME.rule, gutter=True)
        self.assertEqual(rule_line(5, DEFAULT_THEME), (Span("─────", rule),))
        self.assertEqual(rule_line(0, DEFAULT_THEME), (Span("", rule),))

    def test_every_composer_row_is_full_width_with_no_sides_at_every_width(self) -> None:
        for cols in (60, 100, 150):
            composer = Composer(text="a" * 160 + " 한글 tail", caret=3)
            frame = build_frame(cols=cols, rows=24, composer=composer, info=self.info)
            top = frame.budget.composer_top
            self.assertEqual(lines_text([frame.lines[top - 1], frame.lines[top + frame.budget.composer]]), ["─" * cols] * 2)
            for index, row in enumerate(frame.lines[top : top + frame.budget.composer]):
                with self.subTest(cols=cols, row=lines_text([row])):
                    self.assertEqual(row[0].text, "❯ " if index == 0 else "  ")
                    self.assertNotIn("│", lines_text([row])[0])
                    self.assertLessEqual(line_width(row), cols)
            self.assertEqual(frame.cursor, (top, 2 + 3))  # the caret is the input's own column: no side before it

    def test_no_mode_changes_the_rules_and_a_shell_line_takes_the_shell_hue_only_on_its_prompt_mark(self) -> None:
        # The owner, round 4: no composer recolour for accept all or plan; the mode is said on the info line. A `!`
        # line's mark is the shell family's hue (#2223 review: the running blue says only "running").
        expected = (rule_line(30, DEFAULT_THEME), rule_line(30, DEFAULT_THEME))
        for mode in ("normal", MODE_ACCEPT, MODE_PLAN, MODE_ACCEPT_PLAN, MODE_SHELL, "not-a-mode"):
            with self.subTest(mode=mode):
                frame = build_frame(cols=30, rows=24, composer=Composer(text="!ls", caret=3), info=self.info, mode=mode)
                top, bottom = frame.budget.composer_top - 1, frame.budget.composer_top + frame.budget.composer
                self.assertEqual((frame.lines[top], frame.lines[bottom]), expected)
                mark = frame.lines[frame.budget.composer_top][0]
                self.assertEqual(mark.text, "❯ ")
                shell = DEFAULT_THEME.kinds[KIND_FAMILIES.index("shell")]
                # A gutter: the mark frames the draft and a drag on the main screen does not copy it.
                self.assertEqual(mark.style, replace(shell if mode == MODE_SHELL else DEFAULT_THEME.prompt, gutter=True))

    def test_the_placeholder_is_drawn_after_the_prompt_and_never_typed(self) -> None:
        composer = Composer()
        frame = build_frame(
            cols=40, rows=24, composer=composer, info=self.info, placeholder="Ask Hermes anything"
        )
        row = frame.lines[frame.budget.composer_top]
        self.assertEqual(lines_text([row]), [composer_row("❯ Ask Hermes anything", 40)])
        self.assertIn(Span("Ask Hermes anything", replace(DEFAULT_THEME.hint, gutter=True)), row)
        self.assertEqual(frame.cursor, (frame.budget.composer_top, 2))
        self.assertEqual(composer.text, "")
        typed = build_frame(
            cols=40,
            rows=24,
            composer=Composer(text="x", caret=1),
            info=self.info,
            placeholder="Ask Hermes anything",
        )
        self.assertEqual(lines_text([typed.lines[typed.budget.composer_top]]), [composer_row("❯ x", 40)])

    def test_the_sticky_line_shows_the_first_line_of_the_prompt(self) -> None:
        line = sticky_line("  fix the 한글 bug\nand more", 40, DEFAULT_THEME)
        self.assertEqual(lines_text([line]), ["↳ you: fix the 한글 bug"])
        self.assertEqual(lines_text([sticky_line("abcdefghij", 12, DEFAULT_THEME)]), ["↳ you: abcd…"])

    def test_the_sticky_line_has_no_band_and_reads_apart_from_a_transcript_row_by_its_colours(self) -> None:
        # Round 3, review B NIT 9: right under the turn's last row (`▸ thought for …`), it read as one more of them.
        # Round 4: no band behind the person's own text, as the prompt's echo has none; `↳ you:` in the accent,
        # which no transcript row starts with, and the prompt in the muted text colour.
        from omh.tui.style import is_fill
        from omh.tui.theme import theme_named

        for theme in (DEFAULT_THEME, theme_named("sky", "#FFFFFF"), theme_named("sky", "#1E1E1E")):
            with self.subTest(theme=theme.name):
                line = sticky_line("fix the bug", 40, theme)
                self.assertEqual({span.style.bg for span in line}, {None})
                self.assertFalse(any(is_fill(span) for span in line))
                self.assertEqual([(span.text, span.style) for span in line],
                                 [("↳ you: ", theme.running), ("fix the bug", theme.muted)])
                (cut,) = [sticky_line("abcdefghij", 12, theme)]
                self.assertEqual((cut[-1].text, cut[-1].style), ("…", theme.dim))  # a dim mark where it is cut


if __name__ == "__main__":
    unittest.main()
