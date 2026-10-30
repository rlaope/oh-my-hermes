"""The /theme picker: the launch looks in the slot, previewed on the logo and the card as the highlight moves.

It holds no IO: the app opens it on the look in use, feeds it keys and clicks,
previews the look under the highlight after every move, and on Enter keeps it
(saved under the OMH home) or on Esc puts the one from before back.

Keys: Up/Down (or k/j, as in the pagers) move one row; Enter keeps the
highlighted look; Esc or Ctrl+C closes. A click on a row moves the highlight
there. Where the launch card is no longer on screen to show the look, the app
puts a compact preview (`preview`) above the list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .keys import CHAR, DOWN, ENTER, ESCAPE, UP, Key, Paste
from .session_picker import CURRENT_MARK, pointer
from .style import Line, Span, Style
from .theme import LAUNCH_PRESETS, Theme
from .width import truncate_line

MOVE = "move"
PICK = "pick"
CLOSE = "close"
# Its keys, longest first: on the info line while it is open.
KEYS = ("↑↓ or a click previews · enter keeps it · esc puts the last one back", "↑↓ enter keeps · esc puts it back",
        "esc puts it back")
TITLE = " Launch look"
SUMMARIES = {
    "spectrum": "the five tool-kind hues swept across the logo · a box per section",
    "violet": "violet to magenta, the skill hue's family · one box",
    "gold": "caduceus gold · one box in two columns",
    "graphite": "grey and white, turquoise hyphens · rules, no side edges",
    "sakura": "pastel pink, sky blue and cream · one box",
    "moonlit": "moonlight yellow and silver over navy · rules, no side edges",
    "aurora": "emerald and teal into violet · a box per section",
    "ember": "amber through orange to crimson · one box in two columns",
    "kanagawa-wave": "indigo, spring teal and violet over sumi-ink · rules, no side edges",
}
SWATCH = "■"


@dataclass
class LaunchPicker:
    current: str  # the look in use as it opened: what Esc puts back
    index: int = 0
    first_row: int = 1  # the last render's row of the first look, under the preview and the header

    def __post_init__(self) -> None:
        self.index = LAUNCH_PRESETS.index(self.current) if self.current in LAUNCH_PRESETS else 0

    @property
    def highlighted(self) -> str:
        return LAUNCH_PRESETS[self.index]

    def handle_key(self, event: Key | Paste) -> str | None:
        """Apply one key: MOVE when the highlight moved, PICK on Enter, CLOSE on Esc or Ctrl+C, else None."""
        if isinstance(event, Paste):
            return None
        if event.name == ESCAPE or (event.name == CHAR and event.ctrl and event.char == "c"):
            return CLOSE
        if event.name == ENTER:
            return PICK
        plain = event.name == CHAR and not (event.ctrl or event.alt)
        if event.name in (UP, DOWN) or (plain and event.char in ("j", "k")):
            return self.move_to(self.index + (1 if event.name == DOWN or event.char == "j" else -1))
        return None

    def move_to(self, index: int) -> str | None:
        """Highlight row `index` (clamped); MOVE when that moved it."""
        index = min(max(index, 0), len(LAUNCH_PRESETS) - 1)
        if index == self.index:
            return None
        self.index = index
        return MOVE

    def lines(self, width: int, theme: Theme, max_rows: int, swatches: Mapping[str, Sequence[Style]],
              preview: Sequence[Line] = ()) -> list[Line]:
        """`preview` (when the rest still fits under it), a header row, then a row per look (its name, its colours,
        what it is), as many as `max_rows` holds."""
        shown = list(preview) if len(preview) + 1 + len(LAUNCH_PRESETS) <= max_rows else []
        rows: list[Line] = [*shown, truncate_line((Span(TITLE, theme.heading),), width)]
        self.first_row = len(rows)
        widest = max((len(swatches.get(name, ())) for name in LAUNCH_PRESETS), default=0)  # one summary column
        name_width = max(10, max(map(len, LAUNCH_PRESETS)) + 1)
        for index, name in enumerate(LAUNCH_PRESETS):
            highlighted = index == self.index
            mark = CURRENT_MARK if name == self.current else " "
            row: list[Span] = [pointer(highlighted, theme),
                               Span(f"{mark} {name:<{name_width}}", theme.menu_current if highlighted else theme.menu)]
            row += [Span(SWATCH, swatch) for swatch in swatches.get(name, ())]
            row.append(Span(" " * (widest - len(swatches.get(name, ())))))
            row.append(Span(f"  {SUMMARIES[name]}", theme.text if highlighted else theme.muted))
            rows.append(truncate_line(tuple(row), width))
        return rows[: max(max_rows, 0)]
