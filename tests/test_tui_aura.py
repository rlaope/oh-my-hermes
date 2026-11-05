"""The aura a `dag-ulw` in the composer draws (owner request 2026-10-23, after Claude Code's `ultrathink`).

The token moves through a purple gradient a step a tick and the composer's rules take the same gradient, only while
the draft holds it, at the truecolor depth with motion on; the rows, the caret and the cells stay the draft's own.
"""

from __future__ import annotations

from dataclasses import replace
import unittest

from _local_package import load_local_package

load_local_package()

from omh.tui.app import IDLE_READ_SECONDS, TICK_SECONDS  # noqa: E402
from omh.tui.aura import AURA_RULE, RULE_GLINT_CELLS, aura_ranges  # noqa: E402
from omh.tui.composer import Composer  # noqa: E402
from omh.tui.frame import RULE, build_frame  # noqa: E402
from omh.tui.keys import BACKSPACE, ENTER, Key, Paste  # noqa: E402
from omh.tui.style import COLOR_16, COLOR_256, NO_COLOR, TRUECOLOR, Span  # noqa: E402
from omh.tui.theme import DEFAULT_THEME, without_colour  # noqa: E402
from omh.tui.width import line_width  # noqa: E402
from test_tui_modes import make_app, type_text  # noqa: E402

KNOWN = frozenset({"dag-ulw", "plan"})


def composer_with(text: str) -> Composer:
    composer = Composer()
    composer.replace(0, 0, text)
    return composer


def frame_for(text: str, *, aura: int = 0, depth: str = TRUECOLOR, theme=DEFAULT_THEME, cols: int = 80):
    return build_frame(cols=cols, rows=24, composer=composer_with(text), info=(), theme=theme, known_slash=KNOWN,
                       aura=aura, aura_depth=depth)


def rows_of(frame) -> tuple[tuple[Span, ...], tuple[Span, ...], tuple[Span, ...]]:
    """The top rule, the composer's first row and the bottom rule."""
    lines = list(frame.lines)
    top = next(index for index, line in enumerate(lines) if line and line[0].text.startswith((RULE, AURA_RULE)))
    return lines[top], lines[top + 1], lines[top + 2]


def styles_over(line: tuple[Span, ...], text: str, word: str) -> list:
    """The style of each character of `word`'s first occurrence on `line` (whose text is `text`)."""
    at = text.index(word)
    styles, cell = [], 0
    for span in line:
        for char in span.text:
            if at <= cell < at + len(word):
                styles.append(span.style)
            cell += 1
    return styles


def text_of(line: tuple[Span, ...]) -> str:
    return "".join(span.text for span in line)


class KeywordTests(unittest.TestCase):
    def test_the_token_whole_in_any_case_and_nothing_that_goes_on_from_it(self) -> None:
        for text, found in (("dag-ulw", ["dag-ulw"]), ("/dag-ulw migrate every service", ["/dag-ulw"]),
                            ("run DAG ULW now", ["DAG ULW"]), ("(dag-ulw), then Dag-Ulw.", ["dag-ulw", "Dag-Ulw"])):
            with self.subTest(text=text):
                self.assertEqual([text[start:end] for start, end in aura_ranges(text)], found)
        for text in ("dag-ulwx", "undag ulw", "src/dag-ulw/plan.md", "a/dag-ulw", "dag_ulw", "dagulw", "dag-ulw-plan",
                     "my-dag-ulw"):
            with self.subTest(text=text):
                self.assertEqual(aura_ranges(text), [])

    def test_a_korean_particle_after_it_keeps_it_whole_as_the_router_reads_it(self) -> None:
        # The review of 254c15335: `\w` counts Hangul, so `dag-ulw로` turned the aura off while the router dispatched.
        from omh.routing.chat import route_chat_message

        for text, token in (("dag-ulw로 돌려줘", "dag-ulw"), ("dag ulw로 해줘", "dag ulw"), ("/dag-ulw로", "/dag-ulw"),
                            ("dag-ulw를 써서 정리해줘", "dag-ulw"), ("dag-ulw가 끝나면 알려줘", "dag-ulw"),
                            ("dag-ulw는 언제 쓰나", "dag-ulw"), ("dag-ulw에서 돌려줘", "dag-ulw"),
                            ("/dag-ulw를 실행해줘", "/dag-ulw")):
            with self.subTest(text=text):
                self.assertEqual([text[start:end] for start, end in aura_ranges(text)], [token])
        for text in ("dag-ulw로 돌려줘", "dag ulw로 해줘", "/dag-ulw로", "/dag-ulw를 실행해줘"):
            with self.subTest(route=text):
                route = route_chat_message(text, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "dag-ulw"))


class DrawTests(unittest.TestCase):
    def test_the_token_runs_through_the_hues_in_every_frame_over_its_slash_colour(self) -> None:
        theme = DEFAULT_THEME
        for phase in range(12):
            with self.subTest(phase=phase):
                _top, row, _bottom = rows_of(frame_for("please /dag-ulw migrate then /plan", aura=phase))
                text = text_of(row)
                lit = styles_over(row, text, "/dag-ulw")
                self.assertTrue(all(style.bold for style in lit))
                hues = {style.fg for style in lit}
                self.assertGreaterEqual(len(hues), 6, "violet to lavender across the eight cells, every frame")
                self.assertEqual(lit[0].fg in {theme.aura[0].fg, theme.aura_glint[0].fg}, True)
                self.assertEqual(lit[-1].fg in {theme.aura[-1].fg, theme.aura_glint[-1].fg}, True)
                self.assertEqual(styles_over(row, text, "/plan"), [theme.slash] * 5, "another /name keeps its colour")

    def test_a_brighter_band_sweeps_through_the_letters(self) -> None:
        glint = set(DEFAULT_THEME.aura_glint)
        lit_cells = []
        for phase in range(12):
            _top, row, _bottom = rows_of(frame_for("dag-ulw", aura=phase))
            lit = styles_over(row, text_of(row), "dag-ulw")
            lit_cells.append(tuple(at for at, style in enumerate(lit) if style in glint))
        self.assertEqual(lit_cells[:4], [(), (0,), (0, 1), (1, 2)], "it enters from the left, a cell a phase")
        self.assertEqual(lit_cells[7:10], [(5, 6), (6,), ()], "and leaves at the right")
        self.assertEqual(lit_cells[11], lit_cells[0], "and comes round again")

    def test_both_rules_are_heavy_in_the_gradient_with_a_travelling_band_and_go_back_after(self) -> None:
        self.assertEqual((RULE, AURA_RULE), ("─", "━"))
        plain_top, _row, plain_bottom = rows_of(frame_for("migrate every service", cols=83))
        self.assertEqual({text_of(plain_top), text_of(plain_bottom)}, {RULE * 83})
        bands = []
        for phase in (0, 5):
            top, _row, bottom = rows_of(frame_for("dag ulw migrate every service", cols=83, aura=phase))
            self.assertEqual(top, bottom, "both rules, the same glow")
            self.assertEqual(text_of(top), AURA_RULE * 83, "heavy, full width, in the same cells")
            self.assertGreaterEqual(len({span.style.fg for span in top}), 8, "a gradient across the width")
            cells = [span.style for span in top for _char in span.text]
            # The rule is a gutter (never copied by a drag); its glint is the theme's glint.
            bands.append([at for at, style in enumerate(cells)
                          if replace(style, gutter=False) in set(DEFAULT_THEME.aura_glint)])
        self.assertEqual(len(bands[1]), RULE_GLINT_CELLS)
        self.assertNotEqual(bands[0], bands[1], "the band travels along it")
        self.assertEqual(len(frame_for("dag ulw migrate").lines), len(frame_for("migrate").lines), "no row added")

    def test_256_and_16_colours_paint_it_at_their_depth_and_no_colour_leaves_it_bold(self) -> None:
        for depth, code in ((COLOR_256, "38;5;"), (COLOR_16, "")):
            with self.subTest(depth=depth):
                top, row, _bottom = rows_of(frame_for("dag-ulw", depth=depth))
                lit = styles_over(row, text_of(row), "dag-ulw")
                self.assertEqual({style.depth for style in lit} | {span.style.depth for span in top}, {depth})
                self.assertIn(code, lit[0].sgr())
                self.assertNotIn("38;2;", lit[0].sgr())
        plain = without_colour(DEFAULT_THEME)
        top, row, bottom = rows_of(frame_for("dag-ulw", theme=plain, depth=NO_COLOR))
        lit = styles_over(row, text_of(row), "dag-ulw")
        self.assertTrue(all(style.bold for style in (*lit, *(span.style for span in (*top, *bottom)))))
        self.assertTrue(all("38;" not in style.sgr() for style in lit), "no colour")
        self.assertTrue(all("38;" not in span.style.sgr() for span in (*top, *bottom)))
        self.assertEqual(text_of(top), AURA_RULE * 80)

    def test_it_reads_on_a_dark_and_a_light_background(self) -> None:
        from omh.tui.theme import build_theme, contrast_ratio, default_theme, surface_for

        for background in ("#0D1117", "#FFFFFF", "#3A3A3A", "#DDDDDD", "#5A5A5A", "#A8A8A8", "#C0C0C0"):
            with self.subTest(background=background):
                theme = build_theme(default_theme(), background)
                surface = surface_for(default_theme(), background)
                styles = (*theme.aura, *theme.aura_glint)
                self.assertGreaterEqual(min(contrast_ratio(style.fg, surface) for style in styles), 4.5)
                self.assertEqual(len(theme.aura), len(theme.aura_glint))

    def test_where_its_band_would_not_show_it_is_the_still_bold_look(self) -> None:
        # The review of 254c15335: on #808080 the lift pulled the steps and the band to one ink (1.01:1).
        from omh.tui.theme import AURA_GLINT_MIN_CONTRAST, aura_moves, build_theme, contrast_ratio, default_theme

        self.assertEqual(AURA_GLINT_MIN_CONTRAST, 1.15)
        for background, moves in (("#808080", False), ("#C0C0C0", True), ("#3A3A3A", True), ("#0D1117", True),
                                  ("#FFFFFF", True)):
            with self.subTest(background=background):
                theme = build_theme(default_theme(), background)
                self.assertEqual(aura_moves(theme), moves)
                top, row, bottom = rows_of(frame_for("dag-ulw go", theme=theme, aura=5))
                lit = styles_over(row, text_of(row), "dag-ulw")
                self.assertEqual(text_of(top), AURA_RULE * 80)
                if moves:
                    self.assertGreaterEqual(min(contrast_ratio(a.fg, b.fg) for a, b in zip(theme.aura, theme.aura_glint)),
                                            AURA_GLINT_MIN_CONTRAST)
                    self.assertGreater(len({style.fg for style in lit}), 4)
                else:
                    self.assertEqual(set(lit), {replace(DEFAULT_THEME.slash, fg=None)}, "bold, the draft's own colour")
                    self.assertEqual(top, (Span(AURA_RULE * 80, replace(theme.rule, bold=True, gutter=True)),))
                    self.assertEqual(top, bottom)

    def test_every_moving_aura_reads_on_every_skin_and_grey(self) -> None:
        # The review of d8337c891: unlifted, a band colour near the background's dark/light flip fell to 3.72:1 (sky,
        # #787878) while the aura still moved. Every step and every band colour of a moving aura keeps TEXT_CONTRAST.
        from omh.skin_pack import SKIN_THEMES
        from omh.tui.theme import TEXT_CONTRAST, aura_moves, build_theme, contrast_ratio, surface_for

        backgrounds = [f"#{level:02X}{level:02X}{level:02X}" for level in range(0x50, 0xE1, 4)] + ["#0D1117", "#FFFFFF"]
        for skin in SKIN_THEMES:
            for background in backgrounds:
                theme = build_theme(skin, background)
                if not aura_moves(theme):
                    continue
                surface = surface_for(skin, background)
                low = min(contrast_ratio(style.fg, surface) for style in (*theme.aura, *theme.aura_glint))
                self.assertGreaterEqual(low, TEXT_CONTRAST, f"{skin.short_name} on {background}")

    def test_a_masked_draft_or_one_holding_a_paste_has_none(self) -> None:
        aura = set(DEFAULT_THEME.aura) | set(DEFAULT_THEME.aura_glint)
        masked = Composer(masked=True)
        masked.replace(0, 0, "dag-ulw")
        pasted = composer_with("dag-ulw ")
        pasted.handle(Paste("\n".join(f"line {number}" for number in range(40))))
        for composer in (masked, pasted):
            frame = build_frame(cols=80, rows=24, composer=composer, info=(), theme=DEFAULT_THEME, aura=3)
            self.assertFalse([span for line in frame.lines for span in line if span.style in aura])
            self.assertFalse([line for line in frame.lines if AURA_RULE in text_of(line)])

    def test_the_caret_and_the_cells_are_the_drafts_own(self) -> None:
        for text in ("/dag-ulw migrate every service", "한글 작업 dag ulw 서비스 이전", "x" * 70 + " dag-ulw " + "y" * 30):
            with self.subTest(text=text[:20]):
                lit = frame_for(text, cols=60, aura=4)
                plain = build_frame(cols=60, rows=24, composer=composer_with(text), info=(), theme=DEFAULT_THEME)
                self.assertEqual(lit.cursor, plain.cursor)
                self.assertEqual([text_of(line).replace(AURA_RULE, RULE) for line in lit.lines],
                                 [text_of(line).replace(AURA_RULE, RULE) for line in plain.lines])
                self.assertTrue(all(line_width(line) <= 60 for line in lit.lines))


class AppTests(unittest.TestCase):
    @staticmethod
    def app(depth: str = TRUECOLOR, *, motion: bool = True):
        clock = [10.0]
        app, client = make_app(clock=lambda: clock[0])
        app.color_depth, app.motion = depth, motion
        return app, client, clock

    def test_it_ticks_only_while_the_token_is_in_the_draft_and_would_move(self) -> None:
        app, _client, clock = self.app()
        type_text(app, "migrate every service")
        app.last_render = app.clock()
        self.assertFalse(app._aura_live())
        self.assertEqual(app._read_timeout(), IDLE_READ_SECONDS, "no tick for a draft without it")
        app.dirty, app.last_render = False, app.clock()
        before = app.last_render
        clock[0] += 2 * TICK_SECONDS
        app._render_when_due()
        self.assertEqual(app.last_render, before, "no frame for a draft without it")
        type_text(app, " with dag ulw")
        app.last_render = app.clock()
        self.assertTrue(app._aura_live())
        self.assertAlmostEqual(app._read_timeout(), TICK_SECONDS)
        app.dirty = False
        clock[0] += 2 * TICK_SECONDS
        app._render_when_due()
        self.assertEqual(app.last_render, clock[0], "a frame a tick while it is there")
        for depth, motion in ((COLOR_256, True), (NO_COLOR, True), (TRUECOLOR, False)):
            with self.subTest(depth=depth, motion=motion):
                app.color_depth, app.motion = depth, motion
                self.assertFalse(app._aura_live(), "it would not move: nothing ticks")
                self.assertEqual(app._read_timeout(), IDLE_READ_SECONDS)

    def test_the_phase_follows_the_tick_and_stands_at_zero_when_it_does_not_move(self) -> None:
        app, _client, clock = self.app()
        type_text(app, "dag-ulw")
        frames = []
        for at in (10.0, 10.0 + 2.5 * TICK_SECONDS):
            clock[0] = at
            app._render()
            frames.append(app.region._lines)
        self.assertTrue(frames[0] != frames[1], "the gradient moved")
        app.color_depth = COLOR_256
        still = []
        for at in (20.0, 20.0 + 2.5 * TICK_SECONDS):
            clock[0] = at
            app._render()
            still.append(app.region._lines)
        self.assertTrue(still[0] == still[1], "a static gradient at 256 colours")
        aura = {style.fg for style in app.theme.aura}
        self.assertEqual({span.style.depth for line in still[1] for span in line if span.style.fg in aura}, {COLOR_256})

    def test_it_stands_still_where_its_band_would_not_show(self) -> None:
        from omh.tui.theme import build_theme, default_theme

        app, _client, _clock = self.app()
        app.theme = build_theme(default_theme(), "#808080")
        type_text(app, "dag-ulw")
        app.last_render = app.clock()
        self.assertFalse(app._aura_live())
        self.assertEqual(app._read_timeout(), IDLE_READ_SECONDS)

    def test_nothing_ticks_and_nothing_glows_while_a_list_or_the_tree_holds_the_keys(self) -> None:
        from omh.tui.keys import ESCAPE

        app, _client, _clock = self.app()
        type_text(app, "dag-ulw migrate")
        self.assertTrue(app._aura_live())
        aura = set(app.theme.aura) | set(app.theme.aura_glint)
        for holder in ("list_selected", "tree_selected"):
            with self.subTest(holder=holder):
                if holder == "list_selected":
                    app.list_selected = "sa-1"
                else:
                    app.tree_selected = "d:run:node"
                self.assertFalse(app._aura_live())
                frame = build_frame(cols=80, rows=24, composer=app.composer, info=(), theme=app.theme, aura=3,
                                    composer_blank=True)
                self.assertFalse([line for line in frame.lines if AURA_RULE in text_of(line)], "the rules are plain")
                self.assertFalse([span for line in frame.lines for span in line if span.style in aura])
                app._on_input(Key(ESCAPE))
                app.list_selected = app.tree_selected = None  # Esc gives the keys back (each closes on it)
                self.assertTrue(app._aura_live())

    def test_it_ends_the_frame_the_token_goes_or_the_prompt_is_sent(self) -> None:
        app, client, _clock = self.app()
        aura = set(app.theme.aura) | set(app.theme.aura_glint)

        def lit() -> bool:
            app._render()
            return any(span.style in aura for line in app.region._lines for span in line)

        type_text(app, "dag-ulw")
        self.assertTrue(lit())
        app._on_input(Key(BACKSPACE))
        self.assertFalse(lit(), "dag-ul is no token")
        self.assertFalse(app._aura_live())
        type_text(app, "w migrate")
        self.assertTrue(lit())
        app._on_input(Key(ENTER))
        self.assertFalse(lit(), "sent: the composer is empty")
        self.assertFalse(app._aura_live())


if __name__ == "__main__":
    unittest.main()
