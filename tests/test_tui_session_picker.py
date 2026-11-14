"""The `/sessions` picker (`omh.tui.session_picker`): rows, keys, and what it draws."""

from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from _tui_lines import line_text
from omh.tui.frame import RULE
from omh.tui.keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, PAGE_DOWN, PAGE_UP, UP, Key, Paste
from omh.tui.session_picker import (
    CLOSE, CURRENT_NOT_DELETED, DAY_GROUPS, DELETE, DELETE_CONFIRM, DELETING, EMPTY_TITLE, KEYS, PICK, RENAME,
    RENAME_KEYS, PickerAction, SessionPicker, SessionRow, age_text, day_group, session_rows,
)
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME
from omh.tui.width import line_width

# Local noon, so the fixture's day groups are the same in every time zone: its rows started 30 s and 2 h before
# (today) and 3 days before (the previous 7 days).
NOW = datetime(2026, 10, 13, 12, 0).timestamp()

# The recorded `session.list` row shape (Hermes 6c61c3e27d), plus synthesized neighbours.
LISTED = {
    "sessions": [
        {"id": "20261013_115656_e709ea", "title": "Reply with ok", "preview": "Reply with exactly the word: ok",
         "started_at": NOW - 30, "message_count": 14, "source": "tui", "_lineage_root_id": None},
        {"id": "20261012_090000_aaaaaa", "title": "", "preview": "Refactor the router\nsecond line",
         "started_at": NOW - 7200, "message_count": 1, "source": "cli"},
        {"id": "20261001_090000_bbbbbb", "title": "Release notes", "preview": "",
         "started_at": NOW - 3 * 86400, "message_count": 40, "source": "tui"},
        {"title": "no id"},
        "not a row",
    ]
}


def picker(**kwargs: object) -> SessionPicker:
    return SessionPicker(session_rows(LISTED), current="20261013_115656_e709ea", **kwargs)


class SessionRowsTests(unittest.TestCase):
    def test_rows_keep_the_list_order_and_skip_rows_without_an_id(self) -> None:
        rows = session_rows(LISTED)
        self.assertEqual([row.id for row in rows],
                         ["20261013_115656_e709ea", "20261012_090000_aaaaaa", "20261001_090000_bbbbbb"])
        self.assertEqual([row.label for row in rows], ["Reply with ok", "Refactor the router", "Release notes"])
        self.assertEqual(session_rows({"sessions": "nope"}), [])

    def test_age_reads_in_the_largest_whole_unit(self) -> None:
        cases = {NOW - 5: "just now", NOW - 300: "5m ago", NOW - 7200: "2h ago", NOW - 3 * 86400: "3d ago", 0: ""}
        for started, expected in cases.items():
            with self.subTest(started=started):
                self.assertEqual(age_text(started, NOW), expected)


class KeyTests(unittest.TestCase):
    def test_arrows_and_pages_move_within_the_rows_and_enter_picks(self) -> None:
        chooser = picker(page=2)
        for key, index in ((UP, 0), (DOWN, 1), (DOWN, 2), (DOWN, 2), (PAGE_UP, 0), (PAGE_DOWN, 2)):
            with self.subTest(key=key):
                self.assertIsNone(chooser.handle_key(Key(key)))
                self.assertEqual(chooser.index, index)
        self.assertEqual(chooser.handle_key(Key(ENTER)), PickerAction(PICK, "20261001_090000_bbbbbb"))

    def test_typing_filters_by_title_preview_or_id_and_backspace_widens_again(self) -> None:
        chooser = picker()
        for char in "ROUT":
            chooser.handle_key(Key(CHAR, char))
        self.assertEqual([row.id for row in chooser.visible()], ["20261012_090000_aaaaaa"])
        self.assertEqual(chooser.handle_key(Key(ENTER)), PickerAction(PICK, "20261012_090000_aaaaaa"))
        for _ in range(4):
            chooser.handle_key(Key(BACKSPACE))
        chooser.handle_key(Paste("bbbbbb\nignored"))
        self.assertEqual([row.id for row in chooser.visible()], ["20261001_090000_bbbbbb"])

    def test_enter_with_nothing_matching_picks_nothing(self) -> None:
        chooser = picker(query="zzz")
        self.assertIsNone(chooser.handle_key(Key(ENTER)))

    def test_esc_and_ctrl_c_close(self) -> None:
        for key in (Key(ESCAPE), Key(CHAR, "c", ctrl=True)):
            with self.subTest(key=key):
                self.assertEqual(picker().handle_key(key), PickerAction(CLOSE))


class LinesTests(unittest.TestCase):
    def test_a_header_then_one_row_per_session_with_the_current_one_marked(self) -> None:
        lines = picker().lines(60, DEFAULT_THEME, 10, NOW)
        texts = [line_text(line) for line in lines]
        self.assertTrue(texts[0].startswith(" Sessions (3)"))
        self.assertEqual(len(lines), 10)
        self.assertEqual(texts[-1], "❯ type to filter")  # the filter, where the composer was
        # A rule under the header and one over the filter row, set in so no row starts as the composer's rules do.
        self.assertEqual((texts[1], texts[-2]), (" " + RULE * 58,) * 2)  # one cell short of either edge
        self.assertEqual({lines[1][0].style, lines[-2][0].style}, {DEFAULT_THEME.muted})
        self.assertEqual([text.strip() for text in (texts[2], texts[4], texts[6])], ["Current", "Today", "Previous 7 days"])
        current, other, old = texts[3], texts[5], texts[7]
        self.assertTrue(current.startswith("❯ ● Reply with ok"))  # the pointer, then the current session's mark
        self.assertTrue(current.rstrip().endswith("just now   14 messages"))
        self.assertTrue(other.startswith("    Refactor the router"))
        self.assertTrue(other.rstrip().endswith("2h ago    1 message"))
        self.assertTrue(old.rstrip().endswith("3d ago   40 messages"))
        # The age and the count each right-aligned in a column of its own, so the rows read as a table.
        self.assertEqual(len({text.index("ago") for text in (other, old)} | {current.index("now")}), 1)
        self.assertEqual(len({text.index("message") for text in (current, other, old)}), 1)
        self.assertTrue(all(line_width(line) <= 60 for line in lines))
        # The highlighted name in the accent, the others in the terminal's foreground; no row has a fill.
        self.assertEqual(next(span for span in lines[3] if "Reply" in span.text).style, DEFAULT_THEME.menu_current)
        self.assertEqual(next(span for span in lines[5] if "Refactor" in span.text).style, DEFAULT_THEME.menu)
        self.assertEqual(lines[4][-1].style, DEFAULT_THEME.muted)  # a heading is muted, where the titles start
        self.assertEqual(texts[4].index("Today"), current.index("Reply"))
        self.assertEqual({span.style.bg for line in lines for span in line}, {None})

    def test_sessions_are_grouped_by_the_local_day_they_started_in_list_order_inside_a_group(self) -> None:
        midnight = datetime.fromtimestamp(NOW).replace(hour=0, minute=0)
        started = {  # id: start, listed most recently active first, as Hermes lists them
            "old-but-active": midnight - timedelta(days=9),
            "this-morning": midnight + timedelta(hours=1),
            "last-night": midnight - timedelta(hours=1),
            "six-days": midnight - timedelta(days=5, hours=12),
            "a-week": midnight - timedelta(days=6, hours=1),
            "unknown": None,
            "just-now": datetime.fromtimestamp(NOW),
        }
        rows = [SessionRow(sid, sid, "", at.timestamp() if at else 0.0, 1) for sid, at in started.items()]
        chooser = SessionPicker(rows, current="")  # no current session among them: no `Current` group
        self.assertEqual([row.id for row in chooser.visible()], list(started))  # before a render: Hermes' order
        texts = [line_text(line).strip() for line in chooser.lines(60, DEFAULT_THEME, 30, NOW)[2:-2]]
        self.assertEqual([text.lstrip("❯ ").split()[0] for text in texts], [
            "Today", "this-morning", "just-now", "Yesterday", "last-night", "Previous", "six-days",
            "Earlier", "old-but-active", "a-week", "unknown",
        ])
        self.assertEqual([DAY_GROUPS[day_group(row.started_at, NOW)] for row in chooser.visible()],
                         ["Today"] * 2 + ["Yesterday", "Previous 7 days"] + ["Earlier"] * 3)

    def test_keys_move_from_session_to_session_past_the_headings(self) -> None:
        chooser = picker()
        chooser.lines(60, DEFAULT_THEME, 10, NOW)
        picked = []
        for key in (DOWN, DOWN, DOWN, UP, UP, PAGE_DOWN):
            chooser.handle_key(Key(key))
            picked.append(chooser.visible()[chooser.index].id)
        self.assertEqual(picked, ["20261012_090000_aaaaaa", "20261001_090000_bbbbbb", "20261001_090000_bbbbbb",
                                  "20261012_090000_aaaaaa", "20261013_115656_e709ea", "20261001_090000_bbbbbb"])
        self.assertEqual(chooser.handle_key(Key(ENTER)), PickerAction(PICK, "20261001_090000_bbbbbb"))
        lines = [line_text(line) for line in chooser.lines(60, DEFAULT_THEME, 10, NOW)]
        self.assertTrue(lines[7].startswith("❯   Release notes"), lines)  # the pointer on the row, never a heading

    def test_a_filter_keeps_only_the_headings_of_groups_with_a_match(self) -> None:
        texts = [line_text(line).strip() for line in picker(query="release").lines(60, DEFAULT_THEME, 10, NOW)]
        self.assertEqual(texts[0], "Sessions (1/3)")
        self.assertEqual(texts[2], "Previous 7 days")
        self.assertNotIn("Today", texts)
        self.assertTrue(texts[3].startswith("❯   Release notes"))

    def test_the_rules_go_first_when_the_list_would_get_short(self) -> None:
        for max_rows, rules in ((5, 0), (6, 1), (7, 2)):  # the header's rule first, then the filter row's
            with self.subTest(max_rows=max_rows):
                lines = [line_text(line) for line in picker().lines(60, DEFAULT_THEME, max_rows, NOW)]
                self.assertEqual(len(lines), max_rows)
                self.assertEqual(sum(RULE in line for line in lines), rules)
                self.assertEqual(lines[-1], "❯ type to filter")

    def test_one_more_row_of_room_never_shows_fewer_list_rows(self) -> None:
        many = SessionPicker([SessionRow(f"s{n}", f"session {n}", "", NOW - n * 3600, 1) for n in range(40)],
                             current="")
        shown = []
        for max_rows in range(1, 30):
            texts = [line_text(line) for line in many.lines(60, DEFAULT_THEME, max_rows, NOW)]
            shown.append(sum(1 for text in texts if "session " in text))
        self.assertEqual(shown, sorted(shown))
        self.assertEqual(shown[5:7], [shown[5], shown[5]])  # 6 rows and 7 rows: the same list (L2: 4 then 3)

    def test_a_heading_is_never_the_last_row_shown_while_its_rows_are_below(self) -> None:
        # 24x10-like budgets over a list of several day groups, at every highlighted row.
        midnight = datetime.fromtimestamp(NOW).replace(hour=0, minute=0)
        starts = [NOW - 60, NOW - 120, (midnight - timedelta(hours=2)).timestamp(), (midnight - timedelta(hours=3)).timestamp(),
                  (midnight - timedelta(days=3)).timestamp(), (midnight - timedelta(days=4)).timestamp(),
                  (midnight - timedelta(days=20)).timestamp(), (midnight - timedelta(days=30)).timestamp()]
        rows = [SessionRow(f"s{n}", f"t{n}", "", at, 1) for n, at in enumerate(starts)]
        headings = {"Current", *DAY_GROUPS}
        # The review's case too: six sessions, the current one first, at 60 columns, where opening the picker
        # scrolled `Current` out of view at heights 5, 6, 7 and 10.
        six = [SessionRow(f"c{n}", "" if n == 0 else f"t{n}", "", at, 1) for n, at in enumerate(starts[:6])]
        for current, cases, width in (("s1", rows, 24), ("c0", six, 60)):
            for max_rows in range(3, 13):
                chooser = SessionPicker(cases, current=current)
                for step in range(len(cases)):
                    with self.subTest(width=width, max_rows=max_rows, step=step):
                        texts = [line_text(line).strip() for line in chooser.lines(width, DEFAULT_THEME, max_rows, NOW)]
                        listed = [text for text in texts[1:-1] if not text.startswith(RULE)]
                        if listed[-1] in headings:  # only the list's very end may stop on one, with nothing below
                            self.fail(f"orphan heading {listed[-1]!r}: {texts}")
                        at = next(number for number, text in enumerate(listed) if text.startswith("❯"))
                        shown = chooser.visible()
                        group = chooser._group(shown[chooser.index])
                        first = chooser.index == 0 or chooser._group(shown[chooser.index - 1]) != group
                        if first and max_rows > 3:  # a list of two rows or more shows the heading over its first row
                            self.assertEqual(listed[at - 1] if at else "", group, texts)
                    chooser.handle_key(Key(DOWN))

    def test_the_current_session_heads_the_list_and_is_this_session_while_untitled(self) -> None:
        rows = [SessionRow("today-1", "Today's work", "", NOW - 60, 3),
                SessionRow("local-9190b15b79de2cc242c5f69c11c0d0e7", "", "a first prompt", NOW - 9 * 86400, 2),
                SessionRow("20261012_090000_cccccc", "", "", NOW - 86400, 1)]
        texts = [line_text(line) for line in SessionPicker(rows, current=rows[1].id).lines(60, DEFAULT_THEME, 12, NOW)]
        self.assertEqual([text.strip() for text in texts[2:4]][0], "Current")
        self.assertTrue(texts[3].startswith("❯ ● this session"), texts)  # resumed 9 days after it started: still first
        self.assertTrue(any(text.startswith("    20261012_090000_cccccc") for text in texts))  # another untitled: its id
        self.assertNotIn("local-9190", "".join(texts))
        titled = SessionPicker(rows, current="today-1").lines(60, DEFAULT_THEME, 12, NOW)
        self.assertTrue(line_text(titled[3]).startswith("❯ ● Today's work"))
        self.assertIn("a first prompt", "".join(line_text(line) for line in titled))  # not current: its own label

    def test_a_start_in_milliseconds_or_past_any_calendar_does_not_break_the_render(self) -> None:
        listed = {"sessions": [{"id": "ms", "title": "in ms", "started_at": (NOW - 300) * 1000},
                               {"id": "far", "title": "far off", "started_at": 1e300},
                               {"id": "soon", "title": "an hour ahead", "started_at": NOW + 3600},
                               {"id": "later", "title": "three days ahead", "started_at": NOW + 3 * 86400},
                               {"id": "inf", "title": "infinite", "started_at": float("inf")},
                               {"id": "nan", "title": "not a number", "started_at": float("nan")}]}
        rows = session_rows(listed)
        self.assertAlmostEqual(rows[0].started_at, NOW - 300)
        self.assertEqual(age_text(rows[0].started_at, NOW), "5m ago")
        self.assertEqual([row.started_at for row in rows[-3:]] + [rows[1].started_at], [NOW + 3 * 86400, 0.0, 0.0, 0.0])
        self.assertEqual([DAY_GROUPS[day_group(row.started_at, NOW)] for row in rows],
                         ["Today", "Earlier", "Today", "Today", "Earlier", "Earlier"])  # a future day is still today's
        for value in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=value):
                self.assertEqual(age_text(value, NOW), "")
        texts = [line_text(line) for line in SessionPicker(rows, current="").lines(60, DEFAULT_THEME, 12, NOW)]
        self.assertIn("in ms", "".join(texts))

    def test_rows_scroll_to_keep_the_highlighted_one_and_the_page_follows_the_room(self) -> None:
        chooser = picker(index=2)
        lines = chooser.lines(60, DEFAULT_THEME, 4, NOW)
        self.assertEqual(len(lines), 4)
        self.assertIn("Release notes", line_text(lines[-2]))
        self.assertEqual(chooser.page, 2)

    def test_a_filter_that_matches_nothing_says_so(self) -> None:
        lines = picker(query="zzz").lines(60, DEFAULT_THEME, 5, NOW)
        self.assertIn("Sessions (0/3)", line_text(lines[0]))
        self.assertIn("no session matches", line_text(lines[1]))
        self.assertEqual(line_text(lines[-1]), "❯ zzz")

    def test_the_filter_row_is_last_at_every_budget_and_says_what_typing_filters_by(self) -> None:
        chooser = picker(query="re")
        for max_rows in range(2, 9):
            with self.subTest(max_rows=max_rows):
                lines = chooser.lines(60, DEFAULT_THEME, max_rows, NOW)
                self.assertLessEqual(len(lines), max_rows)
                self.assertEqual(line_text(lines[-1]), "❯ re")
                self.assertNotIn("filter", line_text(lines[0]))
        self.assertEqual(len(chooser.lines(60, DEFAULT_THEME, 1, NOW)), 1)
        filtered = picker()
        filtered.handle_key(Key(CHAR, "R"))
        self.assertEqual(line_text(filtered.lines(60, DEFAULT_THEME, 6, NOW)[-1]), "❯ R")


class FrameTests(unittest.TestCase):
    """The keys ladder in the header, the highlighted row on a tiny budget, and the caret at the end of the filter."""

    def test_the_header_is_the_title_alone(self) -> None:
        # The keys are the info line's.
        self.assertEqual(line_text(picker().lines(100, DEFAULT_THEME, 6, NOW)[0]).rstrip(), " Sessions (3)")
        self.assertEqual(line_width(picker().lines(8, DEFAULT_THEME, 6, NOW)[0]), 8)

    def test_two_rows_or_fewer_keep_the_highlighted_row_and_drop_the_header(self) -> None:
        chooser = picker(index=1)
        one = chooser.lines(60, DEFAULT_THEME, 1, NOW)
        self.assertEqual(len(one), 1)
        self.assertTrue(line_text(one[0]).startswith("❯   Refactor the router"), one)
        self.assertEqual(next(span for span in one[0] if "Refactor" in span.text).style, DEFAULT_THEME.menu_current)
        two = [line_text(line) for line in chooser.lines(60, DEFAULT_THEME, 2, NOW)]
        self.assertTrue(two[0].startswith("❯   Refactor the router"), two)
        self.assertEqual(two[1], "❯ type to filter")
        self.assertIn("no session matches", line_text(picker(query="zzz").lines(60, DEFAULT_THEME, 1, NOW)[0]))

    def test_the_caret_sits_at_the_end_of_the_filter_row(self) -> None:
        for query, budget in (("", 6), ("re", 6), ("re", 2), ("한글", 6)):
            with self.subTest(query=query, budget=budget):
                chooser = picker(query=query)
                lines = chooser.lines(60, DEFAULT_THEME, budget, NOW)
                self.assertEqual(chooser.caret, (len(lines) - 1, line_width((Span("❯ " + query),))))
        chooser = picker()
        chooser.lines(60, DEFAULT_THEME, 1, NOW)
        self.assertIsNone(chooser.caret)  # no filter row drawn, no caret


if __name__ == "__main__":
    unittest.main()


CTRL_R = Key(CHAR, "r", ctrl=True)
CTRL_D = Key(CHAR, "d", ctrl=True)


def typed(chooser: SessionPicker, text: str) -> list[PickerAction | None]:
    return [chooser.handle_key(Key(CHAR, char)) for char in text]


def shown(chooser: SessionPicker, width: int = 100, rows: int = 12) -> str:
    return "\n".join(line_text(line) for line in chooser.lines(width, DEFAULT_THEME, rows, NOW))


class RenameTests(unittest.TestCase):
    """Ctrl+R: the filter row becomes the highlighted session's title (opencode `session.rename`, ctrl+r)."""

    def renaming(self) -> SessionPicker:
        chooser = picker()
        shown(chooser)  # the day groups order the rows: the current one first, then the 2 h old one
        chooser.handle_key(Key(DOWN))
        self.assertIsNone(chooser.handle_key(CTRL_R))
        return chooser

    def test_ctrl_r_opens_the_title_field_and_enter_asks_for_the_rename(self) -> None:
        chooser = self.renaming()
        self.assertEqual((chooser.renaming, chooser.title), ("20261012_090000_aaaaaa", ""))  # untitled: an empty field
        self.assertEqual(chooser.keys(), RENAME_KEYS)
        drawn = shown(chooser)
        self.assertIn("Rename Refactor the router", drawn)
        self.assertIn("type the session's new title", drawn)
        self.assertEqual(typed(chooser, "Router split"), [None] * len("Router split"))
        self.assertTrue(shown(chooser).splitlines()[-1].endswith("Router split"))
        self.assertEqual(chooser.query, "")  # typing went to the title, not the filter
        action = chooser.handle_key(Key(ENTER))
        self.assertEqual(action, PickerAction(RENAME, "20261012_090000_aaaaaa", "Router split"))
        self.assertEqual(chooser.renaming, "")
        self.assertEqual(chooser.keys(), KEYS)
        self.assertIn("renaming…", shown(chooser))

    def test_the_field_is_prefilled_with_the_title_the_row_has(self) -> None:
        chooser = picker()
        chooser.handle_key(CTRL_R)  # the current session, titled "Reply with ok"
        self.assertEqual(chooser.title, "Reply with ok")
        chooser.handle_key(Key(BACKSPACE))
        chooser.handle_key(Key(BACKSPACE))
        typed(chooser, "OK")
        self.assertEqual(chooser.handle_key(Key(ENTER)), PickerAction(RENAME, "20261013_115656_e709ea", "Reply with OK"))

    def test_esc_cancels_and_puts_the_filter_back(self) -> None:
        for key in (Key(ESCAPE), Key(CHAR, "c", ctrl=True)):
            with self.subTest(key=key):
                chooser = picker(query="re")
                chooser.handle_key(CTRL_R)
                typed(chooser, "x")
                self.assertIsNone(chooser.handle_key(key))  # no action: the picker stays open, nothing is sent
                self.assertEqual((chooser.renaming, chooser.title, chooser.query), ("", "", "re"))
                self.assertTrue(shown(chooser).splitlines()[-1].endswith("re"))

    def test_an_empty_title_is_refused_here(self) -> None:
        chooser = self.renaming()
        typed(chooser, "   ")
        self.assertIsNone(chooser.handle_key(Key(ENTER)))
        self.assertEqual(chooser.renaming, "20261012_090000_aaaaaa")  # still the field
        self.assertIn(EMPTY_TITLE, shown(chooser))

    def test_a_rename_answered_updates_the_row_and_a_refusal_is_said_on_it_until_the_next_key(self) -> None:
        chooser = self.renaming()
        typed(chooser, "Router split")
        chooser.asked(chooser.handle_key(Key(ENTER)))  # type: ignore[arg-type]
        self.assertTrue(chooser.renamed("20261012_090000_aaaaaa", "Router split"))
        self.assertIn("Router split", shown(chooser))
        self.assertNotIn("Refactor the router", shown(chooser))
        self.assertFalse(chooser.renamed("no-such-row", "x"))
        self.assertTrue(chooser.refused("20261001_090000_bbbbbb", "session not found"))
        self.assertIn("session not found", shown(chooser))
        chooser.handle_key(Key(DOWN))
        self.assertNotIn("session not found", shown(chooser))


class DeleteTests(unittest.TestCase):
    """Ctrl+D: the row asks, a second Ctrl+D deletes (opencode `session.delete`, ctrl+d)."""

    def armed(self) -> SessionPicker:
        chooser = picker()
        shown(chooser)
        chooser.handle_key(Key(DOWN))
        self.assertIsNone(chooser.handle_key(CTRL_D))
        return chooser

    def test_ctrl_d_asks_on_the_row_and_a_second_one_deletes(self) -> None:
        chooser = self.armed()
        self.assertIn(DELETE_CONFIRM, shown(chooser))
        self.assertEqual(chooser.handle_key(CTRL_D), PickerAction(DELETE, "20261012_090000_aaaaaa"))
        self.assertNotIn(DELETE_CONFIRM, shown(chooser))

    def test_any_other_key_takes_the_first_press_back_and_does_nothing_more(self) -> None:
        for key in (Key(DOWN), Key(CHAR, "x"), Key(ENTER), Key(ESCAPE), Paste("y")):
            with self.subTest(key=key):
                chooser = self.armed()
                self.assertIsNone(chooser.handle_key(key))
                self.assertEqual((chooser.arming, chooser.index, chooser.query), ("", 1, ""))
                self.assertNotIn(DELETE_CONFIRM, shown(chooser))
                self.assertIsNone(chooser.handle_key(CTRL_D))  # a new first press, not a delete
                self.assertEqual(chooser.arming, "20261012_090000_aaaaaa")

    def test_the_current_session_is_never_deleted_and_its_row_says_so(self) -> None:
        chooser = picker()
        shown(chooser)
        self.assertIsNone(chooser.handle_key(CTRL_D))  # the current session heads the list
        self.assertEqual(chooser.arming, "")
        self.assertIn(CURRENT_NOT_DELETED, shown(chooser))
        self.assertIsNone(chooser.handle_key(CTRL_D))
        self.assertIn(CURRENT_NOT_DELETED, shown(chooser))

    def test_a_delete_answered_removes_the_row_and_one_out_takes_no_second_ask(self) -> None:
        chooser = self.armed()
        action = chooser.handle_key(CTRL_D)
        chooser.asked(action)  # type: ignore[arg-type]
        self.assertIn(DELETING, shown(chooser))
        self.assertIsNone(chooser.handle_key(CTRL_D))  # its call is out: no new ask
        self.assertEqual(chooser.arming, "")
        self.assertTrue(chooser.deleted("20261012_090000_aaaaaa"))
        self.assertEqual([row.id for row in chooser.rows], ["20261013_115656_e709ea", "20261001_090000_bbbbbb"])
        self.assertIn("Sessions (2)", shown(chooser))
        self.assertFalse(chooser.deleted("20261012_090000_aaaaaa"))

    def test_ctrl_r_and_ctrl_d_with_alt_or_with_nothing_listed_do_nothing(self) -> None:
        chooser = picker(query="zzz")  # nothing matches
        self.assertIsNone(chooser.handle_key(CTRL_R))
        self.assertIsNone(chooser.handle_key(CTRL_D))
        self.assertEqual((chooser.renaming, chooser.arming), ("", ""))
        chooser = picker()
        chooser.handle_key(Key(CHAR, "d", ctrl=True, alt=True))
        chooser.handle_key(Key(CHAR, "r", ctrl=True, alt=True))
        self.assertEqual((chooser.renaming, chooser.arming), ("", ""))
