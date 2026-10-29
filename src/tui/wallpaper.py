"""The living wallpaper (owner request 2026-10-29): each launch look paints the terminal's background its own colour
and keeps a scene moving in the screen's blank cells.

The background is the look's `ground` (`theme.look_ground`), which the app
sets as the terminal's default background with OSC 11 while the wallpaper
shows and puts back on every way out (`App._sync_ground`). This module says
only which cells of the scene are lit at a clock time: `scene(look, cols,
rows, seconds, light)` is every lit cell of a `cols` by `rows` screen as
`Cell(row, col, char, fg)`, a pure function of its arguments (no state, and
the scattering comes from a fixed hash, `_noise`, not from `random`), so the
same moment always gives the same cells. The screen layer
(`screen.LiveRegion`) keeps the cells that fall on a blank cell, paints them
with absolute moves over the screen and takes them off before anything can
scroll, as it does the working glow's frame, so none reaches the scrollback.

Each look has one scene (`SCENES`), drawn with plain characters and blocks,
never emoji: one or two motifs at a size that reads at a glance, with dense
characters for their bodies (`BODY`, a texture each cell changes slowly, so
a body shimmers the way the owner's reference does), and light particles
around them. moonlit has a big crescent moon whose glow pulses, clouds
drifting and stars twinkling; sakura a blossoming branch from the top-right
corner with petals falling and swaying; aurora tall curtains of light waving
across the screen; ember a campfire near the bottom with flames flickering
and sparks rising; gold a large sun whose rays turn, and motes; violet large
soft bokeh drifting; graphite rain over a puddle that ripples where drops
land; spectrum a prism with a beam of light going in and fanning out into
the five hues. The motifs sit where a working session leaves the screen blank:
its right side (`RIGHT`), where transcript rows end short of the edge, and
for sakura's branch the top-right corner.

It is ambience behind work: never more than `LIT_CEILING` of the screen, no
cell past `AMBIENT_CONTRAST` against the ground, and a cell's colour is
stepped to `LEVELS`, so a cell keeps its bytes until its step or its
character changes and the screen layer repaints only what moved. Everything
that moves moves within a second.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

from .theme import BLACK, DEFAULT_LAUNCH, LAUNCH_PALETTES, LogoPalette, _logo_stops, blend, contrast_ratio, is_light

# How often the app paints the scene's changed cells between frames (a turn's frames, every spinner tick, bring it
# along too): about four times a second keeps the motion visible within a second while an idle screen writes little.
TICK_SECONDS = 0.25
PEAK = 0.9  # the brightest a cell gets: the look's colour this far from the ground
LEVELS = 8  # brightness steps: a cell keeps its bytes until its step changes
# No cell stands out from the ground by more than this, well under the 4.5:1 the theme gives words: ambience never
# reads as loud as text. A step that would is taken down until it does not.
AMBIENT_CONTRAST = 3.0
# At most this share of a screen's cells is lit at any moment: motifs big enough to read at a glance, and five cells
# in six left to the ground, so the scene stays behind the work rather than a picture over it (the test samples every
# look on six screen sizes).
LIT_CEILING = 1 / 6
MIN_COLS, MIN_ROWS = 80, 24  # a screen smaller than this has no scene (its ground still shows): the motifs need room
TAU = 2 * math.pi
BODY = "%t;:"  # a motif's body: dense characters, as the reference draws its clouds
SHIMMER_SECONDS = 2.5  # a body cell keeps its character about this long, then takes another
# The rows the motifs keep to, as shares of the screen's: under the top rows and over the composer. The motifs keep to
# the screen's right side (`RIGHT`), where a working session's rows end short of the edge and their tails are blank.
BAND = (0.06, 0.8)
RIGHT = 0.45  # the share of the width the right side starts at


@dataclass(frozen=True)
class Cell:
    """One lit cell of the scene: where on the screen (0-based), its character, and its colour."""

    row: int
    col: int
    char: str
    fg: str


def _noise(index: int, salt: int = 0) -> float:
    """A fixed pseudo-random number in [0, 1) for `index` and `salt` (a 32-bit integer hash), the same every call."""
    value = (index * 0x9E3779B1 + salt * 0x85EBCA77 + 0x165667B1) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value / 0x100000000


def _count(cols: int, rows: int, cells_each: int) -> int:
    """How many of a scattered thing a screen holds: one per `cells_each` cells, at least one."""
    return max(1, cols * rows // cells_each)


def _wave(seconds: float, period: float, phase: float) -> float:
    """0 to 1 and back over `period` seconds, starting `phase` (0 to 1) of the way through."""
    return 0.5 + 0.5 * math.sin(TAU * (seconds / period + phase))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


class _Canvas:
    """The lit cells being drawn, the later of two on one cell winning, each colour the ground mixed toward a colour
    by a stepped strength (`LEVELS`)."""

    def __init__(self, cols: int, rows: int, ground: str, seconds: float) -> None:
        self.cols, self.rows, self.ground, self.seconds = cols, rows, ground, seconds
        self.cells: dict[tuple[int, int], Cell] = {}

    def put(self, row: float, col: float, char: str, colour: str, strength: float, under: str = "") -> None:
        """Light the cell at (`row`, `col`) with `char` in `colour` mixed from `under` (the ground unless named: a
        pale colour mixed toward black keeps its hue where mixed into a dark ground it turns grey)."""
        steps = round(_clamp(strength, 0.0, 1.0) * LEVELS)
        at = (int(math.floor(row)), int(math.floor(col)))
        if steps <= 0 or not (0 <= at[0] < self.rows and 0 <= at[1] < self.cols):
            return
        under = under or self.ground
        mixed = blend(under, colour, PEAK * steps / LEVELS)
        while steps > 1 and contrast_ratio(mixed, self.ground) > AMBIENT_CONTRAST:
            steps -= 1
            mixed = blend(under, colour, PEAK * steps / LEVELS)
        self.cells[at] = Cell(at[0], at[1], char, mixed)

    def body(self, row: int, col: int, colour: str, strength: float, salt: int, chars: str = BODY,
             under: str = "") -> None:
        """A motif's body cell: a dense character that the cell keeps for about `SHIMMER_SECONDS`, picked by where
        the cell is on the screen (so a moving motif changes only its edges), then another."""
        spot = row * 7919 + col
        turn = int(self.seconds / SHIMMER_SECONDS + _noise(spot, salt))
        char = chars[int(_noise(spot + turn * 104729, salt + 1) * len(chars))]
        self.put(row, col, char, colour, strength, under)

    def band(self) -> tuple[int, int]:
        """The rows the motifs keep to (`BAND`), first and last."""
        return int(self.rows * BAND[0]), int(self.rows * BAND[1])


def _blob(canvas: _Canvas, top: float, left: float, wide: float, tall: float, colour: str, strength: float,
          salt: int) -> None:
    """A cloud-like body `wide` by `tall` cells at (`top`, `left`): a wide ellipse with two puffs on top, its rim a
    step lighter."""
    puffs = ((0.5, 0.62, 1.0, 1.0), (0.32, 0.38, 0.42, 0.55), (0.66, 0.34, 0.36, 0.5))  # centre x, y; half w, h
    for row in range(int(top), int(top + tall) + 1):
        for col in range(int(left), int(left + wide) + 1):
            depth = 0.0
            for share_x, share_y, half_w, half_h in puffs:
                across = (col + 0.5 - left - share_x * wide) / (half_w * wide / 2)
                down = (row + 0.5 - top - share_y * tall) / (half_h * tall / 2)
                depth = max(depth, 1 - (across * across + down * down))
            if depth > 0:
                canvas.body(row, col, colour, strength * (1.0 if depth > 0.3 else 0.65), salt)


def _moonlit(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A big crescent moon high on the right, its glow pulsing; clouds drifting right across the screen, one
    across the moon's foot; stars twinkling."""
    cols, rows = canvas.cols, canvas.rows
    stops = _logo_stops(palette)
    for index in range(_count(cols, rows, 110)):
        shine = _wave(seconds, 1.5 + 2 * _noise(index, 3), _noise(index, 4))
        char = "*" if shine > 0.8 else "+" if shine > 0.5 else "."
        canvas.put(_noise(index, 2) * rows, _noise(index, 1) * cols, char, stops[1], 0.3 + 0.7 * shine)
    top, bottom = canvas.band()
    radius = _clamp(rows * 0.11, 2.5, 5.0)  # in rows; a cell is half as wide as it is tall
    centre_row, centre_col = top + radius + 0.5, cols - 2 * radius - 8
    moonlight = canvas.ground if is_light(canvas.ground) else BLACK  # a pale gold on a dark ground, not a grey
    pulse = _wave(seconds, 2.4, 0.0)
    for row in range(int(centre_row - radius) - 2, int(centre_row + radius) + 3):
        for col in range(int(centre_col - 2 * radius) - 4, int(centre_col + 2 * radius) + 5):
            down, across = row + 0.5 - centre_row, (col + 0.5 - centre_col) / 2
            far = math.hypot(down, across)
            bite = math.hypot(down + 0.3 * radius, across - 0.5 * radius)  # the dark disc that leaves a crescent
            if far <= radius and bite >= 0.82 * radius:
                canvas.body(row, col, stops[0], 1.0, 9, "%#@", moonlight)
            elif radius < far <= radius + 1.4 and bite > 0.82 * radius + 1.6:  # the glow, round the lit side only
                canvas.put(row, col, "." if far > radius + 0.7 else ":", stops[0], 0.25 + 0.5 * pulse, moonlight)
    scale = min(1.0, cols / 150)
    for index in range(3):
        wide, tall = (14 + 6 * _noise(index, 11)) * scale + 6, 4 + 2 * _noise(index, 12)
        speed = 1.2 + 0.9 * index
        span = cols + wide
        left = (_noise(index, 13) * span + seconds * speed) % span - wide
        at = top + (bottom - top - tall) * (0.15 + 0.35 * index)
        if index == 2:
            at = centre_row + radius * 0.4  # the third passes across the moon's foot
        _blob(canvas, at, left, wide, tall, stops[2], 0.75, 20 + index)


def _sakura(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A cherry branch reaching in from the top-right corner with blossom clusters along it, swaying a little, and
    petals falling from it, swaying and turning as they fall."""
    cols, rows = canvas.cols, canvas.rows
    stops = _logo_stops(palette)
    reach, drop = min(cols * 0.36, 60.0), _clamp(rows * 0.32, 5, 14)
    sway = math.sin(TAU * seconds / 3.0)
    for step in range(int(reach)):
        share = step / reach
        col = cols - 1 - step
        row = drop * share ** 1.4 + 0.6 * sway * share
        canvas.put(row, col, "_" if share < 0.25 else "/" if share < 0.7 else ".", palette.edge, 1.0)
        if step % 9 == 4:  # a twig
            canvas.put(row + 1, col - 1, "\\", palette.edge, 0.8)
    for index in range(6):
        share = 0.12 + 0.15 * index
        col = cols - 1 - share * reach + sway
        row = drop * share ** 1.4 + 0.6 * sway * share
        wide, tall = 6 + 4 * _noise(index, 2), 3 + _noise(index, 3)
        for down in range(-1, int(tall)):
            for across in range(int(-wide / 2), int(wide / 2) + 1):
                if (across / (wide / 2)) ** 2 + ((down - tall / 3) / (tall / 2)) ** 2 <= 1:
                    canvas.body(int(row + down), int(col + across), stops[index % 2], 0.9, 30 + index, "*@%o")
    for index in range(_count(cols, rows, 70)):
        fall = 1.8 + 1.4 * _noise(index, 1)
        start = cols - _noise(index, 6) * reach * 1.4
        row = (_noise(index, 2) * (rows + 2) + seconds * fall) % (rows + 2) - 1
        drift = (2 + 2 * _noise(index, 3)) * math.sin(TAU * (seconds / (2 + 2 * _noise(index, 4)) + _noise(index, 5)))
        col = (start - row * 0.8 + drift) % cols
        char = "*'`,"[int(seconds * (1.5 + _noise(index, 7)) + 4 * _noise(index, 8)) % 4]
        canvas.put(row, col, char, stops[index % 2], 0.6 + 0.4 * _noise(index, 9))


def _aurora(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """Tall curtains of light across the screen's right side, their tops waving and their length breathing, bright at
    the top and fading down, in the look's green, teal and violet across the screen; a strand in every other
    column."""
    cols = canvas.cols
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    reach = (bottom - top) * 0.8
    for col in range(int(cols * RIGHT) // 2 * 2, cols, 2):
        glow = _wave(seconds, 9, col / (cols * 0.6))
        if glow < 0.2:
            continue
        crest = top + reach * (0.1 + 0.12 * math.sin(TAU * (col / (cols * 0.5) + seconds / 5)))
        length = reach * (0.3 + 0.3 * _wave(seconds, 6, col / (cols * 0.35)))
        colour = stops[min(int(((col / cols + seconds / 40) % 1) * len(stops)), len(stops) - 1)]
        for down in range(int(length)):
            fade = 1 - down / length
            char = "|" if fade > 0.6 else "!" if fade > 0.35 else ":"
            canvas.put(crest + down, col, char, colour, (0.35 + 0.65 * glow) * (0.3 + 0.7 * fade))


def _ember(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A campfire low on the right, over the composer: logs, flames flickering over them, and sparks rising from it and
    fading as they climb."""
    cols, rows = canvas.cols, canvas.rows
    stops = _logo_stops(palette)
    _top, bottom = canvas.band()
    centre, wide = cols * 0.8, _clamp(cols * 0.14, 10, 22)
    tall = _clamp(rows * 0.26, 5, 11)
    for across in range(int(-wide / 2), int(wide / 2) + 1):
        canvas.put(bottom, centre + across, "=" if across % 3 else "#", palette.edge, 1.0)
    flicker = int(seconds * 7)
    for up in range(1, int(tall) + 1):
        height = up / tall
        half = wide / 2 * (1 - height) ** 0.8
        for across in range(int(-half) - 1, int(half) + 2):
            edge = abs(across) / (half + 0.5)
            if _noise(up * 131 + across * 7 + flicker * 1009, 3) < edge * edge:
                continue  # a ragged, flickering edge
            heat = (1 - height) * (1 - 0.5 * edge)
            char = "#" if heat > 0.6 else "%" if heat > 0.4 else "*" if heat > 0.2 else "^"
            colour = stops[min(int(height * len(stops)), len(stops) - 1)]
            canvas.put(bottom - up, centre + across, char, colour, 0.5 + 0.5 * heat)
    for index in range(_count(cols, rows, 130)):
        height = rows * (0.3 + 0.4 * _noise(index, 1))
        rise = 3.0 + 3.0 * _noise(index, 2)
        risen = (seconds * rise + _noise(index, 3) * height) % height
        share = risen / height
        col = centre + (_noise(index, 4) - 0.5) * wide + 2 * math.sin(TAU * (seconds / 2 + _noise(index, 5))) * share
        char = "*" if share < 0.3 else "'" if share < 0.65 else "."
        colour = stops[min(1 + int(share * (len(stops) - 1)), len(stops) - 1)]
        canvas.put(bottom - tall * 0.5 - risen, col, char, colour, 1 - 0.8 * share)


def _gold(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A large sun high on the right, its body glinting and its rays turning slowly round it; motes
    floating across the screen."""
    cols, rows = canvas.cols, canvas.rows
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    for index in range(_count(cols, rows, 80)):
        col = _noise(index, 1) * cols + 3 * math.sin(TAU * (seconds / (5 + 4 * _noise(index, 2)) + _noise(index, 3)))
        bob = 1.5 * math.sin(TAU * (seconds / (4 + 4 * _noise(index, 5)) + _noise(index, 6)))
        row = top + _noise(index, 4) * (bottom - top) + bob
        shine = _wave(seconds, 1.5 + 2 * _noise(index, 7), _noise(index, 8))
        char = "*" if shine > 0.75 else "+" if shine > 0.45 else "."
        canvas.put(row, col, char, stops[1 + index % 3], 0.4 + 0.6 * shine)
    radius = _clamp(rows * 0.09, 2.0, 4.0)
    centre_row, centre_col = top + radius + 1.5, cols - 2 * radius - 16
    for row in range(int(centre_row - radius) - 1, int(centre_row + radius) + 2):
        for col in range(int(centre_col - 2 * radius) - 2, int(centre_col + 2 * radius) + 3):
            if math.hypot(row + 0.5 - centre_row, (col + 0.5 - centre_col) / 2) <= radius:
                canvas.body(row, col, stops[1], 1.0, 40, "@%#")
    turn = seconds * 0.5
    for ray in range(12):
        angle = turn + ray * TAU / 12
        char = "-|/\\"[_ray_glyph(angle)]
        for step in range(int(radius * 0.8)):
            reach = radius + 1.2 + step
            canvas.put(centre_row + reach * math.sin(angle), centre_col + 2 * reach * math.cos(angle), char,
                       stops[2], 0.85 - 0.5 * step / (radius * 0.8))


def _ray_glyph(angle: float) -> int:
    """Which of `-|/\\` draws a line at `angle` (radians, screen rows growing downward)."""
    eighth = int(((angle % math.pi) + math.pi / 8) / (math.pi / 4)) % 4  # 0 across, 1 down-right, 2 down, 3 down-left
    return (0, 3, 1, 2)[eighth]


def _violet(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """Four large, soft out-of-focus lights drifting right across the screen's right side and bobbing, each a ring with
    a sparse glow inside, breathing."""
    cols, rows = canvas.cols, canvas.rows
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    for index in range(4):
        radius = _clamp(rows * (0.07 + 0.03 * _noise(index, 1)), 2.0, 5.0)
        span = cols * (1 - RIGHT) + 4 * radius
        centre_col = cols * RIGHT + (_noise(index, 2) * span + seconds * (0.9 + 0.5 * _noise(index, 3))) % span \
            - 2 * radius
        centre_row = top + radius + (bottom - top - 2 * radius) * _noise(index, 4) \
            + math.sin(TAU * (seconds / 4 + _noise(index, 5)))
        breath = 0.55 + 0.45 * _wave(seconds, 3 + 2 * _noise(index, 6), _noise(index, 7))
        colour = stops[(2 * index) % len(stops)]
        for row in range(int(centre_row - radius) - 1, int(centre_row + radius) + 2):
            for col in range(int(centre_col - 2 * radius) - 2, int(centre_col + 2 * radius) + 3):
                far = math.hypot(row + 0.5 - centre_row, (col + 0.5 - centre_col) / 2)
                if abs(far - radius) < 0.55:
                    canvas.put(row, col, "o" if far < radius else "O", colour, breath)
                elif far < radius - 0.5 and (row + col) % 2 == 0:
                    canvas.put(row, col, ":", colour, breath * 0.45)


def _graphite(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """Rain falling into a puddle low on the screen, over the composer; where a drop lands a ripple spreads along the
    puddle's line. One drop in six is the look's turquoise."""
    cols, rows = canvas.cols, canvas.rows
    grey = palette.greys[0] if palette.greys else palette.label
    _top, puddle = canvas.band()
    surface = palette.whites[3] if palette.whites else palette.label
    for col in range(cols):
        if _noise(col, 50) < 0.55:
            canvas.put(puddle, col, "_" if _noise(col, 51) < 0.7 else "~", surface, 0.45)
    for index in range(_count(cols, rows, 200)):
        fall = 6.0 + 3.0 * _noise(index, 1)
        drop, travel = divmod(seconds * fall + _noise(index, 2) * (puddle + 6), puddle + 6)
        col = int(_noise(index * 131 + int(drop), 3) * cols)
        colour = palette.spark if palette.spark and index % 6 == 0 else grey
        if travel < puddle:
            for tail in range(3):
                canvas.put(travel - tail, col, "|", colour, 0.85 - 0.25 * tail)
        else:
            ring = int((travel - puddle) * 1.2) + 1  # landed: the ripple spreads for the rest of the fall's cycle
            canvas.put(puddle, col - 2 * ring, "(", colour, 0.9 - 0.12 * ring)
            canvas.put(puddle, col + 2 * ring, ")", colour, 0.9 - 0.12 * ring)


def _spectrum(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A prism on the screen's right side with a beam of light going in from the left and fanning out of it into the
    five hues to the right; pulses of light run along the beam and the rays."""
    cols, rows = canvas.cols, canvas.rows
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    tall = _clamp(rows * 0.3, 4, 10)
    apex_row, apex_col = rows * 0.42, cols * 0.66  # low enough for the launch screen's blank band too
    middle = apex_row + tall * 0.6
    for down in range(int(tall) + 1):
        half = down * 1.1
        canvas.put(apex_row + down, apex_col - half, "/", palette.label, 1.0)
        canvas.put(apex_row + down, apex_col + half, "\\", palette.label, 1.0)
        for across in range(int(-half) + 1, int(half)):
            if down == int(tall):
                canvas.put(apex_row + down, apex_col + across, "_", palette.label, 1.0)
            elif (across + down) % 3 == 0:
                canvas.put(apex_row + down, apex_col + across, ".", palette.label, 0.35)
    pulse = seconds * 8  # columns a second the light runs along the beam and the rays
    enter = int(apex_col - (middle - apex_row) * 1.1)
    for col in range(int(cols * RIGHT * 0.8), enter):
        canvas.put(middle, col, "=" if (col - pulse) % 21 < 2 else "-", palette.label, 0.8)
    leave = apex_col + (middle - apex_row) * 1.1
    for hue in range(len(stops)):
        slope = (hue - (len(stops) - 1) / 2) * 0.045  # rows per column: the fan opens to a few rows each way
        for step in range(int(cols - leave)):
            char = "=" if (step - pulse) % 23 < 2 else "-"
            canvas.put(middle + slope * step, leave + step, char, stops[hue], 0.9 - 0.3 * step / (cols - leave))


SCENES: dict[str, Callable[[_Canvas, LogoPalette, float], None]] = {
    "spectrum": _spectrum, "violet": _violet, "gold": _gold, "graphite": _graphite,
    "sakura": _sakura, "moonlit": _moonlit, "aurora": _aurora, "ember": _ember,
}


def scene(look: str, cols: int, rows: int, seconds: float, light: bool) -> tuple[Cell, ...]:
    """Every lit cell of launch look `look`'s scene on a `cols` by `rows` screen at clock time `seconds`, in its
    light set on a light terminal; the default look's for an unknown name, none on a screen under `MIN_COLS` by
    `MIN_ROWS`. The same arguments give the same cells."""
    if cols < MIN_COLS or rows < MIN_ROWS:
        return ()
    name = look if look in SCENES else DEFAULT_LAUNCH
    palette = LAUNCH_PALETTES[name][1 if light else 0]
    canvas = _Canvas(cols, rows, palette.ground, seconds)
    SCENES[name](canvas, palette, seconds)
    return tuple(canvas.cells[at] for at in sorted(canvas.cells))
