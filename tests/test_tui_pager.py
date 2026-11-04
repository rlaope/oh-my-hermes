"""The in-memory pager's frames (`omh.tui.pager`): a frame repaints only the rows that changed since the last one."""

from __future__ import annotations

import random
import unittest
from collections import Counter
from unittest.mock import patch

from _vt_screen import VTScreen
from omh.tui.keys import CHAR, Key
from omh.tui.pager import HISTORY_BLOCKS_KEPT, HistoryPager, Pager
from omh.tui.style import Line, Span
from omh.tui.theme import DEFAULT_THEME as THEME, theme_named


def rows(*texts: str) -> list[Line]:
    return [(Span(text),) for text in texts]


def fresh_screen(pager: Pager, cols: int, height: int) -> list[str]:
    """What a pager showing the same page draws on a blank screen."""
    screen = VTScreen(height, cols)
    copy = Pager(pager.title, list(pager.lines), pager.top)
    screen.feed(copy.frame(cols, height, THEME))
    return screen.lines()


class PagerFrameTests(unittest.TestCase):
    def test_a_frame_with_nothing_changed_writes_nothing(self) -> None:
        pager = Pager("log", rows("one", "two"))
        self.assertIn("two", pager.frame(30, 6, THEME))
        self.assertEqual(pager.frame(30, 6, THEME), "")

    def test_only_the_rows_that_changed_are_painted(self) -> None:
        pager = Pager("log", rows("row 0", "row 1", "row 2"))
        pager.frame(30, 6, THEME)
        pager.lines = rows("row 0", "ROW 1", "row 2")
        changed = pager.frame(30, 6, THEME)
        self.assertIn("ROW 1", changed)
        self.assertNotIn("row 0", changed)
        self.assertNotIn("row 2", changed)
        self.assertNotIn("log ·", changed)  # the footer says the same

    def test_every_row_erases_on_a_looks_ground_and_a_new_ground_paints_every_row_again(self) -> None:
        from omh.tui.screen import ERASE_TO_LINE_END, on_ground

        ground = "#211538"
        self.assertEqual(Pager("log", rows("row 0")).frame(30, 6, THEME, None), Pager("log", rows("row 0")).frame(
            30, 6, THEME), "no ground: the bytes as without one")
        pager = Pager("log", rows("row 0", "row 1"))
        plain = pager.frame(30, 6, THEME)
        grounded = pager.frame(30, 6, THEME, ground)
        self.assertIn("row 0", grounded, "a new ground paints every row again")
        self.assertEqual(grounded.count(on_ground(ERASE_TO_LINE_END, ground)), 5)  # each page row
        self.assertNotIn(on_ground(ERASE_TO_LINE_END, ground), plain)
        self.assertEqual(pager.frame(30, 6, THEME, ground), "")

    def test_a_new_size_or_an_invalidate_paints_every_row_again(self) -> None:
        pager = Pager("log", rows("row 0", "row 1"))
        pager.frame(30, 6, THEME)
        self.assertIn("row 0", pager.frame(31, 6, THEME))
        self.assertIn("row 0", pager.frame(31, 7, THEME))
        pager.invalidate()  # something else cleared the screen
        self.assertIn("row 0", pager.frame(31, 7, THEME))

    def test_the_screen_after_any_run_of_diffed_frames_is_the_one_a_full_frame_draws(self) -> None:
        generator = random.Random(5)
        words = ["alpha", "beta", "gamma", "delta", "한글 줄", "a much longer row that runs past the edge of the screen"]
        for trial in range(30):
            pager = Pager("log", [])
            screen = VTScreen(8, 24)
            for _step in range(12):
                pager.lines = rows(*(generator.choice(words) for _ in range(generator.randrange(0, 14))))
                pager.top = generator.randrange(0, 10)
                screen.feed(pager.frame(24, 8, THEME))
                with self.subTest(trial=trial, step=_step):
                    self.assertEqual(screen.lines(), fresh_screen(pager, 24, 8))

    def test_a_one_row_screen_shows_the_footer_as_it_always_did(self) -> None:
        """The footer hook (`Pager.footer`, for `/dag`'s two rows) changes no other pager: on a screen of one row
        the footer is painted over the page's only row, last."""
        pager = Pager("title", [(Span("body row"),), (Span("second"),)])
        screen = VTScreen(1, 80)
        screen.feed(pager.frame(80, 1, THEME))
        self.assertTrue(screen.line(0).startswith(" title · 1-1/2 · j/k line"), screen.line(0))
        for height in (2, 5, 24):
            screen = VTScreen(height, 80)
            screen.feed(Pager("title", [(Span("body row"),)]).frame(80, height, THEME))
            with self.subTest(rows=height):
                self.assertEqual(screen.line(0).rstrip(), "body row")
                self.assertTrue(screen.line(height - 1).startswith(" title · 1-1/1 · j/k line"))


def key(char: str) -> Key:
    return Key(CHAR, char=char)


def items_of(heights: list[int]) -> list[list[Line]]:
    return [rows(*(f"block {index} row {row}" for row in range(height))) for index, height in enumerate(heights)]


def flattened(items: list[list[Line]]) -> list[Line]:
    """The blocks as `/history` used to build them all at once: a blank row between blocks."""
    lines: list[Line] = []
    for item in items:
        if item:
            lines.extend([()] if lines else [])
            lines.extend(item)
    return lines


class HistoryPagerTests(unittest.TestCase):
    """`/history` renders a block only when a page reaches it, and pages exactly as a pager over every row would."""

    def history(self, items: list[list[Line]], calls: list[tuple[int, int]] | None = None) -> HistoryPager:
        def render(index: int, width: int, theme: object) -> list[Line]:
            if calls is not None:
                calls.append((index, width))
            return items[index]

        return HistoryPager("history", count=len(items), render=render)

    def test_every_key_shows_the_page_a_pager_over_all_the_rows_shows(self) -> None:
        generator = random.Random(11)
        for trial in range(40):
            items = items_of([generator.randrange(0, 7) for _ in range(generator.randrange(1, 30))])  # 0: a block with no rows
            lazy, eager = self.history(items), Pager("history", flattened(items))
            lazy_screen, eager_screen = VTScreen(8, 30), VTScreen(8, 30)
            lazy_screen.feed(lazy.frame(30, 8, THEME))
            eager_screen.feed(eager.frame(30, 8, THEME))
            for step in range(25):
                chars = "".join(generator.choice("jjjkk bgG") for _ in range(generator.randrange(1, 4)))
                for pager, screen in ((lazy, lazy_screen), (eager, eager_screen)):
                    for char in chars:  # several keys between two frames: each is a move of its own
                        pager.handle_key(key(char), 8)
                    screen.feed(pager.frame(30, 8, THEME))
                with self.subTest(trial=trial, step=step, keys=chars):
                    self.assertEqual(lazy_screen.lines()[:-1], eager_screen.lines()[:-1])

    def test_blocks_with_no_rows_get_no_blank_row_and_none_opens_the_history(self) -> None:
        items = items_of([0, 0, 2, 0, 1])
        lazy, eager = self.history(items), Pager("history", flattened(items))
        lazy_screen, eager_screen = VTScreen(8, 30), VTScreen(8, 30)
        lazy_screen.feed(lazy.frame(30, 8, THEME))
        eager_screen.feed(eager.frame(30, 8, THEME))
        self.assertEqual([row.rstrip() for row in lazy_screen.lines()[:4]], ["block 2 row 0", "block 2 row 1", "", "block 4 row 0"])
        self.assertEqual(lazy_screen.lines()[:-1], eager_screen.lines()[:-1])

    def test_opening_and_jumping_to_either_end_render_only_the_blocks_those_pages_reach(self) -> None:
        calls: list[tuple[int, int]] = []
        pager = self.history(items_of([3] * 2000), calls)
        first = VTScreen(24, 80)
        first.feed(pager.frame(80, 24, THEME))
        self.assertEqual(first.lines()[0].rstrip(), "block 0 row 0")
        self.assertIn("history · 1-6/2000 entries", first.lines()[-1])
        self.assertLess(len(calls), 20)  # the first page and the last one, 6 blocks each
        pager.handle_key(key("G"), 24)
        last = VTScreen(24, 80)
        last.feed(pager.frame(80, 24, THEME))
        self.assertEqual(last.lines()[-2].rstrip(), "block 1999 row 2")
        pager.handle_key(key("g"), 24)
        pager.frame(80, 24, THEME)
        self.assertLess(len(calls), 20)  # both ends were kept

    def test_paging_through_every_block_keeps_only_the_most_recent_ones(self) -> None:
        calls: list[tuple[int, int]] = []
        pager = self.history(items_of([3] * 2000), calls)
        pager.frame(80, 24, THEME)
        for _ in range(2000 * 4 // 23 + 1):
            pager.handle_key(key(" "), 24)
            pager.frame(80, 24, THEME)
        self.assertEqual(pager.item, 1994)  # the last page's top: 23 rows end with block 1999's last
        self.assertLessEqual(len(pager._kept), HISTORY_BLOCKS_KEPT)
        # Each block rendered once on the way down; the last page's first five also once at the open, to bound the
        # moves, and left to go from what was kept since no frame walks them again. The last block stays kept.
        renders = Counter(index for index, _width in calls)
        self.assertEqual(len(renders), 2000)
        self.assertEqual(sorted(index for index, count in renders.items() if count > 1), list(range(1994, 1999)))

    def test_its_fields_hide_no_method_of_pager(self) -> None:
        pager = self.history(items_of([3] * 50))
        pager.frame(80, 24, THEME)
        hidden = [name for name, value in vars(Pager).items() if callable(value) and not callable(getattr(pager, name))]
        self.assertEqual(hidden, [])
        Pager._scroll(pager, 1, 24)  # reached through the base class, as Pager's own methods reach it

    def test_a_frame_that_moves_nothing_does_not_walk_the_last_page_again(self) -> None:
        pager = self.history(items_of([3] * 2000))
        pager.frame(80, 24, THEME)  # the top page; the last page's top is found once, to bound the moves
        walked: list[int] = []
        real = pager._rendered

        def recording(index: int, cols: int, theme: object) -> list[Line]:
            walked.append(index)
            return real(index, cols, theme)

        pager._rendered = recording  # type: ignore[method-assign]
        pager.invalidate()  # a frame drawn again (a gateway event dirtied the screen): nothing moved
        pager.frame(80, 24, THEME)
        self.assertTrue(walked)
        self.assertEqual([index for index in walked if index >= 1990], [])
        pager.handle_key(key("G"), 24)  # a jump still finds it, from what was kept
        pager.frame(80, 24, THEME)
        self.assertEqual(pager.item, 1994)

    def test_a_new_size_finds_the_last_page_again(self) -> None:
        def render(index: int, width: int, theme: object) -> list[Line]:
            return rows(*(f"block {index} part {part}" for part in range(max(1, 120 // width))))  # wraps by width

        def last_page_top(cols: int, height: int) -> tuple[int, int]:
            fresh = HistoryPager("history", count=50, render=render)
            fresh.handle_key(key("G"), height)
            fresh.frame(cols, height, THEME)
            return fresh.item, fresh.offset

        pager = HistoryPager("history", count=50, render=render)
        pager.handle_key(key("G"), 10)
        tops = []
        for cols, height in ((40, 10), (80, 10), (80, 20)):  # three rows a block, then one, then a taller screen
            pager.frame(cols, height, THEME)
            tops.append((pager.item, pager.offset))
            self.assertEqual(tops[-1], last_page_top(cols, height))
        self.assertEqual(len(set(tops)), 3)

    def test_the_last_block_stays_as_first_drawn_so_the_last_page_holds(self) -> None:
        # Only the last block can still change (a reply streaming while /history is open).
        items = items_of([2] * 50)
        pager = HistoryPager("history", count=50, render=lambda index, width, theme: items[index])
        with patch("omh.tui.pager.HISTORY_BLOCKS_KEPT", 4):
            pager.frame(80, 10, THEME)  # the top page; the last page's top is found from blocks 47 to 49
            items[49] = rows(*(f"block 49 grown {part}" for part in range(5)))  # the live block grew meanwhile
            for _ in range(5):  # paging on turns the kept rows over
                pager.handle_key(key(" "), 10)
                pager.frame(80, 10, THEME)
            pager.handle_key(key("G"), 10)
            pager.invalidate()  # paint every row of the next frame
            screen = VTScreen(10, 80)
            screen.feed(pager.frame(80, 10, THEME))
        self.assertEqual(screen.lines()[-2].rstrip(), "block 49 row 1")  # its last row, as the pager first drew it

    def test_a_cache_of_one_block_still_pages_holding_the_last_block(self) -> None:
        pager = self.history(items_of([2] * 5))
        with patch("omh.tui.pager.HISTORY_BLOCKS_KEPT", 1):
            pager.frame(80, 10, THEME)  # the last block is kept first, by the walk to the last page's top
            for char in "jjG":
                pager.handle_key(key(char), 10)
                pager.frame(80, 10, THEME)
        self.assertIn(4, pager._kept)
        self.assertLessEqual(len(pager._kept), 2)  # the last block, and the one block the cap allows besides it

    def test_the_block_used_longest_ago_leaves_first(self) -> None:
        calls: list[tuple[int, int]] = []
        pager = self.history(items_of([1] * 10), calls)
        with patch("omh.tui.pager.HISTORY_BLOCKS_KEPT", 4):
            for index in (0, 1, 2, 3, 0, 4):  # block 0 used again before block 4 needs a place
                pager._rendered(index, 80, THEME)
            pager._rendered(0, 80, THEME)
        self.assertEqual([index for index, _width in calls], [0, 1, 2, 3, 4])  # 0 was kept; 1 left for 4

    def test_a_new_width_renders_the_blocks_again_at_it(self) -> None:
        calls: list[tuple[int, int]] = []
        pager = self.history(items_of([2] * 50), calls)
        pager.frame(80, 10, THEME)
        pager.frame(60, 10, THEME)
        self.assertEqual({width for index, width in calls if index == 0}, {80, 60})

    def test_a_new_theme_renders_the_blocks_again_in_it(self) -> None:
        items = items_of([2] * 50)
        themes: list[object] = []

        def render(index: int, width: int, theme: object) -> list[Line]:
            if index == 0:
                themes.append(theme)
            return items[index]

        pager = HistoryPager("history", count=len(items), render=render)
        crimson = theme_named("crimson")
        pager.frame(80, 10, THEME)
        pager.frame(80, 10, crimson)
        self.assertEqual(len(themes), 2)
        self.assertIs(themes[1], crimson)

    def test_a_move_asked_for_before_the_first_frame_is_made_at_it(self) -> None:
        pager = self.history(items_of([3] * 100))
        pager.handle_key(key("G"), 10)
        pager.handle_key(key("k"), 10)
        screen = VTScreen(10, 40)
        screen.feed(pager.frame(40, 10, THEME))
        self.assertEqual(screen.lines()[-2].rstrip(), "block 99 row 1")


if __name__ == "__main__":
    unittest.main()
