"""The rewind picker: the session's earlier prompts in the slot, filtered as you type.

`session.history` answers with the session's durable display transcript, each
row with the `row_id` a rewind names. The picker lists the person's prompts
(user rows with a row id and some text), newest first, numbered by their
place in the session, and returns the one picked. Its last row is the filter
(`session_picker.filter_line`), where the composer is drawn while no picker is
open. It holds no IO: the app asks for the history, feeds keys in, and acts on
what comes back (the prompt comes back into the composer; sending it
truncates before that row).

Keys: Up/Down move one row, PageUp/PageDown one page; printable text filters
(ignoring case) and Backspace takes a filter character back; Enter picks the
highlighted row; Esc or Ctrl+C closes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .fuzzy import subsequence_tail
from .keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, PAGE_DOWN, PAGE_UP, UP, Key, Paste, list_nav_step
from .session_picker import age_text, picker_frame, picker_row
from .style import Line, Span
from .theme import Theme

PICK = "pick"
CLOSE = "close"
# Its keys, longest first: on the info line while it is open.
KEYS = ("↑↓ move · enter edits it · esc closes", "↑↓ enter edits it · esc closes", "esc closes")
TITLE = " Rewind to a prompt ({count})"


@dataclass(frozen=True)
class RewindRow:
    row_id: int
    text: str
    ordinal: int  # its place among the session's prompts, from 1
    index: int  # its place in the history's messages: the ones before it are what a rewind keeps
    timestamp: float

    @property
    def label(self) -> str:
        return self.text.strip().split("\n", 1)[0]


@dataclass(frozen=True)
class RewindAction:
    kind: str  # PICK or CLOSE
    row: RewindRow | None = None


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def rewind_rows(result: Mapping[str, object]) -> list[RewindRow]:
    """The prompts of a `session.history` answer, newest first; a user row without an int row id or text is skipped."""
    messages = result.get("messages")
    if not isinstance(messages, list):
        return []
    rows: list[RewindRow] = []
    ordinal = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        row_id, text = message.get("row_id"), message.get("text")
        if not isinstance(row_id, int) or isinstance(row_id, bool) or not isinstance(text, str) or not text.strip():
            continue
        ordinal += 1
        rows.append(RewindRow(row_id, text, ordinal, index, _number(message.get("timestamp"))))
    return rows[::-1]


@dataclass
class RewindPicker:
    rows: list[RewindRow]
    query: str = ""
    index: int = 0
    page: int = 1  # rows the last render showed; PageUp/PageDown move by this many
    caret: tuple[int, int] | None = None  # the last render's caret, at the end of its filter row

    def visible(self) -> list[RewindRow]:
        return subsequence_tail(self.rows, self.query, lambda row: (row.text,))

    def handle_key(self, event: Key | Paste) -> RewindAction | None:
        """Apply one key; a `RewindAction` when the person picked a prompt or closed the picker."""
        if isinstance(event, Paste):
            self._filter(self.query + event.text.split("\n", 1)[0])
            return None
        if event.name == ESCAPE or (event.name == CHAR and event.ctrl and event.char == "c"):
            return RewindAction(CLOSE)
        shown = self.visible()
        if event.name == ENTER:
            return RewindAction(PICK, shown[min(self.index, len(shown) - 1)]) if shown else None
        steps = {UP: -1, DOWN: 1, PAGE_UP: -self.page, PAGE_DOWN: self.page}
        arc = list_nav_step(event)
        if arc and shown:
            self.index = min(max(self.index + arc, 0), len(shown) - 1)
        elif event.name in steps and shown:
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
        """A header row, the filtered prompts scrolled so the highlighted one shows, then the filter row
        (`session_picker.picker_frame`)."""
        shown = self.visible()
        self.index = min(self.index, max(len(shown) - 1, 0))
        frame = picker_frame(
            (Span(TITLE.format(count=len(self.rows)), theme.heading),), len(shown), self.index,
            lambda number: self._row(shown[number], number == self.index, width, theme, now),
            " no prompt matches the filter", self.query, width, theme, max_rows,
        )
        self.page, self.caret = frame.page, frame.caret
        return frame.lines

    def _row(self, row: RewindRow, highlighted: bool, width: int, theme: Theme, now: float) -> Line:
        return picker_row(highlighted, f"#{row.ordinal} ", row.label, age_text(row.timestamp, now), width, theme)
