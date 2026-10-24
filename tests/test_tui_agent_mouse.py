"""Clicks on the agent list, and when the OMH TUI asks the terminal for mouse reports at all: only while the list is open.

Neither the agent view under the info line nor the count on it is clickable
while the list is closed (the owner's decision of 2026-10-14): during a turn
the wheel scrolls and a drag selects, and Down opens the list from the
keyboard, on the view's own rows.

Where a click lands is never taken from the app. Each case reads the VT
screen the scripted terminal painted (`drawn`), finds the row and the cells
the thing to click is shown on, and sends a report for that cell the way the
terminal counts it: columns and rows from 1. What the click did is then read
from the app. A click "one off" is a report for the neighbouring cell or row.

The app works out which screen row its live region ends on and reads no
click while that row is not certain. A scripted terminal starts the way a
real launch does, with the app not told the cursor row, so most cases first
press Ctrl+L (`settled`): the redraw clears the screen and homes the cursor,
and from there the row is known. `UnknownRowTests` covers the launch itself.
"""

from __future__ import annotations

import errno
from pathlib import Path
import unittest

from _tui_gateway_replay import Scenario
from test_tui_agent_list import INTERRUPTED_PROMPT, delegating_scenario, focused, info_left, more_agents, under_the_frame
from test_tui_agent_view import STARTS, agent_app, relay
from test_tui_app import LIVE_ID, NO_TERMIOS, AppTestCase, FakePoller, ScriptedTerminal, Step, info_index
from test_tui_modes import SID, RecordingClient, composer_index, drawn, make_app, type_text
from test_tui_subagents import FIRST, FRAMES, SECOND
from omh.commands.theme_picker import KEY_DOWN, KEY_NONE, KEY_QUIT
from omh.tui import keys as keys_module
from omh.tui import terminal as terminal_module
from omh.tui.agent_view import AGENT_LIST_HINT
from omh.tui.app import (
    CURSOR_POSITION_REQUEST,
    EXIT_DRAIN_SECONDS,
    READ_TIMEOUT_SECONDS,
    RESIZE_SETTLE_SECONDS,
    REPORTING_SLOT_ARM_SECONDS,
    SLOT_ARM_SECONDS,
    App,
)
from omh.tui.gateway import Event, GatewayExited, ServerRequest
from omh.tui.keys import (
    BUTTON_LEFT,
    BUTTON_MIDDLE,
    BUTTON_RIGHT,
    CHAR,
    DOWN,
    ENTER,
    ESCAPE,
    MOUSE_REPORT_SECONDS,
    NO_BUTTON,
    WHEEL_DOWN,
    WHEEL_UP,
    Key,
    KeyDecoder,
    Mouse,
)
from omh.tui.modes import IDLE_HINT
from omh.tui.pager import ALT_SCREEN_OFF
from omh.tui.screen import ERASE_BELOW
from omh.tui.session_picker import SessionPicker, SessionRow

MOUSE_ON = terminal_module.MOUSE_REPORTING_ON
MOUSE_OFF = terminal_module.MOUSE_REPORTING_OFF
CTRL_L = Key(CHAR, "l", ctrl=True)


def settled(app: App) -> App:
    """Ctrl+L: the screen is cleared and redrawn from the top row, so the app knows where its region is."""
    app._on_input(CTRL_L)
    drawn(app)
    return app


def reporting(app: App) -> bool:
    """Whether mouse reports are on after one repaint."""
    drawn(app)
    return app.terminal.mouse_reporting  # type: ignore[attr-defined]


def mouse_calls(app: App) -> list[bool]:
    return app.terminal.mouse_calls  # type: ignore[attr-defined]


def row_of(app: App, text: str) -> int:
    """The 1-based screen row whose text contains `text`, as a mouse report counts rows."""
    screen = drawn(app)
    (row,) = [index for index, line in enumerate(screen) if text in line]
    return row + 1


def column_of(app: App, text: str) -> int:
    """The 1-based column of the first cell of `text` on the screen (the agent rows hold no wide glyph)."""
    (line,) = [line for line in drawn(app) if text in line]
    return line.index(text) + 1


def click(app: App, x: int, y: int) -> None:
    app._on_input(Mouse(BUTTON_LEFT, x, y))


def state(app: App, client: RecordingClient) -> tuple[object, ...]:
    """Everything a mouse report could change."""
    return (
        app.composer.text,
        app.pager is not None,
        app.log_agent,
        app.list_selected,
        len(client.calls),
        len(client.answers),
        len(app.transcript.blocks),
        app.exit_code,
        app.mode,
    )


def running(**options: object) -> tuple[App, RecordingClient]:
    """A turn running with the two recorded agents in the view, the region's row known."""
    app, client = agent_app(**options)
    return settled(app), client


def listing(**options: object) -> tuple[App, RecordingClient]:
    """`running`, with the agent list open (Down): the one state mouse reports are on in."""
    app, client = running(**options)
    app._on_input(Key(DOWN))
    drawn(app)
    return app, client


SECOND_ROW = "read the diff for risks"  # the second agent's row in the list


class MouseStateTests(unittest.TestCase):
    def test_reports_are_on_only_while_the_agent_list_is_open(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        settled(app)
        steps: list[tuple[str, bool]] = []

        def note(what: str) -> None:
            steps.append((what, reporting(app)))

        note("idle, no agent")
        app.turn_pending = True
        note("a turn running, no agent")
        relay(app, STARTS)
        note("a turn running, agents in the view")
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        note("an approval open")
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(CHAR, "d"))
        note("the approval denied, the turn still running")
        app._on_input(Key(DOWN))
        note("the list focused")
        app._on_input(Key(ENTER))
        note("an agent's log open")
        app._on_input(Key(CHAR, "q"))
        note("back in the list")
        app._on_input(Key(ESCAPE))
        note("back on the view, the turn still running")
        relay(app, FRAMES[2:])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        note("the turn over, the finished agents still shown")
        app._on_input(Key(DOWN))
        note("the list focused while idle")
        app._on_input(Key(ESCAPE))
        note("the list left while idle")
        type_text(app, "next")
        app._on_input(Key(ENTER))
        note("the next turn, the roster empty")
        self.assertEqual(
            steps,
            [
                ("idle, no agent", False),
                ("a turn running, no agent", False),
                ("a turn running, agents in the view", False),  # the wheel and selection work during the turn
                ("an approval open", False),
                ("the approval denied, the turn still running", False),
                ("the list focused", True),
                ("an agent's log open", False),
                ("back in the list", True),
                ("back on the view, the turn still running", False),
                ("the turn over, the finished agents still shown", False),
                ("the list focused while idle", True),
                ("the list left while idle", False),
                ("the next turn, the roster empty", False),
            ],
        )
        self.assertEqual(mouse_calls(app), [True, False, True, False, True, False])
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])

    def test_the_switch_is_written_only_when_the_state_changes(self) -> None:
        app, _client = listing()
        for _ in range(5):
            drawn(app)
        written = "".join(app.terminal.writes)  # type: ignore[attr-defined]
        self.assertEqual((written.count(MOUSE_ON), written.count(MOUSE_OFF)), (1, 0))
        # Clicks and the wheel, in SGR form; never the modes that report motion.
        self.assertEqual(MOUSE_ON, "\x1b[?1000h\x1b[?1006h")
        for mode in ("?1002h", "?1003h", "?1015h"):
            self.assertNotIn(mode, written)

    def test_no_reports_where_no_list_can_open(self) -> None:
        for rows, on in ((5, False), (6, True), (9, True), (24, True)):
            with self.subTest(rows=rows):
                app, _client = running(rows=rows)
                app._on_input(Key(DOWN))
                self.assertEqual(reporting(app), on)
                self.assertEqual(mouse_calls(app), [True] if on else [])

    def test_the_view_and_the_count_have_nothing_to_click_but_the_list_does(self) -> None:
        app, _client = running(cols=40)
        self.assertIn("  2 agents · ↓ agents", "\n".join(drawn(app)))
        self.assertFalse(reporting(app))
        app._on_input(Key(DOWN))
        self.assertTrue(reporting(app))

    def test_a_pager_that_is_no_agents_log_turns_them_off_too(self) -> None:
        app, _client = listing()
        self.assertTrue(reporting(app))
        app._open_pager("history", [])
        self.assertFalse(reporting(app))
        app._leave_pager()
        self.assertTrue(reporting(app))  # the list is still open under it

    def test_a_question_answered_with_text_turns_them_off(self) -> None:
        app, _client = listing()
        app._on_server_request(ServerRequest("srq-1", "vault.code", {}))
        self.assertFalse(reporting(app))

    def test_the_session_picker_takes_the_list_and_its_reports_away(self) -> None:
        app, _client = listing()
        app.picker = SessionPicker([SessionRow("stored-1", "a title", "", 0.0, 1)], current="")
        self.assertFalse(reporting(app))
        self.assertIsNone(app.list_selected)

    def test_the_model_chain_picker_runs_with_them_off_and_the_list_gets_them_back(self) -> None:
        during: list[bool] = []

        def pick(environ: object, theme: object, *, read_key: object, write: object, width: int) -> str:
            during.append(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
            return "Cancelled; nothing was changed."

        app, _client = listing(pick_model_chains=pick)
        self.assertTrue(reporting(app))
        app._omh_model("")  # typing /omh-model would leave the list first
        self.assertEqual(during, [False])
        self.assertTrue(reporting(app))
        self.assertEqual(mouse_calls(app), [True, False, True])

    def test_a_report_split_after_its_escape_does_not_cancel_the_model_chain_picker(self) -> None:
        # A release the terminal sent before it acted on the picker's off, split after its ESC by 200 ms.
        now = [100.0]
        keys: list[str] = []

        def pick(environ: object, theme: object, *, read_key, write: object, width: int) -> str:
            keys.extend((read_key(), read_key()))
            return "Cancelled; nothing was changed."

        app, _client = listing(clock=lambda: now[0], pick_model_chains=pick)
        self.assertTrue(reporting(app))
        reads = [(0.0, b"\x1b"), *[(READ_TIMEOUT_SECONDS, b"")] * 3, (READ_TIMEOUT_SECONDS, b"[<0;5;5m"), (0.0, b"j")]

        def read(timeout: float, wake: int | None = None) -> bytes:
            delay, data = reads.pop(0)
            now[0] += delay
            return data

        app.terminal.read = read  # type: ignore[method-assign]
        app._omh_model("")
        self.assertEqual(keys, [KEY_NONE, KEY_DOWN])  # the report is no key, and the picker is still open for j

    def test_a_resize_right_after_an_escape_does_not_cancel_the_model_chain_picker(self) -> None:
        # Reports never on: only the silence after the ESC tells it from an arrow, and a resize signal ends a
        # read at once with nothing read, before any silence.
        for gap, expected in ((0.0, [KEY_DOWN]), (READ_TIMEOUT_SECONDS, [KEY_QUIT])):
            with self.subTest(gap=gap):
                now = [100.0]
                keys: list[str] = []

                def pick(environ: object, theme: object, *, read_key, write: object, width: int) -> str:
                    keys.append(read_key())
                    return "Cancelled; nothing was changed."

                app, _client = make_app(clock=lambda: now[0], pick_model_chains=pick)
                reads = [(0.0, b"\x1b"), (gap, b""), (0.0, b"[B")]

                def read(timeout: float, wake: int | None = None) -> bytes:
                    delay, data = reads.pop(0)
                    now[0] += delay
                    return data

                app.terminal.read = read  # type: ignore[method-assign]
                type_text(app, "/omh-model")
                app._on_input(Key(ENTER))
                self.assertEqual(keys, expected)  # an arrow's rest after a resize; a real silence is Esc

    def test_shutdown_turns_them_off_before_the_screen_is_handed_back(self) -> None:
        for paging in (False, True):
            with self.subTest(paging=paging):
                app, _client = listing()
                self.assertTrue(reporting(app))
                if paging:
                    app._open_pager("history", [])
                writes = app.terminal.writes  # type: ignore[attr-defined]
                start = len(writes)
                app._shutdown()
                self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
                shutdown = writes[start:]
                self.assertEqual(shutdown[0], MOUSE_OFF)  # the first thing written on the way out
                self.assertEqual("".join(shutdown).count(MOUSE_OFF), 1)
                # Then the alternate screen goes, and the live region is erased: the screen is the shell's again.
                handed_back = [index for index, text in enumerate(shutdown) if ALT_SCREEN_OFF in text or "\x1b[J" in text]
                self.assertTrue(handed_back)
                self.assertGreater(min(handed_back), 0)

    def test_shutdown_from_an_open_log_leaves_them_off(self) -> None:
        app, _client = listing()
        app._on_input(Key(ENTER))
        self.assertFalse(reporting(app))
        app._shutdown()
        self.assertEqual(mouse_calls(app), [True, False])
        self.assertIn(ALT_SCREEN_OFF, "".join(app.terminal.writes))  # type: ignore[attr-defined]


class HungUpTerminal(ScriptedTerminal):
    """A scripted terminal that can be made to refuse every write, as a pty whose window closed does (EIO)."""

    refusal: int | None = None

    def write(self, text: str) -> None:
        if self.refusal is not None:
            raise OSError(self.refusal, "the terminal refused the write")
        super().write(text)


class FailingShutdownTests(unittest.TestCase):
    """Whatever fails on the way out, the shell gets its screen back, and the exit under way is the one reported."""

    def leaving(self) -> tuple[App, RecordingClient, HungUpTerminal]:
        terminal = HungUpTerminal()
        client = RecordingClient()
        app = App(terminal, client, {}, poller=FakePoller(), clock=lambda: 0.0)  # type: ignore[arg-type]
        app.sid = SID
        app.turn_pending = True
        relay(app, STARTS)
        settled(app)
        app._on_input(Key(DOWN))  # the list: reports on
        drawn(app)
        self.assertTrue(terminal.mouse_reporting)
        app.yolo_by_tui = True  # accept is on: the exit owes Hermes an explicit off
        return app, client, terminal

    def test_a_hang_up_with_reports_on_leaves_by_the_signal_not_a_traceback(self) -> None:
        app, client, terminal = self.leaving()

        def hang_up(timeout: float, wake: int | None = None) -> bytes:
            terminal.refusal = errno.EIO
            raise SystemExit(128 + 1)  # SIGHUP, as _exit_on_signal raises it

        terminal.read = hang_up  # type: ignore[method-assign]
        with self.assertRaises(SystemExit) as raised:
            app.run()
        self.assertEqual(raised.exception.code, 129)
        self.assertTrue(app.poller.stopped)  # type: ignore[attr-defined]
        self.assertIn(("config.set", {"key": "yolo", "session_id": SID, "value": "off"}), client.calls)

    def test_a_poller_that_fails_to_stop_leaves_the_screen_handed_back(self) -> None:
        app, client, terminal = self.leaving()
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))  # an agent's log: the alternate screen
        drawn(app)

        def broken(timeout: float = 1.0) -> None:
            raise RuntimeError("the HUD thread is wedged")

        app.poller.stop = broken  # type: ignore[method-assign]
        start = len(terminal.writes)
        with self.assertRaises(RuntimeError):
            app._shutdown()
        written = "".join(terminal.writes[start:])
        self.assertIn(ALT_SCREEN_OFF, written)
        self.assertIn(ERASE_BELOW, written)
        self.assertFalse(terminal.mouse_reporting)
        self.assertIn(("config.set", {"key": "yolo", "session_id": SID, "value": "off"}), client.calls)

    def test_last_lines_that_fail_to_render_still_leave_the_region_erased(self) -> None:
        app, _client, terminal = self.leaving()

        def broken(cols: int, theme: object) -> list:
            raise ValueError("a block that cannot render")

        app.transcript.take_stable_lines = broken  # type: ignore[method-assign]
        start = len(terminal.writes)
        with self.assertRaises(ValueError):
            app._shutdown()
        self.assertIn(ERASE_BELOW, "".join(terminal.writes[start:]))
        self.assertTrue(app.poller.stopped)  # type: ignore[attr-defined]

    def test_a_refusal_that_is_not_a_hang_up_still_raises(self) -> None:
        app, _client, terminal = self.leaving()
        terminal.refusal = errno.EBADF
        with self.assertRaises(OSError) as raised:
            app._shutdown()
        self.assertEqual(raised.exception.errno, errno.EBADF)
        self.assertTrue(app.poller.stopped)  # type: ignore[attr-defined]


class ViewNotClickableTests(unittest.TestCase):
    def test_no_cell_of_the_view_or_the_count_opens_anything_and_reports_stay_off_during_a_turn(self) -> None:
        app, client = running()
        rows = [row_of(app, "2 agents · ↓ agents"), row_of(app, "  ● main"), row_of(app, "find usages of"),
                row_of(app, SECOND_ROW)]
        before = state(app, client)
        for y in rows:
            for x in range(1, 82):
                click(app, x, y)
        self.assertEqual(state(app, client), before)
        self.assertFalse(reporting(app))
        self.assertEqual(mouse_calls(app), [])
        self.assertEqual(app.clickable, {})

    def test_a_report_decoded_from_the_terminals_bytes_opens_a_list_rows_log(self) -> None:
        app, _client = listing()
        y = row_of(app, SECOND_ROW)
        for event in KeyDecoder().feed(f"\x1b[<0;10;{y}M\x1b[<0;10;{y}m".encode("ascii")):
            app._on_input(event)
        self.assertEqual(app.log_agent, SECOND)


class ListClickTests(unittest.TestCase):
    def open(self, **options: object) -> tuple[App, RecordingClient]:
        app, client = focused(**options)
        return settled(app), client

    def test_a_click_on_an_agents_row_highlights_it_and_opens_its_log(self) -> None:
        for x in (1, 40, 80):
            with self.subTest(x=x):
                app, client = self.open()
                self.assertEqual(app.list_selected, FIRST)
                click(app, x, row_of(app, "read the diff for risks"))
                self.assertEqual((app.list_selected, app.log_agent), (SECOND, SECOND))
                app._on_input(Key(ESCAPE))
                self.assertEqual((app.pager, app.list_selected), (None, SECOND))  # back in the list, on that row
                self.assertEqual(under_the_frame(app)[-1], AGENT_LIST_HINT)
                self.assertEqual(client.calls, [])

    def test_an_x_asked_of_one_agent_never_confirms_on_another_reached_by_a_click(self) -> None:
        # A click moves the highlight without a key, so the first agent's question is still armed; one x on the
        # agent clicked must only ask about that one.
        app, client = self.open()
        app._on_input(Key(CHAR, "x"))  # asks about the first agent
        click(app, 5, row_of(app, "read the diff for risks"))  # opens the second agent's log
        app._on_input(Key(ESCAPE))  # back in the list, on the second agent
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])
        self.assertEqual(app.interrupt_armed, SECOND)

    def test_a_click_on_main_leaves_the_list(self) -> None:
        app, client = self.open()
        click(app, 5, row_of(app, "  ● main"))
        self.assertEqual((app.list_selected, app.pager, client.calls), (None, None, []))
        self.assertEqual(len(under_the_frame(app)), 1)

    def test_the_info_line_the_rows_above_it_and_the_row_under_the_region_open_nothing(self) -> None:
        app, client = self.open()
        before = state(app, client)
        top = row_of(app, "  ● main")
        info = row_of(app, AGENT_LIST_HINT)
        last = row_of(app, SECOND_ROW)
        self.assertEqual((info, last), (top - 1, top + 2), "the list is under the info line, the region's last rows")
        for y in (info, info - 1, info - 2, last + 1, 1, 24, 25):
            with self.subTest(y=y):
                click(app, 10, y)
                self.assertEqual(state(app, client), before)
        click(app, 81, row_of(app, "read the diff for risks"))  # past the right edge
        self.assertEqual(state(app, client), before)

    def test_every_row_of_a_scrolled_list_opens_the_agent_it_shows(self) -> None:
        app, _client = agent_app()
        more_agents(app, 7)
        app._on_input(Key(DOWN))
        for _ in range(8):
            app._on_input(Key(DOWN))  # the last agent: main and the two recorded ones scrolled off
        settled(app)
        rows = under_the_frame(app)[:-1]
        self.assertEqual(len(rows), 8, "nine running agents raise the view to a third of 24 rows")
        self.assertEqual([row.split("task ")[1][0] for row in rows if "task " in row], list("0123456"))
        # Each click moves the highlight, and the list scrolls to it; the next row is found on the new screen.
        for number in (6, 4, 0):
            with self.subTest(number=number):
                click(app, 10, row_of(app, f"task {number}"))
                self.assertEqual(app.log_agent, f"sa-extra-{number}")
                app._on_input(Key(CHAR, "q"))
                self.assertEqual(app.list_selected, f"sa-extra-{number}")
        self.assertEqual(under_the_frame(app)[0], "  ● main")  # scrolled back up to the highlight on task 0
        click(app, 10, row_of(app, "read the diff for risks"))
        self.assertEqual(app.log_agent, SECOND)

    def test_the_rows_of_a_short_terminals_list_are_the_ones_clicked(self) -> None:
        app, _client = agent_app(rows=10)
        app._on_input(Key(DOWN))
        settled(app)
        click(app, 3, row_of(app, "read the diff for risks"))
        self.assertEqual(app.log_agent, SECOND)

    def test_while_the_list_is_shown_the_info_line_is_not_there_to_click(self) -> None:
        app, client = running()
        y, x = row_of(app, "2 agents · ↓ agents"), column_of(app, "↓ agents")
        app._on_input(Key(DOWN))
        self.assertEqual(row_of(app, AGENT_LIST_HINT), y)  # the hint stands where the count was
        click(app, x, y)
        self.assertEqual((app.pager, app.list_selected, client.calls), (None, FIRST, []))


class IgnoredReportTests(unittest.TestCase):
    def reports(self, x: int, y: int) -> dict[str, Mouse]:
        return {
            "a release": Mouse(BUTTON_LEFT, x, y, pressed=False),
            "a release naming no button": Mouse(NO_BUTTON, x, y, pressed=False),
            "motion with the button held": Mouse(BUTTON_LEFT, x, y, motion=True),
            "motion with none held": Mouse(NO_BUTTON, x, y, motion=True),
            "the wheel up": Mouse(WHEEL_UP, x, y),
            "the wheel down": Mouse(WHEEL_DOWN, x, y),
            "the middle button": Mouse(BUTTON_MIDDLE, x, y),
            "the right button": Mouse(BUTTON_RIGHT, x, y),
            "a shift click": Mouse(BUTTON_LEFT, x, y, shift=True),
            "an alt click": Mouse(BUTTON_LEFT, x, y, alt=True),
            "a ctrl click": Mouse(BUTTON_LEFT, x, y, ctrl=True),
        }

    def test_on_a_list_row_only_a_plain_left_press_does_anything(self) -> None:
        app, client = listing()
        y = row_of(app, SECOND_ROW)
        before = state(app, client)
        for name, report in self.reports(10, y).items():
            with self.subTest(name):
                app._on_input(report)
                self.assertEqual(state(app, client), before)
        app._on_input(Mouse(BUTTON_LEFT, 10, y))
        self.assertEqual(app.log_agent, SECOND)

    def test_the_same_reports_as_bytes_type_nothing_and_open_nothing(self) -> None:
        app, client = listing()
        y, x = row_of(app, SECOND_ROW), 10
        before = state(app, client)
        codes = (64, 65, 66, 67, 32, 35, 1, 2, 3, 4, 8, 16, 128)  # wheel, motion, other buttons, modifiers, an unnamed one
        data = "".join(f"\x1b[<{code};{x};{y}M" for code in codes) + f"\x1b[<0;{x};{y}m" + "\x1b[M !!"
        for event in KeyDecoder().feed(data.encode("ascii")):
            app._on_input(event)
        self.assertEqual(state(app, client), before)

    def test_a_report_in_the_legacy_encoding_does_not_close_the_list(self) -> None:
        # A terminal without SGR reports answers mode 1000 with `ESC[M` and three bytes, which decodes
        # to one key without a name. The list reads every other key as "leave".
        app, client = focused()
        settled(app)
        before = state(app, client)
        for event in KeyDecoder().feed(b"\x1b[M !!\x1b[M#!!"):  # a press and its release
            app._on_input(event)
        self.assertEqual(state(app, client), before)
        self.assertEqual(app.list_selected, FIRST)
        self.assertEqual(under_the_frame(app)[-1], AGENT_LIST_HINT)

    def test_a_click_opens_nothing_whenever_the_tui_did_not_ask_for_reports(self) -> None:
        def view(app: App, now: list[float]) -> None:
            app._on_input(Key(ESCAPE))  # the list left: the agent view alone is no place to click

        def approval(app: App, now: list[float]) -> None:
            app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
            now[0] += SLOT_ARM_SECONDS

        def keys_pager(app: App, now: list[float]) -> None:
            app._on_input(Key(ESCAPE))  # the list takes every key, `?` too: leave it first
            app._on_input(Key(CHAR, "?"))

        def agent_log(app: App, now: list[float]) -> None:
            app._on_input(Key(ENTER))

        def resizing(app: App, now: list[float]) -> None:
            app._on_resize()  # the size has not settled: the old frame is still on screen, nothing is redrawn

        for into in (view, approval, keys_pager, agent_log, resizing):
            with self.subTest(into.__name__):
                now = [100.0]
                app, client = listing(clock=lambda: now[0])
                y, x = row_of(app, SECOND_ROW), 10
                into(app, now)
                app._render_when_due()
                before = state(app, client)
                click(app, x, y)
                self.assertEqual(state(app, client), before)
                if into is not resizing:
                    self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]

    def test_while_a_question_is_open_a_click_opens_nothing_before_any_frame_redraws_the_cells(self) -> None:
        # The question opens and the click comes in the same read: `clickable` still holds the last frame's cells.
        for method, params in (("approval", {"command": "rm -rf ./x"}), ("vault.code", {})):
            with self.subTest(method=method):
                app, client = listing()
                y = row_of(app, SECOND_ROW)
                self.assertTrue(app.clickable)
                app._on_server_request(ServerRequest("srq-1", method, params))
                self.assertTrue(app.clickable)  # no frame since: the cells are still there
                click(app, 10, y)
                self.assertEqual((app.pager, app.log_agent, client.calls), (None, "", []))
                self.assertIsNotNone(app.slot)

    def test_another_programs_leftover_reports_open_nothing_in_a_session_without_agents(self) -> None:
        app, client = make_app(busy=True)
        settled(app)
        before = state(app, client)
        for y in range(1, 25):
            for x in (1, 10, 40, 80):
                click(app, x, y)
        self.assertEqual(state(app, client), before)
        self.assertEqual(mouse_calls(app), [])


class UnknownRowTests(unittest.TestCase):
    """The region's place on the screen: read where it is certain, and no click read where it is not."""

    def test_at_launch_the_row_is_not_known_so_reports_stay_off_and_a_click_is_not_read(self) -> None:
        app, client = agent_app()  # no Ctrl+L: the app was never told which row the cursor started on
        y, x = row_of(app, SECOND_ROW), column_of(app, "read the diff")
        self.assertIsNone(app.region.last_row(24))
        self.assertFalse(reporting(app))
        before = state(app, client)
        for off in (-1, 0, 1):
            click(app, x, y + off)
        self.assertEqual(state(app, client), before)
        self.assertEqual(mouse_calls(app), [])
        app._on_input(Key(DOWN))  # the keyboard needs no row: the list and the log still open
        app._on_input(Key(ENTER))
        self.assertEqual(app.log_agent, FIRST)

    def test_once_output_has_pushed_the_region_to_the_last_row_the_click_is_read(self) -> None:
        app, _client = agent_app()
        app._on_input(Key(DOWN))
        self.assertFalse(reporting(app))  # the list is open, but its row is not known yet
        app.transcript.add_notice("\n".join(f"line {number}" for number in range(40)))  # more than the screen holds
        self.assertTrue(reporting(app))
        self.assertEqual(app.region.last_row(24), 23)
        y = row_of(app, SECOND_ROW)
        self.assertEqual(y, 24)  # the list's last row, under the info line: the screen's last row
        click(app, 10, y)
        self.assertEqual(app.log_agent, SECOND)

    def test_after_a_redraw_the_region_sits_under_the_output_and_clicks_follow_it(self) -> None:
        app, client = listing()
        screen = drawn(app)
        last = info_index(screen)  # the list's last row is the region's
        self.assertEqual(app.region.last_row(24), last)
        self.assertLess(last, 23)
        self.assertEqual(screen[last + 1 :], [""] * (23 - last))  # nothing under the region
        y = row_of(app, SECOND_ROW)
        self.assertEqual(y, last + 1)  # the report counts from 1, the screen from 0
        before = state(app, client)
        for off in (1, -3):  # the row under the region, the info line
            click(app, 10, y + off)
            self.assertEqual(state(app, client), before)
        click(app, 10, y)
        self.assertEqual(app.log_agent, SECOND)

    def test_when_output_pushes_the_region_down_the_click_follows_it(self) -> None:
        app, _client = listing()
        self.assertLess(row_of(app, SECOND_ROW), 21)
        app.transcript.add_notice("\n".join(f"line {number}" for number in range(40)))
        self.assertEqual(row_of(app, SECOND_ROW), 24)
        self.assertEqual(app.region.last_row(24), 23)
        click(app, 10, 23)  # the row above the second agent's holds the first agent
        self.assertEqual(app.log_agent, FIRST)
        app._on_input(Key(CHAR, "q"))
        click(app, 10, 24)
        self.assertEqual(app.log_agent, SECOND)

    def test_a_redraw_behind_an_open_pager_does_not_claim_the_top_row(self) -> None:
        # The clear went to the alternate screen; the main screen's cursor is wherever the old frame left it.
        app, _client = agent_app()
        app._on_input(Key(CHAR, "?"))
        app._full_redraw()
        app._on_input(Key(CHAR, "q"))
        drawn(app)
        self.assertIsNone(app.region.last_row(24))
        self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]


def step_through(app: App, now: list[float], reads: list[tuple[float, bytes]]) -> None:
    """Run the loop one step per read: each read takes its time on the app's clock, then hands back its bytes."""
    queue = list(reads)

    def read(timeout: float, wake: int | None = None) -> bytes:
        delay, data = queue.pop(0)
        now[0] += delay
        return data

    app.terminal.read = read  # type: ignore[method-assign]
    app.client.poll = lambda: []  # type: ignore[attr-defined]
    while queue:
        app._step()


def paused(first: bytes, pause: float, rest: bytes) -> list[tuple[float, bytes]]:
    """`first`, then `pause` seconds of empty reads, then `rest`, then two seconds of quiet."""
    silences = int(pause / READ_TIMEOUT_SECONDS + 1e-9)
    quiet = [(READ_TIMEOUT_SECONDS, b"")]
    return [(0.0, first), *quiet * silences, (pause - silences * READ_TIMEOUT_SECONDS, rest), *quiet * 40]


class SplitReportLoopTests(unittest.TestCase):
    """The review's two splits of a wheel report, in the loop, while the agent list is open (reports on).

    There Esc leaves the list, so an Esc that waits is seen as the list
    staying open.
    """

    def setUp(self) -> None:
        self.now = [100.0]
        self.app, self.client = listing(clock=lambda: self.now[0])
        self.assertTrue(reporting(self.app))

    def test_a_report_split_after_its_marker_types_nothing_and_does_nothing(self) -> None:
        for pause in (0.06, 0.4, 0.6):
            with self.subTest(pause=pause):
                before = state(self.app, self.client)
                step_through(self.app, self.now, paused(b"\x1b[<65;12", pause, b";40M"))
                self.assertEqual(state(self.app, self.client), before)
                self.assertEqual(self.app.composer.text, "")

    def test_a_report_split_after_its_escape_types_nothing_and_within_300_ms_does_nothing(self) -> None:
        before = state(self.app, self.client)
        step_through(self.app, self.now, paused(b"\x1b", 0.06, b"[<65;12;40M"))
        self.assertEqual(state(self.app, self.client), before)
        # Split for longer than the 300 ms wait, the ESC is Esc (it leaves the list); the rest is still dropped.
        step_through(self.app, self.now, paused(b"\x1b", 0.4, b"[<65;12;40M"))
        self.assertEqual(self.app.composer.text, "")
        self.assertIsNone(self.app.list_selected)
        self.assertEqual(self.client.calls, [])

    def test_esc_pressed_while_reports_are_on_acts_once_300_ms_have_passed(self) -> None:
        step_through(self.app, self.now, [(0.0, b"\x1b"), *[(READ_TIMEOUT_SECONDS, b"")] * 5])
        self.assertEqual(self.app.list_selected, FIRST)  # 250 ms: it may still be a report
        step_through(self.app, self.now, [(READ_TIMEOUT_SECONDS, b"")] * 2)
        self.assertIsNone(self.app.list_selected)  # by 350 ms the list is left

    def test_a_key_typed_while_esc_waits_acts_at_once_and_is_typed(self) -> None:
        step_through(self.app, self.now, [(0.0, b"\x1b"), *[(READ_TIMEOUT_SECONDS, b"")] * 4, (0.0, b"n")])
        self.assertIsNone(self.app.list_selected)  # at 200 ms, not lost
        self.assertEqual(self.app.composer.text, "n")

    def test_with_reports_off_esc_interrupts_at_the_first_silence(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        settled(app)
        self.assertFalse(reporting(app))
        step_through(app, now, [(0.0, b"\x1b"), (READ_TIMEOUT_SECONDS, b"")])
        self.assertEqual(client.named("session.interrupt"), [{"session_id": SID}])


class LateReportLoopTests(unittest.TestCase):
    """Reports the terminal sent before it acted on an off arrive after it, split, and still type nothing."""

    def test_the_release_of_the_click_that_opens_a_log_types_nothing_and_leaves_the_log_open(self) -> None:
        for code in (0, 65):  # the click's own release, and the review's wheel turn
            for pause in (0.06, 0.2, 0.4):
                with self.subTest(code=code, pause=pause):
                    now = [100.0]
                    app, _client = listing(clock=lambda: now[0])
                    y, x = row_of(app, SECOND_ROW), 10
                    step_through(app, now, [(0.0, f"\x1b[<0;{x};{y}M".encode("ascii"))])  # the press opens the log
                    self.assertEqual(app.log_agent, SECOND)
                    self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]  # the log's frame
                    late = f"\x1b[<{code};{x};{y}{'m' if code == 0 else 'M'}".encode("ascii")
                    step_through(app, now, paused(late[:1], pause, late[1:]))
                    self.assertEqual(app.composer.text, "")
                    # Past the 300 ms wait the ESC is Esc, which leaves the log; the rest is still dropped.
                    self.assertEqual(app.log_agent, "" if pause > 0.3 else SECOND)

    def test_a_report_split_after_the_turn_ended_types_nothing_and_interrupts_nothing(self) -> None:
        for pause in (0.06, 0.2, 0.4):
            with self.subTest(pause=pause):
                now = [100.0]
                app, client = listing(clock=lambda: now[0])
                app._on_event(Event("message.complete", SID, {"text": "done"}))
                app.turn_pending = False
                app.list_selected = None  # the list left: reports go off at the next frame
                step_through(app, now, [(0.0, b"")])
                self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
                step_through(app, now, paused(b"\x1b", pause, b"[<0;5;5m"))
                self.assertEqual(app.composer.text, "")
                self.assertEqual(client.named("session.interrupt"), [])

    def test_a_report_that_starts_after_the_grace_is_read_as_keys_as_documented(self) -> None:
        now = [100.0]
        app, _client = listing(clock=lambda: now[0])
        app.turn_pending = False
        app.list_selected = None  # the list left: reports go off at the next frame
        step_through(app, now, [(0.0, b"")])
        self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        now[0] += MOUSE_REPORT_SECONDS
        step_through(app, now, paused(b"\x1b", 0.06, b"[<0;5;5m"))
        self.assertEqual(app.composer.text, "[<0;5;5m")


class SlotArmFromArrivalTests(unittest.TestCase):
    """A question turns reports off as it opens, so an Esc pressed then waits out the grace before it is decided.

    The arm delay counts from when a key's first byte arrived, not from when
    the decoder decided it: an Esc pressed 0.1 s after an approval opened is
    decided 0.4 s after, and must still answer nothing. Reports were on as
    these questions opened, so the delay is `REPORTING_SLOT_ARM_SECONDS`: a
    report's ESC arriving 0.45 s after the off is held for its `[` and then
    read as Esc, and must not answer either.
    """

    APPROVAL = ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"})
    SUDO = ServerRequest("srq-1", "sudo", {"command": "apt install x"})
    DENY = ("srq-1", {"result": {"choice": "deny"}})
    ONCE = ("srq-1", {"result": {"choice": "once"}})
    QUIET = [(READ_TIMEOUT_SECONDS, b"")]
    INSIDE = (0.10, 0.30, 0.39, 0.45)  # first bytes inside the delay; the ESC at 0.45 is held as a report's
    PAST = REPORTING_SLOT_ARM_SECONDS + 0.05

    def press(self, request: ServerRequest, at: float, first: bytes, rest: bytes = b"", then: bytes = b"") -> list:
        """`first` `at` s after `request` opened, `rest` 0.2 s later when given, `then` 2 s after that; the answers sent."""
        now = [100.0]
        app, client = listing(clock=lambda: now[0])
        self.assertTrue(reporting(app))
        app._on_server_request(request)
        step_through(app, now, [(0.0, b"")])  # the frame that turns reports off as the question opens
        self.assertEqual((app.terminal.mouse_reporting, app.mouse_off_at), (False, 100.0))  # type: ignore[attr-defined]
        reads = [(at, first)]
        if rest:
            reads += [*self.QUIET * 3, (READ_TIMEOUT_SECONDS, rest)]
        reads += self.QUIET * 40
        if then:
            reads += [(0.0, then), *self.QUIET]
        step_through(app, now, reads)
        return client.answers

    def test_an_esc_whose_first_byte_came_inside_the_delay_answers_nothing(self) -> None:
        for at in self.INSIDE:
            with self.subTest(at=at):
                self.assertEqual(self.press(self.APPROVAL, at, b"\x1b"), [])
        self.assertEqual(self.press(self.APPROVAL, self.PAST, b"\x1b"), [self.DENY])

    def test_an_enter_split_after_its_escape_is_timed_from_the_escape(self) -> None:
        for at in self.INSIDE:
            with self.subTest(at=at):
                self.assertEqual(self.press(self.APPROVAL, at, b"\x1b", b"[13u"), [])
        self.assertEqual(self.press(self.APPROVAL, self.PAST, b"\x1b[13u"), [self.DENY])

    def test_a_right_arrow_split_after_its_escape_is_timed_from_the_escape(self) -> None:
        for at in self.INSIDE:
            with self.subTest(at=at):
                self.assertEqual(self.press(self.APPROVAL, at, b"\x1b", b"[C", then=b"\r"), [self.DENY])
        self.assertEqual(self.press(self.APPROVAL, self.PAST, b"\x1b[C", then=b"\r"), [self.ONCE])

    def test_the_composers_enter_on_a_question_answered_with_text_is_timed_the_same_way(self) -> None:
        self.assertEqual(self.press(self.SUDO, 0.45, b"\x1b", b"[13u"), [])
        self.assertEqual(self.press(self.SUDO, self.PAST, b"\x1b[13u"), [("srq-1", {"result": {"value": ""}})])

    def test_a_key_whose_first_byte_came_before_the_slot_opened_is_early_however_late_it_is_decided(self) -> None:
        # A Right arrow split twice by jitter around the opening: its ESC 10 ms before, its `[` and its `C` each
        # 0.27 to 0.29 s later, inside the 0.3 s wait. It is decided 0.55 s after the opening, past the delay,
        # and still answers nothing; the untouched approval then denies.
        now = [100.0]
        app, client = listing(clock=lambda: now[0])
        self.assertTrue(reporting(app))
        step_through(app, now, [(0.0, b"\x1b")])
        now[0] += 0.01
        app._on_server_request(self.APPROVAL)
        reads = [(0.04, b""), *self.QUIET * 3, (0.07, b"["), *self.QUIET * 5, (0.04, b"C")]
        step_through(app, now, reads)
        self.assertAlmostEqual(now[0] - app.slot_opened_at, 0.55)
        self.assertEqual(client.answers, [])
        step_through(app, now, [*self.QUIET * 40, (0.0, b"\r"), *self.QUIET])
        self.assertEqual(client.answers, [self.DENY])

    def esc_after_an_off(self, off_before: float | None, at: float) -> list:
        """An Esc `at` s after an approval opened, reports having gone off `off_before` s before it (None: never on)."""
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        settled(app)
        if off_before is not None:
            app._set_mouse(True)
            app._set_mouse(False)
            now[0] += off_before
        app._on_server_request(self.APPROVAL)
        step_through(app, now, [(at, b"\x1b"), *self.QUIET * 20])
        return client.answers

    def test_a_slot_that_opens_within_the_grace_after_an_off_takes_the_longer_delay(self) -> None:
        self.assertEqual(self.esc_after_an_off(0.2, 0.45), [])
        self.assertEqual(self.esc_after_an_off(0.2, self.PAST), [self.DENY])

    def test_a_slot_that_opens_with_no_report_on_its_way_keeps_the_shorter_delay(self) -> None:
        for off_before in (None, MOUSE_REPORT_SECONDS + 0.1):
            with self.subTest(off_before=off_before):
                self.assertEqual(self.esc_after_an_off(off_before, SLOT_ARM_SECONDS - 0.01), [])
                self.assertEqual(self.esc_after_an_off(off_before, SLOT_ARM_SECONDS + 0.05), [self.DENY])


class ResizeTests(unittest.TestCase):
    def test_reports_go_off_as_the_size_changes_and_come_back_with_the_settled_redraw(self) -> None:
        now = [100.0]
        app, _client = listing(clock=lambda: now[0])
        self.assertTrue(reporting(app))
        app.terminal.screen.resize(24, 100)  # type: ignore[attr-defined]
        app._on_resize()
        self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]  # before any frame
        now[0] += RESIZE_SETTLE_SECONDS / 2
        app._render_when_due()
        self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]  # still settling
        now[0] += RESIZE_SETTLE_SECONDS
        app._render_when_due()
        self.assertTrue(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        self.assertEqual(mouse_calls(app), [True, False, True])

    def test_a_click_read_in_the_step_that_sees_the_size_change_is_dropped(self) -> None:
        for paging in (False, True):
            with self.subTest(paging=paging):
                now = [100.0]
                app, client = listing(clock=lambda: now[0])
                y, x = row_of(app, SECOND_ROW), 10
                data = f"\x1b[<0;{x};{y}M".encode("ascii")
                if paging:
                    app._on_input(Key(CHAR, "?"))
                    data = b"q" + data  # the key list left and the click, in one read
                else:
                    app.terminal.screen.resize(24, 100)  # type: ignore[attr-defined]  # the VT model resizes the main screen only
                app.terminal._resized = True  # type: ignore[attr-defined]
                step_through(app, now, [(0.0, data)])
                self.assertEqual((app.pager, app.log_agent, client.calls), (None, "", []))


class DrainTerminal(ScriptedTerminal):
    """A scripted terminal whose reads are a list on its own clock: each `read` takes the next entry, then `endless`.

    A read that brings bytes takes `READ_TAKES` of the clock; one that brings nothing waits its whole timeout.
    """

    READ_TAKES = 0.01

    def __init__(self, incoming: list[bytes | type[BaseException]], endless: bytes = b"") -> None:
        super().__init__()
        self.incoming = list(incoming)
        self.endless = endless
        self.now = [0.0]
        self.log: list[tuple[str, object]] = []  # ("write", text) and ("read", timeout), in order

    def write(self, text: str) -> None:
        self.log.append(("write", text))
        super().write(text)

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        self.log.append(("read", timeout))
        item = self.incoming.pop(0) if self.incoming else self.endless
        if not isinstance(item, bytes):
            raise item("the terminal hung up")
        self.now[0] += min(self.READ_TAKES, timeout) if item else timeout
        return item


class ExitDrainTests(unittest.TestCase):
    REPORT = b"\x1b[<0;30;22M\x1b[<0;30;22m"
    ANSWER = b"\x1b[24;1R"  # the terminal's answer to the cursor position request

    def leaving(self, terminal: DrainTerminal, *, with_reports: bool = True) -> tuple[App, RecordingClient]:
        client = RecordingClient()
        app = App(terminal, client, {}, poller=FakePoller(), clock=lambda: terminal.now[0])  # type: ignore[arg-type]
        app.sid = SID
        app.turn_pending = True
        if with_reports:
            relay(app, STARTS)
        settled(app)
        if with_reports:
            app._on_input(Key(DOWN))  # the list: reports on
            drawn(app)
        self.assertEqual(terminal.mouse_reporting, with_reports)
        terminal.log.clear()
        return app, client

    def reads(self, terminal: DrainTerminal) -> list[float]:
        return [timeout for kind, timeout in terminal.log if kind == "read"]  # type: ignore[misc]

    def writes(self, terminal: DrainTerminal) -> list[str]:
        return [str(what) for kind, what in terminal.log if kind == "write"]

    def test_input_is_dropped_up_to_the_answer_to_a_cursor_position_request_and_no_further(self) -> None:
        incoming: list[bytes | type[BaseException]] = [
            self.REPORT,
            self.REPORT + b"x",  # a key typed meanwhile goes with the reports: the TUI read it and acts on nothing
            b"\x1b[<0;31;22M" + self.ANSWER,
        ]
        terminal = DrainTerminal(incoming, endless=b"typed for the shell")
        app, client = self.leaving(terminal)
        before = state(app, client)
        app._shutdown()
        self.assertEqual(len(self.reads(terminal)), 3)  # it stopped the moment the answer came
        self.assertEqual(state(app, client), before)  # nothing read there was acted on
        self.assertEqual(CURSOR_POSITION_REQUEST, "\x1b[6n")
        writes = self.writes(terminal)
        self.assertEqual((writes[0], writes[-1]), (MOUSE_OFF, CURSOR_POSITION_REQUEST))  # asked after the off
        kinds = [kind for kind, _what in terminal.log]
        self.assertEqual(set(kinds[kinds.index("read") :]), {"read"})  # nothing is written once the drain began

    def test_an_answer_split_across_reads_ends_it_once_whole(self) -> None:
        terminal = DrainTerminal([self.REPORT + b"\x1b[2", b"4;", b"1R"], endless=self.REPORT)
        app, _client = self.leaving(terminal)
        app._shutdown()
        self.assertEqual(len(self.reads(terminal)), 3)

    def test_what_only_looks_like_the_answer_does_not_end_it(self) -> None:
        for lookalike in (b"\x1b[<0;24;1M", b"\x1b[24R", b"\x1b[;1R", b"\x1b[24;R", b"\x1b[1;5A", b"R;1"):
            with self.subTest(lookalike=lookalike):
                terminal = DrainTerminal([lookalike, self.ANSWER], endless=self.REPORT)
                app, _client = self.leaving(terminal)
                app._shutdown()
                self.assertEqual(len(self.reads(terminal)), 2)

    def test_a_terminal_that_never_answers_is_drained_for_a_second_at_most(self) -> None:
        terminal = DrainTerminal([], endless=self.REPORT)  # a terminal that never stops sending
        app, client = self.leaving(terminal)
        before = state(app, client)
        app._shutdown()
        self.assertEqual(EXIT_DRAIN_SECONDS, 1.0)
        self.assertAlmostEqual(terminal.now[0], EXIT_DRAIN_SECONDS)
        waits = self.reads(terminal)
        self.assertTrue(all(0 < wait <= EXIT_DRAIN_SECONDS for wait in waits))
        self.assertEqual(state(app, client), before)

    def test_a_read_that_waits_out_the_time_left_ends_it(self) -> None:
        terminal = DrainTerminal([self.REPORT])
        app, _client = self.leaving(terminal)
        app._shutdown()
        self.assertEqual(len(self.reads(terminal)), 2)
        self.assertAlmostEqual(terminal.now[0], EXIT_DRAIN_SECONDS)

    def test_a_resize_signal_does_not_end_it_early(self) -> None:
        terminal = DrainTerminal([self.REPORT, self.ANSWER], endless=b"typed for the shell")
        app, _client = self.leaving(terminal)
        real = terminal.read
        first = [True]

        def read(timeout: float, wake: int | None = None) -> bytes:
            if first:  # the first read ends at once with nothing read, as a resize signal ends it
                first.clear()
                terminal.log.append(("read", timeout))
                return b""
            return real(timeout, wake)

        terminal.read = read  # type: ignore[method-assign]
        app._shutdown()
        self.assertEqual(len(self.reads(terminal)), 3)  # the empty read, the report, the answer

    def test_a_terminal_that_hung_up_ends_it_quietly(self) -> None:
        terminal = DrainTerminal([self.REPORT, EOFError])
        app, _client = self.leaving(terminal)
        app._shutdown()
        self.assertEqual(len(self.reads(terminal)), 2)

    def test_nothing_is_asked_or_read_when_reports_were_never_on(self) -> None:
        terminal = DrainTerminal([], endless=b"typed ahead for the shell")
        app, _client = self.leaving(terminal, with_reports=False)
        app._shutdown()
        self.assertEqual(self.reads(terminal), [])
        written = "".join(self.writes(terminal))
        self.assertNotIn(MOUSE_OFF, written)
        self.assertNotIn(CURSOR_POSITION_REQUEST, written)

    def test_reports_on_earlier_in_the_run_are_drained_though_they_are_off_at_exit(self) -> None:
        terminal = DrainTerminal([self.REPORT, self.ANSWER], endless=b"typed for the shell")
        app, _client = self.leaving(terminal)
        app.list_selected = None  # the list left: reports off
        drawn(app)
        self.assertFalse(terminal.mouse_reporting)
        terminal.log.clear()
        app._shutdown()
        self.assertEqual(self.writes(terminal)[-1], CURSOR_POSITION_REQUEST)
        self.assertEqual(len(self.reads(terminal)), 2)

    def test_reports_off_for_longer_than_a_report_can_still_arrive_are_not_drained(self) -> None:
        # Nothing is asked, so no cursor position answer can reach the shell's prompt over a slow link.
        for since, drained in ((MOUSE_REPORT_SECONDS + 0.01, False), (MOUSE_REPORT_SECONDS - 0.01, True)):
            with self.subTest(since=since):
                terminal = DrainTerminal([self.REPORT, self.ANSWER], endless=b"typed for the shell")
                app, _client = self.leaving(terminal)
                app.list_selected = None  # the list left: reports off
                drawn(app)
                self.assertFalse(terminal.mouse_reporting)
                terminal.now[0] += since
                terminal.log.clear()
                app._shutdown()
                written = "".join(self.writes(terminal))
                self.assertEqual(CURSOR_POSITION_REQUEST in written, drained)
                self.assertEqual(len(self.reads(terminal)), 2 if drained else 0)

    def test_run_drains_on_its_way_out_however_the_loop_ended(self) -> None:
        def poll_nothing() -> list[object]:
            return []

        def gateway_gone() -> list[object]:
            return [GatewayExited(1)]

        def gateway_broke() -> list[object]:
            raise RuntimeError("a bug in a step")

        endings: dict[str, tuple[list[bytes | type[BaseException]], object, type[BaseException] | None]] = {
            "SIGTERM, as SystemExit in a read": ([SystemExit, self.REPORT, self.ANSWER], poll_nothing, SystemExit),
            # Ctrl+C leaves the list, which takes every key, then Ctrl+D on the empty composer exits.
            "Ctrl+C, then Ctrl+D on an empty composer": ([b"\x03\x04", self.REPORT, self.ANSWER], poll_nothing, None),
            "the gateway exiting": ([b"", self.REPORT, self.ANSWER], gateway_gone, None),
            "an exception out of a step": ([b"", self.REPORT, self.ANSWER], gateway_broke, RuntimeError),
            "the terminal hanging up": ([EOFError, EOFError], poll_nothing, None),
        }
        for ending, (incoming, poll, raised) in endings.items():
            with self.subTest(ending):
                terminal = DrainTerminal(incoming)
                app, client = self.leaving(terminal)
                client.poll = poll  # type: ignore[attr-defined]
                if raised is None:
                    app.run()
                else:
                    with self.assertRaises(raised):
                        app.run()
                writes = self.writes(terminal)
                self.assertEqual(writes[-1], CURSOR_POSITION_REQUEST)  # the drain ran, after the off
                self.assertLess(writes.index(MOUSE_OFF), len(writes) - 1)
                self.assertEqual(len(self.reads(terminal)), 2 if ending == "the terminal hanging up" else 3)
                self.assertFalse(terminal.mouse_reporting)


class DocumentedMouseTests(unittest.TestCase):
    """What INSTALLATION and the OMH TUI boundary page say about the mouse, held to the code they describe."""

    ROOT = Path(__file__).resolve().parents[1]

    def prose(self, name: str) -> str:
        return " ".join((self.ROOT / name).read_text(encoding="utf-8").split())

    def test_the_escape_time_and_the_grace_the_docs_name_are_the_decoders(self) -> None:
        seconds, grace = keys_module.REPORTING_ESCAPE_SECONDS, keys_module.MOUSE_REPORT_SECONDS
        whole = round(seconds + grace, 3)  # past this a stalled report can type its rest
        installation = self.prose("docs/INSTALLATION.md")
        self.assertIn(f"for {grace:g} s after they go off, an Esc pressed on its own acts after {seconds:g} s", installation)
        self.assertIn("Another key typed within that time ends the wait, and both keys act, except `[`", installation)
        self.assertIn("A key the terminal sends in the same burst as the Esc is Alt with that key", installation)
        self.assertIn("the Esc is lost and a character still types", installation)
        self.assertIn(f"A report that starts later than {grace:g} s after they went off", installation)
        self.assertIn(f"so can any report that takes more than {whole:g} s to arrive whole", installation)
        agents = self.prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(f"within {grace:g} s after it goes off, types nothing if it arrives whole within {whole:g} s of its "
                      f"first byte. If {round(seconds * 1000)} ms pass after that byte without the next, the byte is read "
                      f"as Esc, and the rest is dropped only if it arrives within {grace:g} s after that.", agents)
        self.assertIn(f"types nothing if it arrives whole within {whole:g} s of its first byte",
                      self.prose("src/tui/agent_view.py"))

    def test_the_o_continuations_installation_names_are_every_ss3_final(self) -> None:
        named = {"F1 to F4": b"PQRS", "an arrow": b"ABCD", "Home": b"H", "End": b"F"}
        self.assertEqual(sorted(b"".join(named.values())), sorted(keys_module._SS3_FINALS))
        self.assertIn("as is `O` arriving together with the letter that ends F1 to F4, an arrow, Home or End.",
                      self.prose("docs/INSTALLATION.md"))

    def test_no_doc_says_a_split_report_never_types_however_long_the_pause(self) -> None:
        for name in ("src/tui/keys.py", "src/tui/app.py", "src/tui/agent_view.py", "docs/INSTALLATION.md", "docs/OMH-TUI-BOUNDARY.md", "AGENTS.md"):
            with self.subTest(name=name):
                text = self.prose(name)
                self.assertNotIn("however a pause splits it", text)
                self.assertNotIn("the rest is dropped.", text)
                self.assertNotIn("any key but `[`", text)

    def test_the_wait_is_not_credited_to_tmux_or_vim(self) -> None:
        # tmux's escape-time default is 500 ms (10 ms since 3.5) and Vim's ttimeoutlen 100: neither is 300.
        for name in ("src/tui/keys.py", "src/tui/app.py", "src/tui/agent_view.py", "docs/INSTALLATION.md", "docs/OMH-TUI-BOUNDARY.md", "AGENTS.md"):
            with self.subTest(name=name):
                text = self.prose(name)
                self.assertNotIn("tmux and vim", text)
                self.assertNotIn("escape-time", text)

    def test_the_way_to_select_anyway_is_named_for_each_terminal_no_more_surely_than_it_is_known(self) -> None:
        text = self.prose("docs/INSTALLATION.md")
        self.assertIn(
            "hold Fn while dragging in Terminal.app (or turn off View → Allow Mouse Reporting), Option in iTerm2, "
            "Shift in most other terminals",
            text,
        )
        self.assertNotIn("Option-drag in Terminal.app", text)

    def test_the_boundary_says_what_each_click_does_and_when_a_report_can_still_type(self) -> None:
        text = self.prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn("A plain left click on an agent opens its log, one on the list's `main` row leaves the list, and "
                      "every other report does nothing.", text)
        self.assertIn("One that starts later and is split right after its first or second byte is read as keys.", text)
        for name in ("docs/OMH-TUI-BOUNDARY.md", "AGENTS.md"):
            with self.subTest(name=name):
                self.assertNotIn("No report ever types", self.prose(name))
                self.assertNotIn("a report can open an agent's log and nothing else", self.prose(name))


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class MouseReplayTests(AppTestCase):
    def scenario(self) -> Scenario:
        return delegating_scenario(("subagent.tail", {"result": {"subagent_id": SECOND, "available": False}}))

    def test_in_the_real_loop_reports_wait_for_the_list_and_a_click_on_its_row_opens_that_agent(self) -> None:
        run = self.prepare(self.scenario())
        terminal = run.terminal
        x, aimed = 10, [0]
        on = lambda: terminal.mouse_reporting  # noqa: E731
        listed = terminal.shows(AGENT_LIST_HINT)
        near_misses = Step(when=lambda: on() and listed() and aim(), capture="listed", label="the list, reports on")
        hit = Step(when=listed, capture="ignored", label="ignored")

        def aim() -> bool:
            """Aim at the second agent's row where the screen shows it (a report counts rows from 1)."""
            y = aimed[0] = next(index for index, row in enumerate(terminal.screen.lines()) if SECOND_ROW in row) + 1
            near_misses.data = b"".join(f"\x1b[<{code};{x};{y}M".encode("ascii") for code in (64, 65, 35, 2)) + (
                f"\x1b[<0;{x};{y}m\x1b[<0;{x};{y + 1}M\x1b[<0;{x};{y + 2}M".encode("ascii")
            )
            hit.data = f"\x1b[<0;{x};{y}M".encode("ascii")
            return True

        terminal.script(
            self.submit(run, INTERRUPTED_PROMPT),
            Step(b"\x0c", when=terminal.shows("  ● main"), capture="launched", label="the view"),
            Step(b"\x1b[B", when=lambda: terminal.shows("  ● main")() and not on(), capture="redrawn", label="no reports"),
            near_misses,
            hit,
            Step(b"q", when=terminal.shows("read the diff · ←/→ agents"), capture="log", label="the second agent's log"),
            Step(b"\x1b", when=lambda: on() and listed(), capture="back", label="the list again"),
            Step(b"\x1b", when=lambda: not listed() and not on(), label="the view again"),
            # The agent view stays under the info line after the turn: `idle` reads the screen's last row.
            Step(b"\x04", when=lambda: "Interrupted." in terminal.history() and terminal.shows(IDLE_HINT)(),
                 capture="over", label="the end"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        captures = terminal.captures
        # The coordinates above are where the screen showed the thing clicked.
        rows, y = captures["listed"], aimed[0]
        self.assertEqual(info_index(rows), y - 1)  # the list's last row (y counts from 1, the screen from 0)
        self.assertIn("read the diff for risks", rows[y - 1])
        self.assertEqual(info_left(rows[y - 4]), AGENT_LIST_HINT)  # over main and two agents; the effort on the right
        # Wheel, motion, a right press, a release and two near misses (the two rows under the region): still the
        # list, on the first agent, and nothing typed.
        ignored = captures["ignored"]
        self.assertIn("▸ ", ignored[y - 2])
        self.assertEqual(captures["log"][0], "read the diff for risks")
        self.assertEqual(run.calls("subagent.tail")[0]["params"], {"session_id": LIVE_ID, "subagent_id": SECOND})
        # Off during the turn with the view shown, on with the list, off for the log, on back in the list, off once
        # the list is left.
        self.assertEqual(terminal.mouse_calls, [True, False, True, False])
        self.assertFalse(terminal.mouse_reporting)
        self.assertEqual(len(run.calls("session.interrupt")), 1)


def composer_text(screen: list[str]) -> str:
    return screen[composer_index(screen)]


if __name__ == "__main__":
    unittest.main()
