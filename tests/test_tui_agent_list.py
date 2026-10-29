"""The agent list Down opens on the agent view's rows, the log view Enter opens from it, and the tail it reads.

The in-memory cases drive an `App` over the recording client from
`test_tui_modes`, with Hermes 6c61c3e27d's recorded subagent frames
(`test_tui_agent_view.relay`). A `subagent.tail` answer is handed back in the
shape `tui_gateway/methods_subagents.py` gives it: `subagent_id`, `available`,
`text`, `truncated`. The clock is the test's, so "at most one call every two
seconds" is counted, never waited for. One case runs the real loop against
the replay gateway, with the recorded frames injected into a recorded turn.
"""

from __future__ import annotations

import json
import re
import unittest

from _tui_gateway_replay import Scenario, recorded_answer, spans
from _tui_lines import INFO_INSET, lines_text, RULE_ROW, without_badge
from test_tui_agent_view import STARTS, VIEW, agent_app, agent_event, mode_row, relay, screen_info_index, view_rows
from test_tui_app import LIVE_ID, NO_TERMIOS, AppTestCase, Step, startup_answers, info_index
from test_tui_modes import SID, RecordingClient, answer, composer_index, drawn, make_app, notices, queue, steers, type_text
from test_tui_subagents import FIRST, FRAMES, SECOND
from omh.tui import gateway_contract as contract
from omh.tui.agent_view import (
    AGENT_LIST_HINT,
    TAIL_ANSWER_SECONDS,
    TAIL_MISSES_BEFORE_STOP,
    TAIL_POLL_SECONDS,
)
from omh.tui.app import EXIT_HINT, SLOT_ARM_SECONDS, App
from omh.tui.layout import AGENT_VIEW_ROWS, agent_view_cap
from omh.tui.frame import BROWSING_HINT, INFO_INSET as INFO_INSET_CELLS, MODE_NORMAL
from omh.tui.gateway import Event, Response, ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, TAB, UP, Key, KeyDecoder, Paste
from omh.tui.pager import ALT_SCREEN_OFF, ALT_SCREEN_ON, Pager
from omh.tui.session_picker import SessionPicker, SessionRow
from omh.tui.style import Span
from omh.tui.subagents import MAIN_ID
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NOTICE_WARN, TOOL_OK, TOOL_RUNNING, AssistantBlock, ToolGroup

CTRL_C = Key(CHAR, "c", ctrl=True)
TAIL_CALL = ("subagent.tail", {"session_id": SID, "subagent_id": FIRST})
TAIL = {"subagent_id": FIRST, "available": True, "text": "reading src/api/client.py\nfound 3 call sites\n", "truncated": False}
NO_TAIL = {"subagent_id": FIRST, "available": False, "text": "", "truncated": False}


def under_the_frame(app: App) -> list[str]:
    """While the agent list is open, its rows (the agent view's, under the info line) and then the info line's left
    side; with it closed, the info line's left side alone."""
    screen = drawn(app)
    info = screen_info_index(app, screen)
    rows = screen[info + 1 : info + 1 + len(app.listed)] if app.list_selected is not None else []
    return [*rows, info_left(screen[info])]


def info_left(row: str) -> str:
    """The info line's left side, after the inset it starts with under the composer: its right side (model, context,
    effort) stands 3 cells or more away; the badge at its left end taken out."""
    row = without_badge(row)
    if not row.startswith(INFO_INSET):
        raise AssertionError(f"the info line does not start {INFO_INSET_CELLS} cells in: {row!r}")
    return re.split(r" {3,}", row[INFO_INSET_CELLS:])[0]


def focused(**options: object) -> tuple[App, RecordingClient]:
    """An app whose agent list has the keys, on the first agent."""
    app, client = agent_app(**options)
    app._on_input(Key(DOWN))
    return app, client


def more_agents(app: App, count: int) -> list[str]:
    ids = [f"sa-extra-{number}" for number in range(count)]
    for number, subagent_id in enumerate(ids):
        agent_event(app, "start", subagent_id, goal=f"task {number}")
    return ids


def log_open(**options: object) -> tuple[App, RecordingClient]:
    """An app showing the first agent's log, opened from the list."""
    app, client = focused(**options)
    app._on_input(Key(ENTER))
    return app, client


def paged(app: App) -> list[str]:
    assert app.pager is not None
    return lines_text(list(app.pager.lines))


def tails(client: RecordingClient) -> list[dict]:
    return client.named("subagent.tail")


class ListFocusTests(unittest.TestCase):
    def test_down_on_an_empty_composer_gives_the_list_the_keys_on_the_first_agent(self) -> None:
        app, client = agent_app()
        self.assertEqual(len(under_the_frame(app)), 1)  # the info line, with the count
        app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, FIRST)
        rows = under_the_frame(app)
        expected, ids = app.roster.list_lines(80, DEFAULT_THEME, FIRST, 0, AGENT_VIEW_ROWS, 0.0)
        self.assertEqual(ids, (MAIN_ID, FIRST, SECOND))
        self.assertEqual(rows, [text.rstrip() for text in lines_text(expected)] + [AGENT_LIST_HINT])
        self.assertEqual(rows[0], "  ● main")
        self.assertTrue(rows[1].startswith("❯ ⠋ find usages of old_api in src/"), rows[1])
        self.assertTrue(rows[2].startswith("  ⠋ read the diff for risks"), rows[2])
        self.assertEqual(rows[-1], AGENT_LIST_HINT)
        self.assertEqual(client.calls, [])

    def test_with_no_agent_down_is_still_the_composers(self) -> None:
        app, _client = make_app()
        type_text(app, "an earlier prompt")
        app._on_input(Key(ENTER))
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "an earlier prompt")
        app._on_input(Key(DOWN))  # the input history's way back to the empty draft
        self.assertEqual((app.composer.text, app.list_selected), ("", None))
        app._on_input(Key(DOWN))
        self.assertEqual((app.composer.text, app.list_selected), ("", None))
        self.assertEqual(len(under_the_frame(app)), 1)

    def test_with_agents_down_still_walks_the_history_until_the_composer_is_empty(self) -> None:
        app, _client = make_app()
        type_text(app, "an earlier prompt")
        app._on_input(Key(ENTER))
        relay(app, STARTS)
        app._on_input(Key(UP))
        app._on_input(Key(DOWN))
        self.assertEqual((app.composer.text, app.list_selected), ("", None))
        app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, FIRST)

    def test_down_is_not_the_lists_while_something_else_has_the_keys_or_the_composer_has_text(self) -> None:
        def approval(app: App) -> None:
            app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))

        def question(app: App) -> None:
            choices = {"questions": [{"qid": "q0", "question": "Which?", "choices": ["red", "blue"]}]}
            app._on_server_request(ServerRequest("srq-1", "clarify", choices))

        def typed_answer(app: App) -> None:
            app._on_server_request(ServerRequest("srq-1", "vault.code", {}))

        def picker(app: App) -> None:
            app.picker = SessionPicker([SessionRow("stored-1", "a title", "", 0.0, 1)], current="")

        def pager(app: App) -> None:
            app.pager = Pager("history", [])

        def menu(app: App) -> None:
            type_text(app, "/he")

        def draft(app: App) -> None:
            type_text(app, "a draft")

        def path_menu(app: App) -> None:
            from omh.tui.app import PathItem

            app.path_items = [PathItem("@src/", "src/", "dir")]

        for opened in (approval, question, typed_answer, picker, pager, menu, draft, path_menu):
            with self.subTest(opened.__name__):
                now = [100.0]
                app, client = agent_app(clock=lambda: now[0])
                opened(app)
                now[0] += SLOT_ARM_SECONDS
                app._on_input(Key(DOWN))
                self.assertIsNone(app.list_selected)
                self.assertEqual((client.calls, client.answers), ([], []))

    def test_a_terminal_too_small_for_a_slot_has_no_list_to_open(self) -> None:
        for rows, cols in ((5, 80), (24, 19)):
            with self.subTest(rows=rows, cols=cols):
                app, _client = agent_app(rows=rows, cols=cols)
                app._on_input(Key(DOWN))
                self.assertIsNone(app.list_selected)
        for rows in (6, 9, 10):  # the info line says the list's keys at every height with a slot
            with self.subTest(rows=rows):
                app, _client = agent_app(rows=rows)
                app._on_input(Key(DOWN))
                self.assertEqual(app.list_selected, FIRST)

    def test_up_and_down_move_the_highlight_and_stop_at_either_end(self) -> None:
        app, _client = focused()
        seen = []
        for key in (DOWN, DOWN, DOWN, UP, UP, UP, UP, DOWN):
            app._on_input(Key(key))
            seen.append(app.list_selected)
        self.assertEqual(seen, [SECOND, SECOND, SECOND, FIRST, MAIN_ID, MAIN_ID, MAIN_ID, FIRST])
        rows = under_the_frame(app)
        self.assertEqual([row[:2] for row in rows[:3]], ["  ", "❯ ", "  "])

    def test_the_list_shows_main_and_six_agents_and_scrolls_to_keep_the_highlight_in_view(self) -> None:
        app, _client = agent_app(rows=30)  # a quarter of 30 rows is past the view's usual seven
        extra = more_agents(app, 7)  # nine agents with the two recorded ones, all running
        for number, subagent_id in enumerate(extra):  # finished: they raise no cap
            agent_event(app, "complete", subagent_id, goal=f"task {number}", status="completed")
        app._on_input(Key(DOWN))
        rows = under_the_frame(app)
        self.assertEqual(len(rows), AGENT_VIEW_ROWS + 1)
        self.assertEqual((rows[0], rows[-1]), ("  ● main", AGENT_LIST_HINT))
        self.assertIn("task 3", rows[6])
        for _ in range(8):
            app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, extra[-1])
        rows = under_the_frame(app)
        self.assertEqual(len(rows), AGENT_VIEW_ROWS + 1)
        self.assertTrue(rows[6].startswith("❯ ") and "task 6" in rows[6], rows[6])
        self.assertIn("task 0", rows[0])  # main and the two recorded agents scrolled off
        for _ in range(9):
            app._on_input(Key(UP))
        self.assertEqual(under_the_frame(app)[0], "❯ ● main")

    def test_a_short_terminal_shows_as_many_rows_as_it_can_spare(self) -> None:
        app, _client = agent_app(rows=10)
        more_agents(app, 7)
        before = view_rows(app)
        app._on_input(Key(DOWN))
        rows = under_the_frame(app)
        self.assertEqual(len(rows), agent_view_cap(10, 80, 11) + 1)  # what the view gets there, and the info line
        self.assertEqual(len(rows) - 1, before, "the list takes the view's rows, no more and no fewer")
        self.assertEqual(rows[-1], AGENT_LIST_HINT)
        self.assertTrue(rows[1].startswith("❯ "), rows)

    def test_the_composer_is_blank_while_the_list_is_open_and_comes_back_on_its_row(self) -> None:
        app, _client = agent_app()
        type_text(app, "x")
        app._set_composer("")  # an empty composer, drawn once
        before = drawn(app)
        resting, status = composer_index(before), screen_info_index(app, before)
        app._on_input(Key(DOWN))
        during = drawn(app)
        # No composer: the one `❯ ` row is the list's pointer on the highlighted agent.
        self.assertEqual([row for row in during if row.startswith("❯ ") and "old_api" not in row], [], during)
        # Its rows stay: the rules, and the browsing hint where the prompt was.
        self.assertTrue(during[resting - 1].startswith(RULE_ROW) and during[resting + 1].startswith(RULE_ROW), during)
        self.assertEqual(during[resting].strip(), BROWSING_HINT)
        self.assertEqual(screen_info_index(app, during), status)
        self.assertEqual(info_left(during[status]), AGENT_LIST_HINT)  # the info line says the list's keys
        self.assertEqual(during[status + 1 : status + 1 + len(app.listed)], under_the_frame(app)[:-1])
        app._on_input(Key(ESCAPE))
        after = drawn(app)
        self.assertEqual((composer_index(after), screen_info_index(app, after)), (resting, status))
        self.assertEqual(after, before)

    def test_the_list_is_the_views_rows_and_nothing_moves_as_it_opens(self) -> None:
        for pinned in (False, True):
            with self.subTest(pinned=pinned):
                app, _client = agent_app()
                app.transcript.add_notice("printed above the region")
                if pinned:  # output that brings the region to the screen's last row
                    for number in range(30):
                        app.transcript.add_notice(f"line {number}")
                before = drawn(app)
                info = screen_info_index(app, before)
                self.assertEqual(before[info + 1 : info + 4], VIEW)
                app._on_input(Key(DOWN))
                during = drawn(app)
                self.assertEqual(screen_info_index(app, during), info, "the info line stays on its row")
                self.assertEqual([row[2:] for row in during[info + 1 : info + 4]], [row[2:] for row in VIEW])
                self.assertTrue(during[info + 2].startswith("❯ "), during)
                top = info + 1 + len(VIEW) - app.region.height
                self.assertEqual(during[:top], before[:top])  # nothing above the region moved
                working = [index for index, row in enumerate(before) if row.startswith("✻ Working")]
                self.assertEqual(working, [index for index, row in enumerate(during) if row.startswith("✻ Working")])

    def test_no_caret_is_shown_while_the_list_has_the_keys(self) -> None:
        app, _client = focused()
        drawn(app)
        self.assertFalse(app.terminal.screen.cursor_visible)  # type: ignore[attr-defined]
        app._on_input(Key(ESCAPE))
        drawn(app)
        self.assertTrue(app.terminal.screen.cursor_visible)  # type: ignore[attr-defined]

    def test_the_count_leaves_the_info_line_while_the_list_shows_the_agents(self) -> None:
        app, _client = agent_app()
        self.assertTrue(under_the_frame(app)[0].startswith("2 agents · ↓ agents"))  # the count
        app._on_input(Key(DOWN))
        self.assertNotIn("agents", under_the_frame(app)[-1])


class ListLeaveTests(unittest.TestCase):
    def test_enter_on_main_only_leaves(self) -> None:
        app, client = focused()
        app._on_input(Key(UP))
        app._on_input(Key(ENTER))
        self.assertEqual((app.list_selected, app.pager, client.calls), (None, None, []))
        self.assertEqual(app.composer.text, "")

    def test_esc_leaves_without_interrupting_the_turn(self) -> None:
        app, client = focused()
        app._on_input(Key(ESCAPE))
        self.assertEqual((app.list_selected, client.calls), (None, []))
        self.assertEqual(len(under_the_frame(app)), 1)
        app._on_input(Key(ESCAPE))  # the list is gone: this Esc is the one that interrupts
        self.assertEqual(client.calls, [("session.interrupt", {"session_id": SID})])

    def test_ctrl_c_leaves_without_interrupting_or_arming_the_exit(self) -> None:
        for busy in (True, False):
            with self.subTest(busy=busy):
                app, client = focused(busy=busy)
                app._on_input(CTRL_C)
                self.assertEqual((app.list_selected, client.calls, notices(app), app.exit_code), (None, [], [], None))

    def test_ctrl_c_with_shift_or_alt_held_leaves_too(self) -> None:
        # As the composer takes them (kitty and modifyOtherKeys report the modifier; the legacy Alt chord is Esc).
        for key in (Key(CHAR, "c", ctrl=True, shift=True), Key(CHAR, "c", ctrl=True, alt=True, protocol=True)):
            with self.subTest(key=key):
                app, client = focused()
                app._on_input(key)
                self.assertEqual((app.list_selected, client.calls, app.exit_code), (None, [], None))

    def test_while_a_steer_is_open_the_interrupt_press_arms_the_exit_and_the_next_one_leaves(self) -> None:
        # The owner's rule (#2302) holds over a steer: the info line names the exit, and the second press makes it.
        app, client = focused()
        app._on_input(Key(CHAR, "s"))
        self.assertIsNotNone(app.agent_steer)
        app._on_input(CTRL_C)
        self.assertEqual(len(client.named("session.interrupt")), 1)
        self.assertIn(EXIT_HINT, mode_row(app))  # the row over the agent view
        app._on_input(CTRL_C)
        self.assertEqual((app.exit_code, len(client.named("session.interrupt"))), (0, 1))

    def test_a_typed_character_does_nothing_and_the_list_keeps_the_keys(self) -> None:
        app, client = focused()
        before = under_the_frame(app)
        type_text(app, "hi 12/?")
        self.assertEqual((app.list_selected, app.composer.text, client.calls), (FIRST, "", []))
        self.assertEqual(under_the_frame(app), before)

    def test_left_and_q_leave_as_esc_does(self) -> None:
        for key in (Key(LEFT), Key(CHAR, "q")):
            with self.subTest(key=key):
                app, client = focused()
                app._on_input(key)
                self.assertEqual((app.list_selected, app.composer.text, client.calls), (None, "", []))

    def test_esc_then_a_command_in_one_read_leaves_the_list_and_types_the_command(self) -> None:
        # The bytes are Alt+/ and then the rest: the chord leaves the list, then the composer types its `/`.
        app, client = focused()
        for event in KeyDecoder().feed(b"\x1b/quit"):
            app._on_input(event)
        self.assertEqual((app.list_selected, app.composer.text, client.calls), (None, "/quit", []))

    def test_a_paste_does_nothing(self) -> None:
        app, _client = focused()
        app._on_input(Paste("two\nlines"))
        self.assertEqual((app.list_selected, app.composer.text), (FIRST, ""))

    def test_any_other_key_does_nothing(self) -> None:
        for key in (Key(TAB, shift=True), Key(CHAR, "?"), Key(CHAR, "t", ctrl=True), Key(CHAR, "r", ctrl=True), Key(TAB),
                    Key(RIGHT), Key(CHAR, "d", ctrl=True)):
            with self.subTest(key=key):
                app, client = focused()
                app._on_input(key)
                self.assertEqual((app.list_selected, client.calls, app.pager, app.search), (FIRST, [], None, None))
                self.assertIsNone(app.exit_code)

    def test_an_approval_arriving_closes_the_list_and_the_enter_aimed_at_it_answers_nothing(self) -> None:
        now = [100.0]
        app, client = focused(clock=lambda: now[0])
        self.assertEqual(app.list_selected, FIRST)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] += SLOT_ARM_SECONDS / 2
        app._on_input(Key(ENTER))  # on its way to "view log" when the approval opened
        self.assertEqual(client.answers, [])
        self.assertEqual((app.list_selected, app.pager), (None, None))
        self.assertIsNotNone(app.slot)
        screen = drawn(app)
        status = screen_info_index(app, screen)
        # The approval stands where the composer was, the row under it is the info line, with its keys, and the
        # agent view stays under that.
        self.assertEqual(screen[status - 1], "▌   ✎ no, and tell Hermes what to do instead")  # the approval's last row
        self.assertIn("esc denies", screen[status])
        self.assertEqual([row[4:] for row in screen[status + 1 : status + 4]], [row[4:] for row in VIEW])
        now[0] += SLOT_ARM_SECONDS
        for key in (Key(DOWN), Key(UP)):
            app._on_input(key)  # the approval takes every key: these two move its highlight there and back
        self.assertEqual((app.list_selected, client.answers), (None, []))
        app._on_input(Key(ENTER))  # a deliberate Enter on deny: the explicit deny
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])
        self.assertIsNone(app.list_selected)  # and answering it does not bring the list back
        self.assertEqual(client.calls, [("session.interrupt", {"session_id": SID})])  # the deny stops the turn; no log

    def test_a_question_answered_with_text_closes_the_list_too(self) -> None:
        now = [100.0]
        app, client = focused(clock=lambda: now[0])
        app._on_server_request(ServerRequest("srq-1", "vault.code", {}))
        app._on_input(Key(ENTER))
        self.assertEqual((client.answers, app.list_selected, app.pager), ([], None, None))

    def test_the_session_picker_opening_closes_the_list(self) -> None:
        app, client = focused()
        app._sessions("")
        answer(app, client, recorded_answer("session", "session_list")["result"])
        self.assertIsNotNone(app.picker)
        self.assertIsNone(app.list_selected)
        app._on_input(Key(DOWN))  # the picker's key now
        self.assertIsNone(app.list_selected)

    def test_a_queued_prompt_starting_its_turn_empties_the_roster_and_closes_the_list(self) -> None:
        app, _client = focused()
        queue(app, "the next task")
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(len(under_the_frame(app)), 1)
        self.assertIsNone(app.list_selected)

    def test_a_terminal_resized_too_small_for_a_slot_closes_the_list(self) -> None:
        app, _client = focused()
        app.terminal.screen.resize(5, 80)  # type: ignore[attr-defined]
        app._on_resize()
        app._full_redraw()
        app.redraw_at = None
        drawn(app)
        self.assertIsNone(app.list_selected)

    def test_a_highlighted_agent_that_is_gone_leaves_the_highlight_on_main(self) -> None:
        app, _client = focused()
        app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, SECOND)
        app.roster.clear()
        agent_event(app, "start", FIRST)
        self.assertEqual(under_the_frame(app)[0], "❯ ● main")
        self.assertEqual(app.list_selected, MAIN_ID)


class AgentLogTests(unittest.TestCase):
    def test_enter_on_an_agent_opens_its_log_on_the_alternate_screen(self) -> None:
        app, _client = focused(frames=FRAMES[:6])
        app._on_input(Key(ENTER))
        self.assertEqual(app.log_agent, FIRST)
        self.assertIn(ALT_SCREEN_ON, app.terminal.writes)  # type: ignore[attr-defined]
        self.assertEqual(paged(app), lines_text(app.roster.log_lines(FIRST, 80, DEFAULT_THEME, 0.0)))
        self.assertEqual(
            paged(app),
            [
                "find usages of old_api in src/ and list every call site",
                "running · 0s · 3 tools · deepseek-v4.1-flash",
                "",
                "▸ I will grep for old_api first",
                "● search_files  old_api",
                "● read_file  src/api/client.py",
                "● terminal",
            ],
        )
        assert app.pager is not None
        self.assertEqual(app.pager.title, "find usages of · ←/→ agents")
        screen = drawn(app)
        self.assertEqual(screen[0], "find usages of old_api in src/ and list every call site")
        self.assertIn("find usages of · ←/→ agents", screen[-1])

    def test_q_and_esc_come_back_to_the_list_on_the_agent_that_was_shown(self) -> None:
        for key in (Key(CHAR, "q"), Key(ESCAPE)):
            with self.subTest(key=key):
                app, client = log_open()
                app._on_input(key)
                self.assertEqual((app.pager, app.log_agent, app.list_selected), (None, "", FIRST))
                self.assertIn(ALT_SCREEN_OFF, "".join(app.terminal.writes))  # type: ignore[attr-defined]
                self.assertEqual(under_the_frame(app)[-1], AGENT_LIST_HINT)
                self.assertEqual(client.named("session.interrupt"), [])  # that Esc left the log, nothing more

    def test_the_log_redraws_as_the_agents_events_arrive(self) -> None:
        now = [0.0]
        app, _client = log_open(clock=lambda: now[0])
        self.assertEqual(paged(app)[-1], "no output yet")
        now[0] = 4.0
        agent_event(app, "tool", tool_name="read_file", tool_preview="src/a.py", tool_count=1)
        agent_event(app, "tool", SECOND, tool_name="terminal", tool_count=1)  # another agent's: not this log's
        drawn(app)
        self.assertEqual(paged(app)[1:], ["running · 4s · 1 tool · deepseek-v4.1-flash", "", "● read_file  src/a.py"])
        agent_event(app, "complete", status="completed", summary="three call sites", duration_seconds=5.0, tool_count=1)
        drawn(app)
        self.assertEqual(paged(app)[1], "completed · 5s · 1 tool · deepseek-v4.1-flash")
        self.assertEqual(paged(app)[-1], "three call sites")

    def test_a_tick_with_nothing_new_repaints_nothing_and_a_full_redraw_under_the_log_paints_it_all(self) -> None:
        now = [0.0]
        app, _client = log_open(clock=lambda: now[0])
        screen = drawn(app)
        writes = len(app.terminal.writes)  # type: ignore[attr-defined]
        app._render()
        self.assertEqual("".join(app.terminal.writes[writes:]), "")  # type: ignore[attr-defined]
        now[0] = 3.0  # the header's clock moves: that row alone repaints
        app._render()
        tick = "".join(app.terminal.writes[writes:])  # type: ignore[attr-defined]
        self.assertIn(" · 3s · 0 tools", tick)
        self.assertNotIn("find usages of old_api", tick)
        app._full_redraw()  # it clears the screen the log is on
        self.assertEqual(drawn(app)[0], screen[0])

    def test_a_log_read_at_its_end_follows_new_rows_and_one_scrolled_up_stays(self) -> None:
        app, _client = agent_app()
        for number in range(60):
            agent_event(app, "tool", tool_name=f"tool_{number}", tool_count=number + 1)
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        drawn(app)
        assert app.pager is not None
        body = app.pager.body_rows(24)
        self.assertEqual(app.pager.top, len(app.pager.lines) - body)  # opened on its newest rows
        self.assertIn("tool_59", app.terminal.screen.lines()[body - 1])  # type: ignore[attr-defined]
        agent_event(app, "tool", tool_name="tool_60", tool_count=61)
        drawn(app)
        self.assertEqual(app.pager.top, len(app.pager.lines) - body)
        self.assertIn("tool_60", app.terminal.screen.lines()[body - 1])  # type: ignore[attr-defined]
        for _ in range(5):
            app._on_input(Key(CHAR, "k"))
        held = app.pager.top
        agent_event(app, "tool", tool_name="tool_61", tool_count=62)
        drawn(app)
        self.assertEqual(app.pager.top, held)
        self.assertNotIn("tool_61", "\n".join(app.terminal.screen.lines()[:body]))  # type: ignore[attr-defined]

    def test_left_and_right_move_to_the_agent_before_and_after_and_stop_at_either_end(self) -> None:
        app, _client = log_open()
        seen = []
        for key in (RIGHT, RIGHT, LEFT, LEFT):
            app._on_input(Key(key))
            assert app.pager is not None
            seen.append((app.log_agent, app.pager.title, paged(app)[0]))
        first = (FIRST, "find usages of · ←/→ agents", "find usages of old_api in src/ and list every call site")
        second = (SECOND, "read the diff · ←/→ agents", "read the diff for risks")
        self.assertEqual(seen, [second, second, first, first])
        app._on_input(Key(RIGHT))
        app._on_input(Key(CHAR, "q"))
        self.assertEqual(app.list_selected, SECOND)  # back in the list, on the agent last shown

    def test_left_and_right_in_any_other_pager_do_nothing(self) -> None:
        app, _client = agent_app()
        app._on_input(Key(CHAR, "?"))
        assert app.pager is not None
        before = (app.pager.title, list(app.pager.lines), app.pager.top)
        for key in (LEFT, RIGHT):
            app._on_input(Key(key))
        self.assertEqual((app.pager.title, list(app.pager.lines), app.pager.top), before)
        self.assertEqual(app.log_agent, "")

    def test_a_log_whose_agent_a_new_turn_dropped_keeps_its_rows(self) -> None:
        app, client = log_open(frames=FRAMES[:6])
        shown = paged(app)
        app.roster.clear()
        agent_event(app, "start", "sa-new", goal="the next turn's agent")
        drawn(app)
        self.assertEqual(paged(app), shown)
        for key in (LEFT, RIGHT):
            app._on_input(Key(key))
        self.assertEqual((app.log_agent, paged(app)), (FIRST, shown))
        app._ask_tail_when_due()
        self.assertEqual(tails(client), [])

    def test_an_approval_arriving_closes_the_log_and_the_list_under_it(self) -> None:
        now = [100.0]
        app, client = log_open(clock=lambda: now[0])
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        app._on_input(Key(ENTER))
        self.assertEqual((app.pager, app.log_agent, client.answers), (None, "", []))
        drawn(app)
        self.assertIsNone(app.list_selected)
        self.assertIsNotNone(app.slot)

    def test_a_log_is_not_opened_for_an_agent_the_roster_does_not_hold(self) -> None:
        app, _client = agent_app()
        app._open_agent_log("sa-nobody")
        self.assertEqual((app.pager, app.log_agent), (None, ""))


class OutputWhileAViewIsOpenTests(unittest.TestCase):
    """A command's long output answered while a view has the alternate screen: the view stays, the output waits.

    A command's output never opens a pager, so it lands in the transcript,
    under the command's echo, and shows there once the person leaves the view.
    """

    LONG = "\n".join(f"usage row {number}" for number in range(40))

    def sent(self, app: App, command: str) -> None:
        type_text(app, command)
        app._on_input(Key(ENTER))

    def check_waited(self, app: App, view: list[str]) -> None:
        self.assertEqual(drawn(app), view)  # the view is still the one drawn
        self.assertEqual(notices(app)[-1], self.LONG)
        self.assertEqual("".join(app.terminal.writes).count(ALT_SCREEN_ON), 1)  # type: ignore[attr-defined]

    def test_behind_an_agents_log(self) -> None:
        app, client = agent_app()
        self.sent(app, "/usage")
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        view = drawn(app)
        answer(app, client, {"output": self.LONG})
        self.assertEqual(app.log_agent, FIRST)
        self.check_waited(app, view)
        self.assertIn("find usages of · ←/→ agents", view[-1])
        app._on_input(Key(CHAR, "q"))
        app._on_input(Key(ESCAPE))
        drawn(app)
        history = app.terminal.screen.history() + app.terminal.screen.lines()  # type: ignore[attr-defined]
        self.assertIn("    ⎿  usage row 0", history)  # in the transcript, under its echo, once the view is left
        self.assertIn("       … +28 rows · ctrl+o shows all", history)

    def test_behind_the_key_list(self) -> None:
        app, client = agent_app()
        self.sent(app, "/usage")
        app._on_input(Key(CHAR, "?"))
        view = drawn(app)
        answer(app, client, {"output": self.LONG})
        self.check_waited(app, view)
        self.assertIn(" keys · ", view[-1])

    def test_behind_the_history_pager(self) -> None:
        app, client = agent_app()
        self.sent(app, "/usage")
        app.transcript.add_notice("an earlier notice")
        self.sent(app, "/history")
        view = drawn(app)
        self.assertIn(" history · ", view[-1])
        answer(app, client, {"output": self.LONG})
        self.check_waited(app, view)

    def test_a_pager_that_is_not_the_log_view_is_never_drawn_as_an_agents_log(self) -> None:
        app, _client = log_open()
        app._open_pager("history", [(Span("an earlier turn"),)])
        self.assertEqual(app.log_agent, "")
        screen = drawn(app)
        self.assertEqual(screen[0], "an earlier turn")
        self.assertIn(" history · ", screen[-1])
        self.assertEqual("".join(app.terminal.writes).count(ALT_SCREEN_ON), 1)  # type: ignore[attr-defined]


def recorded_parity(segment: str) -> tuple[dict, dict]:
    """The recorded call's params and its answer's result, from tests/fixtures/tui_gateway/parity.jsonl."""
    from test_tui_gateway_contract import recorded_rows

    rows = recorded_rows("parity", segment)
    call = next(row["frame"] for row in rows if row["dir"] == "out")
    return call["params"], next(row["frame"] for row in rows if row["dir"] == "in")["result"]


class AgentActionTests(unittest.TestCase):
    """`x` interrupts the highlighted agent once a second `x` confirms; `s` steers it with text the person sends."""

    def test_x_asks_once_and_a_second_x_interrupts_the_highlighted_agent(self) -> None:
        app, client = focused()
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])
        self.assertEqual(under_the_frame(app)[-1], "x again interrupts find usages of · any other key cancels")
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [("subagent.interrupt", {"session_id": SID, "subagent_id": FIRST})])
        answer(app, client, {"found": True, "subagent_id": FIRST})
        self.assertEqual(notices(app)[-1], "Interrupted find usages of.")
        self.assertEqual(app.list_selected, FIRST)  # the list stays open on it

    def test_an_agent_that_had_already_finished_is_said_so(self) -> None:
        params, result = recorded_parity("subagent_interrupt")
        self.assertEqual(set(params), {"session_id", "subagent_id"})
        app, client = focused()
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(CHAR, "x"))
        answer(app, client, result)  # Hermes 6c61c3e27d: found false
        self.assertEqual(notices(app)[-1], "find usages of had already finished.")

    def test_any_other_key_cancels_the_question_and_does_what_it_does(self) -> None:
        app, client = focused()
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, SECOND)
        app._on_input(Key(CHAR, "x"))
        self.assertIn("x again interrupts read the diff", under_the_frame(app)[-1])
        self.assertEqual(client.calls, [])
        app, client = focused()
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(DOWN))
        app._on_input(Key(UP))  # back on the first agent: its question ended with the Down
        self.assertEqual(under_the_frame(app)[-1], AGENT_LIST_HINT)
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])  # a first x again, not the second

    def test_on_main_or_a_finished_agent_x_sends_nothing(self) -> None:
        app, client = focused()
        app._on_input(Key(UP))  # main
        app._on_input(Key(CHAR, "x"))
        self.assertEqual((app.list_selected, app.composer.text), (MAIN_ID, ""))  # nothing to act on: the key does nothing
        app, client = focused(frames=FRAMES)  # both finished
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])
        self.assertIn("has finished", notices(app)[-1])

    def test_s_steers_the_highlighted_agent_with_the_text_sent_next(self) -> None:
        app, client = focused()
        app._on_input(Key(CHAR, "s"))
        self.assertIsNone(app.list_selected)  # the composer has the keys for the text
        self.assertIn("steering find usages of", " ".join(under_the_frame(app)))
        type_text(app, "skip the tests folder")
        app._on_input(Key(ENTER))
        self.assertEqual(
            client.calls,
            [("subagent.steer", {"session_id": SID, "subagent_id": FIRST, "text": "skip the tests folder"})],
        )
        answer(app, client, {"status": "queued", "subagent_id": FIRST, "text": "skip the tests folder"})
        self.assertEqual(steers(app)[-1], "↪ steer queued by Hermes · find usages of: skip the tests folder")
        self.assertIsNone(app.agent_steer)

    def test_a_steer_hermes_rejects_comes_back_to_the_composer(self) -> None:
        params, result = recorded_parity("subagent_steer")
        self.assertEqual(set(params), {"session_id", "subagent_id", "text"})
        app, client = focused()
        app._on_input(Key(CHAR, "s"))
        type_text(app, "use the other file")
        app._on_input(Key(ENTER))
        answer(app, client, result)  # Hermes 6c61c3e27d: rejected
        self.assertIn("Hermes did not take the steer", steers(app)[-1])
        self.assertTrue(steers(app)[-1].endswith("· find usages of: use the other file"), steers(app))
        self.assertEqual(app.composer.text, "use the other file")
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])

    def test_a_steer_hermes_refuses_says_why_and_comes_back_to_the_composer(self) -> None:
        app, client = focused()
        app._on_input(Key(CHAR, "s"))
        type_text(app, "use it")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 4009, "message": "agent busy."})
        self.assertEqual(
            steers(app)[-1],
            "⧗ back in the composer — Hermes did not take the steer (agent busy) · find usages of: use it",
        )
        self.assertEqual(app.composer.text, "use it")
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])

    def test_a_steer_settled_after_its_session_was_left_comes_back_with_a_notice_naming_that_session(self) -> None:
        # As the main steer's: the text comes back, never to the session now open, and a notice says whose it was.
        answers = {
            "taken": ({"status": "queued", "subagent_id": FIRST, "text": "use it"}, None),
            "rejected": (recorded_parity("subagent_steer")[1], None),
            "refused": (None, {"code": 4009, "message": "agent busy."}),
            "unanswered": None,
        }
        for name, answered in answers.items():
            for leave in ("new", "switch"):
                with self.subTest(answer=name, leave=leave):
                    now = [0.0]
                    app, client = focused(clock=lambda: now[0])
                    app.stored_id = "stored-1"
                    app._on_input(Key(CHAR, "s"))
                    type_text(app, "use it")
                    app._on_input(Key(ENTER))
                    steer = len(client.calls)
                    if leave == "new":
                        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
                    else:
                        app._on_session_resumed("stored-2", {"session_id": "live-2", "stored_session_id": "stored-2"})
                    if answered is None:
                        now[0] += 3600
                        app._expire_calls()
                    else:
                        app._on_response(Response(steer, *answered))
                    self.assertEqual(app.composer.text, "use it")
                    self.assertEqual(
                        [method for method, _params in client.calls[steer:]], ["session.close", "commands.catalog"]
                    )
                    said = [text for text in notices(app, NOTICE_WARN) if "stored-1" in text]
                    self.assertEqual(len(said), 1, notices(app))
                    self.assertIn("find usages of", said[0])
                    self.assertIn("not sent to this one", said[0])

    def test_an_agent_whose_id_is_blank_is_not_listed_so_no_steer_row_can_be_left_held(self) -> None:
        app, client = make_app(busy=True, clock=lambda: 0.0)
        app._on_event(Event("subagent.start", SID, {"subagent_id": " ", "goal": "read the diff", "depth": 1}))
        self.assertEqual(app.roster.agents, {})
        app._on_input(Key(DOWN))  # no list to open
        self.assertIsNone(app.list_selected)
        self.assertEqual(client.calls, [])

    def test_esc_cancels_the_steer_keeps_the_text_as_a_draft_and_nothing_is_sent(self) -> None:
        app, client = focused()
        app._on_input(Key(CHAR, "s"))
        type_text(app, "never mind")
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.agent_steer)
        self.assertEqual(app.composer.text, "never mind")  # an ordinary draft now
        self.assertEqual(client.calls, [])
        app._on_input(Key(ESCAPE))  # as for any draft: the first Esc arms the clear
        self.assertEqual((app.composer.text, app.escape_armed[0]), ("never mind", "clear"))  # type: ignore[index]
        app._on_input(Key(ESCAPE))
        self.assertEqual(app.composer.text, "")
        self.assertEqual(client.calls, [])

    def test_a_narrow_list_keeps_its_keys_and_the_way_back(self) -> None:
        for cols, said in ((100, AGENT_LIST_HINT), (42, "⏎ log · x interrupt · s steer · esc back"),  # and the inset
                           (34, "x interrupt · s steer · esc back")):
            with self.subTest(cols=cols):
                app, _client = focused(cols=cols)
                self.assertEqual(under_the_frame(app)[-1].rstrip(), said)

    def test_the_hint_names_both_keys(self) -> None:
        app, _client = focused()
        self.assertEqual(under_the_frame(app)[-1], AGENT_LIST_HINT)
        self.assertIn("x interrupt", AGENT_LIST_HINT)
        self.assertIn("s steer", AGENT_LIST_HINT)

    def test_the_contract_declares_both_calls_with_a_session_and_an_agent(self) -> None:
        self.assertEqual(contract.CLIENT_METHODS["subagent.interrupt"], {"session_id", "subagent_id"})
        self.assertEqual(contract.CLIENT_METHODS["subagent.steer"], {"session_id", "subagent_id", "text"})
        self.assertNotEqual(contract.call_problem("subagent.interrupt", {"session_id": SID}), "")
        self.assertNotEqual(contract.call_problem("subagent.steer", {"session_id": SID, "subagent_id": FIRST, "text": " "}), "")
        self.assertEqual(contract.call_problem("subagent.steer", recorded_parity("subagent_steer")[0]), "")


class AgentRowsDuringATurnTests(unittest.TestCase):
    """What the agent list's `s` and `x` write waits under the running `delegate_task` call, as a steer does.

    Subagents only exist while the parent's call runs, so every one of these
    rows arrives over a live block: written at once, it closed that call
    (`▪`, cut off) or split a streaming reply.
    """

    def delegating(self, **options: object) -> tuple[App, RecordingClient]:
        app, client = agent_app(busy=True, frames=[], **options)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "delegate_task", "context": "two subagents"}))
        relay(app, STARTS)
        app._on_input(Key(DOWN))  # the list, on the first agent
        return app, client

    def finish(self, app: App) -> list[tuple[str, str]]:
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "delegate_task", "result": {"output": "done"}}))
        app._on_event(Event("message.complete", SID, {"text": "Both agents finished.", "status": "complete"}))
        return [(tool.name, tool.status) for block in app.transcript.blocks if isinstance(block, ToolGroup)
                for tool in block.tools]

    def assert_running(self, app: App) -> None:
        group = app.transcript.blocks[-1]
        self.assertIsInstance(group, ToolGroup)
        self.assertEqual(group.tools[0].status, TOOL_RUNNING)

    def test_a_steer_leaves_the_delegate_call_running_and_lands_after_it(self) -> None:
        app, client = self.delegating()
        app._on_input(Key(CHAR, "s"))
        type_text(app, "skip the tests folder")
        app._on_input(Key(ENTER))
        self.assertEqual(lines_text(app.transcript.live_lines(100, DEFAULT_THEME))[-1],
                         "↪ steer · find usages of: skip the tests folder")  # the main steer's format, while it waits
        answer(app, client, {"status": "queued", "subagent_id": FIRST, "text": "skip the tests folder"})
        self.assert_running(app)
        self.assertEqual(self.finish(app), [("delegate_task", TOOL_OK)])
        kinds = [type(block).__name__ for block in app.transcript.blocks]
        self.assertEqual(kinds[:3], ["ToolGroup", "SteerBlock", "AssistantBlock"])
        self.assertEqual(steers(app), ["↪ steer queued by Hermes · find usages of: skip the tests folder"])

    def test_an_interrupt_and_its_refusal_leave_the_delegate_call_running(self) -> None:
        for reply, said in (
            ({"result": {"found": True, "subagent_id": FIRST}}, "Interrupted find usages of."),
            ({"error": {"code": 4009, "message": "agent not ready"}}, "Hermes did not interrupt find usages of: agent not ready."),
        ):
            with self.subTest(said=said):
                app, client = self.delegating()
                app._on_input(Key(CHAR, "x"))
                app._on_input(Key(CHAR, "x"))
                answer(app, client, reply.get("result"), reply.get("error"))
                self.assert_running(app)
                self.assertEqual(self.finish(app), [("delegate_task", TOOL_OK)])
                self.assertEqual(notices(app)[0], said)

    def test_an_interrupt_hermes_never_answers_says_so_and_leaves_the_delegate_call_running(self) -> None:
        now = [0.0]
        app, client = self.delegating(clock=lambda: now[0])
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls[-1][0], "subagent.interrupt")
        now[0] += 3600  # far past any call's answer time
        app._expire_calls()
        self.assert_running(app)  # the notice waits under the call instead of cutting it off
        self.assertEqual(self.finish(app), [("delegate_task", TOOL_OK)])
        self.assertEqual(notices(app)[0], "Hermes has not answered subagent.interrupt in 120 s; the OMH TUI stopped waiting for it.")

    def test_x_on_an_agent_that_finished_while_the_call_runs_leaves_the_call_running(self) -> None:
        app, client = self.delegating()
        relay(app, [frame for frame in FRAMES if frame[0] == "subagent.complete" and frame[1]["subagent_id"] == FIRST])
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])
        self.assert_running(app)
        self.assertEqual(self.finish(app), [("delegate_task", TOOL_OK)])
        self.assertIn("has finished", notices(app)[0])

    def test_a_refused_steer_leaves_the_delegate_call_running(self) -> None:
        app, client = self.delegating()
        app._on_input(Key(CHAR, "s"))
        type_text(app, "use the other file")
        app._on_input(Key(ENTER))
        answer(app, client, {"status": "rejected"})
        self.assert_running(app)
        self.assertEqual(app.composer.text, "use the other file")

    def test_a_steer_during_a_streaming_reply_does_not_split_it(self) -> None:
        app, client = agent_app(busy=True, frames=[])
        app._on_event(Event("message.start", SID, {}))
        relay(app, STARTS)
        app._on_event(Event("message.delta", SID, {"text": "First half, "}))
        app._on_input(Key(DOWN))
        app._on_input(Key(CHAR, "s"))
        type_text(app, "shorter")
        app._on_input(Key(ENTER))
        answer(app, client, {"status": "queued", "subagent_id": FIRST, "text": "shorter"})
        app._on_event(Event("message.delta", SID, {"text": "second half."}))
        app._on_event(Event("message.complete", SID, {"text": "First half, second half.", "status": "complete"}))
        replies = [block.text for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(replies, ["First half, second half."])


class TailPollTests(unittest.TestCase):
    def open(self, **options: object) -> tuple[App, RecordingClient, list[float]]:
        now = [50.0]
        app, client = log_open(clock=lambda: now[0], **options)
        return app, client, now

    def test_opening_a_running_agents_log_asks_for_its_tail_once(self) -> None:
        app, client, _now = self.open()
        self.assertEqual(client.calls, [])  # nothing until the loop's next step
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [TAIL_CALL])
        self.assertEqual(contract.call_problem(*TAIL_CALL), "")

    def test_an_unanswered_call_holds_the_next_back_for_ten_seconds_and_its_late_answer_is_dropped(self) -> None:
        app, client, now = self.open(frames=FRAMES[:6])
        before = paged(app)[3:]
        for _ in range(20):  # 50.0 to 59.5
            app._ask_tail_when_due()
            now[0] += 0.5
        self.assertEqual(client.calls, [TAIL_CALL])
        self.assertEqual((now[0], TAIL_ANSWER_SECONDS), (60.0, 10.0))
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [TAIL_CALL, TAIL_CALL])  # ten seconds without an answer: one more goes
        app._on_response(Response(1, TAIL, None))  # the first call's answer, late
        drawn(app)
        self.assertEqual(paged(app)[3:], before)  # dropped: the second call is the one waited for
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 2)  # and it did not free the second call's place
        answer(app, client, TAIL)
        drawn(app)
        self.assertEqual(paged(app)[3:], ["reading src/api/client.py", "found 3 call sites"])

    def test_an_available_tail_becomes_the_log(self) -> None:
        app, client, _now = self.open(frames=FRAMES[:6])
        app._ask_tail_when_due()
        answer(app, client, TAIL)
        drawn(app)
        self.assertEqual(paged(app)[3:], ["reading src/api/client.py", "found 3 call sites"])
        self.assertEqual(notices(app), [])

    def test_a_tail_hermes_cut_says_earlier_output_is_missing(self) -> None:
        app, client, _now = self.open()
        app._ask_tail_when_due()
        answer(app, client, {**TAIL, "text": "f a line\nthe first whole line\nthe last line\n", "truncated": True})
        drawn(app)
        self.assertEqual(paged(app)[3:], ["… earlier output not shown", "the first whole line", "the last line"])

    def test_the_next_call_waits_two_seconds_from_the_last_one(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        answer(app, client, TAIL)
        for later in (0.05, 1.0, TAIL_POLL_SECONDS - 0.01):
            now[0] = 50.0 + later
            app._ask_tail_when_due()
            self.assertEqual(len(tails(client)), 1, later)
        now[0] = 50.0 + TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [TAIL_CALL, TAIL_CALL])

    def test_over_ten_seconds_of_steps_no_two_calls_are_less_than_two_seconds_apart(self) -> None:
        app, client, now = self.open()
        sent_at: list[float] = []
        for step in range(201):  # the loop's 50 ms step, every answer back within it
            now[0] = 50.0 + step * 0.05
            before = len(client.calls)
            app._ask_tail_when_due()
            if len(client.calls) > before:
                sent_at.append(now[0])
                answer(app, client, TAIL)
        self.assertEqual(len(sent_at), 6)  # at 0, 2, 4, 6, 8 and 10 seconds
        self.assertTrue(all(later - earlier >= TAIL_POLL_SECONDS for earlier, later in zip(sent_at, sent_at[1:])))
        self.assertEqual(TAIL_POLL_SECONDS, 2.0)

    def test_a_slow_answer_does_not_bring_the_next_call_forward(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        now[0] = 59.0  # nine seconds for the answer
        answer(app, client, TAIL)
        app._ask_tail_when_due()
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 2)  # one more, not one per missed interval

    def test_no_call_after_the_agent_finished(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        answer(app, client, TAIL)
        agent_event(app, "complete", status="completed", summary="done")
        for _ in range(20):
            now[0] += 1.0
            app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 1)

    def test_no_call_for_an_agent_that_had_finished_before_its_log_opened(self) -> None:
        app, client = agent_app(frames=FRAMES, busy=False)
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(app.log_agent, FIRST)
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [])

    def test_no_call_for_an_agent_still_waiting_for_a_worker(self) -> None:
        app, client = agent_app()
        agent_event(app, "spawn_requested", "sa-queued", goal="waiting its turn")
        app._open_agent_log("sa-queued")
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [])

    def test_no_call_without_a_session(self) -> None:
        app, client, now = self.open()
        app.sid = ""
        for _ in range(10):
            now[0] += 3.0
            app._ask_tail_when_due()
        self.assertEqual(client.calls, [])

    def test_no_call_once_the_log_is_closed_or_while_another_pager_is_open(self) -> None:
        app, client, now = self.open()
        app._on_input(Key(CHAR, "q"))
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [])
        app._on_input(Key(ESCAPE))  # out of the list
        app._on_input(Key(CHAR, "?"))  # the key list: a pager, but no agent's log
        now[0] += 5.0
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [])

    def test_no_call_while_only_the_list_or_the_view_is_shown(self) -> None:
        app, client = focused()
        app._ask_tail_when_due()
        app._on_input(Key(ESCAPE))
        app._ask_tail_when_due()
        self.assertEqual(client.calls, [])

    def test_a_tail_that_is_not_available_changes_nothing_and_says_nothing(self) -> None:
        app, client, now = self.open(frames=FRAMES[:6])
        before = paged(app)[3:]  # the log under the header, whose elapsed time moves with the clock
        self.assertEqual(len(before), 4)
        app._ask_tail_when_due()
        answer(app, client, NO_TAIL)
        drawn(app)
        self.assertEqual((paged(app)[3:], notices(app)), (before, []))
        # A reply that says available with any word but true is not one either.
        for available in ("true", 1, None):
            now[0] += TAIL_POLL_SECONDS
            app._ask_tail_when_due()
            answer(app, client, {**TAIL, "available": available})
        drawn(app)
        self.assertEqual((paged(app)[3:], notices(app)), (before, []))
        self.assertEqual(len(tails(client)), 4)  # each one an answer without a tail; it asks again, at its pace

    def test_five_answers_in_a_row_without_a_tail_stop_the_calls_until_the_agent_sends_a_frame(self) -> None:
        app, client, now = self.open()

        def ask_and_miss(times: int) -> None:
            for _ in range(times):
                now[0] += TAIL_POLL_SECONDS
                before = len(client.calls)
                app._ask_tail_when_due()
                if len(client.calls) > before:
                    answer(app, client, NO_TAIL)

        self.assertEqual(TAIL_MISSES_BEFORE_STOP, 5)
        ask_and_miss(4)
        answer_error = {"code": 4001, "message": "session not found or not owned by this transport"}
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        answer(app, client, error=answer_error)  # an error is an answer without a tail too
        self.assertEqual(len(tails(client)), 5)
        ask_and_miss(30)  # a minute
        self.assertEqual(len(tails(client)), 5)  # ten seconds of nothing: no more calls for this agent
        agent_event(app, "tool", SECOND, tool_name="terminal", tool_count=1)  # another agent's frame
        ask_and_miss(3)
        self.assertEqual(len(tails(client)), 5)
        agent_event(app, "tool", tool_name="read_file", tool_preview="src/a.py", tool_count=1)  # its own
        ask_and_miss(10)
        self.assertEqual(len(tails(client)), 10)  # asked again, and bounded again

    def test_a_timed_out_call_is_forgotten_when_the_next_goes_out(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        first = len(client.calls)
        now[0] += TAIL_ANSWER_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 2)
        waiting = [call for call in app.pending.values() if call.method == "subagent.tail"]
        self.assertEqual(len(waiting), 1)  # a gateway that never answers cannot grow `pending`
        self.assertEqual(client.forgotten, [first])  # nor the client's own record of what it waits for

    def test_a_new_turn_drops_every_piece_of_tail_bookkeeping(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        answer(app, client, NO_TAIL)
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()  # a second call, still out
        second = len(client.calls)
        self.assertTrue(app.tail_misses)
        app._submit_prompt("next task")
        self.assertEqual(app.tail_misses, {})
        self.assertEqual([call for call in app.pending.values() if call.method == "subagent.tail"], [])
        self.assertEqual(client.forgotten, [second])
        self.assertEqual((app.tail_asked_at, app.tail_open), (None, False))

    def test_a_tail_in_between_starts_the_count_again_and_the_count_is_each_agents(self) -> None:
        app, client, now = self.open()
        for result in (NO_TAIL, NO_TAIL, NO_TAIL, NO_TAIL, TAIL, NO_TAIL, NO_TAIL, NO_TAIL, NO_TAIL):
            now[0] += TAIL_POLL_SECONDS
            app._ask_tail_when_due()
            answer(app, client, result)
        self.assertEqual(len(tails(client)), 9)
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 10)  # four in a row since the tail: it still asks
        answer(app, client, NO_TAIL)
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 10)  # five: it stops
        app._on_input(Key(RIGHT))  # the next agent's log has its own count
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(tails(client)[-1], {"session_id": SID, "subagent_id": SECOND})

    def test_an_error_answer_changes_nothing_and_says_nothing(self) -> None:
        app, client, now = self.open(frames=FRAMES[:6])
        before = paged(app)
        app._ask_tail_when_due()
        answer(app, client, error={"code": 4001, "message": "session not found or not owned by this transport"})
        drawn(app)
        self.assertEqual((paged(app), notices(app), app.exit_code), (before, [], None))
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 2)

    def test_a_hermes_without_the_method_is_drift_like_any_declared_call(self) -> None:
        app, client, _now = self.open()
        app._ask_tail_when_due()
        answer(app, client, error={"code": contract.METHOD_NOT_FOUND, "message": "unknown method"})
        self.assertEqual(app.exit_code, 1)
        self.assertIn("subagent.tail", app.farewell)

    def test_a_tail_answered_after_the_agent_finished_does_not_replace_its_reply(self) -> None:
        app, client, _now = self.open()
        app._ask_tail_when_due()
        agent_event(app, "complete", status="completed", summary="three call sites", duration_seconds=5.0)
        answer(app, client, TAIL)
        drawn(app)
        self.assertEqual(paged(app)[3:], ["three call sites"])

    def test_a_tail_answered_after_the_agent_finished_is_dropped_even_with_nothing_in_its_log(self) -> None:
        # The roster would let a tail seed a finished agent's empty log; the app reads tails of running agents only.
        app, client, _now = self.open()
        app._ask_tail_when_due()
        agent_event(app, "complete", status="completed", summary="", duration_seconds=5.0)
        self.assertEqual(len(app.roster.agents[FIRST].log), 0)
        answer(app, client, TAIL)
        self.assertEqual(len(app.roster.agents[FIRST].log), 0)
        drawn(app)
        self.assertEqual(paged(app)[3:], ["no output yet"])

    def test_a_tail_answered_after_the_session_was_left_is_dropped(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        app.sid = "live-2"
        app._on_response(Response(1, TAIL, None))
        self.assertEqual(len(app.roster.agents[FIRST].log), 0)
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()  # and the next one goes out for the session the app is in now
        self.assertEqual(tails(client)[-1], {"session_id": "live-2", "subagent_id": FIRST})

    def test_a_tail_whose_text_is_not_text_is_not_read(self) -> None:
        app, client, _now = self.open()
        app._ask_tail_when_due()
        answer(app, client, {**TAIL, "text": ["not", "text"]})
        self.assertEqual(len(app.roster.agents[FIRST].log), 0)

    def test_after_moving_to_another_agent_the_next_tail_is_that_agents(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        answer(app, client, TAIL)
        app._on_input(Key(RIGHT))
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 1)  # the pace is the view's, not each agent's
        now[0] += TAIL_POLL_SECONDS
        app._ask_tail_when_due()
        self.assertEqual(tails(client)[-1], {"session_id": SID, "subagent_id": SECOND})

    def test_a_log_opened_again_within_two_seconds_of_the_last_call_waits_for_the_pace(self) -> None:
        app, client, now = self.open()
        app._ask_tail_when_due()
        answer(app, client, TAIL)
        app._on_input(Key(CHAR, "q"))
        now[0] += 1.0
        app._on_input(Key(ENTER))  # the same log, opened again from the list
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 1)  # not as it opens: one second after the last call
        now[0] += TAIL_POLL_SECONDS - 1.0
        app._ask_tail_when_due()
        self.assertEqual(len(tails(client)), 2)

    def test_the_tail_is_the_only_call_the_agent_views_make(self) -> None:
        app, client, now = self.open()
        for key in (RIGHT, LEFT, Key(CHAR, "q"), Key(UP), Key(DOWN), Key(ENTER), Key(CHAR, "q"), Key(ESCAPE)):
            app._on_input(key if isinstance(key, Key) else Key(key))
            now[0] += 3.0
            app._ask_tail_when_due()
            if client.calls and app.tail_open:
                answer(app, client, TAIL)
            drawn(app)
        self.assertEqual({method for method, _params in client.calls}, {"subagent.tail"})
        self.assertEqual(client.answers, [])
        self.assertEqual(app.mode, MODE_NORMAL)


def subagent_frame(event_type: str, payload: dict[str, object]) -> str:
    """One recorded subagent frame as the gateway would send it on the live session."""
    return json.dumps(
        {"jsonrpc": "2.0", "method": "event", "params": {"type": event_type, "session_id": LIVE_ID, "payload": payload}}
    )


INTERRUPTED_PROMPT = "Write the numbers from 1 to 300, one per line, nothing else."


def delegating_scenario(*answers: tuple[str, dict]) -> Scenario:
    """The recorded turn the person interrupts, with Hermes' subagent frames arriving just before it waits.

    The replay holds that turn open until it reads `session.interrupt`, so
    the agents stay running for as long as the script needs them.
    """
    played = spans("session", "startup", "create", "interrupted_turn")
    waits_at = sum(stop - start for start, stop in played[:2]) + 18  # the recorded session.interrupt
    frames = tuple((waits_at, subagent_frame(event_type, payload)) for event_type, payload in FRAMES[:6])
    return Scenario("session", played, inject=frames, answers=(*startup_answers(), *answers))


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class AgentReplayTests(AppTestCase):
    def test_the_view_the_list_and_the_log_work_in_the_real_loop_and_the_tail_is_asked_of_hermes(self) -> None:
        tail = {"subagent_id": FIRST, "available": True, "text": "TAIL: grepping src/\n", "truncated": False}
        run = self.prepare(delegating_scenario(("subagent.tail", {"result": tail})))
        terminal = run.terminal
        listed = terminal.shows(AGENT_LIST_HINT)
        terminal.script(
            self.submit(run, INTERRUPTED_PROMPT),
            Step(b"\x1b[B", when=terminal.shows("  ● main"), capture="view", label="the view"),
            Step(b"\r", when=listed, capture="list", label="the list"),
            Step(b"\x1b[C", when=terminal.shows("TAIL: grepping src/"), capture="log", label="the tail in the log"),
            Step(b"q", when=terminal.shows("read the diff · ←/→ agents"), capture="second", label="the second agent"),
            Step(b"\x1b", when=listed, capture="back", label="the list again"),
            Step(b"\x1b", when=lambda: not listed() and terminal.shows("  ● main")(), label="the view again"),
            # The agent view stays under the info line after the turn: `idle` reads the screen's last row.
            Step(b"\x04", when=lambda: "Interrupted." in terminal.history() and terminal.idle(),
                 label="the end"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        captures = terminal.captures
        view = captures["view"]
        status = info_index(view) - 3  # the agent view's three rows are the screen's last ones
        self.assertTrue(without_badge(view[status]).startswith(INFO_INSET + "2 agents · ↓ agents"), view)
        self.assertEqual(view[status + 1], "  ● main")
        self.assertIn("find usages of", view[status + 2])
        self.assertIn("read the diff", view[status + 3])
        rows = captures["list"]
        self.assertEqual(info_index(rows) - 3, status, "the list opens on the view's rows")
        self.assertEqual(rows[status + 1], "  ● main")
        self.assertTrue(rows[status + 2].startswith("❯ ") and "find usages of old_api" in rows[status + 2], rows)
        # The list's keys, whole: at 80 columns the right side (the effort) gives way to them and to the badge.
        self.assertEqual(info_left(rows[status]), AGENT_LIST_HINT)
        self.assertTrue(rows[status].startswith(INFO_INSET + "[⚚ OMH Native]  "), rows[status])
        # While the list has the keys the composer's rules stay and its row says how to browse: no prompt to type in.
        self.assertEqual([row for row in rows if row.startswith("❯ ") and "old_api" not in row], [], rows)
        self.assertEqual([row.strip() for row in rows if BROWSING_HINT in row], [BROWSING_HINT])
        self.assertEqual(captures["log"][0], "find usages of old_api in src/ and list every call site")
        self.assertEqual(captures["second"][0], "read the diff for risks")
        # Back on the second agent, the list's last row: the screen's last row that is not blank.
        self.assertTrue(captures["back"][info_index(captures["back"])].startswith("❯ "), captures["back"])
        calls = run.calls("subagent.tail")
        self.assertEqual(calls[0]["params"], {"session_id": LIVE_ID, "subagent_id": FIRST})
        self.assertLessEqual(len(calls), 2)
        self.assertEqual(len(run.calls("session.interrupt")), 1)  # the last Esc alone, with the list gone


class ContractTests(unittest.TestCase):
    def test_the_tail_call_carries_exactly_what_hermes_names(self) -> None:
        # Hermes 6c61c3e27d: SubagentIdParams is session_id, subagent_id and profile (tui_gateway/contracts/).
        self.assertEqual(contract.CLIENT_METHODS["subagent.tail"], {"session_id", "subagent_id"})
        self.assertEqual(contract.call_problem(*TAIL_CALL), "")

    def test_a_tail_call_hermes_would_reject_is_never_sent(self) -> None:
        # A missing subagent id is answered 4000, which the client reads as drift and leaves the session over.
        refused = {
            "no subagent id": {"session_id": SID},
            "an empty subagent id": {"session_id": SID, "subagent_id": ""},
            "a subagent id that is not text": {"session_id": SID, "subagent_id": 7},
            "no session id": {"subagent_id": FIRST},
            "an empty session id": {"session_id": "", "subagent_id": FIRST},
            "a key Hermes takes but the TUI does not send": {"session_id": SID, "subagent_id": FIRST, "profile": "x"},
            "text to send to the agent": {"session_id": SID, "subagent_id": FIRST, "text": "do this"},
        }
        for name, params in refused.items():
            with self.subTest(name):
                self.assertNotEqual(contract.call_problem("subagent.tail", params), "")

    def test_the_only_calls_that_act_on_a_subagent_are_the_two_the_boundary_names(self) -> None:
        # docs/OMH-TUI-BOUNDARY.md: `x` (interrupt, confirmed) and `s` (steer with typed text), each on a keypress in the list.
        self.assertEqual(
            sorted(method for method in contract.CLIENT_METHODS if method.startswith("subagent.")),
            ["subagent.interrupt", "subagent.steer", "subagent.tail"],
        )


if __name__ == "__main__":
    unittest.main()
