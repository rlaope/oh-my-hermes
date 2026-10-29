"""The OMH TUI's stream-safe markdown renderer (`omh.tui.markdown`).

A reply is flushed to scrollback line by line while it streams, so the one
property everything rests on is that rendering line by line (threading
`MarkdownState`) gives exactly the rows a whole-document render gives. Every
other expectation here is a literal row, never a call back into the module.
"""

from __future__ import annotations

from dataclasses import replace
import random
import unicodedata
import unittest

from _tui_lines import lines_text
from unittest.mock import patch

from omh.tui import markdown
from omh.tui.markdown import (
    GrowingLine, MarkdownState, clean_text, render_growing, render_line, render_lines, render_markdown, strip_escapes,
)
from omh.tui.style import Line, Span
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.width import is_control, line_width

FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"

DOCUMENT = "\n".join(
    [
        "# Release notes",
        "",
        "The **router** now reads *every* `cue` and links [the spec](https://example.com/spec).",
        "- first bullet that is long enough to wrap onto a second row",
        "  - nested bullet",
        "    continuation under the nested item",
        "12. numbered item with snake_case_name kept literal",
        "> quoted line with **bold**",
        ">> nested quote",
        "---",
        "| col a | **col b** |",
        "```python",
        "def f(x):",
        "    return x * 2  # *not italic*",
        "```",
        "```diff",
        "--- a/file.py",
        "+++ b/file.py",
        "@@ -1,2 +1,2 @@",
        "-old line",
        "+new line",
        " context line",
        "```",
        "한글 문단도 줄바꿈이 셀 단위로 맞아야 합니다 " + FAMILY,
        "~~~",
        "unclosed fence keeps going",
    ]
)


def span_with(row: Line, text: str) -> Span:
    return next(span for span in row if span.text == text)


def render(text: str, width: int = 40) -> list[Line]:
    return render_markdown(text, width, THEME)


class BlockTests(unittest.TestCase):
    def test_heading_drops_its_hashes_and_takes_the_heading_style(self) -> None:
        rows = render("## Plan")
        self.assertEqual(lines_text(rows), ["Plan"])
        self.assertEqual(rows[0][0].style, THEME.heading)

    def test_hashes_without_a_space_are_text(self) -> None:
        rows = render("#hashtag")
        self.assertEqual(lines_text(rows), ["#hashtag"])
        self.assertEqual(rows[0][0].style, THEME.text)

    def test_bullet_wraps_under_its_text(self) -> None:
        rows = render("- alpha beta gamma delta epsilon", width=16)
        self.assertEqual(lines_text(rows), ["• alpha beta", "  gamma delta", "  epsilon"])
        self.assertEqual(span_with(rows[0], "• ").style, THEME.muted)  # a bullet is no state: grey, not the running blue

    def test_numbered_item_wraps_under_its_text(self) -> None:
        rows = render("10. one two three four five six", width=14)
        self.assertEqual(lines_text(rows), ["10. one two", "    three four", "    five six"])

    def test_nested_items_and_continuation_lines_hang_under_the_item_text(self) -> None:
        rows = render("- top\n  - nested\n    more text\n1. item\n  lazy")
        self.assertEqual(lines_text(rows), ["• top", "  • nested", "    more text", "1. item", "   lazy"])

    def test_a_plain_paragraph_ends_the_list(self) -> None:
        rows = render("- a\nplain\n  indented")
        self.assertEqual(lines_text(rows), ["• a", "plain", "  indented"])

    def test_blockquote_bars_every_row_and_nests(self) -> None:
        rows = render("> quoted **bold**\n>> deep", width=40)
        self.assertEqual(lines_text(rows), ["│ quoted bold", "│ │ deep"])
        self.assertEqual(span_with(rows[0], "quoted ").style, THEME.quote)
        self.assertEqual(span_with(rows[0], "bold").style, replace(THEME.quote, bold=True))

    def test_horizontal_rules_fill_the_width(self) -> None:
        for source in ("---", "***", "_ _ _"):
            with self.subTest(source=source):
                self.assertEqual(lines_text(render(source, width=12)), ["─" * 12])
        self.assertEqual(lines_text(render("--", width=12)), ["--"])

    def test_tables_pass_through_as_plain_text(self) -> None:
        rows = render("| a | **b** |")
        self.assertEqual(lines_text(rows), ["| a | **b** |"])
        self.assertEqual(rows[0], (Span("| a | **b** |", THEME.text),))

    def test_blank_lines_are_empty_rows(self) -> None:
        self.assertEqual(render("a\n\nb"), [(Span("a", THEME.text),), (), (Span("b", THEME.text),)])


class FenceTests(unittest.TestCase):
    def test_code_is_verbatim_with_no_inline_markup(self) -> None:
        rows = render("```python\nx = *a* `b` [c](d)\n```")
        self.assertEqual(lines_text(rows), ["python", "x = *a* `b` [c](d)"])
        self.assertEqual(rows[1], (Span("x = *a* `b` [c](d)", THEME.text),))
        self.assertEqual(rows[0], (Span("python", THEME.muted),))
        self.assertEqual(render("```\nx = *a*\n```"), [(Span("x = *a*", THEME.code),)])

    def test_fence_markers_are_never_painted(self) -> None:
        rows = render("before\n```\ncode\n~~~~ruby extra\n```\n~~~~ruby extra\nputs 1\n~~~~\nafter")
        self.assertEqual(lines_text(rows), ["before", "code", "~~~~ruby extra", "ruby", "puts 1", "after"])

    def test_an_indented_fence_labels_at_its_indent(self) -> None:
        rows = render("- step:\n  ```sh\n  ls\n  ```")
        self.assertEqual(lines_text(rows), ["• step:", "  sh", "  ls"])

    def test_fence_state_opens_and_closes(self) -> None:
        _, state = render_line("```Python extra", MarkdownState(), 40, THEME)
        self.assertTrue(state.in_fence)
        self.assertEqual(state.fence_lang, "python")
        _, state = render_line("```", state, 40, THEME)
        self.assertFalse(state.in_fence)

    def test_a_shorter_or_different_run_does_not_close(self) -> None:
        _, state = render_lines(["~~~~", "code", "~~~", "```"], MarkdownState(), 40, THEME)
        self.assertTrue(state.in_fence)
        _, state = render_line("~~~~~", state, 40, THEME)
        self.assertFalse(state.in_fence)

    def test_long_code_lines_hard_wrap_by_cells_keeping_every_space(self) -> None:
        rows = render("```\nab  cd  ef\n```", width=4)
        self.assertEqual(lines_text(rows), ["ab  ", "cd  ", "ef"])

    def test_inline_triple_backticks_are_code_not_a_fence(self) -> None:
        rows = render("```a``` after")
        self.assertEqual(lines_text(rows), ["a after"])

    def test_diff_lines_get_full_row_bands(self) -> None:
        rows = render("```diff\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n ctx\n```", width=20)
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0], (Span("diff", THEME.muted),))
        self.assertEqual(rows[1], (Span("--- a/f", THEME.label),))
        self.assertEqual(rows[2], (Span("+++ b/f", THEME.label),))
        self.assertEqual(rows[3], (Span("@@ -1 +1 @@", THEME.muted),))  # a hunk header is no state either
        self.assertEqual(rows[4], (Span("-old" + " " * 16, THEME.diff_remove),))
        self.assertEqual(rows[5], (Span("+new" + " " * 16, THEME.diff_add),))
        self.assertEqual(rows[6], (Span(" ctx", THEME.code),))

    def test_a_wrapped_diff_line_bands_every_row(self) -> None:
        rows = render("```patch\n+" + "x" * 24 + "\n```", width=10)[1:]
        self.assertEqual(
            rows,
            [
                (Span("+xxxxxxxxx", THEME.diff_add),),
                (Span("xxxxxxxxxx", THEME.diff_add),),
                (Span("xxxxx     ", THEME.diff_add),),
            ],
        )

    def test_a_diff_fence_inside_a_list_reads_markers_after_the_fence_indent(self) -> None:
        rows = render("- change:\n  ```diff\n  +added\n  ```", width=12)
        self.assertEqual(rows[2], (Span("  +added    ", THEME.diff_add),))


class InlineTests(unittest.TestCase):
    def test_inline_code(self) -> None:
        rows = render("use `git status` now")
        self.assertEqual(
            rows[0], (Span("use ", THEME.text), Span("git status", THEME.code), Span(" now", THEME.text))
        )

    def test_bold_and_italic(self) -> None:
        row = render("**b** *i* _u_")[0]
        self.assertEqual(span_with(row, "b").style, replace(THEME.text, bold=True))
        self.assertEqual(span_with(row, "i").style, replace(THEME.text, italic=True))
        self.assertEqual(span_with(row, "u").style, replace(THEME.text, italic=True))

    def test_emphasis_nests(self) -> None:
        row = render("**a *b* c**")[0]
        self.assertEqual(span_with(row, "b").style, replace(THEME.text, bold=True, italic=True))

    def test_intraword_underscores_and_spaced_stars_stay_literal(self) -> None:
        rows = render("snake_case_name and 2 * 3 * 4")
        self.assertEqual(rows[0], (Span("snake_case_name and 2 * 3 * 4", THEME.text),))
        rows = render("my_var and their_")
        self.assertEqual(rows[0], (Span("my_var and their_", THEME.text),))

    def test_links_show_text_then_url(self) -> None:
        row = render("see [docs](https://example.com).")[0]
        self.assertEqual(lines_text([row]), ["see docs (https://example.com)."])
        self.assertEqual(span_with(row, "docs").style, THEME.link)
        self.assertEqual(span_with(row, " (https://example.com)").style, THEME.muted)

    def test_escapes_and_unclosed_markers_are_literal(self) -> None:
        self.assertEqual(lines_text(render("\\*not\\* `open **bold [x](")), ["*not* `open **bold [x]("])


class StreamingTests(unittest.TestCase):
    def test_line_by_line_render_equals_whole_render(self) -> None:
        for width in (12, 40, 80):
            with self.subTest(width=width):
                streamed: list[Line] = []
                state = MarkdownState()
                for source in DOCUMENT.split("\n"):
                    rows, state = render_line(source, state, width, THEME)
                    streamed.extend(rows)
                self.assertEqual(streamed, render_markdown(DOCUMENT, width, THEME))
                self.assertTrue(state.in_fence)

    def test_hangul_and_emoji_wrap_by_cells_without_splitting_a_cluster(self) -> None:
        rows = render("- 한글 문장이 아주 길게 이어집니다 " + FAMILY + " 가족", width=12)
        self.assertEqual(lines_text(rows), ["• 한글", "  문장이", "  아주 길게", "  이어집니다", "  " + FAMILY + " 가족"])
        self.assertTrue(all(line_width(row) <= 12 for row in rows))

    def test_wide_code_wraps_on_glyph_boundaries_and_decomposed_hangul_is_composed(self) -> None:
        decomposed = unicodedata.normalize("NFD", "가나다라마바사")
        rows = render("```\n" + decomposed + "\n```", width=5)
        self.assertEqual(lines_text(rows), ["가나", "다라", "마바", "사"])


class MalformedInputTests(unittest.TestCase):
    CASES = (
        "```",
        "```\n```\n```",
        "#######",
        "# ",
        "**",
        "*",
        "_",
        "`",
        "``x`",
        "[a](",
        "[](u)",
        "[a]()",
        ">" * 60 + " deep",
        "- " * 40,
        "1.",
        "1234567890. too many digits",
        "*" * 501,
        "**" * 2000 + "x" + "**" * 2000,
        "_a_b_c_d_" * 50,
        "\x1b[2J\x1b[31mred\x07",
        "\tindented\twith\ttabs",
        "\r\n\x00\x85",
        "+" * 300,
        "```diff\n+" + FAMILY * 30,
        " " * 200 + "far",
    )

    def test_never_raises_and_never_paints_a_control_character(self) -> None:
        for source in self.CASES:
            for width in (1, 3, 20, 80):
                with self.subTest(source=source[:30], width=width):
                    rows = render(source, width=width)
                    for row in rows:
                        for span in row:
                            self.assertFalse(any(is_control(ch) for ch in span.text), span.text)
                    if width >= 20:
                        self.assertTrue(all(line_width(row) <= width for row in rows))

    def test_escape_sequences_are_dropped_whole(self) -> None:
        self.assertEqual(lines_text(render("\x1b[2J\x1b[31mred\x07")), ["red"])

    def test_tabs_expand_to_spaces(self) -> None:
        self.assertEqual(lines_text(render("\tx")), ["    x"])


class EscapeSequenceTests(unittest.TestCase):
    """Gateway text carries ANSI colour (Hermes renders inline diffs with SGR); none of it may reach a Line."""

    CASES = (
        ("\x1b[38;2;255;255;255;48;2;120;20;20m-old\x1b[0m", "-old"),
        ("\x1b[1;31mbold red\x1b[m plain", "bold red plain"),
        ("\x1b]8;;https://example.com\x07link\x1b]8;;\x07", "link"),
        ("\x1b]8;id=1;https://example.com\x1b\\link\x1b]8;;\x1b\\ after", "link after"),
        ("\x1b]0;window title\x07text", "text"),
        ("up\x1b[2Aleft\x1b[10D\x1b[10;5Hat\x1b[K\x1b[2J", "upleftat"),
        ("\x1b[?25lhidden cursor\x1b[?25h", "hidden cursor"),
        ("\x1b7saved\x1b8 \x1b(Bcharset\x1bc", "saved charset"),
        ("\x1bPdevice control\x1b\\kept", "kept"),
        ("\x9b31m8-bit csi\x9b0m", "8-bit csi"),
        ("\x9d8;;u\x9clink\x9d8;;\x9c", "link"),
        ("cut off \x1b[38;2;12", "cut off "),
        ("unterminated \x1b]8;;https://x.y never closes", "unterminated "),
        ("broken \x1b[31한글", "broken 한글"),
        ("lone escape \x1b", "lone escape "),
        ("plain text, no escapes [31m", "plain text, no escapes [31m"),
    )

    def test_complete_and_cut_off_sequences_are_dropped_whole(self) -> None:
        for source, expected in self.CASES:
            with self.subTest(source=source):
                self.assertEqual(strip_escapes(source), expected)
                self.assertEqual(clean_text(source), expected)

    def test_every_markdown_construct_drops_them(self) -> None:
        document = "\n".join(
            [
                "# \x1b[1mTitle\x1b[0m",
                "- \x1b[32mitem\x1b[0m",
                "> \x1b]8;;https://x.y\x07quote\x1b]8;;\x07",
                "`\x1b[31mcode\x1b[0m` and [\x1b[4mlink\x1b[0m](https://x.y)",
                "```python",
                "x = '\x1b[31mred\x1b[0m'",
                "```",
                "```diff",
                "\x1b[38;2;255;255;255;48;2;20;90;20m+added\x1b[0m",
                "```",
            ]
        )
        rows = render(document, width=40)
        self.assertEqual(
            lines_text(rows),
            ["Title", "• item", "│ quote", "code and link (https://x.y)", "python", "x = 'red'", "diff",
             "+added" + " " * 34],
        )
        for row in rows:
            for span in row:
                self.assertNotIn("\x1b", span.text)
                self.assertNotIn("[3", span.text)


HIGHLIGHTED = "\n".join(
    [
        "Some code:",
        "```python",
        "def greet(name):",
        '    """Say hello.',
        "",
        "    # still the docstring",
        '    """',
        "    return f'hi {name}'  # 한글 " + FAMILY,
        "```",
        "```ts",
        "const msg = `line one",
        "line two ${x}`; /* block",
        "comment */ let n = 0x1F;",
        "```",
        "```go",
        "s := `raw",
        "```",
        "after the fence *stays markdown*",
    ]
)


class BidiControlTests(unittest.TestCase):
    BIDI = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

    def test_clean_text_drops_every_embedding_override_and_isolate(self) -> None:
        self.assertEqual(clean_text(f"a{self.BIDI}b"), "ab")
        self.assertEqual(clean_text("echo safe\u202e; rm -rf ~\u202c"), "echo safe; rm -rf ~")

    def test_other_format_characters_and_right_to_left_text_stay(self) -> None:
        # Marks that only lean a neutral one way, joiners, and Hebrew or Arabic letters themselves.
        for kept in ("\u200e", "\u200f", "\u061c", "\u200d", "שלום", "مرحبا"):
            with self.subTest(kept=kept):
                self.assertEqual(clean_text(f"a{kept}b"), f"a{kept}b")

    def test_rendered_markdown_carries_none(self) -> None:
        rows = render_markdown(f"# {self.BIDI}Title\n- item{self.BIDI}\n`code{self.BIDI}`", 60, THEME)
        self.assertFalse(any(ch in self.BIDI for row in rows for span in row for ch in span.text))


class HighlightTests(unittest.TestCase):
    def test_line_by_line_render_equals_whole_render_across_multiline_strings_and_comments(self) -> None:
        for width in (8, 30, 80):
            with self.subTest(width=width):
                streamed: list[Line] = []
                state = MarkdownState()
                for source in HIGHLIGHTED.split("\n"):
                    rows, state = render_line(source, state, width, THEME)
                    streamed.extend(rows)
                self.assertEqual(streamed, render_markdown(HIGHLIGHTED, width, THEME))
                self.assertEqual(state, MarkdownState())

    def test_highlighted_rows_take_the_syntax_roles(self) -> None:
        rows = render("```python\nreturn 'x'  # c\n```")
        self.assertEqual(
            rows[1],
            (Span("return", THEME.syntax_keyword), Span(" ", THEME.text), Span("'x'", THEME.syntax_string),
             Span("  ", THEME.text), Span("# c", THEME.syntax_comment)),
        )

    def test_the_carry_threads_through_the_state_and_the_fence_close_resets_it(self) -> None:
        _, state = render_lines(["```python", "s = '''open"], MarkdownState(), 40, THEME)
        self.assertEqual(state.code_carry, "'''")
        rows, state = render_line("    # inside", state, 40, THEME)
        self.assertEqual(rows, [(Span("    # inside", THEME.syntax_string),)])
        rows, state = render_line("```", state, 40, THEME)
        self.assertEqual((rows, state), ([], MarkdownState()))
        self.assertEqual(lines_text(render("```python\ns = '''open\n```\nafter *it*")), ["python", "s = '''open", "after it"])

    def test_a_wrapped_highlighted_line_keeps_its_styles_and_never_splits_a_glyph(self) -> None:
        rows = render('```js\nlet s = "한글한글" // 끝\n```', width=9)[1:]
        self.assertEqual(
            rows,
            [
                (Span("let", THEME.syntax_keyword), Span(" s = ", THEME.text), Span('"', THEME.syntax_string)),
                (Span('한글한글"', THEME.syntax_string),),
                (Span(" ", THEME.text), Span("// 끝", THEME.syntax_comment)),
            ],
        )
        self.assertEqual([line_width(row) for row in rows], [9, 9, 6])

    def test_random_fenced_documents_never_raise_and_stream_like_the_whole(self) -> None:
        generator = random.Random(2087)
        langs = ["python", "js", "json", "bash", "go", "rust", "yaml", "c", "sql", "nope", ""]
        alphabet = ['"""', "'''", "`", "/*", "*/", '"', "'", "#", "//", "x", " ", "\\", "한", FAMILY, "\x1b[31m"]
        for _ in range(60):
            sources: list[str] = []
            for _ in range(generator.randrange(1, 8)):
                sources.append("```" + generator.choice(langs))
                for _ in range(generator.randrange(0, 5)):
                    sources.append("".join(generator.choice(alphabet) for _ in range(generator.randrange(0, 12))))
                if generator.random() < 0.7:
                    sources.append("```")
            width = generator.choice((1, 7, 40))
            with self.subTest(sources=sources, width=width):
                streamed, _ = render_lines(sources, MarkdownState(), width, THEME)
                self.assertEqual(streamed, render_markdown("\n".join(sources), width, THEME))
                for row in streamed:
                    for span in row:
                        self.assertFalse(any(is_control(ch) for ch in span.text), span.text)


# What a streamed line grows by: words and spaces, every inline mark (closed later, or never), escapes, joining marks
# and jamo a cut must not fall before, wide and emoji clusters, hard-broken words and paths, a tab and controls.
GROWTH = (
    "word ", "token ", "a", "b ", "  ", " ", "**", "*", "_", "__", "`", "``", "[", "]", "(", ")", "\\", "x_y ",
    "한국어 ", "가", "\u1161", "e\u0301 ", "\u0301", "👍🏽 ", FAMILY + " ", "🇰🇷", "/", "https://x.example/a/b ",
    "verylongwordwithoutanyspacesatall" * 2, "-", "1.", "#", ">", "|", "\t", "\x1b[31m", "\x07", "\u202e", ". ",
    "x\u200d ", "\u200d",
)
PROSE = ("word ", "to", "ken ", "and ", "**b** ", "`c` ", "[l](u) ", "_i_ ")


class GrowingLineTests(unittest.TestCase):
    """`render_growing` is `render_line` for a line that grows at its end, wrapping only the rows past its cut."""

    def test_every_step_of_a_growing_line_renders_as_the_whole_line_does(self) -> None:
        starts = ("", "- ", "1. ", "  ", "    ", "* ", "-", "--", "# ", "> ", "```", "|")
        cuts = 0
        for seed in range(160):
            rnd = random.Random(seed)
            line, memo = rnd.choice(starts), GrowingLine()
            state = rnd.choice((MarkdownState(), MarkdownState(list_indent=2)))
            width = rnd.choice((1, 2, 5, 8, 13, 20, 40, 77))
            for step in range(40):
                pieces = GROWTH if rnd.random() < 0.3 else PROSE
                line += "".join(rnd.choice(pieces) for _ in range(rnd.randint(1, 4)))
                drawn_at = width if rnd.random() < 0.9 else rnd.choice((5, 13, 40))  # a resize now and then
                self.assertEqual(render_growing(line, state, drawn_at, THEME, memo), render_line(line, state, drawn_at,
                                 THEME), (seed, step, drawn_at, line))
                cuts += memo.cut > 0
        self.assertGreater(cuts, 1000)  # the cut is what the equality is about: most steps draw past one

    def test_a_space_a_zwj_joins_is_no_place_to_cut(self) -> None:
        # Review of #2389: the space after `x‍` is one cluster with it, so the word after it opens no row of its own.
        memo, line = GrowingLine(), "one two x\u200d __s "
        for grown in (line, line + "t_"):
            self.assertEqual(render_growing(grown, MarkdownState(), 12, THEME, memo), render_line(grown, MarkdownState(),
                             12, THEME))

    def test_a_line_that_cannot_be_cut_does_no_more_work_than_render_line(self) -> None:
        # Review of #2389: an early open mark kept the cut still and the bookkeeping made each frame dearer.
        for opening in ("use the ` key ", "an **open one ", "a [link without end ", "*.py "):
            line, memo = opening + "token " * 200, GrowingLine()
            for grown in (line, line + "more ", line + "more and more "):
                calls: dict[str, list[int]] = {}
                for name in ("_code_span", "_emphasis", "_link", "wrap_line"):
                    real = getattr(markdown, name)
                    calls[name] = [0, 0]

                    def counting(*args: object, _real: object = real, _name: str = name) -> object:
                        calls[_name][which] += 1
                        return _real(*args)  # type: ignore[operator]

                    patch(f"omh.tui.markdown.{name}", counting).start()
                try:
                    which = 0
                    render_line(grown, MarkdownState(), 60, THEME)
                    which = 1
                    render_growing(grown, MarkdownState(), 60, THEME, memo)
                finally:
                    patch.stopall()
                self.assertEqual(memo.cut, 0, opening)
                for name, (by_line, by_growing) in calls.items():
                    self.assertLessEqual(by_growing, by_line, (opening, name))

    def test_a_line_on_one_row_notes_no_place_to_cut(self) -> None:
        # Review 2 of #2389: noting cut places on a line that has not wrapped made it dearer than `render_line`.
        noted: list[str] = []
        real = markdown._cluster_each

        def counting(text: str, index: int) -> bool:
            noted.append(text)
            return real(text, index)

        line, memo = "", GrowingLine()
        with patch("omh.tui.markdown._cluster_each", counting):
            while len(line) < 90:
                line += "a\u200d "
                render_growing(line, MarkdownState(), 100, THEME, memo)
        self.assertEqual(noted, [])

    def test_a_long_streamed_paragraph_wraps_only_its_last_rows(self) -> None:
        wrapped: list[int] = []
        real = markdown.wrap_line

        def counting(line: Line, cells: int) -> list[Line]:
            wrapped.append(sum(len(span.text) for span in line))
            return real(line, cells)

        line, memo = "", GrowingLine()
        with patch("omh.tui.markdown.wrap_line", counting):
            for index in range(3000):
                line += ("**bold** ", "`code` ", "한국어 ", "token ")[index % 4]
                wrapped.clear()
                render_growing(line, MarkdownState(), 60, THEME, memo)
        self.assertGreater(len(line), 19_000)
        self.assertLess(sum(wrapped), 600, wrapped)  # the last frame wrapped a few rows' text, not the paragraph


if __name__ == "__main__":
    unittest.main()
