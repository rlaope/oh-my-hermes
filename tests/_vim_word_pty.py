"""WM-7: real TUI/PTY word-motion acceptance (no composer replacements).

Call ``assert_word_motions_pty(self)`` from ``TestWM.test_pty``.  The only
fake is the existing recorded JSON-RPC gateway; terminal, app, decoder,
composer, layout and rendering are the production implementations.
"""
from __future__ import annotations

import codecs
import importlib.util
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from _test_temp_root import make_test_tempdir
from _tui_gateway_replay import Scenario, materialize, recorded_answer, replay_env, spans
from _vt_screen import VTScreen

TEXT = "alpha,beta gamma.delta epsilon"
# (command, starting code-point offset, expected offset); literal Vim oracles.
CASES = (("w", 0, 5), ("W", 0, 11), ("b", 20, 17),
         ("B", 20, 11), ("e", 11, 15), ("E", 11, 21),
         ("ge", 17, 16), ("gE", 17, 9))


def assert_word_motions_pty(testcase):
    """Assert all eight motions at 20 and 100 columns in disposable profiles."""
    if importlib.util.find_spec("termios") is None:
        testcase.skipTest("the OMH TUI needs termios")
    import pty
    import termios

    repo = Path(__file__).resolve().parents[1]
    for width in (20, 100):
        with testcase.subTest(columns=width), make_test_tempdir("omh-word-pty-") as temporary:
            root = Path(temporary)
            materialize(root, Scenario("session", spans("session", "startup", "create"), answers=(
                ("config.get", {"result": {"config": {"display": {"vim_mode": True}}}}),
                ("config.get", {"result": {"mtime": 100.0}}),
                ("commands.catalog", recorded_answer("session", "commands_catalog")),
                ("session.list", recorded_answer("session", "session_list")),
                ("model.options", recorded_answer("parity", "model_options")),
            )))
            home = root / "profile"
            home.mkdir()
            (home / "config.yaml").write_text("display:\n  vim_mode: true\n", encoding="utf-8")
            env = replay_env(root)
            env.update(HOME=str(root), HERMES_HOME=str(home), OMH_HOME=str(root / "omh"),
                       HERMES_CWD=str(root), TERM="xterm-256color", TERM_PROGRAM="Apple_Terminal",
                       PYTHONPATH=os.pathsep.join((str(repo), str(repo / "tests"))),
                       OMH_NO_TUI="0", OMH_TUI_KEYBOARD="legacy")
            master, slave = pty.openpty()
            termios.tcsetwinsize(slave, (40, width))
            screen = VTScreen(rows=40, cols=width)
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            raw = bytearray()
            child = None
            try:
                child = subprocess.Popen(
                    [sys.executable, "-c", "import os; from omh.tui.app import main; "
                     "raise SystemExit(main(os.environ, fetch_latest=lambda: '', contain_faults=False))"],
                    cwd=repo, env=env, stdin=slave, stdout=slave, stderr=slave,
                    start_new_session=True,
                )
                os.close(slave)
                slave = None

                def pump(seconds=0.25):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                            try:
                                chunk = os.read(master, 65536)
                            except OSError:
                                break
                            if not chunk:
                                break
                            raw.extend(chunk)
                            try:
                                screen.feed(decoder.decode(chunk))
                            except AssertionError as error:
                                log = root / "tui_gateway" / "client_frames.jsonl"
                                raise AssertionError(f"{error}\nRPC: {log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''}\nRAW: {raw.decode('utf-8', 'replace')[-5000:]}") from error

                def send(data):
                    os.write(master, data)
                    pump()

                deadline = time.monotonic() + 12
                while "INSERT" not in "\n".join(screen.lines()) and time.monotonic() < deadline:
                    pump()
                    if child.poll() is not None:
                        break
                testcase.assertIn("INSERT", "\n".join(screen.lines()), raw.decode("utf-8", "replace")[-6000:])
                send(b"\x1b[200~" + TEXT.encode() + b"\x1b[201~")
                send(b"\x1b")  # separate read: not an Alt chord
                testcase.assertIn("NORMAL", "\n".join(screen.lines()))
                for motion, start, expected in CASES:
                    with testcase.subTest(columns=width, motion=motion):
                        send(b"gg0" + b"l" * start)
                        # Map each literal text character to its rendered coordinate by
                        # walking the composer rows from the unique first word. No
                        # production word-motion/layout helper computes this oracle.
                        lines = screen.lines()
                        first = next((r for r, line in enumerate(lines) if "alpha" in line), None)
                        testcase.assertIsNotNone(first, lines)
                        positions = []
                        offset = 0
                        for row in range(first, len(lines)):
                            line = lines[row]
                            col = line.find("alpha") if row == first else 2
                            while col < len(line) and offset < len(TEXT):
                                testcase.assertEqual(line[col], TEXT[offset], (width, row, col, lines))
                                positions.append((row, col))
                                offset += 1
                                col += 1
                            if offset == len(TEXT):
                                break
                            if offset < len(TEXT) and TEXT[offset] == " ":
                                positions.append((row, col))
                                offset += 1
                        testcase.assertEqual(offset, len(TEXT), lines)
                        testcase.assertEqual(screen.cursor, positions[start], (motion, "origin", lines))
                        send(motion.encode())
                        testcase.assertEqual(screen.cursor, positions[expected], (width, motion, lines, screen.lines()))
                        testcase.assertEqual(screen.lines(), lines, "motion changed rendered draft")
                        testcase.assertTrue(screen.cursor_visible)
                # Pending g commands own invalid followers/Escape in the real
                # decoder/App path too: neither may edit or clear this draft.
                for prefix, cancel in ((b"g", b"x"), (b"2dg", b"x"), (b"3g", b"\x1b"), (b"2dg", b"\x1b")):
                    with testcase.subTest(columns=width, prefix=prefix, cancel=cancel):
                        send(b"gg0")
                        lines = screen.lines()
                        origin = screen.cursor
                        send(prefix)
                        send(cancel)
                        testcase.assertEqual(screen.lines(), lines, "g cancellation changed rendered draft")
                        testcase.assertEqual(screen.cursor, origin)
                        testcase.assertIn("NORMAL", "\n".join(screen.lines()))
                        send(b"w")
                        testcase.assertEqual(screen.cursor, (origin[0], origin[1] + 5), "cancel left a pending command")
                testcase.assertIsNone(child.poll(), raw.decode("utf-8", "replace")[-4000:])
            finally:
                if child is not None:
                    if child.poll() is None:
                        try:
                            os.killpg(child.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            child.wait(timeout=4)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait(timeout=4)
                    else:
                        child.wait(timeout=4)
                os.close(master)
                if slave is not None:
                    os.close(slave)


def test_pty(self):
    """Drop-in TestWM.test_pty implementation."""
    assert_word_motions_pty(self)


if __name__ == "__main__":
    import unittest

    class TestWM(unittest.TestCase):
        test_pty = test_pty

    unittest.main()
