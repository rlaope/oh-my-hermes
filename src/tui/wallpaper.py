"""The living wallpaper (owner request 2026-10-29): each launch look paints the terminal's background its own colour
and keeps a scene moving in the screen's blank cells.

The background is the look's `ground` (`theme.look_ground`), which the app
sets as the terminal's default background with OSC 11 while the wallpaper
shows and puts back on every way out (`App._sync_ground`). This module says
only which cells of the scene are lit at a clock time: `scene(look, cols,
rows, seconds, light)` is every lit cell of a `cols` by `rows` screen as
`Cell(row, col, char, fg, bg)`, a pure function of its arguments (no state,
and the scattering comes from a fixed hash, `_noise`, not from `random`), so
the same moment always gives the same cells. The screen layer
(`screen.LiveRegion`) keeps the cells that fall on a blank cell, paints them
with absolute moves over the screen and takes them off before anything can
scroll, as it does the working glow's frame, so none reaches the scrollback.

The scenes are pixel art (owner's choice of 2026-10-29, after characters
such as `%t;:` and rings of `O` read as broken text): a cell is two pixels,
one over the other, drawn with a half block, `▀` in the top pixel's colour
over the bottom pixel's as background, `▄` for a bottom pixel alone, and for
two of one colour a space on that colour, which fills the whole cell where a
block glyph would leave the terminal's line spacing showing as a stripe; a
pixel left out shows the ground. Nothing else is drawn.

The art follows the brand's pixel-aura short (owner's choice of 2026-10-29):
an aura (`_aura`) is a mosaic of solid square tiles over an ellipse, dense in
the middle and scattering out to single tiles, each patch in one of a few
colours and each tile a shade apart, and four-point sparkles (`_sparkles`,
`SPARKLE`) grow and fade round the motifs. The default look, spectrum, keeps
only its ground and draws no scene (owner's choice of 2026-10-30). The other
looks draw their motif in this language, from small bitmaps kept here as
data (`Sprite`: rows of letters, each letter a colour role a scene maps to one
of the look's colours, `.` left out), some with frames that make them move: moonlit a crescent moon in a
pixel halo that breathes, soft tile clouds drifting and sparkle stars;
sakura blossom clusters over a faint pink aura with petals falling; aurora
ribbons of scattered tiles whose tops wave; ember a flame flickering through
three frames in a warm glow, with embers rising; gold a sun in a breathing
glow, sparkles for rays, and motes; violet pastel jellyfish drifting, their
bells pulsing; graphite a cloud raining into a puddle whose ripples spread.
The motifs sit low on the right (`BAND`, `RIGHT`), where the launch card and
a working session's rows leave the screen blank.

It is ambience behind work: never more than `LIT_CEILING` of the screen, no
pixel past `AMBIENT_CONTRAST` against the ground, and a pixel's colour is
stepped to `LEVELS`, so a cell keeps its bytes until a pixel in it changes
and the screen layer repaints only what moved. Everything that moves moves
within a second.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math

from .theme import (
    BLACK, LAUNCH_PALETTES, WHITE, LogoPalette, _logo_stops, blend, contrast_ratio, is_light,
)

# How often the app paints the scene's changed cells between frames (a turn's frames, every spinner tick, bring it
# along too): about four times a second keeps the motion visible within a second while an idle screen writes little.
TICK_SECONDS = 0.25
PEAK = 0.9  # the furthest a pixel's colour goes from the ground toward the look's, where the cap allows it
LEVELS = 8  # brightness steps: a cell keeps its bytes until its step changes
# No pixel stands out from the ground by more than this, well under the 4.5:1 the theme gives words: ambience never
# reads as loud as text. A step that would is taken down until it does not.
AMBIENT_CONTRAST = 3.0
# At most this share of a screen's cells is lit at any moment: motifs big enough to read at a glance, and five cells
# in six left to the ground, so the scene stays behind the work rather than a picture over it (the test samples every
# look on six screen sizes).
LIT_CEILING = 1 / 6
MIN_COLS, MIN_ROWS = 80, 24  # a screen smaller than this has no scene (its ground still shows): the motifs need room
TAU = 2 * math.pi
# The only glyphs drawn: a cell's top pixel, its bottom pixel, and for two of one colour a space on that background,
# which fills the cell to its edges where a block glyph leaves the terminal's line spacing showing as a stripe.
UPPER, LOWER, FULL = "▀", "▄", " "
# The rows the motifs keep to, as shares of the screen's: the lower half, over the composer, which is blank under the
# launch screen's card and, in a working session, at the right ends of the transcript's rows; and the right side
# (`RIGHT`), where a working session's rows end short of the edge and their tails are blank.
BAND = (0.62, 0.9)
RIGHT = 0.45  # the share of the width the right side starts at
CLEAR = "."  # a bitmap's pixel left out: the ground shows
PASTEL = 0.12  # how far every colour is softened toward white first: the pixel aura's pastels (more turns them grey
# under the contrast cap on a dark ground)
AURA_TILE = 2  # an aura's tile, in pixels a side: the aura is a mosaic of square tiles, not a speckle
# The brand's pixel-aura hues (the `oh-my-hermes` pixel-aura short): violet, pink, cyan, mint and periwinkle.
UNDER_DARK = 0.7
AURORA_FROM = 0.35  # aurora: the share of the width its curtains start at, wider than the other motifs
AURORA_LEAST = 0.5  # aurora: the dimmest a curtain's column gets, so every column of it shows  # on a dark ground, how far toward black the shade every colour is mixed from sits
TWO_CLOUD_CELLS = 4000  # moonlit: a screen of this many cells has room for a second cloud beside the moon
BIG_COLS, BIG_ROWS, BIG_SCALE = 140, 40, 2  # a screen this big draws the motifs' art pixels two pixels square

Sprite = tuple[str, ...]  # a bitmap, top row first, one letter a pixel: a colour role, or `CLEAR`

MOON: Sprite = (  # a clean crescent moon: a rim, b body, c shade
    "..........aa.........",
    "......aaaaaa.........",
    ".....aabbba..........",
    "....abbbba...........",
    "...abbbbba...........",
    "..abbbbbba...........",
    ".aabbbbbba...........",
    ".abbbbbbba...........",
    ".abbbbbbba...........",
    ".abbbbbbba...........",
    "abbbbbbbbba..........",
    "abbbbbbbbba..........",
    ".abbbbbbbbba.........",
    ".abbbbbbbbbba........",
    ".abbbbbbbbbccaa......",
    ".aabbbbbbbcccccaaaaaa",
    "..abbbbbbcccccccccca.",
    "...abbbbcccccccccca..",
    "....abbcccccccccca...",
    ".....aaccccccccaa....",
    "......aaaaccaaaa.....",
    "..........aa.........",
)
SPARKLE: tuple[Sprite, Sprite, Sprite] = (  # a four-point sparkle growing: s arm, w centre
    ("w",),
    (".s.", "sws", ".s."),
    ("..s..", "..s..", "sswss", "..s..", "..s.."),
)
BLOSSOM: Sprite = (  # five petals round a centre: p petal, q petal's shade, c centre
    ".p.p.",
    "ppqpp",
    ".qcq.",
    "ppqpp",
    "..p..",
)
PETAL: tuple[Sprite, Sprite] = (("pq",), ("p", "q"))  # a falling petal, turning
FLAME: tuple[Sprite, Sprite, Sprite] = (  # the fire's three frames: r outer red, o orange, y yellow core
    (
        ".....r......",
        "....rr......",
        "....ror.....",
        "...rroor..r.",
        "...roooor.r.",
        "..rrooyorrr.",
        "..rooyyoor..",
        ".rrooyyyor..",
        ".rooyyyyoor.",
        ".rooyyyyyor.",
        "..rooyyyor..",
        "...rrooorr..",
    ),
    (
        "......r.....",
        "......rr....",
        ".....ror....",
        ".r..roorr...",
        ".r.roooor...",
        ".rrroyoorr..",
        "..rooyyoor..",
        "..royyyoorr.",
        ".rooyyyyoor.",
        ".roooyyyyor.",
        "..rooyyyor..",
        "..rrooorr...",
    ),
    (
        "............",
        ".....r..r...",
        "....rr.ror..",
        "....rorroor.",
        "...rooooor..",
        "...rooyyoor.",
        "..rroyyyoor.",
        "..rooyyyyor.",
        ".rooyyyyyor.",
        ".rooyyyyoor.",
        "..rooyyyor..",
        "...rroooor..",
    ),
)
SUN: Sprite = (  # a sun's disc: o rim, y body, w glint
    "...ooooo...",
    "..oyyyyyo..",
    ".oywwyyyyo.",
    "oywwyyyyyyo",
    "oywyyyyyyyo",
    "oyyyyyyyyyo",
    "oyyyyyyyyyo",
    "oyyyyyyyyyo",
    ".oyyyyyyyo.",
    "..oyyyyyo..",
    "...ooooo...",
)
JELLYFISH: tuple[Sprite, Sprite] = (  # its bell open, then pulsed shut: e edge, b bell, w glint, t tentacle
    (
        "....eeeee....",
        "..eebbbbbee..",
        ".ebwwbbbbbbe.",
        "ebwwbbbbbbbbe",
        "ebbbbbbbbbbbe",
        "eeeeeeeeeeeee",
        ".t..t..t..t..",
        ".t..t..t..t..",
        "..t..t..t..t.",
        "..t..t..t..t.",
        ".t..t..t..t..",
        ".t...t..t..t.",
        "..t..t...t...",
        "..t...t..t...",
        "......t......",
    ),
    (
        ".....eee.....",
        "...eebbbee...",
        "..ebwwbbbbe..",
        "..ewwbbbbbe..",
        "..ebbbbbbbe..",
        "..ebbbbbbbe..",
        "...eeeeeee...",
        "...t.t.t.t...",
        "..t..t..t.t..",
        "..t.t..t..t..",
        "...t..t..t...",
        "...t.t..t.t..",
        "..t..t...t...",
        "..t...t..t...",
        "......t......",
    ),
)
SPRITES: dict[str, Sprite | tuple[Sprite, ...]] = {
    "MOON": MOON, "SPARKLE": SPARKLE, "BLOSSOM": BLOSSOM, "PETAL": PETAL, "FLAME": FLAME, "SUN": SUN,
    "JELLYFISH": JELLYFISH,
}


@dataclass(frozen=True)
class Cell:
    """One lit cell of the scene: where on the screen (0-based), its half-block glyph, its colour, and the colour
    under the glyph's other half (None: the ground)."""

    row: int
    col: int
    char: str
    fg: str
    bg: str | None = None


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


def _frame(frames: tuple[Sprite, ...], seconds: float, period: float, phase: float = 0.0) -> Sprite:
    """The frame of `frames` showing at `seconds`, each held `period` seconds in turn."""
    return frames[int(seconds / period + phase * len(frames)) % len(frames)]


class _Canvas:
    """The pixels being drawn, two to a cell's height (`height` pixel rows), the later of two on one pixel winning;
    each colour the ground mixed toward a colour by a stepped strength (`tone`)."""

    def __init__(self, cols: int, rows: int, ground: str, seconds: float) -> None:
        self.cols, self.rows, self.ground, self.seconds = cols, rows, ground, seconds
        self.height = 2 * rows
        self.pixels: dict[tuple[int, int], str] = {}
        self.reach: dict[tuple[str, str], float] = {}  # (colour, under) -> the furthest mix within the cap
        # What a colour is mixed from: on a dark ground a darker shade of it, so a tile keeps its hue (mixed into a
        # navy, a pale yellow turns grey; mixed from near black it stays a soft gold), on a light ground the ground.
        self.under = ground if is_light(ground) else blend(ground, BLACK, UNDER_DARK)

    def tone(self, colour: str, strength: float, under: str = "") -> str | None:
        """`colour` mixed from `under` (the ground unless named: a pale colour mixed toward black keeps its hue where
        mixed into a dark ground it turns grey) by `strength` (0 to 1, stepped to `LEVELS`) of the furthest mix that
        stays within `AMBIENT_CONTRAST` of the ground, so a motif's shades stay apart under the cap; None where the
        strength rounds to nothing."""
        steps = round(_clamp(strength, 0.0, 1.0) * LEVELS)
        if steps <= 0:
            return None
        under = under or self.under
        reach = self.reach.get((colour, under))
        if reach is None:
            reach = PEAK
            while reach > 0 and contrast_ratio(blend(under, colour, reach), self.ground) > AMBIENT_CONTRAST:
                reach -= 1 / 64
            self.reach[colour, under] = reach = max(reach, 0.0)
        return blend(under, colour, reach * steps / LEVELS)

    def dot(self, y: float, x: float, colour: str | None) -> None:
        """Light pixel (`y`, `x`) (pixel rows, columns) in `colour`, already toned; nothing off screen or for None."""
        at = (int(math.floor(y)), int(math.floor(x)))
        if colour is not None and 0 <= at[0] < self.height and 0 <= at[1] < self.cols:
            self.pixels[at] = colour

    def sprite(self, top: float, left: float, art: Sprite, colours: Mapping[str, str | None], scale: int = 1) -> None:
        """Draw `art` with its top-left pixel at (`top`, `left`), each letter in its colour, each art pixel `scale`
        pixels square; `CLEAR` left out."""
        for down, line in enumerate(art):
            for across, letter in enumerate(line):
                if letter == CLEAR:
                    continue
                for y in range(scale):
                    for x in range(scale):
                        self.dot(top + down * scale + y, left + across * scale + x, colours.get(letter))

    def scale(self) -> int:
        """How many pixels square a motif's art pixel is drawn: two on a big screen, so a motif reads at a glance."""
        return BIG_SCALE if self.cols >= BIG_COLS and self.rows >= BIG_ROWS else 1

    def band(self) -> tuple[int, int]:
        """The pixel rows the motifs keep to (`BAND`), first and last."""
        return int(self.height * BAND[0]), int(self.height * BAND[1])

    def cells(self) -> tuple[Cell, ...]:
        """The pixels as cells: `▀` in the top pixel's colour over the bottom one's as its background, `▄` for a bottom
        pixel alone, and a space on the colour where both are one (`FULL`)."""
        cells: dict[tuple[int, int], Cell] = {}
        for (y, x) in self.pixels:
            row = y // 2
            if (row, x) in cells:
                continue
            top, bottom = self.pixels.get((2 * row, x)), self.pixels.get((2 * row + 1, x))
            if top is not None and top == bottom:
                cells[row, x] = Cell(row, x, FULL, top, top)
            elif top is not None:
                cells[row, x] = Cell(row, x, UPPER, top, bottom)
            else:
                cells[row, x] = Cell(row, x, LOWER, bottom or "")
        return tuple(cells[at] for at in sorted(cells))


def _pastel(colour: str) -> str:
    """`colour` softened toward white (`PASTEL`), the pixel aura's palette."""
    return blend(colour, WHITE, PASTEL)


def _aura(canvas: _Canvas, centre_y: float, centre_x: float, tall: float, wide: float, colours: Sequence[str],
          salt: int, breath: float = 1.0, fill: float = 0.85, hollow: float = 0.0) -> None:
    """A pixel aura (the brand's, after the `oh-my-hermes` pixel-aura short): square tiles of `AURA_TILE` pixels a side
    scattered over an ellipse `tall` pixel rows by `wide` columns round (`centre_y`,
    `centre_x`), solid near the middle and thinning out to single tiles at the rim, each patch of it in one of
    `colours` (`_pastel`) and each tile a shade lighter or darker. Which tiles are lit is fixed by place (`salt`), so
    the aura only changes where `breath` (its size, near 1) moves the rim; `hollow` leaves the middle out, for a
    halo."""
    tile = AURA_TILE
    reach_y, reach_x = tall / 2 * breath, wide / 2 * breath
    first_y, first_x = int((centre_y - reach_y) // tile), int((centre_x - reach_x) // tile)
    for tile_y in range(first_y, int((centre_y + reach_y) // tile) + 1):
        for tile_x in range(first_x, int((centre_x + reach_x) // tile) + 1):
            y, x = tile_y * tile, tile_x * tile
            down, across = (y + tile / 2 - centre_y) / (tall / 2), (x + tile / 2 - centre_x) / (wide / 2)
            far = down * down + across * across  # the place's own distance: breathing moves only the rim
            if far >= breath * breath or far < hollow * hollow:
                continue
            spot = tile_y * 7919 + tile_x
            if _noise(spot, salt) > min(1.0, 1.5 * fill * max(1 - far, 0.0) ** 0.8) + 0.06:
                continue
            region = (math.atan2(down, across) / TAU + 0.5 + 0.25 * _noise((tile_y // 3) * 977 + tile_x // 4, salt + 1))
            colour = _pastel(colours[int(region * len(colours)) % len(colours)])
            tone = canvas.tone(colour, 0.5 + 0.35 * max(1 - far, 0.0) + 0.3 * (_noise(spot, salt + 2) - 0.5))
            for row in range(tile):
                for col in range(tile):
                    canvas.dot(y + row, x + col, tone)


def _sparkles(canvas: _Canvas, centre_y: float, centre_x: float, tall: float, wide: float, count: int,
              colour: str, seconds: float, salt: int) -> None:
    """`count` four-point sparkles over an area `tall` by `wide` pixels round (`centre_y`, `centre_x`), each growing
    through `SPARKLE`'s frames and gone again in turn, at its own pace."""
    colours = {"s": canvas.tone(_pastel(colour), 1.0), "w": canvas.tone(WHITE, 1.0)}
    scale = canvas.scale()
    for index in range(count):
        phase = (seconds / (1.6 + 1.2 * _noise(index, salt)) + _noise(index, salt + 1)) % 1
        step = int(phase * 6)  # off, small, medium, large, medium, small
        if step == 0:
            continue
        frame = SPARKLE[(0, 0, 1, 2, 1, 0)[step]]
        y = centre_y + (_noise(index, salt + 2) - 0.5) * tall - len(frame) * scale // 2
        x = centre_x + (_noise(index, salt + 3) - 0.5) * wide - len(frame[0]) * scale // 2
        canvas.sprite(y, x, frame, colours, scale)


def _moonlit(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A clean pixel crescent moon on the right with a pastel pixel halo that breathes, soft pixel clouds drifting,
    and sparkle stars twinkling."""
    cols = canvas.cols
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    scale = canvas.scale()
    wide, tall = len(MOON[0]), len(MOON)  # one pixel an art pixel: it fits the band at any size
    moon_top, moon_left = max(top, bottom - tall - 4), cols - wide - 12
    centre_y, centre_x = moon_top + tall / 2, moon_left + wide / 2
    _aura(canvas, centre_y, centre_x, tall * 1.6, wide * 1.6, (stops[2], stops[3], stops[1]), 31,
          breath=1 + 0.05 * math.sin(TAU * seconds / 3), fill=0.4, hollow=0.66)
    moon = _pastel(stops[0])
    canvas.sprite(moon_top, moon_left, MOON, {"a": canvas.tone(moon, 1.0), "b": canvas.tone(moon, 0.85),
                                              "c": canvas.tone(moon, 0.6)})
    for index in range(1 if cols * canvas.rows < TWO_CLOUD_CELLS else 2):
        span = cols * (1 - RIGHT) + 40 * scale
        left = cols * RIGHT + ((0.2 + 0.5 * index) * span + seconds * 0.6) % span - 20 * scale
        _aura(canvas, bottom - (6 + 10 * index) * scale, left + 10 * scale, 7 * scale, 22 * scale,
              (stops[3], stops[4], stops[2]), 41 + index, fill=0.8)
    _sparkles(canvas, (top + bottom) / 2, cols * (0.5 + RIGHT / 2), bottom - top, cols * (1 - RIGHT), 9, stops[0],
              seconds, 51)


def _sakura(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """Clusters of cherry blossom on the right, each a soft pink pixel cloud with five-petal blossoms in it, petals
    falling from them, swaying and turning, and sparkles."""
    cols, height = canvas.cols, canvas.height
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    scale = canvas.scale()
    petals = {"p": canvas.tone(stops[0], 1.0), "q": canvas.tone(stops[0], 0.7), "c": canvas.tone(stops[-1], 1.0)}
    sway = math.sin(TAU * seconds / 3.0)
    for index in range(3):
        centre_y = top + (bottom - top) * (0.2 + 0.25 * index)
        centre_x = cols - (0.08 + 0.12 * index) * cols * (1 - RIGHT) * 2
        _aura(canvas, centre_y, centre_x, 14 * scale, 30 * scale, (stops[1], stops[0], stops[1]), 61 + index,
              breath=1 + 0.03 * sway, fill=0.22)
        for blossom in range(5):
            y = centre_y + (_noise(index * 7 + blossom, 62) - 0.5) * 9 * scale - 2 * scale
            x = centre_x + (blossom - 2) * 6 * scale + (_noise(index * 7 + blossom, 63) - 0.5) * 3 * scale \
                - 2 * scale
            canvas.sprite(y, x, BLOSSOM, petals, scale)
    for index in range(_count(cols, canvas.rows, 140)):
        fall = 3.5 + 3.0 * _noise(index, 1)
        y = (_noise(index, 2) * (height + 4) + seconds * fall) % (height + 4) - 2
        drift = (2 + 2 * _noise(index, 3)) * math.sin(TAU * (seconds / (2 + 2 * _noise(index, 4)) + _noise(index, 5)))
        x = cols * RIGHT + (_noise(index, 6) * cols * (1 - RIGHT) - y * 0.3 + drift) % (cols * (1 - RIGHT))
        colours = {"p": canvas.tone(_pastel(stops[index % 2]), 0.9), "q": canvas.tone(_pastel(stops[index % 2]), 0.6)}
        canvas.sprite(y, x, _frame(PETAL, seconds, 0.6, _noise(index, 7)), colours)
    _sparkles(canvas, (top + bottom) / 2, cols * (0.5 + RIGHT / 2), bottom - top, cols * (1 - RIGHT), 6, stops[1],
              seconds, 64)


def _aurora(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """Curtains of light across the band's whole width and height, in the aura's tiles: ribbons of tile columns (four
    lit, one dark in turn), dense under a waving crest near the band's top and thinning out to its bottom, each
    column at least half lit (`AURORA_LEAST`), in the look's mint, teal and violet; sparkle stars along the top.
    Filling the band whole, the curtains read in a short band too: the launch screen's card for aurora, a box per
    section, leaves only the band's lower rows blank on a short screen."""
    cols = canvas.cols
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    tall = bottom - top
    tile = AURA_TILE
    for tile_x in range(int(cols * AURORA_FROM) // tile, cols // tile + 1):
        if tile_x % 5 == 4:
            continue  # the dark fold between two ribbons
        x = tile_x * tile
        glow = AURORA_LEAST + (1 - AURORA_LEAST) * (0.5 + 0.5 * math.sin(TAU * x / (cols * 0.35)))
        crest = top + tall * 0.12 * (1 + math.sin(TAU * (x / (cols * 0.4) + seconds / 7)))
        colour = _pastel(stops[min(int(x / cols * len(stops)), len(stops) - 1)])
        for tile_y in range(int(crest) // tile, bottom // tile + 1):
            y = tile_y * tile
            fade = _clamp(1 - (y - crest) / max(bottom - crest, 1), 0.0, 1.0)
            if _noise(tile_y * 7919 + tile_x, 71) > 0.3 + 0.65 * fade:
                continue  # scattered: thinning out below
            tone = canvas.tone(colour, glow * (0.45 + 0.55 * fade))
            for row in range(tile):
                for col in range(tile):
                    canvas.dot(y + row, x + col, tone)
    _sparkles(canvas, top + 4, cols * (0.5 + AURORA_FROM / 2), 10, cols * (1 - AURORA_FROM), 7, stops[1], seconds, 72)


def _ember(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A fire low on the right: a warm pastel pixel glow, a flame flickering through three frames over it, embers
    rising from it as square pixels, and sparkles."""
    cols = canvas.cols
    stops = _logo_stops(palette)
    _top, bottom = canvas.band()
    scale = canvas.scale()
    flame = _frame(FLAME, seconds, 0.25)
    wide, tall = len(flame[0]) * scale, len(flame) * scale
    left, flame_top = int(cols * 0.8) - wide // 2, bottom - tall
    _aura(canvas, bottom - tall * 0.35, left + wide / 2, tall * 1.1, wide * 2.6, (stops[0], stops[1], stops[2]), 81,
          breath=1 + 0.05 * _wave(seconds, 3.0, 0.0), fill=0.6)
    colours = {"r": canvas.tone(_pastel(stops[-1]), 0.9), "o": canvas.tone(_pastel(stops[2]), 1.0),
               "y": canvas.tone(_pastel(stops[0]), 1.0)}
    canvas.sprite(flame_top, left, flame, colours, scale)
    for index in range(_count(cols, canvas.rows, 320)):
        height = canvas.height * (0.3 + 0.4 * _noise(index, 1))
        risen = (seconds * (4.0 + 3.0 * _noise(index, 2)) + _noise(index, 3) * height) % height
        share = risen / height
        x = left + wide / 2 + (_noise(index, 4) - 0.5) * wide * 1.4 \
            + 3 * math.sin(TAU * (seconds / 2 + _noise(index, 5))) * share
        tone = canvas.tone(_pastel(stops[min(1 + int(share * (len(stops) - 1)), len(stops) - 1)]), 1 - 0.7 * share)
        canvas.sprite(flame_top - risen, x, ("ee", "ee") if scale > 1 else ("e",), {"e": tone})
    _sparkles(canvas, flame_top - tall, left + wide / 2, tall * 2, wide * 4, 5, stops[0], seconds, 82)


def _gold(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A soft pixel sun on the right: its disc, a warm pastel pixel glow round it that breathes, sparkles twinkling
    round it as its rays, and motes floating."""
    cols = canvas.cols
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    scale = canvas.scale()
    size = len(SUN) * scale
    sun_top, sun_left = top + 6 * scale, cols - size - 16
    centre_y, centre_x = sun_top + size / 2, sun_left + size / 2
    for index in range(_count(cols, canvas.rows, 120)):
        x = cols * RIGHT + _noise(index, 1) * cols * (1 - RIGHT) \
            + 3 * math.sin(TAU * (seconds / (5 + 4 * _noise(index, 2)) + _noise(index, 3)))
        y = top + _noise(index, 4) * (bottom - top)
        canvas.dot(y, x, canvas.tone(_pastel(stops[1 + index % 3]), 0.4 + 0.5 * _wave(seconds, 2, _noise(index, 8))))
    _aura(canvas, centre_y, centre_x, size * 2.2, size * 2.6, (stops[0], stops[1], stops[2]), 91,
          breath=1 + 0.05 * math.sin(TAU * seconds / 2.5), fill=0.55, hollow=0.3)
    canvas.sprite(sun_top, sun_left, SUN, {"o": canvas.tone(_pastel(stops[2]), 1.0),
                                           "y": canvas.tone(_pastel(stops[1]), 1.0),
                                           "w": canvas.tone(_pastel(stops[0]), 1.0)}, scale)
    _sparkles(canvas, centre_y, centre_x, size * 2.6, size * 3.2, 8, stops[0], seconds, 92)


def _violet(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """Three pastel pixel jellyfish drifting slowly across the screen's right side in the lower half, each with a
    soft glow behind its bell, the bell pulsing between two frames and its tentacles trailing; sparkles round them."""
    cols = canvas.cols
    stops = _logo_stops(palette)
    top, bottom = canvas.band()
    scale = canvas.scale()
    width, tall = len(JELLYFISH[0][0]) * scale, len(JELLYFISH[0]) * scale
    for index in range(3):
        span = cols * (1 - RIGHT) + width
        x = cols * RIGHT + ((index / 3 + 0.1 * _noise(index, 1)) * span + seconds * 0.5) % span - width  # spaced
        y = top + max(bottom - top - tall, 0) * (0.15 + 0.35 * index)
        colour = _pastel(stops[(2 * index + 1) % len(stops)])
        _aura(canvas, y + tall * 0.2, x + width / 2, tall * 0.7, width * 1.6, (colour,), 101 + index, fill=0.32,
              hollow=0.45)
        colours = {"e": canvas.tone(colour, 1.0), "b": canvas.tone(colour, 0.7),
                   "w": canvas.tone(_pastel(stops[0]), 1.0), "t": canvas.tone(colour, 0.55)}
        canvas.sprite(y, x, _frame(JELLYFISH, seconds, 1.2, _noise(index, 4)), colours, scale)
    _sparkles(canvas, (top + bottom) / 2, cols * (0.5 + RIGHT / 2), bottom - top, cols * (1 - RIGHT), 7, stops[0],
              seconds, 104)


def _graphite(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """A soft grey pixel cloud on the right raining cool pastel streaks into a puddle low on the screen, where each
    landing drop spreads a pixel ripple; a sparkle now and then. One drop in six is the look's turquoise."""
    cols = canvas.cols
    grey = palette.greys[0] if palette.greys else palette.label
    top, puddle = canvas.band()
    scale = canvas.scale()
    cloud_y, cloud_x, cloud_wide = top + 6 * scale, cols * (0.5 + RIGHT / 2), cols * (1 - RIGHT) * 0.8
    _aura(canvas, cloud_y, cloud_x, 10 * scale, cloud_wide, (grey, palette.spark or grey, grey), 111,
          breath=1 + 0.03 * math.sin(TAU * seconds / 4), fill=0.8)
    for col in range(int(cloud_x - cloud_wide / 2), int(cloud_x + cloud_wide / 2)):
        if _noise(col, 50) < 0.5:
            canvas.dot(puddle, col, canvas.tone(_pastel(grey), 0.45))
    fall_from = cloud_y + 3 * scale
    for index in range(_count(cols, canvas.rows, 220)):
        fall = 14.0 + 6.0 * _noise(index, 1)
        cycle = puddle - fall_from + 12
        drop, travel = divmod(seconds * fall + _noise(index, 2) * cycle, cycle)
        col = int(cloud_x + (_noise(index * 131 + int(drop), 3) - 0.5) * cloud_wide)
        colour = _pastel(palette.spark if palette.spark and index % 6 == 0 else grey)
        if fall_from + travel < puddle:
            for tail in range(3):
                canvas.dot(fall_from + travel - tail, col, canvas.tone(colour, 0.85 - 0.2 * tail))
        else:
            ring = (fall_from + travel - puddle) / 12
            tone = canvas.tone(colour, 0.9 - 0.6 * ring)
            for step in range(16):
                angle = step * TAU / 16
                canvas.dot(puddle + (1 + 2 * ring) * math.sin(angle), col + (2 + 8 * ring) * math.cos(angle), tone)
    _sparkles(canvas, (top + puddle) / 2, cloud_x, puddle - top, cloud_wide, 3, palette.spark or grey, seconds, 112)


def _kanagawa_wave(canvas: _Canvas, palette: LogoPalette, seconds: float) -> None:
    """An ambient ocean swell on the right: rolling wave bands with sea spray motes and crest sparkles."""
    stops = _logo_stops(palette)
    cols = canvas.cols
    top, bottom = canvas.band()
    tall = bottom - top
    scale = canvas.scale()
    wave_from = cols * RIGHT
    wave_wide = cols * (1 - RIGHT)

    for layer in (0, 1):
        period = 7.0 + layer * 3.0
        phase = seconds / period + layer * 0.4
        colour_idx = (layer * 2) % len(stops)
        colour = _pastel(stops[colour_idx])
        layer_offset = layer * 4 * scale
        for tile_y in range(top // AURA_TILE, bottom // AURA_TILE):
            y = tile_y * AURA_TILE
            for tile_x in range(int(wave_from) // AURA_TILE, cols // AURA_TILE):
                x = tile_x * AURA_TILE
                rel_x = (x - wave_from) / max(wave_wide, 1.0)
                crest_shape = math.sin(math.pi * min(rel_x, 1.0)) * (0.5 + 0.3 * rel_x)
                crest = (bottom - (tall * 0.35 * crest_shape) - layer_offset
                         + math.sin(TAU * (rel_x * 1.5 - phase)) * 2.0 * scale)
                crest = _clamp(crest, top + 2, bottom)
                if crest <= y <= bottom:
                    depth = (y - crest) / max(bottom - crest, 1.0)
                    fade = (1.0 - depth * 0.6) * (0.4 + 0.6 * rel_x)
                    if _noise(tile_y * 4099 + tile_x + layer * 1337, 43) > 0.45 + 0.5 * fade:
                        continue
                    toned = canvas.tone(colour, fade)
                    for dy in range(AURA_TILE):
                        for dx in range(AURA_TILE):
                            canvas.dot(y + dy, x + dx, toned)

    spray_colour = _pastel(stops[-1])
    count = _count(cols, canvas.rows, 240)
    for index in range(count):
        mote_x = wave_from + wave_wide * (0.2 + 0.8 * _noise(index, 3))
        rel_x = (mote_x - wave_from) / max(wave_wide, 1.0)
        crest_shape = math.sin(math.pi * min(rel_x, 1.0)) * (0.5 + 0.3 * rel_x)
        base_y = bottom - (tall * 0.35 * crest_shape)
        speed = 0.5 + 0.5 * _noise(index, 7)
        cycle = 4.0 / speed
        time_offset = _noise(index, 5) * cycle
        progress = ((seconds + time_offset) % cycle) / cycle
        spray_h = tall * (0.25 + 0.35 * _noise(index, 11))
        mote_y = base_y - progress * spray_h
        mote_x += math.sin(TAU * (progress + _noise(index, 13))) * 2.0 * scale
        if top <= mote_y <= bottom and 0 <= mote_x < cols:
            share = progress
            toned = canvas.tone(spray_colour, (1.0 - share) * 0.8)
            canvas.dot(mote_y, mote_x, toned)

    _sparkles(canvas, bottom - tall * 0.35, cols * (0.5 + RIGHT / 2), tall * 0.4, wave_wide * 0.8, 6,
              stops[1 % len(stops)], seconds, 91)


SCENES: dict[str, Callable[[_Canvas, LogoPalette, float], None]] = {
    "violet": _violet, "gold": _gold, "graphite": _graphite,
    "sakura": _sakura, "moonlit": _moonlit, "aurora": _aurora, "ember": _ember,
    "kanagawa-wave": _kanagawa_wave,
}


def scene(look: str, cols: int, rows: int, seconds: float, light: bool) -> tuple[Cell, ...]:
    """Every lit cell of launch look `look`'s scene on a `cols` by `rows` screen at clock time `seconds`, in its
    light set on a light terminal; none for the default look (it has no scene) or an unknown name, which takes the
    default look, nor on a screen under `MIN_COLS` by `MIN_ROWS`. The same arguments give the same cells."""
    if cols < MIN_COLS or rows < MIN_ROWS or look not in SCENES:
        return ()
    palette = LAUNCH_PALETTES[look][1 if light else 0]
    canvas = _Canvas(cols, rows, palette.ground, seconds)
    SCENES[look](canvas, palette, seconds)
    return canvas.cells()
