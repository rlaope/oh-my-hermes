"""`/resume` as Claude Code draws its resume picker (`SessionPicker.card_lines`, `layout.tall_cap`).

The picker takes most of the screen: an inset rule, `Resume session (n of m)`,
the filter in a rounded search box with the caret in it, then a card per
session (its name, then `2 days ago · 14 messages · tui` muted) under the day
headings. Where the cards do not fit it stays the one-row list; closing it on
the bottom rows gives every row it took back to the transcript.
"""

from __future__ import annotations

import unittest

from _tui_lines import line_text
from omh.tui.keys import BACKSPACE, CHAR, DOWN, ESCAPE, Key
from omh.tui.layout import TALL_CONTEXT_ROWS, allocate, choice_cap, max_height, tall_cap
from omh.tui.session_picker import (
    CARD_KEYS, CARDS_MIN_COLS, DELETE_CONFIRM, SessionPicker, SessionRow, age_words, session_rows,
)
from omh.tui.theme import DEFAULT_THEME
from omh.tui.width import cell_width, line_width
from test_tui_modes import drawn, make_app
from test_tui_session_picker import LISTED, NOW


def picker(**kwargs: object) -> SessionPicker:
    return SessionPicker(session_rows(LISTED), current="20261013_115656_e709ea", **kwargs)


def texts(chooser: SessionPicker, width: int = 80, rows: int = 20) -> list[str]:
    return [line_text(line) for line in chooser.card_lines(width, DEFAULT_THEME, rows, NOW)]


def cards(shown: list[str]) -> list[str]:
    """The rows under the search box and over the keys: the list."""
    keys = next(number for number, text in enumerate(shown) if text.strip().startswith("↑↓ to move"))
    return shown[6:keys - 1]


# The least height the cards are drawn in at 80 columns: the head (6), two cards (5), the blank and the two rows its
# keys wrap onto there.
CARDS_MIN_ROWS = 14


def many(count: int) -> SessionPicker:
    return SessionPicker([SessionRow(f"s{n}", f"session {n}", "", NOW - n * 3600, n + 1) for n in range(count)],
                         current="")


class CardTests(unittest.TestCase):
    def test_a_rule_the_header_a_search_box_then_one_card_per_session(self) -> None:
        shown = texts(picker())
        self.assertTrue(shown[0].startswith(" ─") and shown[0].rstrip().endswith("─"))
        self.assertEqual(shown[1].rstrip(), "  Resume session (1 of 3)")
        self.assertTrue(shown[2].startswith("  ╭") and shown[2].endswith("╮"))
        self.assertTrue(shown[3].startswith("  │ ⌕ Search…") and shown[3].endswith("│"))
        self.assertTrue(shown[4].startswith("  ╰") and shown[4].endswith("╯"))
        self.assertEqual(shown[5], "")
        self.assertEqual([text.rstrip() for text in cards(shown)], [
            "    Current",
            "  ❯ Reply with ok",
            "    ● this session · just now · 14 messages · tui",
            "",
            "    Today",
            "    Refactor the router",
            "    2 hours ago · 1 message · cli",
            "",
            "    Previous 7 days",
            "    Release notes",
            "    3 days ago · 40 messages · tui",
        ])
        self.assertEqual(" · ".join(text.strip() for text in shown[-2:] if text.strip()), " · ".join(CARD_KEYS))
        self.assertTrue(all(line_width(line) <= 80 for line in picker().card_lines(80, DEFAULT_THEME, 20, NOW)))

    def test_the_styles_follow_claude_codes_the_pointer_and_name_in_the_accent_the_rest_muted(self) -> None:
        lines = picker().card_lines(80, DEFAULT_THEME, 20, NOW)
        title = lines[7]
        self.assertEqual(next(span for span in title if "Reply" in span.text).style, DEFAULT_THEME.menu_current)
        self.assertEqual(next(span for span in title if "❯" in span.text).style, DEFAULT_THEME.menu_current)
        self.assertEqual(next(span for span in lines[11] if "Refactor" in span.text).style, DEFAULT_THEME.menu)
        self.assertEqual(next(span for span in lines[8] if "messages" in span.text).style, DEFAULT_THEME.muted)
        self.assertEqual(next(span for span in lines[1] if "Resume" in span.text).style, DEFAULT_THEME.heading)
        self.assertEqual({span.style.bg for line in lines for span in line}, {None})  # no fills

    def test_the_header_counts_the_highlighted_card_and_a_filter_narrows_it(self) -> None:
        chooser = picker()
        texts(chooser)
        chooser.handle_key(Key(DOWN))
        self.assertEqual(texts(chooser)[1].rstrip(), "  Resume session (2 of 3)")
        for char in "release":
            chooser.handle_key(Key(CHAR, char))
        shown = texts(chooser)
        self.assertEqual(shown[1].rstrip(), "  Resume session (1 of 1)")
        self.assertTrue(shown[3].startswith("  │ ⌕ release "), shown[3])
        self.assertNotIn("Today", "\n".join(shown))
        for _ in "release":
            chooser.handle_key(Key(BACKSPACE))
        chooser.handle_key(Key(CHAR, "z"))
        chooser.handle_key(Key(CHAR, "q"))
        shown = texts(chooser)
        self.assertEqual(shown[1].rstrip(), "  Resume session (0 of 3)")
        self.assertIn("no session matches the filter", "\n".join(shown))

    def test_a_filter_keeps_the_height_so_the_search_box_does_not_move(self) -> None:
        chooser = picker()
        opened = len(texts(chooser))
        chooser.handle_key(Key(CHAR, "z"))
        self.assertEqual(len(texts(chooser)), opened)  # blank rows under the cards, the box where it was
        self.assertEqual(len(texts(chooser, rows=15)), 15)  # never past the room it is given

    def test_the_caret_is_in_the_search_box_at_the_end_of_what_was_typed(self) -> None:
        for query in ("", "re", "한글"):
            with self.subTest(query=query):
                chooser = picker(query=query)
                shown = texts(chooser)
                self.assertEqual(chooser.caret, (3, cell_width("  │ ⌕ ") + cell_width(query)))
                self.assertEqual(shown[3][: len("  │ ⌕ ")], "  │ ⌕ ")
        long = picker(query="x" * 200)
        shown = texts(long, width=40)
        self.assertEqual(cell_width(shown[3]), 40 - 2)  # the box keeps its width (inset 2 a side), its text cut at the head
        self.assertIn("…", shown[3])
        self.assertLess(long.caret[1], 40 - 2)  # type: ignore[index]  # inside the box's right edge

    def test_ages_read_in_words_as_claude_codes_do(self) -> None:
        cases = {NOW - 5: "just now", NOW - 60: "1 minute ago", NOW - 300: "5 minutes ago", NOW - 3600: "1 hour ago",
                 NOW - 86400: "1 day ago", NOW - 3 * 86400: "3 days ago", NOW - 7 * 86400: "1 week ago",
                 NOW - 20 * 86400: "2 weeks ago", NOW - 65 * 86400: "2 months ago", NOW - 400 * 86400: "1 year ago",
                 0: ""}
        for started, expected in cases.items():
            with self.subTest(started=started):
                self.assertEqual(age_words(started, NOW), expected)

    def test_a_long_list_scrolls_the_highlighted_card_into_view_with_arrows_for_what_is_hidden(self) -> None:
        chooser = many(20)
        shown = texts(chooser, rows=16)
        self.assertIn(len(shown), (15, 16))  # as tall as the cards that fit, never ending on a blank row
        listed = cards(shown)
        self.assertTrue(listed[-1].startswith("  ↓ "), shown)  # more below, on the last card's own row
        self.assertFalse(any(text.startswith("  ↑ ") for text in listed))
        for _ in range(10):
            chooser.handle_key(Key(DOWN))
        shown = texts(chooser, rows=16)
        self.assertLessEqual(len(shown), 16)
        self.assertTrue(any(text.startswith("  ❯ session 10") for text in shown), shown)
        listed = cards(shown)
        self.assertTrue(listed[0].startswith("  ↑ "), shown)  # the first row under the box says more sit above
        self.assertTrue(listed[-1].startswith("  ↓ "), shown)
        self.assertNotEqual(listed[-1].strip(), "↓")  # never an arrow alone on a blank row

    def test_every_highlighted_card_shows_whole_at_every_height(self) -> None:
        for rows in range(CARDS_MIN_ROWS, 30):
            chooser = many(12)
            for step in range(12):
                with self.subTest(rows=rows, step=step):
                    shown = texts(chooser, rows=rows)
                    self.assertLessEqual(len(shown), rows)
                    at = next(number for number, text in enumerate(shown) if text.startswith("  ❯ "))
                    self.assertLess(at + 1, len(shown))  # its second row is drawn too
                    self.assertIn("message", shown[at + 1])
                chooser.handle_key(Key(DOWN))

    def test_a_delete_asks_on_the_cards_second_row(self) -> None:
        chooser = picker()
        texts(chooser)
        chooser.handle_key(Key(DOWN))
        chooser.handle_key(Key(CHAR, "d", ctrl=True))
        shown = texts(chooser)
        at = next(number for number, text in enumerate(shown) if text.startswith("  ❯ "))
        self.assertEqual(shown[at + 1].strip(), DELETE_CONFIRM)

    def test_ctrl_r_makes_the_search_box_the_title_field(self) -> None:
        chooser = picker()
        texts(chooser)
        chooser.handle_key(Key(DOWN))
        chooser.handle_key(Key(CHAR, "r", ctrl=True))
        shown = texts(chooser)
        self.assertEqual(shown[1].rstrip(), "  Rename Refactor the router")
        self.assertTrue(shown[3].startswith("  │ ✎ type the session's new title"), shown[3])
        for char in "Router":
            chooser.handle_key(Key(CHAR, char))
        self.assertTrue(texts(chooser)[3].startswith("  │ ✎ Router "))

    def test_too_little_room_or_a_waiting_picker_keeps_the_one_row_list(self) -> None:
        self.assertTrue(picker().fits_cards(80, CARDS_MIN_ROWS))
        for width, rows, waiting in ((80, CARDS_MIN_ROWS - 1, False), (CARDS_MIN_COLS - 1, 20, False), (80, 20, True)):
            with self.subTest(width=width, rows=rows, waiting=waiting):
                chooser = picker(waiting=waiting)
                self.assertFalse(chooser.fits_cards(width, rows))
                shown = texts(chooser, width=width, rows=rows)
                self.assertFalse(any("Resume session" in text for text in shown))
                self.assertTrue(shown[-1].startswith("❯ "), shown)  # the filter row, where the composer was

    def test_the_source_is_read_from_the_listed_row_and_kept_short(self) -> None:
        rows = session_rows({"sessions": [{"id": "a", "source": "  discord\n\tdm  "}, {"id": "b", "source": 3},
                                          {"id": "c", "source": "x" * 80}]})
        self.assertEqual([row.source for row in rows], ["discord dm", "", "x" * 24])


class WrapTests(unittest.TestCase):
    """Long names, facts and the keys wrap as Claude Code's picker wraps them, never past the card."""

    LONG = "PR 2867 캐리 리뷰 하고 TUI resume 피커를 클로드 코드처럼 개편하면서 줄바꿈까지 맞추는 아주 긴 세션 제목"

    def test_a_long_name_wraps_onto_a_second_row_and_is_cut_after_it(self) -> None:
        chooser = SessionPicker([SessionRow("a", self.LONG, "", NOW - 60, 3, "tui"),
                                 SessionRow("b", "short", "", NOW - 120, 1)], current="")
        for width, rows in ((100, 2), (60, 2)):
            with self.subTest(width=width):
                listed = cards(texts(chooser, width=width, rows=24))
                at = next(number for number, text in enumerate(listed) if text.startswith("  ❯ "))
                self.assertTrue(listed[at + rows - 1].startswith("    ") and listed[at + rows - 1].strip(), listed)
                self.assertIn("1 minute ago", listed[at + rows])  # the facts under the name's last row
                self.assertTrue(all(cell_width(text) <= width - 2 for text in listed), listed)
        narrow = cards(texts(chooser, width=40, rows=24))
        self.assertTrue(narrow[2].rstrip().endswith("…"), narrow)  # two rows at most, the rest cut
        self.assertIn("minute ago", narrow[3])

    def test_the_keys_wrap_between_two_keys_and_the_info_line_says_none(self) -> None:
        for width in (60, 100, 200):
            with self.subTest(width=width):
                shown = texts(picker(), width=width, rows=24)
                keys = [text.strip() for text in shown[-3:] if text.strip().startswith(("↑↓", "Ctrl", "Esc", "Type",
                                                                                         "Enter"))]
                self.assertEqual(" · ".join(keys), " · ".join(CARD_KEYS))
                self.assertTrue(all(not key.endswith("·") for key in keys))  # broken only between two keys
                self.assertTrue(all(cell_width(text.rstrip()) <= width - 2 for text in cards(shown) + shown[-2:]))
        self.assertEqual(len([text for text in texts(picker(), width=200, rows=24)[-2:] if text.strip()]), 1)


class LayoutTests(unittest.TestCase):
    def test_tall_cap_leaves_the_info_line_and_a_little_transcript(self) -> None:
        for rows, cols in ((24, 80), (40, 120), (12, 40)):
            with self.subTest(rows=rows, cols=cols):
                self.assertEqual(tall_cap(rows, cols), max_height(rows) - 1 - TALL_CONTEXT_ROWS)
                self.assertGreater(tall_cap(rows, cols), choice_cap(rows, cols))
        self.assertEqual(tall_cap(4, 80), 0)  # a tiny terminal

    def test_slot_limit_raises_the_hidden_composers_slot_only(self) -> None:
        tall = allocate(24, 80, tail_rows=30, slot_rows=40, composer_rows=1, composer_hidden=True,
                        slot_limit=tall_cap(24, 80))
        self.assertEqual(tall.slot, tall_cap(24, 80))
        self.assertEqual(tall.total, max_height(24))
        plain = allocate(24, 80, tail_rows=30, slot_rows=40, composer_rows=1, composer_hidden=True)
        self.assertEqual(plain.slot, choice_cap(24, 80))
        shown = allocate(24, 80, tail_rows=30, slot_rows=40, composer_rows=1, slot_limit=tall_cap(24, 80))
        self.assertLess(shown.slot, tall_cap(24, 80))  # with the composer drawn the limit does nothing


class AppTests(unittest.TestCase):
    def test_resume_takes_most_of_the_screen_with_the_info_line_saying_its_keys(self) -> None:
        app, _client = make_app(rows=30, cols=90)
        for number in range(40):
            app.transcript.add_notice(f"transcript line {number}")
        drawn(app)
        app._open_session_picker({"sessions": [
            {"id": f"s{n}", "title": f"session {n}", "started_at": NOW - n * 3600, "message_count": n, "source": "tui"}
            for n in range(12)]})
        screen = drawn(app)
        header = next(number for number, row in enumerate(screen) if "Resume session (1 of 12)" in row)
        self.assertLessEqual(header, 1 + TALL_CONTEXT_ROWS + 1)  # only a little transcript above it
        self.assertNotIn("esc closes", screen[-1])  # the keys are under the cards, wrapped, not on the info line
        self.assertTrue(any(row.strip().startswith("↑↓ to move · Enter to switch") for row in screen), screen)
        self.assertFalse(any(row.startswith("──") for row in screen))  # no composer rules
        box = header + 2
        self.assertEqual(app.terminal.screen.cursor[0], box)  # type: ignore[attr-defined]  # the caret in the box

    def test_closing_on_the_bottom_rows_gives_its_rows_back_to_the_transcript(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        for number in range(40):
            app.transcript.add_notice(f"transcript line {number}")
        before = drawn(app)
        app._open_session_picker(LISTED)
        drawn(app)
        app._on_input(Key(ESCAPE))
        after = drawn(app)
        self.assertEqual(after, before)  # the screen it opened over, row for row: no band of blank rows
        self.assertIsNone(app.picker)

    def test_a_short_terminal_keeps_the_one_row_list(self) -> None:
        app, _client = make_app(rows=10, cols=80)
        app._open_session_picker(LISTED)
        screen = drawn(app)
        self.assertFalse(any("Resume session" in row for row in screen), screen)
        self.assertTrue(any(row.startswith(" Sessions (3)") for row in screen), screen)


if __name__ == "__main__":
    unittest.main()
