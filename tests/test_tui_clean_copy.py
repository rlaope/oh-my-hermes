"""What a selection copies: the rail on the main screen, and the pager's own drag to copy without it (the owner's
request of 2026-10-28, "the blue line on the left gets copied with the text").

On the main screen the transcript lives in the terminal's own scrollback, and
the terminal's own selection (its bypass modifier, or `OMH_TUI_MOUSE=0`) copies
it, rail and all; the OMH TUI's own drag there copies without it
(`tests/test_tui_main_mouse.py`). The rail a block hangs on
is the thin `┃` in its colour (the owner's choice of 2026-10-30, after the
painted full cell of #2371 read too heavy), and without colour your prompt's is
the light `│`. The pager (alternate screen) takes the mouse with a held
button's motion: a drag selects, its release copies the text without the rail
or a reply's margin, and the footer says what the copy did.
"""

from __future__ import annotations

import base64
import subprocess
import unittest
from unittest.mock import patch

from _tui_lines import line_text
from _vt_screen import VTScreen
from test_tui_bot_board import NOW, FixtureRoot, snapshot
from test_tui_modes import drawn, make_app
from omh.tui.app import COPY_NOTE_SECONDS, App
from omh.tui import clipboard
from omh.tui.bot_board import BotBoard
from omh.tui.clipboard import (
    COPY_OSC52,
    COPY_PBCOPY,
    COPY_UNCONFIRMED,
    PBCOPY_SECONDS,
    TMUX_QUERY_SECONDS,
    copy_route,
    pbcopy,
    tmux_client_over_ssh,
)
from omh.tui.keys import BUTTON_LEFT, CHAR, WHEEL_DOWN, WHEEL_UP, Key, Mouse
from omh.tui.pager import FOOTER_KEYS, WHEEL_LINES, Pager
from omh.tui.screen import paint_line
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_LAUNCH, DEFAULT_THEME, build_theme, on_band, with_prompt_band, without_colour
from omh.tui.transcript import (
    NOTICE_ERROR,
    NOTICE_OK,
    NOTICE_WARN,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_RUNNING,
    AssistantBlock,
    CommandBlock,
    NoticeBlock,
    SteerBlock,
    ThinkingBlock,
    ToolGroup,
    ToolRow,
    TurnSummaryBlock,
    UserBlock,
    block_rows,
)
from omh.skin_pack import SKIN_THEMES

# Every glyph a terminal could draw as a bar beside the text: the rail's `┃`, its light `│` and their kin.
BAR_GLYPHS = set("┃│▎▍▌▋▏▕▐┆┊╎║█")
# The blocks that hang on a rail; a steer reads as the prompt it is (a refused one, an amber row, does not).
RAILED = (UserBlock, CommandBlock, AssistantBlock, ToolGroup, SteerBlock)
REPLY = "first line of the reply\nsecond line"
KITTY = {"TERM": "xterm-kitty"}


def every_block() -> list[object]:
    command = CommandBlock("/model", done=True)
    command.parts = [("switched", NOTICE_OK), ("a warning", NOTICE_WARN), ("it failed", NOTICE_ERROR)]
    return [
        UserBlock("a prompt\nits second line"),
        UserBlock("/omh-docs write it", known=frozenset({"omh-docs"})),
        command,
        AssistantBlock("**hello** there\n\n```sh\nls\n```"),
        ToolGroup([ToolRow("a", "terminal", "ls", TOOL_RUNNING), ToolRow("b", "read_file", "a.py", TOOL_OK),
                   ToolRow("c", "terminal", "pytest", TOOL_ERROR, output=("1 failed",))], done=True),
        NoticeBlock("a notice", NOTICE_WARN),
        NoticeBlock("allowed", NOTICE_OK),
        SteerBlock("go left"),
        ThinkingBlock("thinking about it", done=True),
        TurnSummaryBlock(34.0, 3, 1200),
    ]


def themes() -> list[tuple[str, object]]:
    banded = with_prompt_band(build_theme(SKIN_THEMES[0], "#1E1E1E"), SKIN_THEMES[0], "#1E1E1E", DEFAULT_LAUNCH)
    return [("default", DEFAULT_THEME), ("prompt band", banded), ("NO_COLOR", without_colour(DEFAULT_THEME))]


class BarOnTheMainScreenTests(unittest.TestCase):
    def test_a_railed_blocks_rows_draw_the_bar_in_their_first_cell_and_nowhere_else(self) -> None:
        for name, theme in themes():
            for block in every_block():
                for expanded in (False, True):
                    with self.subTest(theme=name, block=type(block).__name__, expanded=expanded):
                        rows = block_rows(block, 60, theme, expanded=expanded)
                        self.assertTrue(rows)
                        screen = VTScreen(len(rows) + 1, 60)
                        screen.feed("\r\n".join(paint_line(row, 60) for row in rows))
                        bars = {(at, column) for at, line in enumerate(screen.lines())
                                for column, glyph in enumerate(line) if glyph in BAR_GLYPHS}
                        if not isinstance(block, RAILED):
                            self.assertEqual(bars, set(), screen.lines())
                            continue
                        light = name == "NO_COLOR" and isinstance(block, (UserBlock, CommandBlock, SteerBlock))
                        railed = [at for at, row in enumerate(rows) if row]  # the blank rows between two calls have none
                        self.assertEqual(bars, {(at, 0) for at in railed}, screen.lines())
                        for at in railed:
                            self.assertEqual(rows[at][0].text, "│" if light else "┃")
                            self.assertEqual((rows[at][0].style.gutter, rows[at][0].style.reverse), (True, False))

    def test_the_rail_is_a_thin_bar_in_its_colour(self) -> None:
        for name, theme in themes()[:2]:  # NO_COLOR: `test_without_colour_your_prompts_rail_is_the_light_bar`
            with self.subTest(theme=name):
                (row, *_rest) = block_rows(UserBlock("hi"), 40, theme)
                self.assertEqual((row[0].text, row[1].text), ("┃", " "))
                self.assertFalse(row[0].style.reverse)
                roles = on_band(theme, theme.prompt_band) if theme.prompt_band.bg is not None else theme
                self.assertEqual(row[0].style.fg, roles.dim.fg)  # the prompt's grey, measured against its band
                screen = VTScreen(2, 40)
                screen.feed(paint_line(row, 40))
                grey = tuple(int(roles.dim.fg[at:at + 2], 16) for at in (1, 3, 5))
                self.assertEqual(screen.attrs_at(0, 0)[:5], (38, 2, *grey))  # the bar in its colour (on any band)
                self.assertNotIn(7, screen.attrs_at(0, 0))  # not a painted cell
                self.assertEqual(screen.line(0), "┃ ❯ hi")  # what a terminal's selection copies: the bar too

    def test_each_rail_keeps_its_blocks_colour(self) -> None:
        theme = DEFAULT_THEME
        reply = block_rows(AssistantBlock("ok"), 40, theme)
        call = block_rows(ToolGroup([ToolRow("a", "terminal", "ls", TOOL_ERROR)], done=True), 40, theme)
        self.assertEqual({row[0].style.fg for row in reply}, {theme.brand.fg})
        self.assertEqual({row[0].style.fg for row in call}, {theme.error.fg})


def reply_app(environ: dict[str, str] | None = None, platform: str = "linux") -> tuple[App, list[str]]:
    """An app with a prompt and a reply, the history pager open on them; what `pbcopy` was handed."""
    app, _client = make_app(rows=12, cols=60, environ=environ or {})
    app.platform = platform
    copied: list[str] = []
    app.pbcopy = lambda text: copied.append(text) is None  # type: ignore[method-assign]  # never the real clipboard
    app.transcript.add_user("explain it")
    app.transcript.blocks.append(AssistantBlock(REPLY, model="deepseek-v4.1-flash"))
    app._history("")
    drawn(app)
    return app, copied


def row_of(app: App, text: str) -> int:
    """The 1-based screen row showing `text`, as a report counts it."""
    return next(index for index, line in enumerate(app.terminal.screen.lines()) if text in line) + 1  # type: ignore[attr-defined]


def drag(app: App, start: tuple[int, int], end: tuple[int, int]) -> None:
    """A left press at `start`, the held button's motion to `end`, and the release there; (x, y) from 1."""
    app._on_input(Mouse(BUTTON_LEFT, *start))
    app._on_input(Mouse(BUTTON_LEFT, *end, motion=True))
    app._on_input(Mouse(BUTTON_LEFT, *end, pressed=False))


def osc52(app: App) -> list[str]:
    """What each OSC 52 the app wrote put on the clipboard."""
    sent = [text.removeprefix("52;c;") for text in app.terminal.screen.osc if text.startswith("52;c;")]  # type: ignore[attr-defined]
    return [base64.b64decode(text.rstrip("\x07")).decode("utf-8") for text in sent]


class PagerDragTests(unittest.TestCase):
    def test_a_drag_copies_the_text_without_the_rail_or_the_margin_through_osc52(self) -> None:
        app, copied = reply_app(KITTY)
        first, second = row_of(app, "first line"), row_of(app, "second line")
        drag(app, (1, first), (60, second))  # from the rail's own cell to the row's far end
        self.assertEqual(osc52(app), [REPLY])
        self.assertEqual(copied, [])
        footer = drawn(app)[-1]
        self.assertEqual(footer, f"✓ copied {len(REPLY)} chars to clipboard")

    def test_a_drag_from_mid_row_copies_from_there(self) -> None:
        app, _copied = reply_app(KITTY)
        y = row_of(app, "first line")
        x = app.terminal.screen.line(y - 1).index("line of") + 1  # type: ignore[attr-defined]
        drag(app, (x, y), (x + len("line of") - 1, y))
        self.assertEqual(osc52(app), ["line of"])

    def test_the_selection_is_drawn_reversed_while_it_is_made(self) -> None:
        app, _copied = reply_app(KITTY)
        y = row_of(app, "first line")
        x = app.terminal.screen.line(y - 1).index("first") + 1  # type: ignore[attr-defined]
        app._on_input(Mouse(BUTTON_LEFT, x, y))
        app._on_input(Mouse(BUTTON_LEFT, x + 4, y, motion=True))
        drawn(app)
        screen = app.terminal.screen  # type: ignore[attr-defined]
        self.assertEqual([7 in screen.attrs_at(y - 1, x - 1 + at) for at in range(6)], [True] * 5 + [False])
        self.assertEqual(osc52(app), [])  # nothing copied before the release

    def test_the_highlight_leaves_the_rail_and_the_margin_as_they_are(self) -> None:
        app, _copied = reply_app(KITTY)
        first, second = row_of(app, "first line"), row_of(app, "second line")
        app._on_input(Mouse(BUTTON_LEFT, 1, first))
        app._on_input(Mouse(BUTTON_LEFT, 60, second, motion=True))
        drawn(app)
        screen = app.terminal.screen  # type: ignore[attr-defined]
        self.assertEqual(screen.line(first - 1)[0], "┃")
        self.assertNotIn(7, screen.attrs_at(first - 1, 0))  # the rail's bar shows as it always does, not highlighted
        self.assertEqual([7 in screen.attrs_at(first - 1, column) for column in range(1, 5)], [False] * 3 + [True])

    def test_a_double_click_copies_a_word_and_a_triple_click_the_row(self) -> None:
        now = [100.0]
        app, _client = make_app(rows=12, cols=60, environ=KITTY, clock=lambda: now[0])
        app.transcript.blocks.append(AssistantBlock("run omh-docs/api.md now"))
        app._history("")
        drawn(app)
        y = row_of(app, "omh-docs")
        x = app.terminal.screen.line(y - 1).index("docs") + 1  # type: ignore[attr-defined]
        for _ in range(3):
            app._on_input(Mouse(BUTTON_LEFT, x, y))
            app._on_input(Mouse(BUTTON_LEFT, x, y, pressed=False))
            now[0] += 0.1
        self.assertEqual(osc52(app), ["omh-docs/api.md", "run omh-docs/api.md now"])

    def test_a_plain_click_copies_nothing(self) -> None:
        app, _copied = reply_app(KITTY)
        y = row_of(app, "first line")
        app._on_input(Mouse(BUTTON_LEFT, 8, y))
        app._on_input(Mouse(BUTTON_LEFT, 8, y, pressed=False))
        self.assertEqual(osc52(app), [])
        self.assertIn(FOOTER_KEYS[:20], drawn(app)[-1])

    def test_the_notice_goes_after_a_while_and_the_keys_come_back(self) -> None:
        now = [100.0]
        app, _client = make_app(rows=12, cols=60, environ=KITTY, clock=lambda: now[0])
        app.transcript.blocks.append(AssistantBlock(REPLY))
        app._history("")
        drawn(app)
        drag(app, (1, row_of(app, "first line")), (60, row_of(app, "second line")))
        self.assertIn("copied", drawn(app)[-1])
        self.assertEqual(app._read_timeout() <= COPY_NOTE_SECONDS, True)  # the loop wakes to take it off
        now[0] += COPY_NOTE_SECONDS
        app._expire_notification()
        self.assertIn(FOOTER_KEYS[:20], drawn(app)[-1])

    def test_a_copy_nothing_confirms_says_it_was_sent(self) -> None:
        for environ, why in (({"TERM": "xterm-256color"}, "terminal may not support OSC 52"),
                             ({"TERM": "tmux-256color", "TMUX": "/tmp/tmux-501/default,1,0"},
                              "tmux passes it on only with set-clipboard on")):
            with self.subTest(environ=environ):
                app, copied = reply_app(environ, platform="linux")
                drag(app, (1, row_of(app, "first line")), (60, row_of(app, "first line")))
                self.assertEqual(osc52(app), ["first line of the reply"])
                self.assertEqual(copied, [])
                self.assertEqual(drawn(app)[-1], f"⚠ copy sent ({why})")

    def test_on_a_local_mac_a_terminal_that_ignores_osc52_gets_pbcopy(self) -> None:
        app, copied = reply_app({"TERM_PROGRAM": "Apple_Terminal"}, platform="darwin")
        drag(app, (1, row_of(app, "first line")), (60, row_of(app, "first line")))
        self.assertEqual((copied, osc52(app)), (["first line of the reply"], []))
        self.assertEqual(drawn(app)[-1], "✓ copied 23 chars to clipboard")

    def test_a_pbcopy_that_fails_falls_back_to_osc52_and_says_it_was_sent(self) -> None:
        app, _copied = reply_app({"TERM_PROGRAM": "Apple_Terminal"}, platform="darwin")
        app.pbcopy = lambda text: False  # type: ignore[method-assign]
        drag(app, (1, row_of(app, "first line")), (60, row_of(app, "first line")))
        self.assertEqual(osc52(app), ["first line of the reply"])
        self.assertEqual(drawn(app)[-1], "⚠ copy sent (terminal may not support OSC 52)")

    def test_a_key_lets_the_selection_go(self) -> None:
        app, _copied = reply_app(KITTY)
        y = row_of(app, "first line")
        app._on_input(Mouse(BUTTON_LEFT, 5, y))
        app._on_input(Mouse(BUTTON_LEFT, 12, y, motion=True))
        app._on_input(Key(CHAR, "k"))
        app._on_input(Mouse(BUTTON_LEFT, 12, y, pressed=False))
        self.assertEqual(osc52(app), [])
        drawn(app)
        self.assertNotIn(7, app.terminal.screen.attrs_at(y - 1, 6))  # type: ignore[attr-defined]


class CopyRouteTests(unittest.TestCase):
    def test_which_way_a_copy_goes(self) -> None:
        cases = [
            ({"TERM": "xterm-kitty"}, "darwin", COPY_OSC52),
            ({"TERM": "xterm-ghostty", "TERM_PROGRAM": "ghostty"}, "darwin", COPY_OSC52),
            ({"TERM_PROGRAM": "WezTerm"}, "linux", COPY_OSC52),
            ({"TERM": "xterm-kitty", "TMUX": "/tmp/t,1,0"}, "linux", COPY_UNCONFIRMED),  # tmux may not pass it on
            ({"TERM_PROGRAM": "Apple_Terminal"}, "darwin", COPY_PBCOPY),
            ({"TERM_PROGRAM": "iTerm.app"}, "darwin", COPY_PBCOPY),  # its OSC 52 waits on a preference
            ({"TERM_PROGRAM": "tmux", "TMUX": "/tmp/t,1,0"}, "darwin", COPY_PBCOPY),
            ({"TERM_PROGRAM": "iTerm.app", "SSH_CONNECTION": "10.0.0.2 5 10.0.0.1 22"}, "darwin", COPY_UNCONFIRMED),
            ({"TERM": "xterm-256color"}, "linux", COPY_UNCONFIRMED),
        ]
        for environ, platform, route in cases:
            with self.subTest(environ=environ, platform=platform):
                self.assertEqual(copy_route(environ, platform, lambda environ: False), route)  # tmux: a local client

    def test_inside_tmux_pbcopy_waits_for_tmux_to_say_its_client_is_local(self) -> None:
        asked: list[dict] = []

        def over_ssh(answer: bool):
            return lambda environ: asked.append(dict(environ)) is None and answer

        tmux = {"TERM_PROGRAM": "tmux", "TMUX": "/tmp/t,1,0"}
        self.assertEqual(copy_route(tmux, "darwin", over_ssh(True)), COPY_UNCONFIRMED)  # attached later over SSH
        self.assertEqual(copy_route(tmux, "darwin", over_ssh(False)), COPY_PBCOPY)
        self.assertEqual(len(asked), 2)
        for environ, platform in (({"TERM_PROGRAM": "Apple_Terminal"}, "darwin"), (tmux, "linux")):
            copy_route(environ, platform, over_ssh(False))
        self.assertEqual(len(asked), 2)  # asked only on a Mac, only inside tmux

    def test_the_tmux_question_is_fixed_bounded_and_counts_anything_unclear_as_remote(self) -> None:
        def answering(code: int, out: str = "", err: str = ""):
            return lambda argv, **options: (calls.append((argv, options)),
                                            subprocess.CompletedProcess(argv, code, out, err))[1]

        cases = [
            (answering(0, "-SSH_CONNECTION\n"), False),  # a client removed it: the last one is local
            (answering(1, "", "unknown variable: SSH_CONNECTION\n"), False),  # the session never had it
            (answering(0, "SSH_CONNECTION=10.0.0.2 5 10.0.0.1 22\n"), True),
            (answering(1, "", "error connecting to /tmp/t (No such file or directory)\n"), True),
        ]
        for run, remote in cases:
            calls: list = []
            with self.subTest(remote=remote), patch.object(clipboard.subprocess, "run", run):
                self.assertEqual(tmux_client_over_ssh({"TMUX": "/tmp/t,1,0"}), remote)
                (argv, options), = calls
                self.assertEqual(argv, ["tmux", "show-environment", "SSH_CONNECTION"])
                self.assertEqual(options["timeout"], TMUX_QUERY_SECONDS)
        for error in (subprocess.TimeoutExpired(["tmux"], 1.0), OSError("no tmux")):
            with self.subTest(error=type(error).__name__), patch.object(clipboard.subprocess, "run", side_effect=error):
                self.assertTrue(tmux_client_over_ssh({"TMUX": "/tmp/t,1,0"}))

    def test_pbcopy_reads_utf8_and_gives_up_in_time(self) -> None:
        calls: list = []

        def run(argv, **options):
            calls.append((argv, options))
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(clipboard.subprocess, "run", run):
            self.assertTrue(pbcopy("한글 copy", {"PATH": "/usr/bin", "LANG": "C"}))
        ((argv, options),) = calls
        self.assertEqual(argv, ["pbcopy"])
        self.assertEqual(options["input"], "한글 copy".encode("utf-8"))
        self.assertEqual(options["env"]["LC_ALL"], "en_US.UTF-8")  # else pbcopy reads Korean as MacRoman
        self.assertEqual(options["timeout"], PBCOPY_SECONDS)
        for error in (subprocess.TimeoutExpired(["pbcopy"], PBCOPY_SECONDS), OSError("no pbcopy")):
            with self.subTest(error=type(error).__name__), patch.object(clipboard.subprocess, "run", side_effect=error):
                self.assertFalse(pbcopy("x", {}))


class PagerWheelTests(unittest.TestCase):
    def test_the_wheel_scrolls_the_pager_its_reports_now_reach(self) -> None:
        pager = Pager("log", [(Span(f"row {index}"),) for index in range(40)])
        pager.frame(30, 10, DEFAULT_THEME)
        self.assertEqual(pager.handle_mouse(Mouse(WHEEL_DOWN, 5, 5), 10, 0.0), "")
        self.assertEqual(pager.top, WHEEL_LINES)
        pager.handle_mouse(Mouse(WHEEL_DOWN, 5, 5), 10, 0.0)
        pager.handle_mouse(Mouse(WHEEL_UP, 5, 5), 10, 0.0)
        self.assertEqual(pager.top, WHEEL_LINES)
        for _ in range(20):
            pager.handle_mouse(Mouse(WHEEL_DOWN, 5, 5), 10, 0.0)
        self.assertEqual(pager.top, 40 - 9)  # no further than the last page

    def test_in_the_app_the_wheel_scrolls_the_history_pager(self) -> None:
        app, _client = make_app(rows=12, cols=60)
        for index in range(30):
            app.transcript.add_notice(f"notice {index}")
        app._history("")
        top = drawn(app)[0]
        app._on_input(Mouse(WHEEL_DOWN, 10, 3))
        self.assertNotEqual(drawn(app)[0], top)
        app._on_input(Mouse(WHEEL_UP, 10, 3))
        self.assertEqual(drawn(app)[0], top)
        self.assertTrue(app.terminal.mouse_drag)  # type: ignore[attr-defined]

    def test_the_wheel_lets_a_finished_selection_go(self) -> None:
        pager = Pager("log", [(Span(f"row {index}"),) for index in range(40)])
        pager.frame(30, 10, DEFAULT_THEME)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 1, 2), 10, 0.0)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 5, 3, motion=True), 10, 0.0)
        self.assertEqual(pager.handle_mouse(Mouse(BUTTON_LEFT, 5, 3, pressed=False), 10, 0.0), "row 1\nrow 2")
        pager.handle_mouse(Mouse(WHEEL_DOWN, 5, 3), 10, 0.0)
        self.assertEqual((pager.top, pager._span_on(1)), (WHEEL_LINES, None))

    def test_the_wheel_does_nothing_while_a_drag_is_under_way(self) -> None:
        # A trackpad's inertia keeps sending wheel reports for about a second after a scroll.
        pager = Pager("log", [(Span(f"row {index}"),) for index in range(40)])
        pager.frame(30, 10, DEFAULT_THEME)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 1, 2), 10, 0.0)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 5, 3, motion=True), 10, 0.1)
        pager.handle_mouse(Mouse(WHEEL_DOWN, 5, 3), 10, 0.2)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 5, 4, motion=True), 10, 0.3)
        self.assertEqual(pager.handle_mouse(Mouse(BUTTON_LEFT, 5, 4, pressed=False), 10, 0.4), "row 1\nrow 2\nrow 3")
        self.assertEqual(pager.top, 0)

    def test_rows_of_blocks_lose_their_gutter_in_the_copy(self) -> None:
        rows = block_rows(UserBlock("hello\nthere"), 40, DEFAULT_THEME)
        pager = Pager("log", rows)
        pager.frame(40, 6, DEFAULT_THEME)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 1, 1), 6, 0.0)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 40, 2, motion=True), 6, 0.0)
        copied = pager.handle_mouse(Mouse(BUTTON_LEFT, 40, 2, pressed=False), 6, 0.0)
        self.assertEqual(copied, "❯ hello\n  there")  # the prompt's mark stays; the rail's two cells do not
        self.assertEqual([line_text(row) for row in rows], ["┃ ❯ hello", "┃   there"])


class SecondDragTests(unittest.TestCase):
    """A second drag from the cell the last one started on is a drag, not a double click (#2371 review)."""

    def test_two_drags_from_one_cell_in_quick_succession_both_copy_their_range(self) -> None:
        now = [100.0]
        app, _client = make_app(rows=12, cols=60, environ=KITTY, clock=lambda: now[0])
        app.transcript.blocks.append(AssistantBlock(REPLY))
        app._history("")
        drawn(app)
        first, second = row_of(app, "first line"), row_of(app, "second line")
        for start in ((1, first), (5, first)):  # from the rail's cell, then from a text cell
            for _ in range(2):
                drag(app, start, (60, second))
                now[0] += 0.3
        self.assertEqual(osc52(app), [REPLY, REPLY, REPLY, REPLY])

    def test_a_double_click_counts_only_after_a_plain_click_and_from_its_release(self) -> None:
        pager = Pager("log", [(Span("alpha bravo"),), (Span("charlie"),)])
        pager.frame(30, 6, DEFAULT_THEME)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1), 6, 0.0)  # a plain click, held for 0.9 s
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1, pressed=False), 6, 0.9)
        self.assertEqual(pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1), 6, 1.2), "alpha")  # 0.3 s after the release
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1, pressed=False), 6, 1.25)
        self.assertEqual(pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1), 6, 1.3), "alpha bravo")  # the third: the row
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1, pressed=False), 6, 1.35)
        # A press that moved off its cell and came back is no click: the next press starts a drag.
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1), 6, 5.0)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 6, 2, motion=True), 6, 5.05)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1, motion=True), 6, 5.1)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1, pressed=False), 6, 5.15)
        self.assertEqual(pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1), 6, 5.2), "")


class CopiedTextTests(unittest.TestCase):
    def drag(self, pager: Pager, rows: int, start: tuple[int, int], end: tuple[int, int]) -> str:
        pager.frame(30, rows, DEFAULT_THEME)
        pager.handle_mouse(Mouse(BUTTON_LEFT, *start), rows, 0.0)
        pager.handle_mouse(Mouse(BUTTON_LEFT, *end, motion=True), rows, 0.1)
        return pager.handle_mouse(Mouse(BUTTON_LEFT, *end, pressed=False), rows, 0.2)

    def test_a_drag_past_the_content_copies_no_empty_rows_after_it(self) -> None:
        pager = Pager("log", [(Span("one"),), (Span("two"),)])
        self.assertEqual(self.drag(pager, 10, (1, 1), (30, 9)), "one\ntwo")

    def test_each_rows_trailing_spaces_are_dropped_and_its_inner_ones_kept(self) -> None:
        pager = Pager("log", [(Span("return  1   "),), (Span("  x = 2  "),)])
        self.assertEqual(self.drag(pager, 6, (1, 1), (30, 2)), "return  1\n  x = 2")

    def test_a_wide_character_is_in_from_either_of_its_cells(self) -> None:
        pager = Pager("log", [(Span("한글 text"),)])  # 한 on columns 0-1, 글 on 2-3
        self.assertEqual(self.drag(pager, 6, (2, 1), (4, 1)), "한글")  # from 한's right half to 글's right half
        pager = Pager("log", [(Span("한글 text"),)])
        pager.frame(30, 6, DEFAULT_THEME)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 2, 1), 6, 0.0)
        pager.handle_mouse(Mouse(BUTTON_LEFT, 3, 1, motion=True), 6, 0.1)
        screen = VTScreen(6, 30)
        screen.feed(pager.frame(30, 6, DEFAULT_THEME))
        self.assertEqual([7 in screen.attrs_at(0, column) for column in range(5)], [True] * 4 + [False])

    def test_a_press_under_the_page_starts_no_selection(self) -> None:
        pager = Pager("log", [(Span("one"),), (Span("two"),)])
        self.assertEqual(self.drag(pager, 6, (1, 6), (30, 1)), "")  # pressed on the footer, dragged up into the page
        self.assertIsNone(pager._span_on(0))


class NoColorRailTests(unittest.TestCase):
    def test_without_colour_your_prompts_rail_is_the_light_bar(self) -> None:
        # With colour every rail is the thin `┃` in its own colour; without, the prompt's would look the same as a
        # reply's, so it is the light `│` (its `❯` marks it anyway).
        call = ToolGroup([ToolRow("a", "terminal", "ls", TOOL_OK)], done=True)
        for name, theme, prompt_bar in (("NO_COLOR", without_colour(DEFAULT_THEME), "│"), ("colour", DEFAULT_THEME, "┃")):
            with self.subTest(theme=name):
                rows = [block_rows(block, 40, theme)[0] for block in
                        (UserBlock("hi"), CommandBlock("/model", done=True), AssistantBlock("ok"), call)]
                screen = VTScreen(4, 40)
                screen.feed("\r\n".join(paint_line(row, 40) for row in rows))
                self.assertEqual([screen.line(row)[:4] for row in range(4)],
                                 [f"{prompt_bar} ❯ ", f"{prompt_bar} ❯ ", "┃ ⚚ ", "┃ ● "])
                self.assertEqual([7 in screen.attrs_at(row, 0) for row in range(4)], [False] * 4)  # no cell painted
                self.assertEqual([bool(screen.attrs_at(row, 0)) for row in range(4)], [name == "colour"] * 4)


class BotBoardWheelTests(FixtureRoot):
    def test_the_wheel_scrolls_the_profile_list_and_leaves_its_highlight(self) -> None:
        board = BotBoard("bots", clock=lambda: NOW)
        board.take(snapshot(self.environ))
        board.frame(80, 8, DEFAULT_THEME)
        highlighted, top = board.profile_index, board.top
        self.assertGreater(len(board.lines), top + board.body_rows(8) + WHEEL_LINES)
        board.handle_mouse(Mouse(WHEEL_DOWN, 5, 3), 8, 0.0)
        board.frame(80, 8, DEFAULT_THEME)
        self.assertEqual((board.profile_index, board.top), (highlighted, top + WHEEL_LINES))


if __name__ == "__main__":
    unittest.main()
