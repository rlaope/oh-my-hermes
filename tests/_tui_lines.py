"""Plain text out of the OMH TUI's styled lines, for assertions in the TUI tests."""

from __future__ import annotations

from collections.abc import Iterable

from omh.tui.frame import INFO_INSET as INFO_INSET_CELLS, RULE
from omh.tui.style import Line
from omh.tui import app as tui_app

INFO_INSET = " " * INFO_INSET_CELLS  # the info line under the composer's rule starts this far in


# The badge at the info line's left end without the version, longest form first (`badge_text` is the one with it).
BADGE_TEXTS = ("[⚚ OMH Native]", "[⚚ OMH]", "⚚")
BADGE_GAP = "  "  # between the badge and what follows it on the left
INFO_GAP = "   "  # between the left side and the right side's fields, at least


def badge_text() -> str:
    """The badge's longest form as the TUI draws it now: `[⚚ OMH Native v<version>]`, the version read where the
    badge reads it (`omh.tui.app.__version__`), so a test that pins the version sees the form it pinned."""
    return f"[⚚ OMH Native v{tui_app.__version__}]"


def info_row_index(screen: list[str]) -> int:
    """The info line's row: the last that is not blank, since every row under the region is (the agent view's rows
    aside, which tests that draw one place themselves)."""
    return max(index for index, row in enumerate(screen) if row)


def without_badge(row: str) -> str:
    """The info line's text with the badge at its left end taken out, its inset kept: what the line says after the
    badge, as the line read before the badge moved onto it. When nothing follows the badge on the left, the gap to
    the right side's fields stays at least `INFO_GAP` wide, as it is drawn."""
    body = row.removeprefix(INFO_INSET)
    for badge in (badge_text(), *BADGE_TEXTS):
        if body.startswith(badge):
            rest = body[len(badge) :]
            if rest.startswith(INFO_GAP):
                return INFO_INSET + rest
            return INFO_INSET + rest.removeprefix(BADGE_GAP) if rest.startswith(BADGE_GAP) or not rest.strip() else row
    return row


def line_text(line: Line) -> str:
    """The characters one styled line shows, styles dropped."""
    return "".join(span.text for span in line)


def lines_text(lines: Iterable[Line]) -> list[str]:
    """`line_text` of each line, in order."""
    return [line_text(line) for line in lines]


def composer_text(row: str) -> str:
    """A composer row as typed (the composer has no sides): trailing blanks dropped."""
    return row.rstrip()


def composer_row(text: str, cols: int) -> str:
    """The screen text of a composer row holding `text` at `cols` columns: the row itself, since the composer has no
    sides to pad to (a screen row's trailing blanks are dropped)."""
    return text[:cols]


def rule_edges(cols: int) -> tuple[str, str]:
    """The screen text of the composer's rules, above and under it, at `cols` columns."""
    return RULE * cols, RULE * cols


RULE_ROW = RULE * 2  # how one of the composer's rules starts on the screen: no other row starts with it


def rule_rows(rows: Iterable[str]) -> list[int]:
    """The indexes of the composer's rules among screen rows: its top rule first, then its bottom one."""
    return [index for index, row in enumerate(rows) if row.startswith(RULE_ROW)]
