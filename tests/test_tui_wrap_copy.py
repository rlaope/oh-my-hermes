"""A drag over rows the OMH TUI wrapped copies the line as it was written (the owner's request of 2026-11-11, "a long
command copies as five lines with the left bar in it").

The TUI wraps a reply to the screen's width, so one long command or path is
drawn over several rows. Each row after the first carries an empty mark
(`style.wrap_mark`) saying how it goes on from the row above: after spaces the
wrap dropped, inside a word too long for a row, or in code, whose spaces stay
on the rows. A drag on the main screen (the default since 2026-11-11) joins
those rows again, with one space, with nothing, or as they are, and leaves out
the rail as before; a line break the text itself had stays a line break.
"""

from __future__ import annotations

import unittest

from test_tui_clean_copy import osc52, row_of
from test_tui_main_mouse import CTRL_L, drag
from test_tui_modes import drawn, make_app
from omh.tui.app import App
from omh.tui.markdown import render_markdown
from omh.tui.pager import Selection
from omh.tui.screen import paint_line
from omh.tui.style import WRAP_CUT, WRAP_SPACE, WRAP_VERBATIM, Line, wrap_of
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import AssistantBlock

COMMAND = ("~/.hermes/hermes-agent/venv/bin/python ~/.hermes/profiles/omh-tui/cache/scratch/otty_kitty_probe.py "
           "~/.hermes/profiles/omh-tui/cache/documents/native-inputs/"
           "60733e12c74bcd0f0732eb78f7943a26f5bdb2ccb081d87f5cc2f84e9246a1fa/upload_qjcf8wv1.png")
KITTY = {"TERM": "xterm-kitty"}  # a copy goes out as OSC 52, which the VT screen keeps


def reply_app(reply: str, cols: int = 60, environ: dict[str, str] | None = None) -> App:
    """`reply` on the main screen at `cols`, redrawn from the top row so the region's place is certain; the
    default mouse setting unless `environ` names one."""
    app, _client = make_app(rows=24, cols=cols, environ={**KITTY, **(environ or {})})
    app.environ = {key: value for key, value in app.environ.items()
                   if key != "OMH_TUI_MOUSE" or "OMH_TUI_MOUSE" in (environ or {})}
    app.platform = "linux"
    app.pbcopy = lambda text: False  # type: ignore[method-assign]  # never the real clipboard
    app.transcript.add_user("show me")
    app.transcript.blocks.append(AssistantBlock(reply, model="m"))
    app._on_input(CTRL_L)
    drawn(app)
    return app


def drag_rows(app: App, first: str, last: str) -> str:
    """Drag from the rail of the row showing `first` to the end of the row showing `last`; what was copied."""
    drag(app, (1, row_of(app, first)), (app.size[0], row_of(app, last)))
    sent = osc52(app)
    return sent[-1] if sent else ""


def copied(rows: list[Line]) -> str:
    """What a drag over every one of `rows` copies (the pager's and the main screen's `Selection`)."""
    selection = Selection()
    selection.press((0, 0), 0.0, lambda row: rows[row])
    selection.move((len(rows) - 1, 10_000))
    return selection.release(1.0, lambda row: rows[row])


class MainScreenDragTests(unittest.TestCase):
    def test_the_default_drag_copies_a_wrapped_command_as_one_line_without_the_rail(self) -> None:
        app = reply_app(f"Run this:\n\n{COMMAND}\n\nThen tell me.")
        screen = [line for line in app.terminal.screen.lines() if line.strip()]  # type: ignore[attr-defined]
        self.assertGreater(sum("hermes" in line or "60733e" in line or "upload" in line for line in screen), 2)
        self.assertEqual(drag_rows(app, "Run this", "Then tell me"), f"Run this:\n\n{COMMAND}\n\nThen tell me.")

    def test_a_drag_over_wrapped_prose_puts_back_the_space_the_wrap_dropped(self) -> None:
        prose = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
        app = reply_app(prose, cols=40)
        self.assertEqual(drag_rows(app, "one two", "sixteen"), prose)

    def test_a_word_cut_inside_is_joined_with_nothing(self) -> None:
        word = "x" * 90
        app = reply_app(word, cols=40)
        self.assertEqual(drag_rows(app, "xxxx", "xxxx"), word[:app.size[0] - 4])  # one row only
        drag(app, (1, row_of(app, "xxxx")), (app.size[0], row_of(app, "xxxx") + 2))
        self.assertEqual(osc52(app)[-1], word)

    def test_a_line_break_the_text_had_stays(self) -> None:
        app = reply_app("first line\nsecond line")
        self.assertEqual(drag_rows(app, "first line", "second line"), "first line\nsecond line")

    def test_with_zero_the_terminal_keeps_the_drag_and_the_tui_copies_nothing(self) -> None:
        app = reply_app(COMMAND, environ={"OMH_TUI_MOUSE": "0"})
        self.assertFalse(app._takes_mouse())
        self.assertEqual(drag_rows(app, "~/.hermes", "upload"), "")


class SelectionJoinTests(unittest.TestCase):
    def test_the_marks_say_how_each_row_goes_on(self) -> None:
        rows = render_markdown("aaaa bbbb cccc " + "y" * 30, 10, DEFAULT_THEME)
        self.assertEqual([wrap_of(row) for row in rows], [None, WRAP_SPACE, WRAP_SPACE, WRAP_CUT, WRAP_CUT])
        self.assertEqual(copied(rows), "aaaa bbbb cccc " + "y" * 30)

    def test_code_keeps_its_spaces_where_the_row_broke(self) -> None:
        line = "echo   a    b    c    d    e    f"
        rows = render_markdown(f"```\n{line}\n```", 8, DEFAULT_THEME)
        self.assertEqual({wrap_of(row) for row in rows[1:]}, {WRAP_VERBATIM})
        self.assertEqual(copied(rows), line)

    def test_a_drag_that_starts_on_a_wrapped_row_starts_there(self) -> None:
        rows = render_markdown("aaaa bbbb cccc dddd", 10, DEFAULT_THEME)
        selection = Selection()
        selection.press((1, 0), 0.0, lambda row: rows[row])
        selection.move((len(rows) - 1, 10_000))
        self.assertEqual(selection.release(1.0, lambda row: rows[row]), "cccc dddd")

    def test_the_mark_paints_nothing(self) -> None:
        rows = render_markdown("aaaa bbbb cccc", 6, DEFAULT_THEME)
        self.assertEqual(wrap_of(rows[1]), WRAP_SPACE)
        self.assertEqual(paint_line(rows[1], 6), paint_line(tuple(span for span in rows[1] if span.text), 6))


if __name__ == "__main__":
    unittest.main()
