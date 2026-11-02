"""The `/sessions` picker: Hermes' stored sessions in the slot, filtered as you type.

`session.list` answers with the person's stored sessions, most recently
active first. The picker groups them under a muted heading for the local day
each started (`DAY_GROUPS`: today, yesterday, the rest of the past week,
earlier), keeping Hermes' order inside a group, and shows each as one row: its
title, or the first prompt when it has no title, then its age and its message
count, each right-aligned in a column of its own. It marks the session this
TUI is in and returns the id the person picked. Its last row is the filter
(`filter_line`), drawn where the composer is, which the app hides while a
picker is open. It holds no IO: the app sends the list call, feeds keys in,
and runs the switch with the id it gets back.

Keys: Up/Down move one session, PageUp/PageDown one page, past the headings;
printable text filters (by title, first prompt or id, ignoring case), keeping
the headings of the groups with a match, and Backspace takes a filter
character back; Enter picks the highlighted row; Esc or Ctrl+C closes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
import math

from .composer import PROMPT
from .frame import RULE
from .keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, PAGE_DOWN, PAGE_UP, UP, Key, Paste
from .prompts import CHOICE_MARK
from .style import Line, Span
from .theme import Theme
from .width import cell_width, truncate, truncate_line

PICK = "pick"
CLOSE = "close"
CURRENT_MARK = "●"
# Its keys, longest first: on the info line while it is open.
KEYS = ("↑↓ move · enter switches · esc closes", "↑↓ enter switches · esc closes", "esc closes")
FILTER_PROMPT = PROMPT  # the composer's mark, on the row that stands where the composer was
FILTER_PLACEHOLDER = "type to filter"
# The filter row while the picker waits for typing to stop before it takes keys (`SessionPicker.waiting`).
WAITING_PLACEHOLDER = "↑↓ to pick · keep typing to stay in your prompt"
# The sessions' day groups, by the local calendar day a session started: today, yesterday, the five days before
# (the past week), and everything older or of no known start.
DAY_GROUPS = ("Today", "Yesterday", "Previous 7 days", "Earlier")
# The session this TUI is in heads the list under a group of its own: Hermes' rows carry no last activity, so by its
# start a long session resumed today would sink under `Earlier`.
CURRENT_GROUP = "Current"
CURRENT_LABEL = "this session"  # the current session's name while it has no title, in place of its id
# A start time past this many seconds is in milliseconds (1e11 s is past the year 5000).
MILLISECONDS_FROM = 1e11
# A picker draws a rule under its header, and then one over its filter row, while it keeps at least this many list
# rows: one more row of room never shows one fewer row of list.
RULED_MIN_ROWS = 3
# Its rules are set in by one cell on each side, as its header is, so no row of it starts as the composer's rules do.
RULE_INSET = " "
# Between a session row's age column and its message-count column.
COLUMN_GAP = "   "


@dataclass(frozen=True)
class SessionRow:
    id: str
    title: str
    preview: str
    started_at: float
    message_count: int

    @property
    def label(self) -> str:
        """What the row is called: the title, else the first prompt, else the id."""
        return (self.title or self.preview or self.id).strip().split("\n", 1)[0]


@dataclass(frozen=True)
class PickerAction:
    kind: str  # PICK or CLOSE
    session_id: str = ""


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _seconds(value: object) -> float:
    """A start time in seconds: one given in milliseconds is scaled down, and one no calendar holds (inf, nan, a
    year past 9999) is unknown, 0."""
    number = _number(value)
    number = number / 1000 if number > MILLISECONDS_FROM else number
    if not math.isfinite(number):
        return 0.0
    try:
        date.fromtimestamp(number)
    except (ValueError, OverflowError, OSError):
        return 0.0
    return number


def session_rows(result: Mapping[str, object]) -> list[SessionRow]:
    """The rows of a `session.list` answer, in its order; rows without an id are skipped."""
    sessions = result.get("sessions")
    if not isinstance(sessions, list):
        return []
    rows: list[SessionRow] = []
    for entry in sessions:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            continue
        title = entry.get("title")
        preview = entry.get("preview")
        rows.append(
            SessionRow(
                id=entry["id"],
                title=title if isinstance(title, str) else "",
                preview=preview if isinstance(preview, str) else "",
                started_at=_seconds(entry.get("started_at")),
                message_count=int(_number(entry.get("message_count"))),
            )
        )
    return rows


def day_group(started_at: float, now: float) -> int:
    """Which of `DAY_GROUPS` a session that started at `started_at` is in at `now`, by the local calendar."""
    if started_at <= 0:
        return len(DAY_GROUPS) - 1
    try:
        days = (date.fromtimestamp(now) - date.fromtimestamp(started_at)).days
    except (ValueError, OverflowError, OSError):  # a start no calendar holds is no known start
        return len(DAY_GROUPS) - 1
    return 0 if days <= 0 else 1 if days == 1 else 2 if days < 7 else 3


def age_text(started_at: float, now: float) -> str:
    """`just now`, `5m ago`, `3h ago`, `2d ago`; "" when the start time is unknown (none, or not a finite number)."""
    if not math.isfinite(started_at) or started_at <= 0:
        return ""
    seconds = max(0, int(now - started_at))
    for size, suffix in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{suffix} ago"
    return "just now"


def filter_line(query: str, width: int, theme: Theme, placeholder: str = FILTER_PLACEHOLDER) -> Line:
    """A picker's last row: what typing filters it by, or how to start, after the composer's prompt glyph."""
    typed = Span(query, theme.text) if query else Span(placeholder, theme.hint)
    return truncate_line((Span(FILTER_PROMPT, theme.prompt), typed), width)


def pointer(highlighted: bool, theme: Theme) -> Span:
    """A menu or picker row's first column: `❯` on the highlighted row (the choice prompts' mark), blank on the rest."""
    return Span(CHOICE_MARK if highlighted else " " * len(CHOICE_MARK), theme.menu_current)


def picker_row(highlighted: bool, lead: str, label: str, meta: str, width: int, theme: Theme) -> Line:
    """One picker row, with no fill (`theme.menu`): the pointer, `lead` (a mark or a number) and `label`, then `meta`
    set right. The highlighted row's name is bold in the accent and its meta in the text colour; every other row's
    meta is muted."""
    name = theme.menu_current if highlighted else theme.menu
    words = theme.text if highlighted else theme.muted
    head = pointer(highlighted, theme)
    meta = f" {meta} " if meta else " "
    room = width - cell_width(head.text) - cell_width(lead) - cell_width(meta)
    if room < 8:
        return truncate_line((head, Span(lead + label, name)), width)
    label = truncate(label, room)
    return (head, Span(lead + label, name), Span(" " * (room - cell_width(label)) + meta, words))


def picker_rule(width: int, theme: Theme) -> Line:
    """A picker's rule: `RULE` across `width` but for `RULE_INSET` at either end, muted."""
    inset = cell_width(RULE_INSET)
    return (Span(RULE_INSET + RULE * max(width - 2 * inset, 0), theme.muted),)


@dataclass(frozen=True)
class PickerFrame:
    lines: list[Line]
    caret: tuple[int, int] | None  # (row, col) at the end of the filter row's text; None with no filter row drawn
    page: int  # list rows shown: what PageUp and PageDown move by


def picker_frame(
    head: Line,
    count: int,
    index: int,
    row: Callable[[int], Line],
    empty: str,
    query: str,
    width: int,
    theme: Theme,
    max_rows: int,
    heading: Callable[[int], bool] | None = None,
    placeholder: str = FILTER_PLACEHOLDER,
) -> PickerFrame:
    """A picker's rows within `max_rows`, the same for every picker.

    A header (`head`), the `count` list rows `row` draws scrolled so the
    highlighted `index` shows (`empty` when there are none), then the
    filter row, its caret at the end of what was typed so an IME pre-edit
    shows there. A rule (`picker_rule`) sets the list off from the header,
    and then one from the filter row, while `RULED_MIN_ROWS` list rows
    still fit; with less room the rules go first. With two rows or fewer
    the header goes too, so the highlighted row stays. A list row that
    only heads the rows after it (`heading`) is never the last row shown
    while its rows are below: that row is left blank instead, so the list
    never scrolls a heading above the highlighted row out of view and the
    frame keeps its height.
    """
    if max_rows <= 0:
        return PickerFrame([], None, 1)
    current = (lambda number: truncate_line(row(number), width)) if count else (lambda number: (Span(empty, theme.muted),))
    caret = min(cell_width(FILTER_PROMPT) + cell_width(query), max(width - 1, 0))
    if max_rows <= 2:
        lines = [current(index), filter_line(query, width, theme, placeholder)][:max_rows]
        return PickerFrame(lines, (1, caret) if max_rows == 2 else None, 1)
    header = truncate_line(head, width)
    rule = picker_rule(width, theme)
    above = [rule] if max_rows - 3 >= RULED_MIN_ROWS else []
    below = [rule] if max_rows - 4 >= RULED_MIN_ROWS else []
    body = max_rows - 2 - len(above) - len(below)
    start = min(max(index - body + 1, 0), max(count - body, 0))
    end = min(start + body, count)
    rows = [current(number) for number in range(start, end)] if count else [current(0)]
    if heading is not None and end < count and end - 1 != index and heading(end - 1):
        rows[-1] = ()
    lines = [header, *above, *rows, *below, filter_line(query, width, theme, placeholder)]
    return PickerFrame(lines, (len(lines) - 1, caret), body)


def _messages(count: int, digits: int) -> str:
    """`12 messages`, the count right-aligned in `digits` cells and `1 message ` padded to the plural's width."""
    return f"{count:>{digits}} message{' ' if count == 1 else 's'}"


@dataclass
class SessionPicker:
    rows: list[SessionRow]
    current: str  # the stored id of the session this TUI is in
    query: str = ""
    index: int = 0
    page: int = 1  # rows the last render showed; PageUp/PageDown move by this many
    caret: tuple[int, int] | None = None  # the last render's caret, at the end of its filter row
    now: float = 0.0  # the last render's clock, which the day groups count from; 0 keeps the list order
    # Opened while the person was typing: keys go on to the composer until typing stops (`App._picker_takes`).
    waiting: bool = False

    def visible(self) -> list[SessionRow]:
        """The rows the filter keeps: the current session first, then a day group after another (`day_group`), in
        list order inside each."""
        needle = self.query.casefold()
        kept = [row for row in self.rows if not needle or needle in f"{row.title}\n{row.preview}\n{row.id}".casefold()]
        return sorted(kept, key=self._rank) if self.now > 0 else kept

    def _rank(self, row: SessionRow) -> int:
        return -1 if row.id == self.current else day_group(row.started_at, self.now)

    def _group(self, row: SessionRow) -> str:
        return CURRENT_GROUP if row.id == self.current else DAY_GROUPS[day_group(row.started_at, self.now)]

    def handle_key(self, event: Key | Paste) -> PickerAction | None:
        """Apply one key; a `PickerAction` when the person picked a row or closed the picker."""
        if isinstance(event, Paste):
            self._filter(self.query + event.text.split("\n", 1)[0])
            return None
        if event.name == ESCAPE or (event.name == CHAR and event.ctrl and event.char == "c"):
            return PickerAction(CLOSE)
        shown = self.visible()
        if event.name == ENTER:
            return PickerAction(PICK, shown[min(self.index, len(shown) - 1)].id) if shown else None
        steps = {UP: -1, DOWN: 1, PAGE_UP: -self.page, PAGE_DOWN: self.page}
        if event.name in steps and shown:
            self.index = min(max(self.index + steps[event.name], 0), len(shown) - 1)
        elif event.name == BACKSPACE:
            self._filter(self.query[:-1])
        elif event.name == CHAR and not event.ctrl and not event.alt:
            self._filter(self.query + event.char)
        return None

    def _filter(self, query: str) -> None:
        self.query = query
        self.index = 0

    def lines(self, width: int, theme: Theme, max_rows: int, now: float) -> list[Line]:
        """A header row, the filtered rows under their day groups' headings scrolled so the highlighted one shows,
        then the filter row (`picker_frame`)."""
        self.now = now
        shown = self.visible()
        self.index = min(self.index, max(len(shown) - 1, 0))
        entries: list[SessionRow | str] = []  # a session's row, or a day group's heading before its first
        for row in shown:
            group = self._group(row)
            if group not in entries:
                entries.append(group)
            entries.append(row)
        ages = max((cell_width(age_text(row.started_at, now)) for row in shown), default=0)
        digits = max((len(str(row.message_count)) for row in shown), default=1)
        title = f" Sessions ({len(shown)}/{len(self.rows)})" if self.query else f" Sessions ({len(self.rows)})"
        highlighted = entries.index(shown[self.index]) if shown else 0
        frame = picker_frame(
            (Span(title, theme.heading),), len(entries), highlighted,
            lambda number: self._entry(entries[number], number == highlighted, width, theme, now, ages, digits),
            " no session matches the filter" if self.rows else " Hermes listed no stored sessions", self.query, width,
            theme, max_rows,
            lambda number: isinstance(entries[number], str),
            WAITING_PLACEHOLDER if self.waiting else FILTER_PLACEHOLDER,
        )
        self.page, self.caret = frame.page, frame.caret
        return frame.lines

    def _entry(
        self, entry: SessionRow | str, highlighted: bool, width: int, theme: Theme, now: float, ages: int, digits: int
    ) -> Line:
        """A day group's heading, muted where the rows' titles start, or a session's row: its age and message count
        right-aligned in columns `ages` and `digits` wide."""
        if isinstance(entry, str):
            inset = cell_width(CHOICE_MARK) + cell_width(f"{CURRENT_MARK} ")
            return (Span(" " * inset, theme.muted), Span(entry, theme.muted))
        current = entry.id == self.current
        label = CURRENT_LABEL if current and not entry.title.strip() else entry.label
        age = f"{age_text(entry.started_at, now):>{ages}}{COLUMN_GAP}" if ages else ""
        meta = age + _messages(entry.message_count, digits)
        return picker_row(highlighted, f"{CURRENT_MARK if current else ' '} ", label, meta, width, theme)
