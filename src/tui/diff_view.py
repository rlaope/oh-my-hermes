"""An edit tool's inline diff, as rows under that tool's row in the transcript.

Hermes renders the diff itself before it reaches the wire
(`agent/display.py::render_edit_diff_with_delta`, Hermes 6c61c3e27d):
`_emit_inline_diff` writes a "  ┊ review diff" header meant for its own
terminal printer, then `_render_inline_unified_diff` writes, per file, an
`a/x → b/x` header (the `---`/`+++` pair folded into one line), `@@` hunk
headers, and `+` / `-` / context lines, each wrapped in 24-bit SGR colour;
`_summarize_rendered_diff_sections` caps a long diff and appends one summary
line ("… omitted N diff line(s) …"). `tool.complete.payload.inline_diff` is
those lines joined by "\\n".

So the colour is stripped (`clean_text`, which drops whole escape sequences),
the review header is dropped as Ink drops it, every other line is classified
by its first characters, and the theme paints it: added and removed lines as
bands from the gutter's edge to the right edge, the file header in the label
style, context like code, anything else dim. A code line also takes syntax
colour after its mark, in the language the file header names (`language_of`,
`highlight.highlight_line`), over its band; a colour that would not read on a
band is lifted there (`_on_band`). Each side carries its own open string or
comment (the new file reads added and context lines, the old one removed and
context lines), and a hunk or file header resets both. Diff lines hard-wrap like fenced
code, never splitting a glyph; the summary and other prose word-wrap.

Hunk headers are not rows. Their `-a +c` starts number the lines after them
in a dim, right-aligned gutter (the new file's number for added and context
lines, the old file's for removed ones), and a hunk after the first leaves a
`⋮` in the gutter where the numbering jumps. The gutter is `DIFF_INDENT`
cells, wider only for a number that needs it, so a band starts where the
indent ends; a terminal too narrow for it gets neither gutter nor indent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .highlight import highlight_line
from .markdown import band_rows, clean_text, hard_wrap, wrap_prefixed
from .style import Line, Span, Style
from ..skin_pack import hex_to_rgb
from .theme import BLACK, TEXT_CONTRAST, WHITE, Theme, is_light, lifted_colour
from .width import line_width, truncate_left

DIFF_FILE = "file"
DIFF_HUNK = "hunk"
DIFF_ADDED = "added"
DIFF_REMOVED = "removed"
DIFF_CONTEXT = "context"
DIFF_NOTE = "note"  # the omitted-lines summary, "\ No newline at end of file", anything else

DIFF_INDENT = 5  # the diff hangs under the tool row's result column, where `  ⎿  ` puts a result's words
PREVIEW_LINES = 24  # diff lines shown in the live and flushed view; /history shows them all

FILE_ARROW = " → "  # `_render_inline_unified_diff` joins the two file names with it
HUNK_GAP_MARK = "⋮"  # in the gutter where a later hunk starts
REVIEW_HEADER_MARK = "┊"  # `display.diff.review_header` in every Hermes locale


@dataclass(frozen=True)
class DiffLine:
    kind: str
    text: str


def _kind(text: str) -> str:
    if text.startswith("@@"):
        return DIFF_HUNK
    if text.startswith("+"):
        return DIFF_ADDED
    if text.startswith("-"):
        return DIFF_REMOVED
    if text.startswith(" "):
        return DIFF_CONTEXT
    if FILE_ARROW in text:
        return DIFF_FILE
    return DIFF_NOTE


def _trimmed(lines: list[str]) -> list[str]:
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = len(lines)
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _side(name: str) -> str:
    """One side of the file header without git's `a/` or `b/` prefix."""
    for prefix in ("a/", "b/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


_NO_FILE = "/dev/null"  # git's side of a created or deleted file


def compact_file_header(text: str) -> str:
    """`a/x → b/x` as `x` when one file is edited, created or deleted; `x → y` only for a rename."""
    before, _, after = text.strip().partition(FILE_ARROW)
    old, new = _side(before.strip()), _side(after.strip())
    if old in (new, _NO_FILE, ""):
        return new
    if new == _NO_FILE:
        return old
    return f"{old}{FILE_ARROW}{new}"


def _without_padding(line: DiffLine) -> DiffLine:
    """A code line without the spaces after its text, its `+`, `-` or ` ` kept; any other line as it is."""
    if line.kind in (DIFF_ADDED, DIFF_REMOVED, DIFF_CONTEXT):
        return DiffLine(line.kind, line.text[:1] + line.text[1:].rstrip())
    return line


def parse_inline_diff(payload: str) -> tuple[DiffLine, ...]:
    """The classified lines of an `inline_diff` payload; () for an empty one or one that is only the header.

    Hermes pads each changed line with spaces (to 143 cells in a live patch);
    a band reaches the right edge by itself, and the padding would wrap it
    into a second, empty band row, so a code line's trailing spaces go.
    """
    lines = _trimmed([clean_text(line) for line in payload.split("\n")])
    if lines and lines[0].lstrip().startswith(REVIEW_HEADER_MARK):
        lines = _trimmed(lines[1:])
    classified = [_without_padding(DiffLine(_kind(line), line)) for line in lines]
    return tuple(
        DiffLine(line.kind, compact_file_header(line.text)) if line.kind == DIFF_FILE else line for line in classified
    )


def _style(kind: str, theme: Theme) -> Style:
    if kind == DIFF_ADDED:
        return theme.diff_add
    if kind == DIFF_REMOVED:
        return theme.diff_remove
    if kind == DIFF_FILE:
        return theme.label
    if kind == DIFF_CONTEXT:
        return theme.code
    return theme.muted


def _indent(width: int) -> Line:
    """The diff's hanging indent; it gives way on a terminal too narrow to leave the text more room than it takes."""
    return (Span(" " * DIFF_INDENT),) if width > DIFF_INDENT * 2 else ()


def _hunk_starts(text: str) -> tuple[int, int] | None:
    """(old, new) first line numbers from `@@ -a,b +c,d @@`; None when the header does not carry both."""
    parts = text.split("@@")
    fields = parts[1].split() if len(parts) >= 3 else []
    if len(fields) < 2 or not fields[0].startswith("-") or not fields[1].startswith("+"):
        return None
    try:
        return int(fields[0][1:].partition(",")[0]), int(fields[1][1:].partition(",")[0])
    except ValueError:
        return None


def _numbered(lines: Sequence[DiffLine]) -> list[tuple[DiffLine, int | None]]:
    """Each line with its gutter number: new-file numbers for added and context lines, old-file for removed."""
    old: int | None = None
    new: int | None = None
    numbered: list[tuple[DiffLine, int | None]] = []
    for line in lines:
        number = None
        if line.kind == DIFF_HUNK:
            old, new = _hunk_starts(line.text) or (None, None)
        elif line.kind in (DIFF_ADDED, DIFF_CONTEXT) and new is not None:
            number, new = new, new + 1
        elif line.kind == DIFF_REMOVED and old is not None:
            number, old = old, old + 1
        if line.kind == DIFF_CONTEXT and old is not None:
            old += 1
        numbered.append((line, number))
    return numbered


def _gutter_cells(numbers: Sequence[int | None], width: int) -> int:
    """`DIFF_INDENT`, wider for a long number; 0 on a terminal too narrow to leave the text more room than it takes."""
    longest = max((len(str(number)) for number in numbers if number is not None), default=0)
    cells = max(DIFF_INDENT, longest + 1)
    return cells if width > cells * 2 else 0


def _gutter(label: str, gutter: int, theme: Theme) -> Line:
    """`label` right-aligned in the gutter, one space before the text; nothing when there is no gutter."""
    return (Span(label.rjust(gutter - 1) + " ", theme.muted),) if gutter else ()


def language_of(path: str) -> str:
    """The `highlight.LANGUAGES` name for a file by its extension (or its name, for a Makefile), "" for none."""
    name = path.rsplit("/", 1)[-1].lower()
    if name in ("makefile", "dockerfile"):
        return name
    return name.rpartition(".")[2] if "." in name else ""


def _coloured(text: str, style: Style, lang: str, carry: str, theme: Theme) -> tuple[list[Span], str]:
    """A diff line's spans: its `+`, `-` or ` ` mark in `style`, its code in the language's syntax colours, each
    over `style`'s band. A line of a language with no table is one span in `style`, as before."""
    if not lang or len(text) < 2:
        return [Span(text, style)], carry
    code, carry = highlight_line(text[1:], lang, carry, theme)
    if code == [Span(text[1:], theme.code)]:  # `highlight_line`'s answer for a language it has no table for
        return [Span(text, style)], carry
    # The language's plain text keeps the band's own ink (`diff_add`'s foreground on a dark one), else the terminal's;
    # a syntax colour on a band is lifted until it reads there (`_on_band`), as the theme lifts it on the terminal.
    return [Span(text[:1], style), *(Span(span.text, replace(span.style, fg=_on_band(span.style.fg, style) if span.style.fg
                                                             else (style.fg if style.bg else None), bg=style.bg))
                                     for span in code)], carry


def _on_band(colour: str, style: Style) -> str:
    """`colour` moved toward white on a dark band, black on a light one, only as far as `TEXT_CONTRAST` there takes."""
    if not style.bg or not hex_to_rgb(style.bg) or not hex_to_rgb(colour):
        return colour
    return lifted_colour(colour, style.bg, TEXT_CONTRAST, BLACK if is_light(style.bg) else WHITE)


def _code_rows(spans: list[Span], style: Style, width: int, band: bool, number: int | None, gutter: int,
               theme: Theme) -> list[Line]:
    """A diff line hard-wrapped like fenced code after the gutter, its number on the first row; a band reaches the right edge."""
    cells = width - gutter
    if len(spans) == 1:  # one colour: wrapped and banded as one run, as before syntax colour
        rows = band_rows(spans[0].text, cells, style) if band else hard_wrap(spans, cells)
    else:
        rows = hard_wrap(spans, cells)
        if band:  # each row padded to the right edge in the band
            rows = [(*row, Span(" " * max(0, cells - line_width(row)), style)) for row in rows]
    label = str(number) if number is not None else ""
    return [(*_gutter(label if index == 0 else "", gutter, theme), *row) for index, row in enumerate(rows)]


def _note_rows(text: str, style: Style, width: int) -> list[Line]:
    """Prose (a summary, a count) word-wrapped under the indent."""
    indent = _indent(width)
    return wrap_prefixed((Span(text, style),), indent, indent, width)


def _line_rows(line: DiffLine, number: int | None, width: int, gutter: int, theme: Theme, spans: list[Span]) -> list[Line]:
    style = _style(line.kind, theme)
    if line.kind == DIFF_NOTE:
        return _note_rows(line.text, style, width)
    if line.kind == DIFF_FILE:
        # One row, cut from the left: the end of a path names the file.
        indent = _indent(width)
        return [(*indent, Span(truncate_left(line.text, width - line_width(indent)), style))]
    return _code_rows(spans, style, width, line.kind in (DIFF_ADDED, DIFF_REMOVED), number, gutter, theme)


def _hidden_note(hidden: int) -> str:
    noun = "line" if hidden == 1 else "lines"
    return f"… +{hidden} {noun} · ctrl+o shows all"


def diff_rows(
    lines: Sequence[DiffLine], width: int, theme: Theme, full: bool = False, lead: Line = ()
) -> list[Line]:
    """The rows for a parsed diff at `width`: the first `PREVIEW_LINES` lines and a count of the rest, or all.

    Hunk headers count toward the preview, but not toward the hidden count, which names rows.
    `lead` (`DIFF_INDENT` cells: the tool row's result mark) takes the place of
    the first row's indent when that row has one.
    """
    width = max(1, width)
    numbered = _numbered(lines)
    gutter = _gutter_cells([number for _line, number in numbered], width)
    shown = numbered if full else numbered[:PREVIEW_LINES]
    rows: list[Line] = []
    hunks = 0
    lang, carry = "", {DIFF_ADDED: "", DIFF_REMOVED: "", DIFF_CONTEXT: ""}
    for line, number in shown:
        if line.kind == DIFF_HUNK:
            hunks += 1
            carry = dict.fromkeys(carry, "")
            if hunks > 1 and gutter:
                rows.append((Span(HUNK_GAP_MARK.rjust(gutter - 1), theme.dim),))
            continue
        if line.kind == DIFF_FILE:
            lang, carry = language_of(line.text.rpartition(FILE_ARROW)[2] or line.text), dict.fromkeys(carry, "")
        spans = [Span(line.text, _style(line.kind, theme))]
        if line.kind in carry:
            # The new file reads added and context lines in order, the old one removed and context lines: each side
            # carries its own open string or comment, and a context line moves both.
            side = DIFF_REMOVED if line.kind == DIFF_REMOVED else DIFF_ADDED
            spans, after = _coloured(line.text, _style(line.kind, theme), lang, carry[side], theme)
            carry[side] = after
            if line.kind == DIFF_CONTEXT:
                carry[DIFF_REMOVED] = after
        rows.extend(_line_rows(line, number, width, gutter, theme, spans))
    hidden = sum(1 for line, _number in numbered[len(shown) :] if line.kind != DIFF_HUNK)
    if hidden:
        rows.extend(_note_rows(_hidden_note(hidden), theme.muted, width))
    indent = _indent(width)
    if lead and indent and rows and rows[0][: len(indent)] == indent:
        rows[0] = (*lead, *rows[0][len(indent) :])
    return rows
