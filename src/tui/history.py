"""Hermes' own input history, and the Ctrl+R search over the composer's.

`$HERMES_HOME/.hermes_history` is the file Hermes' TUI keeps (ui-tui
`lib/history.ts`; `~/.hermes` when HERMES_HOME is unset, as there), so a
prompt typed in `hermes --tui` is in the OMH TUI's Up and Ctrl+R, and one
typed here is in Hermes'. Its format is that file's: each entry is a
`# <time>` line followed by one `+`-prefixed line per line of the entry, and
any other line ends an entry. Lines end in LF, as Ink writes them on every
platform. A line's one trailing CR is dropped as it is read, so a CRLF file
(edited by hand, or written on Windows before the append was binary) reads as
its LF twin; Ink keeps that CR, but writes none itself.

What the OMH TUI does with it, and nothing more:

- `load_history` reads at most the file's last `HISTORY_READ_BYTES` and keeps
  its newest entries; when that cut falls inside the file, everything before
  the first `#` line after it is dropped, so no entry is read in part. A file
  that is missing or cannot be read is no history.
- `append_entry` appends one entry with a single write to a descriptor opened
  `O_APPEND` (each write lands whole at the end, so it interleaves with
  Hermes' own appends entry by entry), `O_NOFOLLOW` (a symlink in the file's
  place is refused, not followed), `O_BINARY` where the platform has it (on
  Windows a text-mode descriptor would write each LF as CRLF) and, for a file
  it creates, mode 0600. It
  never rewrites, truncates or creates the directory the file goes in. A
  failure costs the entry and nothing else: it returns False.

The app calls `append_entry` only for what the composer records, a line the
person sent: never an answer to a question Hermes asked, never masked input.

`HistorySearch` is the inline search Ctrl+R opens in the slot: newest match
first, Ctrl+R again for older ones, Enter takes the match into the composer,
Esc, Ctrl+C or Ctrl+G cancel, Backspace on an empty query cancels too. Its
query row is its last row, drawn where the composer is (the app hides the
composer while it is open, as for a picker), and its caret is at the end of
the query there, so an IME pre-edit shows where the text goes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import stat

from .composer import HISTORY_CAP, PROMPT
from .keys import BACKSPACE, CHAR, ENTER, ESCAPE, Key, Paste, list_nav_step
from .style import Line, Span
from .theme import Theme
from .width import cell_width, truncate_line

HISTORY_FILE = ".hermes_history"
# The most of the file read at start: about ten thousand typical prompts, far past the entries kept.
HISTORY_READ_BYTES = 1 << 20
ENTRY_LINE = "+"
HEADER_LINE = "#"

SEARCH_ACCEPT = "accept"
SEARCH_CANCEL = "cancel"
SEARCH_LABEL = "⌕ search history: "
SEARCH_HINT = "ctrl+r older · enter takes it · esc cancels"
# Shorter forms for a narrow info line, longest first: the last keeps only the way out.
SEARCH_HINTS = (SEARCH_HINT, "ctrl+r older · esc cancels", "esc cancels")
SEARCH_NONE = "no earlier prompt holds it"
_CANCEL_CHARS = frozenset("cg")  # with Ctrl


def history_path(environ: Mapping[str, str]) -> Path | None:
    """Where the file is: under HERMES_HOME, else `~/.hermes` (Hermes' own rule); None without a home at all."""
    hermes_home = environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home) / HISTORY_FILE
    home = environ.get("HOME")
    return Path(home) / ".hermes" / HISTORY_FILE if home else None


def parse_entries(text: str) -> list[str]:
    """The entries in `text`, oldest first: each run of `+` lines, without the `+` or one trailing CR."""
    entries: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        line = line[:-1] if line.endswith("\r") else line
        if line.startswith(ENTRY_LINE):
            current.append(line[len(ENTRY_LINE) :])
        elif current:
            entries.append("\n".join(current))
            current = []
    if current:
        entries.append("\n".join(current))
    return entries


def load_history(path: Path, limit: int = HISTORY_CAP, read_bytes: int = HISTORY_READ_BYTES) -> list[str]:
    """The newest `limit` entries of the file at `path`, oldest first, read from at most its last `read_bytes`.

    Only a regular file is read: a symlink in its place is not followed (as the
    append does not follow one), and a FIFO is opened without waiting for a
    writer and then refused, so starting the TUI never blocks on it.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return []
    try:
        regular = stat.S_ISREG(os.fstat(descriptor).st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(descriptor)
        return []
    with os.fdopen(descriptor, "rb") as handle:  # closes the descriptor whatever happens below
        try:
            size = handle.seek(0, os.SEEK_END)
            start = max(size - read_bytes, 0)
            handle.seek(start)
            data = handle.read(read_bytes)
        except OSError:
            return []
    text = data.decode("utf-8", "replace")
    if start:
        header = text.find("\n" + HEADER_LINE)
        text = text[header + 1 :] if header >= 0 else ""
    return parse_entries(text)[-limit:] if limit > 0 else []


def append_entry(path: Path, text: str) -> bool:
    """Append `text` (stripped) as one entry in the file's format; False when blank or when the write failed."""
    entry = text.strip()
    if not entry:
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    record = f"\n{HEADER_LINE} {stamp}\n" + "".join(f"{ENTRY_LINE}{line}\n" for line in entry.split("\n"))
    data = record.encode("utf-8", "replace")
    flags = (
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_BINARY", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        return False
    try:
        while data:
            data = data[os.write(descriptor, data) :]
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return True


@dataclass
class HistorySearch:
    """Ctrl+R's search over `entries` (oldest first); `original` is the composer's text as the search opened."""

    entries: Sequence[str]
    original: str
    query: str = ""
    skip: int = 0  # older matches Ctrl+R has stepped past
    caret: tuple[int, int] | None = None  # the last render's caret, at the end of the query on its query row

    def matches(self) -> list[str]:
        """Every entry holding the query (any case), newest first."""
        needle = self.query.casefold()
        return [entry for entry in reversed(self.entries) if needle in entry.casefold()]

    def current(self) -> str | None:
        found = self.matches()
        return found[min(self.skip, len(found) - 1)] if found else None

    def handle_key(self, event: Key | Paste) -> str | None:
        """One key: SEARCH_ACCEPT, SEARCH_CANCEL, or None while the search goes on."""
        if isinstance(event, Paste):
            self._query(self.query + event.text.split("\n", 1)[0])
            return None
        if event.name == ESCAPE or (event.name == CHAR and event.ctrl and event.char in _CANCEL_CHARS):
            return SEARCH_CANCEL
        if event.name == ENTER:
            return SEARCH_ACCEPT if self.current() is not None else SEARCH_CANCEL
        step = list_nav_step(event)
        if step != 0 and self.matches():
            self.skip = min(max(self.skip + step, 0), len(self.matches()) - 1)
        elif event.name == CHAR and event.ctrl and event.char == "r":
            self.skip = min(self.skip + 1, max(len(self.matches()) - 1, 0))
        elif event.name == BACKSPACE:
            if not self.query:
                return SEARCH_CANCEL
            self._query(self.query[:-1])
        elif event.name == CHAR and not event.ctrl and not event.alt:
            self._query(self.query + event.char)
        return None

    def _query(self, query: str) -> None:
        self.query = query
        self.skip = 0

    def lines(self, width: int, theme: Theme, max_rows: int) -> list[Line]:
        """The match's first line and where it is among the matches, then the query row (its keys are on the info
        line, `SEARCH_HINTS`). One row is the query row."""
        self.caret = None
        if max_rows <= 0:
            return []
        query = truncate_line((Span(SEARCH_LABEL, theme.muted), Span(self.query)), width)
        found = self.matches()
        match = self.current()
        if match is None:
            shown = truncate_line((Span(f"  {SEARCH_NONE}", theme.muted),), width)
        else:
            count = f"  {min(self.skip, len(found) - 1) + 1}/{len(found)}"
            shown = truncate_line((Span(PROMPT, theme.prompt), Span(match.split("\n", 1)[0]), Span(count, theme.muted)), width)
        rows = [query] if max_rows == 1 else [shown, query]
        self.caret = (len(rows) - 1, min(cell_width(SEARCH_LABEL + self.query), max(width - 1, 0)))
        return rows
