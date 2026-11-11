"""The composer: the multi-line input a prompt is typed into.

`Composer` is a state machine with no IO: `handle` takes one decoded key or
paste and returns what the app should do about it, `render` draws the text at
a width and reports where the caret is in cells, so the app parks the
hardware cursor there and an IME pre-edit (Korean, Japanese) shows in place.

Text is kept NFC and the caret is a str index on a cluster boundary
(`width.clusters`): a Hangul syllable, an emoji with a skin tone, a ZWJ family
or a flag is one step for the arrows and one deletion for Backspace/Delete.
A decomposed (NFD) paste is composed when it is inserted. Control characters
other than newline and tab are dropped on insert; a tab is kept and drawn as
`TAB_CELLS` spaces.

Rows wrap between words, as the transcript's echo of the sent prompt does: a
row that overflows ends before the last word that starts on it after a space
(or tab), so the spaces end the row and the next row starts with that word; a
word longer than a row breaks at the cell, cluster by cluster. Masked input
wraps by the cell alone. The spaces stay in the text and on the row they end,
so every caret position maps to exactly one (row, col). A continuation row
starts with a space only after a row that holds one word, or only spaces, and
has no room left for that space (a tab takes four cells): a space cannot hang
past the edge, where the caret before it would sit. A row filled to the last
cell is followed by an empty row, so the caret after it never sits past the
right edge. Continuation rows are indented by the prompt's width. When the
input needs more than `max_rows` rows, the visible window scrolls just enough
to keep the caret row inside it.

Keys: printable text inserts, with Alt too unless the chord came as a kitty or
modifyOtherKeys report (the legacy bytes `ESC x` are also Esc then x arriving in
one read, and the x is not lost with the Esc), except Alt+B and Alt+F, legacy
`ESC b` and `ESC f` or reported, which move a word back and forward as
readline's do (Terminal.app sends Option+Left/Right that way); Enter submits,
except right after a backslash, which it turns into a newline; Alt+Enter,
Shift+Enter and Ctrl+J insert a newline (Ctrl+Enter is Enter here; the app
decides what its submit means, and takes Ctrl+J itself as the send-now key
on an empty composer while a turn runs with a prompt queued); Backspace/Delete remove one cluster;
Left/Right move one cluster, with Ctrl or Alt one word; Up/Down move one
visual row and browse history at the first and last row; Home/End and
Ctrl+A/Ctrl+E go to the start/end of the logical line; Ctrl+U/Ctrl+K kill to
the start/end of the line (at the edge, the newline itself); Ctrl+W,
Alt+Backspace and Ctrl+Backspace delete the word before the caret; a paste
inserts as is, newlines kept; Tab completes; Esc cancels and keeps the text;
Ctrl+C clears the text and cancels, or reports an interrupt when there is no
text; Ctrl+D exits on empty input and deletes forward otherwise; Ctrl+_ (what
Ctrl+-, Ctrl+/ and Ctrl+7 send on most terminals, or Ctrl+- reported as
itself) undoes the last edit and Ctrl+Y redoes it.

Undo steps back through the edits since the last submit, at most
`UNDO_CAP`: each key or paste that changed the text is one step, a run of
characters typed one after another at the caret is one step, and so is an
edit the app makes (`replace`, `restore`). A step puts back the text, its
paste chips and the caret. A new edit drops what redo held; a submit drops
both; masked input keeps none.

A paste of more than `PASTE_CHIP_LINES` lines or `PASTE_CHIP_CHARS`
characters (Claude Code's thresholds) goes in as one chip,
`[Pasted text #1 +60 lines]`, its text held in `pastes` (memory only, until
the composer empties). The chip is atomic: the caret steps over it and
never lands inside, and a deletion that reaches it (Backspace, Delete,
Ctrl+W, Ctrl+U, Ctrl+K) takes it whole. A submit sends the text with every
chip expanded where it stands and reports the compact text beside it
(`ComposerAction.shown`), which is what the transcript shows; history keeps
the expanded text. Masked input takes a paste as typed.

An image the app attaches is a token at the caret, `[Image #1]` and a space
(`insert_image`; the app numbers them). In the text a token is one character
of the last private-use plane, which only the composer writes (`_clean` drops
one from anything inserted), so typing `[Image #1]` by hand makes no token: it
is one cluster, so the caret never lands inside it, the arrows step over it,
any deletion that reaches it takes it whole, and a row never splits it. Its
image goes with it (`images`), undo puts both back, and the app reads which
images the draft holds from `images` alone. A submit sends and shows each
token as its label and reports the images in order (`ComposerAction.images`);
history keeps the labels, so a recalled prompt is plain text and holds no
image. Masked input takes no token.

Vim mode (`vim`, Hermes' `display.vim_mode`; the app turns it on for the main
composer only) adds modal editing. The composer starts in INSERT, where every
key does what it does without vim mode except Esc, which goes to NORMAL (the
caret steps back one cluster, as Vim's does) and reports nothing; so does a
legacy Alt chord other than Alt+B and Alt+F, whose bytes are also Esc and the
key in one read: it goes to NORMAL and its key is read there. In NORMAL the
caret sits on a character, never after a line's last one, and a printable
character is a command, never text: motions `h l 0 ^ $ w b e`, `j k` (one
row, as Up and Down, history at the first and last row), `gg G` (the first
or last line, or line N with a count); `i a I A o O` go to INSERT; `x X D C s
S r<char> dd cc yy p P`, an operator `d c y` with a motion `h l 0 ^ $ w b e`
(`dw` and `cw` stop at the end of the line, `cw` on a word is `ce`), `u` and
Ctrl+R (undo, redo). A count before a command or a motion repeats it (`3w`,
`2dd`, `d2w`, `3x`, `3p`); inserting commands and `0 ^ $` take none. `w b e`
move by words between blanks (Vim's `W B E`). A deletion, a change and a yank
keep what they took for `p` and `P` (after and before the caret, or below and
above the line for whole lines), its paste chips and images with it. A paste
chip and an image token are one character to every motion and deletion. Any
other character does nothing, and so does a key that arrives while a command
is half typed (`d` then Enter): it drops the half-typed command. Backspace is
`h` and Delete `x`; every other key (arrows, Home/End, Enter, Tab, Ctrl
chords, a paste, which inserts at the caret) does what it does in INSERT,
except that Enter always submits there, a backslash before the caret or not. A
change (`c`, `s`, `o`) and what is typed after it are one undo step. A
submit starts the next prompt in INSERT. Masked input is never modal.

History is held oldest first, at most `HISTORY_CAP` entries; a submit
appends unless the text is blank or repeats the newest entry, or
`records_history` is off (the app turns it off while the composer answers a
question Hermes asked). Each entry it records is handed to `on_record` too,
which the app points at Hermes' history file (`history.py`). Masked input (secrets, sudo) draws one bullet per
cluster, refuses newlines, never browses history, never enters it, and is
shown as bullets by `repr` too.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import accumulate
import re
import unicodedata

from .keys import (
    BACKSPACE,
    CHAR,
    DELETE,
    DOWN,
    END,
    ENTER,
    ESCAPE,
    HOME,
    LEFT,
    RIGHT,
    TAB,
    UP,
    Key,
    Paste,
    is_leader_key,
)
from .style import DEFAULT_STYLE, Line, Span, Style
from .width import TAB_CELLS, cell_width, cluster_width, clusters, is_control, truncate

PROMPT = "❯ "
MASK = "•"
NEWLINE = "\n"
TAB_CHAR = "\t"
# What a row may end on: a space, as in the transcript's wrap (`width.wrap`), or a tab, drawn as spaces. A no-break
# space is not one.
WORD_BREAKS = frozenset({" ", TAB_CHAR})
# The most entries history holds, the oldest leaving first: as many as Hermes' own TUI keeps (ui-tui `history.ts`).
HISTORY_CAP = 1000
# A paste longer than this many lines, or this many characters, becomes one chip.
PASTE_CHIP_LINES = 3
PASTE_CHIP_CHARS = 800
PASTE_CHIP = "[Pasted text #{number} +{lines} lines]"
PASTE_CHIP_ONE_LINE = "[Pasted text #{number} · {chars:,} chars]"
UNDO_CAP = 100
IMAGE_LABEL = "[Image #{number}]"
# The characters that stand for image tokens in the text: the last private-use plane, which nothing typed uses.
_TOKEN_FIRST, _TOKEN_LAST = 0x100000, 0x10FFFD
UNDO_CHARS = frozenset("_-")  # with Ctrl
REDO_CHAR = "y"  # with Ctrl
# Vim mode: the editing mode's names, as the info line and Hermes' own status bar say them.
VIM_INSERT = "INSERT"
VIM_NORMAL = "NORMAL"
VIM_REPLACE = "REPLACE"
VIM_VISUAL = "VISUAL"
VIM_REDO_CHAR = "r"  # with Ctrl, in NORMAL
VIM_COUNT_CAP = 9999  # a count larger than this is this
_VIM_OPERATORS = "dcy"
_VIM_MOTIONS = ("h", "l", "0", "^", "$", "w", "W", "b", "B", "e", "E", "ge", "gE")
_DIGITS = "0123456789"
_BLANKS = (" ", TAB_CHAR)

NONE = "none"
SUBMIT = "submit"
CANCEL = "cancel"
INTERRUPT = "interrupt"
EXIT = "exit"
COMPLETE = "complete"


@dataclass(frozen=True)
class ComposerAction:
    kind: str
    text: str = ""  # the submitted text, for SUBMIT only, every paste chip expanded
    shown: str = ""  # the submitted text as the composer showed it, when chips made it differ from `text`
    chips: tuple[tuple[str, str], ...] = ()  # each chip in `shown`, its label and its text (`Composer.restore`)
    images: tuple[tuple[str, object], ...] = ()  # each image token in the text, in order: its label and its image


NOTHING = ComposerAction(NONE)
# An undo or a redo in NORMAL: it keeps its own steps, so `handle` records none for it. Told apart from NOTHING by
# identity.
_TOOK_STEP = ComposerAction(NONE)

# Readline's Alt+B and Alt+F, legacy or reported; the legacy bytes are also what stock macOS Terminal.app sends for
# Option+Left and Option+Right.
ALT_WORD_MOVES = {"b": LEFT, "f": RIGHT}


@dataclass(frozen=True)
class _Row:
    start: int  # cluster index of the row's first cluster
    end: int  # cluster index after the row's last cluster (a newline is never inside a row)
    hard: bool  # the row ends its logical line, so the position at `end` belongs to it


def _is_token(ch: str) -> bool:
    return _TOKEN_FIRST <= ord(ch) <= _TOKEN_LAST


def _fit_tokens(shape: _Shape, avail: int, images: Mapping[str, tuple[str, object]]) -> _Shape:
    """`shape` as drawn at `avail` cells: a token whose label is wider than that is cut to it, so no row overflows."""
    wide = [index for index, unit in enumerate(shape.units)
            if unit[0] in images and (shape.widths[index] or 0) > avail]
    if not wide:
        return shape
    shown, widths = list(shape.shown), list(shape.widths)
    for index in wide:
        shown[index] = truncate(shown[index], avail)
        widths[index] = cell_width(shown[index])
    return _Shape(shape.text, shape.masked, shape.units, shape.bounds, shown, widths)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


@dataclass(frozen=True)
class _Shape:
    """One text value measured: its clusters, their boundaries, and what each draws as and how wide."""

    text: str
    masked: bool
    units: list[str]
    bounds: list[int]  # str index of every cluster boundary, from 0 to len(text)
    shown: list[str]
    widths: list[int | None]  # `None` for a newline


# Where `_shape` may cut the text into chunks that segment apart: after a newline (no cluster spans one), and after
# a space when the next character is ASCII, a Hangul syllable or a CJK ideograph (none of them joins the space).
_CHUNK_EDGE = re.compile("(?<=\n)|(?<= )(?=[\x00-\x7f\uac00-\ud7a3\u4e00-\u9fff])")
_Chunk = tuple[list[str], list[str], list[int | None]]  # a chunk's clusters, what each draws as, and its widths


def _chunk(text: str, masked: bool, labels: Mapping[str, str]) -> _Chunk:
    units = clusters(text)
    shown: list[str] = []
    widths: list[int | None] = []
    for unit in units:
        if unit == NEWLINE:
            shown.append("")
            widths.append(None)
        elif unit[0] in labels:  # an image token, drawn as its label
            shown.append(labels[unit[0]])
            widths.append(cell_width(labels[unit[0]]))
        elif masked:
            shown.append(MASK)
            widths.append(1)
        elif unit == TAB_CHAR:
            shown.append(" " * TAB_CELLS)
            widths.append(TAB_CELLS)
        else:
            shown.append(unit)
            widths.append(cluster_width(unit))
    return units, shown, widths


def _shape(text: str, masked: bool, labels: Mapping[str, str], kept: dict[tuple[str, bool], _Chunk]) -> _Shape:
    """`text` measured chunk by chunk; `kept` holds the chunks measured last time, so an edit measures only its own.

    `kept` is replaced by the chunks of `text`, and must be emptied when `labels` change."""
    now: dict[tuple[str, bool], _Chunk] = {}
    units: list[str] = []
    shown: list[str] = []
    widths: list[int | None] = []
    for piece in _CHUNK_EDGE.split(text):
        key = (piece, masked)
        chunk = now[key] = now.get(key) or kept.get(key) or _chunk(piece, masked, labels)
        units += chunk[0]
        shown += chunk[1]
        widths += chunk[2]
    kept.clear()
    kept.update(now)
    bounds = list(accumulate(map(len, units), initial=0))
    return _Shape(text, masked, units, bounds, shown, widths)


def _cluster_index(bounds: Sequence[int], caret: int) -> int:
    """How many clusters lie before `caret`; a caret inside a cluster counts as its start."""
    return max(bisect_right(bounds, caret) - 1, 0)


def _clean(text: str, masked: bool) -> str:
    kept: list[str] = []
    for ch in text.replace("\r\n", NEWLINE).replace("\r", NEWLINE):
        if ch == NEWLINE:
            if not masked:
                kept.append(ch)
        elif (ch == TAB_CHAR or not is_control(ch)) and not _is_token(ch):
            kept.append(ch)
    return "".join(kept)


def _layout(widths: Sequence[int | None], avail: int, breaks: Sequence[bool]) -> list[_Row]:
    """Visual rows for clusters of these widths (`None` is a newline) at `avail` cells.

    `breaks[i]` says cluster i is a space or a tab a row may end on. A row
    that overflows ends before the last word on it that follows one, so the
    spaces end that row and the next starts with the word. With no such word
    it ends at the cell: a word longer than a row breaks there, and a space
    with no room left after a row of one word, or of only spaces, starts the
    next row. After a word moves down, the cluster that overflowed is
    measured again on the word's new row.
    """
    rows: list[_Row] = []
    start = used = 0
    for index, width in enumerate(widths):
        if width is None:
            rows.extend(_close_line(start, index, used, avail))
            start, used = index + 1, 0
            continue
        while used and used + width > avail:
            words = range(index, start, -1) if breaks else ()
            cut = next((at for at in words if breaks[at - 1] and not breaks[at]), index)
            rows.append(_Row(start, cut, hard=False))
            start, used = cut, sum(cells or 0 for cells in widths[cut:index])
        used += width
    rows.extend(_close_line(start, len(widths), used, avail))
    return rows


def _close_line(start: int, end: int, used: int, avail: int) -> list[_Row]:
    if used >= avail:  # full to the edge: the position after it gets a row of its own
        return [_Row(start, end, hard=False), _Row(end, end, hard=True)]
    return [_Row(start, end, hard=True)]


def _locate(rows: Sequence[_Row], widths: Sequence[int | None], index: int) -> tuple[int, int]:
    """(visual row, cells from the row start) of the position before cluster `index`."""
    for number, row in enumerate(rows):
        if row.start <= index < row.end or (index == row.end and row.hard):
            return number, sum(width or 0 for width in widths[row.start : index])
    return len(rows) - 1, 0


def _position_at(row: _Row, widths: Sequence[int | None], col: int) -> int:
    """The rightmost position in `row` whose column is at most `col`."""
    last = row.end if row.hard else row.end - 1
    best = row.start
    used = 0
    for index in range(row.start, last):
        used += widths[index] or 0
        if used > col:
            break
        best = index + 1
    return best


def _word_start(units: Sequence[str], index: int) -> int:
    while index > 0 and units[index - 1].isspace():
        index -= 1
    while index > 0 and not units[index - 1].isspace():
        index -= 1
    return index


def _word_end(units: Sequence[str], index: int) -> int:
    while index < len(units) and units[index].isspace():
        index += 1
    while index < len(units) and not units[index].isspace():
        index += 1
    return index


def _word_target(classes: Sequence[str], index: int, motion: str) -> int:
    """Resolve one word step on atom classes, saturating at the buffer edges."""
    size = len(classes)
    if not size:
        return 0
    index = min(index, size)
    if motion == "w":
        if index < size:
            kind = classes[index]
            while index < size and classes[index] == kind:
                index += 1
        while index < size and classes[index] == "space":
            index += 1
        return index
    if motion == "b":
        index = max(index - 1, 0)
        while index > 0 and classes[index] == "space":
            index -= 1
        while index > 0 and classes[index - 1] == classes[index]:
            index -= 1
        return index
    if motion == "ge":
        if index < size and classes[index] != "space":
            kind = classes[index]
            while index > 0 and classes[index - 1] == kind:
                index -= 1
        index = max(index - 1, 0)
        while index > 0 and classes[index] == "space":
            index -= 1
        return index
    # Preserve the after-last boundary while exhausting whitespace: NORMAL
    # clamps it to the last atom unless it is a real trailing empty hard line.
    index = min(index + 1, size)
    while index < size and classes[index] == "space":
        index += 1
    while index + 1 < size and classes[index + 1] == classes[index]:
        index += 1
    return index


def _next_word(units: Sequence[str], index: int) -> int:
    """Vim's `W`: the start of the next word, across lines; the end of the text after the last."""
    while index < len(units) and not units[index].isspace():
        index += 1
    while index < len(units) and units[index].isspace():
        index += 1
    return index


def _end_of_word(units: Sequence[str], index: int) -> int:
    """Vim's `E`: the last unit of the word after `index` (of this one when `index` is not its last)."""
    index += 1
    while index < len(units) and units[index].isspace():
        index += 1
    while index + 1 < len(units) and not units[index + 1].isspace():
        index += 1
    return min(index, len(units) - 1)


def _line_of(units: Sequence[str], index: int) -> tuple[int, int]:
    """The logical line `index` is on: the index of its first unit and of the newline that ends it (or the end)."""
    start = end = index
    while start > 0 and units[start - 1] != NEWLINE:
        start -= 1
    while end < len(units) and units[end] != NEWLINE:
        end += 1
    return start, end


def _first_blank_free(units: Sequence[str], start: int, end: int) -> int:
    """Vim's `^`: the first unit of the line `start`..`end` that is no space or tab; its last when all are."""
    index = start
    while index < end and units[index] in _BLANKS:
        index += 1
    return index if index < end else max(end - 1, start)


_QUOTE_CHARS = ('"', "'", "`")
_BRACKET_PAIRS = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{"}
_BRACKET_OPENERS = {"(": "(", ")": "(", "[": "[", "]": "[", "{": "{", "}": "{"}
_BRACKET_CLOSERS = {"(": ")", "[": "]", "{": "}"}


def _backslashes_before(units: Sequence[str], line_start: int, index: int) -> int:
    """How many backslashes run back from just before `index`, not past `line_start`."""
    count = 0
    at = index - 1
    while at >= line_start and units[at] == "\\":
        count += 1
        at -= 1
    return count


def _raw_quote(units: Sequence[str], start: int, line_end: int, quote: str) -> int | None:
    """The first `quote` from `start` before `line_end`, escaped or not."""
    at = start
    while at < line_end:
        if units[at] == quote:
            return at
        at += 1
    return None


def _closing_quote(units: Sequence[str], start: int, line_end: int, quote: str) -> int | None:
    """The first `quote` from `start` before `line_end` that no backslash escapes."""
    at = start
    while at < line_end:
        unit = units[at]
        if unit == "\\":
            at += 2
            continue
        if unit == quote:
            return at
        at += 1
    return None


@dataclass(frozen=True)
class _Register:
    """What a NORMAL deletion, change or yank took, for `p` and `P`: the text, its chips and images, and whether it
    was whole lines."""

    text: str
    pastes: dict[str, str]
    images: dict[str, tuple[str, object]]
    linewise: bool


@dataclass(frozen=True)
class _RepeatChange:
    command: str
    effective_count: int
    recipe: tuple[tuple[int, int, str], ...] = ()
    terminal: int = 0
    register: _Register | None = None
    counted: bool = True


_Snapshot = tuple[str, int, dict[str, str], dict[str, tuple[str, object]]]


@dataclass
class _InsertChange:
    before: _Snapshot
    command: str
    count: int
    origin: int
    counted: bool = True
    recipe: list[tuple[int, int, str]] = field(default_factory=list)
    eligible: bool = True
    recorded: bool = False
    retained_bytes: int = 0


class _RevisionMap(dict):
    """Composer metadata with monotonic invalidation, including in-place/ABA edits.

    Keep dict's public API; snapshots remain ordinary dictionaries. The callback
    owns no text, image bytes or atom-boundary copy.
    """

    def __init__(self, values, changed):
        super().__init__(values)
        self.changed = changed

    def __setitem__(self, key, value):
        if key not in self or self[key] != value:
            super().__setitem__(key, value)
            self.changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.changed()

    def clear(self):
        if self:
            super().clear()
            self.changed()

    def pop(self, key, *default):
        if key not in self:
            return super().pop(key, *default)
        value = super().pop(key)
        self.changed()
        return value

    def popitem(self):
        value = super().popitem()
        self.changed()
        return value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, *args, **kwargs):
        values = dict(*args, **kwargs)
        if any(key not in self or self[key] != value for key, value in values.items()):
            super().update(values)
            self.changed()

    def __ior__(self, values):
        self.update(values)
        return self


@dataclass
class Composer:
    text: str = ""
    caret: int = 0
    history: list[str] = field(default_factory=list)
    history_index: int | None = None
    masked: bool = False
    visual_anchor: int | None = None
    visual_head: int | None = None
    visual_line: bool = False
    _generation: int = field(default=0, init=False, repr=False)
    _saved_visual: tuple | None = field(default=None, init=False, repr=False)
    records_history: bool = True
    on_record: Callable[[str], None] | None = field(default=None, repr=False, compare=False)
    pastes: dict[str, str] = field(default_factory=dict, repr=False, compare=False)  # chip label -> its text
    # image token (its character in the text) -> its label and the image the app gave it
    images: dict[str, tuple[str, object]] = field(default_factory=dict, repr=False, compare=False)
    vim: bool = field(default=False, compare=False)  # modal editing (`set_vim`); `normal` says which mode
    normal: bool = field(default=False, init=False, compare=False)
    # A NORMAL command typed so far: its count, its operator (`d c y`) and the count after that, and a `g` or an `r`
    # waiting for the key that completes it.
    _count: str = field(default="", init=False, repr=False, compare=False)
    _operator: str = field(default="", init=False, repr=False, compare=False)
    _op_count: str = field(default="", init=False, repr=False, compare=False)
    _prefix: str = field(default="", init=False, repr=False, compare=False)
    _leader: bool = field(default=False, init=False, repr=False, compare=False)
    # Successful search memory is per draft, separate from transient prefixes and undo.
    _last_search: tuple[str, str] | None = field(default=None, init=False, repr=False, compare=False)
    _register: _Register | None = field(default=None, init=False, repr=False, compare=False)
    _changing: bool = field(default=False, init=False, repr=False, compare=False)  # a change went to INSERT
    _paste_count: int = field(default=0, init=False, repr=False, compare=False)
    _token_count: int = field(default=0, init=False, repr=False, compare=False)
    _draft: str = field(default="", init=False, repr=False, compare=False)
    _draft_images: dict[str, tuple[str, object]] = field(default_factory=dict, init=False, repr=False, compare=False)
    _avail: int | None = field(default=None, init=False, repr=False, compare=False)
    _scroll: int = field(default=0, init=False, repr=False, compare=False)
    # The text measured, and its rows at one width: a caret move or a redraw reuses them until the text changes.
    _shaped: _Shape | None = field(default=None, init=False, repr=False, compare=False)
    # The chunks of that text, and the image labels they were measured with (`_shape` reuses them across an edit).
    _chunks: dict[tuple[str, bool], _Chunk] = field(default_factory=dict, init=False, repr=False, compare=False)
    _chunk_labels: dict[str, str] = field(default_factory=dict, init=False, repr=False, compare=False)
    # (measured, cells, rows, the measured text as drawn at that width: a token wider than a row cut to it)
    _laid: tuple[_Shape, int, list[_Row], _Shape] | None = field(default=None, init=False, repr=False, compare=False)
    # Undo and redo: (text, caret, paste chips, image tokens) before each step, newest last.
    _undo: list[_Snapshot] = field(default_factory=list, init=False, repr=False, compare=False)
    _redo: list[_Snapshot] = field(default_factory=list, init=False, repr=False, compare=False)
    _typing_at: int | None = field(default=None, init=False, repr=False, compare=False)  # where the typed run's caret is

    _repeat_change: _RepeatChange | None = field(default=None, init=False, repr=False)
    _insert_change: _InsertChange | None = field(default=None, init=False, repr=False)
    _replaying: bool = field(default=False, init=False, repr=False)
    _bell: bool = field(default=False, init=False, repr=False)

    def __setattr__(self, name: str, value: object) -> None:
        # Masking is also changed by App without delivering a composer event.
        if name == "masked" and "masked" in self.__dict__ and self.masked != value:
            self._reset_repeat()
            self._invalidate_reselection()
            self._clear_visual()
        if name in ("text", "pastes", "images") and name in self.__dict__ and self.__dict__[name] != value:
            self._invalidate_reselection()
        if name in ("pastes", "images"):
            # A shallow repeat candidate must get callbacks bound to itself,
            # never to the live composer; committed maps likewise rebind here.
            value = _RevisionMap(value, self._metadata_changed)
            if name == "images":
                self._shaped = self._laid = None
        object.__setattr__(self, name, value)

    def take_bell(self) -> bool:
        """Drain the transient notification; terminal policy belongs to App."""
        bell, self._bell = self._bell, False
        return bell

    def _discard_insert_recipe(self, *, bell: bool = False) -> None:
        session = self._insert_change
        if session is not None:
            session.eligible = False
            session.recipe.clear()
            session.retained_bytes = 0
        self._bell |= bell

    def _retain_repeat(self, change: _RepeatChange) -> None:
        from .vim_repeat import _utf8
        owned = sum(_utf8(payload) for _at, _deleted, payload in change.recipe)
        # Only arguments, not semantic command spelling, are owned text.
        if change.command.startswith("r"):
            owned += _utf8(change.command[1:])
        register = change.register
        images = 0
        if register is not None:
            owned += _utf8(register.text)
            for label, text in register.pastes.items():
                owned += max(1, register.text.count(label)) * _utf8(text)
            for token, (label, _image) in register.images.items():
                occurrences = max(1, register.text.count(token))
                images += occurrences
                owned += occurrences * _utf8(label)
        if len(change.recipe) > 9999 or owned > 1024 * 1024 or images > 256:
            self._bell = True
            return
        self._repeat_change = change

    def _reset_repeat(self) -> None:
        self._repeat_change = None
        self._insert_change = None

    def __post_init__(self) -> None:
        self._set(self.text, min(max(self.caret, 0), len(self.text)))

    def __repr__(self) -> str:
        text = MASK * len(clusters(self.text)) if self.masked else self.text
        return f"Composer(text={text!r}, caret={self.caret}, masked={self.masked})"

    # -- editing primitives ---------------------------------------------------

    def _measured(self) -> _Shape:
        """The text's `_Shape`, worked out again only when the text or the mask changed."""
        shape = self._shaped
        if shape is None or shape.masked != self.masked or shape.text != self.text:
            labels = {token: label for token, (label, _image) in self.images.items()}
            if labels != self._chunk_labels:
                self._chunks.clear()
                self._chunk_labels = labels
            shape = self._shaped = _shape(self.text, self.masked, labels, self._chunks)
        return shape

    def _rows(self, avail: int) -> tuple[_Shape, list[_Row]]:
        """The measured text and its visual rows at `avail` cells, laid out again only when either changed."""
        shape = self._measured()
        laid = self._laid
        if laid is None or laid[0] is not shape or laid[1] != avail:
            fitted = _fit_tokens(shape, avail, self.images)
            breaks = [] if shape.masked else [unit in WORD_BREAKS for unit in shape.units]
            laid = self._laid = (shape, avail, _layout(fitted.widths, avail, breaks), fitted)
        return laid[3], laid[2]

    def _set(self, text: str, caret: int) -> None:
        """Store `text` as NFC with the caret moved to the matching cluster boundary."""
        full = _nfc(text)
        self.text = full
        bounds = self._measured().bounds
        self.caret = bounds[_cluster_index(bounds, min(len(_nfc(text[:caret])), len(full)))]

    def _replace(self, start: int, end: int, insert: str = "") -> None:
        session = self._insert_change
        record = None
        if session is not None and session.eligible and not self._replaying:
            _units, edges, _index = self._atoms()
            if start in edges and end in edges:
                record = (edges.index(start) - session.origin, edges.index(end) - edges.index(start), insert)
            else:
                session.eligible = False
        if self.pastes and start < end:  # a deletion that reaches a chip takes it whole
            for chip_start, chip_end in self._chip_spans():
                if chip_start < end and chip_end > start:
                    start, end = min(start, chip_start), max(end, chip_end)
        self._set(self.text[:start] + insert + self.text[end:], start + len(insert))
        if self.pastes:
            self.pastes = {label: text for label, text in self.pastes.items() if label in self.text}
            self._caret_off_chip(forward=True)
        if self.images:
            self.images = {token: image for token, image in self.images.items() if token in self.text}
            self._unjoin_tokens()

        if record is not None and session is not None:
            from .vim_repeat import _utf8
            session.retained_bytes += _utf8(record[2])
            if session.retained_bytes > 1024 * 1024:
                self._discard_insert_recipe(bell=True)
                return
            if session.recipe and record[1] == 0:
                offset, deleted, payload = session.recipe[-1]
                if deleted == 0 and record[0] == offset + len(clusters(payload)):
                    session.recipe[-1] = (offset, 0, payload + record[2])
                else:
                    session.recipe.append(record)
            else:
                session.recipe.append(record)
            if len(session.recipe) > 9999:
                self._discard_insert_recipe(bell=True)

    def _unjoin_tokens(self) -> None:
        """Drop what joined a token's cluster (a combining mark typed after it), which would be neither drawn nor
        fit to send: the token stays one cluster that is only its label."""
        shape = self._measured()
        if not any(len(unit) > 1 and unit[0] in self.images for unit in shape.units):
            return
        before = _cluster_index(shape.bounds, self.caret)
        units = [unit[0] if unit[0] in self.images else unit for unit in shape.units]
        self._set("".join(units), len("".join(units[:before])))

    def _chip_spans(self) -> list[tuple[int, int]]:
        """Every chip's (start, end) in the text, in order."""
        spans: list[tuple[int, int]] = []
        for label in self.pastes:
            index = self.text.find(label)
            while index >= 0:
                spans.append((index, index + len(label)))
                index = self.text.find(label, index + len(label))
        return sorted(spans)

    def _caret_off_chip(self, forward: bool) -> None:
        """A caret that fell inside a chip goes to its end (`forward`) or its start."""
        for start, end in self._chip_spans():
            if start < self.caret < end:
                self.caret = end if forward else start
                return

    def shown(self) -> str:
        """The composer's text as its row shows it: a chip as its label, an image token as its label."""
        return self._labelled(self.text)

    def expanded(self, text: str | None = None) -> str:
        """`text` (the composer's own by default) with every chip replaced by the text it holds, every image token by
        its label."""
        text = self.text if text is None else text
        if self.pastes:
            parts: list[str] = []
            done = 0
            for start, end in self._chip_spans() if text == self.text else []:
                parts.append(text[done:start])
                parts.append(self.pastes[text[start:end]])
                done = end
            parts.append(text[done:])
            text = "".join(parts)
        return self._labelled(text)

    def _labelled(self, text: str) -> str:
        """`text` with every image token replaced by its label, and a token character no image is mapped to dropped:
        none leaves the composer."""
        return "".join(self.images[ch][0] if ch in self.images else "" if _is_token(ch) else ch for ch in text)

    def _new_token(self) -> str:
        """A token character neither the text nor `images` holds."""
        for _ in range(_TOKEN_LAST - _TOKEN_FIRST + 1):
            token = chr(_TOKEN_FIRST + self._token_count % (_TOKEN_LAST - _TOKEN_FIRST + 1))
            self._token_count += 1
            if token not in self.text and token not in self.images:
                return token
        raise ValueError("image token pool exhausted")

    def _tokens_for(self, text: str, images: Sequence[tuple[str, object]]) -> str:
        """`text` with the first `label` of each of `images` (label, image) made that image's token again."""
        for label, image in images:
            at = text.find(label)
            if at >= 0:
                token = self._new_token()
                self.images[token] = (label, image)
                text = text[:at] + token + text[at + len(label) :]
        return text

    def insert_image(self, label: str, image: object) -> bool:
        self._clear_visual()
        """An image token drawn as `label` at the caret, a space on each side of it unless the text has one there (or
        it starts the text); one undo step. False, and nothing inserted, when the input is masked."""
        if self.masked:
            return False
        self._drop_pending()
        if self._insert_change is not None:
            self._discard_insert_recipe()
        before = self._state()
        token = self._new_token()
        self.images[token] = (label, image)
        lead = "" if self.caret == 0 or self.text[self.caret - 1].isspace() else " "
        trail = "" if self.text[self.caret : self.caret + 1].isspace() else " "
        self._replace(self.caret, self.caret, lead + token + trail)
        self._step(before, typed=False)
        self._clamp_normal()
        return True

    def _insert_paste(self, text: str) -> None:
        """A paste: a long one (and not masked) as a chip, anything else as typed.

        A chip's number is one no label in the text has, chips `restore` put back included.
        """
        cleaned = _clean(text, self.masked)
        lines = len(cleaned.rstrip(NEWLINE).split(NEWLINE))
        if self.masked or not (lines > PASTE_CHIP_LINES or len(cleaned) > PASTE_CHIP_CHARS):
            self._insert(text)
            return
        label = self._chip_label(cleaned)
        self.pastes[label] = cleaned
        self._replace(self.caret, self.caret, label)

    def _chip_label(self, cleaned: str, taken: Collection[str] = ()) -> str:
        """A label for a chip holding `cleaned` whose number no label in the text has, nor any in `pastes` or
        `taken`."""
        lines = len(cleaned.rstrip(NEWLINE).split(NEWLINE))
        label = ""
        while not label or label in self.text or label in self.pastes or label in taken:
            self._paste_count += 1
            label = (
                PASTE_CHIP.format(number=self._paste_count, lines=lines)
                if lines > 1
                else PASTE_CHIP_ONE_LINE.format(number=self._paste_count, chars=len(cleaned))
            )
        return label

    def _insert(self, text: str) -> None:
        cleaned = _clean(text, self.masked)
        if cleaned:
            self._replace(self.caret, self.caret, cleaned)

    def replace(self, start: int, end: int, text: str, images: Sequence[tuple[str, object]] = ()) -> None:
        """Put `text` (cleaned as a paste is) in place of `self.text[start:end]`; the caret lands after it. One undo step.

        `images` (label, image) are tokens again where their labels stand in `text`."""
        self._reset_repeat()
        self._invalidate_reselection()
        self._clear_visual()
        before = self._state()
        self._replace(start, end, self._tokens_for(_clean(text, self.masked), images))
        self._step(before, typed=False)
        self._clamp_normal()

    def restore(self, shown: str, chips: Sequence[tuple[str, str]], images: Sequence[tuple[str, object]] = ()) -> None:
        """Put back, at the caret, a text a submit showed as `shown`: its `chips` (label, text) are chips again, and
        its `images` (label, image) tokens."""
        self._reset_repeat()
        self._invalidate_reselection()
        self._clear_visual()
        before = self._state()
        self.pastes.update(chips)
        self._replace(self.caret, self.caret, self._tokens_for(_clean(shown, self.masked), images))
        self._step(before, typed=False)
        self._clamp_normal()

    def _state(self) -> _Snapshot:
        return self.text, self.caret, dict(self.pastes), dict(self.images)

    def _step(self, before: _Snapshot, typed: bool) -> None:
        """Keep `before` as an undo step when the text changed since, unless it continues a typed run."""
        if self._replaying:
            return
        session = self._insert_change
        if session is not None:
            if not session.recorded and self.text != session.before[0]:
                if not self.masked:
                    self._undo.append(session.before)
                    del self._undo[:-UNDO_CAP]
                self._redo.clear()
                session.recorded = True
            return
        if before[0] == self.text:
            if before[1] != self.caret:
                self._typing_at = None  # a caret move ends the run
            return
        if not self.masked and not (typed and self._typing_at == before[1]):
            self._undo.append(before)
            del self._undo[:-UNDO_CAP]
        self._redo.clear()
        self._typing_at = self.caret if typed else None

    def _take_step(self, source: list[_Snapshot], target: list[_Snapshot]) -> None:
        """Undo (from `_undo`) or redo (from `_redo`) one step; the state left goes on the other list."""
        # Traversal ends capture even when there is no step to take. Do not
        # finish it: undone insertion text must never become the next dot.
        self._discard_insert_recipe()
        self._insert_change = None
        self._clear_visual()
        if not source:
            return
        target.append(self._state())
        text, caret, pastes, images = source.pop()
        self._invalidate_reselection()
        self.pastes = dict(pastes)
        self.images = dict(images)
        self._set(text, caret)
        self._typing_at = None
        self.history_index = None  # the text is no history entry any more
        self._draft, self._draft_images = "", {}

    def _units(self) -> tuple[list[str], list[int], int]:
        """Clusters, their boundaries, and the caret's cluster index."""
        shape = self._measured()
        return shape.units, shape.bounds, _cluster_index(shape.bounds, self.caret)

    def _load(self, text: str) -> None:
        self._invalidate_reselection()
        self._clear_visual()
        self._reset_repeat()
        self._set(text, len(text))
        self._scroll = 0

    def _clear(self) -> None:
        self._last_search = None
        self._load("")
        self.history_index = None
        self._draft, self._draft_images = "", {}
        self.pastes = {}
        self.images = {}
        self._paste_count = 0

    # -- key handling ---------------------------------------------------------

    def handle(self, event: Key | Paste) -> ComposerAction:
        if self.masked:
            self._invalidate_reselection()
            self._clear_visual()
            self._reset_repeat()
        if isinstance(event, Paste):
            self._clear_visual()
        if isinstance(event, Paste) and self._insert_change is not None:
            self._discard_insert_recipe()
        return self._handle_repeat_event(event)

    def _handle_repeat_event(self, event: Key | Paste) -> ComposerAction:
        # Followers are consumed before even the shared undo/redo chords can dispatch.
        if self._leader and isinstance(event, Key):
            self._drop_pending()
            return NOTHING
        if isinstance(event, Key) and event.name == CHAR and event.ctrl and not event.alt:
            redo = event.char == REDO_CHAR or (self.normal and event.char == VIM_REDO_CHAR)
            if event.char in UNDO_CHARS or redo:
                self._drop_pending()
                self._take_step(self._redo, self._undo) if redo else self._take_step(self._undo, self._redo)
                self._clamp_normal()
                return NOTHING
        if (self.vim and self.normal and not self.visual and not self.masked and isinstance(event, Key)
                and event.name == CHAR and event.char == "." and not event.ctrl and not event.alt
                and not self._operator and not self._prefix):
            # Dot owns its snapshot after admission; the generic edit wrapper
            # must not copy maps or normalize the caret on a rejected replay.
            self._normal_char(".")
            return NOTHING
        if (self.vim and self.normal and not self.visual and not self.masked
                and isinstance(event, Key) and event.name == CHAR
                and not (event.ctrl or event.alt) and not self._operator
                and (self._prefix == "g" or (not self._prefix and
                     (event.char == "g" or (event.char in _DIGITS and
                      (event.char != "0" or self._count)))))):
            # Counts and g initiation are grammar, not edits or motions. Defer
            # atom normalization until an actual gg/ge/gE motion completes;
            # otherwise a rejected gv could already have moved a stale caret.
            follower = self._prefix == "g"
            self._normal_command(event.char)
            if follower and event.char in "geE":
                self._clamp_normal()
            return NOTHING
        before = self._state()
        modal = self._modal(event) if self.vim and not self.masked else None
        if modal is _TOOK_STEP:
            self._clamp_normal()
            return NOTHING
        action = self._handle(event) if modal is None else modal
        if action.kind == SUBMIT:
            self._undo.clear()
            self._redo.clear()
            self._typing_at = None
            self.normal = False  # the next prompt starts in INSERT
            self._drop_pending()
        else:
            typed = modal is None and isinstance(event, Key) and event.name == CHAR and not event.ctrl and not event.alt
            self._step(before, typed)
            if self._changing and before[0] != self.text:
                self._typing_at = self.caret  # what is typed next joins the change's undo step
        self._changing = False
        self._clamp_normal()
        return action

    # -- vim mode ---------------------------------------------------------------

    def set_vim(self, on: bool) -> None:
        """Modal editing on or off; either way the composer is in INSERT with no command half typed."""
        self._reset_repeat()
        self._invalidate_reselection()
        self._clear_visual()
        self.vim = on
        self._last_search = None
        self.normal = False
        self._drop_pending()

    @property
    def vim_label(self) -> str:
        """The editing mode or pending single-replacement cue; empty outside Vim."""
        if not self.vim or self.masked:
            return ""
        if self.visual:
            return "VISUAL LINE" if self.visual_line else VIM_VISUAL
        if self.normal and self._leader:
            return f"{VIM_NORMAL} · SPC"
        if self.normal and self._prefix == "r":
            return VIM_REPLACE
        return VIM_NORMAL if self.normal else VIM_INSERT

    @property
    def leader(self) -> bool:
        """Whether a Vim leader sequence is waiting for its next key."""
        return self._leader

    @property
    def pending(self) -> bool:
        """Whether a NORMAL command or leader is half typed, which Esc drops."""
        return bool(self._count or self._operator or self._op_count or self._prefix or self._leader)

    @property
    def visual(self) -> bool:
        return self.visual_anchor is not None

    @property
    def visual_span(self) -> tuple[int, int] | None:
        if not self.visual:
            return None
        units, bounds, _index = self._atoms()
        assert self.visual_anchor is not None and self.visual_head is not None
        lo, hi = sorted((self.visual_anchor, self.visual_head))
        if self.visual_line:
            lo = _line_of(units, lo)[0]
            hi = _line_of(units, hi)[1]
            return bounds[lo], bounds[min(hi + 1, len(units))]
        return bounds[lo], bounds[min(hi + 1, len(units))]

    def _invalidate_reselection(self) -> None:
        self._generation = self.__dict__.get("_generation", 0) + 1
        self._saved_visual = None

    def _metadata_changed(self) -> None:
        self._invalidate_reselection()
        self._shaped = self._laid = None

    def _save_visual(self) -> None:
        if self.visual:
            self._saved_visual = (self._generation, self.visual_anchor, self.visual_head, self.visual_line)

    def _restore_visual(self) -> None:
        saved = self._saved_visual
        if saved is None:
            return
        generation, anchor, head, line = saved
        units, bounds, _ = self._atoms()
        if (generation != self._generation or type(anchor) is not int or type(head) is not int
                or type(line) is not bool
                or not 0 <= anchor <= len(units) or not 0 <= head <= len(units)):
            self._saved_visual = None
            return
        self.visual_anchor, self.visual_head, self.visual_line = anchor, head, line
        self.caret = bounds[head]

    def _exit_visual(self) -> None:
        self._save_visual()
        self._clear_visual()

    def _clear_visual(self) -> None:
        self.visual_anchor = self.visual_head = None
        self.visual_line = False
        self._drop_pending()

    def _visual_char(self, char: str) -> ComposerAction:
        if char.isascii() and char.isdigit() and (char != "0" or self._count) and not self._prefix:
            self._count = str(min(int(self._count + char), VIM_COUNT_CAP))
            return NOTHING
        prefix, self._prefix = self._prefix, ""
        if not prefix and char in "gfFtT":
            self._prefix = char
            return NOTHING
        count = int(self._count) if self._count else None
        self._drop_pending()
        if not prefix and char in "vV":
            line = char == "V"
            if self.visual_line == line:
                self._exit_visual()
            else:
                self.visual_line = line
            return NOTHING
        if not prefix and char == "u":
            self._clear_visual()
            self._take_step(self._undo, self._redo)
            return _TOOK_STEP
        if not prefix and char in _VIM_OPERATORS:
            units, _bounds, _index = self._atoms()
            assert self.visual_anchor is not None and self.visual_head is not None
            lo, hi = sorted((self.visual_anchor, self.visual_head))
            linewise = self.visual_line
            line_count = 1
            if linewise:
                lo = _line_of(units, lo)[0]
                hi = _line_of(units, hi)[1]
                line_count = 1 + sum(unit == NEWLINE for unit in units[lo:hi])
            else:
                hi = min(hi + 1, len(units))
            before = self._state()
            self._exit_visual()
            if linewise:
                self._line_span(char, lo, hi)
                if not units:
                    self._yank(0, 0, linewise=True)
                if char == "y":
                    self.caret = self._atoms()[1][_first_blank_free(units, lo, hi)]
            else:
                self._operate_span(char, (lo, hi))
            command = char + ("L" + str(line_count) if linewise else "V" + str(hi - lo))
            if char == "c":
                session = _InsertChange(before, command, 1, self._atoms()[2])
                self._insert_change = session
                if before[0] != self.text:
                    if not self.masked:
                        self._undo.append(before)
                        del self._undo[:-UNDO_CAP]
                    self._redo.clear()
                    session.recorded = True
            elif char == "d" and self.text != before[0]:
                self._retain_repeat(_RepeatChange(command, 1))
            return NOTHING
        if prefix in ("f", "F", "t", "T"):
            self._search(prefix, char, count or 1, "")
        elif prefix == "g":
            if char == "g":
                self._goto_line(count or 1)
            elif char in "eE":
                self._move("g" + char, count)
        elif not prefix and char in (";", ","):
            if self._last_search is not None:
                kind, target = self._last_search
                if char == ",":
                    kind = {"f": "F", "F": "f", "t": "T", "T": "t"}[kind]
                self._search(kind, target, count or 1, "", repeat=True)
        elif not prefix and char in (*_VIM_MOTIONS, "j", "k", "G"):
            self._move(char, count)
        units, bounds, index = self._atoms()
        # A head can be an empty-line sentinel, but never the position after
        # the final character of a nonempty hard line.
        if index and (index == len(units) or units[index] == NEWLINE) and units[index - 1] != NEWLINE:
            index -= 1
        self.caret = bounds[index]
        self.visual_head = index
        return NOTHING

    def _drop_pending(self) -> None:
        self._leader = False
        self._count = self._operator = self._op_count = self._prefix = ""

    def _modal(self, event: Key | Paste) -> ComposerAction | None:
        """Vim mode's part of `event`; None leaves it to the composer's own keys (INSERT's, or one NORMAL shares)."""
        if not isinstance(event, Key):
            self._drop_pending()
            return None  # a paste inserts at the caret, in either mode
        # The legacy bytes of an Alt chord are also Esc and the key in one read; Alt+B and Alt+F stay word moves.
        legacy_alt = (
            event.name == CHAR and event.alt and not event.ctrl and not event.protocol
            and event.char not in ALT_WORD_MOVES
        )
        if not self.normal:
            if event.name == ESCAPE:
                self._enter_normal()
                return NOTHING
            if legacy_alt:
                self._enter_normal()
                return self._normal_char(event.char)
            return None
        if self.visual and event.name == ESCAPE:
            self._drop_pending() if self.pending else self._exit_visual()
            return NOTHING
        if self.visual and event.name == ENTER:
            self._clear_visual()
            return None
        if self._prefix in ("g", "f", "F", "t", "T", "r"):
            if event.name == CHAR and not (event.ctrl or event.alt):  # a reported Shift is in the char already
                return self._normal_char(event.char)
            self._drop_pending()
            return NOTHING
        if self._operator and self._prefix in ("i", "a"):
            if event.name == CHAR and not (event.ctrl or event.alt):
                return self._normal_char(event.char)
            self._drop_pending()
            # A legacy Alt chord is Esc and the key in one read: the Esc drops the object, then the key is a fresh one.
            return self._normal_char(event.char) if legacy_alt else NOTHING
        if not self.visual and is_leader_key(event) and not (self._operator or self._prefix):
            self._drop_pending()  # a count does not carry into a leader sequence
            self._leader = True
            return NOTHING
        if event.name == CHAR and ((not event.ctrl and not event.alt) or legacy_alt):
            return self._normal_char(event.char)
        if event.name in (BACKSPACE, DELETE) and not (event.ctrl or event.alt or event.shift):
            return self._normal_char("h" if event.name == BACKSPACE else "x")
        if self.pending or self.visual:
            self._drop_pending()  # unsupported visual keys cannot mutate text behind the selection
            return NOTHING
        return None

    def _enter_normal(self) -> None:
        """INSERT to NORMAL: the caret steps back onto the character before it, unless it starts a line."""
        self._finish_insert()
        self.normal = True
        self._drop_pending()
        self._typing_at = None
        units, bounds, index = self._atoms()
        if index > 0 and units[index - 1] != NEWLINE:
            self.caret = bounds[index - 1]

    def _enter_insert(self, change: bool = False) -> None:
        self.normal = False
        self._drop_pending()
        self._typing_at = None
        self._changing = change

    def _clamp_normal(self) -> None:
        """In NORMAL the caret is on a character: never after a line's last one (an empty line keeps it), never
        inside a paste chip."""
        if not self.normal or self.visual:
            return
        units, bounds, index = self._atoms()
        if (index == len(units) or units[index] == NEWLINE) and index > 0 and units[index - 1] != NEWLINE:
            index -= 1
        self.caret = bounds[index]

    def _atoms(self) -> tuple[list[str], list[int], int]:
        """`_units` with every paste chip one unit: what NORMAL's motions and deletions step over whole."""
        units, bounds, _index = self._units()
        if self.pastes:
            spans = self._chip_spans()
            merged: list[str] = []
            edges = [0]
            for unit, start, end in zip(units, bounds, bounds[1:]):
                if merged and any(chip_start < start < chip_end for chip_start, chip_end in spans):
                    merged[-1] += unit
                    edges[-1] = end
                else:
                    merged.append(unit)
                    edges.append(end)
            units, bounds = merged, edges
        return units, bounds, _cluster_index(bounds, self.caret)

    def _word_classes(self, units: Sequence[str], big: bool = False) -> list[str]:
        """Classify NORMAL atoms; opaque metadata tokens are singleton runs."""
        result = []
        for at, unit in enumerate(units):
            if unit in self.pastes or any(_is_token(ch) for ch in unit):
                kind = f"opaque:{at}"
            elif unit.isspace():
                kind = "space"
            elif big:
                kind = "word"
            else:
                base = next((ch for ch in unit if not unicodedata.category(ch).startswith("M")), "")
                kind = "keyword" if base == "_" or (base and unicodedata.category(base)[0] in "LN") else "punctuation"
            result.append(kind)
        return result

    def _take_count(self) -> int | None:
        """The count typed for the command being completed (one before an operator times one after it); None
        without one."""
        if not (self._count or self._op_count):
            return None
        count = int(self._count or "1") * int(self._op_count or "1")
        self._count = self._op_count = ""
        return min(count, VIM_COUNT_CAP)

    def _normal_char(self, char: str) -> ComposerAction:
        if self.visual:
            return self._visual_char(char)
        if self._replaying:
            return self._normal_command(char)
        if char == "." and not (self._operator or self._prefix):
            override = int(self._count) if self._count else None
            self._drop_pending()
            self._repeat(override)
            return _TOOK_STEP
        before = self._state()
        count = min(int(self._count or "1") * int(self._op_count or "1"), VIM_COUNT_CAP)
        counted = bool(self._count or self._op_count)
        command = self._operator + self._prefix + char
        if char in ";," and self._last_search is not None:
            kind, target = self._last_search
            if char == ",":
                kind = {"f": "F", "F": "f", "t": "T", "T": "t"}[kind]
            command = self._operator + kind + target
        result = self._normal_command(char)
        if self.pending:
            return result
        if not self.normal:
            if command in ("i", "a", "I", "A", "o", "O", "s", "S", "C") or command.startswith("c"):
                session = _InsertChange(before, command, count, self._atoms()[2], counted=counted)
                self._insert_change = session
                if before[0] != self.text:
                    if not self.masked:
                        self._undo.append(before)
                        del self._undo[:-UNDO_CAP]
                    self._redo.clear()
                    session.recorded = True
            return result
        if before[0] != self.text and command != "u":
            self._retain_repeat(_RepeatChange(command, count, register=self._register if command in ("p", "P") else None, counted=counted))
        return result

    def _execute_repeat(self, change: _RepeatChange, count: int) -> None:
        command = change.command
        if len(command) > 2 and command[:2] in ("dL", "cL"):
            self._lines(command[0], min(int(command[2:]) * count, len(self._atoms()[0]) + 1))
            return
        if len(command) > 2 and command[:2] in ("dV", "cV"):
            units, _bounds, index = self._atoms()
            self._operate_span(command[0], (index, min(index + int(command[2:]) * count, len(units))))
            return
        if command in ("p", "P"):
            current = self._register
            self._register = change.register
            try:
                self._put(command == "p", count)
            finally:
                self._register = current
        elif len(command) >= 2 and command[0] in "dcy":
            op, tail = command[0], command[1:]
            if len(tail) == 2 and tail[0] in "ia":
                desc, target = tail
                span = (self._text_object_span(desc, count) if target == "w" else
                        self._quote_object_span(desc, count, target) if target in _QUOTE_CHARS else
                        self._bracket_object_span(desc, count, target) if target in _BRACKET_PAIRS else None)
                self._operate_span(op, span)
            elif len(tail) == 2 and tail[0] in "fFtT":
                self._search(tail[0], tail[1], count, op)
            else:
                self._operate(op, tail, count if change.counted or tail not in ("gg", "G") else None)
        elif command.startswith("r") and len(command) > 1:
            self._replace_chars(command[1:], count)
        else:
            self._command(command, count)

    def _apply_recipe(self, change: _RepeatChange, origin: int) -> int:
        for offset, deleted, payload in change.recipe:
            _units, bounds, _index = self._atoms()
            at = origin + offset
            if at < 0 or at + deleted >= len(bounds):
                raise ValueError("insertion recipe out of bounds")
            self._replace(bounds[at], bounds[at + deleted], payload)
        _units, bounds, _index = self._atoms()
        endpoint = origin + change.terminal
        if endpoint < 0 or endpoint >= len(bounds):
            raise ValueError("insertion endpoint out of bounds")
        self.caret = bounds[endpoint]
        return endpoint

    def _finish_insert(self) -> None:
        session = self._insert_change
        if session is None:
            return
        self._insert_change = None
        terminal = self._atoms()[2] - session.origin
        change = _RepeatChange(session.command, session.count, tuple(session.recipe), terminal, counted=session.counted)
        if session.eligible and session.count > 1 and session.command in ("i", "a", "I", "A", "o", "O"):
            # Apply additional copies to a detached candidate first.
            self._repeat_transaction(change, session.count - 1, continuation=True)
        if not session.recorded:
            self._step(session.before, False)
        elif self.text == session.before[0] and self._undo and self._undo[-1] == session.before:
            self._undo.pop()
        if self.text != session.before[0] and session.eligible:
            self._retain_repeat(change)
        elif self.text == session.before[0]:
            self.caret = session.before[1]

    def _repeat(self, override: int | None) -> None:
        change = self._repeat_change
        if change is not None:
            if override is not None:
                from dataclasses import replace
                change = replace(change, counted=True)
            self._repeat_transaction(change, override or change.effective_count)

    def _repeat_transaction(self, change: _RepeatChange, count: int, *, continuation: bool = False) -> None:
        # Admission is virtual: no expanded strings, snapshots, map copies or
        # token reservations until every semantic endpoint and budget passes.
        from .vim_repeat import preflight
        try:
            plan = preflight(self, change, count, continuation)
        except ValueError:
            self._bell = True
            return
        from copy import copy
        candidate = copy(self)
        candidate.pastes = dict(self.pastes)
        candidate.images = dict(self.images)
        candidate._chunks = dict(self._chunks)
        candidate._undo = list(self._undo)
        candidate._redo = list(self._redo)
        candidate._insert_change = None
        candidate._replaying = True
        before = self._state()
        insert, copies, count = plan.insertion, plan.copies, plan.count
        try:
            for n in range(copies):
                if not continuation or change.command in ("o", "O"):
                    if n == 0 or change.command in ("o", "O"):
                        candidate._execute_repeat(change, 1 if change.command in ("i", "a", "I", "A", "o", "O") else count)
                if insert:
                    origin = candidate._atoms()[2]
                    candidate._apply_recipe(change, origin)
            if insert and not continuation:
                candidate._enter_normal()
            candidate._clamp_normal() if not continuation else None
        except (ValueError, IndexError):
            self._bell = True
            return
        # A change can delete and reinsert identical text. Its admitted
        # mutations still expire the old selection, unlike a failed/no-op dot.
        if candidate._generation != self._generation:
            self._invalidate_reselection()
        self.pastes, self.images = candidate.pastes, candidate.images
        self._set(candidate.text, candidate.caret)
        self._register = candidate._register
        self._paste_count, self._token_count = candidate._paste_count, candidate._token_count
        if not continuation:
            self.normal = True
            self._step(before, False)

    def _normal_command(self, char: str) -> ComposerAction:
        """A character typed in NORMAL: part of a command, or the key that completes one."""
        prefix, self._prefix = self._prefix, ""
        if prefix in ("f", "F", "t", "T"):
            self._search(prefix, char, self._take_count() or 1, self._operator)
            return NOTHING
        if prefix in ("i", "a"):
            count, operator = self._take_count() or 1, self._operator
            self._drop_pending()
            if char == "w" and operator:
                self._operate_span(operator, self._text_object_span(prefix, count))
            elif char in _QUOTE_CHARS and operator:
                self._operate_span(operator, self._quote_object_span(prefix, count, char))
            elif char in _BRACKET_PAIRS and operator:
                self._operate_span(operator, self._bracket_object_span(prefix, count, char))
            return NOTHING
        if prefix == "r":
            self._replace_chars(char, self._take_count() or 1)
            return NOTHING
        if prefix == "g":
            count, operator = self._take_count(), self._operator
            self._drop_pending()
            if char == "g":
                if operator:
                    self._operate(operator, "gg", count)
                else:
                    self._goto_line(count or 1)
            elif char == "v" and not operator:
                self._restore_visual()
            elif char in ("e", "E"):
                if operator:
                    self._operate(operator, "g" + char, count or 1)
                else:
                    self._move("g" + char, count)
            return NOTHING
        if char in _DIGITS and (char != "0" or (self._op_count if self._operator else self._count)):
            if self._operator:
                self._op_count = str(min(int(self._op_count + char), VIM_COUNT_CAP))
            else:
                self._count = str(min(int(self._count + char), VIM_COUNT_CAP))
            return NOTHING
        if char in ("f", "F", "t", "T"):
            self._prefix = char
            return NOTHING
        if char in (";", ","):
            count, operator = self._take_count() or 1, self._operator
            self._drop_pending()
            if self._last_search is not None:
                kind, target = self._last_search
                if char == ",":
                    kind = {"f": "F", "F": "f", "t": "T", "T": "t"}[kind]
                self._search(kind, target, count, operator, repeat=True)
            return NOTHING
        if char == "g" or (char == "r" and not self._operator):
            self._prefix = char
            return NOTHING
        if char in _VIM_OPERATORS and not self._operator:
            self._operator = char
            return NOTHING
        if self._operator and char in ("i", "a"):
            self._prefix = char
            return NOTHING
        count = self._take_count()
        operator, self._operator = self._operator, ""
        if operator:
            self._operate(operator, char, count)
            return NOTHING
        return self._command(char, count)

    def _command(self, char: str, count: int | None) -> ComposerAction:
        """A NORMAL command that is no operator: a motion, a key that goes to INSERT, an edit, an undo."""
        times = count or 1
        units, bounds, index = self._atoms()
        start, end = _line_of(units, index)
        if char in "vV":
            self.visual_anchor = self.visual_head = index
            self.visual_line = char == "V"
        elif char in _VIM_MOTIONS or char in "jkG":
            self._move(char, count)
        elif char == "i":
            self._enter_insert()
        elif char in "aA":
            if char == "A":
                self.caret = bounds[end]
            elif index < end:
                self.caret = bounds[index + 1]
            self._enter_insert()
        elif char == "I":
            self.caret = bounds[_first_blank_free(units, start, end)]
            self._enter_insert()
        elif char in "oO":
            at = bounds[end] if char == "o" else bounds[start]
            self._replace(at, at, NEWLINE)
            self.caret = at + 1 if char == "o" else at
            self._enter_insert(change=True)
        elif char in "xXs":
            self._operate("c" if char == "s" else "d", "h" if char == "X" else "l", times)
        elif char in "DC":
            self._operate(char.lower(), "$", 1)
        elif char == "S":
            self._operate("c", "c", times)
        elif char in "pP":
            self._put(char == "p", times)
        elif char == "u":
            for _ in range(times):
                self._take_step(self._undo, self._redo)
            return _TOOK_STEP
        return NOTHING  # any other character does nothing

    def _move(self, char: str, count: int | None) -> None:
        times = count or 1
        units, bounds, index = self._atoms()
        start, end = _line_of(units, index)
        if char in "jk":
            for _ in range(times):
                entry = self.history_index
                self._vertical(1 if char == "j" else -1)
                if self.history_index != entry:
                    break  # into the history: one entry, whatever the count
            return
        if char == "G":
            self._goto_line(count or len(units) + 1)  # past the last line is the last
            return
        target = index
        if char == "h":
            target = max(index - times, start)
        elif char == "l":
            target = min(index + times, max(end - 1, start))
        elif char == "0":
            target = start
        elif char == "^":
            target = _first_blank_free(units, start, end)
        elif char == "$":
            target = end
        else:
            classes = self._word_classes(units, char[-1].isupper())
            for _ in range(times):
                target = _word_target(classes, target, char.lower())
        self.caret = bounds[min(target, len(units))]

    def _goto_line(self, number: int) -> None:
        """The caret to line `number` (1 the first; past the last, the last), on its first character not blank."""
        units, bounds, _index = self._atoms()
        starts = [0, *(at + 1 for at, unit in enumerate(units) if unit == NEWLINE)]
        start = starts[min(max(number, 1), len(starts)) - 1]
        _start, end = _line_of(units, start)
        self.caret = bounds[_first_blank_free(units, start, end)]

    def _motion_span(self, motion: str, times: int, operator: str) -> tuple[int, int] | None:
        """The units an operator with `motion` acts on, (first, after last); None for a motion it takes none with."""
        units, _bounds, index = self._atoms()
        start, end = _line_of(units, index)
        if motion == "h":
            return max(index - times, start), index
        if motion == "l":
            return index, min(index + times, end)
        if motion == "0":
            return start, index
        if motion == "^":
            target = _first_blank_free(units, start, end)
            return min(index, target), max(index, target)
        if motion == "$":
            return index, end
        if motion not in ("w", "W", "b", "B", "e", "E", "ge", "gE"):
            return None
        if not units:
            return index, index
        classes = self._word_classes(units, motion[-1].isupper())
        kind = motion.lower()
        target = index
        if kind == "w" and operator == "c" and index < len(units) and classes[index] != "space":
            while target + 1 < len(units) and classes[target + 1] == classes[index]:
                target += 1
            for _ in range(times - 1):
                target = _word_target(classes, target, "e")
            return index, min(target + 1, len(units))
        for _ in range(times):
            target = _word_target(classes, target, kind)
        if kind == "b":
            return target, index
        if kind == "ge":
            return target, min(index + 1, len(units))
        if kind == "e":
            return index, min(target + 1, len(units))
        if times == 1 and index < end and classes[index] != "space" and target > end:
            target = end  # dw/dW never consume the following hard line.
        return index, target

    def _search_motion(self, kind: str, target: str, times: int, *, repeat: bool = False) -> tuple[int, int] | None:
        """Resolve a complete line-local search without committing partial counted progress."""
        target = _nfc(target)
        if (len(clusters(target)) != 1 or cluster_width(target) <= 0
                or any(is_control(ch) or ch in (NEWLINE, TAB_CHAR) or _is_token(ch) for ch in target)):
            return None
        units, _bounds, index = self._atoms()
        start, end = _line_of(units, index)
        direction = 1 if kind in ("f", "t") else -1
        till = kind in ("t", "T")
        cursor = index
        remaining = times
        for match in range(index + direction, end if direction > 0 else start - 1, direction):
            unit = units[match]
            if unit in self.pastes or any(_is_token(ch) for ch in unit) or _nfc(unit) != target:
                continue
            landing = match - direction if till else match
            if repeat and till and landing == cursor:
                continue  # explicit till accepts this success; repeats must progress
            remaining -= 1
            if remaining == 0:
                return landing, match
            if repeat:
                cursor = landing
        return None

    def _search(self, kind: str, target: str, times: int, operator: str, *, repeat: bool = False) -> None:
        """Commit one successful motion/span; a miss must never enter INSERT or replace memory."""
        result = self._search_motion(kind, target, times, repeat=repeat)
        self._drop_pending()
        if result is None:
            return
        if not repeat:
            self._last_search = kind, _nfc(target)
        landing, match = result
        _units, bounds, index = self._atoms()
        if not operator:
            self.caret = bounds[landing]
            return
        span = {"f": (index, match + 1), "t": (index, match),
                "F": (match, index), "T": (match + 1, index)}[kind]
        self._operate_span(operator, span)

    def _text_object_span(self, descriptor: str, times: int) -> tuple[int, int] | None:
        """Line-local `iw` runs or `aw` words, using space/tab breaks on whole NORMAL atoms."""
        if descriptor not in ("i", "a"):
            return None
        units, _bounds, index = self._atoms()
        line_start, line_end = _line_of(units, index)
        if index >= line_end:
            return index, index
        blank = units[index] in WORD_BREAKS
        start = index
        while start > line_start and (units[start - 1] in WORD_BREAKS) == blank:
            start -= 1
        end = start
        last_word_end = None
        remaining = times
        while end < line_end and remaining:
            run_blank = units[end] in WORD_BREAKS
            while end < line_end and (units[end] in WORD_BREAKS) == run_blank:
                end += 1
            if not run_blank:
                last_word_end = end
            if descriptor == "i" or not run_blank:
                remaining -= 1
        if descriptor == "a" and blank and last_word_end is not None:
            end = last_word_end  # blank-start objects never add trailing padding, even with excess counts
        if descriptor == "a" and not blank:
            if end < line_end:  # prefer all trailing blanks after the aggregate word span
                while end < line_end and units[end] in WORD_BREAKS:
                    end += 1
            elif last_word_end == end:  # no trailing padding: take the leading blank run, if any
                while start > line_start and units[start - 1] in WORD_BREAKS:
                    start -= 1
        return start, end

    def _quote_object_span(self, descriptor: str, times: int, q: str) -> tuple[int, int] | None:
        """Line-local quoted text object (`i` or `a` with `"`, `'`, or `` ` ``) using atom indexes."""
        if descriptor not in ("i", "a") or q not in _QUOTE_CHARS:
            return None
        units, _bounds, index = self._atoms()
        line_start, line_end = _line_of(units, index)

        if index < line_end and units[index] == q:
            # On a quote: the pair, enumerated from the line's start, that holds the caret.
            found_pair: tuple[int, int] | None = None
            scan_pos = line_start
            while scan_pos < line_end:
                open_pos = _raw_quote(units, scan_pos, line_end, q)
                if open_pos is None:
                    break
                close_pos = _closing_quote(units, open_pos + 1, line_end, q)
                if close_pos is None:
                    break
                if open_pos <= index <= close_pos:
                    found_pair = (open_pos, close_pos)
                    break
                scan_pos = close_pos + 1
            if found_pair is None:
                return None
            open_idx, close_idx = found_pair
        else:
            # Off a quote: the nearest unescaped one strictly before the caret opens, else the line's first.
            cand = index - 1
            open_idx: int | None = None
            while cand >= line_start:
                if units[cand] == q and (_backslashes_before(units, line_start, cand) % 2 == 0):
                    open_idx = cand
                    break
                cand -= 1
            if open_idx is None:
                open_idx = _raw_quote(units, line_start, line_end, q)
            if open_idx is None:
                return None
            close_idx = _closing_quote(units, open_idx + 1, line_end, q)
            if close_idx is None:
                return None

        if descriptor == "i":
            if times >= 2:
                return open_idx, close_idx + 1
            return open_idx + 1, close_idx

        # descriptor == "a"
        # Includes delimiters plus contiguous trailing ASCII space/tab run;
        # only if no trailing run, include contiguous preceding ASCII space/tab run.
        start = open_idx
        end = close_idx + 1
        trailing_end = end
        while trailing_end < line_end and units[trailing_end] in _BLANKS:
            trailing_end += 1

        if trailing_end > end:
            return start, trailing_end

        leading_start = start
        while leading_start > line_start and units[leading_start - 1] in _BLANKS:
            leading_start -= 1
        return leading_start, end

    def _bracket_object_span(self, descriptor: str, times: int, target: str) -> tuple[int, int] | None:
        """Balanced bracket text object (`i` or `a` with `()`, `[]`, `{}`) using atom indexes."""
        if descriptor not in ("i", "a") or target not in _BRACKET_PAIRS or times < 1:
            return None
        open_char = _BRACKET_OPENERS[target]
        close_char = _BRACKET_CLOSERS[open_char]
        units, _bounds, index = self._atoms()

        # Plain stack/parent scan over full composer units:
        # Each entry tracks its parent index in open_stack, open atom index, and matched close atom index.
        open_stack: list[int] = []  # indices into records
        # record: [parent_rec_idx, open_idx, close_idx]
        records: list[list[int | None]] = []
        active_at_caret: int | None = None
        caret_record: int | None = None

        for idx, u in enumerate(units):
            if u == open_char:
                parent = open_stack[-1] if open_stack else None
                rec_idx = len(records)
                records.append([parent, idx, None])
                open_stack.append(rec_idx)
                if idx == index:
                    caret_record = rec_idx
            elif u == close_char and open_stack:
                rec_idx = open_stack.pop()
                records[rec_idx][2] = idx
                if idx == index and caret_record is None:
                    caret_record = rec_idx

            if idx == index and caret_record is None:
                active_at_caret = open_stack[-1] if open_stack else None

        # Determine starting candidate record:
        cand_rec = caret_record if caret_record is not None else active_at_caret

        if cand_rec is None:
            # No active opener at caret; select first opener strictly forward across composer.
            # An unmatched forward opener must be chosen (and will fail), blocking child substitution.
            for rec_idx, rec in enumerate(records):
                if rec[1] is not None and rec[1] > index:
                    cand_rec = rec_idx
                    break

        if cand_rec is None:
            return None

        # Effective count N selects the Nth same-family ancestor (candidate is level 1)
        cur: int | None = cand_rec
        depth = 1
        while cur is not None and depth < times:
            cur = records[cur][0]
            depth += 1

        if cur is None or depth < times:
            return None

        rec = records[cur]
        open_idx, close_idx = rec[1], rec[2]
        if open_idx is None or close_idx is None:
            return None

        if descriptor == "i":
            return open_idx + 1, close_idx
        return open_idx, close_idx + 1

    def _operate(self, operator: str, motion: str, times: int | None) -> None:
        """Resolve logical-line operators separately from rendered-row navigation."""
        count = times or 1
        units, _bounds, index = self._atoms()
        if motion == operator:
            self._lines(operator, count)
            return
        if motion in ("j", "k", "gg", "G"):
            starts = [0, *(at + 1 for at, unit in enumerate(units) if unit == NEWLINE)]
            current = starts.index(_line_of(units, index)[0])
            if motion in ("j", "k"):
                target = current + (count if motion == "j" else -count)
            else:
                target = count - 1 if times is not None else (0 if motion == "gg" else len(starts) - 1)
            target = min(max(target, 0), len(starts) - 1)
            lo, hi = sorted((current, target))
            self._line_span(operator, starts[lo], _line_of(units, starts[hi])[1])
            return
        span = self._motion_span(motion, count, operator)
        # Vim's exclusive forward column-zero exception applies to w/W only;
        # inclusive and backward motions must retain their own endpoints.
        if span is not None and motion in ("w", "W"):
            lo, hi = span
            start, end = _line_of(units, index)
            if hi > end and hi < len(units) and units[hi - 1] == NEWLINE:
                if index <= _first_blank_free(units, start, end):
                    self._line_span(operator, start, hi - 1)
                    return
                span = lo, hi - 1
        self._operate_span(operator, span)

    def _operate_span(self, operator: str, span: tuple[int, int] | None) -> None:
        """Shared characterwise register, edit and change effects for motions and objects."""
        if span is None:
            return
        _units, bounds, _index = self._atoms()
        start, end = bounds[span[0]], bounds[span[1]]
        if start < end:
            self._yank(start, end, linewise=False)
        if operator == "y":
            self.caret = start
        elif start < end or operator == "c":
            self._replace(start, end)
            if operator == "c":
                self._enter_insert(change=True)

    def _lines(self, operator: str, times: int) -> None:
        """Doubled operators select hard lines beginning at the current line."""
        units, _bounds, index = self._atoms()
        start, end = _line_of(units, index)
        for _ in range(times - 1):
            if end >= len(units):
                break
            end = _line_of(units, end + 1)[1]
        self._line_span(operator, start, end)

    def _line_span(self, operator: str, start: int, end: int) -> None:
        """Apply inclusive hard lines, retaining one replacement line for change."""
        units, bounds, _index = self._atoms()
        if not units:
            if operator == "c":
                self._enter_insert(change=True)
            return  # No selected content: retain the register even for empty changes.
        self._yank(bounds[start], bounds[end], linewise=True)
        if operator == "y":
            return  # Linewise yank preserves the original caret.
        if operator == "c":
            self._replace(bounds[start], bounds[end])
            self._enter_insert(change=True)
            return
        if end < len(units):
            self._replace(bounds[start], bounds[end + 1])
        else:
            self._replace(bounds[start - 1] if start > 0 else bounds[start], bounds[end])
        units, bounds, index = self._atoms()
        start, end = _line_of(units, index)
        self.caret = bounds[_first_blank_free(units, start, end)]

    def _yank(self, start: int, end: int, linewise: bool) -> None:
        text = self.text[start:end]
        self._register = _Register(
            text,
            {label: pasted for label, pasted in self.pastes.items() if label in text},
            {token: image for token, image in self.images.items() if token in text},
            linewise,
        )

    def _put(self, after: bool, times: int) -> None:
        """`p` (after the caret, or below the line) or `P` (before it, or above): what the last deletion, change or
        yank took, `times` over; each copy of an image is a token of its own, for the same image."""
        register = self._register
        if register is None:
            return
        # A chip whose label a chip of other text now has (the labels count from 1 again once the composer
        # empties) is put under a label of its own.
        text = register.text
        for label, pasted in register.pastes.items():
            if self.pastes.get(label, pasted) != pasted or (label in self.text and label not in self.pastes):
                new_label = self._chip_label(pasted, taken=register.pastes)
                text = text.replace(label, new_label)
                label = new_label
            self.pastes[label] = pasted
        copies: list[str] = []
        for _ in range(times):
            fresh: dict[int, str] = {}
            for token, image in register.images.items():
                fresh[ord(token)] = new = self._new_token()
                self.images[new] = image
            copies.append(text.translate(fresh))
        units, bounds, index = self._atoms()
        start, end = _line_of(units, index)
        if register.linewise:
            block = NEWLINE.join(copies)
            at = bounds[end] if after else bounds[start]
            self._replace(at, at, NEWLINE + block if after else block + NEWLINE)
            self.caret = at + 1 if after else at
            units, bounds, index = self._atoms()
            line_start, line_end = _line_of(units, index)
            self.caret = bounds[_first_blank_free(units, line_start, line_end)]
            return
        at = bounds[index + 1] if after and index < end else bounds[index]
        self._replace(at, at, "".join(copies))
        units, bounds, index = self._atoms()
        if index > 0:
            self.caret = bounds[index - 1]  # on the last character put

    def _replace_chars(self, char: str, times: int) -> None:
        """`r<char>`: the `times` characters from the caret's become `char`; nothing when the line has fewer."""
        cleaned = _clean(char, self.masked)
        units, bounds, index = self._atoms()
        _start, end = _line_of(units, index)
        if not cleaned or NEWLINE in cleaned or index + times > end:
            return
        self._replace(bounds[index], bounds[index + times], cleaned * times)
        units, bounds, index = self._atoms()
        if index > 0:
            self.caret = bounds[index - 1]

    def _handle(self, event: Key | Paste) -> ComposerAction:
        if isinstance(event, Paste):
            self._insert_paste(event.text)
            return NOTHING
        if event.name == ENTER:
            adds_line = event.alt or event.shift
            continues = not self.masked and not self.normal and self.text[self.caret - 1 : self.caret] == "\\"
            if not adds_line and continues:  # in NORMAL, Enter always sends
                self._replace(self.caret - 1, self.caret, NEWLINE)
                return NOTHING
            if adds_line:
                self._insert(NEWLINE)
                return NOTHING
            return self._submit()
        if event.name == CHAR:
            if event.ctrl:
                return self._control(event.char)
            if event.alt and event.char in ALT_WORD_MOVES:
                self._move_or_delete(Key(ALT_WORD_MOVES[event.char], alt=True))
            elif not (event.alt and event.protocol):
                self._insert(event.char)
            return NOTHING
        if event.name == TAB:
            return NOTHING if event.shift else ComposerAction(COMPLETE)
        if event.name == ESCAPE:
            return ComposerAction(CANCEL)
        if event.name in (UP, DOWN):
            self._vertical(-1 if event.name == UP else 1)
            return NOTHING
        self._move_or_delete(event)
        return NOTHING

    def _move_or_delete(self, key: Key) -> None:
        units, bounds, index = self._units()
        by_word = key.ctrl or key.alt
        if key.name == BACKSPACE and index > 0:
            self._replace(bounds[_word_start(units, index) if by_word else index - 1], self.caret)
        elif key.name == DELETE and index < len(units):
            self._replace(self.caret, bounds[index + 1])
        elif key.name == LEFT:
            self.caret = bounds[_word_start(units, index) if by_word else max(index - 1, 0)]
            self._caret_off_chip(forward=False)
        elif key.name == RIGHT:
            self.caret = bounds[_word_end(units, index) if by_word else min(index + 1, len(units))]
            self._caret_off_chip(forward=True)
        elif key.name == HOME:
            self.caret = self._line_start()
        elif key.name == END:
            self.caret = self._line_end()

    def _control(self, char: str) -> ComposerAction:
        if char == "c":
            if not self.text:
                return ComposerAction(INTERRUPT)
            self._clear()
            return ComposerAction(CANCEL)
        if char == "d":
            if not self.text:
                return ComposerAction(EXIT)
            self._move_or_delete(Key(DELETE))
        elif char == "j":
            self._insert(NEWLINE)
        elif char == "a":
            self.caret = self._line_start()
        elif char == "e":
            self.caret = self._line_end()
        elif char == "u":
            start = self._line_start()
            self._replace(start - 1 if start == self.caret and start > 0 else start, self.caret)
        elif char == "k":
            end = self._line_end()
            self._replace(self.caret, end + 1 if end == self.caret and end < len(self.text) else end)
        elif char == "w":
            units, bounds, index = self._units()
            self._replace(bounds[_word_start(units, index)], self.caret)
        return NOTHING

    def _line_start(self) -> int:
        return self.text.rfind(NEWLINE, 0, self.caret) + 1

    def _line_end(self) -> int:
        end = self.text.find(NEWLINE, self.caret)
        return len(self.text) if end < 0 else end

    def record(self, text: str, sent: bool = True) -> None:
        """Keep `text`, trimmed as Hermes' history file keeps it, as the newest history entry, unless it is blank,
        repeats the newest, or nothing may be recorded.

        Only a `sent` line goes on to `on_record`; a draft the person cleared
        stays in this session's history alone.
        """
        entry = text.strip()
        if self.records_history and not self.masked and entry and (not self.history or self.history[-1] != entry):
            self.history.append(entry)
            del self.history[:-HISTORY_CAP]
            if sent and self.on_record is not None:
                self.on_record(entry)

    def _submit(self) -> ComposerAction:
        shown = self._labelled(self.text)
        text = self.expanded()
        chips = tuple((label, pasted) for label, pasted in self.pastes.items() if label in shown)
        images = tuple(self.images[ch] for ch in self.text if ch in self.images)
        self.record(text)
        self._clear()
        return ComposerAction(SUBMIT, text, shown if shown != text else "", chips, images)

    # -- rows and history -----------------------------------------------------

    def _vertical(self, step: int) -> None:
        if self._avail is not None:
            shape, rows = self._rows(self._avail)
        else:  # never rendered: logical lines only
            shape = self._measured()
            shape, rows = self._rows(sum(width or 0 for width in shape.widths) + 1)
        widths, bounds = shape.widths, shape.bounds
        row, col = _locate(rows, widths, _cluster_index(bounds, self.caret))
        target = row + step
        if 0 <= target < len(rows):
            self.caret = bounds[_position_at(rows[target], widths, col)]
            self._caret_off_chip(forward=True)
        elif self.visual:
            return
        elif step < 0:
            self._history_back()
        else:
            self._history_forward()

    def _history_back(self) -> None:
        if self.masked or not self.history or self.history_index == 0:
            return
        if self.history_index is None:
            self._draft, self._draft_images = self.text, dict(self.images)  # its tokens come back with it
            self.history_index = len(self.history) - 1
        else:
            self.history_index -= 1
        self._load(self.history[self.history_index])

    def _history_forward(self) -> None:
        if self.masked or self.history_index is None:
            return
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._load(self.history[self.history_index])
            return
        self.history_index = None
        self.images = {**self.images, **self._draft_images}
        self._load(self._draft)
        self._draft, self._draft_images = "", {}

    # -- drawing --------------------------------------------------------------

    def render(
        self,
        width: int,
        max_rows: int,
        prompt: str = PROMPT,
        prompt_style: Style = DEFAULT_STYLE,
        chip_style: Style = DEFAULT_STYLE,
        marks: Sequence[tuple[int, int]] = (),
        mark_style: Style = DEFAULT_STYLE,
        glow: Sequence[tuple[int, int]] = (),
        glow_style: Callable[[int, int], Style] | None = None,
        selection_style: Style = Style(reverse=True),
    ) -> tuple[list[Line], tuple[int, int]]:
        """The visible rows at `width` cells, and the caret as (row, col) within them; paste chips and image tokens in
        `chip_style`, the `marks` (str index ranges of the text, such as a `/name` that resolves) in `mark_style`, and
        the `glow` ranges (`aura`) a style a character, `glow_style(offset, length)` with `offset` from the range's
        start in a range `length` long, over a mark."""
        prompt_cells = cell_width(prompt)
        avail = max(width - prompt_cells, 1)
        self._avail = avail
        shape, rows = self._rows(avail)
        shown, widths = shape.shown, shape.widths
        row, col = _locate(rows, widths, _cluster_index(shape.bounds, self.caret))
        visible = max(max_rows, 1)
        scroll = min(max(self._scroll, row - visible + 1), row)
        scroll = max(min(scroll, len(rows) - visible), 0)
        self._scroll = scroll
        indent = Span(" " * prompt_cells)
        chips = self._chip_spans() if self.pastes and not self.masked else []
        if self.images:
            chips = sorted([*chips, *((at, at + 1) for at, ch in enumerate(self.text) if ch in self.images)])
        selection = self.visual_span
        final_line_selected = False
        if self.visual_line and self.visual_anchor is not None and self.visual_head is not None:
            atoms, _bounds, _index = self._atoms()
            final_line_selected = _line_of(atoms, max(self.visual_anchor, self.visual_head))[1] == len(atoms)
        lines: list[Line] = []
        for number in range(scroll, min(len(rows), scroll + visible)):
            lead = Span(prompt, prompt_style) if number == 0 else indent
            start, end = rows[number].start, rows[number].end
            if chips or marks or glow or selection is not None:
                body_spans = _chip_styled(shown, shape.bounds, start, end, chips, chip_style, marks, mark_style,
                                          glow, glow_style, selection, selection_style)
                if selection is not None and rows[number].hard:
                    at = shape.bounds[end]
                    if end < len(shape.units) and shape.units[end] == NEWLINE and selection[0] <= at < selection[1]:
                        body_spans.append(Span("␊", selection_style))
                    elif selection == (at, at) or (self.visual_line and selection[0] <= at < selection[1]) or (
                        final_line_selected and end == len(shape.units)
                    ):
                        body_spans.append(Span(" ", selection_style))
                lines.append((lead, *body_spans))
                continue
            body = "".join(shown[start:end])
            lines.append((lead, Span(body)) if body else (lead,))
        return lines, (row - scroll, prompt_cells + col)


def _chip_styled(
    shown: Sequence[str], bounds: Sequence[int], start: int, end: int, chips: Sequence[tuple[int, int]], style: Style,
    marks: Sequence[tuple[int, int]] = (), mark_style: Style = DEFAULT_STYLE,
    glow: Sequence[tuple[int, int]] = (), glow_style: Callable[[int, int], Style] | None = None,
    selection: tuple[int, int] | None = None, selection_style: Style = DEFAULT_STYLE,
) -> list[Span]:
    """Clusters `start` to `end` as spans, the ones inside a chip (by str index) in `style`, inside a glow range in
    `glow_style` of their offset in it, inside a mark in `mark_style`."""
    spans: list[Span] = []
    for index in range(start, end):
        inside = any(chip_start <= bounds[index] < chip_end for chip_start, chip_end in chips)
        lit = None if inside or glow_style is None else next(
            (glow_style(bounds[index] - lit_start, lit_end - lit_start) for lit_start, lit_end in glow
             if lit_start <= bounds[index] < lit_end),
            None)
        marked = not inside and any(mark_start <= bounds[index] < mark_end for mark_start, mark_end in marks)
        wanted = style if inside else lit if lit is not None else mark_style if marked else DEFAULT_STYLE
        if selection is not None and selection[0] <= bounds[index] < selection[1]:
            wanted = replace(wanted, bg=selection_style.bg, reverse=selection_style.reverse,
                             fg=selection_style.fg or wanted.fg)
        if spans and spans[-1].style == wanted:
            spans[-1] = Span(spans[-1].text + shown[index], wanted)
        else:
            spans.append(Span(shown[index], wanted))
    return spans
