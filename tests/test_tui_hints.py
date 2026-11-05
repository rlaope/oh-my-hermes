"""Hints that say one thing at a time, and layouts that keep them on narrow terminals.

While Hermes asks something, the info line names that question's keys and
the working row stops offering Esc for an interrupt, so the screen gives Esc
one meaning. The agent count's last mark says what Down opens (`↓ agents`). An
approval keeps a short key hint on the info line at 60 and 40 columns, and a
long command wraps under its own indent. The banner is one row (brand, version, resumed
session, working directory; the model and the keys are on the info line), and
a fresh session is told where the last one is.
"""

from __future__ import annotations

import unittest

from _tui_lines import INFO_INSET, line_text, lines_text, without_badge
from test_tui_agent_view import agent_app
from test_tui_modes import answer, make_app
from omh.tui.app import App, banner_lines
from omh.tui.gateway import Response, ServerRequest
from omh.tui.prompts import open_request
from omh.tui.subagents import OPEN_MARK
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NoticeBlock

APPROVAL = ServerRequest("srq-1", "approval", {"command": "rm -rf ./build", "description": "recursive delete"})
CLARIFY = ServerRequest("srq-2", "clarify", {"questions": [{"qid": "q1", "question": "Which?", "choices": ["a", "b"]}]})
SECRET = ServerRequest("srq-3", "secret", {"env_var": "TOKEN"})


def mode_row(app: App) -> str:
    return without_badge(line_text(app._info_line(100)))


class QuestionKeyTests(unittest.TestCase):
    def test_an_open_question_puts_its_keys_on_the_info_line_and_esc_means_one_thing(self) -> None:
        cases = [
            (APPROVAL, "↑↓ pick · enter confirms · d or esc denies and stops"),
            (CLARIFY, "Enter to select · ↑↓ to navigate · Esc to cancel"),
            (SECRET, "type it · enter sends · esc declines"),
        ]
        for request, keys in cases:
            with self.subTest(method=request.method):
                app, _client = make_app(busy=True)
                app._on_server_request(request)
                if request.method == "clarify":
                    # A framed question says its keys on its own row under its bottom rule, not on the info line.
                    self.assertIn(keys, [line_text(row).strip() for row in app._slot_lines(100, 24)])
                    self.assertNotIn("esc", mode_row(app).casefold())
                else:
                    self.assertIn(keys, mode_row(app))
                self.assertNotIn("esc interrupt", mode_row(app))
                tail = app._tail(100)  # a framed question draws no waiting row: its key row carries the clock
                self.assertNotIn("esc to interrupt", line_text(tail[-1]) if tail else "")  # the working row too

    def test_an_approval_with_no_turn_running_says_deny_not_stop(self) -> None:
        # A subagent that outlived the turn can still ask; nothing would be interrupted then.
        app, client = make_app(busy=False)
        app._on_server_request(APPROVAL)
        self.assertIn("↑↓ pick · enter confirms · d or esc denies", mode_row(app))
        self.assertNotIn("stops", mode_row(app))
        app.turn_pending = True
        self.assertIn("d or esc denies and stops", mode_row(app))

    def test_without_a_question_the_working_row_offers_the_interrupt_and_only_it(self) -> None:
        # Review B: the info line's `esc interrupt` repeated the working row's `esc to interrupt`.
        app, _client = make_app(busy=True)
        self.assertIn("esc to interrupt", line_text(app._tail(100)[-2]))  # the working row, its tip under it
        self.assertNotIn("esc", mode_row(app))


class EscMeaningTests(unittest.TestCase):
    """Whatever has Esc during a turn, the screen offers Esc for one thing only: the interrupt only when Esc does it."""

    def screen_says(self, app: App) -> str:
        app._render()
        return "\n".join(app.terminal.screen.lines())  # type: ignore[attr-defined]

    def states(self) -> list[tuple[str, App, object]]:
        from test_tui_agent_view import STARTS, relay
        from omh.tui.keys import CHAR, DOWN, Key

        draft, client = make_app(busy=True, cols=100)
        from test_tui_modes import type_text

        type_text(draft, "a draft")  # Esc arms the clear
        listed, listed_client = agent_app(busy=True, frames=[], cols=100)
        relay(listed, STARTS)
        listed._on_input(Key(DOWN))  # the agent list: Esc goes back
        steering, steering_client = agent_app(busy=True, frames=[], cols=100)
        relay(steering, STARTS)
        steering._on_input(Key(DOWN))
        steering._on_input(Key(CHAR, "s"))  # Esc cancels the steer
        searching, searching_client = make_app(busy=True, cols=100)
        searching.composer.history = ["an older prompt"]
        searching._on_input(Key(CHAR, "r", ctrl=True))  # Esc cancels the search
        return [("draft", draft, client), ("agent list", listed, listed_client),
                ("agent steer", steering, steering_client), ("history search", searching, searching_client)]

    def test_no_state_that_gives_esc_another_meaning_offers_it_for_the_interrupt(self) -> None:
        from omh.tui.keys import ESCAPE, Key

        for label, app, client in self.states():
            with self.subTest(state=label):
                said = self.screen_says(app)
                self.assertNotIn("esc to interrupt", said)
                self.assertNotIn("esc interrupt", said)
                before = len(client.calls)  # type: ignore[attr-defined]
                app._on_input(Key(ESCAPE))
                self.assertNotIn("session.interrupt", [method for method, _ in client.calls[before:]])  # type: ignore[attr-defined]

    def test_an_empty_composer_during_a_turn_offers_it_and_esc_does_it(self) -> None:
        from omh.tui.keys import ESCAPE, Key

        app, client = make_app(busy=True, cols=100)
        said = self.screen_says(app)
        self.assertEqual(said.count("esc to interrupt"), 1)  # offered once, on the working row
        self.assertNotIn("esc interrupt", said)
        app._on_input(Key(ESCAPE))
        self.assertEqual(client.calls[-1][0], "session.interrupt")


class NarrowSayTests(unittest.TestCase):
    """What the next key does keeps its point on a narrow info line: a shorter form, never a cut-off long one."""

    def rewind_row(self, cols: int, agents: bool, mode: str = "normal", effort: str = "") -> str:
        from test_tui_agent_view import STARTS, relay
        from test_tui_modes import show_mode
        from omh.tui.app import Rewind

        app, _client = agent_app(busy=False, frames=[], cols=cols)
        if agents:
            relay(app, STARTS)  # the agents from the turn before stay counted on the row
        show_mode(app, mode)
        app.effort = effort
        app.rewind = Rewind(row_id=7, ordinal=2, before=())
        return line_text(app._info_line(cols))

    def steer_row(self, cols: int, mode: str = "normal", effort: str = "") -> str:
        from test_tui_agent_view import STARTS, relay
        from test_tui_modes import show_mode
        from omh.tui.keys import CHAR, DOWN, Key

        app, _client = agent_app(busy=True, frames=[], cols=cols)
        relay(app, STARTS)
        show_mode(app, mode)
        app.effort = effort
        app._on_input(Key(DOWN))
        app._on_input(Key(CHAR, "s"))
        return line_text(app._info_line(cols))

    def test_the_right_side_and_a_mode_label_give_way_before_the_rewind_or_steer_is_cut(self) -> None:
        from omh.tui.frame import MODE_ACCEPT_PLAN, MODE_PLAN

        for cols, mode, effort in ((40, MODE_PLAN, "high"), (60, MODE_ACCEPT_PLAN, "xhigh")):
            with self.subTest(cols=cols, mode=mode, effort=effort):
                rewind = self.rewind_row(cols, agents=False, mode=mode, effort=effort)
                self.assertTrue(rewind.rstrip().endswith("⏪ replaces #2+ · esc"), rewind)
                self.assertNotIn("effort", rewind)  # the right side went first
                steer = self.steer_row(cols, mode=mode, effort=effort)
                self.assertTrue(steer.rstrip().endswith("↪ steer · esc cancels"), steer)
                self.assertIn("plan mode on", steer)  # the label always stays
        # Once the say form has shortened, the right side takes the room it left over.
        row = self.rewind_row(71, agents=False, mode=MODE_PLAN, effort="high")
        self.assertTrue(row.endswith("⏪ replaces #2 and later · esc cancels   effort high"), row)
        self.assertNotIn("effort", self.rewind_row(70, agents=False, mode=MODE_PLAN, effort="high"))

    def test_at_forty_columns_with_accept_and_plan_the_labels_shorten_before_the_say_form_is_cut(self) -> None:
        from omh.tui.frame import MODE_ACCEPT_PLAN

        for effort in ("", "xhigh"):
            with self.subTest(effort=effort):
                rewind = self.rewind_row(40, agents=False, mode=MODE_ACCEPT_PLAN, effort=effort)
                steer = self.steer_row(40, mode=MODE_ACCEPT_PLAN, effort=effort)
                self.assertTrue(rewind.rstrip().endswith("⏪ replaces #2+ · esc"), rewind)
                self.assertTrue(steer.rstrip().endswith("↪ steer · esc cancels"), steer)
                for row in (rewind, steer):
                    self.assertTrue(row.startswith(INFO_INSET + "⏵⏵") and "⏸" in row, row)  # both modes are still named
                    self.assertFalse(row.rstrip().endswith("…"), row)
                    self.assertLessEqual(len(row), 40)

    def test_the_labels_keep_their_words_where_the_say_form_fits_beside_them(self) -> None:
        from omh.tui.frame import MODE_ACCEPT_PLAN

        for cols in (60, 100):
            with self.subTest(cols=cols):
                row = self.rewind_row(cols, agents=False, mode=MODE_ACCEPT_PLAN)
                self.assertTrue(row.startswith(INFO_INSET + "⏵⏵ accept all on · ⏸ plan mode on · ⏪"), row)

    def test_a_question_keeps_its_way_out_at_forty_columns_with_accept_and_plan(self) -> None:
        from test_tui_modes import show_mode
        from omh.tui.frame import MODE_ACCEPT_PLAN

        app, _client = make_app(busy=True, cols=40)
        show_mode(app, MODE_ACCEPT_PLAN)
        app._on_server_request(CLARIFY)
        row = line_text(app._info_line(40))
        self.assertTrue(row.startswith(INFO_INSET + "⏵⏵") and "⏸" in row, row)
        # The way out is on the question's own key row, which keeps it at forty columns.
        self.assertTrue(line_text(app._slot_lines(40, 24)[-1]).rstrip().endswith("Esc to cancel"))

    def test_the_right_side_gives_way_before_the_count_or_the_steered_agents_name(self) -> None:
        row = self.steer_row(100, effort="high")
        self.assertIn("steering find usages of", row)
        self.assertIn("2 agents · ↓ agents", row)  # the count, whole
        self.assertNotIn("effort", row)
        wide = self.steer_row(140, effort="high")
        self.assertIn("steering find usages of: enter sends it to that agent · esc cancels", wide)
        self.assertTrue(wide.endswith("effort high"), wide)

    def test_a_rewind_keeps_what_it_replaces_and_how_to_cancel_at_every_width(self) -> None:
        for cols in (100, 60, 40):
            for agents in (False, True):
                with self.subTest(cols=cols, agents=agents):
                    row = self.rewind_row(cols, agents)
                    self.assertIn("replaces", row)
                    self.assertTrue(any(said in row for said in ("#2 and everything after it", "#2 and later", "#2+")), row)
                    self.assertIn("esc", row)
                    self.assertFalse(row.rstrip().endswith("…"), row)
        self.assertIn("replaces prompt #2 and everything after it · esc cancels", self.rewind_row(100, False))

    def test_an_agent_steer_keeps_esc_cancels_at_every_width_with_the_count_shown(self) -> None:
        for cols in (100, 80, 60, 40):
            with self.subTest(cols=cols):
                row = self.steer_row(cols)
                self.assertIn("esc cancels", row)
                self.assertIn("steer", row)
                self.assertFalse(row.rstrip().endswith("…"), row)
                if cols >= 60:  # the count gives way before the agent's name does
                    self.assertIn("steering find usages of", row)


class CountMarkTests(unittest.TestCase):
    def test_the_counts_last_mark_says_what_down_opens(self) -> None:
        self.assertEqual(OPEN_MARK, "↓ agents")
        app, _client = agent_app()
        self.assertEqual(line_text(app._agent_chip(120)), "2 agents · ↓ agents")


class NarrowApprovalTests(unittest.TestCase):
    COMMAND = "find . -name '*.pyc' -delete && echo done with a long tail of words"

    def rows(self, width: int) -> list[str]:
        slot = open_request("srq", "approval", {"command": self.COMMAND, "description": "delete in root path"})
        return lines_text(slot.lines(width, DEFAULT_THEME, 8))

    def test_the_info_line_keeps_a_way_to_deny_at_sixty_and_forty_columns(self) -> None:
        for width in (60, 40):
            with self.subTest(width=width):
                app, _client = make_app(busy=True, cols=width)
                app.effort = "high"
                app._on_server_request(ServerRequest("srq-1", "approval", {"command": self.COMMAND}))
                row = line_text(app._info_line(width))
                self.assertIn("esc denies", row)
                self.assertLessEqual(len(row), width)
                self.assertIn("▌ ❯ ✗ deny", self.rows(width))

    def test_a_wrapped_command_keeps_its_indent(self) -> None:
        # One command, so it is listed whole, wrapped under the indent (two would each fit on a row of their own).
        slot = open_request("srq", "approval", {"command": self.COMMAND.replace(" && ", " -o -exec "),
                                                "description": "delete in root path"})
        rows = lines_text(slot.lines(50, DEFAULT_THEME, 20))
        command_rows = [row for row in rows[1 : rows.index("▌ ❯ ✗ deny")] if row.strip("▌ ─")]  # past the spacing
        self.assertGreater(len(command_rows), 1)
        for row in command_rows:
            self.assertTrue(row.startswith("▌   "), rows)


class BannerTests(unittest.TestCase):
    def test_the_banner_is_one_row_without_the_model_or_the_key_hint(self) -> None:
        rows = banner_lines(cwd="~/project", resumed="", theme=DEFAULT_THEME, width=100)
        self.assertEqual(len(rows), 2)
        self.assertEqual(line_text(rows[0]).split(" · ", 1)[1], "~/project")
        self.assertEqual(rows[1], ())
        resumed = line_text(banner_lines(cwd="~/project", resumed="abc", theme=DEFAULT_THEME, width=100)[0])
        self.assertIn("resumed abc · ~/project", resumed)

    def last_session(self, app: App, client: object, sessions: list[dict]) -> None:
        (call,) = [index for index, (method, _params) in enumerate(client.calls) if method == "session.list"]  # type: ignore[attr-defined]
        app._on_response(Response(call + 1, {"sessions": sessions}, None))

    def test_a_fresh_session_names_the_last_one_and_how_to_resume_it(self) -> None:
        app, client = make_app()
        app.stored_id = "now"
        app._ask_last_session()
        self.assertIn(("session.list", {"limit": 3}), client.calls)
        self.last_session(app, client, [
            {"id": "now", "title": "", "message_count": 0, "started_at": 0},
            {"id": "opened-and-left", "title": "", "message_count": 0, "started_at": 0},  # nothing to go back to
            {"id": "earlier", "title": "fix the flaky test", "message_count": 12, "started_at": 0},
        ])
        notice = [block.text for block in app.transcript.blocks if isinstance(block, NoticeBlock)]
        self.assertEqual(notice, ["last session: fix the flaky test · /resume earlier reopens it"])  # the notice mark only

    def test_a_hermes_that_does_not_know_session_list_costs_the_notice_not_the_session(self) -> None:
        app, client = make_app()
        app._ask_last_session()
        answer(app, client, error={"code": -32601, "message": "Method not found"})
        self.assertIsNone(app.exit_code)
        self.assertEqual(app.transcript.blocks, [])

    def test_nothing_is_said_once_the_person_has_started_or_without_an_earlier_session(self) -> None:
        app, client = make_app()
        app.stored_id = "now"
        app._ask_last_session()
        app._send_prompt("already typing")
        self.last_session(app, client, [{"id": "earlier", "title": "x", "message_count": 3, "started_at": 0}])
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, NoticeBlock)])
        app, client = make_app()
        app.stored_id = "now"
        app._ask_last_session()
        self.last_session(app, client, [{"id": "now", "title": "x", "message_count": 3, "started_at": 0}])
        self.assertEqual(app.transcript.blocks, [])


if __name__ == "__main__":
    unittest.main()
