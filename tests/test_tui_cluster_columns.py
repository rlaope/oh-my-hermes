"""Columns are counted by grapheme cluster wherever the TUI maps a cell to text or styles text cell by cell.

`width` paints a ZWJ family, an emoji with a skin tone, a VS16 emoji and a
flag as one 2-cell glyph and a base with its combining marks as one unit. The
pager's selection (`_cells`, `_word_at`, `_reversed`), the recall glint
(`transcript._glinted`) and the running box's aura in `/dag`
(`panels._aura_box`) counted code points instead: a double click on a word
after `👨‍👩‍👧` copied nothing, a drag copied half a family, and a style
change landed inside a cluster, which breaks the glyph on the terminal (QA
round 2026-10-28, R-B).
"""

from __future__ import annotations

import base64
import re
import time
import unicodedata
import unittest
from dataclasses import replace

from _vt_screen import VTScreen
from test_tui_bot_board import NOW, bots
from test_tui_modes import drawn, make_app
from omh.plugin_bundle.omh.delegation_view import Segment
from omh.tui import bot_board, subagents
from omh.tui.keys import BUTTON_LEFT, Mouse
from omh.tui.pager import Pager, _cells, _kept_cells, _reversed, _source_clusters, _word_at, forget_cells
from omh.tui.panels import _aura_box
from omh.tui.screen import paint_line, without_controls
from omh.tui.style import TRUECOLOR, Span, Style
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import AssistantBlock, _glinted
from omh.tui.width import TAB_CELLS, cluster_width, clusters, clusters_as_written, line_width

# One cluster each, with what a code-point count made of it.
LEADS = {
    "cjk": "한",
    "decomposed hangul": "한",  # 한 as jamo, as macOS pastes it
    "combining mark": "a̲",  # a with a combining low line: no precomposed form
    "zwj family": "👨‍👩‍👧",  # painted 2, counted 6
    "skin tone": "👍🏻",  # painted 2, counted 4
    "vs16": "☀️",  # painted 2, counted 1 or 3
    "flag": "🇰🇷",  # two regional indicators, one glyph
}
# Two Kirat Rai letters NFC writes as one (U+16D69). The script is Unicode 16: an interpreter whose unicodedata is
# older (Python 3.11 has Unicode 14) composes nothing here, so the pair is two units there and the cases that count
# on one are run only where NFC composes it. No other letter NFC composes with the one before it outside Hangul,
# which joins as a zero-width jamo anyway, so Unicode 14 has no such pair to test instead.
KIRAT_RAI = "\U00016D63\U00016D67"
KIRAT_RAI_COMPOSES = unicodedata.normalize("NFC", KIRAT_RAI) == "\U00016D69"
WHERE_KIRAT_RAI_COMPOSES = {"kirat rai": KIRAT_RAI} if KIRAT_RAI_COMPOSES else {}
LEADS.update(WHERE_KIRAT_RAI_COMPOSES)
KITTY = {"TERM": "xterm-kitty"}
# A cluster of two or more code points whose first is not in the rest of the page, for a cut to fall inside.
CUT_LEADS = {
    "zwj family": "👨\u200d👩\u200d👧",
    "skin tone": "👍🏻",
    "flag": "🇰🇷",
    "combining mark": "z\u0301",
    "decomposed hangul": "\u1112\u1161\u11ab",
    **WHERE_KIRAT_RAI_COMPOSES,
}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def text_of(line) -> str:
    return "".join(span.text for span in line)


def no_cluster_split(line) -> bool:
    """Every span boundary of `line` falls between two clusters of its text."""
    return [cluster for span in line for cluster in clusters(span.text)] == clusters(text_of(line))


def _timed(work) -> float:
    start = time.perf_counter()
    work()
    return time.perf_counter() - start


def click(pager: Pager, x: int, now: float) -> str:
    """A plain press and release on column `x` of the first row; what the press picked (a double click's word)."""
    picked = pager.handle_mouse(Mouse(BUTTON_LEFT, x, 1), 10, now)
    pager.handle_mouse(Mouse(BUTTON_LEFT, x, 1, pressed=False), 10, now + 0.01)
    return picked


def drag(pager: Pager, start: int, end: int) -> str:
    pager.handle_mouse(Mouse(BUTTON_LEFT, start, 1), 10, 0.0)
    pager.handle_mouse(Mouse(BUTTON_LEFT, end, 1, motion=True), 10, 0.1)
    return pager.handle_mouse(Mouse(BUTTON_LEFT, end, 1, pressed=False), 10, 0.2)


class PagerSelectionTests(unittest.TestCase):
    def test_a_double_click_on_a_word_after_a_cluster_copies_that_word(self) -> None:
        for name, lead in {**LEADS, "two cjk": "한글"}.items():
            with self.subTest(lead=name):
                pager = Pager("log", [(Span(f"{lead} target"),)])
                pager.frame(40, 10, DEFAULT_THEME)
                x = line_width((Span(f"{lead} "),)) + 1  # the painted column of `t`, as a report counts it
                click(pager, x, 0.0)
                self.assertEqual(click(pager, x, 0.1), "target")

    def test_a_word_of_combining_marks_is_one_word(self) -> None:
        pager = Pager("log", [(Span("x a̲b̲c̲ y"),)])
        pager.frame(40, 10, DEFAULT_THEME)
        click(pager, 4, 0.0)  # on b
        self.assertEqual(click(pager, 4, 0.1), "a̲b̲c̲")

    def test_a_drag_over_either_cell_of_a_cluster_copies_all_of_it(self) -> None:
        for name, lead in LEADS.items():
            with self.subTest(lead=name):
                width = cluster_width(nfc(lead))
                pager = Pager("log", [(Span(f"{lead} x"),)])
                pager.frame(40, 10, DEFAULT_THEME)
                self.assertEqual(drag(pager, 1, width + 1), lead)  # its cells and the space after it, as written
                pager = Pager("log", [(Span(f"{lead} x"),)])
                pager.frame(40, 10, DEFAULT_THEME)
                self.assertEqual(drag(pager, width, width + 2), f"{lead} x")  # from its last cell on

    def test_the_highlight_reverses_a_whole_cluster_and_moves_no_column(self) -> None:
        plain = Style()
        lit = replace(plain, reverse=True)
        for name, lead in LEADS.items():
            with self.subTest(lead=name):
                line = (Span(f"{lead} x"),)
                self.assertEqual(_reversed(line, 0, 0), (Span(lead, lit), Span(" x", plain)))
                pager = Pager("log", [line])
                pager.frame(40, 10, DEFAULT_THEME)
                pager.handle_mouse(Mouse(BUTTON_LEFT, 1, 1), 10, 0.0)
                pager.handle_mouse(Mouse(BUTTON_LEFT, 1, 1, motion=True), 10, 0.1)
                screen = VTScreen(10, 40)
                screen.feed(pager.frame(40, 10, DEFAULT_THEME))
                width = cluster_width(nfc(lead))
                self.assertEqual(screen.line(0), f"{nfc(lead)} x")
                self.assertEqual([7 in screen.attrs_at(0, column) for column in range(width + 2)],
                                 [True] * width + [False, False])

    def test_a_copy_hands_back_the_code_points_it_was_given_not_their_nfc_form(self) -> None:
        # A decomposed macOS path pasted into a shell or grep must match the file it names, byte for byte.
        for word in ("cafe\u0301", "\u1112\u1161\u11ab\u1100\u1173\u11af", "re\u0301sume\u0301.txt"):
            with self.subTest(word=word):
                pager = Pager("log", [(Span(f"open {word} now"),)])
                pager.frame(40, 10, DEFAULT_THEME)
                x = line_width((Span("open "),)) + 2
                click(pager, x, 0.0)
                self.assertEqual(click(pager, x, 0.1), word)
                pager = Pager("log", [(Span(f"open {word} now"),)])
                pager.frame(40, 10, DEFAULT_THEME)
                self.assertEqual(drag(pager, 1, 40), f"open {word} now")
                self.assertEqual(text_of(_reversed((Span(word),), 0, 99)), word)

    def test_the_logs_pager_copies_a_decomposed_path_as_written(self) -> None:
        now = [100.0]
        app, client = make_app(rows=12, cols=60, environ=KITTY, clock=lambda: now[0])
        app.pbcopy = lambda text: False  # type: ignore[method-assign]  # never the real clipboard
        path = "/Users/me/cafe\u0301/notes.txt"
        client.stderr_tail = lambda: [f"read {path} ok"]  # type: ignore[attr-defined]
        app._logs("")
        drawn(app)
        screen = app.terminal.screen  # type: ignore[attr-defined]
        y = next(index for index, line in enumerate(screen.lines()) if "notes" in line)
        x = screen.line(y).index("/Users") + 2
        for _ in range(2):
            app._on_input(Mouse(BUTTON_LEFT, x, y + 1))
            app._on_input(Mouse(BUTTON_LEFT, x, y + 1, pressed=False))
            now[0] += 0.1
        sent = [text.removeprefix("52;c;") for text in screen.osc if text.startswith("52;c;")]
        self.assertEqual([base64.b64decode(text.rstrip("\x07")).decode("utf-8") for text in sent], [path])

    def test_escapes_and_controls_take_no_column_and_are_never_copied(self) -> None:
        # `paint_line` drops them (`screen.without_controls`), so the pager measures and copies what it paints.
        for text, x, word in (("\x1b[31mERROR\x1b[0m: boom", 8, "boom"), ("\x9b31mred\x9b0m alert", 5, "alert"),
                              ("\x1b]8;;http://x\x07link\x1b]8;;\x07 here", 6, "here"),
                              ("👨\x01\u200d👩 x", 4, "x"), ("☀\x01\ufe0f x", 4, "x")):
            with self.subTest(text=text):
                pager = Pager("log", [(Span(text),)])
                pager.frame(40, 10, DEFAULT_THEME)
                click(pager, x, 0.0)
                self.assertEqual(click(pager, x, 0.1), word)
                line = (Span(text),)
                self.assertEqual(sum(cell.width for cell in _cells(line)), line_width(without_controls(line)))
                lit, plain = VTScreen(1, 40), VTScreen(1, 40)
                lit.feed(paint_line(_reversed(line, 0, 1), 40))
                plain.feed(paint_line(line, 40))
                self.assertEqual(lit.line(0), plain.line(0), "the highlight paints the same glyphs")

    def test_the_highlight_never_joins_two_spans_into_one_cluster(self) -> None:
        line = (Span("ab👨\u200d"), Span("👩 tail"))  # measured span by span, as `width` measures every row
        for low, high in ((0, 0), (20, 20), (2, 3), (0, 20)):
            with self.subTest(low=low, high=high):
                self.assertEqual(line_width(_reversed(line, low, high)), line_width(line))

    def test_a_zero_width_cluster_that_leads_the_row_leaves_the_word_after_it_clickable(self) -> None:
        self.assertEqual(_word_at((Span("\ufeffhello world"),), 0), (0, 4))
        self.assertEqual(_word_at((Span("\u0301abc"),), 0), (0, 2))

    def test_a_word_keeps_punctuation_that_carries_a_mark(self) -> None:
        pager = Pager("log", [(Span("snake_\u0301case x"),)])
        pager.frame(40, 10, DEFAULT_THEME)
        click(pager, 1, 0.0)
        self.assertEqual(click(pager, 1, 0.1), "snake_\u0301case")

    def test_one_long_cluster_is_measured_in_linear_time(self) -> None:
        # One base with thousands of marks, not NFC. Pairing each cluster with its source by growing a run one code
        # point at a time took 472 ms for 8,000 marks (117 ms for 4,000: quadratic); pairing the units takes 10 ms.
        # `_source_clusters` is timed itself: `_cells` keeps a row, so a second `_reversed` would time the cache.
        text = "a" + "\u0301" * 8000
        best = min(_timed(lambda: _source_clusters(text)) for _ in range(3))
        self.assertLess(best, 0.1)

    def test_a_long_row_is_not_kept_and_closing_the_pager_lets_go_of_the_rest(self) -> None:
        forget_cells()
        long_row = (Span("abcd " * 400),)  # a /logs line far wider than any screen
        _cells(long_row)
        self.assertEqual(_kept_cells.cache_info().currsize, 0, "a row past CELLS_KEPT_CHARS is measured, not kept")
        _cells((Span("short"),))
        self.assertEqual(_kept_cells.cache_info().currsize, 1)
        app, client = make_app(rows=12, cols=60, environ=KITTY)
        app.pbcopy = lambda text: False  # type: ignore[method-assign]  # never the real clipboard
        client.stderr_tail = lambda: ["one log line", "and another"]  # type: ignore[attr-defined]
        app._logs("")
        drawn(app)
        rows = app.terminal.screen.lines()  # type: ignore[attr-defined]
        drag_row = next(index for index, row in enumerate(rows) if "one log" in row) + 1
        app._on_input(Mouse(BUTTON_LEFT, 1, drag_row))
        app._on_input(Mouse(BUTTON_LEFT, 8, drag_row, motion=True))
        drawn(app)
        self.assertGreater(_kept_cells.cache_info().currsize, 0)
        app._leave_pager()
        self.assertEqual(_kept_cells.cache_info().currsize, 0, "what the pager kept goes with it")

    def test_a_span_of_only_escapes_does_not_become_a_fill_under_the_highlight(self) -> None:
        sgr = re.compile("\x1b\\[[0-9;]*[mK]")
        for line in ((Span("abc"), Span("\x1b[0m", Style(bg="#202020"))),
                     (Span("abc"), Span("", Style(bg="#202020")))):  # a real fill stays one
            with self.subTest(line=line):
                for low, high in ((0, 0), (0, 9), (5, 9)):
                    self.assertEqual(paint_line(_reversed(line, low, high), 10).count("\x1b[48;"),
                                     paint_line(line, 10).count("\x1b[48;"))
                    self.assertEqual(sgr.sub("", paint_line(_reversed(line, low, high), 10)),
                                     sgr.sub("", paint_line(line, 10)))

    def test_kirat_rai_units_as_written_pair_with_the_painted_ones_and_the_span_copies_as_written(self) -> None:
        # Whatever this interpreter's NFC does with these letters, the units as written are the painted units, so a
        # span holding them (an NFD path beside them) is copied as written; before, the units did not pair where NFC
        # composes the pair, and the whole span fell back to NFC.
        for text in (KIRAT_RAI, "\U00016D67\U00016D67", "\U00016D63\U00016D67\U00016D67", "a" + KIRAT_RAI,
                     "\U0001F1F0\U00016D67\U00016D67"):
            with self.subTest(text=text):
                self.assertEqual([nfc(unit) for unit in clusters_as_written(text)], clusters(text))
        text = "/tmp/e\u0301te\u0301 " + KIRAT_RAI
        self.assertEqual("".join(cell.text for cell in _cells((Span(text),))), text)

    @unittest.skipUnless(KIRAT_RAI_COMPOSES, "this interpreter's unicodedata predates Kirat Rai (Unicode 16)")
    def test_a_kirat_rai_pair_nfc_composes_is_one_unit_and_never_cut_apart(self) -> None:
        # U+16D63 U+16D67 is U+16D69 and U+16D67 U+16D67 is U+16D68 under NFC: one unit written and painted.
        self.assertEqual(clusters_as_written(KIRAT_RAI), [KIRAT_RAI])
        self.assertEqual(clusters_as_written("\U00016D63\U00016D67\U00016D67"), ["\U00016D63\U00016D67\U00016D67"])
        self.assertEqual(subagents._cut("aaaa" + KIRAT_RAI + " tail", 5), "aaaa" + subagents.CUT_MARK)

    def test_the_logs_pager_paints_and_copies_what_stderr_shows(self) -> None:
        now = [100.0]
        app, client = make_app(rows=12, cols=60, environ=KITTY, clock=lambda: now[0])
        app.pbcopy = lambda text: False  # type: ignore[method-assign]  # never the real clipboard
        client.stderr_tail = lambda: [  # type: ignore[attr-defined]
            "\x1b[31mERROR\x1b[0m: boom", "\x9b33mwarn\x9b0m: \x1b]8;;http://x\x07docs\x1b]8;;\x07", "col\tnext"]
        app._logs("")
        drawn(app)
        screen = app.terminal.screen  # type: ignore[attr-defined]
        rows = screen.lines()
        self.assertTrue(any("ERROR: boom" in row for row in rows))
        self.assertTrue(any("warn: docs" in row for row in rows))
        self.assertTrue(any("col\tnext".expandtabs(TAB_CELLS) in row for row in rows), "a tab is spaces")
        y = next(index for index, row in enumerate(rows) if "ERROR: boom" in row)
        x = rows[y].index("boom") + 1
        for _ in range(3):  # a triple click: the row
            app._on_input(Mouse(BUTTON_LEFT, x, y + 1))
            app._on_input(Mouse(BUTTON_LEFT, x, y + 1, pressed=False))
            now[0] += 0.1
        sent = [text.removeprefix("52;c;") for text in screen.osc if text.startswith("52;c;")]
        self.assertEqual([base64.b64decode(text.rstrip("\x07")).decode("utf-8") for text in sent][-1], "ERROR: boom")

    def test_the_app_copies_the_word_after_a_zwj_family_with_the_clipboard_stubbed(self) -> None:
        now = [100.0]
        app, _client = make_app(rows=12, cols=60, environ=KITTY, clock=lambda: now[0])
        handed: list[str] = []
        app.pbcopy = lambda text: handed.append(text) is None  # type: ignore[method-assign]  # never the real clipboard
        app.transcript.blocks.append(AssistantBlock("👨‍👩‍👧 target here"))
        app._history("")
        drawn(app)
        screen = app.terminal.screen  # type: ignore[attr-defined]
        y = next(index for index, line in enumerate(screen.lines()) if "target" in line)
        cells = screen._text[y]
        x = next(column for column in range(len(cells)) if cells[column:column + 6] == list("target")) + 1
        for _ in range(2):
            app._on_input(Mouse(BUTTON_LEFT, x, y + 1))
            app._on_input(Mouse(BUTTON_LEFT, x, y + 1, pressed=False))
            now[0] += 0.1
        sent = [text.removeprefix("52;c;") for text in screen.osc if text.startswith("52;c;")]
        self.assertEqual([base64.b64decode(text.rstrip("\x07")).decode("utf-8") for text in sent], ["target"])
        self.assertEqual(handed, [])


class ClusterCutTests(unittest.TestCase):
    """A cut by character count (a log row, a payload field, a bot's message) ends between two clusters."""

    def test_a_log_row_and_a_payload_field_are_cut_before_the_cluster_the_limit_falls_in(self) -> None:
        for name, lead in CUT_LEADS.items():
            with self.subTest(lead=name):
                text = "a" * 9 + lead + " tail"  # the limit, 10, falls inside `lead`
                self.assertEqual(subagents._cut(text, 10), "a" * 9 + subagents.CUT_MARK)
                self.assertEqual(subagents._one_line(text, 10), "a" * 9 + subagents.CUT_MARK)
                self.assertEqual(subagents._cut(text, 9 + len(lead)), "a" * 9 + lead + subagents.CUT_MARK)
                self.assertEqual(subagents._cut(text, len(text)), text)

    def test_a_cut_keeps_the_texts_own_code_points_and_never_grows_past_its_limit(self) -> None:
        text = "\u0958" * 10  # NFC writes each as two code points (it is a composition exclusion)
        cut = subagents._cut(text, 5)
        self.assertEqual(cut, "\u0958" * 5 + subagents.CUT_MARK)
        self.assertEqual(subagents._cut("cafe\u0301 au lait", 6), "cafe\u0301 " + subagents.CUT_MARK)

    def test_a_bots_message_is_cut_before_the_cluster_the_limit_falls_in(self) -> None:
        for name, lead in CUT_LEADS.items():
            with self.subTest(lead=name):
                text = "a" * (bot_board.MESSAGE_SHOWN_CHARS - 1) + lead + " tail"
                snapshot = bot_board.BoardSnapshot(bot_board.BoardView("p", "s1"), bots(), (),
                                                   messages=(bot_board.MessageRow("user", text, NOW),), read_at=NOW)
                page = "".join(text_of(line) for line in bot_board.message_lines(snapshot, None, NOW, 200, DEFAULT_THEME))
                self.assertIn("a…", page)
                self.assertNotIn(lead[0], page, "no piece of the cluster is left before the cut")


class ClusterStyleTests(unittest.TestCase):
    def test_the_recall_glint_starts_on_the_painted_column_and_splits_no_cluster(self) -> None:
        style = Style(fg="#888888")
        for name, lead in LEADS.items():
            with self.subTest(lead=name):
                spans = _glinted(f"{lead}abcdefghij", style, cluster_width(nfc(lead)), DEFAULT_THEME)
                self.assertTrue(no_cluster_split(spans))
                self.assertEqual(spans[0], Span(nfc(lead), style))
                self.assertEqual(spans[1], Span("a", replace(DEFAULT_THEME.aura[0], bold=False)))

    def test_the_running_box_aura_reaches_its_right_border_and_splits_no_cluster(self) -> None:
        aura = {style.fg for style in (*DEFAULT_THEME.aura, *DEFAULT_THEME.aura_glint)}
        for name, lead in LEADS.items():
            with self.subTest(lead=name):
                row = (Segment("│ ", "node:running"), Segment(f"{lead} title", "node-title:running"),
                       Segment(" │", "node:running"))
                size = line_width(tuple(Span(segment.text) for segment in row))
                line = _aura_box(row, 1, DEFAULT_THEME, TRUECOLOR, 0, size, False, 0)
                self.assertEqual(text_of(line), nfc(f"│ {lead} title │"))
                self.assertTrue(no_cluster_split(line))
                self.assertEqual(line[-1].text[-1], "│")
                self.assertIn(line[-1].style.fg, aura, "the right border is the box's last cell")


if __name__ == "__main__":
    unittest.main()
