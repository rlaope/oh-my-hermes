"""The OMH TUI's loop and entry point, driven end to end.

Each test runs `omh.tui.app.main` (or the `App` it builds) with a scripted
terminal whose output lands in the VT screen model, a fake HUD poller, and the
real `GatewayClient` talking to the replay gateway, which plays recorded Hermes
6c61c3e27d frames and checks every frame the TUI sends against the recording.
The TUI's startup differs from the recording client's (it asks `config.get`,
`commands.catalog`, `session.list` and `model.options` after `session.create`,
without waiting for any), so those are answered from the scenario's answer
table: the catalog and the session list with their recorded answers, the
config with an empty one and the configured default with no model.

A script step waits for a condition on what the screen shows, then delivers
its bytes (or a resize); one silent read follows every step, so a lone Esc
settles as the Escape key. A step that never becomes ready ends the run with
EOF after a deadline and is reported by its label.
"""

from __future__ import annotations

import base64
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import time
import unittest
from unittest.mock import patch

from _test_temp_root import make_test_tempdir
from _tui_gateway_replay import (
    EXIT,
    HANG,
    Scenario,
    client_frames,
    load_fixture,
    materialize,
    recorded_answer,
    replay_env,
    spans,
)
from _tui_lines import info_row_index, without_badge, composer_text, INFO_INSET, line_text, RULE_ROW, rule_rows
from _vt_screen import VTScreen
from omh.tui import terminal as terminal_module
from omh.skin_pack import default_theme, hex_to_rgb, theme_for_name, write_theme_choice
from omh.tui.app import (
    EXIT_HINT,
    SEND_NOW_HINT,
    SLOT_ARM_SECONDS,
    App,
    banner_logo,
    initial_theme,
    main,
    picker_key,
    run_model_chain_picker,
)
from omh.tui.gateway import GatewayClient, GatewayUnavailable, ServerRequest, gateway_spawn
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, UP, Key, Mouse, Paste
from omh.tui.launch import CLOSED_EXIT, FALLBACK_EXIT, FALLBACK_SENTINEL_ENV, SESSION_FILE_ENV
from omh.tui.modes import ACCEPT_LABEL, PLAN_LABEL, info_line
from omh.tui.screen import CLEAR_SCREEN_AND_SCROLLBACK, ERASE_SCROLLBACK
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME, theme_named
from omh.tui.width import line_width
from omh.version import __version__

FAST_GRACE = 0.3
STORED_ID = "20261013_115656_e709ea"
LIVE_ID = "b6af062a"
APPROVAL_STORED_ID = "20261013_115811_9850e7"
ROTATED_ID = "20261013_130000_rotated"
RULE_MARK = "────"  # in both of the composer's rules
BOX_MARK = RULE_ROW  # one of the composer's rules: two per frame, above and under it
# The working row's clock, `(12s · …` or `(1m 4s)`: on screen while a turn runs or waits on the person.
WORKING_CLOCK = re.compile(r"\(\d+(?:m \d+)?s(?: · |\))")
# Between turns in the normal mode: the info line's left side is the badge alone, or with the agent count after it.
IDLE_LEFT = re.compile(r"\d+ agents?(?: · ↓ agents)?")
EMPTY_COMPOSER = "❯ Ask Hermes anything"  # the composer's placeholder: nothing typed
# Between the composer and the info line on these 24-row terminals: the bottom rule.
UNDER_COMPOSER = 1
# Only the session call is awaited. The catalog is read after the session, naming it, so project-local skills
# are listed for its workspace; a fresh session then asks for the stored sessions, to name the last one. Last,
# the config file's mtime and Hermes' configured default model, which a later move is measured from.
STARTUP_METHODS = [
    "client.capabilities", "session.create", "config.get", "commands.catalog", "session.list", "config.get",
    "model.options",
]
NO_TERMIOS = terminal_module.termios is None
# The block logo a start shows above the banner on these 24-row terminals from 100 columns: six rows and a blank.
LOGO = [line_text(row) for row in banner_logo(default_theme(), None, 100, 24)]
LOGO_ROWS = len(LOGO)
TURN_CANCELLED = "Turn cancelled before the agent was ready"


# Hermes 6c61c3e27d's answer to `session.interrupt` (`methods_session_interrupt.py`), which every approval deny now sends.
INTERRUPTED = ("session.interrupt", {"result": {"status": "interrupted"}})


# Hermes' configured default (a `model.options` naming no session): the same at every read, so nothing moves.
NO_DEFAULT = ("model.options", {"result": {"model": "", "provider": ""}})
# A launch whose default read Hermes refused: nothing to measure a move from, so a turn starts without the check
# (`App._start_turn`). Tests of what input typed in one burst does during a turn use it.
UNREAD_DEFAULT = ("model.options", {"error": {"code": 4001, "message": "no default"}})


def startup_answers(default: tuple[str, dict] = NO_DEFAULT) -> tuple[tuple[str, dict], ...]:
    return (
        ("config.get", {"result": {"config": {}}}),
        ("commands.catalog", recorded_answer("session", "commands_catalog")),
        # The last-session lookup a fresh session makes: the recording lists only the session itself.
        ("session.list", recorded_answer("session", "session_list")),
        default,
    )


class TtyStream(io.StringIO):
    def __init__(self, tty: bool = True) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@dataclass
class Step:
    data: bytes = b""
    when: Callable[[], bool] | None = None
    resize: tuple[int, int] | None = None  # (rows, cols)
    capture: str = ""  # save the screen under this name when the step fires
    label: str = ""


class ScriptedTerminal:
    """What `App` needs from a terminal: scripted input, output fed to a VT screen, a scriptable size."""

    def __init__(self, rows: int = 24, cols: int = 80, timeout: float = 20.0) -> None:
        self.screen = VTScreen(rows, cols)
        self.steps: deque[Step] = deque()
        self.timeout = timeout
        self.deadline = 0.0
        self.stalled = ""
        self.captures: dict[str, list[str]] = {}
        self.writes: list[str] = []
        self.entered = 0
        self.exited = 0
        self.fired: dict[str, float] = {}  # label -> when that step fired
        self.exited_at = 0.0
        self.mouse_reporting = False
        self.mouse_drag = False  # reports include a held button's motion (the pager's drag)
        self.mouse_calls: list[bool] = []  # every `set_mouse` that changed the state, in order
        self.background: str | None = None  # what the background query answers
        self.cursor_row: int | None = None  # the 1-based cursor row the same query reports
        self.typed_during_query = b""  # input the query read while it waited
        self.background_queries = 0
        self.suspended = 0  # `suspend` calls: a job stopped and continued at once
        self.cursor_queries = 0  # `query_cursor_row` calls, which answer `cursor_row`
        self.typed_after_stop = b""  # input that query read while it waited
        self._resized = False
        self._quiet = False

    def script(self, *steps: Step) -> None:
        self.steps.extend(steps)

    def __enter__(self) -> ScriptedTerminal:
        self.entered += 1
        if not self.deadline:
            self.deadline = time.monotonic() + self.timeout
        return self

    def __exit__(self, *exc: object) -> None:
        self.exited += 1
        self.exited_at = time.monotonic()

    def size(self) -> tuple[int, int]:
        return (self.screen.cols, self.screen.rows)

    def query_background(self) -> tuple[str | None, bytes, int | None]:
        self.background_queries += 1
        return self.background, self.typed_during_query, self.cursor_row

    def query_cursor_row(self) -> tuple[bytes, int | None]:
        self.cursor_queries += 1
        return self.typed_after_stop, self.cursor_row

    def resized(self) -> bool:
        resized, self._resized = self._resized, False
        return resized

    def write(self, text: str) -> None:
        self.writes.append(text)
        self.screen.feed(text)

    def suspend(self) -> bool:
        """As `Terminal.suspend` for a job the shell continues at once: counted, nothing written."""
        self.suspended += 1
        return True

    def set_mouse(self, enabled: bool, drag: bool = False) -> None:
        """As `Terminal.set_mouse`: the mode switch is written only when the state changes."""
        drag = enabled and drag
        if drag != self.mouse_drag:
            self.mouse_drag = drag
            self.write(terminal_module.MOUSE_DRAG_ON if drag else terminal_module.MOUSE_DRAG_OFF)
        if enabled == self.mouse_reporting:
            return
        self.mouse_reporting = enabled
        self.mouse_calls.append(enabled)
        self.write(terminal_module.MOUSE_REPORTING_ON if enabled else terminal_module.MOUSE_REPORTING_OFF)

    def _wait(self, what: str) -> bytes:
        if time.monotonic() > self.deadline:
            self.stalled = what
            raise EOFError(what)
        time.sleep(0.005)
        return b""

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        if self._quiet:
            self._quiet = False
            return self._wait("the silence after a step")
        if not self.steps:
            return self._wait("the script ran out before the TUI exited")
        step = self.steps[0]
        if step.when is not None and not step.when():
            return self._wait(step.label or f"step {step!r}")
        self.steps.popleft()
        self._quiet = True
        if step.label:
            self.fired[step.label] = time.monotonic()
        if step.capture:
            self.captures[step.capture] = self.screen.lines()
        if step.resize is not None:
            self.screen.resize(*step.resize)
            self._resized = True
        return step.data

    # -- reading the screen --

    def info_row(self) -> str:
        """The info line, its badge taken out: the last row that starts with the badge, else the screen's last row that
        is not blank (an agent view's rows stand under the line; "" on a blank screen)."""
        rows = [line for line in self.screen.lines() if line]
        badged = [line for line in rows if without_badge(line) != line]
        return without_badge((badged or rows)[-1]) if rows else ""

    def history(self) -> str:
        return "\n".join(self.screen.history())

    def idle(self) -> bool:
        """No turn runs and nothing asks (agents may still run): no working row is on the screen, and the info line
        names the mode in accept or plan, or, in the normal mode, says nothing after the badge but the agent count
        while the composer is empty (a draft, Esc's or Ctrl+C's second press, a picker or a question each say or
        hide something)."""
        lines = self.screen.lines()
        if any(WORKING_CLOCK.search(line) for line in lines):
            return False
        body = self.info_row().removeprefix(INFO_INSET)
        if body.startswith((ACCEPT_LABEL, PLAN_LABEL)):
            return True
        left = re.split(r" {3,}", body)[0].strip()
        return (not left or IDLE_LEFT.fullmatch(left) is not None) and any(line.startswith(EMPTY_COMPOSER) for line in lines)

    def running(self) -> bool:
        """A turn runs and nothing asks: the working row counts its seconds."""
        return any(WORKING_CLOCK.search(line) for line in self.screen.lines()) and not self.idle()

    def shows(self, needle: str) -> Callable[[], bool]:
        return lambda: needle in "\n".join(self.screen.lines())

    def prompt_foreground(self) -> tuple[int, ...]:
        """The colour of the composer's `❯`, read off the screen: the last row that starts with one, at its first cell."""
        rows = self.screen.lines()
        row = next(index for index in range(len(rows) - 1, -1, -1) if rows[index].startswith("❯ "))
        attrs = self.screen.attrs_at(row, 0)
        start = attrs.index(38)
        return tuple(attrs[start + 2 : start + 5])

    def box_foreground(self) -> tuple[int, ...]:
        """The colour of the composer's top rule, read off the screen."""
        rows = self.screen.lines()
        row = next(index for index, line in enumerate(rows) if line.startswith(RULE_ROW))
        attrs = self.screen.attrs_at(row, 0)
        start = attrs.index(38)
        return tuple(attrs[start + 2 : start + 5])


class FakePoller:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.started = False
        self.stopped = False
        self.wake: object = None

    def start(self, wake: object = None) -> None:
        self.started = True
        self.wake = wake

    def stop(self, timeout: float = 1.0) -> None:
        self.stopped = True

    def set_session(self, stored_id: str) -> None:
        self.sessions.append(stored_id)

    def take(self) -> None:
        return None

    def refresh(self) -> int:
        self.refreshes = getattr(self, "refreshes", 0) + 1
        return self.refreshes

    def watch_tokens(self, session_ids: Sequence[str]) -> None:
        self.watched = tuple(session_ids)


@dataclass
class Run:
    root: Path
    environ: dict[str, str]
    terminal: ScriptedTerminal
    poller: FakePoller = field(default_factory=FakePoller)
    stderr: io.StringIO = field(default_factory=io.StringIO)
    clients: list[GatewayClient] = field(default_factory=list)
    code: int | None = None

    @property
    def frames(self) -> list[dict]:
        return client_frames(self.root)

    def calls(self, method: str) -> list[dict]:
        return [frame for frame in self.frames if frame.get("method") == method]

    @property
    def active_session_file(self) -> Path:
        return Path(self.environ["HERMES_TUI_ACTIVE_SESSION_FILE"])

    @property
    def fallback_sentinel(self) -> Path:
        return Path(self.environ[FALLBACK_SENTINEL_ENV])


class AppTestCase(unittest.TestCase):
    def prepare(self, scenario: Scenario, *, rows: int = 24, cols: int = 80, env: dict | None = None) -> Run:
        root = Path(self.enterContext(make_test_tempdir("omh-tui-app-")))
        materialize(root, scenario)
        environ = {
            **replay_env(root),
            "HERMES_TUI_ACTIVE_SESSION_FILE": str(root / "active-session.json"),
            "HERMES_TUI_CWD": "/fixture/project",
            # The input history file goes here, never into the person's own ~/.hermes.
            "HERMES_HOME": str(root),
            "TERM": "xterm-256color",
            FALLBACK_SENTINEL_ENV: str(root / "fallback"),
            "OMH_TUI_GLOW": "0",  # the working glow's margin moves every row; its own tests turn it on
            **(env or {}),
        }
        environ.pop("OMH_NO_TUI", None)
        return Run(root, environ, ScriptedTerminal(rows, cols))

    def make_client(self, run: Run) -> Callable[..., GatewayClient]:
        def build(spawn: object, **options: object) -> GatewayClient:
            client = GatewayClient(spawn, **options)  # type: ignore[arg-type]
            run.clients.append(client)
            self.addCleanup(client.close, FAST_GRACE)
            return client

        return build

    def run_main(self, run: Run) -> Run:
        run.code = main(
            run.environ,
            stdin=TtyStream(),
            stdout=TtyStream(),
            stderr=run.stderr,
            open_terminal=lambda: run.terminal,
            make_client=self.make_client(run),
            make_poller=lambda omh_home, hermes_home: run.poller,
        )
        return run

    def assert_clean_run(self, run: Run, code: int = 0) -> None:
        self.assertEqual(run.terminal.stalled, "", f"the script stalled; screen:\n{run.terminal.history()}")
        self.assertEqual(run.code, code, run.stderr.getvalue())
        tails = [line for client in run.clients for line in client.stderr_tail()]
        self.assertFalse([line for line in tails if line.startswith("replay:")], tails)
        self.assertFalse(run.fallback_sentinel.exists(), "a session that ran asked for the fallback")

    def assert_fell_back(self, run: Run) -> None:
        """Exit 75 and the sentinel `omh` named: without the file, `omh` passes the 75 on instead."""
        self.assertEqual(run.code, FALLBACK_EXIT, run.stderr.getvalue())
        self.assertTrue(run.fallback_sentinel.exists(), "exited 75 without creating the fallback sentinel")

    def submit(self, run: Run, text: str) -> Step:
        return Step(text.encode("utf-8") + b"\r", when=run.terminal.idle, label="the idle info line")


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class StartupRefusalTests(AppTestCase):
    def test_an_unsupported_terminal_falls_back_before_anything_starts(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup")))
        run.code = main(
            run.environ,
            stdin=TtyStream(tty=False),
            stdout=TtyStream(),
            stderr=run.stderr,
            open_terminal=lambda: run.terminal,
            make_client=self.make_client(run),
            make_poller=lambda omh_home, hermes_home: run.poller,
        )
        self.assert_fell_back(run)
        self.assertIn("cannot run the OMH TUI", run.stderr.getvalue())
        self.assertEqual(run.clients, [])
        self.assertEqual(run.terminal.writes, [])

    def test_a_missing_interpreter_falls_back_naming_it(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup")))
        del run.environ["HERMES_PYTHON"]
        self.run_main(run)
        self.assert_fell_back(run)
        self.assertIn("HERMES_PYTHON", run.stderr.getvalue())
        self.assertEqual(run.terminal.entered, 0)

    def test_an_attach_hand_off_exits_1_naming_hermes_resume(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup")),
            env={"HERMES_TUI_GATEWAY_URL": "ws://127.0.0.1:9/attach", "HERMES_TUI_RESUME": "20261013_000000_abc"},
        )
        self.run_main(run)
        self.assertEqual(run.code, 1)
        self.assertFalse(run.fallback_sentinel.exists())
        self.assertIn("hermes --tui --resume 20261013_000000_abc", run.stderr.getvalue())
        self.assertEqual(run.clients, [])
        self.assertEqual(run.terminal.entered, 0)

    def test_drift_on_the_session_call_falls_back_and_reaps_the_gateway(self) -> None:
        # Hermes 6c61c3e27d's real -32601 answer, served for session.create.
        drift = recorded_answer("session", "drift_reply")
        run = self.prepare(Scenario("session", spans("session", "startup"), answers=(("session.create", drift),)))
        shell = [f"$ shell {n}" for n in range(5)]
        run.terminal.screen.feed("".join(f"{line}\r\n" for line in shell))
        self.run_main(run)
        self.assert_fell_back(run)
        self.assertIn("-32601", run.stderr.getvalue())
        self.assertEqual(run.terminal.entered, 0)
        # A launch that falls back clears nothing: the shell's rows stay on the screen, and nothing went to scrollback.
        self.assertEqual((run.terminal.screen.lines()[:5], run.terminal.screen.scrollback), (shell, []))
        self.assertEqual(run.clients[0].close(grace=FAST_GRACE), 0)

    def test_drift_on_the_busy_mode_call_is_a_notice_and_the_session_goes_on(self) -> None:
        # config.get is answered after the first frame, and the busy mode has a default: its drift costs nothing.
        drift = recorded_answer("session", "drift_reply")
        answers = (
            ("config.get", drift),
            ("commands.catalog", recorded_answer("session", "commands_catalog")),
            ("session.list", recorded_answer("session", "session_list")),
            NO_DEFAULT,
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        run.terminal.script(
            Step(b"\x04", when=lambda: "did not send its settings" in run.terminal.history() and run.terminal.idle(),
                 label="the settings notice")
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertNotIn("this Hermes refused config.get", run.stderr.getvalue())

    def test_the_gateway_stderr_printed_at_a_failed_start_carries_no_escape_sequence(self) -> None:
        run = self.prepare(
            Scenario("session", (), stderr=("\x1b[31mboom\x1b[0m: no provider\x1b]0;title\x07",), after=EXIT, exit_code=1)
        )
        self.run_main(run)
        self.assert_fell_back(run)
        printed = run.stderr.getvalue()
        self.assertIn("  boom: no provider\n", printed)
        self.assertNotIn("\x1b", printed)
        self.assertNotIn("\x07", printed)

    def test_the_fallback_marker_carries_every_line_said_about_a_failed_start(self) -> None:
        # Hermes' own TUI, which `omh` opens next, clears these lines from the screen; `omh` says them again after.
        run = self.prepare(Scenario("session", (), stderr=("refused: home is owned by a running gateway",),
                                    after=EXIT, exit_code=1))
        self.run_main(run)
        self.assert_fell_back(run)
        printed = run.stderr.getvalue()
        self.assertIn("  refused: home is owned by a running gateway\n", printed)
        self.assertEqual(run.fallback_sentinel.read_text(encoding="utf-8"), printed)

    def test_ctrl_c_while_the_session_opens_exits_130_and_closes_the_gateway(self) -> None:
        # The gateway start and the session call run before the terminal goes raw, where
        # Ctrl+C is still SIGINT; KeyboardInterrupt stands in for it on the first startup call.
        run = self.prepare(Scenario("session", spans("session", "startup"), answers=startup_answers()))
        build = self.make_client(run)

        def interrupted(spawn: object) -> GatewayClient:
            client = build(spawn)
            call = client.call

            def call_or_interrupt(method: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
                if method == "session.create":
                    raise KeyboardInterrupt
                return call(method, params, timeout, cancel)  # type: ignore[arg-type]

            client.call = call_or_interrupt  # type: ignore[method-assign]
            return client

        run.code = main(
            run.environ,
            stdin=TtyStream(),
            stdout=TtyStream(),
            stderr=run.stderr,
            open_terminal=lambda: run.terminal,
            make_client=interrupted,
            make_poller=lambda omh_home, hermes_home: run.poller,
        )
        self.assertEqual(run.code, 130)
        self.assertIn("interrupted", run.stderr.getvalue())
        self.assertNotIn("Traceback", run.stderr.getvalue())
        self.assertEqual(run.terminal.entered, 0)
        with self.assertRaises(GatewayUnavailable):  # its input was closed: the child is being reaped
            run.clients[0].request("session.list", {"limit": 1})


# What `Terminal.query_background` writes before the first frame: the background, the cursor's row, the attributes.
STARTUP_QUERY = (
    terminal_module.BACKGROUND_QUERY + terminal_module.CURSOR_POSITION_QUERY + terminal_module.DEVICE_ATTRIBUTES_QUERY
)


class WireTerminal(ScriptedTerminal):
    """Writes the startup query's bytes as the real terminal does, so the launch's own writes show in their order."""

    def query_background(self) -> tuple[str | None, bytes, int | None]:
        self.write(STARTUP_QUERY)
        return super().query_background()


class SignalledTerminal(ScriptedTerminal):
    """Raises `signum` in this process from inside the loop, the first time the TUI is idle."""

    def __init__(self, signum: int) -> None:
        super().__init__()
        self.signum = signum

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        if self.signum and self.idle():
            signum, self.signum = self.signum, 0
            signal.raise_signal(signum)
        return super().read(timeout, wake)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class ExitSignalTests(AppTestCase):
    def test_sigterm_and_sighup_restore_the_terminal_reap_the_gateway_and_put_the_handler_back(self) -> None:
        for name in ("SIGTERM", "SIGHUP"):
            with self.subTest(signal=name):
                signum = getattr(signal, name)
                caught: list[int] = []

                def outer(number: int, frame: object) -> None:
                    caught.append(number)  # only reached if the TUI installed no handler of its own

                # The handler the TUI must restore, and a guard: a TUI that installs none
                # leaves this runner alive and the script below exits it.
                self.addCleanup(signal.signal, signum, signal.signal(signum, outer))
                run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
                # Under `omh` too: a signal's code is never the closed-session one.
                run.environ[SESSION_FILE_ENV] = str(run.root / "omh-session.json")
                run.terminal = SignalledTerminal(signum)
                run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
                with self.assertRaises(SystemExit) as raised:
                    self.run_main(run)
                self.assertEqual(raised.exception.code, 128 + signum)
                self.assertEqual(caught, [])
                self.assertEqual((run.terminal.entered, run.terminal.exited), (1, 1))
                with self.assertRaises(GatewayUnavailable):  # its input was closed: the child is being reaped
                    run.clients[0].request("session.list", {"limit": 1})
                self.assertIs(signal.getsignal(signum), outer)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class SessionTests(AppTestCase):
    def test_startup_draws_status_and_composer_and_writes_the_active_session_file(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.environ[SESSION_FILE_ENV] = str(run.root / "omh-session.json")
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, capture="ready", label="the first frame"))
        self.run_main(run)
        self.assert_clean_run(run, CLOSED_EXIT)  # `omh` launched it: Hermes prints no epilogue, `omh` its card
        screen = run.terminal.captures["ready"]
        info = info_index(screen)
        self.assertTrue(screen[info].startswith(INFO_INSET + "[⚚ OMH Native]   "), screen)  # the badge alone on the left
        self.assertIn("v4.1-flash-ultrafast · ", screen[info])  # its short name beside the badge at 80 columns
        composer = info - 1 - UNDER_COMPOSER
        self.assertEqual(composer_text(screen[composer]), "❯ Ask Hermes anything", screen)
        self.assertTrue(screen[composer - 1].startswith(BOX_MARK), screen)
        self.assertTrue(screen[composer + 1].startswith(RULE_ROW), screen)
        self.assertEqual([frame["method"] for frame in run.frames], STARTUP_METHODS)
        self.assertEqual(run.calls("config.get")[0]["params"], {"key": "full"})
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": STORED_ID})
        self.assertEqual(stat.S_IMODE(os.stat(run.active_session_file).st_mode), 0o600)
        # `omh`'s own copy names the home whose state database holds the session, for the exit card.
        omh_session = Path(run.environ[SESSION_FILE_ENV])
        self.assertEqual(json.loads(omh_session.read_text(encoding="utf-8")),
                         {"session_id": STORED_ID, "hermes_home": str(run.root), "opened": []})
        self.assertEqual(stat.S_IMODE(os.stat(omh_session).st_mode), 0o600)
        self.assertEqual(run.poller.sessions, [STORED_ID])
        self.assertTrue(run.poller.started and run.poller.stopped)
        # A new HUD snapshot wakes the loop as gateway news does: through the app, whichever client is live.
        self.assertEqual(getattr(run.poller.wake, "__func__", None), App._wake_loop)
        self.assertEqual((run.terminal.entered, run.terminal.exited), (1, 1))
        # The region is gone after exit; nothing of it is left on the screen.
        self.assertNotIn(BOX_MARK, run.terminal.history())

    def test_a_typed_prompt_is_submitted_and_the_reply_lands_in_scrollback(self) -> None:
        prompt = "Reply with exactly the word: ok"
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers())
        )
        run.terminal.script(
            self.submit(run, prompt),
            Step(b"\x04", when=lambda: "later." in run.terminal.history() and run.terminal.idle(), label="reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (submitted,) = run.calls("prompt.submit")
        self.assertEqual(submitted["params"], {"session_id": LIVE_ID, "text": prompt})
        history = run.terminal.history()
        self.assertIn(f"❯ {prompt}", history)
        self.assertIn("I'm Hermes, your agent", history)
        self.assertLess(history.index(f"❯ {prompt}"), history.index("I'm Hermes"))

    def test_input_during_a_turn_is_queued_and_sent_when_the_turn_ends(self) -> None:
        run = self.prepare(
            Scenario(
                "session",
                spans("session", "startup", "create", "plain_turn", "smart_approved_turn"),
                answers=startup_answers(),
            )
        )
        run.terminal.script(
            # One read: the second Enter lands while the first prompt's turn is pending.
            Step(b"first prompt\rsecond prompt\r", when=run.terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: "cleanly)." in run.terminal.history() and run.terminal.idle(), label="turn 2"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        first, second = run.calls("prompt.submit")
        self.assertEqual(first["params"], {"session_id": LIVE_ID, "text": "first prompt"})
        self.assertEqual(second["params"], {"session_id": LIVE_ID, "text": "second prompt", "queued": True})
        history = run.terminal.history()
        self.assertLess(history.index("  ❯ first prompt"), history.index("later."))
        self.assertLess(history.index("later."), history.index("❯ second prompt"))

    def test_ctrl_c_during_a_turn_sends_session_interrupt(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "interrupted_turn"), answers=startup_answers())
        )
        run.terminal.script(
            self.submit(run, "Write the numbers from 1 to 300, one per line, nothing else."),
            Step(b"\x03", when=run.terminal.running, label="running"),
            Step(b"\x04", when=lambda: "Interrupted." in run.terminal.history() and run.terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (interrupt,) = run.calls("session.interrupt")
        self.assertEqual(interrupt["params"], {"session_id": LIVE_ID})

    def test_ctrl_c_twice_during_a_turn_interrupts_once_and_exits_0(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "interrupted_turn"), answers=startup_answers())
        )
        run.terminal.script(
            self.submit(run, "Write the numbers from 1 to 300, one per line, nothing else."),
            Step(b"\x03", when=run.terminal.running, label="running"),
            Step(b"\x03", when=run.terminal.shows(EXIT_HINT), label="the exit hint"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame["params"] for frame in run.calls("session.interrupt")], [{"session_id": LIVE_ID}])

    def test_a_session_closed_under_omh_exits_closed_exit_and_elsewhere_0(self) -> None:
        # Hermes' launcher prints its exit summary, naming `hermes --tui --resume`, for 0 and 130 only.
        closes = {
            "ctrl+c twice": lambda run: (Step(b"\x03", when=run.terminal.idle, label="idle"),
                                         Step(b"\x03", when=run.terminal.shows(EXIT_HINT), label="the exit hint")),
            "ctrl+d": lambda run: (Step(b"\x04", when=run.terminal.idle, label="idle"),),
            "/exit": lambda run: (self.submit(run, "/exit"),),
        }
        for launched_by_omh in (True, False):
            for name, steps in closes.items():
                with self.subTest(omh=launched_by_omh, close=name):
                    answers = (*startup_answers(), ("session.close", {"result": {"closed": True}}))
                    run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
                    if launched_by_omh:
                        run.environ[SESSION_FILE_ENV] = str(run.root / "omh-session.json")
                    run.terminal.script(*steps(run))
                    self.run_main(run)
                    self.assert_clean_run(run, CLOSED_EXIT if launched_by_omh else 0)

    def test_a_gateway_exit_under_omh_still_returns_1(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers(), after=EXIT)
        )
        run.environ[SESSION_FILE_ENV] = str(run.root / "omh-session.json")
        self.run_main(run)
        self.assertEqual(run.code, 1)

    def test_ctrl_c_twice_while_idle_exits_0(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.script(
            Step(b"\x03", when=run.terminal.idle, label="idle"),
            Step(b"\x03", when=run.terminal.shows(EXIT_HINT), label="the exit hint"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame["method"] for frame in run.frames], STARTUP_METHODS)

    def test_ctrl_c_as_kitty_and_modify_other_keys_reports_exits_like_the_byte(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.script(
            Step(b"\x1b[99;5u", when=run.terminal.idle, label="idle"),
            Step(b"\x1b[27;5;99~", when=run.terminal.shows(EXIT_HINT), label="the exit hint"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame["method"] for frame in run.frames], STARTUP_METHODS)

    def test_mouse_reports_the_tui_did_not_ask_for_type_nothing(self) -> None:
        # A program that died with mouse tracking on leaves the terminal reporting clicks, motion and the wheel.
        reports = b"\x1b[<0;5;20M\x1b[<0;5;20m\x1b[<35;6;21M\x1b[<64;5;20M\x1b[<65;5;20M\x1b[M !!"
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.script(
            Step(reports, when=run.terminal.idle, capture="before", label="idle"),
            Step(b"\x04", when=run.terminal.idle, capture="after", label="the reports"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(composer_row(run.terminal.captures["after"]), composer_row(run.terminal.captures["before"]))
        self.assertEqual([frame["method"] for frame in run.frames], STARTUP_METHODS)

    def test_the_default_terminal_reads_the_environment_main_was_given(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
            env={"TERM_PROGRAM": "iTerm.app"},
        )
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        given: list[object] = []

        def build_terminal(*, environ: object) -> ScriptedTerminal:
            given.append(environ)
            return run.terminal

        with patch("omh.tui.app.Terminal", build_terminal):
            run.code = main(
                run.environ,
                stdin=TtyStream(),
                stdout=TtyStream(),
                stderr=run.stderr,
                make_client=self.make_client(run),
                make_poller=lambda omh_home, hermes_home: run.poller,
            )
        self.assert_clean_run(run)
        self.assertEqual(given, [run.environ])

    def test_a_new_stored_id_rewrites_the_session_file_and_repoints_the_poller(self) -> None:
        rotated = {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "type": "session.info",
                "session_id": LIVE_ID,
                "payload": {"model": "deepseek/deepseek-v4.1-flash-ultrafast", "stored_session_id": ROTATED_ID},
            },
        }
        foreign = {**rotated, "params": {**rotated["params"], "session_id": "someone-else"}}
        foreign["params"]["payload"] = {"stored_session_id": "20261013_999999_foreign"}
        played = spans("session", "startup", "create")
        position = sum(stop - start for start, stop in played)
        run = self.prepare(
            Scenario(
                "session",
                played,
                inject=((position, json.dumps(foreign)), (position, json.dumps(rotated))),
                answers=startup_answers(),
            )
        )
        run.terminal.script(Step(b"\x04", when=lambda: run.poller.sessions[-1:] == [ROTATED_ID], label="rotation"))
        self.run_main(run)
        self.assert_clean_run(run)
        # The event for another session id was dropped; only the live session's rotation counted.
        self.assertEqual(run.poller.sessions, [STORED_ID, ROTATED_ID])
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": ROTATED_ID})
        self.assertEqual(stat.S_IMODE(os.stat(run.active_session_file).st_mode), 0o600)

    def error_run(self, *, submits: int) -> Run:
        """A session whose prompt.submit is answered `streaming` and then ended by a bare `error` event.

        Hermes 6c61c3e27d does this when it cancels a turn before the agent is ready
        (`tui_gateway/methods_prompt.py`): no `message.start`, no `message.complete`.
        """
        submit = (5, 7)  # the recorded prompt.submit and its `streaming` answer
        played = (*spans("session", "startup", "create"), *([submit] * submits))
        position = sum(stop - start for start, stop in played[:3])
        error = {"jsonrpc": "2.0", "method": "event", "params": {
            "type": "error", "session_id": LIVE_ID, "payload": {"message": TURN_CANCELLED}}}
        return self.prepare(Scenario("session", played, inject=((position, json.dumps(error)),), answers=startup_answers()))

    def test_a_turn_ended_by_an_error_event_leaves_the_tui_idle_so_ctrl_c_twice_exits(self) -> None:
        run = self.error_run(submits=1)
        terminal = run.terminal
        terminal.script(
            self.submit(run, "first prompt"),
            Step(b"\x03", when=lambda: TURN_CANCELLED in terminal.history() and terminal.idle(), label="idle again"),
            Step(b"\x03", when=terminal.shows(EXIT_HINT), label="the exit hint"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(run.calls("session.interrupt"), [])

    def test_a_turn_ended_by_an_error_event_sends_the_next_queued_prompt(self) -> None:
        run = self.error_run(submits=2)
        terminal = run.terminal
        terminal.script(
            # One read: the second prompt queues behind the first, whose turn the error ends.
            Step(b"first prompt\rsecond prompt\r", when=terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: len(run.calls("prompt.submit")) == 2, label="the queued prompt sent"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        first, second = run.calls("prompt.submit")
        self.assertEqual(first["params"], {"session_id": LIVE_ID, "text": "first prompt"})
        self.assertEqual(second["params"], {"session_id": LIVE_ID, "text": "second prompt", "queued": True})
        history = terminal.history()
        self.assertLess(history.index(TURN_CANCELLED), history.index("❯ second prompt"))

    def test_a_refused_submit_sends_the_next_queued_prompt(self) -> None:
        answers = (
            *startup_answers(),
            ("prompt.submit", {"error": {"code": 4090, "message": "another process owns this session"}}),
            ("prompt.submit", {"result": {"status": "streaming"}}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            Step(b"first prompt\rsecond prompt\r", when=terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: len(run.calls("prompt.submit")) == 2, label="the queued prompt sent"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        first, second = run.calls("prompt.submit")
        self.assertEqual(second["params"], {"session_id": LIVE_ID, "text": "second prompt", "queued": True})
        self.assertIn("another process owns this session", terminal.history())

    def test_quit_closes_the_session_before_leaving(self) -> None:
        answers = (*startup_answers(), ("session.close", {"result": {"closed": True}}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        run.terminal.script(self.submit(run, "/quit"))
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame["params"] for frame in run.calls("session.close")], [{"session_id": LIVE_ID}])

    def test_exit_is_quit(self) -> None:
        answers = (*startup_answers(), ("session.close", {"result": {"closed": True}}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        run.terminal.script(self.submit(run, "/exit"))
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame["params"] for frame in run.calls("session.close")], [{"session_id": LIVE_ID}])

    def test_a_connection_request_is_named_once_per_operation(self) -> None:
        def event(kind: str, payload: dict) -> str:
            return json.dumps({"jsonrpc": "2.0", "method": "event",
                               "params": {"type": kind, "session_id": LIVE_ID, "payload": payload}})

        played = spans("session", "startup", "create")
        end = sum(stop - start for start, stop in played)
        request = {"op_id": "op-1", "seq": 1, "deadline_at": 0, "targets": [], "tool_call_id": None}
        run = self.prepare(Scenario("session", played, answers=startup_answers(), inject=(
            (end, event("connection.request", request)),
            (end, event("connection.request", {**request, "seq": 2})),
            (end, event("error", {"message": "marker after both requests"})),
        )))
        run.terminal.script(Step(b"\x04", when=run.terminal.shows("marker after both requests"), label="the marker"))
        self.run_main(run)
        self.assert_clean_run(run)
        history = run.terminal.history()
        self.assertEqual(history.count("waiting for an app connection"), 1, history)
        self.assertIn("hermes --tui", history)

    def test_a_gateway_exit_mid_session_returns_1_with_the_resume_line(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers(), after=EXIT)
        )
        self.run_main(run)
        self.assertEqual(run.terminal.stalled, "")
        self.assertEqual(run.code, 1)
        self.assertIn(f"hermes --tui --resume {STORED_ID}", run.stderr.getvalue())
        self.assertIn("exited", run.terminal.history())
        self.assertEqual((run.terminal.entered, run.terminal.exited), (1, 1))

    def test_a_resize_repaints_without_ghost_rows(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))

        def settled(rows: int, cols: int, redraws: int) -> Callable[[], bool]:
            def ready() -> bool:
                screen = run.terminal.screen
                cleared = sum(text.count(CLEAR_SCREEN_AND_SCROLLBACK) for text in run.terminal.writes)
                shown = any(line.startswith(BOX_MARK) for line in screen.lines())
                return (screen.rows, screen.cols) == (rows, cols) and cleared >= redraws and shown

            return ready

        run.terminal.script(
            Step(resize=(16, 60), when=run.terminal.idle, label="idle"),
            Step(resize=(30, 100), when=settled(16, 60, 1), capture="narrow", label="the 16x60 frame"),
            Step(b"\x04", when=settled(30, 100, 2), capture="wide", label="the 30x100 frame"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        for name, rows, cols in (("narrow", 16, 60), ("wide", 30, 100)):
            with self.subTest(size=name):
                screen = run.terminal.captures[name]
                self.assertEqual(len(screen), rows)
                drawn = [line for line in screen if line]
                self.assertEqual(sum(line.startswith(BOX_MARK) for line in screen), 2, screen)  # one frame: its rules
                self.assertEqual(sum(line.startswith(RULE_MARK) for line in screen), 2, screen)
                # The redrawn session (the banner, and at 100 columns the logo above it, since the whole session
                # fits the redraw) and the region (the launch card, refitted, then top edge, composer, bottom edge,
                # info line), nothing else: one card, its boxes all closed.
                logo = LOGO[:-1] if cols >= 100 else []
                card = [line for line in drawn if line[:1] in ("╭", "│", "╰")]
                self.assertEqual(sum(line.startswith("╭─ session") for line in screen), 1 if card else 0, screen)
                self.assertEqual(sum(line.count("╭") for line in card), sum(line.count("╰") for line in card), screen)
                self.assertEqual(drawn[: len(logo)], logo, screen)
                self.assertEqual(len(drawn), 5 + len(logo) + len(card), screen)
                self.assertTrue(drawn[len(logo)].startswith("⚚ OH-MY-HERMES"), screen)
                self.assertTrue(all(len(line) <= cols for line in screen))


    def test_a_settled_resize_redraws_the_session_once_with_no_old_frame_in_scrollback(self) -> None:
        # A real terminal reflows its rows on a width change, so the region cannot repaint in
        # place; after the size settles the TUI erases screen and scrollback and prints the
        # session again at the new width.
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
            cols=100,
            env={"HOME": "/fixture"},
        )

        def settled(rows: int, cols: int, redraws: int) -> Callable[[], bool]:
            def ready() -> bool:
                screen = run.terminal.screen
                cleared = sum(text.count(CLEAR_SCREEN_AND_SCROLLBACK) for text in run.terminal.writes)
                shown = any(line.startswith(BOX_MARK) for line in screen.lines())
                return (screen.rows, screen.cols) == (rows, cols) and cleared >= redraws and shown

            return ready

        run.terminal.script(
            Step(resize=(20, 70), when=run.terminal.idle, label="idle"),
            Step(resize=(20, 60), when=settled(20, 70, 1), label="the 20x70 frame"),
            Step(b"\x04", when=settled(20, 60, 2), capture="final", label="the 20x60 frame"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        screen = run.terminal.captures["final"]
        everything = run.terminal.screen.scrollback + screen
        self.assertEqual(sum(line.startswith(BOX_MARK) for line in everything), 2, everything)  # one frame: its rules
        self.assertEqual(sum(line.startswith("╭─ session") for line in everything), 1, everything)  # one launch card
        self.assertEqual(sum(line.startswith("⚚ OH-MY-HERMES") for line in everything), 1, everything)
        self.assertTrue(screen[0].startswith("⚚ OH-MY-HERMES"), screen[:2])
        self.assertTrue(all(len(line) <= 60 for line in everything))

    def test_a_session_without_subagents_never_turns_on_mouse_reporting_so_drag_selection_stays_native(self) -> None:
        # With agents to click it does, for as long as they are clickable: `test_tui_agent_mouse`.
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        self.run_main(run)
        self.assert_clean_run(run)
        written = "".join(run.terminal.writes)
        for mode in ("?1000h", "?1002h", "?1003h", "?1006h", "?1015h"):
            with self.subTest(mode=mode):
                self.assertNotIn("\x1b[" + mode, written)

@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class PromptSlotTests(AppTestCase):
    def approval_run(self) -> Run:
        return self.prepare(
            Scenario("approval", spans("approval", "startup", "create", "approval_turn"),
                     answers=(*startup_answers(), INTERRUPTED))
        )

    def assert_denied(self, run: Run) -> None:
        """The recorded deny went, then the interrupt that stops the turn (the replay plays the recorded rest anyway)."""
        self.assert_clean_run(run)
        frames = run.frames
        answers = [frame for frame in frames if frame.get("id") == "srq-52e9720342b6"]
        self.assertEqual(answers, [{"jsonrpc": "2.0", "id": "srq-52e9720342b6", "result": {"choice": "deny"}}])
        (interrupt,) = run.calls("session.interrupt")
        self.assertLess(frames.index(answers[0]), frames.index(interrupt))
        self.assertIn("It was blocked", run.terminal.history())

    def armed(self, run: Run, label: str) -> Callable[[], bool]:
        """Ready once the slot that step `label` saw has been open past the arm delay."""
        return lambda: time.monotonic() - run.terminal.fired[label] > SLOT_ARM_SECONDS + 0.05

    def test_an_approval_opens_a_slot_and_d_sends_the_explicit_deny(self) -> None:
        run = self.approval_run()
        run.terminal.script(
            self.submit(run, "Run rm -rf ./omh-m0-probe-dir"),
            Step(when=run.terminal.shows("Hermes asks to run"), capture="slot", label="the approval slot"),
            Step(b"d", when=self.armed(run, "the approval slot"), label="armed"),
            Step(b"\x04", when=lambda: "proceed." in run.terminal.history() and run.terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_denied(run)
        slot = "\n".join(run.terminal.captures["slot"])
        self.assertIn("rm -rf ./omh-m0-probe-dir", slot)
        self.assertIn("waiting on you", slot)
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": APPROVAL_STORED_ID})

    def test_esc_on_an_approval_sends_the_explicit_deny(self) -> None:
        run = self.approval_run()
        run.terminal.script(
            self.submit(run, "Run rm -rf ./omh-m0-probe-dir"),
            Step(when=run.terminal.shows("Hermes asks to run"), label="the approval slot"),
            Step(b"\x1b", when=self.armed(run, "the approval slot"), label="armed"),
            Step(b"\x04", when=lambda: "proceed." in run.terminal.history() and run.terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_denied(run)

    def test_up_then_enter_on_an_armed_approval_still_denies(self) -> None:
        # Up then Enter is the composer's recall-and-resend. On an approval Up moves nothing,
        # so the Enter answers the default deny; the replay accepts only the deny.
        run = self.approval_run()
        run.terminal.script(
            self.submit(run, "Run rm -rf ./omh-m0-probe-dir"),
            Step(when=run.terminal.shows("Hermes asks to run"), label="the approval slot"),
            Step(b"\x1b[A\r", when=self.armed(run, "the approval slot"), label="armed"),
            Step(b"\x04", when=lambda: "proceed." in run.terminal.history() and run.terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_denied(run)

    def test_keys_that_arrive_as_an_approval_opens_are_ignored(self) -> None:
        # Right, Enter would allow once. Typed for the composer as the request lands, they
        # reach the slot inside the arm delay and do nothing; the replay accepts only the deny.
        run = self.approval_run()
        terminal = run.terminal
        now = [100.0]
        client = self.make_client(run)(gateway_spawn(run.environ))
        client.start(ready_timeout=10.0)
        app = App(terminal, client, run.environ, poller=run.poller, clock=lambda: now[0])
        app.startup()
        terminal.script(
            self.submit(run, "Run rm -rf ./omh-m0-probe-dir"),
            Step(b"\x1b[C\r", when=terminal.shows("Hermes asks to run"), label="the approval slot"),
            Step(when=lambda: not now.__setitem__(0, 100.0 + SLOT_ARM_SECONDS / 2), label="half the delay"),
            Step(b"\r", when=terminal.shows("Hermes asks to run"), label="still arming"),
            Step(when=lambda: not now.__setitem__(0, 100.0 + SLOT_ARM_SECONDS), label="the delay passed"),
            Step(b"d", when=terminal.shows("Hermes asks to run"), label="armed"),
            Step(b"\x04", when=lambda: "proceed." in terminal.history() and terminal.idle(), label="end"),
        )
        with terminal:
            run.code = app.run()
        self.assert_denied(run)

    def test_a_resumed_sessions_open_request_is_redelivered_as_a_slot(self) -> None:
        # The recorded approval request, handed back by session.resume as an open request; the
        # replay then expects the recorded deny for it and plays the rest of the recorded turn.
        request = load_fixture("approval")[1][20]["frame"]
        resumed = {
            "result": {
                "session_id": "f05e2691",
                "stored_session_id": APPROVAL_STORED_ID,
                "message_count": 1,
                "messages": [],
                "info": {"model": "deepseek/deepseek-v4.1-flash-ultrafast"},
                "running": True,
                "open_requests": [{"id": request["id"], "method": request["method"], "params": request["params"]}],
            }
        }
        startup = spans("approval", "startup")
        run = self.prepare(
            Scenario("approval", (*startup, (21, 47)), answers=(*startup_answers(), ("session.resume", resumed), INTERRUPTED)),
            env={"HERMES_TUI_RESUME": APPROVAL_STORED_ID},
        )
        run.terminal.script(
            Step(when=run.terminal.shows("Hermes asks to run"), label="the re-delivered approval"),
            Step(b"d", when=self.armed(run, "the re-delivered approval"), label="armed"),
            Step(b"\x04", when=lambda: "proceed." in run.terminal.history() and run.terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_denied(run)
        (resume,) = run.calls("session.resume")
        self.assertEqual(resume["params"], {"session_id": APPROVAL_STORED_ID, "cols": 80})
        self.assertEqual(run.calls("session.create"), [])
        self.assertTrue(run.terminal.history().startswith(f"⚚ OH-MY-HERMES v{__version__} · resumed {APPROVAL_STORED_ID}"))
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": APPROVAL_STORED_ID})

    def assert_withdrawal_closes_the_slot(self, kind: str, payload: dict, envelope: str = "f05e2691") -> None:
        played = (*spans("approval", "startup", "create"), (5, 21))  # the turn up to the approval request
        withdrawal = {"jsonrpc": "2.0", "method": "event", "params": {"type": kind, "session_id": envelope, "payload": payload}}
        position = sum(stop - start for start, stop in played)
        run = self.prepare(
            Scenario("approval", played, inject=((position, json.dumps(withdrawal)),), answers=startup_answers())
        )
        run.terminal.script(
            self.submit(run, "Run rm -rf ./omh-m0-probe-dir"),
            Step(b"\x04", when=run.terminal.shows("· rm -rf ./omh-m0-probe-dir"), label="the withdrawal row"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame for frame in run.frames if frame.get("id") == "srq-52e9720342b6"], [])
        self.assertNotIn("Hermes asks to run", "\n".join(run.terminal.screen.lines()))

    def test_request_cancel_closes_the_slot_without_answering(self) -> None:
        self.assert_withdrawal_closes_the_slot(
            "request.cancel", {"id": "srq-52e9720342b6", "method": "approval", "reason": "timeout"}
        )

    def test_a_withdrawal_closes_the_slot_whatever_session_its_envelope_names(self) -> None:
        # A request from a session being left (a switch, /new) is withdrawn under that session's id.
        self.assert_withdrawal_closes_the_slot(
            "request.cancel", {"id": "srq-52e9720342b6", "method": "approval", "reason": "session_closed"},
            envelope="a-session-being-left",
        )

    def test_approval_cancelled_closes_the_slot_by_its_approval_id(self) -> None:
        self.assert_withdrawal_closes_the_slot(
            "approval.cancelled",
            {
                "session_id": "f05e2691",
                "stored_session_id": APPROVAL_STORED_ID,
                "reason": "interrupt",
                "cancelled_count": 1,
                "request_ids": ["421ace443ef640baa09f80731226646e"],
            },
        )

    def test_a_clarify_choice_is_picked_by_its_number(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "clarify_turn"), answers=startup_answers())
        )
        run.terminal.script(
            self.submit(run, "Ask me red or blue."),
            Step(when=run.terminal.shows("Which color do you prefer?"), label="the clarify slot"),
            Step(b"2", when=self.armed(run, "the clarify slot"), label="armed"),
            Step(b"\x04", when=run.terminal.idle, label="the end of the turn"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        answers = [frame for frame in run.frames if frame.get("id") == "srq-c7e7e10e23ab"]
        self.assertEqual(answers, [{"jsonrpc": "2.0", "id": "srq-c7e7e10e23ab", "result": {"answers": {"q0": "blue"}}}])

    def test_keys_and_an_enter_that_arrive_as_a_clarify_opens_answer_nothing(self) -> None:
        # Enter would pick the highlighted `red`, and so would `1`. Typed for the composer as the
        # question lands, they reach it inside the arm delay and do nothing; the replay records `blue`.
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "clarify_turn"), answers=startup_answers())
        )
        terminal = run.terminal
        now = [100.0]
        client = self.make_client(run)(gateway_spawn(run.environ))
        client.start(ready_timeout=10.0)
        app = App(terminal, client, run.environ, poller=run.poller, clock=lambda: now[0])
        app.startup()
        question = terminal.shows("Which color do you prefer?")
        terminal.script(
            self.submit(run, "Ask me red or blue."),
            Step(b"\r", when=question, label="the clarify slot"),
            Step(when=lambda: not now.__setitem__(0, 100.0 + SLOT_ARM_SECONDS / 2), label="half the delay"),
            Step(b"1", when=question, label="still arming"),
            Step(when=lambda: not now.__setitem__(0, 100.0 + SLOT_ARM_SECONDS), label="the delay passed"),
            Step(b"2", when=question, label="armed"),
            Step(b"\x04", when=terminal.idle, label="the end of the turn"),
        )
        with terminal:
            run.code = app.run()
        self.assert_clean_run(run)
        answers = [frame for frame in run.frames if frame.get("id") == "srq-c7e7e10e23ab"]
        self.assertEqual(answers, [{"jsonrpc": "2.0", "id": "srq-c7e7e10e23ab", "result": {"answers": {"q0": "blue"}}}])

    def test_a_typed_clarify_answer_never_enters_the_input_history(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "clarify_turn"), answers=startup_answers())
        )
        terminal = run.terminal
        terminal.script(
            self.submit(run, "Ask me red or blue."),
            Step(when=terminal.shows("Which color do you prefer?"), label="the clarify slot"),
            Step(b"blue\r", when=self.armed(run, "the clarify slot"), label="armed"),
            Step(b"\x1b[A", when=lambda: terminal.idle() and not terminal.shows("1. red")(), label="idle"),
            Step(b"\x03\x04", when=lambda: composer_row(terminal.screen.lines()) == "❯ Ask me red or blue.",
                 label="the recalled prompt"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        answers = [frame for frame in run.frames if frame.get("id") == "srq-c7e7e10e23ab"]
        self.assertEqual(answers, [{"jsonrpc": "2.0", "id": "srq-c7e7e10e23ab", "result": {"answers": {"q0": "blue"}}}])


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class SlashCommandTests(AppTestCase):
    def test_a_hermes_only_command_shows_its_door_and_sends_nothing(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.script(
            self.submit(run, "/voice"),
            Step(b"\x04", when=run.terminal.shows("hermes --tui"), label="the hermes notice"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertIn("/voice runs in Hermes' own terminal", run.terminal.history())
        self.assertEqual([frame["method"] for frame in run.frames], STARTUP_METHODS)

    def test_an_unknown_command_goes_to_slash_exec_then_command_dispatch_on_4018(self) -> None:
        answers = (
            *startup_answers(),
            ("slash.exec", {"error": {"code": 4018, "message": "not a slash.exec command"}}),
            ("command.dispatch", {"result": {"type": "exec", "output": "xyz ran through command.dispatch"}}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        run.terminal.script(
            self.submit(run, "/xyz"),
            Step(b"\x04", when=run.terminal.shows("xyz ran through"), label="the dispatch output"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (slash,) = run.calls("slash.exec")
        self.assertEqual(slash["params"], {"command": "xyz", "session_id": LIVE_ID})
        (dispatch,) = run.calls("command.dispatch")
        self.assertEqual(dispatch["params"], {"name": "xyz", "arg": "", "session_id": LIVE_ID})

    def test_a_drift_reply_mid_session_ends_it_with_the_line_that_reopens_it_in_hermes(self) -> None:
        # 4000 (a key this Hermes does not know) or -32601 (a method it does not have) during a
        # session means the gateway no longer speaks the declared contract: leave, name hermes.
        for code, message in ((4000, "extra fields not permitted"), (-32601, "unknown method: slash.exec")):
            with self.subTest(code=code):
                answers = (*startup_answers(), ("slash.exec", {"error": {"code": code, "message": message}}))
                run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
                run.terminal.script(self.submit(run, "/xyz"))
                self.run_main(run)
                self.assertEqual(run.terminal.stalled, "")
                self.assertEqual(run.code, 1)
                self.assertIn(f"hermes --tui --resume {STORED_ID}", run.stderr.getvalue())
                self.assertEqual(run.calls("command.dispatch"), [])
                self.assertEqual((run.terminal.entered, run.terminal.exited), (1, 1))

    def test_under_omh_a_drift_reply_ends_the_session_naming_omh_resume(self) -> None:
        answers = (*startup_answers(), ("slash.exec", {"error": {"code": 4000, "message": "extra fields not permitted"}}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        run.environ[SESSION_FILE_ENV] = str(run.root / "omh-session.json")
        run.terminal.script(self.submit(run, "/xyz"))
        self.run_main(run)
        self.assertEqual(run.code, 1)
        self.assertIn(f"Resume the session: omh --resume {STORED_ID}", run.stderr.getvalue())
        self.assertNotIn("hermes --tui", run.stderr.getvalue())

    def test_tab_completes_a_local_command_and_history_pages_on_the_alternate_screen(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers())
        )
        terminal = run.terminal
        run.terminal.script(
            self.submit(run, "Reply with exactly the word: ok"),
            Step(b"/hist", when=lambda: "later." in terminal.history() and terminal.idle(), label="reply"),
            Step(b"\t", when=terminal.shows("/history"), capture="menu", label="the completion menu"),
            Step(b"\r", when=terminal.shows("❯ /history"), label="the completed command"),
            Step(b"q", when=lambda: terminal.screen.alternate, capture="pager", label="the pager"),
            Step(b"\x04", when=lambda: not terminal.screen.alternate and terminal.idle(), capture="back", label="back"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertTrue(any("Page through this session's transcript" in line for line in terminal.captures["menu"]))
        pager = "\n".join(terminal.captures["pager"])
        self.assertIn("I'm Hermes, your agent", pager)
        self.assertIn("history · ", pager)
        back = "\n".join(terminal.captures["back"])
        self.assertIn(BOX_MARK, back)
        self.assertNotIn("history · ", back)
        self.assertEqual(run.calls("slash.exec"), [])

    def test_omh_model_reads_the_picker_keys_from_the_raw_terminal_and_ctrl_c_cancels(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        terminal = run.terminal
        keys: list[str] = []

        def picker(environ: object, theme: object, *, read_key, write, width: int) -> str:
            write("picker frame\nsecond row\n")
            while not keys or keys[-1] not in ("quit", "enter"):
                keys.append(read_key())
            return "Cancelled; the model chains were not changed."

        client = self.make_client(run)(gateway_spawn(run.environ))
        client.start(ready_timeout=10.0)
        app = App(terminal, client, run.environ, poller=run.poller, pick_model_chains=picker)
        app.startup()
        terminal.script(
            self.submit(run, "/omh-model"),
            Step(b"\x1b[Bj\x03", when=terminal.shows("second row"), label="the picker frame"),
            Step(b"\x04", when=terminal.shows("Cancelled; the model chains"), label="the picker result"),
        )
        with terminal:
            run.code = app.run()
        self.assert_clean_run(run)
        # Ctrl+C reached the picker as a key (raw mode keeps it from being a signal).
        self.assertEqual(keys, ["down", "down", "quit"])
        # The terminal stayed in the TUI's raw mode: never handed back and re-entered.
        self.assertEqual((terminal.entered, terminal.exited), (1, 1))
        self.assertIn("picker frame\r\nsecond row\r\n", "".join(terminal.writes))
        # Drawn on the alternate screen: nothing of the picker is left on the main screen or in scrollback.
        self.assertIn("\x1b[?1049h", "".join(terminal.writes))
        self.assertNotIn("picker frame", "\n".join(terminal.screen.scrollback + terminal.screen.lines()))


class InfoLineRightTests(unittest.TestCase):
    """The info line's right side: the model, the context and the effort, no brand and no state words."""

    MODEL = "deepseek/deepseek-v4.1-flash-ultrafast"

    def app(self, cols: int = 100) -> App:
        app = App(ScriptedTerminal(rows=24, cols=cols), None, {}, poller=FakePoller())  # type: ignore[arg-type]
        app.model, app.context_percent, app.effort = self.MODEL, 5.0, "high"
        return app

    def right(self, app: App, width: int) -> str:
        row = without_badge(line_text(app._info_line(width)))
        self.assertLessEqual(line_width(app._info_line(width)), width)
        return row.strip()

    def test_the_right_side_is_model_context_and_effort_with_no_brand_and_no_state(self) -> None:
        app = self.app()
        row = without_badge(line_text(app._info_line(100)))  # the badge is the left side's, at its end
        self.assertTrue(row.endswith(f"{self.MODEL} · ctx 5% · effort high"), row)
        self.assertEqual(line_width(app._info_line(100)), 100)  # the right side ends on the last cell
        for gone in ("⚚", "OMH", "idle", "running", "│"):
            self.assertNotIn(gone, row)

    def test_the_model_shortens_first_then_goes_then_the_effort_then_the_context(self) -> None:
        # The inset, the badge and the 3-cell gap take 19 cells; the right side takes the longest form that fits
        # beside, and goes whole before the badge shortens.
        app = self.app()
        expected = {
            80: f"{self.MODEL} · ctx 5% · effort high",
            79: "deepseek-v4.1-flash-ultrafast · ctx 5% · effort high",
            71: "deepseek-v4.1-flash-ultrafast · ctx 5% · effort high",
            70: "v4.1-flash-ultrafast · ctx 5% · effort high",
            62: "v4.1-flash-ultrafast · ctx 5% · effort high",
            61: "ctx 5% · effort high",
            39: "ctx 5% · effort high",
            38: "ctx 5%",
            25: "ctx 5%",
            24: "",
        }
        self.assertEqual({width: self.right(app, width) for width in expected}, expected)

    def test_a_model_has_up_to_three_names_longest_first(self) -> None:
        from omh.tui.modes import model_forms

        self.assertEqual(model_forms(self.MODEL), (self.MODEL, "deepseek-v4.1-flash-ultrafast", "v4.1-flash-ultrafast"))
        self.assertEqual(model_forms("claude-opus-5-5"), ("claude-opus-5-5", "opus-5-5"))
        self.assertEqual(model_forms("openrouter/gpt5"), ("openrouter/gpt5", "gpt5"))
        self.assertEqual(model_forms("gpt5"), ("gpt5",))
        self.assertEqual(model_forms("vendor/model-"), ("vendor/model-", "model-"))  # no word after the dash
        self.assertEqual(model_forms("vendor/-x"), ("vendor/-x", "-x"))  # no word before it
        self.assertEqual(model_forms(""), ())

    def test_no_name_of_a_shipped_model_is_a_bare_version(self) -> None:
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
        from omh.tui.modes import model_forms

        chains = SHIPPED_MODEL_RECOMMENDATIONS["categories"].values()
        for alias in sorted({entry["model_alias"] for chain in chains for entry in chain}):
            for model in (alias, f"vendor/{alias}"):
                with self.subTest(model=model):
                    self.assertFalse([form for form in model_forms(model) if form[:1].isdigit()])
        self.assertEqual(model_forms("z-ai/glm-5.3"), ("z-ai/glm-5.3", "glm-5.3"))
        self.assertEqual(model_forms("gemini-4-argon"), ("gemini-4-argon",))
        self.assertEqual(model_forms("openai/gpt-5.5"), ("openai/gpt-5.5", "gpt-5.5"))
        self.assertEqual(model_forms("kimi-k3"), ("kimi-k3", "k3"))  # a word that starts with a letter stays

    def test_the_effort_says_its_level_or_names_the_key_while_hermes_reported_none(self) -> None:
        app = self.app()
        for effort, said in (("", "ctrl+t effort"), ("default", "effort default"), ("xhigh", "effort xhigh")):
            with self.subTest(effort=effort):
                app.effort = effort
                self.assertTrue(line_text(app._info_line(100)).endswith(f"ctx 5% · {said}"))

    def test_the_context_turns_warn_then_error_as_it_fills(self) -> None:
        app = self.app()
        theme = app.theme
        for percent, style in ((None, theme.muted), (79.9, theme.muted), (80, theme.warn),
                               (94.9, theme.warn), (95, theme.error), (100, theme.error)):
            with self.subTest(percent=percent):
                app._take_usage({"context_used": 1, "context_max": 2, "context_percent": percent}
                                if percent is not None else {"context_used": 1, "context_max": 1_000_000})
                span = next(span for span in app._info_line(100) if span.text.startswith("ctx"))
                self.assertEqual(span.style, style)

    def test_a_usage_block_without_context_figures_leaves_the_shown_context(self) -> None:
        app = self.app()
        app._take_usage({"context_used": 50_000, "context_max": 200_000})
        self.assertEqual(app.context_percent, 25.0)  # no percent in it: used over max
        for usage in ({"output": 12}, {"context_used": 1, "context_max": 0}, {"context_max": 10}, None):
            with self.subTest(usage=usage):
                app._take_usage(usage)
                self.assertEqual(app.context_percent, 25.0)

    def test_the_huds_chips_stand_first_on_the_right_and_go_last(self) -> None:
        from test_tui_panels import hud_payload

        from omh.tui.panels import HudSnapshot

        app = self.app(cols=160)
        payload = hud_payload()
        payload["repeat"] = {"status": "observed", "consecutive": 4, "period": 2, "intercepted": 1, "stage": "approval"}
        payload["activity"].update(live=True, post_tool_call_observed=True, open_call_count=2, oldest_open_elapsed_seconds=12)
        app.hud = HudSnapshot(app.stored_id, payload, 0.0)
        idle = line_text(app._info_line(160))
        self.assertTrue(idle.endswith(f"repeat x4 cycle-of-2 approval · {self.MODEL} · ctx 5% · effort high"), idle)
        self.assertNotIn("tool", idle)  # the calls in flight only while a turn runs
        app.turn_pending = True
        running = line_text(app._info_line(160))
        self.assertTrue(running.endswith(f"repeat x4 cycle-of-2 approval · 2 tools · 12s · {self.MODEL} · ctx 5% · effort high"),
                        running)
        app.turn_pending = False
        self.assertEqual(self.right(app, 55), "repeat x4 cycle-of-2 approval")


class InfoLineLeftTests(unittest.TestCase):
    def row(self, width: int = 80, **facts: object) -> str:
        defaults: dict[str, object] = {"mode": "normal"}
        return line_text(info_line(**{**defaults, **facts}, width=width, theme=DEFAULT_THEME))  # type: ignore[arg-type]

    def test_normal_mode_says_nothing_of_its_own(self) -> None:
        # Between turns the launch card names `?`, which still opens the list; during a turn the working row offers
        # the interrupt and the queue's own row the send-now key.
        self.assertEqual(self.row(), "")

    def test_accept_and_plan_say_so_in_their_own_colour(self) -> None:
        accept = info_line(mode="accept", width=80, theme=DEFAULT_THEME)
        self.assertEqual(line_text(accept), "⏵⏵ accept all on (⇧⇥ to cycle)")
        self.assertEqual(accept[0].style, replace(DEFAULT_THEME.mode_accept, bold=True))
        plan = info_line(mode="plan", width=80, theme=DEFAULT_THEME)
        self.assertEqual(line_text(plan), "⏸ plan mode on (⇧⇥ to cycle)")
        self.assertEqual(plan[0].style, replace(DEFAULT_THEME.mode_plan, bold=True))
        hermes_own = info_line(mode="accept", width=80,
                               theme=DEFAULT_THEME, cycle="plan")
        self.assertEqual(line_text(hermes_own), "⏵⏵ accept all on (⇧⇥ plan)")
        both = info_line(mode="accept+plan", width=80,
                         theme=DEFAULT_THEME, cycle="plan off")
        self.assertEqual(line_text(both), "⏵⏵ accept all on · ⏸ plan mode on (⇧⇥ plan off)")

    def test_the_right_side_goes_before_the_left_side_shortens(self) -> None:
        right = ((Span("a-model · effort high", DEFAULT_THEME.muted),),)
        whole = len("⏵⏵ accept all on (⇧⇥ to cycle)") + 3 + len("a-model · effort high")
        self.assertTrue(self.row(whole, mode="accept", right=right).endswith("   a-model · effort high"))
        self.assertEqual(self.row(whole - 1, mode="accept", right=right), "⏵⏵ accept all on (⇧⇥ to cycle)")
        say = ("↑↓ pick · enter confirms · d or esc denies and stops", "↑↓ · enter · d/esc")
        self.assertEqual(self.row(60, say=say, right=right), "↑↓ pick · enter confirms · d or esc denies and stops")
        self.assertEqual(self.row(30, say=say, right=right), "↑↓ · enter · d/esc")

    def test_the_hint_is_cut_from_its_end_and_the_label_survives(self) -> None:
        right = ((Span("ctrl+t effort", DEFAULT_THEME.muted),),)
        for width in range(18, 110):
            with self.subTest(width=width):
                row = self.row(width, mode="accept", right=right)
                self.assertTrue(row.startswith("⏵⏵ accept all on"), row)
                self.assertLessEqual(len(row), width)
                if "effort" in row:
                    self.assertTrue(row.endswith("ctrl+t effort"), row)
        # Too narrow for where Shift+Tab goes: the label stays whole, and alone.
        self.assertEqual(self.row(20, mode="accept"), "⏵⏵ accept all on")
        self.assertEqual(self.row(20, mode="plan"), "⏸ plan mode on")

    def test_a_label_too_wide_for_the_line_takes_its_short_words_then_its_glyph(self) -> None:
        # With nothing said, the label itself is what shortens before anything is cut.
        self.assertEqual(self.row(34, mode="accept+plan", cycle="plan off"), "⏵⏵ accept all on · ⏸ plan mode on")
        for width in (30, 24, 18):
            with self.subTest(width=width):
                self.assertEqual(self.row(width, mode="accept+plan", cycle="plan off"), "⏵⏵ accept · ⏸ plan")
        self.assertEqual(self.row(10, mode="accept+plan"), "⏵⏵ · ⏸")
        self.assertEqual(self.row(10, mode="accept"), "⏵⏵ accept")
        self.assertEqual(self.row(4, mode="plan"), "⏸")
        self.assertEqual(self.row(3, mode="accept+plan"), "⏵⏵…")  # under the glyphs it is cut


class LeaveSessionDeclineTests(unittest.TestCase):
    def test_every_request_of_the_session_being_left_is_declined_and_counted(self) -> None:
        from types import SimpleNamespace

        sent: list[tuple[str, dict]] = []
        client = SimpleNamespace(respond=lambda request_id, frame: sent.append((request_id, frame)))
        app = App(ScriptedTerminal(), client, {}, poller=FakePoller())  # type: ignore[arg-type]
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        app._on_server_request(ServerRequest("srq-2", "vault.unlock_prompt", {}))  # never shown: declined as it came
        self.assertEqual([request_id for request_id, _ in sent], ["srq-2"])
        app._on_server_request(ServerRequest("srq-3", "sudo", {"command": "apt install x"}))
        self.assertEqual(app._decline_all_requests(), 2)
        self.assertEqual(sorted(request_id for request_id, _ in sent), ["srq-1", "srq-2", "srq-3"])
        self.assertIn(("srq-1", {"result": {"choice": "deny"}}), sent)
        self.assertIsNone(app.slot)
        self.assertFalse(app.waiting_requests)


class SlotArmingTests(unittest.TestCase):
    """Every slot, not only an approval, ignores its keys and the composer's Enter while it arms."""

    def open_slot(self, method: str, params: dict) -> tuple[App, list[float], list[tuple[str, dict]]]:
        from types import SimpleNamespace

        now = [100.0]
        sent: list[tuple[str, dict]] = []
        client = SimpleNamespace(respond=lambda request_id, frame: sent.append((request_id, frame)))
        app = App(ScriptedTerminal(), client, {}, poller=FakePoller(), clock=lambda: now[0])  # type: ignore[arg-type]
        app._on_server_request(ServerRequest("srq-1", method, params))
        return app, now, sent

    def test_an_enter_inside_the_delay_sends_no_value(self) -> None:
        for method, params in (("sudo", {"command": "apt install x"}), ("secret", {"env_var": "TOKEN_X"}),
                               ("vault.code", {})):
            with self.subTest(method=method):
                app, now, sent = self.open_slot(method, params)
                app._on_input(Key(ENTER))
                self.assertEqual(sent, [])
                self.assertIsNotNone(app.slot)
                now[0] += SLOT_ARM_SECONDS
                app._on_input(Key(ENTER))
                self.assertEqual(sent, [("srq-1", {"result": {"value": ""}})])

    def test_a_clarify_ignores_digits_escape_and_enter_inside_the_delay(self) -> None:
        params = {"questions": [{"qid": "q0", "question": "Which?", "choices": ["red", "blue"]}]}
        app, now, sent = self.open_slot("clarify", params)
        for key in (Key(CHAR, "1"), Key(ESCAPE), Key(DOWN), Key(ENTER)):
            app._on_input(key)
        self.assertEqual(sent, [])
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(CHAR, "2"))
        self.assertEqual(sent, [("srq-1", {"result": {"answers": {"q0": "blue"}}})])



class ShellLineTests(unittest.TestCase):
    def test_a_line_printed_after_the_terminal_is_restored_carries_no_escape_sequence(self) -> None:
        import io

        from omh.tui.app import _say

        stream = io.StringIO()
        _say(stream, "gateway said: \x1b[31mboom\x1b[0m \x1b]8;;http://x\x07link\x1b]8;;\x07")
        self.assertEqual(stream.getvalue(), "gateway said: boom link\n")

class StickyPromptTests(unittest.TestCase):
    """The sent prompt is echoed above the composer only once it has scrolled off the screen."""

    def app(self, flushed: int, busy: bool = True) -> App:
        app = App(ScriptedTerminal(rows=20, cols=60), None, {}, poller=FakePoller())  # type: ignore[arg-type]
        app.sticky = "what changed in the build?"
        app.turn_pending = busy
        app.flushed_since_prompt = flushed
        return app

    def test_no_echo_while_the_prompt_is_still_on_screen(self) -> None:
        self.assertFalse(self.app(flushed=12)._sticky_needed(12))  # 12 transcript rows above the region

    def test_the_echo_appears_once_the_prompt_has_scrolled_off(self) -> None:
        self.assertTrue(self.app(flushed=13)._sticky_needed(12))

    def test_no_echo_when_no_turn_is_running(self) -> None:
        self.assertFalse(self.app(flushed=99, busy=False)._sticky_needed(12))

class ModelChainPickerTests(unittest.TestCase):
    def test_tui_keys_map_to_picker_tokens_and_ctrl_c_ctrl_d_esc_cancel(self) -> None:
        cases = {
            Key(UP): "up", Key(DOWN): "down", Key(LEFT): "left", Key(RIGHT): "right", Key(ENTER): "enter",
            Key(ESCAPE): "quit", Key(CHAR, "c", ctrl=True): "quit", Key(CHAR, "d", ctrl=True): "quit",
            Key(CHAR, "j"): "down", Key(CHAR, "+"): "plus", Key(CHAR, "d"): "default", Key(CHAR, "q"): "quit",
            Key(CHAR, "x"): "", Key(CHAR, "v", ctrl=True): "", Key(LEFT, alt=True): "", Paste("q"): "",
            Mouse("left", 1, 1): "",
        }
        for event, token in cases.items():
            with self.subTest(event=event):
                self.assertEqual(picker_key(event), token)

    def test_a_cancelled_picker_writes_its_frame_through_the_seam_and_saves_nothing(self) -> None:
        root = Path(self.enterContext(make_test_tempdir("omh-tui-picker-")))
        environ = {"OMH_HOME": str(root / "omh"), "HERMES_HOME": str(root / "hermes"), "NO_COLOR": "1"}
        keys = iter(["down", "right", "quit"])
        written: list[str] = []
        message = run_model_chain_picker(
            environ, DEFAULT_THEME, read_key=lambda: next(keys), write=written.append, width=100
        )
        self.assertTrue(message.startswith("Cancelled;"), message)
        self.assertIn("Model chains", written[0])
        self.assertEqual(list(root.iterdir()), [])


FRESH_LIVE_ID = "fresh01"
FRESH_STORED_ID = "20261013_140000_fresh"


def turn_rows(fixture: str, index: int) -> dict:
    return load_fixture(fixture)[1][index]["frame"]


def busy_mode_answers(mode: str) -> tuple[tuple[str, dict], ...]:
    return (
        ("config.get", {"result": {"config": {"display": {"busy_input_mode": mode}}}}),
        ("commands.catalog", recorded_answer("session", "commands_catalog")),
        ("session.list", recorded_answer("session", "session_list")),
        UNREAD_DEFAULT,
    )


class InitialThemeTests(unittest.TestCase):
    def test_an_omh_skin_name_picks_that_theme_and_anything_else_is_sky(self) -> None:
        cases = {
            "omh-amber": "amber",
            "omh-crimson": "crimson",
            "omh": "sky",
            "default": "sky",  # Hermes' own default skin
            "amber": "sky",  # a foreign skin that only shares a short name
            "": "sky",
        }
        for skin, theme in cases.items():
            with self.subTest(skin=skin):
                self.assertEqual(initial_theme({"skin": {"name": skin}}).name, theme)
        self.assertEqual(initial_theme({}).name, "sky")

    def test_the_theme_saved_under_the_omh_home_wins_over_the_hermes_skin(self) -> None:
        with make_test_tempdir("omh-tui-theme-") as tmp:
            omh_home = Path(tmp) / ".omh"
            # Nothing saved: the Hermes skin still decides, as before.
            self.assertEqual(initial_theme({"skin": {"name": "omh-amber"}}, str(omh_home)).name, "amber")
            mono = theme_for_name("mono")
            assert mono is not None
            write_theme_choice(omh_home, mono)

            self.assertEqual(initial_theme({"skin": {"name": "omh-amber"}}, str(omh_home)).name, "mono")
            self.assertEqual(initial_theme({}, str(omh_home)).name, "mono")
            # No OMH home named (the TUI started some other way than bare `omh`).
            self.assertEqual(initial_theme({"skin": {"name": "omh-amber"}}, None).name, "amber")


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class OpeningTests(AppTestCase):
    def test_a_fresh_session_opens_with_the_banner_in_scrollback(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
            cols=100,
            env={"HOME": "/fixture"},
        )
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        self.run_main(run)
        self.assert_clean_run(run)
        history = run.terminal.screen.history()
        # At 100 columns the block logo comes first. The banner is one row: the model and the keys are the info
        # line's.
        self.assertEqual(history[:LOGO_ROWS], LOGO)
        self.assertEqual(history[LOGO_ROWS], f"⚚ OH-MY-HERMES v{__version__} · ~/project")
        self.assertEqual([row for row in history[LOGO_ROWS + 1 :] if row], [])

    def test_the_banner_is_on_screen_at_the_first_frame_not_pushed_into_scrollback(self) -> None:
        # The banner is flushed with the first frame, which is drawn right under it.
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
            cols=100,
            env={"HOME": "/fixture"},
        )
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, capture="first", label="the first frame"))
        self.run_main(run)
        self.assert_clean_run(run)
        screen = run.terminal.captures["first"]
        self.assertEqual(screen[:LOGO_ROWS], LOGO)
        self.assertTrue(screen[LOGO_ROWS].startswith("⚚ OH-MY-HERMES"), screen[: LOGO_ROWS + 2])
        self.assertEqual(screen[LOGO_ROWS + 1], "")
        self.assertEqual(run.terminal.screen.scrollback, [])

    def test_the_launch_fills_the_screen_and_the_composer_stays_on_the_bottom_rows(self) -> None:
        # The owner, 2026-10-23: the TUI opens full screen, the logo and the banner on top and the composer on the
        # bottom rows with the rows between them empty, and the turn's output fills them from the top while the
        # composer stays where it is. Nothing under the info line.
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers()),
            rows=34,
            cols=110,
            env={"HOME": "/fixture"},
        )
        run.terminal.script(
            Step(b"Reply with exactly the word: ok\r", when=run.terminal.idle, capture="start", label="idle"),
            Step(b"\x04", when=lambda: "later." in run.terminal.history() and run.terminal.idle(), capture="turn",
                 label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        for name in ("start", "turn"):
            with self.subTest(capture=name):
                screen = run.terminal.captures[name]
                status = info_index(screen)
                rule = status - 2 - UNDER_COMPOSER
                self.assertIn(RULE_MARK, screen[rule], screen)
                self.assertEqual(status, 33, screen)  # the info line on the last row, the composer above
        start = run.terminal.captures["start"]
        rule = info_index(start) - 2 - UNDER_COMPOSER
        self.assertTrue(start[LOGO_ROWS].startswith(f"⚚ OH-MY-HERMES v{__version__} · ~/project"), start)
        # In between: the launch card right under the banner's blank row, then empty rows down to the composer.
        card_end = max(index for index, line in enumerate(start[:rule]) if line.startswith("╰"))
        self.assertTrue(start[LOGO_ROWS + 2].startswith("╭─ session"), start)
        self.assertEqual(start[card_end + 1 : rule], [""] * (rule - card_end - 1), start)
        turn = run.terminal.captures["turn"]
        self.assertTrue(any(line.startswith("  ✻ ") for line in turn[:rule]), turn)  # the turn above the composer

    def test_only_the_launch_fills_the_screen_a_redraw_after_the_first_prompt_follows_the_content(self) -> None:
        from omh.tui.screen import LiveRegion
        from test_tui_modes import composer_index, drawn, make_app, type_text

        app, _client = make_app(rows=30, cols=100)
        app.launch_layout = True
        app.region = LiveRegion(app.terminal.write, at_top=True)
        self.assertGreater(composer_index(drawn(app)), 20, "the launch: the composer on the bottom rows")
        type_text(app, "hi")
        app._on_input(Key(ENTER, ""))
        app._full_redraw()
        self.assertLess(composer_index(drawn(app)), 10, "after the first prompt the composer follows the content")

    def test_launched_on_a_screen_holding_output_it_starts_on_the_top_row_and_erases_the_scrollback(self) -> None:
        # The owner, 2026-10-22: scrolling up must stop at the top of the session, not walk into the shell's history.
        # Whatever row the shell left the cursor on, reported or not, the rows above it are pushed off the screen,
        # ED 3 then erases the scrollback (the pushed rows and the shell's older output with them, as a full redraw
        # does), and the first frame starts on the top row, so a menu closing leaves the composer where it was.
        older = [f"$ older {n}" for n in range(80)]
        shell = [f"$ shell {n}" for n in range(40)]
        for row, label in ((34, "the last row, reported"), (None, "the last row, not reported"), (12, "mid-screen")):
            with self.subTest(launch=label):
                run = self.prepare(
                    Scenario("session", spans("session", "startup", "create"), answers=startup_answers()), rows=34, cols=110
                )
                run.terminal = WireTerminal(34, 110)
                # The shell's earlier output in scrollback, its `clear`, then the rows above the cursor on `row`.
                run.terminal.screen.feed("".join(f"{line}\r\n" for line in older) + "\x1b[H\x1b[J")
                printed = shell[: (row or 34) - 1]
                run.terminal.screen.feed("".join(f"{line}\r\n" for line in printed))  # the cursor on `row`, at column 0
                self.assertEqual(run.terminal.screen.scrollback, older[:47])
                run.terminal.cursor_row = row
                rows: dict[str, int] = {}

                def composer_row(name: str, run: object = run, rows: dict[str, int] = rows) -> Callable[[], bool]:
                    def note() -> bool:
                        screen = run.terminal.screen.lines()  # type: ignore[attr-defined]
                        rows[name] = next(index for index, line in enumerate(screen) if line.startswith("❯ Ask Hermes"))
                        return True
                    return note

                run.terminal.script(
                    Step(b"/", when=lambda run=run, composer_row=composer_row: run.terminal.idle() and composer_row("before")(),
                         capture="first", label="idle"),
                    Step(b"\x7f", when=run.terminal.shows("/help"), label="the menu"),
                    Step(b"\x04", when=lambda run=run, composer_row=composer_row: not run.terminal.shows("/help")()
                         and composer_row("after")(), label="closed"),
                )
                self.run_main(run)
                self.assert_clean_run(run)
                first = run.terminal.captures["first"]
                history = run.terminal.screen.history()
                self.assertFalse([line for line in history if line.startswith(("$ shell", "$ older"))], history)
                self.assertEqual(history[: LOGO_ROWS - 1], LOGO[:-1])  # scrolling up stops at the logo
                self.assertEqual(first[: LOGO_ROWS - 1], LOGO[:-1])  # the logo opens the top row
                self.assertEqual(rows["after"], rows["before"])
                self.assertEqual(rows["before"], 34 - 2 - UNDER_COMPOSER)  # the bottom rows: composer, rule, info
                writes = "".join(run.terminal.writes)
                # The startup query, the push, ED 3 once, then the first frame. No ED 2: the push leaves only the
                # cursor's own row on the screen, the top row, which the first frame paints over.
                launch = STARTUP_QUERY + "\n" * 33 + "\x1b[33A\r" + ERASE_SCROLLBACK
                self.assertEqual(writes[: len(launch)], launch)
                self.assertEqual(writes.count(ERASE_SCROLLBACK), 1)
                self.assertNotIn("\x1b[2J", writes)

    def test_launched_on_the_top_row_nothing_is_pushed_and_the_scrollback_is_still_erased(self) -> None:
        # The cursor on the top row leaves nothing above it on the screen, but a shell's `clear` leaves its earlier
        # output in scrollback, one scroll up from the session's top: ED 3 erases it all the same.
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal = WireTerminal()
        run.terminal.screen.feed("".join(f"$ older {n}\r\n" for n in range(40)) + "\x1b[H\x1b[J")
        self.assertTrue(run.terminal.screen.scrollback)
        run.terminal.cursor_row = 1
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, capture="first", label="idle"))
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(run.terminal.screen.scrollback, [])
        self.assertTrue(run.terminal.captures["first"][0].startswith("⚚ OH-MY-HERMES"))
        writes = "".join(run.terminal.writes)
        self.assertEqual(writes[: len(STARTUP_QUERY + ERASE_SCROLLBACK)], STARTUP_QUERY + ERASE_SCROLLBACK)
        self.assertEqual(writes.count(ERASE_SCROLLBACK), 1)
        self.assertNotIn("\n" * 23, writes)

    def test_the_banner_stays_one_row_and_keeps_the_end_of_a_long_path(self) -> None:
        from omh.tui.app import banner_lines

        cwd = "/private/tmp/claude-501/a-very-long-scratch-directory-name/session/scratchpad/m9/project"
        for width in (40, 60, 80, 110, 200):
            with self.subTest(width=width):
                header, _blank = banner_lines(cwd=cwd, resumed="", theme=DEFAULT_THEME, width=width)
                text = line_text(header)
                self.assertLessEqual(line_width(header), width)
                if "…" in text and "m9/project" not in text and width >= 110:
                    self.fail(f"the path lost its end at width {width}: {text}")
        wide = line_text(banner_lines(cwd=cwd, resumed="", theme=DEFAULT_THEME, width=110)[0])
        self.assertTrue(wide.endswith("m9/project"), wide)
        narrow = line_text(banner_lines(cwd=cwd, resumed="a-long-session-id-that-fills-the-row-and-more", theme=DEFAULT_THEME,
                                        width=60)[0])
        self.assertNotIn("/private", narrow)

    def test_the_recorded_default_skin_paints_sky_and_an_omh_skin_paints_its_theme(self) -> None:
        ready = turn_rows("session", 0)
        crimson = {**ready, "params": {**ready["params"], "payload": {"skin": {"name": "omh-crimson"}}}}
        for name, inject in (("sky", ()), ("crimson", ((0, json.dumps(crimson)),))):
            with self.subTest(theme=name):
                run = self.prepare(
                    Scenario("session", spans("session", "startup", "create"), inject=inject, answers=startup_answers())
                )
                seen: list[tuple[int, ...]] = []
                run.terminal.script(
                    Step(b"\x04", when=lambda run=run, seen=seen: run.terminal.idle() and not seen.append(
                        run.terminal.box_foreground()), label="the first frame")
                )
                self.run_main(run)
                self.assert_clean_run(run)
                self.assertEqual(seen[-1], hex_to_rgb(theme_named(name).rule.fg))

    def test_a_resumed_session_draws_its_earlier_turns_before_the_first_frame(self) -> None:
        messages = [
            {"role": "user", "text": "What is in this repo?", "row_id": 1},
            {"role": "assistant", "text": "Let me look.", "row_id": 2},
            {"role": "tool", "name": "terminal", "context": "ls -la", "tool_call_id": "c1"},
            {"role": "tool", "name": "read_file", "context": "README.md", "tool_call_id": "c2"},
            {"role": "assistant", "text": "It is **oh-my-hermes**.", "reasoning": "private chain of thought"},
            {"role": "system", "text": "[System: model switched]"},
            {"role": "user", "text": "Thanks"},
        ]
        resumed = {
            "result": {
                "session_id": LIVE_ID,
                "stored_session_id": STORED_ID,
                "message_count": len(messages),
                "messages": messages,
                "info": {"model": "deepseek/deepseek-v4.1-flash-ultrafast", "cwd": "/fixture/project"},
            }
        }
        run = self.prepare(
            Scenario("session", spans("session", "startup"), answers=(*startup_answers(), ("session.resume", resumed))),
            cols=160,
            env={"HERMES_TUI_RESUME": STORED_ID},
        )
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        self.run_main(run)
        self.assert_clean_run(run)
        history = run.terminal.screen.history()
        self.assertEqual(history[:LOGO_ROWS], LOGO)  # a resumed launch is a start too
        self.assertTrue(history[LOGO_ROWS].startswith(f"⚚ OH-MY-HERMES v{__version__} · resumed {STORED_ID}"))
        self.assertEqual(run.calls("session.list"), [])  # a resumed session needs no pointer to the last one
        self.assertEqual(
            history[LOGO_ROWS + 2 : LOGO_ROWS + 15],
            [  # each block on its rail, and a blank row between two calls, as for a live turn
                "  ❯ What is in this repo?",
                "",
                "  ⚚ Hermes",  # who wrote it; the record does not say which model, so none is named
                "    Let me look.",
                "",
                "  ● terminal(ls -la)",
                "",
                "  ● read_file(README.md)",
                "",
                "  ⚚ Hermes",
                "    It is oh-my-hermes.",
                "",
                "  ❯ Thanks",
            ],
        )
        text = "\n".join(history)
        self.assertNotIn("private chain of thought", text)
        self.assertNotIn("[System", text)

    def test_exit_settles_the_screen_at_once_and_reaps_a_slow_gateway_quickly(self) -> None:
        # The fake keeps running past stdin EOF, as the real gateway often does for 10 s and more.
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers(), after=HANG)
        )
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="exit"))
        self.run_main(run)
        returned = time.monotonic()
        self.assert_clean_run(run)
        pressed = run.terminal.fired["exit"]
        self.assertLess(run.terminal.exited_at - pressed, 0.5)
        self.assertLess(returned - pressed, 1.5)
        self.assertNotIn(BOX_MARK, run.terminal.history())


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class LocalCommandTests(AppTestCase):
    def plain_run(self, **scenario: object) -> Run:
        return self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers(), **scenario)
        )

    def after_reply(self, run: Run) -> Callable[[], bool]:
        return lambda: "later." in run.terminal.history() and run.terminal.idle()

    def test_new_declines_open_requests_and_opens_a_fresh_session(self) -> None:
        create = recorded_answer("approval", "create")
        fresh = {
            "result": {
                "session_id": FRESH_LIVE_ID,
                "stored_session_id": FRESH_STORED_ID,
                "message_count": 0,
                "messages": [],
                "info": {"model": "deepseek/deepseek-v4.1-flash-ultrafast"},
            }
        }
        answers = (
            *startup_answers(),
            ("session.create", create),
            ("session.create", fresh),
            ("session.close", {"result": {"closed": True}}),
            # An alias answered while the approval is open: the one way /new runs with a request pending.
            ("slash.exec", {"result": {"type": "alias", "target": "new"}}),
        )
        startup, turn = spans("approval", "startup", "approval_turn")
        run = self.prepare(Scenario("approval", (startup, turn), answers=answers))
        run.terminal.script(
            Step(b"Run rm -rf ./omh-m0-probe-dir\r/fresh\r", when=run.terminal.idle, label="idle"),
            Step(b"\x04", when=run.terminal.shows(f"New session {FRESH_STORED_ID}."), label="the new session"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        denied = [frame for frame in run.frames if frame.get("id") == "srq-52e9720342b6"]
        self.assertEqual(denied, [{"jsonrpc": "2.0", "id": "srq-52e9720342b6", "result": {"choice": "deny"}}])
        (closed,) = run.calls("session.close")
        self.assertEqual(closed["params"], {"session_id": "f05e2691"})
        self.assertEqual(len(run.calls("session.create")), 2)
        self.assertEqual(run.calls("slash.exec")[0]["params"], {"command": "fresh", "session_id": "f05e2691"})
        # The closed session's remaining events never reach the fresh transcript.
        self.assertNotIn("It was blocked", run.terminal.history())
        # The decline was the TUI's, not the person's: the fresh transcript says so.
        self.assertIn("Declined 1 open request from the session you left.", run.terminal.history())
        self.assertEqual(run.poller.sessions, [APPROVAL_STORED_ID, FRESH_STORED_ID])
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": FRESH_STORED_ID})

    def test_a_failed_new_session_keeps_the_current_one_usable(self) -> None:
        answers = (
            *startup_answers(),
            ("session.create", recorded_answer("session", "create")),
            ("session.create", {"error": {"code": 5032, "message": "no provider is configured"}}),
        )
        startup, turn = spans("session", "startup", "plain_turn")
        run = self.prepare(Scenario("session", (startup, turn), answers=answers), cols=200)
        terminal = run.terminal
        terminal.script(
            self.submit(run, "/new"),
            Step(b"Reply with exactly the word: ok\r", when=terminal.shows("Could not start a new session"),
                 label="the notice"),
            Step(b"\x04", when=self.after_reply(run), label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertIn(f"Could not start a new session (5032): no provider is configured. Still in {STORED_ID}.",
                      terminal.history())
        self.assertEqual(run.calls("session.close"), [])
        self.assertEqual(run.calls("prompt.submit")[0]["params"]["session_id"], LIVE_ID)
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": STORED_ID})

    def test_copy_sends_the_last_reply_as_an_osc_52_frame(self) -> None:
        run = self.plain_run()
        run.terminal.script(
            self.submit(run, "Reply with exactly the word: ok"),
            Step(b"/copy\r", when=self.after_reply(run), label="reply"),
            Step(b"\x04", when=run.terminal.shows("Copied the last reply"), label="the copy notice"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        reply = turn_rows("session", 44)["params"]["payload"]["text"].strip()
        copied = [body for body in run.terminal.screen.osc if body.startswith("52;")]  # the titles are OSC 2
        self.assertEqual(copied, ["52;c;" + base64.b64encode(reply.encode("utf-8")).decode("ascii")])
        self.assertNotIn("52;c;", run.terminal.history())

    def test_logs_pages_the_gateway_stderr_and_q_leaves(self) -> None:
        run = self.plain_run(stderr=("gateway warming up", "model list prefetched"))
        terminal = run.terminal
        terminal.script(
            Step(b"/logs\r", when=terminal.idle, label="idle"),
            Step(b"q", when=lambda: terminal.screen.alternate, capture="pager", label="the pager"),
            Step(b"\x04", when=lambda: not terminal.screen.alternate and terminal.idle(), label="back"),
        )
        self.run_main(run)
        self.assertEqual(terminal.stalled, "")
        self.assertEqual(run.code, 0)
        pager = "\n".join(terminal.captures["pager"])
        self.assertIn("gateway warming up", pager)
        self.assertIn("model list prefetched", pager)
        self.assertIn("gateway stderr (memory only)", pager)
        self.assertEqual(run.calls("slash.exec"), [])

    def test_the_theme_is_measured_against_the_background_the_terminal_reports(self) -> None:
        for background, env, expected in (
            ("#FFFFFF", {}, "#FFFFFF"),
            (None, {"COLORFGBG": "0;15"}, "#FFFFFF"),
            (None, {}, None),
            ("#1E1E1E", {"COLORFGBG": "0;15"}, "#1E1E1E"),  # an answer outranks the variable
        ):
            with self.subTest(background=background, env=env):
                run = self.prepare(
                    Scenario("session", spans("session", "startup", "create"), answers=startup_answers()), env=env
                )
                run.terminal.background = background
                seen: list[str | None] = []
                run.terminal.script(
                    Step(b"\x04", when=lambda run=run, seen=seen: run.terminal.idle() and not seen.append(
                        run.terminal.prompt_foreground()), label="the first frame")
                )
                self.run_main(run)
                self.assert_clean_run(run)
                self.assertEqual(run.terminal.background_queries, 1)
                prompt = theme_named("sky", expected).prompt.fg
                self.assertEqual(seen[-1], hex_to_rgb(prompt))

    def test_a_dark_colorfgbg_counts_as_a_reported_dark_background(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers()), env={"COLORFGBG": "15;0"}
        )
        terminal = run.terminal  # answers no OSC 11
        terminal.script(
            self.submit(run, "/theme auto"),
            Step(b"\x04", when=terminal.shows("COLORFGBG"), label="the background notice"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        said = " ".join(word for word in terminal.history().split() if word)  # it wraps on the echo's rail
        self.assertIn("follows the terminal's background (a dark one, as COLORFGBG names it)", said)

    def test_keys_typed_while_the_background_query_waited_reach_the_composer(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.typed_during_query = b"hi"
        run.terminal.script(Step(b"\x15\x04", when=run.terminal.shows("❯ hi"), label="the early keys"))
        self.run_main(run)
        self.assert_clean_run(run)

    def test_theme_light_dark_and_auto_choose_the_background_the_roles_are_measured_against(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        terminal = run.terminal
        seen: dict[str, tuple[int, ...]] = {}

        def note(name: str, needle: str) -> Callable[[], bool]:
            def ready() -> bool:
                if terminal.idle() and needle in terminal.history():
                    seen[name] = terminal.prompt_foreground()
                    return True
                return False
            return ready

        terminal.script(
            self.submit(run, "/theme light"),
            Step(b"/theme amber\r", when=note("light", "on a light background"), label="light"),
            Step(b"/theme dark\r", when=note("amber", "Theme amber"), label="amber"),
            Step(b"/theme auto\r", when=note("dark", "on a dark background"), label="dark"),
            Step(b"\x04", when=note("auto", "follows the terminal"), label="auto"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(seen["light"], hex_to_rgb(theme_named("sky", "#FFFFFF").prompt.fg))
        self.assertEqual(seen["amber"], hex_to_rgb(theme_named("amber", "#FFFFFF").prompt.fg))  # the mode stays
        self.assertEqual(seen["dark"], hex_to_rgb(theme_named("amber").prompt.fg))
        self.assertEqual(seen["auto"], hex_to_rgb(theme_named("amber").prompt.fg))  # nothing reported: dark stand-in

    def test_theme_switches_for_a_known_name_and_names_the_choices_for_an_unknown_one(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        terminal = run.terminal
        seen: list[tuple[int, ...]] = []
        terminal.script(
            self.submit(run, "/theme crimson"),
            Step(b"/theme nope\r", when=lambda: terminal.idle() and "applies to this session" in terminal.history()
                 and not seen.append(terminal.box_foreground()), label="the switch notice"),
            Step(b"\x04", when=terminal.shows("No theme or launch look named nope"), label="the unknown-theme notice"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(seen[-1], hex_to_rgb(theme_named("crimson").rule.fg))
        history = terminal.history()
        self.assertIn("Theme crimson applies to this session", history)
        said = " ".join(word for word in history.split() if word)  # it wraps on the echo's rail
        self.assertIn("No theme or launch look named nope. Themes: sky, amber, crimson, mono. "
                      "Launch looks: spectrum, violet, gold, graphite, sakura, moonlit, aurora, ember.", said)

    def test_help_lists_local_commands_the_hermes_catalog_by_category_and_keys_in_the_transcript(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create"), answers=startup_answers()), rows=40, cols=200
        )
        terminal = run.terminal
        terminal.script(
            # The first frame comes before Hermes' catalog does: /help waits until the menu offers Hermes' /undo.
            Step(b"/und", when=terminal.idle, label="idle"),
            Step(b"\x15/help\r", when=terminal.shows("/undo"), label="Hermes' catalog in the menu"),
            Step(b"\x04", when=lambda: "opens Hermes' own terminal." in terminal.history() and terminal.idle(),
                 label="the help output"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertFalse(terminal.screen.alternate)  # no pager: the output is the transcript's
        pager = terminal.history()
        self.assertIn("/omh-model     Pick OMH model chains", pager)
        self.assertIn("/reload-skills Re-scan Hermes' skills", pager)
        # The recorded catalog's categories, without what the TUI runs itself, routes to Hermes' terminal or drops:
        # Session (/new /clear /redraw), Exit (/quit) and TUI (/density /logs /mouse) are left with nothing, and
        # /export is the TUI's (it says what Hermes exports before it runs).
        # /import only runs in Hermes' classic CLI: /help names it on a line of its own instead.
        self.assertIn("  Configuration: /config", pager)
        self.assertIn("Only Hermes' classic CLI (`hermes --cli`) runs /handoff /worktree /snapshot /import /hatch "
                      "/palette", pager)
        self.assertIn("/compact       Compress this session's context", pager)
        self.assertIn("  Tools & Skills: /tools /toolsets /skills", pager)
        self.assertNotIn("Session:", pager)
        self.assertNotIn("skill commands available", pager)  # the recording lists none
        # The keys live in one table that ? and /keys draw; /help points there.
        self.assertIn("Keys: ? on an empty composer, or /keys, lists every key.", pager)
        self.assertIn("/yolo included", pager)
        # The banner no longer says it, so /help is where the way back to Hermes' own terminal stays.
        self.assertIn("Bare `hermes` opens Hermes' own terminal.", pager)
        self.assertIn("  ❯ /help\n    ⎿  OMH TUI commands:", terminal.history())
        self.assertEqual([frame["method"] for frame in run.frames], STARTUP_METHODS)

    def test_reload_skills_rescans_in_the_gateway_and_the_new_skill_completes(self) -> None:
        # The second catalog is the recorded one with one skill more, in the shape Hermes 6c61c3e27d's
        # `commands.catalog` gives a skill: a pair only, counted in `skill_count`, in no category.
        recorded = recorded_answer("session", "commands_catalog")["result"]
        reloaded = {**recorded, "pairs": [*recorded["pairs"], ["/omh-codebase-uml", "Draw UML from the code"]],
                    "skills": {"/omh-codebase-uml": {"usage": 0, "origin": "local"}}, "skill_count": 1}
        rescan = {"added": [{"name": "omh-codebase-uml"}], "removed": [], "unchanged": [], "total": 1, "commands": 1}
        answers = (
            *startup_answers(),
            ("skills.reload", {"result": {"output": "Reloading skills...\nAdded skills:\n  - omh-codebase-uml\n"
                                                    "1 skill(s) available", "result": rescan}}),
            ("commands.catalog", {"result": reloaded}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            self.submit(run, "/reload-skills"),
            Step(b"/uml", when=terminal.shows("1 skill(s) available"), label="the rescan's output"),
            Step(b"\x7f\x7f\x7f\x7f", when=terminal.shows("/omh-codebase-uml"), capture="menu", label="the menu"),
            Step(b"\x04", when=lambda: terminal.idle() and not terminal.shows("/omh-codebase-uml")(), label="cleared"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertTrue(any("Draw UML from the code" in line for line in terminal.captures["menu"]))
        self.assertEqual(
            [frame["method"] for frame in run.frames], [*STARTUP_METHODS, "skills.reload", "commands.catalog"]
        )
        self.assertEqual([frame["params"] for frame in run.calls("commands.catalog")], [{"session_id": LIVE_ID}] * 2)
        (reload,) = run.calls("skills.reload")
        self.assertEqual(reload["params"], {"session_id": LIVE_ID})
        self.assertEqual(run.calls("slash.exec"), [])

    def test_queue_lists_what_waits_for_the_running_turn(self) -> None:
        run = self.prepare(
            Scenario(
                "session",
                spans("session", "startup", "create", "plain_turn", "smart_approved_turn"),
                answers=startup_answers(UNREAD_DEFAULT),
            )
        )
        terminal = run.terminal
        terminal.script(
            self.submit(run, "/queue"),
            Step(b"first prompt\rsecond prompt\r/queue\r", when=terminal.shows("Nothing is queued."), label="empty"),
            Step(b"\x04", when=lambda: "cleanly)." in terminal.history() and terminal.idle(), label="turn 2"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        history = terminal.screen.history()
        listed = history.index("    ⎿  Queued (sent one at a time as each turn ends):")
        self.assertEqual(history[listed - 1], "  ❯ /queue")
        self.assertEqual(history[listed + 1], "       1. second prompt")
        self.assertIn("  ❯ second prompt  ⧗ from queue", history[listed:])  # the queue sent it once the turn ended
        self.assertLess(history.index("  ❯ first prompt"), listed)

    def test_steer_and_interrupt_modes_send_input_during_a_turn_at_once(self) -> None:
        for mode in ("steer", "interrupt"):
            with self.subTest(mode=mode):
                run = self.prepare(
                    Scenario(
                        "session",
                        spans("session", "startup", "create", "plain_turn", "smart_approved_turn"),
                        answers=busy_mode_answers(mode),
                    )
                )
                terminal = run.terminal
                terminal.script(
                    # The busy mode is read without holding up the first frame, and input sent while a turn runs
                    # before its answer queues (Hermes' default). The replay answers in the order it was asked,
                    # config.get before the catalog, so once the menu offers Hermes' /undo the mode has arrived.
                    Step(b"/und", when=terminal.idle, label="idle"),
                    Step(b"\x15first prompt\rsecond prompt\r", when=terminal.shows("/undo"), label="the mode read"),
                    Step(b"\x04", when=lambda terminal=terminal: "cleanly)." in terminal.history() and terminal.idle(),
                         label="turn 2"),
                )
                self.run_main(run)
                self.assert_clean_run(run)
                first, second = run.calls("prompt.submit")
                self.assertEqual(first["params"], {"session_id": LIVE_ID, "text": "first prompt"})
                # Sent while the first turn was pending, with no `queued`: Hermes applies its own mode.
                self.assertEqual(second["params"], {"session_id": LIVE_ID, "text": "second prompt"})
                self.assertNotIn("queued", terminal.history())

SHOT = {
    "attached": True,
    "path": "/fixture/project/shot.png",
    "count": 1,
    "remainder": "",
    "text": "[User attached image: shot.png]",
    "name": "shot.png",
    "width": 1280,
    "height": 720,
    "token_estimate": 510,
}
CLIP = {
    "attached": True,
    "path": "/fixture/hermes-home/images/clip_20261013_120000_1.png",
    "count": 1,
    "name": "clip_20261013_120000_1.png",
    "width": 640,
    "height": 480,
    "token_estimate": 85,
}
OTHER_STORED_ID = "20261012_090000_router"
OTHER_LIVE_ID = "c0ffee01"
INTERRUPT_ROW = re.compile(r"\(\d+s( · ↓[\d.]+k? tokens)? · esc to interrupt\)")


def bracketed(text: str) -> bytes:
    return b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~"


def info_index(screen: list[str]) -> int:
    """The info line's row: the last that is not blank, since every row under the region is."""
    return info_row_index(screen)


def info_row_of(screen: list[str]) -> str:
    """The info line, its badge taken out (`without_badge`)."""
    return without_badge(screen[info_index(screen)])


def composer_row(screen: list[str]) -> str:
    """What a one-row composer shows: the row above its bottom rule, trailing blanks dropped."""
    return composer_text(screen[info_index(screen) - 1 - UNDER_COMPOSER])


def resumed_other(messages: list[dict] | None = None) -> dict:
    return {
        "result": {
            "session_id": OTHER_LIVE_ID,
            "stored_session_id": OTHER_STORED_ID,
            "message_count": len(messages or []),
            "messages": messages or [],
            "info": {"model": "deepseek/deepseek-v4.1-flash-ultrafast", "cwd": "/fixture/project"},
        }
    }


# The bytes the TUI reads from the path Hermes staged an image at: the fixtures' paths name no real file.
KEPT_IMAGE = b"\x89PNG\r\n\x1a\nfixture"
DETACHED = ("image.detach", {"result": {"detached": True, "count": 0}})


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
@patch("omh.tui.app.read_image", lambda path: KEPT_IMAGE)
class AttachmentTests(AppTestCase):
    def test_image_is_a_token_in_the_composer_and_the_echo_lists_it_under_the_prompt(self) -> None:
        upload = "/fixture/hermes-home/images/upload_1.png"
        answers = (*startup_answers(), ("image.attach", {"result": SHOT}), DETACHED,
                   ("image.attach_bytes", {"result": {"attached": True, "path": upload, "count": 1}}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=answers))
        terminal = run.terminal
        terminal.script(
            Step(b"/image ./shot.png\r", when=terminal.idle, capture="before", label="idle"),
            Step(b"Reply with exactly the word: ok\r", when=terminal.shows("[Image #1]"), capture="token",
                 label="the token"),
            Step(b"\x04", when=lambda: "later." in terminal.history() and terminal.idle(), capture="after",
                 label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (attach,) = run.calls("image.attach")
        self.assertEqual(attach["params"], {"session_id": LIVE_ID, "path": "./shot.png"})
        # Hermes let go of it at once, and the prompt staged it again from the TUI's bytes, right before it went.
        (detach,) = run.calls("image.detach")
        self.assertEqual(detach["params"], {"session_id": LIVE_ID, "path": "/fixture/project/shot.png"})
        (stage,) = run.calls("image.attach_bytes")
        self.assertEqual(base64.b64decode(stage["params"]["content_base64"]), KEPT_IMAGE)
        methods = [frame.get("method") for frame in run.frames if frame.get("method")]
        self.assertLess(methods.index("image.attach_bytes"), methods.index("prompt.submit"))
        before, token = terminal.captures["before"], terminal.captures["token"]
        # The token is in the input row itself: no row above it, and the composer stays where the launch put it.
        self.assertEqual(info_index(token), info_index(before))
        self.assertEqual(composer_row(token), "❯ [Image #1]")
        self.assertIn(RULE_MARK, token[info_index(token) - 1 - UNDER_COMPOSER - 1])
        self.assertNotIn("📎", "\n".join(token))  # no attachment row: the token is the image
        (submit,) = run.calls("prompt.submit")
        self.assertEqual(submit["params"]["text"], "[Image #1] Reply with exactly the word: ok")
        history = terminal.history()
        self.assertIn("[Image #1] Reply with exactly the word: ok", history)
        self.assertIn("⎿  [Image #1]", history)  # one row under the echo for the image it went with

    def test_paste_reports_an_empty_clipboard_and_ctrl_v_attaches_its_image(self) -> None:
        answers = (
            *startup_answers(),
            ("clipboard.paste", {"result": {"attached": False, "message": "No image found in clipboard"}}),
            ("clipboard.paste", {"result": CLIP}),
            DETACHED,
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            self.submit(run, "/paste"),
            Step(b"\x16", when=terminal.shows("No image found in clipboard"), label="the empty-clipboard notice"),
            # Ctrl+C clears the draft, the token with it, and Ctrl+D then exits on the empty composer.
            Step(b"\x03\x04", when=terminal.shows("❯ [Image #1]"), label="the clipboard image's token"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual([frame["params"] for frame in run.calls("clipboard.paste")], [{"session_id": LIVE_ID}] * 2)
        (detach,) = run.calls("image.detach")  # at once, as it was staged; Ctrl+C sends nothing more
        self.assertEqual(detach["params"], {"session_id": LIVE_ID, "path": CLIP["path"]})

    def test_a_one_line_paste_is_offered_to_detect_drop_first(self) -> None:
        answers = (
            *startup_answers(),
            ("input.detect_drop", {"result": {
                "matched": True, "is_image": True, "path": "/fixture/project/drop.png", "count": 1,
                "text": "[User attached image: drop.png]", "name": "drop.png", "width": 800, "height": 600,
                "token_estimate": 340}}),
            ("input.detect_drop", {"result": {
                "matched": True, "is_image": False, "path": "/fixture/project/notes.txt", "name": "notes.txt",
                "text": "[User attached file: /fixture/project/notes.txt]"}}),
            ("input.detect_drop", {"result": {"matched": False}}),
            DETACHED,
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        file_ref = "[User attached file: /fixture/project/notes.txt]"
        terminal.script(
            Step(bracketed("/fixture/project/drop.png"), when=terminal.idle, label="idle"),
            Step(bracketed("/fixture/project/notes.txt"), when=terminal.shows("❯ [Image #1]"), capture="image",
                 label="the image token"),
            Step(bracketed(" and hello"), when=terminal.shows(f"{file_ref}"), label="the file reference"),
            Step(bracketed("line one\nline two"), when=terminal.shows("and hello"), capture="typed",
                 label="the unmatched paste"),
            Step(b"\x03\x04", when=terminal.shows("line two"), label="the multi-line paste"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        sent = [frame["params"] for frame in run.calls("input.detect_drop")]
        self.assertEqual(sent, [
            {"session_id": LIVE_ID, "text": "/fixture/project/drop.png"},
            {"session_id": LIVE_ID, "text": "/fixture/project/notes.txt"},
            {"session_id": LIVE_ID, "text": " and hello"},
        ])
        # An image drop is queued by the gateway: a token, never the path typed.
        self.assertEqual(composer_row(terminal.captures["image"]), "❯ [Image #1]")
        self.assertEqual(composer_row(terminal.captures["typed"]), f"❯ [Image #1] {file_ref} and hello")

    def test_cmd_backspace_takes_the_text_and_the_image_and_nothing_stages_it_again(self) -> None:
        answers = (*startup_answers(), ("image.attach", {"result": SHOT}), DETACHED)
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            self.submit(run, "/image ./shot.png"),
            Step("이런느낌으로".encode(), when=terminal.shows("[Image #1]"), label="the token"),
            Step(b"\x15", when=terminal.shows("[Image #1] 이런느낌으로"), label="the token and the words"),  # Cmd+Backspace
            Step(b"\x04", when=lambda: not terminal.shows("[Image #1]")() and terminal.idle(), capture="gone",
                 label="the token gone"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (detach,) = run.calls("image.detach")  # when it was staged; the token's deletion needs no call
        self.assertEqual(detach["params"], {"session_id": LIVE_ID, "path": "/fixture/project/shot.png"})
        self.assertEqual(run.calls("image.attach_bytes"), [])
        self.assertTrue(composer_row(terminal.captures["gone"]).startswith("❯"))


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class SessionSwitchTests(AppTestCase):
    def test_sessions_opens_a_picker_and_enter_switches_to_the_picked_session(self) -> None:
        listed = recorded_answer("session", "session_list")
        recorded_row = listed["result"]["sessions"][0]
        listed["result"]["sessions"].append(
            {**recorded_row, "id": OTHER_STORED_ID, "title": "Refactor the router", "preview": "Split the router",
             "started_at": recorded_row["started_at"] - 86400, "message_count": 2, "source": "cli"}
        )
        history = [
            {"role": "user", "text": "Split the router in two"},
            {"role": "assistant", "text": "Done: chat.py and recommend.py."},
        ]
        answers = (
            *startup_answers(),
            ("session.list", listed),
            ("session.resume", resumed_other(history)),
            ("session.close", {"result": {"closed": True}}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=answers),
                           env={"HOME": "/fixture"})
        terminal = run.terminal
        terminal.script(
            self.submit(run, "Reply with exactly the word: ok"),
            Step(b"/sessions\r", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
            Step(b"\x1b[B\r", when=terminal.shows("Refactor the router"), capture="picker", label="the picker"),
            Step(b"\x04", when=lambda: f"resumed {OTHER_STORED_ID}" in terminal.history() and terminal.idle(),
                 label="the switch"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        startup, listing = run.calls("session.list")  # the fresh session's last-session lookup, then /sessions
        self.assertEqual((startup["params"], listing["params"]), ({"limit": 3}, {"limit": 50}))
        picker = "\n".join(terminal.captures["picker"])
        self.assertIn("● Reply with ok", picker)
        self.assertIn("2 messages", picker)
        methods = [frame.get("method") for frame in run.frames]
        (resume,) = run.calls("session.resume")
        self.assertEqual(resume["params"], {"session_id": OTHER_STORED_ID, "cols": 80})
        (close,) = run.calls("session.close")
        self.assertEqual(close["params"], {"session_id": LIVE_ID})
        # The old session closes only once the new one is open: a refused resume leaves it untouched.
        self.assertLess(methods.index("session.resume"), methods.index("session.close"))
        shown = terminal.history()
        self.assertTrue(shown.startswith(f"⚚ OH-MY-HERMES v{__version__} · resumed {OTHER_STORED_ID}"), shown[:200])
        self.assertIn("❯ Split the router in two", shown)
        self.assertIn("Done: chat.py and recommend.py.", shown)
        self.assertNotIn("I'm Hermes, your agent", shown)  # the old transcript went with the redraw
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": OTHER_STORED_ID})
        self.assertEqual(run.poller.sessions, [STORED_ID, OTHER_STORED_ID])

    def test_sessions_with_an_id_switches_directly(self) -> None:
        answers = (
            *startup_answers(),
            ("session.resume", resumed_other()),
            ("session.close", {"result": {"closed": True}}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        run.terminal.script(
            self.submit(run, f"/resume {OTHER_STORED_ID}"),
            Step(b"\x04", when=lambda: f"resumed {OTHER_STORED_ID}" in run.terminal.history() and run.terminal.idle(),
                 label="the switch"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        # Only the fresh session's last-session lookup: an id needs no listing.
        self.assertEqual([call["params"] for call in run.calls("session.list")], [{"limit": 3}])
        (resume,) = run.calls("session.resume")
        self.assertEqual(resume["params"], {"session_id": OTHER_STORED_ID, "cols": 80})
        self.assertEqual(run.calls("session.close")[0]["params"], {"session_id": LIVE_ID})

    def test_a_refused_resume_keeps_the_current_session(self) -> None:
        refused = {"error": {"code": 4090, "message": "the session is open in another process"}}
        answers = (*startup_answers(), ("session.resume", refused))
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=answers), cols=200
        )
        terminal = run.terminal
        terminal.script(
            self.submit(run, f"/sessions {OTHER_STORED_ID}"),
            Step(b"Reply with exactly the word: ok\r", when=terminal.shows("Could not switch"), label="the notice"),
            Step(b"\x04", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertIn(f"Could not switch to {OTHER_STORED_ID} (4090): the session is open in another process. "
                      f"Still in {STORED_ID}.", terminal.history())
        self.assertEqual(run.calls("session.close"), [])
        self.assertEqual(run.calls("prompt.submit")[0]["params"]["session_id"], LIVE_ID)
        self.assertEqual(json.loads(run.active_session_file.read_text(encoding="utf-8")), {"session_id": STORED_ID})


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class KeyTests(AppTestCase):
    def interrupted_run(self) -> Run:
        return self.prepare(
            Scenario("session", spans("session", "startup", "create", "interrupted_turn"), answers=startup_answers())
        )

    def running(self, run: Run) -> Callable[[], bool]:
        return run.terminal.running

    def test_esc_on_an_empty_composer_interrupts_and_with_text_keeps_the_draft(self) -> None:
        run = self.interrupted_run()
        terminal = run.terminal
        terminal.script(
            self.submit(run, "Write the numbers from 1 to 300, one per line, nothing else."),
            Step(b"draft", when=self.running(run), capture="running", label="running"),
            Step(b"\x1b", when=terminal.shows("❯ draft"), label="the draft"),
            # The replay holds the turn open until it sees session.interrupt, so a turn still running
            # well after that Esc proves the Esc sent nothing.
            Step(b"\x15", when=lambda: terminal.shows("❯ draft")() and time.monotonic() - terminal.fired["the draft"] > 0.4,
                 capture="after the first esc", label="the draft after Esc"),
            Step(b"\x1b", when=lambda: not terminal.shows("❯ draft")(), label="the empty composer"),
            Step(b"\x04", when=lambda: "Interrupted." in terminal.history() and terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (interrupt,) = run.calls("session.interrupt")
        self.assertEqual(interrupt["params"], {"session_id": LIVE_ID})
        after = terminal.captures["after the first esc"]
        self.assertNotIn("Interrupted.", "\n".join(after))  # the turn still runs
        self.assertIn("esc again to", info_row_of(after))  # and the info line says what a second Esc does
        activity = [line for line in terminal.captures["running"] if INTERRUPT_ROW.search(line)]
        self.assertEqual(len(activity), 1, terminal.captures["running"])

    def test_a_terminal_that_answers_the_kitty_query_names_ctrl_enter_under_the_first_queued_prompt(self) -> None:
        prompt = "Write the numbers from 1 to 300, one per line, nothing else."
        for answer, key in ((b"\x1b[?1u", "ctrl+enter"), (b"", "ctrl+j")):
            with self.subTest(answer=answer):
                run = self.interrupted_run()
                terminal = run.terminal
                terminal.typed_during_query = answer  # what `Terminal.query_background` hands back
                said = SEND_NOW_HINT.format(key=key)
                terminal.script(
                    self.submit(run, prompt),  # legacy bytes only: no key arrives as a report
                    Step(b"then stop\r", when=self.running(run), label="running"),
                    Step(b"\x03", when=terminal.shows(said), capture="queued", label="queued"),
                    # The interrupt brings the queued prompt back into the composer: clear it, then leave.
                    Step(b"\x15\x04", when=lambda: "Interrupted." in terminal.history(), label="end"),
                )
                self.run_main(run)
                self.assert_clean_run(run)
                queued = terminal.captures["queued"]
                row = next(index for index, line in enumerate(queued) if said in line)
                self.assertEqual(queued[row - 1].rstrip(), "⧗ then stop")  # under the queued prompt, its own row
                self.assertNotIn("steer", info_row_of(queued))  # the info line names no steer key
                (submit,) = run.calls("prompt.submit")
                self.assertEqual(submit["params"]["text"], prompt)  # the answer typed nothing

    def test_the_activity_row_counts_the_seconds_since_the_prompt(self) -> None:
        run = self.interrupted_run()
        terminal = run.terminal
        two_seconds = re.compile(r"\(2s( · ↓[\d.]+k? tokens)? · esc to interrupt\)")  # the replay streams
        terminal.script(
            self.submit(run, "Write the numbers from 1 to 300, one per line, nothing else."),
            Step(b"\x03", when=lambda: any(two_seconds.search(line) for line in terminal.screen.lines()),
                 label="two seconds in"),
            Step(b"\x04", when=lambda: "Interrupted." in terminal.history() and terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        pressed = terminal.fired["the idle info line"]
        self.assertGreaterEqual(terminal.fired["two seconds in"] - pressed, 2.0)

    def test_at_completion_asks_complete_path_and_tab_replaces_the_token(self) -> None:
        items = {"items": [
            {"text": "@file:src/app.py", "display": "app.py", "meta": ""},
            {"text": "@folder:src/", "display": "src/", "meta": "dir"},
        ]}
        answers = (*startup_answers(), ("complete.path", {"result": items}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            Step(b"look at @sr", when=terminal.idle, label="idle"),
            Step(b"\t", when=terminal.shows(" app.py"), capture="menu", label="the path menu"),
            # Past the debounce, so a re-ask for the accepted file would have gone out by now.
            Step(b"\x03\x04", when=lambda: terminal.shows("❯ look at @file:src/app.py")()
                 and time.monotonic() - terminal.fired["the path menu"] > 0.5, capture="accepted",
                 label="the accepted path"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        # One call for the whole typed word (debounced), none for the accepted file.
        (asked,) = run.calls("complete.path")
        self.assertEqual(asked["params"], {"word": "@sr", "session_id": LIVE_ID})
        menu = terminal.captures["menu"]
        # The launch puts the composer on the bottom rows, so the menu opens above it, over its top rule.
        top = rule_rows(menu)[0]
        self.assertTrue(menu[top - 2].startswith("❯ app.py"), menu)  # the highlighted row has the pointer
        self.assertTrue(menu[top - 1].startswith("  src/"), menu)
        self.assertIn("dir", menu[top - 1])
        accepted = terminal.captures["accepted"]
        self.assertFalse(any(line.startswith(" src/") for line in accepted), accepted)

    def test_path_completion_waits_for_the_token_to_hold_still_and_drops_a_stale_answer(self) -> None:
        items = {"items": [{"text": "@file:src/app.py", "display": "app.py", "meta": ""}]}
        answers = (*startup_answers(), ("complete.path", {"result": items}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        now = [100.0]
        client = self.make_client(run)(gateway_spawn(run.environ))
        client.start(ready_timeout=10.0)
        app = App(terminal, client, run.environ, poller=run.poller, clock=lambda: now[0])
        app.startup()
        terminal.script(
            Step(b"look at @s", when=terminal.idle, label="idle"),
            Step(b"r", when=lambda: True, label="the next key, no time later"),
            Step(b"", when=lambda: not now.__setitem__(0, 101.0), label="the token held still"),
            Step(b"\x03\x04", when=terminal.shows(" app.py"), label="the path menu"),
        )
        with terminal:
            run.code = app.run()
        self.assert_clean_run(run)
        self.assertEqual([frame["params"] for frame in run.calls("complete.path")],
                         [{"word": "@sr", "session_id": LIVE_ID}])
        # An answer for a word the composer has moved on from is dropped.
        app.composer.handle(Paste("@srx"))
        app._track_path_token()
        app.path_items = []
        app._on_path_items(app.path_seq, "@sr", items)
        self.assertEqual(app.path_items, [])

    def test_ctrl_o_opens_the_details_view_and_q_leaves_it(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers())
        )
        terminal = run.terminal
        terminal.script(
            self.submit(run, "Reply with exactly the word: ok"),
            Step(b"\x0f", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
            Step(b"q", when=lambda: terminal.screen.alternate, capture="details", label="the details view"),
            Step(b"\x04", when=lambda: not terminal.screen.alternate and terminal.idle(), label="back"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        details = "\n".join(terminal.captures["details"])
        self.assertIn("❯ Reply with exactly the word: ok", details)
        self.assertIn("  ⚚ Hermes · deepseek-v4.1-flash-ultrafast\n    ok", details)
        self.assertIn("history · ", details)

    def test_ctrl_l_redraws_the_session_from_memory(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers())
        )
        terminal = run.terminal
        cleared = CLEAR_SCREEN_AND_SCROLLBACK  # the launch's own ED 3 comes alone, without ED 2
        terminal.script(
            self.submit(run, "Reply with exactly the word: ok"),
            Step(b"\x0c", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
            Step(b"\x04", when=lambda: cleared in "".join(terminal.writes) and terminal.idle(), capture="redrawn",
                 label="the redraw"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        everything = terminal.screen.scrollback + terminal.captures["redrawn"]
        self.assertEqual(sum(line.startswith("⚚ OH-MY-HERMES") for line in everything), 1, everything)
        self.assertEqual(sum("I'm Hermes, your agent" in line for line in everything), 1, everything)

    def test_a_backslash_before_enter_adds_a_line_instead_of_sending(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=startup_answers())
        )
        terminal = run.terminal
        terminal.script(
            Step(b"line one\\\rline two\r", when=terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (submitted,) = run.calls("prompt.submit")
        self.assertEqual(submitted["params"], {"session_id": LIVE_ID, "text": "line one\nline two"})


if __name__ == "__main__":
    unittest.main()
