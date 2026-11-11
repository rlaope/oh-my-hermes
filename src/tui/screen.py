"""The inline live region: the only rows of the terminal the OMH TUI repaints.

Everything finished goes to the terminal's own scrollback as plain lines
(`flush_above`), so the terminal's own scrolling, selecting and copying work on
it wherever the app leaves the mouse to the terminal (and with its bypass
modifier where the app takes it: `marks`). Right below the last of them sits one live region: sticky
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

The living wallpaper (`wallpaper`): a frame passed `ambient` cells paints the
ones that fall on a blank cell, with absolute moves: a
wholly blank row whole, and on a row with text its tail, from `TEXT_GAP`
cells past the text (a terminal that draws an ambiguous-width glyph two
cells wide would otherwise push it over the row's last character); never a
band's row, whose background runs to the edge, nor the tail of a row the last
two frames both painted again (a spinner's). That holds for the caller's
rows and the rows under the region, and, where the caller asks
(`ambient_above`), the rows above its top that it flushed, so the wallpaper
stays in view over a screen full of transcript (owner's choice of
2026-10-29). Two costs come with that, and the owner took them: a selection
across several rows copies the glyphs in their tails along with the text,
and a tick that repaints a cell under a selection may end it on terminals
that clear a selection when its cells change. Turning the wallpaper off
(`/wallpaper off`) removes both. A frame that repaints or erases a row takes that row's cells with it;
between frames `paint_ambient` writes only the cells that changed. Before a
write that can scroll the screen or move rows (a flush, a frame that grows),
the cells the scroll would carry into the scrollback are blanked first and
the rest are moved with the screen (`_carry`); a new width or `clear` blanks
them all, so none reaches the scrollback.

A look's ground (`ground`): the app sets the terminal's background to a scene
look's ground with OSC 11, and a terminal that gives that colour only to the
cells written after it (Otty) keeps its own on every cell an erase clears.
So a region given a ground erases on it: the ground as the current background
before each erase (`on_ground`), which under background colour erase fills
the cells with it on every terminal. A region with no ground (the default
look, whose ground is the terminal's own, and every depth below truecolor)
writes the same bytes as without one. Blanks written over a wallpaper cell are
written on it. A new ground (a /theme preview) is painted
over the whole screen in the next frame, inside its synchronized update: the
screen is erased on it from the first row the region flushed that is still on
it, and those rows and the region's are painted again (`_reground`); nothing is
written into the scrollback. `clear` erases with no ground: it hands the screen
back to the shell, whose own background is back by then, and given the screen's
height it first paints the region's rows still on the screen on no ground.

A selection (`marks`): the app numbers the rows this region printed in
order, the rows it flushed and then its own (`doc_row`), so a flushed row
keeps its number while the screen scrolls. The region's own rows are only the
frame's: a frame can put other lines at their numbers (lines flushed that the
region never drew, rows inserted), which the caller checks before it asks
for marks there (`App._keep_selection_true`). `render(..., marks=...)` shows the cells the main
screen's selection holds on each of those rows as `highlight` draws them
(reversed): the region's own rows in the frame, the rows above it painted
again in place with absolute moves. A highlight is never carried into the
scrollback: before a write that can scroll the screen (a flush, a frame that
grows) every row above the region painted with one is painted again as it was
flushed, and the ones still on the screen get it back after the write, inside
the same synchronized update. Painting a row again takes the wallpaper cells
on it, which the wallpaper paints again. A row is mapped only where the
region's place is certain and the row is one this region flushed at the
width it has now; `forget_marks` drops what is painted without a write, for a
screen the terminal has reflowed (a resize, which the full redraw that follows
erases), and `clear` paints the rows again as they were flushed first.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import lru_cache
import unicodedata

from .escapes import strip_escapes
from .style import CSI, SGR_RESET, Line, Span, Style, is_fill
from .wallpaper import Cell
from .width import is_unpainted, line_width, truncate_line

CARRIAGE_RETURN = "\r"
NEWLINE = "\r\n"
ERASE_TO_LINE_END = f"{CSI}K"
ERASE_BELOW = f"{CSI}J"
ERASE_LINE = f"{CSI}2K"
ERASE_TO_LINE_START = f"{CSI}1K"  # EL 1: from the row's first column to the cursor's, both included
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"
# DECSCUSR: the cursor's shape. Vim mode shows a steady beam in INSERT and a steady block in NORMAL (an OMH addition:
# `hermes --cli` keeps a block in both); 0 gives the terminal's default shape back. A terminal that does not know the
# sequence ignores it.
CURSOR_SHAPE_BEAM = f"{CSI}6 q"
CURSOR_SHAPE_BLOCK = f"{CSI}2 q"
CURSOR_SHAPE_UNDERLINE = f"{CSI}4 q"
CURSOR_SHAPE_DEFAULT = f"{CSI}0 q"
AUTOWRAP_OFF = f"{CSI}?7l"
AUTOWRAP_ON = f"{CSI}?7h"
# Home, erase the screen, erase the scrollback (xterm `CSI 3 J`): the start of a full redraw.
CURSOR_HOME = f"{CSI}H"
ERASE_SCROLLBACK = f"{CSI}3J"  # ED 3: the terminal's saved lines, not the screen
CLEAR_SCREEN_AND_SCROLLBACK = f"{CSI}H{CSI}2J{ERASE_SCROLLBACK}"
# One synchronized update: the terminal holds the screen until the end mark, then shows the frame at once.
SYNC_BEGIN = f"{CSI}?2026h"
SYNC_END = f"{CSI}?2026l"
TEXT_GAP = 2  # cells left blank between a row's text and the first wallpaper glyph after it
FLUSHED_KEPT = 512  # flushed rows kept for the wallpaper above the region and a new ground (more than any screen)
# A full redraw flushes again the rows flushed last (`app.REDRAW_TAIL_ROWS` and its banner), so what `_flush` works
# out for a row is kept for this many rows, by row, width and ground: a redraw at the same width works out none again.
FLUSHED_ROWS_KEPT = 5120


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


def _is_blank(line: Line) -> bool:
    """Whether a row shows nothing: only spaces, and no background (a band's fill shows)."""
    return all(not span.text.strip() and span.style.bg is None for span in line)


def _blank_from(line: Line, width: int) -> int | None:
    """Where the wallpaper may start on a row: at its start on a blank row, `TEXT_GAP` cells past the text on one with
    text, never on a band's row (None). The text is counted as wide as a terminal can draw it: a terminal set to
    draw East Asian Ambiguous characters (`…`, `→`, `·`, Greek, box drawing) two cells wide pushes the text one cell
    further right for each, and a glyph there would cover the text, and with it, once the row scrolls, what the
    scrollback keeps of it."""
    if line and is_fill(line[-1]):
        return None
    if _is_blank(line):
        return 0
    return min(line_width(line) + _ambiguous_cells(line), width) + TEXT_GAP


def _ambiguous_cells(line: Line) -> int:
    """How many East Asian Ambiguous characters a row's text holds: the cells a terminal that draws them two cells
    wide adds to it."""
    return sum(unicodedata.east_asian_width(char) == "A" for span in line for char in span.text)


def on_ground(erase: str, ground: str | None) -> str:
    """`erase` (or a blank written over a cell) with `ground` as its background, then default attributes again;
    `erase` itself where there is no ground (see the module docstring)."""
    return f"{Style(bg=ground).sgr()}{erase}{SGR_RESET}" if ground is not None else erase


def paint_line(line: Line, width: int, ground: str | None = None) -> str:
    """The bytes for one row, written from column 0.

    Styled spans end in an SGR reset, so the row leaves default attributes
    behind. A row shorter than `width` ends with erase-to-end-of-line, on
    `ground` where there is one (`on_ground`); a full
    row does not, because on a terminal that keeps the cursor on the last
    column, erasing from there would delete the row's last glyph. A row whose
    last span is empty and has a background (`style.fill`) erases with that
    background, which a terminal paints to the right edge (background colour
    erase), so a band reaches the edge without trailing spaces to copy.
    A gutter that `joins` is painted as one run with a neighbour of the same
    look (a framed question's bar and its context), so marking it a gutter
    changes what a drag copies and not the bytes.
    """
    fill = line[-1].style if line and is_fill(line[-1]) else None
    clipped = truncate_line(without_controls(line), width, ellipsis="")
    runs: list[tuple[Style, str]] = []
    for span in clipped:
        look = replace(span.style, gutter=False, joins=False) if span.style.joins else span.style
        if runs and runs[-1][0] == look:
            runs[-1] = (look, runs[-1][1] + span.text)
        else:
            runs.append((look, span.text))
    parts: list[str] = []
    for look, text in runs:
        sgr = look.sgr()
        parts.append(f"{sgr}{text}{SGR_RESET}" if sgr else text)
    if line_width(clipped) < width:
        parts.append(f"{fill.sgr()}{ERASE_TO_LINE_END}{SGR_RESET}" if fill is not None
                     else on_ground(ERASE_TO_LINE_END, ground))
    return "".join(parts)


@lru_cache(maxsize=FLUSHED_ROWS_KEPT)
def _flushed_row(line: Line, width: int, ground: str | None = None) -> tuple[str, int | None]:
    """A row `_flush` writes: its bytes (`paint_line`) and where the wallpaper may start on it (`_blank_from`)."""
    return paint_line(line, width, ground), _blank_from(line, width)


class LiveRegion:
    def __init__(
        self, write: Callable[[str], None], at_top: bool = False, start_row: int | None = None, lead: str = "",
        ground: str | None = None, highlight: Callable[[Line, int, int], Line] | None = None,
    ) -> None:
        self._write = write
        # How a selection's cells look (`marks`): a row's line with columns low to high drawn selected.
        self._highlight = highlight
        self._flushed_total = 0  # the lines this region flushed: the number of its own first row (`doc_row`)
        self._marks: dict[int, tuple[int, int]] = {}  # the selection's columns by printed row, as the caller asked
        self._marked_above: dict[int, tuple[int, int]] = {}  # the rows above the region painted with them now
        self._ground = ground  # the look's ground every erase paints (see the module docstring); None for none
        self._regrounded = False  # the ground changed since the last frame: the next one paints every row again
        # The rows flushed above the region: each one's first blank column (None for a band, filled to the edge), for the wallpaper's `ambient_above`.
        self._above_blank: deque[int | None] = deque(maxlen=FLUSHED_KEPT)
        # The same rows' lines and the width they were flushed at, to paint them again on a new ground (`_reground`).
        self._above_lines: deque[tuple[Line, int]] = deque(maxlen=FLUSHED_KEPT)
        self._paper: dict[tuple[int, int], str] = {}  # (row, col) -> a wallpaper cell's glyph bytes (colour, char)
        self._papered_at: tuple[int, int] | None = None  # (width, rows) of the screen the wallpaper is painted on
        self._painted_over: tuple[list[int], int | None] = ([], None)  # the last frame's rows painted; erased from
        self._ambient_above = False  # the wallpaper may paint the rows this region flushed above it (`render`)
        self._inserted: tuple[int, int] | None = None  # the last frame's rows inserted with IL: (at, count)
        # The caller's rows the last two frames both painted again (a spinner's, a clock's): the wallpaper leaves their
        # tails alone, since every repaint erases the tail and the cells there would be painted again each frame.
        self._busy_rows: set[int] = set()
        self._last_painted: set[int] = set()  # the caller's rows the last frame painted
        self._lead = lead  # written first, in the first write's synchronized update
        self._rows: list[str] = []  # painted bytes of each row the region holds
        self._row = 0  # hardware cursor row, relative to the region's top
        self._parked: tuple[int, int] | None = (0, 0)
        self._width: int | None = None
        self._lines: tuple[Line, ...] = ()
        self._shown: tuple[Line, ...] = ()  # the same rows as painted: a selection's cells highlighted
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
        return len(self._rows)

    def set_ground(self, ground: str | None) -> None:
        """Erase on `ground` from now on (None: with no ground); a new one paints every row again in the next frame,
        so none keeps the ground it was erased on before."""
        if ground != self._ground:
            self._ground, self._regrounded = ground, True

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

        `screen_rows` is the terminal's height, the same since the region was made.
        """
        return self._top(screen_rows)

    def _top(self, rows: int) -> int | None:
        highest, lowest = self._top_rows(rows, self._shift, self._floor)
        return highest if highest == lowest else None

    def last_row(self, screen_rows: int) -> int | None:
        """The 0-based screen row the caller's last row is on, or None where that is not certain or it holds none."""
        return self._last(screen_rows)

    def _last(self, rows: int) -> int | None:
        """The screen row the region's last row is on, on a screen `rows` tall."""
        top = self._top(rows)
        return None if top is None or not self._rows else top + len(self._rows) - 1

    @property
    def flushed_rows(self) -> int:
        """How many lines this region flushed: the number its own first row has (`doc_row`)."""
        return self._flushed_total

    def doc_row(self, screen_row: int, screen_rows: int) -> int | None:
        """The number of the printed row on 0-based screen row `screen_row` (the rows this region flushed count from 0,
        its own rows follow them), or None where that is not certain: the region's place unknown, a row it did not
        flush (the shell's, an earlier region's, one older than it keeps) or flushed at another width, a row under it."""
        top = self._top(screen_rows)
        if top is None:
            return None
        doc = self._flushed_total + screen_row - top
        return doc if self.doc_line(doc) is not None and screen_row < top + len(self._rows) else None

    def doc_line(self, doc: int) -> Line | None:
        """Printed row `doc`'s line as written, no highlight; None for one this region does not hold."""
        index = doc - self._flushed_total
        if index >= 0:
            return self._lines[index] if index < len(self._lines) else None
        if -index > len(self._above_lines):
            return None
        line, width = self._above_lines[index]
        return line if width == self._width else None

    def forget_marks(self) -> None:
        """Forget the selection's rows painted above the region, writing nothing: the terminal reflowed the screen
        (a resize), so they are no longer where they were, and the full redraw that follows erases them."""
        self._marks, self._marked_above = {}, {}

    def rows_above(self, screen_rows: int, flushed: int = 0, height: int = 0) -> int:
        """The fewest screen rows that can lie above the region once `flushed` lines and a `height`-row frame are drawn.

        Exactly the rows above it wherever its top row is certain; otherwise
        the count for a region that started on the screen's top row.
        """
        shift, floor = self._shift, self._floor
        if flushed:
            shift, floor = self._flushed(shift, floor, flushed)
        if height:
            floor = self._framed(floor, height)
        return self._top_rows(screen_rows, shift, floor)[0]

    @staticmethod
    def _flushed(shift: int, floor: int | None, lines: int) -> tuple[int, int]:
        """`shift` and `floor` after `lines` flushed lines: n rows down, never below the screen's last row."""
        return shift + lines, 1 if floor is None else max(floor - lines, 1)

    @staticmethod
    def _framed(floor: int | None, height: int) -> int:
        """`floor` after a `height`-row frame: never below the screen's last row minus height - 1."""
        return height if floor is None else max(floor, height)

    def _move_to(self, row: int, ops: list[str]) -> None:
        """Cursor to the first column of region row `row`, which must already exist on screen."""
        if row < self._row:
            ops.append(cursor_up(self._row - row))
        elif row > self._row:
            ops.append(cursor_down(row - self._row))
        ops.append(CARRIAGE_RETURN)
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
        self._inserted = (at, count)
        self._rows = self._rows[:at] + [""] * count + self._rows[at:]
        self._lines = self._lines[:at] + ((),) * count + self._lines[at:]
        self._shown = self._shown[:at] + ((),) * count + self._shown[at:]

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
        repaint_all = width != self._width or self._regrounded
        if not repaint_all:
            self._insert_rows(lines, screen_rows, ops)
        last_rows, last_shown = self._rows, self._shown
        kept = 0 if repaint_all else min(len(last_rows), len(last_shown))
        shown = [self._marked(line, self._flushed_total + index) for index, line in enumerate(lines)]
        rows = [
            last_rows[index] if index < kept and line == last_shown[index] else self._paint(line, width)
            for index, line in enumerate(shown)
        ]
        held = max(len(self._rows), 1)  # the row the cursor is on is the region's first row
        painted_rows: list[int] = []
        erased: int | None = None
        if rows:
            self._floor = self._framed(self._floor, len(rows))
            if not self._rows:  # nothing of the region on screen yet: clear what is under its first row
                self._move_to(0, ops)
                ops.append(on_ground(ERASE_BELOW, self._ground))
                erased = 0
        if len(rows) > held:
            self._move_to(held - 1, ops)
            ops.append(NEWLINE * (len(rows) - held))
            self._row = len(rows) - 1
        for index, row in enumerate(rows):
            if repaint_all or index >= len(self._rows) or self._rows[index] != row:
                self._move_to(index, ops)
                ops.append(row)
                painted_rows.append(index)
        if any(self._rows[len(rows) :]):
            self._move_to(len(rows), ops)
            ops.append(on_ground(ERASE_BELOW, self._ground))
            erased = len(rows) if erased is None else erased
        self._busy_rows, self._last_painted = set(painted_rows) & self._last_painted, set(painted_rows)
        self._painted_over = (painted_rows, erased)
        hidden = cursor is None
        last = max(len(rows), 1) - 1
        target = (last, 0) if cursor is None else (min(max(cursor[0], 0), last), min(max(cursor[1], 0), width - 1))
        painted = bool(ops)
        toggled = hidden != self._hidden  # the caret alone appearing or going is a change to write
        self._rows = rows
        self._width = width
        self._lines = tuple(lines)
        self._shown = tuple(shown)
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
        screen_rows: int | None = None, ambient: Sequence[Cell] | None = None, ambient_above: bool = False,
        marks: Mapping[int, tuple[int, int]] | None = None,
        lower: int = 0,
    ) -> None:
        """Show `lines` as the region and park the cursor at `cursor` = (row, col) within it; None hides it.

        `lower` rows first move the region's top down (`can_lower`, `_lower`): the rows above it are painted again
        that many rows lower, from the lines it flushed there, so a region on the screen's last row that shrinks
        keeps its last row there with no blank row left above or under it.

        `flush` is flushed above the region first, in the same write: its lines
        cover the top rows of the region on screen, and `lines` are drawn from
        the row under the last of them. `screen_rows`, the terminal's height,
        lets rows added inside the region be inserted rather than paint every
        row under them again (`_insert_rows`). `ambient`
        is the living wallpaper's cells, painted on the screen's blank cells
        (`_papering`), on the rows this region flushed above it too where
        `ambient_above` says (the app asks whenever the wallpaper shows); None
        takes painted ones off. `marks` is the selection's first and last column
        on each printed row it holds (`doc_row`), drawn by `highlight`; None
        takes it off.
        """
        rows = screen_rows
        self._ambient_above = ambient_above
        self._marks = dict(marks or {}) if self._highlight is not None else {}
        grows = len(lines) > len(self._rows)
        # A highlight above the region never scrolls into the scrollback: those rows are painted as flushed first.
        ops: list[str] = self._unmark(rows) if (flush or grows) and rows is not None else []
        moving: tuple[int, int, int] | None = None
        if ambient is None or rows is None or (max(width, 1), rows) != self._papered_at:
            ops += self._unpaper()
        elif flush or grows:
            moving, lifting = self._before_moving(rows, len(flush), len(lines))
            ops += lifting
        regrounding = self._regrounded and rows is not None
        if regrounding:
            ops += self._reground(rows)
        if lower and rows is not None and self.can_lower(rows, lower):
            ops = self._unpaper() + ops + self._lower(rows, lower)
        self._inserted = None
        if flush:
            ops += self._flush(flush, width)
        written, painted = self._compose(lines, cursor, width, ops, rows)
        if regrounding:  # the frame painted every row again (`_compose`); else the next one with a height does
            self._regrounded = False
        if moving is not None and rows is not None:
            self._carry(moving, rows)
        self._forget_painted_over(rows)
        if rows is not None:
            marking = self._marking(rows)
            if marking:
                written, painted = written + marking, True
        if ambient is not None and rows is not None:
            papering = self._papering(ambient, rows)
            if papering:
                written, painted = written + papering, True
        self._send(written, painted)

    def paint_ambient(self, ambient: Sequence[Cell], screen_rows: int) -> None:
        """Repaint only the living wallpaper's cells that changed, where the region's last frame left the screen
        blank (`_papering`): the wallpaper's own tick, with no frame to build."""
        rows = screen_rows
        lead = self._unpaper() if (self._width, rows) != self._papered_at else []
        self._send(self._papering(ambient, rows, lead), True)

    def flush_above(self, lines: Sequence[Line], width: int, screen_rows: int | None = None) -> None:
        """Print `lines` permanently above the region, then draw the region again beneath them.

        The lines are written over the region's top rows; the region moves
        down by as many rows, scrolling the screen where it reaches the end,
        and once they scroll off the screen they are ordinary scrollback.
        Given `screen_rows`, the terminal's height, the rows above the region
        shown with a highlight are painted as flushed first (`render`).
        """
        frame = self._lines
        ops = self._unmark(screen_rows) + self._unpaper() + self._flush(lines, width)
        self._send(*self._compose(frame, self._cursor, width, ops))

    def _paint(self, line: Line, width: int) -> str:
        return paint_line(line, width, self._ground)

    def _forget_painted_over(self, rows: int | None) -> None:
        """Drop the wallpaper cells the frame just written painted over or erased: they are no longer on screen."""
        painted_rows, erased = self._painted_over
        self._painted_over = ([], None)
        if not self._paper or rows is None:
            return
        top = self._top(rows)
        if top is None:
            return
        gone = {top + index for index in painted_rows}
        cut = None if erased is None else top + erased
        self._paper = {at: cell for at, cell in self._paper.items()
                       if at[0] not in gone and (cut is None or at[0] < cut)}

    def _blank_starts(self, rows: int) -> dict[int, int]:
        """Screen row -> the first column of its blank cells, for the rows the wallpaper may paint on a screen `rows`
        tall (`_blank_from`): each of the caller's rows, whole where it is blank and from `TEXT_GAP` cells past its
        text where it has some, but not one the last two frames both painted again, and the rows under the region;
        above the region only where `ambient_above` was asked, the rows it flushed there, by the same rule. Empty where
        the region's place is not certain."""
        top, width = self._top(rows), self._width
        if top is None or width is None or not self._rows:
            return {}
        caller = len(self._rows)
        starts: dict[int, int] = {}
        if self._ambient_above:
            for row in range(max(top - len(self._above_blank), 0), top):
                start = self._above_blank[row - top]
                if start is not None:
                    starts[row] = start
        for index, line in enumerate(self._lines[:caller]):
            start = None if index in self._busy_rows else _blank_from(line, width)
            if start is not None:
                starts[top + index] = start
        for row in range(top + caller, rows):
            starts[row] = 0
        if self._cursor is not None and not self._hidden:
            caret_row, caret_col = self._cursor_target()
            if top + caret_row in starts:
                starts[top + caret_row] = max(starts[top + caret_row], caret_col + 1)
        return starts

    def _papering(self, ambient: Sequence[Cell], rows: int, lead: Sequence[str] = ()) -> str:
        """The bytes that paint `ambient`'s cells that fall on a blank cell (`_blank_starts`) and blank the ones
        painted before that are no longer lit, only those that changed, after `lead`, then park the cursor where the
        region left it; "" where nothing changed. Each cell is its half block in its colour over its background
        (`Cell.bg`), or the terminal's own background, the look's ground, where it has none; blanking a cell writes a
        plain space, so the ground shows there again."""
        starts, width = self._blank_starts(rows), self._width or 0
        cells: dict[tuple[int, int], str] = {}
        for cell in ambient:
            start = starts.get(cell.row)
            if start is not None and start <= cell.col < width:
                cells[cell.row, cell.col] = Style(fg=cell.fg, bg=cell.bg).sgr() + cell.char + SGR_RESET
        ops = [*lead, *(cursor_at(*at) + glyph for at, glyph in cells.items() if self._paper.get(at) != glyph)]
        ops += [cursor_at(*at) + on_ground(" ", self._ground) for at in self._paper if at not in cells]
        self._paper, self._papered_at = cells, (width, rows)
        top = self._top(rows)
        if not ops or top is None:
            return ""
        return self._absolute(ops, top)

    def _absolute(self, ops: Sequence[str], top: int) -> str:
        """`ops`, which move the cursor by absolute rows, then the cursor parked again where the region left it."""
        parked = self._parked or self._cursor_target()
        self._row, self._parked = parked[0], parked
        back = cursor_at(top + parked[0], parked[1])
        shown = "" if self._hidden else SHOW_CURSOR
        return "".join([HIDE_CURSOR, AUTOWRAP_OFF, *ops, AUTOWRAP_ON, back, shown])

    def _marked(self, line: Line, doc: int) -> Line:
        """`line`, printed row `doc`'s, with the selection's cells on it drawn by `highlight`."""
        span = self._marks.get(doc)
        return line if span is None or self._highlight is None else self._highlight(line, *span)

    def _repaint_above(self, doc: int, top: int, span: tuple[int, int] | None) -> str:
        """The bytes that paint printed row `doc`, above the region, again in place: highlighted with `span`, or as it
        was flushed for None. Its wallpaper cells go with it (the wallpaper paints them again)."""
        line, width = self._above_lines[doc - self._flushed_total]
        row = top - (self._flushed_total - doc)
        self._paper = {at: cell for at, cell in self._paper.items() if at[0] != row}
        shown = line if span is None or self._highlight is None else self._highlight(line, *span)
        return cursor_at(row, 0) + (_flushed_row(line, width, self._ground)[0] if span is None
                                    else paint_line(shown, width, self._ground))

    def _unmark(self, rows: int | None) -> list[str]:
        """The bytes that paint every row above the region shown with a highlight as it was flushed, queued before a
        write that can scroll them into the scrollback (or a `clear`); the cursor then back on the region's row."""
        marked, self._marked_above = self._marked_above, {}
        top = None if rows is None else self._top(rows)
        if not marked or top is None:
            return []
        self._parked = None
        ops = [self._repaint_above(doc, top, None) for doc in sorted(marked)]
        return [AUTOWRAP_OFF, *ops, cursor_at(top + self._row, 0), AUTOWRAP_ON]

    def _marking(self, rows: int) -> str:
        """The bytes that show the selection on the rows above the region still on the screen and take it off the ones
        it left, only those that changed, then park the cursor where the region left it; "" where nothing changed."""
        top = self._top(rows)
        if top is None:
            self._marked_above = {}
            return ""
        wanted = {doc: span for doc, span in self._marks.items()
                  if doc < self._flushed_total and 0 <= top - (self._flushed_total - doc)
                  and self.doc_line(doc) is not None}
        ops = [self._repaint_above(doc, top, None) for doc in sorted(self._marked_above) if doc not in wanted]
        ops += [self._repaint_above(doc, top, span) for doc, span in sorted(wanted.items())
                if self._marked_above.get(doc) != span]
        self._marked_above = wanted
        return self._absolute(ops, top) if ops else ""

    def _before_moving(self, rows: int, flushed: int, height: int) -> tuple[tuple[int, int, int] | None, list[str]]:
        """Before a write that flushes `flushed` lines and draws a `height`-row frame: (where the region's top is, how
        many lines are flushed, how many rows the screen will scroll), for `_carry` to move the painted cells with
        the screen afterwards, and the bytes that blank the cells the scroll would carry into the scrollback (the
        cursor then back on the region's row). The scroll is worked out as the region works out its top: the top
        moves down by the lines flushed, less what the screen scrolls."""
        top = self._top(rows)
        if top is None:
            return None, self._unpaper()
        shift, floor = self._shift, self._floor
        if flushed:
            shift, floor = self._flushed(shift, floor, flushed)
        after = self._top_rows(rows, shift, self._framed(floor, height) if height else floor)[0]
        scroll = max(top + flushed - after, 0)
        lifted = [at for at in self._paper if at[0] < scroll]
        if not lifted:
            return (top, flushed, scroll), []
        for at in lifted:
            del self._paper[at]
        self._parked = None
        ops = [cursor_at(*at) + on_ground(" ", self._ground) for at in lifted]
        return (top, flushed, scroll), [AUTOWRAP_OFF, *ops, cursor_at(top + self._row, 0), AUTOWRAP_ON]

    def _carry(self, moving: tuple[int, int, int], rows: int) -> None:
        """The painted cells where the write just made moved them: the rows the flushed lines covered are gone, the
        rest went up as far as the screen scrolled, and rows inserted with IL pushed the cells under them down (off
        the screen's end, where IL drops them, not into the scrollback)."""
        top, flushed, scroll = moving
        after = self._top(rows)
        kept: dict[tuple[int, int], str] = {}
        for (row, col), glyph in self._paper.items():
            if top <= row < top + flushed:
                continue
            row -= scroll
            if self._inserted is not None and after is not None and row >= after + self._inserted[0]:
                row += self._inserted[1]
            if 0 <= row < rows:
                kept[row, col] = glyph
        self._paper = kept

    def _unpaper(self) -> list[str]:
        """The bytes that take the painted wallpaper cells off, queued before a write that could scroll them into the
        scrollback or move them: each blanked, the cursor then back on the region's row."""
        cells, at = self._paper, self._papered_at
        self._paper, self._papered_at = {}, None
        top = None if at is None else self._top(at[1])
        if not cells or top is None:
            return []
        self._parked = None
        ops = [cursor_at(*cell) + on_ground(" ", self._ground) for cell in cells]
        return [AUTOWRAP_OFF, *ops, cursor_at(top + self._row, 0), AUTOWRAP_ON]

    def _reground(self, rows: int) -> list[str]:
        """The bytes that put a new ground under the whole screen, queued before a frame (which paints the region's
        own rows again) or a `clear`: the screen erased on it from the first row this region flushed that is still on
        the screen, so no cell keeps an earlier ground (a tail), and those flushed rows painted again on it;
        the cursor then back on the region's row. Nothing is written into the scrollback, and nothing moves. The
        wallpaper's cells there go with them (the frame paints them again). Where the region's place is not certain,
        only the region and the screen under it are erased."""
        top = self._top(rows)
        ops: list[str] = []
        if top is None:
            self._move_to(0, ops)
            return [*ops, CARRIAGE_RETURN + on_ground(ERASE_BELOW, self._ground)]
        first = max(top - len(self._above_lines), 0)
        ops.append(cursor_at(first, 0) + on_ground(ERASE_BELOW, self._ground))
        for row in range(first, top):
            line, width = self._above_lines[row - top]
            painted, blank = _flushed_row(line, width, self._ground)
            self._above_blank[row - top] = blank
            ops.append(cursor_at(row, 0) + painted)
        self._paper = {at: cell for at, cell in self._paper.items() if at[0] < first}
        self._marked_above = {}  # painted as flushed; the frame paints the selection again (`_marking`)
        self._parked = None  # the frame these go out in has autowrap off around them
        return [*ops, cursor_at(top + self._row, 0)]

    def can_lower(self, screen_rows: int, count: int) -> bool:
        """Whether the region's top can move `count` rows down (`_lower`): its place is certain, its last row is the
        screen's last row, it holds more rows than that, and it flushed every row that would then be above it, so each
        one can be painted again (none is lost from the screen that this region did not write)."""
        top = self._top(screen_rows)
        return (count > 0 and top is not None and self._last(screen_rows) == screen_rows - 1
                and len(self._rows) > count and len(self._above_lines) >= top + count)

    def _lower(self, rows: int, count: int) -> list[str]:
        """The bytes that move the region's top `count` rows down: every screen row above the new top painted again
        with the line flushed that many rows nearer the region (the last flushed line right over it), and the region's
        first `count` rows given up, so its rows keep their places under the new top. The terminal's scrollback still
        holds the lines that come back on the screen's first rows; they are on it twice once they scroll off again."""
        top = self._top(rows)
        assert top is not None
        lowered = top + count
        ops = [AUTOWRAP_OFF]
        for row in range(lowered):
            line, width = self._above_lines[row - lowered]
            painted, blank = _flushed_row(line, width, self._ground)
            self._above_blank[row - lowered] = blank
            ops.append(cursor_at(row, 0) + on_ground(ERASE_LINE, self._ground) + painted)
        self._shift += count
        self._floor = max((self._floor or 1) - count, 1)
        self._rows, self._lines, self._shown = self._rows[count:], self._lines[count:], self._shown[count:]
        self._row, self._parked = 0, None
        self._painted_over = ([], None)
        self._marked_above = {}  # painted as flushed; the frame paints the selection again (`_marking`)
        return [*ops, AUTOWRAP_ON, cursor_at(lowered, 0)]

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
            painted, blank = _flushed_row(line, width, self._ground)
            ops.append(painted)
            ops.append(NEWLINE)
            self._above_blank.append(blank)
            self._above_lines.append((line, width))
        # The cursor now sits on the row below the last flushed line: the new top.
        self._row = 0
        self._parked = None
        self._shift, self._floor = self._flushed(self._shift, self._floor, len(lines))
        self._flushed_total += len(lines)
        self._rows = self._rows[len(lines) :]
        self._lines = self._lines[len(lines) :]
        self._shown = self._shown[len(lines) :]
        return ops

    def clear(self, screen_rows: int | None = None) -> None:
        """Erase the region and leave the cursor at column 0 of its top row (resize, exit).

        Where the ground changed since the last frame (`set_ground(None)` as
        the screen goes back to the shell) and `screen_rows`, the terminal's
        height, is given, the rows this region flushed that are
        still on the screen are painted again on the new one first (`_reground`).
        """
        lead, self._lead = self._lead, ""
        if lead:
            self._write(lead)
        if not self._rows and self._parked == (0, 0):
            return
        # The rows above the region painted with a highlight as they were flushed, and the cells above its top, which
        # survive the erase below.
        ops: list[str] = self._unmark(screen_rows) + self._unpaper()
        regrounding = self._regrounded and screen_rows is not None
        if regrounding:
            ops += [AUTOWRAP_OFF, *self._reground(screen_rows)]
        self._regrounded = False
        self._move_to(0, ops)
        ops.append(ERASE_BELOW)
        # A screen painted again is one synchronized update, as a frame is, so the erased screen never shows.
        self._write(f"{SYNC_BEGIN}{''.join(ops)}{AUTOWRAP_ON}{SYNC_END}" if regrounding else "".join(ops))
        self._rows = []
        self._parked = (0, 0)
        self._width = None
        self._lines = ()
        self._shown = ()
        self._marks = {}
        self._cursor = (0, 0)
        self._start = None  # the next first frame starts wherever this region's top row was
        self._shift = 0
        self._floor = None
