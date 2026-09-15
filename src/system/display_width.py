"""How wide a string renders in a monospace cell, which is not its length.

`len("이슈")` is 2 and `len("#1612")` is 5, so padding by length puts those two
in columns of visibly different width -- a Korean or Japanese board pads to the
wrong place and the alignment a fenced block exists to provide is gone. East
Asian wide and fullwidth characters occupy two cells; combining marks and
format controls occupy none.

Three call sites computed this three ways before this module: the setup menu
had it right, the coding status board used `len`, and the messenger table
transform was about to add a third. One home, so a board and a chat bubble
cannot disagree about where a column starts.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def display_width(text: str) -> int:
    """Monospace cells ``text`` occupies, ignoring ANSI colour and zero-width marks."""
    visible = _ANSI_ESCAPE_RE.sub("", str(text))
    width = 0
    for character in visible:
        if unicodedata.combining(character):
            continue
        if unicodedata.category(character) in {"Cc", "Cf"}:
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
    return width


def pad_to_width(text: str, width: int) -> str:
    """Left-align ``text`` in a ``width``-cell column.

    `str.ljust` counts characters, so it under-pads any cell holding wide
    characters. A cell already wider than the column is returned unchanged
    rather than truncated: dropping content to keep a column straight trades a
    cosmetic problem for a correctness one.
    """
    return str(text) + " " * max(0, width - display_width(text))
