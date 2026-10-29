"""The in-memory pager: `/history`, `/logs` and long slash output, on the alternate screen.

The pager never touches the live region or the terminal's scrollback. It
switches to the alternate screen, paints a page of already-rendered lines and
a footer, and switches back when the person leaves, which restores the main
screen (live region included) exactly as it was. Nothing it shows is written
anywhere else. After its first frame a pager paints only the rows that changed
since its last one, until the size changes or `invalidate` says something else
cleared the screen, each frame one synchronized update as the live region's.

`Pager` shows lines rendered beforehand. `HistoryPager` (`/history`) renders
the transcript's blocks only as a page reaches them, so a long session opens
at the cost of one page.

Keys: j / Down one line down, k / Up one line up, Space / PageDown a page
down, b / PageUp a page up, g / Home the top, G / End the bottom, q / Esc
leave.

The mouse is the pager's while it is open (`handle_mouse`): the alternate
screen has no scrollback of its own to take away, so the app asks for reports
with a held button's motion there. The wheel scrolls the page `WHEEL_LINES`
lines a notch (never a highlight: the bot board's list keeps its row). A drag
selects the cells it passes over, shown reversed, and its release hands back
their text to copy: the cells of `gutter` spans (a block's rail, a reply's
margin) left out of both, each row's trailing spaces and the empty rows at
either end dropped; a wide glyph is in when either of its cells is. A
double click picks the word under it and a triple click the row, and hands
back that; a click counts toward them only after a plain click on the same
cell (released where it was pressed, with no motion) ended less than
`CLICK_SECONDS` before, so a second drag from where the last one started is a
drag. The wheel does nothing while a drag is under way (a trackpad's inertia
keeps sending it). The selection is of the page on the screen, so a key, a
scroll or the next press lets it go. `note` is a row the footer's last row
shows instead, while the app keeps it there (what a copy did).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import ClassVar, NamedTuple
import unicodedata

from .keys import (
    BUTTON_LEFT, CHAR, DOWN, END, ESCAPE, HOME, PAGE_DOWN, PAGE_UP, UP, WHEEL_DOWN, WHEEL_UP, Key, Mouse, Paste,
)
from .screen import HIDE_CURSOR, SYNC_BEGIN, SYNC_END, paint_line, without_controls
from .style import CSI, Line, Span
from .theme import Theme
from .width import cluster_width, clusters, clusters_as_written

ALT_SCREEN_ON = f"{CSI}?1049h"
ALT_SCREEN_OFF = f"{CSI}?1049l"
FOOTER_KEYS = "j/k line · space/b page · g/G ends · drag copies · q leaves"
WHEEL_LINES = 3  # what one wheel notch scrolls, as a terminal that turns the wheel into arrows sends it
# A press this soon after a plain click released on the same cell is a double click (a word) or a triple (a row).
CLICK_SECONDS = 0.5
WORD_PUNCTUATION = "_-./~"  # what a double click keeps in a word besides letters and digits, as paths and names have
ROW_END = 1 << 30  # the last column of a selection that runs to the end of its row
Cell = tuple[int, int]  # a body cell of the screen: its row and its column, from 0
CELLS_KEPT = 128  # rows whose cells (`_cells`) are kept: more than a screen holds
CELLS_KEPT_CHARS = 256  # the longest row kept, in code points: as wide as a wide screen, so what is kept stays small
# The most blocks a `HistoryPager` keeps rendered; one scrolled back to after it left is rendered again.
HISTORY_BLOCKS_KEPT = 256


def _move_to(row: int) -> str:
    """Column 1 of 0-based screen row `row`."""
    return f"{CSI}{row + 1};1H"


@dataclass
class Pager:
    FOOTER_ROWS: ClassVar[int] = 1  # the rows `footer` paints under the page

    title: str
    lines: Sequence[Line]
    top: int = 0
    note: Line = field(default=(), init=False, repr=False, compare=False)  # the footer's last row while it is set
    # What the last frame left on each screen row (the line and its bytes), and the size it was drawn at.
    _painted: dict[int, tuple[Line, str]] = field(default_factory=dict, init=False, repr=False, compare=False)
    _size: tuple[int, int] | None = field(default=None, init=False, repr=False, compare=False)
    _shown: list[Line] = field(default_factory=list, init=False, repr=False, compare=False)  # the last frame's page
    # The selection's first and last cell as the mouse made them (either can be the earlier one), whether a drag is
    # still making it, the press the button is still down for (its cell and its click count) and whether the
    # pointer left that cell since, and the last plain click (its cell, when it was released, its click count).
    _selection: tuple[Cell, Cell] | None = field(default=None, init=False, repr=False, compare=False)
    _dragging: bool = field(default=False, init=False, repr=False, compare=False)
    _down: tuple[Cell, int] | None = field(default=None, init=False, repr=False, compare=False)
    _moved: bool = field(default=False, init=False, repr=False, compare=False)
    _click: tuple[Cell, float, int] | None = field(default=None, init=False, repr=False, compare=False)

    def invalidate(self) -> None:
        """Forget what is on the screen: the next frame paints every row."""
        self._painted = {}
        self._size = None

    def body_rows(self, rows: int) -> int:
        return max(rows - self.FOOTER_ROWS, 1)

    def _last_top(self, rows: int) -> int:
        return max(len(self.lines) - self.body_rows(rows), 0)

    def handle_key(self, event: Key | Paste, rows: int) -> bool:
        """Move by one key; False when the person left the pager."""
        if not isinstance(event, Key):
            return True
        page = self.body_rows(rows)
        char = event.char if event.name == CHAR and not event.ctrl and not event.alt else ""
        if event.name == ESCAPE or char == "q":
            return False
        if event.name == DOWN or char == "j":
            self._scroll(1, rows)
        elif event.name == UP or char == "k":
            self._scroll(-1, rows)
        elif event.name == PAGE_DOWN or char == " ":
            self._scroll(page, rows)
        elif event.name == PAGE_UP or char == "b":
            self._scroll(-page, rows)
        elif event.name == HOME or char == "g":
            self._scroll_to_end(False, rows)
        elif event.name == END or char == "G":
            self._scroll_to_end(True, rows)
        return True

    def handle_mouse(self, event: Mouse, rows: int, now: float) -> str:
        """Act on one report; the text to copy when a drag ends or a double or triple click picks a word or a row,
        else "" (a press, a drag still moving, a plain click, the wheel, a selection of nothing but blanks)."""
        if event.button in (WHEEL_UP, WHEEL_DOWN):
            if event.pressed and not self._dragging:
                self.clear_selection()
                self._scroll(WHEEL_LINES if event.button == WHEEL_DOWN else -WHEEL_LINES, rows)
            return ""
        body = self.body_rows(rows)
        cell = (min(event.y, body) - 1, event.x - 1)  # a report counts from 1; one under the page is on its last row
        if event.button == BUTTON_LEFT and event.pressed and not event.motion:
            return self._pressed(cell, event.y > body, now)
        down = self._down
        if down is None:
            return ""
        if event.motion and event.pressed:  # the held button's motion
            self._moved = self._moved or cell != down[0]
            if self._dragging and self._selection is not None:
                self._selection = (self._selection[0], cell)
            return ""
        if event.pressed:
            return ""
        self._down = None
        self._click = (down[0], now, down[1]) if not self._moved else None  # a plain click, timed from its release
        if not self._dragging or self._selection is None:
            return ""
        self._dragging = False
        return self._selected() if self._selection[0] != self._selection[1] else self.clear_selection()

    def clear_selection(self) -> str:
        self._selection, self._dragging = None, False
        return ""

    def _pressed(self, cell: Cell, under_page: bool, now: float) -> str:
        """A left press: the start of a drag, or with the one or two before it on the same cell, a word or a row."""
        last, self._click = self._click, None
        count = last[2] % 3 + 1 if last is not None and last[0] == cell and now - last[1] <= CLICK_SECONDS else 1
        self.clear_selection()
        if under_page:
            self._down = None
            return ""
        self._down, self._moved = (cell, count), False
        if count == 1:
            self._selection, self._dragging = (cell, cell), True
            return ""
        row, column = cell
        bounds = _word_at(self._shown[row] if row < len(self._shown) else (), column) if count == 2 else (0, ROW_END)
        if bounds is None:
            return ""
        self._selection = ((row, bounds[0]), (row, bounds[1]))
        return self._selected()

    def _span_on(self, row: int) -> tuple[int, int] | None:
        """The first and last column the selection holds on screen row `row`; None off it."""
        if self._selection is None:
            return None
        first, last = sorted(self._selection)
        if not first[0] <= row <= last[0]:
            return None
        return first[1] if row == first[0] else 0, last[1] if row == last[0] else ROW_END

    def _selected(self) -> str:
        """The selection's text, row by row, without gutter cells or trailing spaces; "" (and none kept) for blanks."""
        if self._selection is None:
            return ""
        first, last = sorted(self._selection)
        texts = []
        for row in range(first[0], last[0] + 1):
            low, high = self._span_on(row) or (0, -1)
            line = self._shown[row] if row < len(self._shown) else ()
            kept = (cell.text for cell in _cells(line) if cell.start <= high and cell.end >= low and not cell.gutter)
            texts.append("".join(kept).rstrip())
        while texts and not texts[-1]:
            texts.pop()  # a drag past the content: no empty rows after it
        while texts and not texts[0]:
            texts.pop(0)
        text = "\n".join(texts)
        return text if text.strip() else self.clear_selection()

    def _scroll(self, step: int, rows: int) -> None:
        self.top = min(max(self.top + step, 0), self._last_top(rows))

    def _scroll_to_end(self, bottom: bool, rows: int) -> None:
        self.top = self._last_top(rows) if bottom else 0

    def _page(self, cols: int, rows: int, theme: Theme) -> tuple[list[Line], str]:
        """The body rows of the current page, and the footer's position text."""
        body = self.body_rows(rows)
        self.top = min(self.top, self._last_top(rows))
        last = min(self.top + body, len(self.lines))
        position = f"{self.top + 1 if self.lines else 0}-{last}/{len(self.lines)}"
        return list(self.lines[self.top : self.top + body]), position

    def frame(self, cols: int, rows: int, theme: Theme) -> str:
        """The alternate screen's rows for the current page that differ from the last frame, footer on the last row.

        "" when no row changed.
        """
        if self._size != (cols, rows):
            self.invalidate()
            self._size = (cols, rows)
        shown, position = self._page(cols, rows, theme)
        self._shown = shown
        parts: list[str] = []
        body = self.body_rows(rows)
        for row in range(body):
            line, span = shown[row] if row < len(shown) else (), self._span_on(row)
            self._paint(row, _reversed(line, *span) if span is not None else line, cols, parts)
        footer = self.footer(position, theme)
        if self.note and footer:
            footer = [*footer[:-1], self.note]
        for at, line in enumerate(footer):
            if rows - len(footer) + at >= 0:  # a screen shorter than the footer keeps its last rows, over the page
                self._paint(rows - len(footer) + at, line, cols, parts)
        return SYNC_BEGIN + HIDE_CURSOR + "".join(parts) + SYNC_END if parts else ""

    def footer(self, position: str, theme: Theme) -> list[Line]:
        """The `FOOTER_ROWS` rows under the page: the title, where the page is, and the keys."""
        return [(Span(f" {self.title} · {position} · {FOOTER_KEYS} ", theme.status),)]

    def _paint(self, row: int, line: Line, cols: int, parts: list[str]) -> None:
        """Add screen row `row`'s bytes to `parts`, unless the last frame left this very line there."""
        held = self._painted.get(row)
        if held is not None and held[0] == line:
            return
        painted = paint_line(line, cols)
        self._painted[row] = (line, painted)
        parts.append(_move_to(row) + painted)


def _source_clusters(text: str) -> list[tuple[str, str]]:
    """Each cluster `text` is painted as (`width.clusters`, which is NFC), with the code points of `text` it was made
    from (`width.clusters_as_written`): a copy hands back the text as it was written, so a decomposed (NFD) macOS path
    still matches its file. Where the two do not pair one for one, the painted form stands for both."""
    painted = clusters(text)
    if text.isascii() or unicodedata.is_normalized("NFC", text):
        return [(cluster, cluster) for cluster in painted]
    written = clusters_as_written(text)
    if len(written) == len(painted) and all(
        unicodedata.normalize("NFC", unit) == cluster for unit, cluster in zip(written, painted)
    ):
        return list(zip(painted, written))
    return [(cluster, cluster) for cluster in painted]


class _Cell(NamedTuple):
    """One cluster of a row as painted: its first and last column (a wide one two, a zero-width one its base's), its
    text in the row's own code points, whether it is a gutter's, its width, and which span of the row it is in."""

    start: int
    end: int
    text: str
    gutter: bool
    width: int
    span: int


def _cells(line: Line) -> tuple[_Cell, ...]:
    """Each grapheme cluster of `line` as `screen.paint_line` measures it: on the text with no escape sequence or
    control (`screen.without_controls`), cluster by cluster within each span (`width.clusters`), so a column here is
    the column on the screen. A row of at most `CELLS_KEPT_CHARS` is kept until `forget_cells`, as a drag asks again
    for the same rows every frame; a longer one is measured each time, so what is kept stays small."""
    if sum(len(span.text) for span in line) <= CELLS_KEPT_CHARS:
        return _kept_cells(line)
    return _measured(line)


def forget_cells() -> None:
    """Let go of every row `_cells` kept: the pager that showed them has closed."""
    _kept_cells.cache_clear()


def _measured(line: Line) -> tuple[_Cell, ...]:
    cells: list[_Cell] = []
    at = 0
    for index, span in enumerate(without_controls(line)):
        for painted, cluster in _source_clusters(span.text):
            width = cluster_width(painted)
            if width == 0 and cells:
                cells.append(_Cell(cells[-1].start, cells[-1].end, cluster, span.style.gutter, 0, index))
                continue
            cells.append(_Cell(at, at + max(width, 1) - 1, cluster, span.style.gutter, width, index))
            at += width
    return tuple(cells)


_kept_cells = lru_cache(maxsize=CELLS_KEPT)(_measured)


def _word_at(line: Line, column: int) -> tuple[int, int] | None:
    """The first and last column of the word on `column` (letters, digits and `WORD_PUNCTUATION`); None on a blank,
    a gutter or past the row's end."""
    cells = _cells(line)

    def in_word(index: int) -> bool:
        base = cells[index].text[0]  # a cluster: its base decides
        return not cells[index].gutter and (base.isalnum() or base in WORD_PUNCTUATION)

    on = [index for index, cell in enumerate(cells) if cell.start <= column <= cell.end]
    # A zero-width cluster that leads the row (a BOM, a lone mark) shares column 0 with the glyph after it: that one.
    index = next((index for index in on if cells[index].width), on[0] if on else None)
    if index is None or not in_word(index):
        return None
    low = high = index
    while low > 0 and in_word(low - 1):
        low -= 1
    while high + 1 < len(cells) and in_word(high + 1):
        high += 1
    return cells[low].start, cells[high].end


def _reversed(line: Line, low: int, high: int) -> Line:
    """`line` with the clusters on columns `low` to `high` (a wide one when either of its cells is) drawn reversed, a
    selection's highlight; gutter cells keep their look, as the copy leaves them out. The text is the one painted
    (`screen.without_controls`), and a style changes only between two clusters of one span: spans are never merged,
    so each is measured and clustered as it was. A span that held only escapes is left out: kept empty, it would read
    as a fill (`style.is_fill`) that the row without the highlight does not have."""
    shown = without_controls(line)
    spans: list[Span] = []
    cells = _cells(shown)
    at = 0
    last = -1  # the span of `shown` the last piece came from
    for index, (given, span) in enumerate(zip(line, shown)):
        if not given.text:
            spans.append(span)  # a fill: the row's background to its edge
            last = -1
        while at < len(cells) and cells[at].span == index:
            cell, at = cells[at], at + 1
            lit = cell.start <= high and cell.end >= low and not span.style.gutter
            style = replace(span.style, reverse=not span.style.reverse) if lit else span.style
            if last == index and spans[-1].style == style:
                spans[-1] = Span(spans[-1].text + cell.text, style)
            else:
                spans.append(Span(cell.text, style))
            last = index
    return tuple(spans)


def _no_rows(index: int, width: int, theme: Theme) -> list[Line]:
    return []


@dataclass
class HistoryPager(Pager):
    """`/history`: the transcript's blocks, each rendered only when a page reaches it.

    `render(index, width, theme)` gives block `index`'s rows; a blank row goes
    above each block that has rows but the first such block. The page's top
    is a block and a row inside it (`item`, `offset`), so opening, moving and
    jumping to either end render only the blocks the page and the last page
    reach, at the frame's width. A move asked for before the first frame is
    made at it; after that each move is made at once, as `Pager` makes it.
    The footer counts messages (blocks), not rows. At most
    `HISTORY_BLOCKS_KEPT` blocks' rows are kept, for one width and theme, the
    last block's always once drawn (with a cap of one, it and one other).
    """

    lines: Sequence[Line] = ()
    count: int = 0
    render: Callable[[int, int, Theme], list[Line]] = _no_rows
    item: int = 0
    offset: int = 0
    _step: int = field(default=0, init=False, repr=False, compare=False)
    _to_end: bool | None = field(default=None, init=False, repr=False, compare=False)
    _kept: dict[int, list[Line]] = field(default_factory=dict, init=False, repr=False, compare=False)
    _drawn: tuple[int, Theme] | None = field(default=None, init=False, repr=False, compare=False)
    # The width and theme the kept rows, the first block with rows and the last page's top are for.
    _kept_for: tuple[int, Theme] | None = field(default=None, init=False, repr=False, compare=False)
    _first: int | None = field(default=None, init=False, repr=False, compare=False)
    # The last page's top, found for (body rows, count) at `_kept_for`; every frame bounds by it.
    _last_page: tuple[tuple[int, int], tuple[int, int]] | None = field(default=None, init=False, repr=False, compare=False)

    def _scroll(self, step: int, rows: int) -> None:
        self._step += step
        self._settle_if_drawn(rows)

    def _scroll_to_end(self, bottom: bool, rows: int) -> None:
        self._step, self._to_end = 0, bottom
        self._settle_if_drawn(rows)

    def _settle_if_drawn(self, rows: int) -> None:
        if self._drawn is not None:
            self._settle(self._drawn[0], self.body_rows(rows), self._drawn[1])

    def _rows(self, index: int, cols: int, theme: Theme) -> list[Line]:
        """Block `index`'s rows at `cols`, the blank row above it included."""
        rows = self._rendered(index, cols, theme)
        return [(), *rows] if rows and index > self._first_with_rows(cols, theme) else rows

    def _rendered(self, index: int, cols: int, theme: Theme) -> list[Line]:
        """Block `index`'s rows at `cols`, rendered once while kept; the block used longest ago leaves first.

        The last block never leaves: it is the one block that can still
        change (a reply streaming while `/history` is open), and holding it
        keeps the page, and the last page's top found from it, as first drawn.
        When it is the only block kept and that fills the cache (a cap of
        one), nothing leaves, so one block is held beside it.
        """
        rows = self._kept.pop(index, None)
        if rows is None:
            rows = self.render(index, cols, theme)
            if len(self._kept) >= HISTORY_BLOCKS_KEPT:
                oldest = next((kept for kept in self._kept if kept != self.count - 1), None)
                if oldest is not None:
                    del self._kept[oldest]
        self._kept[index] = rows
        return rows

    def shows_nothing(self, cols: int, theme: Theme) -> bool:
        """Whether no block has a row at `cols`; the rows rendered to tell are kept for the first frame."""
        self._keep_for(cols, theme)
        return self._first_with_rows(cols, theme) >= self.count

    def _keep_for(self, cols: int, theme: Theme) -> None:
        """Let go of every kept row and position found at another width or theme."""
        if self._kept_for is None or self._kept_for[0] != cols or self._kept_for[1] is not theme:
            self._kept, self._first, self._last_page = {}, None, None
            self._kept_for = (cols, theme)

    def _first_with_rows(self, cols: int, theme: Theme) -> int:
        """The first block with any rows (`count` when none has any), found once per width and theme."""
        if self._first is None:
            index = 0
            while index < self.count and not self._rendered(index, cols, theme):
                index += 1
            self._first = index
        return self._first

    def _last_page_top(self, body: int, cols: int, theme: Theme) -> tuple[int, int]:
        """Where the page starts when its last row is the last block's last row (the top, for less than a page).

        Found once per body height and block count at the width and theme
        drawn, so a frame that moves nothing walks no block for it.
        """
        key = (body, self.count)
        if self._last_page is not None and self._last_page[0] == key:
            return self._last_page[1]
        index, total = self.count, 0
        while index > 0 and total < body:
            index -= 1
            total += len(self._rows(index, cols, theme))
        top = index, max(total - body, 0)
        self._last_page = (key, top)
        return top

    def _settle(self, cols: int, body: int, theme: Theme) -> None:
        """Make the moves asked for, then keep the top a real row no lower than the last page's."""
        if self._to_end is not None:
            self.item, self.offset = self._last_page_top(body, cols, theme) if self._to_end else (0, 0)
        self.offset += self._step
        self._step, self._to_end = 0, None
        while self.offset < 0 and self.item > 0:
            self.item -= 1
            self.offset += len(self._rows(self.item, cols, theme))
        self.offset = max(self.offset, 0)
        while self.item < self.count - 1 and self.offset >= len(self._rows(self.item, cols, theme)):
            self.offset -= len(self._rows(self.item, cols, theme))
            self.item += 1
        self.item, self.offset = min((self.item, self.offset), self._last_page_top(body, cols, theme))

    def _page(self, cols: int, rows: int, theme: Theme) -> tuple[list[Line], str]:
        self._keep_for(cols, theme)
        self._drawn = (cols, theme)
        body = self.body_rows(rows)
        self._settle(cols, body, theme)
        shown: list[Line] = []
        index, skip = self.item, self.offset
        while index < self.count and len(shown) < body:
            shown.extend(self._rows(index, cols, theme)[skip:])
            index, skip = index + 1, 0
        first = self.item + 1 if self.count else 0
        return shown[:body], f"{first}-{index}/{self.count} messages"
