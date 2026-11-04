"""The living wallpaper (owner request 2026-10-29): each launch look gives the terminal its own background (OSC 11,
put back on every way out) and keeps a sparse scene moving in the screen's blank cells (`omh.tui.wallpaper`),
painted by the live region (`screen.LiveRegion`) on blank cells only and taken off before anything scrolls, so
nothing of it reaches the scrollback."""

from __future__ import annotations

import contextlib
import json
import math
from pathlib import Path
import random
import tempfile
import unicodedata
import unittest
from unittest import mock

import _vt_screen
from _vt_screen import VTScreen
from omh.skin_pack import (
    SKIN_THEMES,
    THEME_STORE_SCHEMA,
    default_theme,
    read_wallpaper_choice,
    skin_colors,
    theme_store_path,
    write_glow_choice,
    write_launch_choice,
    write_theme_choice,
    write_wallpaper_choice,
)
from omh.tui import app as app_module
from omh.tui.gateway import Event
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key
from omh.tui.screen import TEXT_GAP, LiveRegion
from omh.tui.style import TRUECOLOR, Span, Style
from omh.tui.terminal import background_restore, background_set
from omh.tui.theme import (
    DEFAULT_LAUNCH,
    EDGE_CONTRAST,
    GLYPH_ROLES,
    LAUNCH_PALETTES,
    LAUNCH_PRESETS,
    TEXT_CONTRAST,
    TEXT_ROLES,
    build_theme,
    contrast_ratio,
    is_light,
    launch_palette,
    launch_styles,
    look_ground,
    readable_on,
    with_launch_look,
    with_prompt_band,
)
from omh.tui.theme import MARK_STEPS, WORD_ROLES, WORD_STEPS
from omh.tui.wallpaper import (
    AMBIENT_CONTRAST, CLEAR, FULL, LIT_CEILING, LOWER, SCENES, SPRITES, UPPER, Cell, scene,
)
from omh.tui.width import cell_width
from test_tui_modes import make_app, notices, type_text
from test_tui_theme import oklab
import test_tui_working_glow as glow_tests

ANSWERED = "#1E1E1E"  # what the terminal answered the startup background query with
WALLPAPER_ON = {"COLORTERM": "truecolor", "TERM": "xterm-256color", "OMH_TUI_WALLPAPER": "1"}
MARK = "░"  # the test scene's glyph: every cell of the screen lit with it, so any cell it reaches shows
SIZES = ((150, 42), (80, 24), (100, 30), (200, 60), (80, 60), (250, 24))


class Recording(VTScreen):
    """The VT screen, keeping the attributes of every row it scrolls off into the scrollback, as the scrollback
    keeps its text: a background left on a scrolled row shows there although its text is a space."""

    def __init__(self, rows: int, cols: int) -> None:
        super().__init__(rows, cols)
        self.scrolled_attrs: list[tuple] = []

    def _line_feed(self) -> None:
        if self._row >= self.rows - 1:
            self.scrolled_attrs.append(tuple(self._attrs[0]))
        super()._line_feed()


@contextlib.contextmanager
def ambiguous_wide():
    """The VT screen drawing East Asian Ambiguous characters two cells wide, as a terminal with that option set does."""
    narrow = _vt_screen.cluster_width
    with mock.patch.object(_vt_screen, "cluster_width",
                           lambda cluster: 2 if len(cluster) == 1 and unicodedata.east_asian_width(cluster) == "A"
                           else narrow(cluster)):
        yield


ROLES = {  # each bitmap's letters, as its comment in `wallpaper` names them
    "MOON": "abc", "SPARKLE": "sw", "BLOSSOM": "pqc", "PETAL": "pq", "FLAME": "roy", "SUN": "oyw", "JELLYFISH": "ebwt",
}


class Clock:
    def __init__(self, at: float) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def everywhere(look: str, cols: int, rows: int, seconds: float, light: bool) -> tuple[Cell, ...]:
    """A scene that lights every cell of the screen: whatever of it lands where it may not, shows."""
    return tuple(Cell(row, col, MARK, "#445566") for row in range(rows) for col in range(cols))


CLOTH = "#7A1F3D"  # the colour of the pixels below that are a space on it


def everywhere_on_cloth(look: str, cols: int, rows: int, seconds: float, light: bool) -> tuple[Cell, ...]:
    """A scene of pixels that are a space on their colour, lighting every cell: a blank that leaves the colour on
    shows nothing to a text check, so these tests look for the colour."""
    return tuple(Cell(row, col, FULL, CLOTH, CLOTH) for row in range(rows) for col in range(cols))


def clothed(attrs: list[list[tuple]] | list[tuple]) -> bool:
    """Whether any cell of these rows carries a background of any colour (an SGR 48), the cloth or another a blank
    was written with."""
    def background(params: tuple) -> bool:
        at = 0
        while at < len(params):
            if params[at] in (38, 48, 58):  # an extended colour: its own 2;r;g;b or 5;n arguments follow
                if params[at] == 48:
                    return True
                at += 5 if params[at + 1:at + 2] == (2,) else 3
            else:
                at += 1
        return False

    return any(background(cell) for row in attrs for cell in row)


class SceneTests(unittest.TestCase):
    def test_every_look_but_the_default_has_its_scene_and_each_its_own_ground_dark_and_light(self) -> None:
        # The default look keeps only its ground (owner's choice of 2026-10-30): no picture, at any moment or size.
        self.assertEqual(set(SCENES), set(LAUNCH_PRESETS) - {DEFAULT_LAUNCH})
        for cols, rows in SIZES:
            for seconds in (0.0, 3.7, 10.9, 1234.5):
                for light in (False, True):
                    self.assertEqual(scene(DEFAULT_LAUNCH, cols, rows, seconds, light), (), (cols, rows, seconds))
        for side, light in ((0, False), (1, True)):
            grounds = {look: look_ground(look, light) for look in LAUNCH_PRESETS}
            self.assertEqual(len(set(grounds.values())), len(LAUNCH_PRESETS), "each look its own background")
            for look, ground in grounds.items():
                self.assertEqual(ground, LAUNCH_PALETTES[look][side].ground)
                self.assertEqual(is_light(ground), light, look)

    def test_the_terminals_own_foreground_stays_readable_on_every_ground(self) -> None:
        # Body text is the terminal's default foreground: a light one on a dark terminal (#C0C0C0 is a dim one) and
        # a dark one on a light terminal; on each ground it keeps well past the 4.5:1 words need.
        for look in LAUNCH_PRESETS:
            with self.subTest(look=look):
                self.assertGreaterEqual(contrast_ratio(look_ground(look, False), "#C0C0C0"), 7.0)
                self.assertGreaterEqual(contrast_ratio(look_ground(look, True), "#333333"), 7.0)

    def test_the_same_moment_gives_the_same_cells_and_the_scene_moves(self) -> None:
        for look in SCENES:
            with self.subTest(look=look):
                for seconds in (0.0, 3.7, 1234.5):
                    self.assertEqual(scene(look, 150, 42, seconds, False), scene(look, 150, 42, seconds, False))
                self.assertNotEqual(scene(look, 150, 42, 10.0, False), scene(look, 150, 42, 16.0, False))
                self.assertTrue(scene(look, 150, 42, 10.0, True))

    def test_a_scene_is_sparse_on_every_screen_and_at_every_moment(self) -> None:
        # The ceiling's reason is beside it (`LIT_CEILING`): ambience behind work, never a picture over it.
        for look in LAUNCH_PRESETS:
            for cols, rows in SIZES:
                for step in range(50):
                    lit = len(scene(look, cols, rows, step * 0.73, False))
                    self.assertLessEqual(lit, LIT_CEILING * cols * rows, (look, cols, rows, step))

    def test_a_scene_is_half_block_pixels_dimmer_than_words_on_its_ground(self) -> None:
        # Pixel art (owner's choice): `▀` over `▄`, a space on the colour where a cell's two pixels match; no text.
        for look in LAUNCH_PRESETS:
            for light in (False, True):
                ground = look_ground(look, light)
                for step in range(40):
                    for cell in scene(look, 150, 42, step * 1.3, light):
                        self.assertIn(cell.char, (UPPER, LOWER, FULL), (look, cell))
                        self.assertEqual(cell_width(cell.char), 1, (look, cell))
                        if cell.char == LOWER:
                            self.assertIsNone(cell.bg, "a bottom pixel alone has the ground above it")
                        if cell.char == FULL:
                            self.assertEqual(cell.bg, cell.fg, "two pixels of one colour: a space on it")
                        for colour in (cell.fg, cell.bg):
                            if colour is not None:
                                self.assertGreater(contrast_ratio(colour, ground), 1.0, (look, cell))
                                self.assertLessEqual(contrast_ratio(colour, ground), AMBIENT_CONTRAST, (look, cell))
                        self.assertLess(AMBIENT_CONTRAST, TEXT_CONTRAST)

    def test_the_bitmaps_are_well_formed(self) -> None:
        # Every frame's rows are one length, frames of one motif are one size, and each letter is a role its scene
        # colours (`ROLES`) or CLEAR.
        for name, art in SPRITES.items():
            frames = art if isinstance(art[0], tuple) else (art,)
            with self.subTest(sprite=name):
                sizes = {(len(frame), len(frame[0])) for frame in frames}
                self.assertEqual(len(sizes), 1 if name not in ("SPARKLE", "PETAL", "FLAME") else len(sizes), sizes)
                for frame in frames:
                    self.assertEqual(len({len(line) for line in frame}), 1, frame)
                    letters = {letter for line in frame for letter in line} - {CLEAR}
                    self.assertLessEqual(letters, set(ROLES[name]), (name, letters))
                    self.assertLessEqual(len(letters), 5, "three to five colours a motif")

    def test_aurora_reads_in_a_short_launch_band(self) -> None:
        # On the README's launch screen aurora's card (a box per section) ends about two thirds down (row 31 of 48
        # at 180x48, measured with the README runner's skills), leaving the band's lower rows only. The curtains fill
        # the band whole, so at least a fifth of those rows' cells are lit at any moment (before: about an eighth).
        for cols, rows in ((180, 48), (160, 60)):
            first, last = round(rows * 0.66), rows - 6  # under the card, over the composer
            for seconds in (0.0, 3.0, 7.0, 11.0):
                lit = sum(1 for cell in scene("aurora", cols, rows, seconds, False) if first <= cell.row <= last)
                with self.subTest(size=(cols, rows), seconds=seconds):
                    self.assertGreaterEqual(lit, 0.2 * (last - first + 1) * cols)

    def test_the_motifs_move(self) -> None:
        # Each frame-animated motif shows another frame within a second, and every scene changes within a second.
        for look in SCENES:
            with self.subTest(look=look):
                self.assertNotEqual(scene(look, 150, 42, 10.0, False), scene(look, 150, 42, 10.9, False))

    def test_a_small_screen_has_no_scene(self) -> None:
        self.assertEqual(scene("moonlit", 79, 30, 1.0, False), ())
        self.assertEqual(scene("moonlit", 100, 23, 1.0, False), ())
        self.assertEqual(scene("no-such-look", 150, 42, 1.0, False), ())  # the default look's, which has none


class GroundContrastTests(unittest.TestCase):
    def test_every_role_passes_its_floor_on_every_looks_ground(self) -> None:
        # Built as the app builds it on a ground (`App._themed`): the look's roles, then `readable_on`, which lifts the
        # stepped colours (a catch row's mark is the logo's colours as they are) against the ground as well.
        short = []
        for skin in SKIN_THEMES:
            for look in LAUNCH_PRESETS:
                for light in (False, True):
                    ground = look_ground(look, light)
                    banded = with_prompt_band(build_theme(skin, ground), skin, ground, look)
                    theme = readable_on(with_launch_look(banded, skin, ground, look), skin, ground)
                    inks = [(role, getattr(theme, role).fg, TEXT_CONTRAST) for role in TEXT_ROLES]
                    inks += [(role, getattr(theme, role).fg, EDGE_CONTRAST) for role in GLYPH_ROLES]
                    inks += [("catch_words", theme.catch_words.fg, TEXT_CONTRAST)]
                    inks += [("kinds", style.fg, TEXT_CONTRAST) for style in theme.kinds]
                    inks += [(role, style.fg, EDGE_CONTRAST) for role in MARK_STEPS for style in getattr(theme, role)]
                    inks += [(role, style.fg, TEXT_CONTRAST) for role in WORD_STEPS for style in getattr(theme, role)
                             if style.fg]
                    styles = launch_styles(skin, ground, launch_palette(look, ground))
                    inks += [("brand", styles.brand.fg, TEXT_CONTRAST), ("label", styles.label.fg, TEXT_CONTRAST),
                             ("edge", styles.edge.fg, EDGE_CONTRAST)]
                    short += [(skin.short_name, look, ground, role, round(contrast_ratio(fg, ground), 2))
                              for role, fg, floor in inks if contrast_ratio(fg, ground) < floor]
                    self.assertIsNotNone(theme.prompt_band.bg, "the ground is known, so bands paint")
        self.assertEqual(short[:12], [], f"{len(short)} inks under their floor")


def _hue(colour: str) -> tuple[float, float]:
    """`colour`'s OKLCH chroma and hue in degrees."""
    _lightness, a, b = oklab(colour)
    return math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


class SceneBandTests(unittest.TestCase):
    """On a dark scene look's ground (owner, 2026-11-04) the diff and outcome bands sit on the look with their hue
    kept, and the pager's footer bar takes the prompt band's colour; the default look keeps the skin's own."""

    BANDS = {"ok_band": "diff_added_word", "diff_add": "diff_added_word", "diff_add_word": "diff_added_word",
             "error_band": "diff_removed_word", "diff_remove": "diff_removed_word",
             "diff_remove_word": "diff_removed_word"}

    def themed(self, skin, look: str, answered: str = ANSWERED, environ=WALLPAPER_ON):
        app, _client = make_app(environ=environ)
        app.adopt_background(answered)
        app.theme = build_theme(skin, answered)
        app.launch_look = look
        return app._themed(), app._ground()

    def test_every_band_and_the_footer_bar_follow_a_dark_scene_ground_and_keep_their_floors_and_hue(self) -> None:
        short = []
        for skin in SKIN_THEMES:
            colours = skin_colors(skin.skin_name)
            for look in SCENES:
                theme, ground = self.themed(skin, look)
                self.assertEqual(ground, look_ground(look, False))
                for role, word in self.BANDS.items():
                    style = getattr(theme, role)
                    where = (skin.short_name, look, role, style.bg)
                    if contrast_ratio(style.bg, ground) < 1.2:
                        short.append((*where, "bg vs ground", round(contrast_ratio(style.bg, ground), 2)))
                    ink = style.fg or "#C0C0C0"  # an outcome band's words are the terminal's own foreground
                    if contrast_ratio(ink, style.bg) < TEXT_CONTRAST:
                        short.append((*where, "text", round(contrast_ratio(ink, style.bg), 2)))
                    (chroma, hue), (_word_chroma, word_hue) = _hue(style.bg), _hue(colours[word])
                    gap = min(abs(hue - word_hue), 360 - abs(hue - word_hue))
                    if gap > 10 or chroma < 0.02:
                        short.append((*where, "hue", round(gap, 1), round(chroma, 3)))
                self.assertEqual(theme.status.bg, theme.prompt_band.bg, (skin.short_name, look))
                if contrast_ratio(theme.status.fg, theme.status.bg) < TEXT_CONTRAST:
                    short.append((skin.short_name, look, "status",
                                  round(contrast_ratio(theme.status.fg, theme.status.bg), 2)))
        self.assertEqual(short[:12], [], f"{len(short)} under their floor or out of their hue")

    def test_the_default_look_a_light_ground_and_no_wallpaper_keep_the_skins_own_bands_and_bar(self) -> None:
        for skin in SKIN_THEMES:
            colours = skin_colors(skin.skin_name)
            fixed = {"ok_band": Style(bg=colours["diff_added"]), "error_band": Style(bg=colours["diff_removed"]),
                     "diff_add": Style(fg=colours["banner_text"], bg=colours["diff_added"]),
                     "diff_add_word": Style(fg=colours["diff_added_word"], bg=colours["diff_added"]),
                     "diff_remove": Style(fg=colours["banner_text"], bg=colours["diff_removed"]),
                     "diff_remove_word": Style(fg=colours["diff_removed_word"], bg=colours["diff_removed"])}
            theme, _ground = self.themed(skin, DEFAULT_LAUNCH)
            plain = build_theme(skin, ANSWERED)
            for role, style in fixed.items():
                self.assertEqual(getattr(theme, role), style, (skin.short_name, role))
            self.assertEqual(theme.status, plain.status, skin.short_name)
            self.assertEqual(theme.status.bg, colours["status_bar_bg"], skin.short_name)
            for look in SCENES:
                off, _ground = self.themed(skin, look, environ={**WALLPAPER_ON, "OMH_TUI_WALLPAPER": "0"})
                light, _ground = self.themed(skin, look, answered="#FAFAFA")
                light_plain = build_theme(skin, look_ground(look, True))
                for role in (*fixed, "status"):
                    self.assertEqual(getattr(off, role), getattr(plain, role), (skin.short_name, look, role))
                    self.assertEqual(getattr(light, role), getattr(light_plain, role), (skin.short_name, look, role))


class RegionTests(unittest.TestCase):
    LINES = [(Span("first row of text"),), (Span("a band", Style(bg="#334455")), Span("", Style(bg="#334455"))),
             (Span("> typed"),), (), (Span("   "),), (Span("  ", Style(bg="#334455")),)]

    def region(self, rows=12, cols=40):
        screen = VTScreen(rows, cols)
        return screen, LiveRegion(screen.feed, at_top=True)

    def test_cells_land_only_on_blank_cells(self) -> None:
        screen, region = self.region()
        region.render(self.LINES, (2, 7), 40, screen_rows=12, ambient=everywhere("", 40, 12, 0, False))
        lines = screen.lines()
        # A row with text gets its tail from TEXT_GAP cells past the text (owner's choice: the wallpaper stays in view
        # over a full session); a terminal that draws an ambiguous-width glyph wide cannot push it over the text.
        self.assertEqual(lines[0], "first row of text" + " " * TEXT_GAP + MARK * (40 - 17 - TEXT_GAP))
        self.assertNotIn(MARK, lines[1], "a band's background runs to the edge: no blank cell on it")
        self.assertEqual(lines[2], "> typed" + " " * TEXT_GAP + MARK * (40 - 7 - TEXT_GAP), "past the caret too")
        self.assertEqual(lines[3:5], [MARK * 40] * 2, "rows that are wholly blank, empty or spaces")
        self.assertEqual(lines[5], "  " + " " * TEXT_GAP + MARK * (40 - 2 - TEXT_GAP), "spaces on a band show the band")
        self.assertTrue(all(line == MARK * 40 for line in lines[6:]), "the rows under the region")
        self.assertEqual(screen.cursor, (2, 7))

    def test_a_row_that_gets_text_takes_its_cells_back_and_a_shrink_clears_them(self) -> None:
        # (A row painted again in two frames running, a spinner's, keeps nothing in its tail until it is still.)
        screen, region = self.region()
        ambient = everywhere("", 40, 12, 0, False)
        region.render(self.LINES, (2, 7), 40, screen_rows=12, ambient=ambient)
        self.assertEqual(screen.line(3), MARK * 40)
        written = [*self.LINES[:3], (Span("streamed"),), *self.LINES[4:]]
        region.render(written, (2, 7), 40, screen_rows=12, ambient=ambient)
        self.assertEqual(screen.line(3), "streamed")
        cleared = [*self.LINES[:3], (), *self.LINES[4:]]
        region.render(cleared, (2, 7), 40, screen_rows=12, ambient=ambient)
        self.assertEqual(screen.line(3), "", "painted again in two frames running (a spinner's row): left alone")
        region.render(cleared, (2, 7), 40, screen_rows=12, ambient=ambient)
        self.assertEqual(screen.line(3), MARK * 40, "still again: painted")
        region.render(self.LINES[:1], None, 40, screen_rows=12, ambient=())
        self.assertNotIn(MARK, "".join(screen.lines()))

    def test_only_the_cells_that_changed_are_written_again(self) -> None:
        written: list[str] = []
        screen = VTScreen(12, 40)
        region = LiveRegion(lambda text: (written.append(text), screen.feed(text)), at_top=True)
        cloth = Cell(9, 1, FULL, CLOTH, CLOTH)
        cells = (Cell(7, 3, "*", "#556677"), Cell(8, 9, ".", "#556677"), cloth)
        region.render(self.LINES, (2, 7), 40, screen_rows=12, ambient=cells)
        self.assertIn("48;2;122;31;61m", "".join(written), "a pixel's background is painted")
        self.assertTrue(clothed([screen._attrs[9]]))
        written.clear()
        region.paint_ambient(cells, 12)
        self.assertEqual(written, [])
        region.paint_ambient((Cell(7, 3, "+", "#556677"), Cell(8, 9, ".", "#556677"), cloth), 12)
        self.assertEqual(len(written), 1)
        self.assertNotIn("9;10H", written[0], "the unchanged cell is not written")
        self.assertEqual((screen.line(7)[3], screen.line(8)[9]), ("+", "."))
        self.assertEqual(screen.cursor, (2, 7))

    def test_cells_are_taken_off_before_a_flush_and_none_reach_the_scrollback(self) -> None:
        screen, region = self.region(rows=8)
        ambient = everywhere("", 40, 8, 0, False)
        for index in range(20):
            region.render([(Span(f"live {index}"),), (Span("> "),)], (1, 2), 40,
                          flush=[(Span(f"flushed {index}"),)], screen_rows=8, ambient=ambient)
        region.render([(Span("live 19"),), (), (Span("> "),)], (2, 2), 40, screen_rows=8, ambient=ambient)
        region.render([(Span("live 19"),), (), (Span("> "),)], (2, 2), 40, screen_rows=8, ambient=ambient)
        self.assertGreater(len(screen.scrollback), 0)
        self.assertFalse(any(MARK in line for line in screen.scrollback))
        self.assertIn(MARK, "".join(screen.lines()))
        self.assertFalse(any(MARK in line for line in screen.lines()[:5]), "never on a flushed row")


    def test_the_rows_flushed_above_are_painted_only_where_asked(self) -> None:
        for above in (False, True):
            with self.subTest(above=above):
                screen, region = self.region()
                ambient = everywhere("", 40, 12, 0, False)
                region.render([(Span("> "),)], (0, 2), 40, flush=[(Span("logo row"),), (Span("card row"),)],
                              screen_rows=12, ambient=ambient, ambient_above=above)
                # Two cells past the text first: a terminal that draws an ambiguous-width glyph wide would otherwise
                # push it over the row's last character.
                self.assertEqual(screen.line(0), "logo row" + ("  " + MARK * 30 if above else ""))
                self.assertEqual(screen.line(1), "card row" + ("  " + MARK * 30 if above else ""))
                region.render([(Span("> "),)], (0, 2), 40, screen_rows=12, ambient=ambient)
                self.assertEqual(screen.line(0), "logo row", "taken off once no longer asked")

    def test_ambiguous_width_text_drawn_wide_is_never_covered(self) -> None:
        # A terminal set to draw East Asian Ambiguous characters two cells wide (an iTerm2 and Terminal.app option)
        # pushes a row's text one cell right for each: the tail starts that much later, so no glyph covers the text,
        # on screen or, once the row scrolls, in the scrollback.
        with ambiguous_wide():
            for count in range(6):
                text = "reply " + "…" * count + " end"
                screen = VTScreen(6, 40)
                region = LiveRegion(screen.feed, at_top=True)
                region.render([(Span(text),), (Span("> "),)], (1, 2), 40, screen_rows=6,
                              ambient=everywhere("", 40, 6, 0, False), ambient_above=True)
                self.assertTrue(screen.line(0).startswith(text + " " * TEXT_GAP + MARK), (count, screen.line(0)))
            screen = VTScreen(8, 40)
            region = LiveRegion(screen.feed, at_top=True)
            ambient = everywhere("", 40, 8, 0, False)
            region.render([(Span("> "),)], (0, 2), 40, flush=[(Span("Greek: αβγδ → ok"),)], screen_rows=8,
                          ambient=ambient, ambient_above=True)
            for index in range(12):
                region.render([(Span("> "),)], (0, 2), 40, flush=[(Span(f"later {index}"),)], screen_rows=8,
                              ambient=ambient, ambient_above=True)
            self.assertEqual(screen.scrollback[0], "Greek: αβγδ → ok")

    def test_random_frames_never_cover_text_or_reach_the_scrollback(self) -> None:
        # Seeded random frames, flushes, inserted rows, ticks and starting places, with and without the glow's margin
        # and the rows above painted, of half-block pixels (`▀` over a background, a space on its colour, `▄`): every
        # cell the region does not hold is the plain run's, text and attributes (so blanking takes a background off
        # too), every cell it holds shows a pixel, and every row the screen scrolls off reaches the scrollback as the
        # plain run's did, text and attributes (after the review's fuzz).
        for seed in range(72):
            wide = seed >= 40  # the rest on a terminal that draws ambiguous characters (the half blocks) wide
            with ambiguous_wide() if wide else contextlib.nullcontext():
                self.random_frames(seed, wide)

    @staticmethod
    def pixel_cells(rnd: random.Random, rows: int, cols: int, wide: bool) -> tuple[Cell, ...]:
        """About seven cells in ten lit with pixels; on an ambiguous-wide screen only `▀` and `▄` (drawn two cells
        wide there) and never in the last column, where a two-cell glyph does not fit."""
        cells = []
        for row in range(rows):
            for col in range(cols - 1 if wide else cols):
                if rnd.random() < 0.7:
                    kind = rnd.random()
                    if wide:
                        cells.append(Cell(row, col, UPPER if kind < 0.5 else LOWER, "#445566", "#223344"))
                    elif kind < 0.4:
                        cells.append(Cell(row, col, UPPER, "#445566", "#223344"))
                    elif kind < 0.7:
                        cells.append(Cell(row, col, FULL, "#556677", "#556677"))
                    else:
                        cells.append(Cell(row, col, LOWER, "#667788"))
        return tuple(cells)

    def random_frames(self, seed: int, wide: bool) -> None:
        rnd = random.Random(seed)
        rows, cols = rnd.choice([(8, 30), (12, 40), (20, 60)])
        footer = rnd.random() < 0.5
        margin = int(footer)
        start = rnd.choice(["top", "row", "none"])
        place = {"at_top": True} if start == "top" else {"start_row": rnd.randrange(rows)} if start == "row" else {}
        painted, plain = Recording(rows, cols), Recording(rows, cols)
        if start != "top":
            shell = "shell\r\n" * rnd.randrange(rows) if start == "none" else f"\x1b[{place['start_row'] + 1};1H"
            for screen in (painted, plain):
                screen.feed(shell)
        regions = [LiveRegion(screen.feed, margin=margin, footer=footer, **place) for screen in (painted, plain)]
        width, screen_rows = cols - 2 * margin, rows - footer
        lines: list = []
        for step in range(50):
            ambient = self.pixel_cells(rnd, rows, cols, wide)
            if rnd.random() < 0.15:
                regions[0].paint_ambient(ambient, screen_rows)
            else:
                if rnd.random() < 0.4 or not lines:
                    letters = "x…αβ─→" if wide else "x"  # ambiguous ones count one cell here, two on that screen
                    longest = width // 2 if wide else width
                    lines = [(Span("".join(rnd.choice(letters) for _ in range(rnd.randrange(longest)))),)
                             if rnd.random() < 0.85 else
                             (Span("band", Style(bg="#334455")), Span("", Style(bg="#334455")))
                             for _ in range(rnd.randint(1, screen_rows - 1))]
                elif rnd.random() < 0.5 and len(lines) < screen_rows - 1:
                    at = rnd.randrange(len(lines) + 1)
                    lines = lines[:at] + [(Span(f"ins{step}"),)] + lines[at:]
                flush = [(Span(f"f{step}-{i}" + "y" * rnd.randrange(width // 2)),)
                         for i in range(rnd.choice([0, 0, 1, 2, 5]))]
                cursor = None if rnd.random() < 0.2 else (rnd.randrange(len(lines)), rnd.randrange(width))
                regions[0].render(lines, cursor, width, flush=flush, screen_rows=screen_rows, ambient=ambient,
                                  ambient_above=rnd.random() < 0.7)
                regions[1].render(lines, cursor, width, flush=flush, screen_rows=screen_rows)
            where = f"seed {seed} step {step}"
            held = set(regions[0]._paper)
            for row in range(rows):
                for col in range(cols):
                    seen, wanted = (painted._text[row][col], painted._attrs[row][col]), \
                        (plain._text[row][col], plain._attrs[row][col])
                    if wide:  # a two-cell glyph spills into the cell on its right: text cells must be untouched
                        if wanted[0] not in (" ", "", _vt_screen.CONTINUATION):
                            self.assertEqual(seen, wanted, (where, row, col))
                    elif (row, col) in held:
                        self.assertIn(seen[0], (UPPER, LOWER, FULL), (where, row, col))
                        self.assertTrue(seen[1], (where, row, col))
                    else:
                        self.assertEqual(seen, wanted, (where, row, col))
            if wide:
                self.assertEqual([line.replace(UPPER, "").replace(LOWER, "").rstrip() for line in painted.scrollback],
                                 [line.rstrip() for line in plain.scrollback], where)
            else:
                self.assertEqual(painted.scrollback, plain.scrollback, where)
                self.assertEqual(painted.scrolled_attrs, plain.scrolled_attrs, where)

    def test_clearing_the_region_takes_the_cells_above_it_off_too(self) -> None:
        # Exit from the launch screen (nothing to flush) and Ctrl+Z only clear the region: the cells beside the logo
        # above its top must go with it, or the shell's next lines scroll them into the scrollback.
        # The pixels are spaces on their colour, so taking them off must take the colour off too.
        screen = Recording(12, 40)
        region = LiveRegion(screen.feed, at_top=True)
        region.render([(Span("> "),)], (0, 2), 40, flush=[(Span("logo row"),), (Span("card row"),)],
                      screen_rows=12, ambient=everywhere_on_cloth("", 40, 12, 0, False), ambient_above=True)
        self.assertTrue(clothed([screen._attrs[0]]))
        region.clear()
        self.assertFalse(clothed(screen._attrs))
        screen.feed("\r\n".join(f"$ shell {index}" for index in range(20)))
        self.assertGreater(len(screen.scrolled_attrs), 0)
        self.assertFalse(clothed(screen.scrolled_attrs))


class AppWallpaperTests(unittest.TestCase):
    def app(self, environ=WALLPAPER_ON, answered: str | None = ANSWERED, rows=20, cols=60):
        clock = Clock(1000.0)
        app, _client = make_app(rows=rows, cols=cols, clock=clock, environ=environ)
        app.adopt_background(answered)
        app.region = app._new_region(at_top=True)
        return app, clock

    def busy(self, app, clock, flushes: int = 12) -> None:
        def event(kind, **payload):
            app.transcript.apply(Event(type=kind, session_id=app.sid, payload=dict(payload)))

        app.transcript.add_user("run the tests")
        app.turn_pending = True
        for index in range(flushes):  # finished replies, flushed above the region, enough to scroll the screen
            event("message.start")
            event("tool.start", tool_id=f"t{index}", name="read_file", context=f"src/file_{index}.py")
            event("tool.complete", tool_id=f"t{index}", name="read_file", result={"ok": True}, duration_s=0.1)
            event("message.complete", text=f"step {index} read")
            clock.at += 0.3
            app._render()
            app._render_when_due()

    def writes(self, app) -> str:
        return "".join(app.terminal.writes)

    def test_the_first_frame_sets_the_looks_ground_and_the_theme_is_measured_against_it(self) -> None:
        app, _clock = self.app()
        app.launch_look = "moonlit"
        app.theme = app._themed()
        ground = look_ground("moonlit", False)
        self.assertEqual(app._surface(), ground)
        self.assertEqual(app.theme.glow_surface.bg, ground)
        app._render()
        self.assertEqual(self.writes(app).count(background_set(ground)), 1)
        app._render()
        self.assertEqual(self.writes(app).count(background_set(ground)), 1, "set once, not every frame")

    def test_a_light_terminal_gets_the_looks_light_ground(self) -> None:
        app, _clock = self.app(answered="#FAFAFA")
        app.launch_look = "moonlit"
        app._render()
        self.assertIn(background_set(look_ground("moonlit", True)), self.writes(app))

    def test_a_look_change_and_the_pickers_preview_set_the_new_ground(self) -> None:
        app, _clock = self.app()
        app._render()
        app._keep_launch_look("moonlit")
        app._render()
        self.assertIn(background_set(look_ground("moonlit", False)), self.writes(app))
        app._theme("")
        app._on_input(Key(DOWN))  # moonlit to aurora, previewed
        app._render()
        self.assertIn(background_set(look_ground("aurora", False)), self.writes(app))
        swatches = app._launch_swatches()
        for look in LAUNCH_PRESETS:
            # Each tile is the ground picking it gives (`_ground`): the default look keeps the terminal's own.
            ground = look_ground(look, False) if look in SCENES else ANSWERED
            self.assertEqual({style.bg for style in swatches[look]}, {ground}, look)

    def test_exit_puts_the_terminals_background_back(self) -> None:
        app, _clock = self.app()
        app._render()
        app._shutdown()
        written = self.writes(app)
        self.assertGreater(written.find(background_restore(ANSWERED)), written.find(
            background_set(look_ground("spectrum", False))), "set first, put back on the way out")
        self.assertEqual(background_restore(ANSWERED), background_set(ANSWERED),
                         "the colour the terminal reported, not OSC 111, which would drop a background set at runtime")
        self.assertNotIn("\x1b]111", written)
        self.assertIsNone(app.ground_set)

    def test_a_crash_in_the_loop_puts_the_background_back_on_the_way_out(self) -> None:
        app, _clock = self.app()
        app._render()
        with mock.patch.object(app, "_step", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
            app.run()
        self.assertIn(background_restore(ANSWERED), self.writes(app))

    def test_a_stop_puts_it_back_and_the_first_frame_after_sets_it_again(self) -> None:
        app, _clock = self.app()
        app.launch_look = "moonlit"
        app._render()
        stopped_at: list[int] = []
        original = app.terminal.suspend

        def suspend() -> bool:
            stopped_at.append(len(self.writes(app)))
            return original()

        app.terminal.suspend = suspend  # type: ignore[method-assign]
        with mock.patch.object(app_module.signal, "SIGTSTP", 20, create=True):
            app._suspend()
        before_stop = self.writes(app)[: stopped_at[0]]
        self.assertIn(background_restore(ANSWERED), before_stop)
        app._render()
        ground = background_set(look_ground("moonlit", False))
        self.assertGreater(self.writes(app).rfind(ground), self.writes(app).rfind(background_restore(ANSWERED)))

    def test_nothing_is_set_where_it_cannot_be_put_back_or_is_not_wanted(self) -> None:
        cases = {
            "no answer": (WALLPAPER_ON, None),
            "256 colours": ({"TERM": "xterm-256color", "OMH_TUI_WALLPAPER": "1"}, ANSWERED),
            "NO_COLOR": ({**WALLPAPER_ON, "NO_COLOR": "1"}, ANSWERED),
            "held off": ({**WALLPAPER_ON, "OMH_TUI_WALLPAPER": "0"}, ANSWERED),
        }
        for name, (environ, answered) in cases.items():
            with self.subTest(case=name):
                app, clock = self.app(environ, answered)
                self.busy(app, clock, flushes=2)
                app._shutdown()
                self.assertNotIn("\x1b]11;#", self.writes(app))
                self.assertNotIn("\x1b]111", self.writes(app))
                self.assertIsNone(app._ambient())
        home = Path(tempfile.mkdtemp(prefix="omh-wallpaper-test-")) / ".omh"
        write_wallpaper_choice(home, False)
        app, _clock = self.app({**WALLPAPER_ON, "OMH_HOME": str(home)})
        app._render()
        self.assertNotIn("\x1b]11;#", self.writes(app))

    def test_a_turn_paints_the_blank_cells_and_nothing_of_it_reaches_the_scrollback(self) -> None:
        for glow in ("0", "1"):  # with the working glow's frame too, which it never paints over
            with self.subTest(glow=glow), mock.patch.object(app_module, "scene", everywhere):
                app, clock = self.app({**WALLPAPER_ON, "OMH_TUI_GLOW": glow})
                self.busy(app, clock)
                screen = app.terminal.screen
                self.assertGreater(len(screen.scrollback), 0, "the turn's output scrolled")
                self.assertFalse(any(MARK in line for line in screen.scrollback))
                self.assertIn(MARK, "".join(screen.lines()))
                for _ in range(30):
                    clock.at += 0.05
                    app._render_when_due()
                    self.assertFalse(any(MARK in line for line in screen.scrollback))
                top = app.region.top_row(app.size[1])
                self.assertIsNotNone(top)
                for row in range(top):  # the transcript's rows above the region: glyphs only past their text
                    text = screen.line(row).split(MARK)[0]
                    if MARK in screen.line(row) and text.strip():
                        self.assertTrue(text.endswith(" " * TEXT_GAP), f"row {row}: {screen.line(row)!r}")
                self.assertTrue(any(MARK in screen.line(row) for row in range(top)), "the tails above are painted")
                if glow == "1":
                    edges = [screen.line(row).ljust(60)[col] for row in range(20) for col in (0, 59)]
                    self.assertNotIn(MARK, edges, "the glow's columns stay its own")
                    self.assertNotIn(MARK, screen.line(19))

    def test_a_session_reads_as_it_would_without_the_wallpaper_and_every_painted_cell_is_tracked(self) -> None:
        # The same session driven twice, with a scene that lights every cell and with the wallpaper off: with the
        # wallpaper's glyph taken out, the screen and the scrollback must be the same after every frame (no cell
        # painted over text, none scrolled away), and every glyph on screen must be one the region knows it painted
        # (none left behind where a scroll, a flush or an inserted row moved the screen under it).
        for glow in ("0", "1"):
            with self.subTest(glow=glow), mock.patch.object(app_module, "scene", everywhere):
                runs = [self.app({**WALLPAPER_ON, "OMH_TUI_GLOW": glow, "OMH_TUI_WALLPAPER": on}) for on in "10"]
                for step in range(40):
                    for app, clock in runs:
                        self.step(app, clock, step)
                    painted, plain = (app.terminal.screen for app, _clock in runs)
                    self.assertEqual([line.replace(MARK, " ").rstrip() for line in painted.lines()], plain.lines(),
                                     f"step {step}")
                    self.assertEqual(painted.scrollback, plain.scrollback, f"step {step}")
                    marks = {(row, col) for row in range(20) for col, char in enumerate(painted.line(row))
                             if char == MARK}
                    self.assertEqual(marks, set(runs[0][0].region._paper), f"step {step}")
                self.assertGreater(len(runs[0][0].terminal.screen.scrollback), 0, "the session scrolled")

    def step(self, app, clock, step: int) -> None:
        """One step of a session that grows from a short one (rows inserted under it), streams, flushes, scrolls and
        ends turns."""
        def event(kind, **payload):
            app.transcript.apply(Event(type=kind, session_id=app.sid, payload=dict(payload)))

        if step % 13 == 0:
            app.transcript.add_user(f"question {step}")
            app.turn_pending = True
            event("message.start")
        elif step % 13 == 12:
            event("message.complete", text=f"answer {step}")
            app.turn_pending = False
        elif step % 3 == 0:
            event("tool.start", tool_id=f"t{step}", name="read_file", context=f"src/file_{step}.py")
            event("tool.complete", tool_id=f"t{step}", name="read_file", result={"ok": True}, duration_s=0.1)
        else:
            event("message.delta", text=f"streamed words {step}\n")
        clock.at += 0.2
        app.dirty = True
        app._render_when_due()

    def test_the_idle_session_ticks_only_the_wallpapers_cells(self) -> None:
        def moving(look, cols, rows, seconds, light):  # one glyph walking along the screen's last blank row
            return (Cell(rows - 6, int(seconds * 4) % cols, MARK, "#445566"),)

        with mock.patch.object(app_module, "scene", moving):
            app, clock = self.app(rows=42, cols=150)
            app.launch_look = "moonlit"
            app.dirty = True
            app._render_when_due()
            self.assertAlmostEqual(app._read_timeout(), app_module.WALLPAPER_TICK_SECONDS)
            seen = set()
            with mock.patch.object(app, "_render", wraps=app._render) as render:
                for _ in range(20):
                    clock.at += app_module.WALLPAPER_TICK_SECONDS
                    app._render_when_due()
                    seen.add(app.terminal.screen.line(36).find(MARK))
                render.assert_not_called()
            self.assertGreaterEqual(len(seen - {-1}), 15, "each tick moved the glyph on screen")
            self.assertEqual(app.terminal.screen.line(36).count(MARK), 1, "and took it off where it was")

    def test_the_default_look_keeps_the_terminals_background_and_an_idle_screen_never_wakes_for_it(self) -> None:
        # Owner, 2026-10-30: the default look's own ground showed through Otty as holes of the terminal's black, Otty
        # taking a set background only on the cells written after it. The default look's ground is the terminal's own.
        app, clock = self.app(rows=42, cols=150)
        self.assertEqual(app.launch_look, DEFAULT_LAUNCH)
        self.assertEqual(app._ground(), ANSWERED)
        app._render()
        self.assertNotIn(background_set(look_ground(DEFAULT_LAUNCH, False)), self.writes(app))
        self.assertEqual(app._ambient(), ())
        self.assertFalse(app._wallpaper_moves())
        self.assertNotAlmostEqual(app._read_timeout() or 0.0, app_module.WALLPAPER_TICK_SECONDS)
        app.launch_look = "moonlit"
        self.assertTrue(app._wallpaper_moves(), "a look with a scene ticks")

    def test_no_tick_while_the_composer_holds_text(self) -> None:
        def moving(look, cols, rows, seconds, light):
            return (Cell(rows - 6, int(seconds * 4) % cols, MARK, "#445566"),)

        with mock.patch.object(app_module, "scene", moving):
            app, clock = self.app(rows=42, cols=150)
            app.launch_look = "moonlit"  # a look that ticks, so only the draft holds it
            type_text(app, "a draft")
            app.dirty = True
            app._render_when_due()
            before = len(app.terminal.writes)
            self.assertFalse(app._wallpaper_moves())
            for _ in range(10):
                clock.at += app_module.WALLPAPER_TICK_SECONDS
                app._render_when_due()
            self.assertEqual(len(app.terminal.writes), before, "no tick moves the cursor away from an IME's pre-edit")

    def test_the_launch_screen_and_the_transcript_are_painted_past_their_text(self) -> None:
        from test_tui_app import FakePoller, ScriptedTerminal
        from test_tui_launch_card import SKILLS, StartClient
        from test_tui_modes import SID

        clock = Clock(1000.0)
        client = StartClient()
        client.skills = SKILLS
        app = app_module.App(ScriptedTerminal(42, 150), client, {**WALLPAPER_ON, "OMH_TUI_GLOW": "0"},  # type: ignore
                             poller=FakePoller(), clock=clock)
        with mock.patch.object(app_module, "scene", everywhere):
            app.startup()
            app.adopt_background(ANSWERED, {})
            app.clear_launch_screen(1)
            app._on_event(Event("session.info", SID, {"model": "openai/gpt-6.1-sol", "skills": SKILLS}))
            app._render()
            screen = app.terminal.screen
            banner = next(row for row in range(42) if "OH-MY-HERMES v" in screen.line(row))
            self.assertLess(banner, app.region.top_row(app.size[1]), "the banner is flushed above the region")
            self.assertIn(MARK, screen.line(banner), "the launch screen's empty area beside the banner")
            # The logo's rows are block and box-drawing characters, East Asian Ambiguous all: counted as wide as a
            # terminal may draw them, they reach past the screen's edge and keep no tail.
            logo = next(row for row in range(42) if "██" in screen.line(row))
            self.assertNotIn(MARK, screen.line(logo))
            app._submit_prompt("first question")
            app.transcript.apply(Event("message.start", SID, {}))
            app.transcript.apply(Event("message.complete", SID, {"text": "an answer someone may copy"}))
            app._render()
            top = app.region.top_row(app.size[1])
            answer = next(row for row in range(top) if "an answer someone may copy" in screen.line(row))
            # The rail's `┃` is East Asian Ambiguous: counted as wide as a terminal may draw it, one cell more.
            self.assertIn("an answer someone may copy" + " " * (TEXT_GAP + 1) + MARK, screen.line(answer),
                          "the transcript's tail, past the gap (owner's choice; /wallpaper off keeps it clean)")

    def test_theme_light_or_dark_against_the_terminal_holds_the_ground_off(self) -> None:
        # The terminal's own foreground is picked for its own background; a ground of the other lightness would leave
        # body text at 1.7:1 or less. Every pairing the app can choose keeps 7:1 for a typical foreground.
        foregrounds = {False: ("#C0C0C0", "#FFFFFF"), True: ("#333333", "#000000")}
        for answered in ("#1E1E1E", "#FAFAFA"):
            for mode in ("auto", "light", "dark"):
                with self.subTest(answered=answered, mode=mode):
                    app, _clock = self.app(answered=answered)
                    app.launch_look = "moonlit"
                    app._render()
                    before = len(app.terminal.writes)
                    app._theme(mode)
                    app._render()
                    ground, light = app._ground(), is_light(answered)
                    if mode != "auto" and (mode == "light") != light:
                        self.assertIsNone(ground)
                        self.assertIn(background_restore(answered), "".join(app.terminal.writes[before:]))
                        self.assertIsNone(app.ground_set)
                    else:
                        self.assertEqual(ground, look_ground("moonlit", light))
                        for fg in foregrounds[light]:
                            self.assertGreaterEqual(contrast_ratio(fg, ground), 7.0)

    def test_a_look_change_past_the_launch_prints_the_session_again_on_the_new_ground_once(self) -> None:
        # Browsing the picker only moves the ground (OSC 11) and the preview: no erase of the scrollback, no reprint
        # per arrow key. Enter on another look prints the session again once, on its ground; Esc back to the look in
        # use prints nothing again.
        clear = "\x1b[3J"
        app, clock = self.app()
        self.busy(app, clock, flushes=4)
        app.turn_pending = False
        app._render()
        app._theme("")
        app._render()
        before = len(app.terminal.writes)
        for _ in range(3):
            app._on_input(Key(DOWN))
            app._render()
        browsing = "".join(app.terminal.writes[before:])
        self.assertNotIn(clear, browsing, "a move erases nothing")
        self.assertIn(background_set(app._ground()), browsing, "a move sets the highlighted look's ground")
        app._on_input(Key(ENTER))
        app._render()
        kept = "".join(app.terminal.writes[before:])
        self.assertEqual(kept.count(clear), 1, "Enter on another look prints the session again, once")
        self.assertEqual(app.rows_ground, app._ground())
        app._theme("")
        app._render()
        before = len(app.terminal.writes)
        for key in (Key(DOWN), Key(ESCAPE)):
            app._on_input(key)
            app._render()
        self.assertNotIn(clear, "".join(app.terminal.writes[before:]), "Esc puts the ground back: nothing to reprint")

    def test_on_the_ground_every_role_also_reads_on_the_terminals_own_background(self) -> None:
        # The rows printed on the ground stay in the terminal after exit, on the background it reported.
        owns = {False: ("#000000", "#1E1E1E", "#282C34", "#002B36"), True: ("#FFFFFF", "#FDF6E3", "#EEEEEE")}
        short = []
        for light, backgrounds in owns.items():
            for own in backgrounds:
                for look in LAUNCH_PRESETS:
                    app, _clock = self.app(answered=own)
                    app.launch_look = look
                    theme, ground = app._themed(), app._ground()
                    for surface in (ground, own):
                        inks = [(role, getattr(theme, role), TEXT_CONTRAST) for role in (*TEXT_ROLES, *WORD_ROLES)]
                        inks += [(role, getattr(theme, role), EDGE_CONTRAST) for role in GLYPH_ROLES]
                        inks += [(role, style, TEXT_CONTRAST) for role in WORD_STEPS for style in getattr(theme, role)]
                        inks += [(role, style, EDGE_CONTRAST) for role in MARK_STEPS for style in getattr(theme, role)]
                        short += [(own, look, surface, role, round(contrast_ratio(style.fg, surface), 2))
                                  for role, style, floor in inks
                                  if style.fg and style.bg is None and contrast_ratio(style.fg, surface) < floor]
        self.assertEqual(short[:8], [], f"{len(short)} inks under their floor")

    def test_exit_and_a_stop_from_the_launch_screen_leave_no_glyph(self) -> None:
        # Pixels that are spaces on their colour: what is left must carry neither a glyph nor the colour.
        for way in ("exit", "stop"):
            with self.subTest(way=way), mock.patch.object(app_module, "scene", everywhere_on_cloth):
                app = self.launch()
                screen = app.terminal.screen
                self.assertTrue(clothed(screen._attrs))
                if way == "exit":
                    app._shutdown()
                else:
                    with mock.patch.object(app_module.signal, "SIGTSTP", 20, create=True):
                        app._suspend()
                self.assertFalse(clothed(screen._attrs), "nothing left to scroll into the shell's scrollback")

    def launch(self):
        from test_tui_app import FakePoller, ScriptedTerminal
        from test_tui_launch_card import SKILLS, StartClient
        from test_tui_modes import SID

        client = StartClient()
        client.skills = SKILLS
        app = app_module.App(ScriptedTerminal(42, 150), client, {**WALLPAPER_ON, "OMH_TUI_GLOW": "0"},  # type: ignore
                             poller=FakePoller(), clock=Clock(1000.0))
        app.startup()
        app.adopt_background(ANSWERED, {})
        app.clear_launch_screen(1)
        app._on_event(Event("session.info", SID, {"model": "openai/gpt-6.1-sol", "skills": SKILLS}))
        app._render()
        return app

    def test_reduced_motion_keeps_the_ground_and_a_still_scene(self) -> None:
        app, clock = self.app({**WALLPAPER_ON, "OMH_TUI_REDUCED_MOTION": "1"})
        app.launch_look = "moonlit"
        first = app._ambient()
        clock.at += 7
        self.assertEqual(app._ambient(), first)
        self.assertFalse(app._wallpaper_moves())
        app._render()
        self.assertIn(background_set(look_ground("moonlit", False)), self.writes(app))

    def test_wallpaper_off_puts_the_background_back_at_once_and_clears_the_cells(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="omh-wallpaper-test-")) / ".omh"
        with mock.patch.object(app_module, "scene", everywhere):
            app, clock = self.app({**WALLPAPER_ON, "OMH_HOME": str(home)})
            app.launch_look = "moonlit"
            self.busy(app, clock, flushes=2)
            self.assertIn(MARK, "".join(app.terminal.screen.lines()))
            for char in "/wallpaper off":
                app._on_input(Key(CHAR, char))
            app._on_input(Key(ENTER))
            self.assertIn(background_restore(ANSWERED), self.writes(app), "before the next frame")
            app._render()
            self.assertNotIn(MARK, "".join(app.terminal.screen.lines()))
        self.assertIs(read_wallpaper_choice(home), False)
        self.assertIn(f"Living wallpaper off, kept in {theme_store_path(home)}.", notices(app))
        self.assertEqual(app._surface(), ANSWERED, "the theme is measured against the terminal's own again")
        app._wallpaper_command("")  # alone, it switches
        self.assertIs(read_wallpaper_choice(home), True)
        app._render()
        self.assertGreater(self.writes(app).rfind(background_set(look_ground("moonlit", False))),
                           self.writes(app).rfind(background_restore(ANSWERED)))

    def test_theme_light_on_a_dark_terminal_says_it_holds_the_wallpaper_off(self) -> None:
        app, _clock = self.app()
        app._theme("light")
        self.assertTrue(any("Living wallpaper held off: /theme light" in notice and "/theme auto" in notice
                            for notice in notices(app)), notices(app))
        app._wallpaper_command("on")
        said = notices(app)[-1]
        self.assertIn("/theme auto", said, "the reason it does not show, not the truecolor one")
        self.assertNotIn("truecolor", said)

    def test_wallpaper_on_says_what_still_holds_it_off(self) -> None:
        app, _clock = self.app({**WALLPAPER_ON, "OMH_TUI_WALLPAPER": "0"})
        app._wallpaper_command("on")
        self.assertTrue(any("OMH_TUI_WALLPAPER=0" in notice for notice in notices(app)))
        app, _clock = self.app(answered=None)
        app._wallpaper_command("on")
        self.assertTrue(any("reported its background" in notice for notice in notices(app)))
        app._wallpaper_command("maybe")
        self.assertTrue(any("/wallpaper on" in notice for notice in notices(app)))


class WallpaperStoreTests(unittest.TestCase):
    def test_the_wallpaper_is_kept_beside_the_other_keys_and_no_write_drops_another(self) -> None:
        home = Path(tempfile.mkdtemp()) / ".omh"
        self.assertIsNone(read_wallpaper_choice(home))
        write_wallpaper_choice(home, False)
        write_theme_choice(home, default_theme())
        write_launch_choice(home, "moonlit")
        write_glow_choice(home, False)
        self.assertIs(read_wallpaper_choice(home), False)
        write_wallpaper_choice(home, True)
        record = json.loads(theme_store_path(home).read_text(encoding="utf-8"))
        self.assertEqual(record, {"schema_version": THEME_STORE_SCHEMA, "theme": default_theme().short_name,
                                  "launch": "moonlit", "glow": "off", "wallpaper": "on"})


class GlowWithWallpaperTests(glow_tests.AppGlowTests):
    """The working glow's own tests, its scrollback ones included, with the living wallpaper on as well."""

    def app(self, environ=glow_tests.GLOW_ON, rows=20, cols=60):
        # The glow suite's screen is under the scenes' 80x24, so a scene that lights every cell stands in for them.
        self.enterContext(mock.patch.object(app_module, "scene", everywhere))
        app, clock = super().app({**environ, "OMH_TUI_WALLPAPER": "1"}, rows, cols)
        app.adopt_background(glow_tests.BACKGROUND)
        if app.color_depth == TRUECOLOR:
            self.assertIsNotNone(app._ground(), "the wallpaper shows")
        return app, clock

    def test_the_wallpaper_paints_beside_the_glow(self) -> None:
        app, clock = self.app()
        self.busy(app, clock, flushes=1)  # a short session: blank rows under it
        screen = app.terminal.screen
        self.assertIn(MARK, "".join(screen.lines()))
        self.assertTrue(app.region._paper)
        self.assertFalse(any(MARK in line for line in screen.scrollback))

    def test_the_real_art_and_the_glow_keep_their_own_cells(self) -> None:
        # The glow's tests above stand a mark in for the scenes; here a real scene's half blocks, which are glyphs the
        # glow draws as well, so the checks go by place: the art never takes the glow's edge, the glow lights the
        # edge, and no half block of either reaches the scrollback.
        rows, cols = 42, 150
        app, clock = glow_tests.AppGlowTests.app(self, {**glow_tests.GLOW_ON, "OMH_TUI_WALLPAPER": "1"}, rows, cols)
        app.adopt_background(glow_tests.BACKGROUND)
        app.launch_look = "moonlit"
        self.busy(app, clock, flushes=40)
        screen = app.terminal.screen
        edge = {(row, col) for row in range(rows) for col in range(cols)
                if row in (0, rows - 1) or col in (0, cols - 1)}
        lit_edge = art = False
        for _ in range(int(glow_tests.LOOP_SECONDS / glow_tests.TICK_SECONDS)):  # the glow once round
            clock.at += glow_tests.TICK_SECONDS
            app._render()
            self.assertFalse(set(app.region._paper) & edge, "the art keeps off the glow's edge")
            lit_edge = lit_edge or any(screen._text[row][col] in glow_tests.GLYPHS for row, col in edge)
            art = art or any(screen._text[row][col] in (UPPER, LOWER) for row, col in app.region._paper)
            self.assertFalse(any({UPPER, LOWER} & set(line) for line in screen.scrollback))
        self.assertGreater(len(screen.scrollback), 0, "the turn's output scrolled")
        self.assertTrue(lit_edge and art, (lit_edge, art))


if __name__ == "__main__":
    unittest.main()
