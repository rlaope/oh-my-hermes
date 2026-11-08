"""An image the person attaches is rendered by Hermes (`image.render`) and drawn under the prompt it goes with.

The app is driven as `test_tui_image_tokens` drives it: Ctrl+V goes through
`App._on_input`, and `FakeHermes` answers the staging calls. It leaves
`image.render` unanswered, so each test answers it itself (`respond`), at the
moment the case needs: before the prompt goes, after it went, after a session
switch. The answer's checking is `test_tui_inline_image_parse`'s; the rows under
the prompt are `test_tui_inline_image_rows`'.
"""

from __future__ import annotations

import base64
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_tui_image_tokens import CTRL_V, FakeHermes
from test_tui_modes import SID, drawn, make_app, notices, type_text
from omh.tui import gateway_contract as contract
from omh.tui.gateway import Event
from omh.tui.app import PREVIEW_WAIT_SECONDS, QUIET_EXPIRY_METHODS, UNSENT_BACK_SWITCH, Attachment, image_caption
from omh.tui.inline_image import PLACEHOLDER, PREVIEW_MAX_ROWS, UPPER_HALF
from omh.tui.keys import ENTER, Key
from omh.tui.style import COLOR_256, TRUECOLOR
from omh.tui.transcript import UserBlock

IMAGE_ID = 0x9A2B3C
DIACRITICS = ("\u0305", "\u030d")
APC = re.compile(r"\x1b_G[^\x1b]*\x1b\\")  # what the VT model in the tests cannot draw, taken out before it


def kitty_result(image_id: int = IMAGE_ID, cols: int = 3, rows: int = 2) -> dict:
    """A kitty answer as Hermes' `render_inline_image` gives it, its transmit in two chunks (the first 4096
    characters, as Hermes' `_kitty_apc` cuts them)."""
    data = base64.standard_b64encode(bytes(range(256)) * 13).decode("ascii")  # 4440 characters
    transmit = (f"\x1b_Ga=T,U=1,i={image_id},c={cols},r={rows},f=100,q=2,m=1;{data[:4096]}\x1b\\"
                f"\x1b_Gm=0;{data[4096:]}\x1b\\")
    return {
        "mode": "kitty", "cols": cols, "rows": rows, "color": "#%06x" % (image_id & 0xFFFFFF), "transmit": transmit,
        "placeholder": [PLACEHOLDER + DIACRITICS[row] + PLACEHOLDER * (cols - 1) for row in range(rows)],
    }


def unicode_result() -> dict:
    """A 2-row by 3-column half-block answer: red over blue in every cell."""
    return {"mode": "unicode", "cols": 3, "rows": 2, "cells": [[[255, 0, 0, 255, 0, 0, 255, 255]] * 3] * 2}


KITTY = {"KITTY_WINDOW_ID": "1", "COLORTERM": "truecolor"}
# Where the TUI asks for half-blocks: Hermes' `display.inline_images: kitty` still answers kitty there unless the ask
# says no graphics.
HALF_BLOCK_TERMINALS = (
    ("Terminal.app", {"TERM_PROGRAM": "Apple_Terminal", "TERM": "xterm-256color"}),
    ("tmux", {"TMUX": "/tmp/tmux-1/default,1,0", "COLORTERM": "truecolor"}),
    ("kitty at 256 colours", {"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty"}),
)


class PreviewTestCase(unittest.TestCase):
    def start(self, cols: int = 80, environ: dict | None = None) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.now = [1000.0]
        self.app, self.client = make_app(cols=cols, environ=environ or {}, clock=lambda: self.now[0])
        terminal = self.app.terminal
        feed = terminal.screen.feed  # type: ignore[attr-defined]
        terminal.screen.feed = lambda text: feed(APC.sub("", text))  # type: ignore[attr-defined]
        self.hermes = FakeHermes(self.app, self.client, Path(home.name))

    def paste(self) -> None:
        self.app._on_input(CTRL_V)
        self.hermes.pump()

    def send(self, text: str = "what is this") -> None:
        type_text(self.app, text)
        self.app._on_input(Key(ENTER))
        self.hermes.pump()

    def renders(self) -> list[dict]:
        return self.client.named("image.render")

    def transmits(self) -> list[str]:
        return [text for text in self.app.terminal.writes if text.startswith("\x1b_G")]  # type: ignore[attr-defined]

    def users(self) -> list[UserBlock]:
        return [block for block in self.app.transcript.blocks if isinstance(block, UserBlock)]

    def written(self) -> str:
        return "".join(self.app.terminal.writes)  # type: ignore[attr-defined]

    def step(self, seconds: float) -> None:
        """One turn of the loop with `seconds` gone by and nothing typed."""
        def read(timeout: float, wake: int | None = None) -> bytes:
            self.now[0] += seconds
            return b""

        with mock.patch.object(self.app.terminal, "read", read):
            self.app._step()


class RequestTests(PreviewTestCase):
    def test_a_paste_asks_hermes_once_for_a_preview_of_the_path_it_staged(self) -> None:
        self.start()
        self.paste()
        path = list(self.hermes.files)[0]
        self.assertEqual(self.renders(), [{"path": path, "cols": 64, "rows": PREVIEW_MAX_ROWS, "graphics": False,
                                           "terminal": "unicode"}])
        methods = [method for method, _params in self.client.calls]
        self.assertLess(methods.index("image.detach"), methods.index("image.render"))

    def test_the_preview_is_as_wide_as_the_terminal_leaves_under_the_label(self) -> None:
        self.start(cols=40)
        self.paste()
        (render,) = self.renders()
        self.assertEqual(render["cols"], 40 - 2 - 2 - 3)  # the rail, the output indent and `⎿  `

    def test_no_preview_is_asked_under_no_color(self) -> None:
        self.start(environ={"NO_COLOR": "1"})
        self.paste()
        self.assertEqual(self.renders(), [])
        self.assertEqual([label for label, _image in self.app.composer.images.values()], ["[Image #1]"])  # attached

    def test_no_preview_is_asked_without_a_session(self) -> None:
        self.start()
        self.app.sid = ""
        self.app._request_preview(Attachment("/h/shot.png", "shot.png", "", "[Image #1]"))
        self.assertEqual(self.renders(), [])

    def test_kitty_and_ghostty_at_truecolor_ask_for_kitty_placeholders(self) -> None:
        self.start(environ={"KITTY_WINDOW_ID": "1", "COLORTERM": "truecolor"})
        self.paste()
        self.assertEqual([render["terminal"] for render in self.renders()], ["kitty"])

    def test_kitty_inside_tmux_or_below_truecolor_asks_for_half_blocks(self) -> None:
        for environ in ({"KITTY_WINDOW_ID": "1", "COLORTERM": "truecolor", "TMUX": "/tmp/tmux-1/default,1,0"},
                        {"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty-256color"}):
            with self.subTest(environ):
                self.start(environ=environ)
                self.paste()
                self.assertEqual([render["terminal"] for render in self.renders()], ["unicode"])

    def test_graphics_is_asked_only_where_kitty_placeholders_paint(self) -> None:
        for name, environ in (*HALF_BLOCK_TERMINALS, ("kitty at truecolor", KITTY)):
            with self.subTest(name):
                self.start(environ=environ)
                self.paste()
                (render,) = self.renders()
                self.assertEqual(render["graphics"], environ is KITTY)
                self.assertEqual(render["terminal"], "kitty" if environ is KITTY else "unicode")

    def test_the_call_is_declared_optional_and_its_expiry_says_nothing(self) -> None:
        self.assertIn("image.render", contract.OPTIONAL_METHODS)
        self.assertIn("image.render", QUIET_EXPIRY_METHODS)


class AnswerTests(PreviewTestCase):
    def test_a_kitty_image_is_sent_to_the_terminal_once_even_when_attached_twice(self) -> None:
        self.start(environ={"KITTY_WINDOW_ID": "1", "COLORTERM": "truecolor"})
        self.paste()
        self.paste()
        self.hermes.respond("image.render", kitty_result())
        self.hermes.respond("image.render", kitty_result())
        self.assertEqual(self.transmits(), [kitty_result()["transmit"]])
        self.assertEqual(sorted(self.app.previews), ["[Image #1]", "[Image #2]"])
        self.assertTrue(all(preview.transmit == "" for preview in self.app.previews.values()))  # not kept
        self.assertEqual(self.app.inline_placed, {IMAGE_ID})

    def test_a_kitty_answer_to_a_half_block_ask_writes_nothing_and_keeps_no_preview(self) -> None:
        for name, environ in HALF_BLOCK_TERMINALS:
            with self.subTest(name):
                self.start(environ=environ)
                self.paste()
                self.hermes.respond("image.render", kitty_result())  # Hermes' config pins kitty
                self.send()
                self.hermes.admit()
                drawn(self.app)
                self.assertEqual((self.transmits(), self.app.inline_placed, self.app.previews), ([], set(), {}))
                self.assertEqual(self.users()[-1].previews, (None,))
                self.assertNotIn(PLACEHOLDER, self.written())

    def test_a_forged_transmit_writes_nothing_and_draws_no_preview(self) -> None:
        self.start(environ={"KITTY_WINDOW_ID": "1", "COLORTERM": "truecolor"})
        self.paste()
        forged = kitty_result()
        forged["transmit"] = "\x1b]52;c;aGVsbG8=\x07" + forged["transmit"]
        self.hermes.respond("image.render", forged)
        self.assertEqual(self.transmits(), [])
        self.assertFalse(any("\x1b]52" in text for text in self.app.terminal.writes))  # type: ignore[attr-defined]
        self.assertEqual(self.app.previews, {})

    def test_off_draws_nothing_and_says_nothing(self) -> None:
        self.start()
        self.paste()
        self.hermes.respond("image.render", {"mode": "off"})
        self.send()
        self.assertEqual(self.app.previews, {})
        self.assertEqual(self.users()[-1].previews, (None,))
        self.assertEqual(notices(self.app), [])

    def test_a_hermes_without_image_render_keeps_the_session_and_the_label(self) -> None:
        self.start()
        self.paste()
        self.hermes.respond("image.render", error={"code": contract.METHOD_NOT_FOUND, "message": "unknown method"})
        self.send()
        self.assertEqual((self.app.sid, self.app.exit_code), (SID, None))
        self.assertEqual(notices(self.app), [])
        screen = "\n".join(drawn(self.app))
        self.assertIn("⎿  [Image #1] image_1.png · 4×3 · 1 KB", screen)

    def test_the_sent_prompt_shows_the_caption_and_the_preview_rows(self) -> None:
        self.start()
        self.paste()
        self.hermes.respond("image.render", unicode_result())
        self.send()
        self.hermes.admit()
        (user,) = self.users()
        self.assertEqual(user.images, ("[Image #1] image_1.png · 4×3 · 1 KB",))
        self.assertEqual([preview.rows for preview in user.previews], [2])
        screen = drawn(self.app)
        at = next(index for index, row in enumerate(screen) if "[Image #1] image_1.png" in row)
        self.assertEqual([row.rstrip()[-3:] for row in screen[at + 1 : at + 3]], [UPPER_HALF * 3] * 2)

    def test_an_answer_after_the_prompt_went_still_shows_in_its_live_echo(self) -> None:
        self.start()
        self.paste()
        self.send()
        self.assertEqual(self.users()[-1].previews, (None,))
        self.hermes.respond("image.render", unicode_result())
        self.assertEqual([preview.cols for preview in self.users()[-1].previews], [3])
        self.assertIn(UPPER_HALF * 3, "\n".join(drawn(self.app)))

    def test_an_answer_after_the_echo_was_printed_leaves_the_printed_rows_alone(self) -> None:
        self.start()
        self.paste()
        self.send()
        self.step(PREVIEW_WAIT_SECONDS)  # the wait is over: the echo is taken into scrollback
        self.hermes.respond("image.render", unicode_result())
        self.assertEqual(self.users()[-1].previews, (None,))
        self.assertIn("[Image #1]", self.app.previews)  # kept, for nothing printed now

    def test_an_answer_after_a_session_switch_is_dropped(self) -> None:
        self.start(environ={"KITTY_WINDOW_ID": "1", "COLORTERM": "truecolor"})
        self.paste()
        self.app._reset_staging(UNSENT_BACK_SWITCH)
        self.hermes.respond("image.render", kitty_result())
        self.assertEqual((self.app.previews, self.transmits()), ({}, []))

    def test_preview_cells_are_painted_at_the_terminals_colour_depth(self) -> None:
        for environ, depth in (({"TERM": "xterm-256color"}, COLOR_256), ({"COLORTERM": "truecolor"}, TRUECOLOR)):
            with self.subTest(depth):
                self.start(environ=environ)
                self.paste()
                self.hermes.respond("image.render", unicode_result())
                (preview,) = self.app.previews.values()
                self.assertEqual({span.style.depth for line in preview.lines for span in line}, {depth})
                self.send()
                drawn(self.app)
                written = "".join(self.app.terminal.writes)  # type: ignore[attr-defined]
                cell = written[: written.index(UPPER_HALF * 3)]
                sgr = cell[cell.rindex("\x1b[") :]
                if depth == COLOR_256:
                    self.assertIn("38;5;", sgr)
                    self.assertIn("48;5;", sgr)
                    self.assertNotIn("38;2;", sgr)
                else:
                    self.assertIn("38;2;255;0;0", sgr)

    def test_only_the_newest_previews_are_kept(self) -> None:
        self.start()
        for _ in range(34):
            self.paste()
        for _ in range(34):
            self.hermes.respond("image.render", unicode_result())
        self.assertEqual(len(self.app.previews), 32)
        self.assertNotIn("[Image #1]", self.app.previews)
        self.assertIn("[Image #34]", self.app.previews)


class EchoWaitTests(PreviewTestCase):
    """The echo of a prompt sent with an image is printed once its preview answers, or `PREVIEW_WAIT_SECONDS` on."""

    def test_paste_enter_then_a_frame_then_the_answer_prints_the_echo_with_its_preview(self) -> None:
        self.start()
        self.paste()
        self.send()
        self.hermes.admit()
        drawn(self.app)  # a frame before Hermes rendered it: the echo is not printed yet
        self.hermes.respond("image.render", unicode_result())
        (user,) = self.users()
        self.assertEqual([preview.rows for preview in user.previews], [2])
        mark = len(self.app.terminal.writes)  # type: ignore[attr-defined]
        drawn(self.app)
        printed = "".join(self.app.terminal.writes[mark:])  # type: ignore[attr-defined]
        self.assertIn("[Image #1] image_1.png", printed)
        self.assertIn(UPPER_HALF * 3, printed)
        self.assertFalse(user.waiting)

    def test_with_no_answer_the_echo_prints_after_the_wait_with_its_caption_and_what_followed_after_it(self) -> None:
        self.start()
        self.paste()
        self.send("first")
        self.hermes.admit()
        self.app._on_event(Event("message.delta", SID, {"text": "a reply"}))
        self.app._on_event(Event("message.complete", SID, {"text": "a reply"}))
        self.step(PREVIEW_WAIT_SECONDS / 2)
        self.assertTrue(self.users()[-1].waiting)  # half the wait: still held, and the reply with it
        self.step(PREVIEW_WAIT_SECONDS / 2)
        self.assertFalse(self.users()[-1].waiting)
        self.assertEqual(self.app.preview_waits, [])
        screen = "\n".join(drawn(self.app))
        self.assertLess(screen.index("[Image #1] image_1.png"), screen.index("a reply"))
        self.assertEqual(self.users()[-1].previews, (None,))

    def test_a_refusal_lets_the_echo_print_at_once(self) -> None:
        self.start()
        self.paste()
        self.send()
        self.assertTrue(self.users()[-1].waiting)
        self.hermes.respond("image.render", error={"code": contract.METHOD_NOT_FOUND, "message": "unknown method"})
        self.assertFalse(self.users()[-1].waiting)
        self.assertEqual(self.app.preview_waits, [])

    def test_an_echo_whose_preview_answered_first_does_not_wait(self) -> None:
        self.start()
        self.paste()
        self.hermes.respond("image.render", unicode_result())
        self.send()
        self.assertFalse(self.users()[-1].waiting)

    def test_flush_rule_stays_in_the_transcript(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src/tui/app.py").read_text(encoding="utf-8")
        self.assertNotIn("transcript._cursor", source)
        self.assertNotIn("transcript._version", source)


class AlternateScreenTests(PreviewTestCase):
    """kitty keeps one image store per screen: a transmit goes only to the main one, where the placeholders are."""

    def test_an_answer_while_the_pager_is_open_is_written_once_after_it_closes(self) -> None:
        self.start(environ=KITTY)
        self.paste()
        self.app._open_pager("history", [()])
        self.hermes.respond("image.render", kitty_result())
        self.assertEqual((self.transmits(), self.app.inline_placed), ([], set()))
        self.app._leave_pager()
        self.assertEqual(self.transmits(), [kitty_result()["transmit"]])
        self.assertEqual(self.app.inline_placed, {IMAGE_ID})
        self.paste()
        self.hermes.respond("image.render", kitty_result())  # the same image again: already on the main screen
        self.assertEqual(len(self.transmits()), 1)

    def test_an_answer_while_the_model_chains_picker_is_open_waits_for_it_to_close(self) -> None:
        self.start(environ=KITTY)
        self.paste()
        self.app.chains_open = True
        self.hermes.respond("image.render", kitty_result())
        self.assertEqual(self.transmits(), [])
        self.app.chains_open = False
        self.app._write_owed_transmits()
        self.assertEqual(len(self.transmits()), 1)

    def test_history_shows_a_kitty_preview_as_its_caption_only(self) -> None:
        self.start(environ=KITTY)
        self.paste()
        self.hermes.respond("image.render", kitty_result())
        self.send()
        self.hermes.admit()
        drawn(self.app)
        mark = len(self.app.terminal.writes)  # type: ignore[attr-defined]
        self.app._history("")
        drawn(self.app)
        shown = "".join(self.app.terminal.writes[mark:])  # type: ignore[attr-defined]
        self.assertIn("[Image #1] image_1.png", shown)
        self.assertNotIn(PLACEHOLDER, shown)

    def test_history_still_shows_a_half_block_preview(self) -> None:
        self.start()
        self.paste()
        self.hermes.respond("image.render", unicode_result())
        self.send()
        self.hermes.admit()
        drawn(self.app)
        mark = len(self.app.terminal.writes)  # type: ignore[attr-defined]
        self.app._history("")
        drawn(self.app)
        self.assertIn(UPPER_HALF * 3, "".join(self.app.terminal.writes[mark:]))  # type: ignore[attr-defined]


class CaptionTests(unittest.TestCase):
    def test_the_caption_names_the_file_its_size_and_its_kilobytes(self) -> None:
        image = Attachment("/h/shot.png", "shot.png", "1280×720", "[Image #3]", b"x" * 86016)
        self.assertEqual(image_caption(image), "[Image #3] shot.png · 1280×720 · 84 KB")
        unsized = Attachment("/h/shot.png", "shot.png", "", "[Image #3]", b"x" * 10)
        self.assertEqual(image_caption(unsized), "[Image #3] shot.png · 1 KB")


if __name__ == "__main__":
    unittest.main()
