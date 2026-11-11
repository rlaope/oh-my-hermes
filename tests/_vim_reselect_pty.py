"""Reselect acceptance through production input/rendering in real OS PTYs.

Only the gateway is replayed. Literal cases below are handwritten semantic and
visible-cell oracles; no composer state/resolver is imported or patched. Set
OMH_VIM_RESELECT_EVIDENCE to retain every journey, including failures.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

from _test_temp_root import make_test_tempdir
from _tui_gateway_replay import (
    Scenario, client_frames, materialize, recorded_answer, replay_env, spans,
)
from _vt_screen import VTScreen

SIZES = ((20, 8), (100, 30))
CHIP_PAYLOAD = "one\ntwo\nthree\nfour"
WRAPPED = "0123456789abcdefghijKLMNOPQRST\nuvwxyz"


@dataclass(frozen=True)
class View:
    highlighted: str
    head_row: str
    head_column: int


@dataclass(frozen=True)
class Journey:
    name: str
    text: str
    acquire: str
    view: View
    operate: str
    submitted: str
    line: bool = False
    exit_key: str = "escape"
    narrow: View | None = None
    resized_narrow: View | None = None
    resized_wide: View | None = None
    clipboard: bool = False
    narrow_submission: str | None = None


# Head columns include the production two-cell composer gutter. Newline markers
# and final-line blanks are display-only: the literal submitted oracle omits them.
JOURNEYS = (
    Journey("reverse-char-delete", "ABCD", "gg03lv2h", View("BCD", "ABCD", 3), "d", "ZA"),
    Journey("reverse-char-undo", "ABCD", "gg03lv2h", View("BCD", "ABCD", 3), "du", "AZBCD"),
    Journey("reverse-char-repeat", "ABCD EFGH", "gg03lv2h", View("BCD", "ABCD EFGH", 3),
            "dw.", "A ZH"),
    Journey("reverse-line-delete", "FIRST\nSECOND", "G$Vgg", View("FIRST␊SECOND ", "FIRST␊", 2),
            "d", "Z", line=True),
    Journey("reverse-line-change", "FIRST\nSECOND", "G$Vgg", View("FIRST␊SECOND ", "FIRST␊", 2),
            "cX", "ZX", line=True),
    Journey("reverse-line-yank-capture", "FIRST\nSECOND", "G$Vgg", View("FIRST␊SECOND ", "FIRST␊", 2),
            "y", "ZFIRST\nSECOND", line=True, exit_key="y"),
    Journey("blank-line", "A\n\nB", "2ggV", View("␊", "␊", 2), "d", "A\nZB", line=True),
    Journey("trailing-empty-line", "A\n", "GV", View(" ", " ", 2), "d", "ZA", line=True),
    Journey("unterminated-last-line", "A\nEND", "G0V", View("END ", "END ", 2), "d", "ZA", line=True),
    # Production terminal rendering NFC-normalizes e + combining acute; the
    # actual input stream retains the decomposed grapheme and ZWJ sequence.
    Journey("unicode-reverse", "Aé👩‍💻🙂Z", "gg04lv3h", View("é👩‍💻🙂Z", "Aé👩‍💻🙂Z", 3),
            "d", "ZA"),
    Journey("character-newline", "AB\nCD", "gg0vG", View("AB␊C", "CD", 2), "d", "ZD"),
    Journey("rendered-row-character", WRAPPED, "gg02lvj",
            View("23456789abcdefghijKLMNOPQRST␊uvw", "uvwxyz", 4),
            "d", "01Zxyz", narrow=View("ijK", "ijKLMNOPQRST", 4),
            resized_narrow=View("ijKLMNOPQRST␊uvw", "uvwxyz", 4),
            resized_wide=View("23456789abcdefghijK", "0123456789abcdefghijKLMNOPQRST", 22),
            narrow_submission="01ZLMNOPQRST\nuvwxyz"),
    Journey("rendered-row-line", WRAPPED, "gg02lVj",
            View("0123456789abcdefghijKLMNOPQRST␊uvwxyz ", "uvwxyz ", 4),
            "d", "Z", line=True, narrow=View("ijKLMNOPQRST␊", "ijKLMNOPQRST␊", 4),
            resized_narrow=View("ijKLMNOPQRST␊uvwxyz ", "uvwxyz ", 4),
            resized_wide=View("0123456789abcdefghijKLMNOPQRST␊", "0123456789abcdefghijKLMNOPQRST␊", 22),
            narrow_submission="Zuvwxyz"),
    Journey("opaque-paste-undo", CHIP_PAYLOAD, "gg0v",
            View("[Pasted text #1 +4 lines]", "[Pasted text #1 +4 lines]", 2),
            "du", "Z" + CHIP_PAYLOAD,
            narrow=View("[Pasted text #1 +4 lines]", "[Pasted text #1", 2)),
    Journey("clipboard-image-undo", "", "gg0v", View("[Image #1]", "[Image #1] ", 2),
            "dux", "Z ", clipboard=True),
)


def assert_reselect_pty(testcase):
    """No PTY skips: every case starts at each size and resizes while restored."""
    import pty
    import termios

    repo = Path(__file__).resolve().parents[1]
    evidence = os.environ.get("OMH_VIM_RESELECT_EVIDENCE")
    for width, height in SIZES:
        for case in JOURNEYS:
            with testcase.subTest(columns=width, rows=height, journey=case.name):
                with make_test_tempdir("omh-reselect-pty-") as temporary:
                    root = Path(temporary)
                    image = root / "clipboard.png"
                    image.write_bytes(b"\x89PNG\r\n\x1a\n")
                    materialize(root, Scenario("session", spans("session", "startup", "create"), answers=(
                        ("config.get", {"result": {"config": {"display": {"vim_mode": True}}}}),
                        ("config.get", {"result": {"mtime": 100.0}}),
                        ("commands.catalog", recorded_answer("session", "commands_catalog")),
                        ("session.list", recorded_answer("session", "session_list")),
                        ("model.options", recorded_answer("parity", "model_options")),
                        ("clipboard.paste", {"result": {"attached": True, "path": str(image), "name": image.name}}),
                        ("image.detach", {"result": {"detached": True}}),
                        ("image.render", {"error": {"code": -32000, "message": "preview unavailable in replay"}}),
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
                    raw, inputs = bytearray(), bytearray()
                    events: list[dict[str, Any]] = []
                    snapshots: list[dict[str, Any]] = []
                    child = None
                    passed = False
                    failure = None
                    wanted = case.narrow_submission if width == 20 and case.narrow_submission is not None else case.submitted

                    def capture(label) -> dict[str, Any]:
                        shapes = re.findall(rb"\x1b\[([0-9]+) q", raw)
                        shot = dict(label=label, size=[screen.cols, screen.rows], lines=screen.lines(),
                                    cells=[list(row) for row in screen._text],
                                    attrs=[[screen.attrs_at(r, c) for c in range(screen.cols)]
                                           for r in range(screen.rows)],
                                    cursor=screen.cursor, cursor_visible=screen.cursor_visible,
                                    cursor_shape=int(shapes[-1]) if shapes else None,
                                    raw_offset=len(raw), input_offset=len(inputs))
                        snapshots.append(shot)
                        return shot

                    def diagnostic():
                        return (f"{width}x{height} {case.name}\n"
                                f"SCREENS: {[(s['label'], s['cursor'], s['lines']) for s in snapshots]!r}\n"
                                f"RPC: {client_frames(root)!r}\nRAW: {raw.decode('utf-8', 'replace')[-4000:]}")

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
                                screen.feed(decoder.decode(chunk))

                    def send(data):
                        inputs.extend(data)
                        events.append(dict(kind="input", hex=data.hex(), raw_offset=len(raw)))
                        testcase.assertEqual(os.write(master, data), len(data), diagnostic())
                        pump()

                    def wait_for(predicate, message, seconds=5):
                        deadline = time.monotonic() + seconds
                        while time.monotonic() < deadline:
                            pump(0.05)
                            if predicate():
                                return
                            if child is not None and child.poll() is not None:
                                break
                        capture("failed-wait")
                        testcase.fail(message + "\n" + diagnostic())

                    def escape_to_normal():
                        send(b"\x1b")
                        wait_for(lambda: "NORMAL" in screen.lines()[-1] and screen.cursor_visible,
                                 "Escape did not settle to NORMAL")

                    def assert_view(label, expected):
                        shot = capture(label)
                        testcase.assertIn("VISUAL LINE" if case.line else "VISUAL", shot["lines"][-1], diagnostic())
                        if not case.line:
                            testcase.assertNotIn("VISUAL LINE", shot["lines"][-1], diagnostic())
                        testcase.assertTrue(shot["cursor_visible"], diagnostic())
                        testcase.assertEqual(shot["cursor_shape"], 2, diagnostic())
                        highlighted = "".join(screen._text[r][c]
                                              for r in range(screen.rows) for c in range(screen.cols)
                                              if 7 in screen.attrs_at(r, c))
                        testcase.assertEqual(highlighted, expected.highlighted, diagnostic())
                        row, column = screen.cursor
                        body = "".join(screen._text[row][2:]).rstrip()
                        testcase.assertEqual(body, expected.head_row.rstrip(), diagnostic())
                        testcase.assertEqual(column, expected.head_column, diagnostic())
                        testcase.assertIn(7, screen.attrs_at(row, column), diagnostic())
                        return shot

                    try:
                        child = subprocess.Popen(
                            [sys.executable, "-B", "-c", "import os; from omh.tui.app import main; "
                             "raise SystemExit(main(os.environ, fetch_latest=lambda: '', contain_faults=False))"],
                            cwd=repo, env=env, stdin=slave, stdout=slave, stderr=slave,
                            start_new_session=True,
                        )
                        os.close(slave)
                        slave = None
                        wait_for(lambda: "INSERT" in screen.lines()[-1], "TUI did not enter INSERT", 12)
                        capture("startup")
                        if case.text:
                            send(b"\x1b[200~" + case.text.encode() + b"\x1b[201~")
                        if case.clipboard:
                            send(b"\x16")
                            wait_for(lambda: any(f.get("method") == "image.detach" for f in client_frames(root)),
                                     "clipboard image was not consumed")
                        escape_to_normal()
                        # Before any selection, counted gv is an observable no-op.
                        before = capture("no-saved-before")
                        send(b"9999gv")
                        after = capture("no-saved-after")
                        testcase.assertEqual((before["lines"], before["attrs"], before["cursor"]),
                                             (after["lines"], after["attrs"], after["cursor"]), diagnostic())
                        send(case.acquire.encode())
                        expected = case.narrow if width == 20 and case.narrow else case.view
                        acquired = assert_view("acquired", expected)
                        if case.exit_key == "escape":
                            escape_to_normal()
                        else:
                            send(case.exit_key.encode())
                        capture("saved")
                        send(b"G0" if not case.clipboard else b"$")
                        capture("moved-away")
                        send(b"9999gv")
                        restored = assert_view("restored", expected)
                        testcase.assertEqual((restored["lines"], restored["attrs"], restored["cursor"]),
                                             (acquired["lines"], acquired["attrs"], acquired["cursor"]), diagnostic())
                        # NORMAL-only gv is consumed without changing an active range.
                        send(b"gv")
                        assert_view("active-gv-noop", expected)
                        escape_to_normal()
                        send(b"gg0gv")
                        assert_view("second-restore", expected)
                        new_width, new_height = (100, 30) if width == 20 else (20, 8)
                        events.append(dict(kind="resize", columns=new_width, rows=new_height,
                                           raw_offset=len(raw), input_offset=len(inputs)))
                        termios.tcsetwinsize(master, (new_height, new_width))
                        screen.resize(new_height, new_width)
                        os.kill(child.pid, signal.SIGWINCH)
                        pump(0.35)
                        resized = (case.resized_wide or case.view) if new_width == 100 else (
                            case.resized_narrow or case.narrow or case.view)
                        assert_view("resized-restored", resized)
                        send(case.operate.encode())
                        if case.operate.startswith("c"):
                            escape_to_normal()
                        capture("operated")
                        testcase.assertIn("NORMAL", screen.lines()[-1], diagnostic())
                        # The submission marker measures the post-operator caret.
                        send(b"iZ")
                        escape_to_normal()
                        send(b"\r")
                        wait_for(lambda: any(f.get("method") == "prompt.submit" for f in client_frames(root)),
                                 "no prompt.submit observed")
                        frames = client_frames(root)
                        submissions = [f for f in frames if f.get("method") == "prompt.submit"]
                        testcase.assertEqual(len(submissions), 1, diagnostic())
                        submitted = submissions[0]["params"]["text"]
                        testcase.assertEqual(submitted, wanted, diagnostic())
                        testcase.assertNotIn("␊", submitted, diagnostic())
                        calls = [f["method"] for f in frames if "method" in f]
                        allowed = {"client.capabilities", "config.get", "commands.catalog", "session.list", "session.create",
                                   "model.options", "prompt.submit"}
                        if case.clipboard:
                            allowed.update(("clipboard.paste", "image.detach", "image.render"))
                            testcase.assertEqual(calls.count("clipboard.paste"), 1, diagnostic())
                            testcase.assertEqual(calls.count("image.detach"), 1, diagnostic())
                        testcase.assertFalse(set(calls) - allowed, diagnostic())
                        testcase.assertIsNone(child.poll(), diagnostic())
                        capture("submitted")
                        passed = True
                    except BaseException as error:
                        failure = repr(error)
                        capture("failure")
                        raise
                    finally:
                        if child is not None:
                            # Terminate the whole owned session, including the replay
                            # gateway; wait() reaps the TUI even after an assertion.
                            try:
                                os.killpg(child.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            try:
                                child.wait(timeout=4)
                            except subprocess.TimeoutExpired:
                                try:
                                    os.killpg(child.pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                                child.wait(timeout=4)
                        os.close(master)
                        if slave is not None:
                            os.close(slave)
                        if evidence:
                            destination = Path(evidence) / f"{width}x{height}-{case.name}"
                            destination.mkdir(parents=True, exist_ok=True)
                            (destination / "terminal.raw").write_bytes(raw)
                            (destination / "input.raw").write_bytes(inputs)
                            (destination / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
                            (destination / "screens.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")
                            (destination / "result.json").write_text(json.dumps(dict(
                                passed=passed, failure=failure, initial_size=[width, height],
                                journey=case.name, child_pid=child.pid if child else None,
                                child_returncode=child.returncode if child else None,
                                expected_submission=wanted,
                                observation="draft/metadata inferred only through real submission and operator/undo; no state hooks",
                            ), indent=2), encoding="utf-8")
                            for name in ("scenario.json", "client_frames.jsonl"):
                                source = root / "tui_gateway" / name
                                if source.exists():
                                    shutil.copyfile(source, destination / name)
