"""The OMH TUI loop's waiting (`App._step`): how long it reads for, when it settles held keys, when it draws.

The terminal here reads on the app's clock: a scripted read takes its
seconds and hands back its bytes, and any other read waits out the timeout
the loop asked for and brings nothing, as a select with no input does.
"""

from __future__ import annotations

import unittest

from _tui_lines import composer_text
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import SID, RecordingClient
from omh.tui.app import (
    FLUSH_SILENCE_SECONDS,
    IDLE_READ_SECONDS,
    MIN_FRAME_SECONDS,
    READ_TIMEOUT_SECONDS,
    TICK_SECONDS,
    App,
)
from omh.tui.gateway import Event


class LoopTerminal(ScriptedTerminal):
    def __init__(self, now: list[float], reads: list[tuple[float, bytes]]) -> None:
        super().__init__()
        self.now = now
        self.reads = list(reads)
        self.log: list[tuple[str, object]] = []  # ("read", timeout) and ("write", text), in order

    def write(self, text: str) -> None:
        self.log.append(("write", text))
        super().write(text)

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        self.log.append(("read", (timeout, wake)))
        delay, data = self.reads.pop(0) if self.reads else (timeout, b"")
        self.now[0] += delay
        return data

    def timeouts(self) -> list[float]:
        return [round(float(value[0]), 6) for kind, value in self.log if kind == "read"]

    def log_reads(self) -> list[tuple[float, int | None]]:
        return [(round(float(value[0]), 6), value[1]) for kind, value in self.log if kind == "read"]  # type: ignore[index]


WAKE = 99  # a descriptor number the loop hands its reads; this terminal never selects on it


def loop_app(*reads: tuple[float, bytes], busy: bool = False) -> tuple[App, LoopTerminal, RecordingClient]:
    now = [100.0]
    terminal = LoopTerminal(now, list(reads))
    client = RecordingClient()
    app = App(terminal, client, {}, poller=FakePoller(), clock=lambda: now[0])  # type: ignore[arg-type]
    app.sid = SID
    app.turn_pending = busy
    app.wake = WAKE
    return app, terminal, client


def drawn_lines(app: App) -> list[str]:
    return app.terminal.screen.lines()  # type: ignore[attr-defined]


def delta(text: str) -> Event:
    return Event("message.delta", SID, {"text": text})


class LoopWaitTests(unittest.TestCase):
    def test_the_first_frame_is_drawn_before_the_first_read(self) -> None:
        app, terminal, _client = loop_app((0.0, b"\x04"))  # Ctrl+D on the empty composer ends the run
        self.assertEqual(app.run(), 0)
        kinds = [kind for kind, _value in terminal.log]
        self.assertLess(kinds.index("write"), kinds.index("read"))

    def test_after_a_frame_the_loop_waits_long_or_until_its_tick_in_one_read(self) -> None:
        app, terminal, _client = loop_app()
        app._render_when_due()
        app._step()
        app._step()
        self.assertEqual(terminal.log_reads(), [(IDLE_READ_SECONDS, WAKE), (IDLE_READ_SECONDS, WAKE)])
        app.turn_pending = True
        app.dirty = True
        app._render_when_due()
        app._step()
        app._step()
        self.assertEqual(terminal.log_reads()[2:], [(TICK_SECONDS, WAKE), (0.0, WAKE)])  # the first read ends at the tick: due then

    def test_held_bytes_bring_the_loop_back_and_settle_after_a_silence(self) -> None:
        app, terminal, client = loop_app((0.0, b"\x1b"), busy=True)
        app._render_when_due()
        while not client.named("session.interrupt") and terminal.now[0] < 101.0:
            app._step()
        reads = terminal.log_reads()
        self.assertTrue(all(timeout <= READ_TIMEOUT_SECONDS for timeout, _wake in reads[1:]), reads)
        quiet = round(terminal.now[0] - 100.0, 6)  # the Esc arrived at 100.0: it settled after this much quiet
        self.assertTrue(FLUSH_SILENCE_SECONDS <= quiet <= MIN_FRAME_SECONDS + READ_TIMEOUT_SECONDS, quiet)

    def test_a_wake_right_after_an_escape_does_not_settle_it(self) -> None:
        app, _terminal, client = loop_app((0.0, b"\x1b"), (0.001, b""), (0.001, b"[A"), busy=True)
        for _ in range(3):
            app._step()
        self.assertEqual(client.named("session.interrupt"), [])  # it was an arrow, read in two parts

    def test_gateway_news_inside_the_frame_interval_waits_for_it_and_shares_one_frame(self) -> None:
        app, terminal, client = loop_app(busy=True)
        frames: list[float] = []
        render = app._render
        app._render = lambda: (frames.append(terminal.now[0]), render())[1]  # type: ignore[method-assign]
        client.inbox.append(Event("message.start", SID, {}))
        terminal.reads.append((0.0, b""))  # woken at once
        app._step()
        client.inbox += [delta("one "), delta("two ")]  # arriving during the interval after that frame
        terminal.reads.append((0.002, b""))  # the gateway's wake ends the read early
        app._step()  # waits out the rest of the interval without the gateway's wake, then draws both
        self.assertEqual(terminal.log_reads()[-1], (round(MIN_FRAME_SECONDS - 0.002, 6), None))
        self.assertEqual(len(frames), 2)
        self.assertGreaterEqual(round(frames[1] - frames[0], 6), MIN_FRAME_SECONDS)
        self.assertIn("one two", "\n".join(drawn_lines(app)))

    def test_a_key_inside_the_frame_interval_draws_at_once(self) -> None:
        app, terminal, _client = loop_app()
        app._render_when_due()
        terminal.reads.append((0.002, b"x"))
        app._step()
        self.assertTrue(app.composer.text == "x" and not app.dirty)
        self.assertIn("❯ x", [composer_text(line) for line in drawn_lines(app)])


if __name__ == "__main__":
    unittest.main()
