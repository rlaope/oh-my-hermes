"""The inline live region: the only rows of the terminal the OMH TUI repaints.

Everything finished goes to the terminal's own scrollback as plain lines
(`flush_above`), so scrolling, selecting and copying stay the terminal's
native behaviour. Right below the last of them sits one live region: sticky
prompt, streaming tail, panels, composer, info line. The region starts
where the output ends and is as tall as its frame, so it follows the content:
it grows downward until its last row is the screen's last row, and from then
on growing scrolls the screen up as printed output would. From then on the
app also keeps its frames from getting shorter (`layout`'s pad rows, blank
rows under the live block), so the region's last row stays there.

The region never learns its absolute row. Every move is relative to the
region's own top (CR, cursor up/down, erase line, erase below, "\\r\\n"), so it
works wherever the shell left the cursor and inside any scrollback state.
Growing emits newlines from the region's last row, which moves into the
blank rows under it or, on the screen's last row, scrolls the screen up from
the bottom exactly as printed output would; where the region's last row is
certain and the screen has room under it, rows added inside the region (a
streaming tail's new line) are inserted with IL at their place instead, so
the rows under them move down without being painted again. Shrinking erases
the rows freed at the region's end. The first frame also erases everything under it. Only rows
whose bytes changed since the last frame are repainted, which keeps a
selection on a static row alive. After every frame the hardware
cursor is parked where the caller asked (the composer caret), so an IME
pre-edit appears in place. A frame with no caret (a question answered by
picking: neither the composer nor a picker's filter is drawn) leaves the cursor hidden, parked on the region's last row; the next frame with
a caret shows it again.

Every row is clipped to `width` cells (a wide glyph that would straddle the
edge is dropped whole) and has its control characters and bidi controls
removed, so neither a stray escape in model output nor a long line can move
the cursor, and no embedding or override can make a bidi-aware terminal draw
a row in another order than the one measured. Autowrap is
switched off while a frame paints: if the terminal measures a glyph wider
than the width table does, the row is cut at the edge instead of wrapping
into the next row and shifting the whole region by one.

Flushing: `flush_above` writes its lines from the region's top row down,
over the region's own rows, and the region continues on the row under the
last of them. The region's rows that no flushed line covered have not moved,
so a following frame repaints only those whose bytes differ there: lines
that leave the top of the streaming tail for the transcript repaint nothing
under them. Lines beyond the region's last
row move into the blank rows under it or scroll the screen, as printed output
does.

Synchronized output: every frame that paints rows is one synchronized
update (DECSET 2026, `SYNC_BEGIN` ... `SYNC_END`), so a terminal that
supports it shows the frame whole instead of row by row, and a blinking or
animated row never flickers; a terminal that does not ignores the mode. A
frame that only parks the cursor is not wrapped. `render(..., flush=lines)`
writes the flushed lines and then the frame under them as one write and one
update, so no screen between the two shows. A region made with a `lead` (a
full redraw's erase) starts its first write with it, inside the same update,
so the erased screen never shows on its own either.

The working glow's frame (`edge_glow`): a region made with a `margin` draws
every row that many columns in from the screen's left edge, and one made with
a `footer` keeps a blank row of its own under the caller's rows. The caller
lays its rows out for a screen that much smaller (`App._edged`), and every
row count it passes in or gets back is of its own rows, the footer left out.
Those keep the screen's first and last columns and its last row free, and a
frame passed to `render` (`edge`) is painted there, and on the screen's top
row where it is lit, over the row's own text (the rest of that row is painted
again from what is under it), wherever every row above the region is one it
flushed (so the top row can be painted back): with the region's last row on
the screen's last row, or above it, where the rows under the region are blank
(the region erased them, and nothing else writes there). A band's background
stops at the region's width, short of the right margin, as it starts after
the left one. Before a write that can scroll the screen (a flush, a frame
that grows) and when the frame goes, the frame is taken off again: the top
row is painted back from what was flushed there and the edge cells are
blanked, so nothing of the frame reaches the scrollback.

Precondition: the region is never taller than the terminal. Cursor-up stops
at the top of the screen, so a taller region would lose its relative
bookkeeping; the layout's height budget guarantees this.

Where the region is on the screen (`top_row`, `last_row`) is worked out from
the writes and a starting row, and said only where it is certain. Every write moves
the top row in one of two ways: a flush of n lines moves it n rows down, but
never below the screen's last row, and a frame of h rows keeps it, but never
below the screen's last row minus h - 1, since growing past the screen's end
scrolls the region up. A frame that shrinks does not move it. Each is
`row -> min(row + shift, screen_rows - floor)`, and so is any sequence of
them, so the region keeps one `shift` and one `floor` and can say where its
top row is for any starting row. The starting row is the screen's top row
when the caller says so (`at_top`: it homed the cursor first, or at launch
moved it there after scrolling the rows above it into scrollback), or the row
the caller learned from the terminal (`start_row`: the cursor position report
after a stop), and then the top row is certain from the first write. Otherwise it
is unknown, and the top row is certain once every possible start gives the
same row, that is once the flushes have pushed it as far down as the screen
allows.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence

from .edge_glow import Edge
from .escapes import strip_escapes
from .style import CSI, SGR_RESET, Line, Span, Style, is_fill
from .width import is_unpainted, line_width, truncate_line

CARRIAGE_RETURN = "\r"
NEWLINE = "\r\n"
ERASE_TO_LINE_END = f"{CSI}K"
ERASE_BELOW = f"{CSI}J"
ERASE_LINE = f"{CSI}2K"
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"
AUTOWRAP_OFF = f"{CSI}?7l"
AUTOWRAP_ON = f"{CSI}?7h"
# Home, erase the screen, erase the scrollback (xterm `CSI 3 J`): the start of a full redraw.
CURSOR_HOME = f"{CSI}H"
ERASE_SCROLLBACK = f"{CSI}3J"  # ED 3: the terminal's saved lines, not the screen
CLEAR_SCREEN_AND_SCROLLBACK = f"{CSI}H{CSI}2J{ERASE_SCROLLBACK}"
# One synchronized update: the terminal holds the screen until the end mark, then shows the frame at once.
SYNC_BEGIN = f"{CSI}?2026h"
SYNC_END = f"{CSI}?2026l"
FLUSHED_KEPT = 512  # flushed rows kept to paint the screen's top row back under the edge frame (more than any screen)


def cursor_up(rows: int) -> str:
    return f"{CSI}{rows}A" if rows > 0 else ""


def cursor_down(rows: int) -> str:
    return f"{CSI}{rows}B" if rows > 0 else ""


def insert_lines(rows: int) -> str:
    """IL: `rows` blank rows at the cursor's row, the rows from it down moving down (no scroll margins are set)."""
    return f"{CSI}{rows}L" if rows > 0 else ""


def _insert_point(old: Sequence[Line], new: Sequence[Line]) -> int:
    """Where rows inserted into `old` make the most of its rows match `new`'s, which is that many rows longer.

    `len(old)` (growth at the end) unless an earlier point keeps more rows
    unchanged: the rows above it in place, the rows from it down moved down.
    """
    count = len(new) - len(old)
    above = [0]
    for index, line in enumerate(old):
        above.append(above[-1] + (line == new[index]))
    below = [0] * (len(old) + 1)
    for index in range(len(old) - 1, -1, -1):
        below[index] = below[index + 1] + (old[index] == new[index + count])
    best = len(old)
    for index in range(len(old) - 1, -1, -1):
        if above[index] + below[index] > above[best] + below[best]:
            best = index
    return best


def cursor_forward(cols: int) -> str:
    return f"{CSI}{cols}C" if cols > 0 else ""


def cursor_at(row: int, col: int) -> str:
    """CUP: the cursor to 0-based screen row `row`, column `col`."""
    return f"{CSI}{row + 1};{col + 1}H"


def without_controls(line: Line) -> Line:
    """The last guard before bytes reach the terminal: no escape sequence, control or bidi control in span text.

    Styles are painted from `Span.style`, never from the text, so any sequence
    found in text came from somewhere else (a gateway string, a tool summary)
    and is removed whole rather than leaving its parameters on screen.
    """
    return tuple(
        Span("".join(ch for ch in strip_escapes(span.text) if not is_unpainted(ch)), span.style) for span in line
    )


def paint_line(line: Line, width: int) -> str:
    """The bytes for one row, written from column 0.

    Styled spans end in an SGR reset, so the row leaves default attributes
    behind. A row shorter than `width` ends with erase-to-end-of-line; a full
    row does not, because on a terminal that keeps the cursor on the last
    column, erasing from there would delete the row's last glyph. A row whose
    last span is empty and has a background (`style.fill`) erases with that
    background, which a terminal paints to the right edge (background colour
    erase), so a band reaches the edge without trailing spaces to copy.
    """
    fill = line[-1].style if line and is_fill(line[-1]) else None
    clipped = truncate_line(without_controls(line), width, ellipsis="")
    parts: list[str] = []
    for span in clipped:
        sgr = span.style.sgr()
        parts.append(f"{sgr}{span.text}{SGR_RESET}" if sgr else span.text)
    if line_width(clipped) < width:
        parts.append(f"{fill.sgr()}{ERASE_TO_LINE_END}{SGR_RESET}" if fill is not None else ERASE_TO_LINE_END)
    return "".join(parts)


class LiveRegion:
    def __init__(
        self, write: Callable[[str], None], at_top: bool = False, start_row: int | None = None, lead: str = "",
        margin: int = 0, footer: bool = False,
    ) -> None:
        self._write = write
        self._margin = margin  # columns every row is drawn in from the screen's left edge
        self._footer = int(footer)  # a blank row of the region's own under the caller's rows
        self._above: deque[str] = deque(maxlen=FLUSHED_KEPT)  # painted bytes of the rows flushed, the last last
        self._framed_at: tuple[int, int] | None = None  # (cols, rows) of the screen the edge frame is painted on
        self._frame_cells: dict[tuple[int, int], str] = {}  # (row, col) -> the painted bytes of the frame there
        self._lead = lead  # written first, in the first write's synchronized update
        self._rows: list[str] = []  # painted bytes of each row the region holds
        self._row = 0  # hardware cursor row, relative to the region's top
        self._parked: tuple[int, int] | None = (0, 0)
        self._width: int | None = None
        self._lines: tuple[Line, ...] = ()
        self._cursor: tuple[int, int] | None = (0, 0)
        self._hidden = False  # the last frame left the hardware cursor hidden (it had no caret)
        # Where the top row is, from the row the region started on (`_start`: 0 when `at_top`, `start_row` when the
        # caller knows it, None when unknown): min(start + shift, screen rows - floor), floor None until a write had one.
        self._start = 0 if at_top else start_row
        self._shift = 0
        self._floor: int | None = None

    @property
    def height(self) -> int:
        """The caller's rows the region holds on screen now (0 before the first frame and after `clear`)."""
        return max(len(self._rows) - self._footer, 0)

    @property
    def caret_hidden(self) -> bool:
        """Whether the last frame had no caret, so the hardware cursor is hidden."""
        return self._hidden

    def _top_rows(self, screen_rows: int, shift: int, floor: int | None) -> tuple[int, int]:
        """(highest, lowest) screen row the top row can be on after writes summed as `shift` and `floor`."""
        bottom = screen_rows - 1 if floor is None else screen_rows - floor
        if self._start is not None:
            known = min(self._start + shift, bottom)
            return known, known
        return min(shift, bottom), min(screen_rows - 1 + shift, bottom)

    def top_row(self, screen_rows: int) -> int | None:
        """The 0-based screen row the region's top row is on, or None where that is not certain.

        `screen_rows` is the terminal's height less the footer, the same since the region was made.
        """
        return self._top(screen_rows + self._footer)

    def _top(self, rows: int) -> int | None:
        highest, lowest = self._top_rows(rows, self._shift, self._floor)
        return highest if highest == lowest else None

    def last_row(self, screen_rows: int) -> int | None:
        """The 0-based screen row the caller's last row is on, or None where that is not certain or it holds none."""
        last = self._last(screen_rows + self._footer)
        return None if last is None or len(self._rows) <= self._footer else last - self._footer

    def _last(self, rows: int) -> int | None:
        """The screen row the region's own last row (the footer, if any) is on, on a screen `rows` tall."""
        top = self._top(rows)
        return None if top is None or not self._rows else top + len(self._rows) - 1

    def rows_above(self, screen_rows: int, flushed: int = 0, height: int = 0) -> int:
        """The fewest screen rows that can lie above the region once `flushed` lines and a `height`-row frame are drawn.

        Exactly the rows above it wherever its top row is certain; otherwise
        the count for a region that started on the screen's top row.
        """
        shift, floor = self._shift, self._floor
        if flushed:
            shift, floor = self._flushed(shift, floor, flushed)
        if height:
            floor = self._framed(floor, height + self._footer)
        return self._top_rows(screen_rows + self._footer, shift, floor)[0]

    @staticmethod
    def _flushed(shift: int, floor: int | None, lines: int) -> tuple[int, int]:
        """`shift` and `floor` after `lines` flushed lines: n rows down, never below the screen's last row."""
        return shift + lines, 1 if floor is None else max(floor - lines, 1)

    @staticmethod
    def _framed(floor: int | None, height: int) -> int:
        """`floor` after a `height`-row frame: never below the screen's last row minus height - 1."""
        return height if floor is None else max(floor, height)

    def _move_to(self, row: int, ops: list[str]) -> None:
        """Cursor to the region's first column (`margin`) of region row `row`, which must already exist on screen."""
        if row < self._row:
            ops.append(cursor_up(self._row - row))
        elif row > self._row:
            ops.append(cursor_down(row - self._row))
        ops.append(CARRIAGE_RETURN + cursor_forward(self._margin))
        self._row = row

    def _insert_rows(self, lines: Sequence[Line], screen_rows: int | None, ops: list[str]) -> None:
        """Rows the frame adds inside the region, where they fit under it on the screen: inserted with IL.

        Only where the region's last row is certain and the screen has a row
        under it for every row added, so nothing scrolls and nothing under the
        region is lost; the region's rows under the insert move down with it
        and keep their bytes, so the comparison that follows paints only the
        new rows and the rows that changed. Otherwise the frame grows at its
        end as before.
        """
        count = len(lines) - len(self._lines)
        last = self._last(screen_rows) if screen_rows is not None and self._rows and count > 0 else None
        if last is None or last + count > screen_rows - 1:
            return
        at = _insert_point(self._lines, lines)
        if at == len(self._lines):
            return
        self._move_to(at, ops)
        ops.append(insert_lines(count))
        self._rows = self._rows[:at] + [""] * count + self._rows[at:]
        self._lines = self._lines[:at] + ((),) * count + self._lines[at:]

    def _compose(
        self, lines: Sequence[Line], cursor: tuple[int, int] | None, width: int, ops: list[str],
        screen_rows: int | None = None,
    ) -> tuple[str, bool]:
        """The frame's bytes, after `ops` already queued ("" when nothing changed), and whether they paint rows.

        A row whose line and width are the ones the last frame painted keeps
        that frame's bytes instead of being painted again; rows added inside
        the region are inserted first where `screen_rows` says there is room
        (`_insert_rows`). `cursor` None hides the hardware cursor and parks it
        at the start of the last row.
        """
        width = max(width, 1)
        repaint_all = width != self._width
        if not repaint_all:
            self._insert_rows(lines, screen_rows, ops)
        last_rows, last_lines = self._rows, self._lines
        kept = 0 if repaint_all else min(len(last_rows), len(last_lines))
        rows = [
            last_rows[index] if index < kept and line == last_lines[index] else self._paint(line, width)
            for index, line in enumerate(lines)
        ]
        held = max(len(self._rows), 1)  # the row the cursor is on is the region's first row
        if rows:
            self._floor = self._framed(self._floor, len(rows))
            if not self._rows:  # nothing of the region on screen yet: clear what is under its first row
                self._move_to(0, ops)
                ops.append(ERASE_BELOW)
        if len(rows) > held:
            self._move_to(held - 1, ops)
            ops.append(NEWLINE * (len(rows) - held))
            self._row = len(rows) - 1
        for index, row in enumerate(rows):
            if repaint_all or index >= len(self._rows) or self._rows[index] != row:
                self._move_to(index, ops)
                ops.append(row)
        if any(self._rows[len(rows) :]):
            self._move_to(len(rows), ops)
            ops.append(ERASE_BELOW)
        hidden = cursor is None
        last = max(len(rows), 1) - 1
        target = (last, 0) if cursor is None else (min(max(cursor[0], 0), last), min(max(cursor[1], 0), width - 1))
        painted = bool(ops)
        toggled = hidden != self._hidden  # the caret alone appearing or going is a change to write
        self._rows = rows
        self._width = width
        self._lines = tuple(lines)
        self._cursor = cursor
        self._hidden = hidden
        if not painted and target == self._parked and not toggled:
            return "", False
        park: list[str] = []
        self._move_to(target[0], park)
        park.append(cursor_forward(target[1]))  # from the region's first column
        self._parked = target
        if not painted:
            return "".join(park) + ((HIDE_CURSOR if hidden else SHOW_CURSOR) if toggled else ""), False
        shown = [] if hidden else [SHOW_CURSOR]
        return "".join([HIDE_CURSOR, AUTOWRAP_OFF, *ops, AUTOWRAP_ON, *park, *shown]), True

    def _send(self, written: str, painted: bool) -> None:
        """Write `written` behind the lead not yet written, as one synchronized update when either paints."""
        if written:
            written, painted, self._lead = self._lead + written, painted or bool(self._lead), ""
            self._write(f"{SYNC_BEGIN}{written}{SYNC_END}" if painted else written)

    def render(
        self, lines: Sequence[Line], cursor: tuple[int, int] | None, width: int, flush: Sequence[Line] = (),
        screen_rows: int | None = None, edge: Edge | None = None,
    ) -> None:
        """Show `lines` as the region and park the cursor at `cursor` = (row, col) within it; None hides it.

        `flush` is flushed above the region first, in the same write: its lines
        cover the top rows of the region on screen, and `lines` are drawn from
        the row under the last of them. `screen_rows`, the terminal's height
        less the footer, lets rows added inside the region be inserted rather
        than paint every row under them again (`_insert_rows`), and places the
        edge frame `edge`, painted over the screen's edge where it may be
        (see the module docstring); None takes a painted one off.
        """
        rows = None if screen_rows is None else screen_rows + self._footer
        if self._footer:
            lines = (*lines, ())
        grows = len(lines) > len(self._rows)
        ops = self._unframe() if flush or grows or edge is None or (edge.cols, rows) != self._framed_at else []
        if flush:
            ops += self._flush(flush, width)
        written, painted = self._compose(lines, cursor, width, ops, rows)
        if edge is not None and rows is not None:
            framing = self._frame(edge, rows, full=painted)
            if framing:
                written, painted = written + framing, True
        self._send(written, painted)

    def flush_above(self, lines: Sequence[Line], width: int) -> None:
        """Print `lines` permanently above the region, then draw the region again beneath them.

        The lines are written over the region's top rows; the region moves
        down by as many rows, scrolling the screen where it reaches the end,
        and once they scroll off the screen they are ordinary scrollback. An
        edge frame is taken off first.
        """
        frame = self._lines
        ops = self._unframe() + self._flush(lines, width)
        self._send(*self._compose(frame, self._cursor, width, ops))

    def _paint(self, line: Line, width: int) -> str:
        """`paint_line`, and with a margin, a band's background (a fill erasing to the line's end) taken back off the
        right margin, so it ends at `width` as it starts after the left margin."""
        painted = paint_line(line, width)
        if self._margin and line and is_fill(line[-1]):
            painted += CARRIAGE_RETURN + cursor_forward(self._margin + width) + ERASE_TO_LINE_END
        return painted

    def _frameable(self, rows: int) -> int | None:
        """The region's top row where an edge frame may be painted on a screen `rows` tall: where the region is is
        certain, and every row above its top is one it flushed. The rows under a region short of the screen's end
        are blank, so the frame may paint there too. None elsewhere."""
        top, last = self._top(rows), self._last(rows)
        if top is None or last is None or top > len(self._above):
            return None
        return top

    def _frame(self, edge: Edge, rows: int, full: bool) -> str:
        """The bytes that paint `edge` over a screen `rows` tall, then park the cursor where the frame left it: every
        cell when `full` (the frame just written may have erased some), else the cells that changed. "" where no
        frame may be painted or nothing changed."""
        top = self._frameable(rows)
        if top is None or len(edge.left) != rows - 2:
            return self._unframe_now()
        cells = {(0, 0): self._top_cells(edge, top), (rows - 1, 0): paint_line(edge.bottom, edge.cols)}
        for row, (left, right) in enumerate(zip(edge.left, edge.right, strict=True), start=1):
            cells[row, 0] = paint_line(left, 1)
            cells[row, edge.cols - 1] = paint_line(right, 1)
        if (edge.cols, rows) != self._framed_at:
            full = True
        ops = [cursor_at(*at) + cells[at] for at in cells if full or self._frame_cells.get(at) != cells[at]]
        self._framed_at, self._frame_cells = (edge.cols, rows), cells
        if not ops:
            return ""
        parked = self._parked or (self._row, 0)
        self._row = parked[0]
        back = cursor_at(top + parked[0], self._margin + parked[1])
        shown = "" if self._hidden else SHOW_CURSOR
        return "".join([HIDE_CURSOR, AUTOWRAP_OFF, *ops, AUTOWRAP_ON, back, shown])

    def _top_cells(self, edge: Edge, top: int) -> str:
        """The screen's top row with the frame on it, written from its first column: what is under it painted again,
        then only the frame's lit cells over that, so the row's text shows wherever the light is not."""
        ops = [ERASE_LINE, cursor_forward(self._margin), self._under(top)]
        col = 0
        for span in edge.top:
            if span.style != Style():
                ops += [cursor_at(0, col), paint_line((span,), line_width((span,)))]
            col += line_width((span,))
        return "".join(ops)

    def _under(self, top: int) -> str:
        """The painted bytes of what is on the screen's top row under the frame: the region's first row where the
        region starts there, else the row it flushed there; "" where it is neither."""
        if top == 0:
            return self._rows[0] if self._rows else ""
        return self._above[-top] if 0 < top <= len(self._above) else ""

    def _unframe(self) -> list[str]:
        """The bytes that take a painted edge frame off, queued before a write: the top row painted back from what is
        there under it, the side cells blanked, the footer erased; the cursor then back on the region's row."""
        if self._framed_at is None:
            return []
        cols, rows = self._framed_at
        self._framed_at, self._frame_cells = None, {}
        top = self._top(rows)
        if top is None:
            return []
        ops = [cursor_at(0, 0), ERASE_LINE, cursor_forward(self._margin), self._under(top)]
        for row in range(1, rows - 1):
            ops += [cursor_at(row, 0), " ", cursor_at(row, cols - 1), " "]
        ops += [cursor_at(rows - 1, 0), ERASE_LINE, cursor_at(top + self._row, self._margin)]
        self._parked = None
        return [AUTOWRAP_OFF, *ops, AUTOWRAP_ON]

    def _unframe_now(self) -> str:
        """`_unframe`'s bytes, with the cursor parked again where the region left it."""
        ops = self._unframe()
        if not ops:
            return ""
        parked = self._cursor_target()
        park: list[str] = []
        self._move_to(parked[0], park)
        park.append(cursor_forward(parked[1]))
        self._parked = parked
        return "".join([HIDE_CURSOR, *ops, *park, "" if self._hidden else SHOW_CURSOR])

    def _cursor_target(self) -> tuple[int, int]:
        """Where the last frame parked the cursor, within the region."""
        last = max(len(self._rows), 1) - 1
        cursor = self._cursor
        width = self._width or 1
        return (last, 0) if cursor is None else (min(max(cursor[0], 0), last), min(max(cursor[1], 0), width - 1))

    def _flush(self, lines: Sequence[Line], width: int) -> list[str]:
        """The bytes that write `lines` from the region's top row down, unwritten; the region then starts under them.

        The region's rows past the ones the lines covered stay where they
        were, so they are now its first rows, kept for the next frame to
        compare against.
        """
        width = max(width, 1)
        ops: list[str] = []
        self._move_to(0, ops)
        for index, line in enumerate(lines):
            painted = self._paint(line, width)
            ops.append(painted if index == 0 else cursor_forward(self._margin) + painted)
            ops.append(NEWLINE)
            self._above.append(painted)
        # The cursor now sits on the row below the last flushed line: the new top.
        self._row = 0
        self._parked = None
        self._shift, self._floor = self._flushed(self._shift, self._floor, len(lines))
        self._rows = self._rows[len(lines) :]
        self._lines = self._lines[len(lines) :]
        return ops

    def clear(self) -> None:
        """Erase the region and leave the cursor at column 0 of its top row (resize, exit)."""
        lead, self._lead = self._lead, ""
        if lead:
            self._write(lead)
        if not self._rows and self._parked == (0, 0):
            return
        ops: list[str] = self._unframe()
        self._move_to(0, ops)
        ops.append(ERASE_BELOW)
        self._write("".join(ops))
        self._rows = []
        self._parked = (0, 0)
        self._width = None
        self._lines = ()
        self._cursor = (0, 0)
        self._start = None  # the next first frame starts wherever this region's top row was
        self._shift = 0
        self._floor = None
