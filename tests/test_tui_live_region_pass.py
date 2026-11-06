"""The owner's live-region pass of 2026-10-28: a mid-turn message on the sent prompt's band with a blank row over it,
the plan's done rows quiet and folded, the plan folded on Ctrl+P with the key named on its header, and who a reply is
from on a header of its own."""

from __future__ import annotations

from dataclasses import replace
from unittest import mock
import unittest

from _tui_lines import line_text, lines_text
from test_tui_modes import SID, drawn, make_app, type_text
from test_tui_panels import hud_payload

from omh.skin_pack import SKIN_THEMES
from omh.tui import transcript as transcript_module
from omh.tui.frame import sticky_line
from omh.tui.gateway import Event
from omh.tui.keys import CHAR, Key
from omh.tui.layout import allocate
from omh.tui.panels import HudSnapshot, panel_lines
from omh.tui.style import is_fill
from omh.tui.theme import (
    DEFAULT_LAUNCH, DEFAULT_THEME as THEME, TEXT_CONTRAST, build_theme, contrast_ratio, with_prompt_band, without_colour,
)
from omh.tui.transcript import AssistantBlock, SteerBlock, block_rows
from omh.tui.width import line_width

BANDED = with_prompt_band(build_theme(SKIN_THEMES[0], "#0D1117"), SKIN_THEMES[0], "#0D1117", DEFAULT_LAUNCH)
DONE_FIVE = [{"text": f"Step {n}", "state": "done"} for n in range(5)]
PLAN = [*DONE_FIVE, {"text": "Full suite, ruff, gates, commit with trailers", "state": "active"},
        {"text": "Push", "state": "pending"}]


def plan_rows(width: int = 80, max_rows: int = 40, **options) -> list[str]:
    return lines_text(panel_lines(hud_payload(PLAN), width, max_rows, THEME, 0.0, **options))


class MidTurnMessageTests(unittest.TestCase):
    def test_the_sticky_prompt_runs_on_the_band_with_a_blank_row_over_it(self) -> None:
        line = sticky_line("dag ulw 공존패치 ㄱㄱ", 60, BANDED)
        self.assertTrue(is_fill(line[-1]) and line[-1].style.bg == BANDED.prompt_band.bg)
        self.assertEqual({span.style.bg for span in line}, {BANDED.prompt_band.bg})
        for span in line[:-1]:
            if span.text.strip():
                self.assertGreaterEqual(contrast_ratio(span.style.fg, BANDED.prompt_band.bg), TEXT_CONTRAST, span)
        budget = allocate(40, 80, sticky=True, tail_rows=3, slot_rows=0, composer_rows=1, sticky_gap=True)
        self.assertEqual((budget.sticky_gap, budget.sticky), (1, 1))
        tight = allocate(10, 80, sticky=True, tail_rows=6, slot_rows=0, composer_rows=1, sticky_gap=True)
        self.assertEqual(tight.sticky_gap, 0, "the gap gives way before a live row")

    def test_a_steer_runs_on_the_band(self) -> None:
        (row,) = block_rows(SteerBlock("look at the docs too"), 60, BANDED)
        self.assertEqual({span.style.bg for span in row}, {BANDED.prompt_band.bg})
        self.assertTrue(line_text(row).startswith("┃ ❯ look at the docs too"))


class PlanBlockTests(unittest.TestCase):
    def test_done_rows_are_quiet_with_the_check_in_the_done_hue(self) -> None:
        lines = panel_lines(hud_payload(PLAN), 80, 40, THEME, 0.0)
        done = next(line for line in lines if "Step 0" in line_text(line))
        self.assertEqual([(span.text, span.style) for span in done][:2], [("[", THEME.muted), ("✓", THEME.ok)])
        self.assertEqual(done[-1].style, THEME.muted)
        pending = next(line for line in lines if "Push" in line_text(line))
        self.assertEqual(pending[-1].style, THEME.text)

    def test_done_rows_fold_into_one_row_before_a_pending_row_is_cut(self) -> None:
        roomy = plan_rows()
        self.assertEqual(len([row for row in roomy if "[✓]" in row]), 5)  # room for every item: nothing folds
        tight = plan_rows(max_rows=4)
        self.assertEqual(tight[1:], ["✓ 5 done", "[•] Full suite, ruff, gates, commit with trailers", "[ ] Push"])

    def test_folded_the_plan_is_its_header_and_the_item_it_is_on(self) -> None:
        (header,) = plan_rows(plan_folded=True, fold_key="ctrl+p")
        self.assertTrue(header.startswith("[Plan] Plan │ 5/7 ▸ Full suite, ruff, gates, commit with trailers"), header)
        self.assertTrue(header.endswith("ctrl+p expand"), header)
        self.assertTrue(plan_rows(fold_key="ctrl+p")[0].endswith("ctrl+p fold"))
        (narrow,) = plan_rows(width=40, plan_folded=True, fold_key="ctrl+p")
        self.assertNotIn("ctrl+p", narrow, "the hint goes first")
        self.assertTrue(narrow.startswith("[Plan] Plan │ 5/7 ▸ Full") and narrow.endswith("…"), narrow)
        self.assertLessEqual(len(narrow), 40)


class ShedPlanHintTests(unittest.TestCase):
    def test_a_plan_collapsed_for_room_names_no_key_and_one_the_person_folded_says_expand(self) -> None:
        # #2349 review, MEDIUM: at 10x60 the plan is its header for lack of room, and `ctrl+p expand` there named a
        # key that could not expand it.
        (shed,) = plan_rows(width=60, max_rows=1, fold_key="ctrl+p")
        self.assertTrue(shed.startswith("[Plan] Plan │ 5/7 ▸ Full"), shed)
        self.assertNotIn("ctrl+p", shed)
        (folded,) = plan_rows(width=80, max_rows=4, fold_key="ctrl+p", plan_folded=True)
        self.assertTrue(folded.endswith("ctrl+p expand"), folded)
        # #2349 follow-up: folded where the rows would collapse it anyway, the key could not expand it either.
        (both,) = plan_rows(width=80, max_rows=1, fold_key="ctrl+p", plan_folded=True)
        self.assertTrue(both.startswith("[Plan] Plan │ 5/7 ▸ Full"), both)
        self.assertNotIn("ctrl+p", both)


class FoldKeyTests(unittest.TestCase):
    def app(self, busy: bool):
        app, client = make_app(busy=busy)
        app.hud = HudSnapshot(app.stored_id, hud_payload(PLAN), 0.0)
        return app, client

    def plan(self, app) -> list[str]:
        return [row for row in drawn(app) if row.startswith("[Plan]") or "[✓]" in row or "[ ]" in row]

    def test_ctrl_p_folds_and_expands_the_plan_running_or_idle_and_types_nothing(self) -> None:
        for busy in (True, False):
            with self.subTest(busy=busy):
                app, client = self.app(busy)
                type_text(app, "half")
                self.assertGreater(len(self.plan(app)), 1)
                app._on_input(Key(CHAR, "p", ctrl=True))
                (header,) = self.plan(app)
                self.assertIn("▸ Full suite", header)
                self.assertEqual(app.composer.text, "half")  # nothing reached the composer
                app._on_input(Key(CHAR, "p", ctrl=True))
                self.assertGreater(len(self.plan(app)), 1)
                self.assertFalse([call for call in client.calls if call[0] in ("prompt.submit", "session.redirect")])

    def test_a_menu_over_the_plan_leaves_the_key_alone(self) -> None:
        # #2349 review, LOW: with `/` typed the menu stands where the plan was, and Ctrl+P flipped a fold nobody saw.
        app, _client = self.app(False)
        type_text(app, "/")
        drawn(app)
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertFalse(app.plan_folded)

    def test_a_plan_collapsed_for_room_leaves_the_key_alone_so_the_header_never_says_expand(self) -> None:
        # #2349 follow-up: on a short terminal Ctrl+P set the fold flag, the header then said `ctrl+p expand`, and
        # pressing it only cleared the flag.
        app, _client = make_app(rows=10, cols=60)
        app.hud = HudSnapshot(app.stored_id, hud_payload(
            [{"text": f"Task {n} xx", "state": "done" if n < 7 else "active" if n == 7 else "pending"}
             for n in range(10)]), 0.0)
        (header,) = self.plan(app)
        self.assertTrue(header.startswith("[Plan] Plan │ 7/10 ▸ Task 7 xx"), header)
        self.assertNotIn("ctrl+p", header)
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertFalse(app.plan_folded)
        self.assertEqual(self.plan(app), [header])

    def test_the_choice_holds_for_a_new_plan_and_without_a_plan_the_key_is_the_composer_s(self) -> None:
        app, _client = self.app(False)
        drawn(app)  # the plan is on screen: the key folds what is seen
        app._on_input(Key(CHAR, "p", ctrl=True))
        app.hud = HudSnapshot(app.stored_id, hud_payload([{"text": "Another plan", "state": "active"}]), 1.0)
        (header,) = self.plan(app)
        self.assertIn("▸ Another plan", header)
        bare, _client = make_app()
        self.assertFalse(bare._plan_fold_key(Key(CHAR, "p", ctrl=True)))


class AssistantHeaderTests(unittest.TestCase):
    def test_a_reply_opens_with_who_wrote_it_and_the_model(self) -> None:
        rows = block_rows(AssistantBlock("ok", done=True, model="deepseek/deepseek-v4.1-flash"), 40, THEME)
        self.assertEqual(lines_text(rows), ["┃ ⚚ Hermes · deepseek-v4.1-flash", "┃   ok"])
        self.assertEqual(rows[0][2].style, replace(THEME.brand, bold=True))
        self.assertEqual(rows[0][3].style, THEME.muted)
        self.assertLessEqual(line_width(block_rows(AssistantBlock("ok", done=True, model="x" * 80), 30, THEME)[0]), 30)

    def test_no_color_keeps_the_name_bold_and_variant_a_puts_the_mark_on_the_first_row(self) -> None:
        plain = without_colour(THEME)
        (header, _row) = block_rows(AssistantBlock("ok", done=True), 40, plain)
        self.assertTrue(header[2].style.bold)
        with mock.patch.object(transcript_module, "ASSISTANT_HEADER", False):
            self.assertEqual(lines_text(block_rows(AssistantBlock("ok", done=True), 40, THEME)), ["┃ ⚚ ok"])

    def test_a_resumed_reply_names_no_model_it_was_not_recorded_with(self) -> None:
        # #2349 review, LOW: a resumed session's replies were named with the model of the moment.
        app, _client = make_app()
        app.model = "openai/gpt-6.1-sol"
        app.transcript.add_assistant("Earlier answer.")
        (block,) = [block for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(lines_text(block_rows(block, 40, THEME))[0], "┃ ⚚ Hermes")

    def test_the_session_s_model_is_named_on_each_reply_begun_under_it(self) -> None:
        app, _client = make_app(busy=True)
        app.model = "openai/gpt-6.1-sol"
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.complete", SID, {"text": "Done.", "status": "complete"}))
        replies = [block for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(replies[-1].model, "openai/gpt-6.1-sol")


if __name__ == "__main__":
    unittest.main()
