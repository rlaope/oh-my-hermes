"""Line-VISUAL production TUI/OS PTY journeys; gateway is a replay backend."""
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
from _tui_gateway_replay import (
    Scenario, client_frames, materialize, recorded_answer, replay_env, spans,
)
from _vt_screen import VTScreen

TEXT = "FIRST\nSECOND\nTAIL"
CASES = (("Vd", "FIRST\nTAIL", 6), ("Vdu", TEXT, 6),
         ("Vkd", "TAIL", 0), ("Vd.", "FIRST", 0),
         ("VvVV", TEXT, 6), ("GVd", "FIRST\nSECOND", 6))


def assert_line_visual_pty(testcase):
    """Execute every line operator at 20×8 and 100×30; missing PTY is a failure."""
    if importlib.util.find_spec("termios") is None:
        testcase.skipTest("the OMH TUI needs termios")
    import pty
    import termios

    repo = Path(__file__).resolve().parents[1]
    for width, height in ((20, 8), (100, 30)):
        for command, expected, caret in CASES:
            with testcase.subTest(columns=width, rows=height, command=command):
                with make_test_tempdir("omh-operator-pty-") as temporary:
                    root = Path(temporary)
                    materialize(root, Scenario("session", spans("session", "startup", "create"), answers=(
                        ("config.get", {"result": {"config": {"display": {"vim_mode": True}}}}),
                        ("config.get", {"result": {"mtime": 100.0}}),
                        ("commands.catalog", recorded_answer("session", "commands_catalog")),
                        ("session.list", recorded_answer("session", "session_list")),
                        ("model.options", recorded_answer("parity", "model_options")),
                        ("prompt.submit", {"result": {"accepted": True}}),
                    )))
                    home = root / "profile"
                    home.mkdir()
                    (home / "config.yaml").write_text("display:\n  vim_mode: true\n", encoding="utf-8")
                    env = replay_env(root)
                    env.update(HOME=str(root), HERMES_HOME=str(home), OMH_HOME=str(root / "omh"),
                               HERMES_CWD=str(root), TERM="xterm-256color", TERM_PROGRAM="Apple_Terminal",
                               PYTHONPATH=os.pathsep.join((str(repo), str(repo / "tests"))),
                               PYTHONDONTWRITEBYTECODE="1", OMH_TUI_UPDATE_CHECK="0",
                               OMH_NO_TUI="0", OMH_TUI_KEYBOARD="legacy")
                    master, slave = pty.openpty()
                    termios.tcsetwinsize(slave, (height, width))
                    screen = VTScreen(rows=height, cols=width)
                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    raw = bytearray()
                    child = None
                    before = after = None
                    try:
                        child = subprocess.Popen(
                            [sys.executable, "-B", "-c", "import os; from omh.tui.app import main; "
                             "raise SystemExit(main(os.environ, fetch_latest=lambda: '', contain_faults=False))"],
                            cwd=repo, env=env, stdin=slave, stdout=slave, stderr=slave,
                            start_new_session=True,
                        )
                        os.close(slave)
                        slave = None

                        def diagnostic():
                            return (f"{width}x{height} {command}\nBEFORE: {before!r}\nAFTER: {after!r}"
                                    f"\nRPC: {client_frames(root)!r}\nRAW: {raw.decode('utf-8', 'replace')[-6000:]}")

                        def pump(seconds=0.12):
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
                                        raise AssertionError(f"{error}\n{diagnostic()}") from error

                        def send(data):
                            os.write(master, data)
                            pump()

                        def escape_to_normal():
                            # A bare Escape can wait for the production decoder's
                            # in-flight terminal-report timeout. Do not send the
                            # next command until its rendered mode has changed.
                            os.write(master, b"\x1b")
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline:
                                pump(0.05)
                                if "NORMAL" in screen.lines()[-1] and screen.cursor_visible:
                                    return
                                if child is not None and child.poll() is not None:
                                    break
                            testcase.fail("Escape did not settle to NORMAL\n" + diagnostic())

                        deadline = time.monotonic() + 12
                        while "INSERT" not in "\n".join(screen.lines()) and time.monotonic() < deadline:
                            pump()
                            if child.poll() is not None:
                                break
                        testcase.assertIn("INSERT", "\n".join(screen.lines()), diagnostic())
                        # Three hard lines remain real lines, not paste chips.
                        send(b"\x1b[200~" + TEXT.encode() + b"\x1b[201~")
                        escape_to_normal()
                        send(b"2gg0")
                        before = (screen.lines(), screen.cursor)
                        testcase.assertIn("NORMAL", "\n".join(before[0]), diagnostic())
                        send(b"V")
                        visual = screen.lines()
                        testcase.assertIn("VISUAL LINE", "\n".join(visual), diagnostic())
                        testcase.assertTrue(screen.cursor_visible, diagnostic())
                        testcase.assertIn(b"\x1b[2 q", raw, diagnostic())
                        # Exit without editing before the independent operator journey.
                        send(b"V")
                        send(command.encode())
                        if command.startswith("c"):
                            testcase.assertIn("INSERT", "\n".join(screen.lines()), diagnostic())
                            send(b"X")
                            escape_to_normal()
                        after = (screen.lines(), screen.cursor)
                        testcase.assertTrue(screen.cursor_visible, diagnostic())
                        testcase.assertIn("NORMAL", "\n".join(after[0]), diagnostic())
                        if command.startswith("y"):
                            testcase.assertEqual(after, before, diagnostic())
                            send(b"P")
                        # A plain-text marker exported through the normal submit
                        # RPC observes the caret without a production hook. "!"
                        # at offset zero would enter shell mode instead.
                        send(b"iZ")
                        escape_to_normal()
                        send(b"\r")
                        deadline = time.monotonic() + 5
                        submissions = []
                        while not submissions and time.monotonic() < deadline:
                            pump()
                            submissions = [frame for frame in client_frames(root)
                                           if frame.get("method") == "prompt.submit"]
                        testcase.assertEqual(len(submissions), 1, diagnostic())
                        testcase.assertEqual(submissions[0]["params"]["text"],
                                             expected[:caret] + "Z" + expected[caret:], diagnostic())
                        testcase.assertIsNone(child.poll(), diagnostic())
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
