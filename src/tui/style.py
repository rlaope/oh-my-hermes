"""Styled text for the OMH TUI: a `Line` is a tuple of `Span`s, each with a `Style`.

Colours are `#rrggbb` strings, the same tokens `skin_pack.skin_colors` hands
out, and are painted as 24-bit SGR (38;2 / 48;2). A colour that is not a plain
hex token is skipped rather than guessed, so a bad palette entry shows default
colour instead of a wrong one.

A style can be painted at a lower colour depth (`Style.depth`): `256` paints
the nearest colour of the xterm 256-colour cube or grey ramp (38;5), `16` the
nearest of the sixteen ANSI colours (30-37, 90-97), and `none` no colour at all
(bold and the other attributes stay). `color_depth` reads the depth an output
supports from its environment. Only the colour parameters change with the
depth, never the text, so a row is the same width at every depth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from ..skin_pack import hex_to_rgb

CSI = "\x1b["
SGR_RESET = f"{CSI}0m"

_BOLD = "1"
_DIM = "2"
_ITALIC = "3"
_UNDERLINE = "4"
_REVERSE = "7"
_FOREGROUND = 38
_BACKGROUND = 48

TRUECOLOR = "truecolor"
COLOR_256 = "256"
COLOR_16 = "16"
NO_COLOR = "none"
COLOR_DEPTHS = (TRUECOLOR, COLOR_256, COLOR_16, NO_COLOR)

# The levels of the xterm 256-colour cube (16-231) and the sixteen ANSI colours as xterm draws them by default: what a
# colour is matched against to choose an index, never a colour the TUI chooses (the theme does that).
_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)
_ANSI_16 = (
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255),
    (255, 255, 255),
)


def color_depth(environ: Mapping[str, str], tty: bool = True) -> str:
    """The colour depth an output takes: none when it is not a terminal, `NO_COLOR` is set or `TERM` is dumb;
    24-bit when `COLORTERM` says truecolor or 24bit; 256 when `TERM` names a 256-colour terminal; else 16."""
    term = environ.get("TERM", "")
    if not tty or environ.get("NO_COLOR") or term == "dumb":
        return NO_COLOR
    if environ.get("COLORTERM", "").strip().lower() in ("truecolor", "24bit"):
        return TRUECOLOR
    return COLOR_256 if "256color" in term else COLOR_16


def _distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> int:
    return sum((a - b) ** 2 for a, b in zip(first, second, strict=True))


def nearest_256(rgb: tuple[int, int, int]) -> int:
    """The index of the cube colour or grey (16-255) nearest `rgb`."""
    levels = [min(range(6), key=lambda at: abs(_CUBE_LEVELS[at] - channel)) for channel in rgb]
    cube = (16 + 36 * levels[0] + 6 * levels[1] + levels[2], tuple(_CUBE_LEVELS[at] for at in levels))
    grey_at = min(range(24), key=lambda at: abs(8 + 10 * at - sum(rgb) / 3))
    grey = (232 + grey_at, (8 + 10 * grey_at,) * 3)
    return min((cube, grey), key=lambda candidate: _distance(candidate[1], rgb))[0]


def nearest_16(rgb: tuple[int, int, int]) -> int:
    """The index of the ANSI colour (0-15) nearest `rgb`."""
    return min(range(16), key=lambda at: _distance(_ANSI_16[at], rgb))


@lru_cache(maxsize=16384)
def _colour_parameter(base: int, value: str | None, depth: str = TRUECOLOR) -> str:
    if value is None or depth == NO_COLOR:
        return ""
    rgb = hex_to_rgb(value)
    if rgb is None:
        return ""
    if depth == COLOR_256:
        return f"{base};5;{nearest_256(rgb)}"
    if depth == COLOR_16:
        index = nearest_16(rgb)
        return str(base - 8 + index if index < 8 else base + 52 + index - 8)
    red, green, blue = rgb
    return f"{base};2;{red};{green};{blue}"


@dataclass(frozen=True)
class Style:
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    depth: str = TRUECOLOR  # how its colours are painted (`COLOR_DEPTHS`)
    # A cell that frames the text and is no part of it (a block's rail, a reply's margin): never painted differently,
    # and left out of what the pager copies (`Pager.handle_mouse`).
    gutter: bool = False

    def sgr(self) -> str:
        """The SGR sequence that turns this style on; "" for the default style."""
        parameters = [
            code
            for enabled, code in (
                (self.bold, _BOLD),
                (self.dim, _DIM),
                (self.italic, _ITALIC),
                (self.underline, _UNDERLINE),
                (self.reverse, _REVERSE),
            )
            if enabled
        ]
        for base, value in ((_FOREGROUND, self.fg), (_BACKGROUND, self.bg)):
            parameter = _colour_parameter(base, value, self.depth)
            if parameter:
                parameters.append(parameter)
        if not parameters:
            return ""
        return f"{CSI}{';'.join(parameters)}m"


DEFAULT_STYLE = Style()


@dataclass(frozen=True)
class Span:
    text: str
    style: Style = DEFAULT_STYLE


Line = tuple[Span, ...]


def fill(style: Style) -> Span:
    """The span that ends a row whose rest takes `style`'s background, to the right edge (`screen.paint_line`)."""
    return Span("", style)


def is_fill(span: Span) -> bool:
    return not span.text and span.style.bg is not None
