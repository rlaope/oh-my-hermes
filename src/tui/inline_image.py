"""An inline image preview: Hermes' `image.render` answer turned into rows the transcript draws.

Hermes renders an image the person attached in one of two forms. `unicode` is a
grid of half-block cells, each a top and a bottom RGBA colour; `kitty` is a
picture the terminal holds (sent once as `transmit`, a kitty graphics APC) and
rows of Unicode placeholders that show it where they are drawn. Everything in
the answer is checked before any of it is used: an answer that is off, out of
shape or out of bounds gives no preview at all, never a partial one.

The kitty `transmit` is the only escape sequence the TUI writes on Hermes'
word, so it is held to the exact form Hermes' `encode_kitty_virtual` writes:
one transmit-and-place command for a virtual placement of this image, at this
size, split into base64 chunks, and nothing else between or around them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from .style import Line, Span, Style

PREVIEW_MAX_COLS = 64  # Hermes' cap (methods_images._MAX_PREVIEW_COLS)
PREVIEW_MAX_ROWS = 16
# The most previews the TUI keeps: of attached images by label (`App.previews`), and of prompts in the transcript.
PREVIEW_KEEP = 32
# The longest transmit Hermes can write for a 64x16 preview: 1024x512 RGBA pixels (2 px per 8x16 cell pixel) are
# 2 MiB raw, a PNG of noise does not compress below that, and base64 and the chunk frames add a third, about 2.8 MiB
# (Hermes' encoder measured 2,689,491 characters for RGBA noise). A longer one is not Hermes' and is not walked.
TRANSMIT_MAX_CHARS = 4 * 1024 * 1024

MODE_KITTY = "kitty"
MODE_UNICODE = "unicode"

PLACEHOLDER = "\U0010eeee"  # kitty's Unicode placeholder for a cell of a virtual placement
UPPER_HALF = "▀"
LOWER_HALF = "▄"
OPAQUE_ALPHA = 32  # an alpha at or above this paints its half, as Hermes' own TUI paints it (cellImage.tsx)

_CHUNK_PAYLOAD_MAX = 4096
# Row r of a placeholder carries kitty's r-th row diacritic: the first 16 of kitty's `rowcolumn-diacritics`, as
# Hermes' `agent/terminal_image.py` (`_ROWCOL_DIACRITICS`) copies them.
ROW_DIACRITICS = (
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
    0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357,
)
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
# One chunk of a kitty transmit. ASCII only, so `\d` is 0-9 and nothing else a terminal might read as a digit.
_CHUNK = re.compile(
    r"\x1b_G(?:a=T,U=1,i=(\d{1,8}),c=(\d{1,3}),r=(\d{1,3}),f=100,q=2,)?m=([01]);([A-Za-z0-9+/=]*)\x1b\\",
    re.ASCII,
)


@dataclass(frozen=True)
class Preview:
    mode: str  # "kitty" | "unicode"
    cols: int
    rows: int
    lines: tuple[Line, ...]  # exactly `rows` rows, each exactly `cols` cells wide (line_width)
    transmit: str = ""  # kitty only: the validated APC bytes to write once
    image_id: int = 0  # kitty only


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _in_bounds(value: object, most: int) -> bool:
    return _is_int(value) and 1 <= value <= most


def _hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02x}{green:02x}{blue:02x}"


def _cell_span(cell: list[int], spans: dict[tuple[str, str | None, str | None], Span]) -> Span:
    """One half-block cell: the upper half on top, the lower below, as Hermes' own TUI paints them. Cells that look
    the same share one span (`spans`, one per preview), so a preview holds a span per colour pair, not per cell."""
    top, bottom = cell[:4], cell[4:]
    top_opaque, bottom_opaque = top[3] >= OPAQUE_ALPHA, bottom[3] >= OPAQUE_ALPHA
    if top_opaque and bottom_opaque:
        key = (UPPER_HALF, _hex(*top[:3]), _hex(*bottom[:3]))
    elif top_opaque:
        key = (UPPER_HALF, _hex(*top[:3]), None)
    elif bottom_opaque:
        key = (LOWER_HALF, _hex(*bottom[:3]), None)
    else:
        key = (" ", None, None)
    span = spans.get(key)
    if span is None:
        span = spans[key] = Span(key[0], Style(fg=key[1], bg=key[2], gutter=True))
    return span


def _is_cell(cell: object) -> bool:
    return isinstance(cell, list) and len(cell) == 8 and all(_is_int(value) and 0 <= value <= 255 for value in cell)


def _unicode_lines(cells: object, cols: int, rows: int) -> tuple[Line, ...] | None:
    if not isinstance(cells, list) or len(cells) != rows:
        return None
    if not all(isinstance(row, list) and len(row) == cols and all(map(_is_cell, row)) for row in cells):
        return None
    spans: dict[tuple[str, str | None, str | None], Span] = {}
    return tuple(tuple(_cell_span(cell, spans) for cell in row) for row in cells)


def _kitty_lines(placeholder: object, color: str, cols: int, rows: int) -> tuple[Line, ...] | None:
    """The placeholder rows, row r one placeholder with kitty's r-th row diacritic and then `cols - 1` more."""
    if not isinstance(placeholder, list) or len(placeholder) != rows:
        return None
    rest = PLACEHOLDER * (cols - 1)
    for index, row in enumerate(placeholder):
        if not isinstance(row, str) or len(row) != cols + 1 or row[0] != PLACEHOLDER or row[2:] != rest:
            return None
        if row[1] != chr(ROW_DIACRITICS[index]):
            return None
    return tuple((Span(row, Style(fg=color, gutter=True)),) for row in placeholder)


def _transmit_image_id(transmit: object, cols: int, rows: int) -> int | None:
    """The image id of a kitty transmit in exactly the form Hermes writes it, at `cols` x `rows`; None for any other.

    The whole string is chunks back to back: the first, and only the first, carries the transmit-and-place control
    for a virtual placement; every chunk but the last says more follows (`m=1`), the last says it is done (`m=0`);
    as Hermes' `_kitty_apc` cuts them, every payload but the last is exactly 4096 characters and the last is 1 to 4096.
    """
    if not isinstance(transmit, str) or not transmit or len(transmit) > TRANSMIT_MAX_CHARS:
        return None
    image_id = None
    position = 0
    done = False
    while position < len(transmit):
        if done:
            return None  # a chunk after the one that said it was the last
        chunk = _CHUNK.match(transmit, position)
        if chunk is None:
            return None
        found_id, found_cols, found_rows, more, payload = chunk.groups()
        if (found_id is not None) != (position == 0):
            return None
        if found_id is not None:
            if int(found_cols) != cols or int(found_rows) != rows:
                return None
            image_id = int(found_id)
        if not payload or len(payload) > _CHUNK_PAYLOAD_MAX or (more == "1" and len(payload) != _CHUNK_PAYLOAD_MAX):
            return None
        done = more == "0"
        position = chunk.end()
    return image_id if done else None


def _valid_transmit(transmit: object, image_id: int, cols: int, rows: int) -> bool:
    """True when `transmit` is a kitty transmit Hermes wrote, at `cols` x `rows`, for the image `image_id` names.

    `image_id` is what the placeholder colour carries, the low 24 bits of the id, so only those are compared."""
    found = _transmit_image_id(transmit, cols, rows)
    return found is not None and found & 0xFFFFFF == image_id & 0xFFFFFF


def preview_from(result: Mapping[str, Any]) -> Preview | None:
    """The preview an `image.render` answer draws; None when it draws none (off, or anything out of shape)."""
    if not isinstance(result, Mapping):
        return None
    mode, cols, rows = result.get("mode"), result.get("cols"), result.get("rows")
    if mode not in (MODE_KITTY, MODE_UNICODE):
        return None
    if not _in_bounds(cols, PREVIEW_MAX_COLS) or not _in_bounds(rows, PREVIEW_MAX_ROWS):
        return None
    if mode == MODE_UNICODE:
        lines = _unicode_lines(result.get("cells"), cols, rows)
        return None if lines is None else Preview(MODE_UNICODE, cols, rows, lines)
    color = result.get("color")
    if not isinstance(color, str) or _COLOR.fullmatch(color) is None:
        return None
    color = color.lower()
    lines = _kitty_lines(result.get("placeholder"), color, cols, rows)
    transmit = result.get("transmit")
    if lines is None or not _valid_transmit(transmit, int(color[1:], 16), cols, rows):
        return None
    image_id = int(_CHUNK.match(transmit).group(1))  # the first chunk's control, checked just above
    return Preview(MODE_KITTY, cols, rows, lines, transmit=transmit, image_id=image_id)
