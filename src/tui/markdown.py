"""Render the markdown subset model replies use, one complete source line at a time.

A reply streams in token by token, and a line that has left the live region is
in the terminal's scrollback for good. So the renderer never looks
ahead: `render_line` turns ONE complete source line into rows, and the only
thing a line can learn from the lines before it is `MarkdownState` (an open
fence and its language, the multi-line string or comment a highlighted fence
line ended inside, the content column of the last list item). Rendering
a reply line by line, threading the state, gives exactly the rows rendering it
whole gives; that equality is what lets the transcript flush a reply while it
is still streaming.

The subset: ATX headings, bullet and numbered lists (wrapped rows hang under
the item text), blockquotes, fenced code (verbatim, hard-wrapped by cells, no
inline markup inside; the opening fence shows only its language as a dim label,
or nothing, and the closing fence shows nothing; a language `highlight.py` knows
is syntax-coloured, any other stays one code colour), ```diff fences whose added
and removed lines are full-row bands, inline `code`, **bold**, *italic* / _italic_, links
`[t](u)` -> `t (u)`, and horizontal rules. Tables pass through as plain text.
Constructs that need a later line to decide an earlier one (setext headings,
indented code) are left out on purpose.

Every row is plain `Line`s for `screen.py` to paint. `clean_text` runs first:
whole escape sequences (CSI, OSC, the other control strings, two-byte escapes)
are dropped, then tabs are expanded and every remaining control character is
dropped, so rows are measured on what will show and carry none of the
`[38;2;…m` debris that dropping only the ESC byte would leave
(`screen.paint_line` strips any sequence again before a row is written).
Malformed markdown renders as literal text; nothing here raises on any input.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
import unicodedata

from .escapes import strip_escapes
from .highlight import highlight_line, highlights
from .style import Line, Span, Style
from .theme import Theme
from .width import TAB_CELLS, cell_width, cluster_width, clusters, is_unpainted, line_width, wrap_line

BULLET = "•"
RULE = "─"
QUOTE_BAR = "│ "
DIFF_LANGUAGES = frozenset({"diff", "patch"})

_FENCE_CHARS = ("`", "~")
_MIN_FENCE_RUN = 3
_MAX_BLOCK_INDENT = 3  # CommonMark: four leading spaces stop a line being a heading, rule or quote
_MAX_HEADING_LEVEL = 6
_BULLET_MARKERS = frozenset("-*+")
_ORDERED_DELIMITERS = frozenset(".)")
_MAX_ORDINAL_DIGITS = 9
_DIGITS = "0123456789"
_RULE_CHARS = frozenset("-*_")
_RULE_MARKS = frozenset(" -*_")  # a line of only these may yet turn out to be a rule
_MIN_RULE_RUN = 3
_ESCAPABLE = frozenset("\\`*_[]()#+-.!|>~")



@dataclass(frozen=True)
class MarkdownState:
    """What one source line hands the next: the open fence, and the list it is in."""

    fence: str = ""  # the opening run (``` or ~~~~...) while inside a fenced block
    fence_lang: str = ""
    fence_indent: int = 0
    list_indent: int = 0  # content column of the most recent list item; 0 outside a list
    code_carry: str = ""  # the string or comment opener a highlighted fence line ended inside

    @property
    def in_fence(self) -> bool:
        return bool(self.fence)


def clean_text(text: str) -> str:
    """One source line made safe to measure: escapes dropped whole, tabs expanded, controls and bidi controls dropped.

    The transcript runs model and tool text through it so widths and wraps are
    computed on what will show. The guarantee that no escape sequence reaches
    the terminal is not this function's: `screen.paint_line` strips every row,
    whatever produced it.
    """
    return "".join(ch for ch in strip_escapes(text).expandtabs(TAB_CELLS) if not is_unpainted(ch))


def wrap_prefixed(spans: Sequence[Span], first: Line, rest: Line, width: int) -> list[Line]:
    """`spans` wrapped to `width`, the first row behind `first` and every other row behind `rest`.

    A prefix that leaves no room for text is dropped rather than overflowing the row.
    """
    width = max(1, width)
    prefix_cells = max(line_width(first), line_width(rest))
    if prefix_cells >= width:
        first, rest, prefix_cells = (), (), 0
    rows = wrap_line(tuple(spans), width - prefix_cells)
    return [(*(first if index == 0 else rest), *row) for index, row in enumerate(rows)]


def render_line(source: str, state: MarkdownState, width: int, theme: Theme) -> tuple[list[Line], MarkdownState]:
    """The rows for one complete source line, and the state the next line starts from."""
    text = clean_text(source)
    width = max(1, width)
    if state.in_fence:
        if _closes_fence(text, state.fence):
            return [], replace(state, fence="", fence_lang="", fence_indent=0, code_carry="")
        return _code_rows(text, state, width, theme)
    opened = _fence_open(text)
    if opened is not None:
        fence, lang = opened
        indent = _leading_spaces(text)
        list_indent = state.list_indent if indent else 0
        label = _verbatim_rows(" " * indent + lang, width, theme.muted) if lang else []
        return label, MarkdownState(fence, lang, indent, list_indent)
    if not text.strip():
        return [()], state
    return _block_rows(text, state, width, theme)


def render_lines(
    sources: Sequence[str], state: MarkdownState, width: int, theme: Theme
) -> tuple[list[Line], MarkdownState]:
    """`render_line` over several complete source lines, threading the state."""
    rows: list[Line] = []
    for source in sources:
        lines, state = render_line(source, state, width, theme)
        rows.extend(lines)
    return rows, state


@dataclass
class GrowingLine:
    """What `render_growing` keeps between the frames of a line still being written: the rows above a cut in it,
    wrapped once, so that a frame wraps only what follows the cut, however long the line has grown."""

    line: str = ""  # the line when the cut last moved: a later line goes on from it, or the cut is not used
    cut: int = 0  # where in `line` the rows above end; 0 for no cut
    dirty: str = ""  # a line `clean_text` changes: one that goes on from it is never cut, so is not checked again
    wrapped: str = ""  # a line that took more than one row: from one that goes on from it, places to cut are noted
    clean: str = ""  # a line `clean_text` leaves as it is: for one that goes on from it, only what was added is checked
    rows: list[Line] = field(default_factory=list)  # the rows above the cut
    rest: Line = ()  # what every row of the line but its first hangs on
    after: MarkdownState = MarkdownState()  # the state the line hands the next
    drawn: tuple[MarkdownState, int, Theme | None] = (MarkdownState(), 0, None)  # the state, width and theme


def render_growing(
    source: str, state: MarkdownState, width: int, theme: Theme, memo: GrowingLine
) -> tuple[list[Line], MarkdownState]:
    """`render_line(source, state, width, theme)` for a line that grows at its end from one call to the next.

    The rows above `memo`'s cut are reused and only the text past it is
    wrapped; the cut then moves down to the last row a word opens whose
    rows nothing after it can change (`_move_cut`). So a long paragraph
    streamed token by token costs a frame its last rows, not the whole
    paragraph. Only a paragraph or a list item line that `clean_text` leaves
    as it is, and that holds no tab, is cut; any other line is rendered whole.
    """
    width = max(1, width)
    if "\t" in source or memo.dirty and source.startswith(memo.dirty):
        return render_line(source, state, width, theme)
    if memo.cut and memo.drawn[:2] == (state, width) and memo.drawn[2] is theme and source.startswith(memo.line):
        start, lead = memo.cut, memo.rest
        tail = source[start:]
        text = clean_text(tail)
        cuttable = text == tail
    else:
        memo.cut, memo.rows = 0, []
        plain = not state.in_fence and source.strip() and not _fence_open(source)
        inline = _inline_block(source, state, theme) if plain else None
        printable = source.isprintable()  # a printable line `clean_text` leaves alone
        if inline is None or line_width(inline[1]) != line_width(inline[2]):
            # `render_line` would clean the line and make the checks just made: a printable one goes on from there.
            return _block_rows(source, state, width, theme) if plain and printable else render_line(source, state,
                                                                                                    width, theme)
        if not printable:
            # With no tab, `clean_text` leaves a line alone where it leaves each part of it alone.
            added = source[len(memo.clean) :] if source.startswith(memo.clean) else source
            if clean_text(added) != added:
                memo.dirty = source
                return render_line(source, state, width, theme)
            memo.clean = source
        start, lead, memo.rest, memo.after = inline
        memo.drawn, text, cuttable = (state, width, theme), source[start:], True
    # A line on one row has no row to cut at: until it has wrapped, it is parsed as `render_line` parses it.
    noted = cuttable and bool(memo.wrapped) and source.startswith(memo.wrapped)
    stops: list[tuple[int, int]] = []
    spans = _inline_spans(text, theme.text, theme, stops if noted else None)
    rows = wrap_prefixed(spans, lead, memo.rest, width)
    drawn = memo.rows + rows
    if noted:
        _move_cut(memo, source, start, spans, stops, rows, lead, width, theme)
    elif len(rows) > 1:
        memo.wrapped = source
    return drawn, memo.after


def _move_cut(
    memo: GrowingLine, source: str, start: int, spans: list[Span], stops: list[tuple[int, int]], rows: list[Line],
    lead: Line, width: int, theme: Theme,
) -> None:
    """Move `memo`'s cut from `start` down to the last of `rows` that opens at one of `stops` but the last.

    Everything before a stop is decided however the line goes on, so with a
    later stop the word the row opens with is too: that row stays where it
    opens, and what follows wraps from there as that text alone would (a
    row a word opens begins with nothing carried over). The rows the
    shown text maps onto, and those the text from the cut wraps to on its
    own, are checked against `rows` before the cut moves.
    """
    if len(stops) < 2 or len(rows) < 2:
        return
    shown = "".join(span.text for span in spans)
    opens = {at: index for index, at in stops[:-1]}  # where a cut can go, by the characters shown before it
    last = stops[-2][1]  # no row opening past this can take the cut: the rows below it are not read
    bare = max(line_width(lead), line_width(memo.rest)) >= width  # `wrap_prefixed` then drops the prefixes
    at, cut_row, cut_at = 0, 0, 0
    for number, row in enumerate(rows):
        if number:
            while shown[at : at + 1] == " ":  # the spaces a break left out
                at += 1
            if at > last:
                break
            if at in opens:
                cut_row, cut_at = number, opens[at]
        words = "".join(span.text for span in row[0 if bare else len(memo.rest if number else lead) :])
        if not shown.startswith(words, at):
            return
        at += len(words)
    if not cut_row:
        return
    if wrap_prefixed(_inline_spans(source[start + cut_at :], theme.text, theme), memo.rest, memo.rest, width) != rows[
        cut_row:
    ]:
        return
    if not memo.cut and set(source[: start + cut_at]) <= _RULE_MARKS:
        return  # it could still turn out to be a rule
    memo.rows = memo.rows + rows[:cut_row]
    memo.cut, memo.line = start + cut_at, source


def render_markdown(text: str, width: int, theme: Theme) -> list[Line]:
    """A whole document at `width`, from a fresh state."""
    return render_lines(text.split("\n"), MarkdownState(), width, theme)[0]


# ── block level ───────────────────────────────────────────────────────────


def _leading_spaces(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


def _run_of(text: str, ch: str) -> str:
    """The run of `ch` that `text` starts with."""
    return text[: len(text) - len(text.lstrip(ch))]


def _fence_open(text: str) -> tuple[str, str] | None:
    stripped = text.lstrip(" ")
    for ch in _FENCE_CHARS:
        run = _run_of(stripped, ch)
        if len(run) < _MIN_FENCE_RUN:
            continue
        info = stripped[len(run) :].strip()
        if ch == "`" and "`" in info:
            return None  # ```a``` on one line is inline code, not a fence
        return run, info.split()[0].lower() if info else ""
    return None


def _closes_fence(text: str, fence: str) -> bool:
    stripped = text.lstrip(" ")
    run = _run_of(stripped, fence[0])
    return len(run) >= len(fence) and not stripped[len(run) :].strip()


def _heading_text(body: str) -> str | None:
    hashes = _run_of(body, "#")
    if not 1 <= len(hashes) <= _MAX_HEADING_LEVEL:
        return None
    if len(body) > len(hashes) and body[len(hashes)] != " ":
        return None
    return body[len(hashes) :].strip()


def _is_rule(body: str) -> bool:
    marks = body.replace(" ", "")
    return len(marks) >= _MIN_RULE_RUN and marks[0] in _RULE_CHARS and marks == marks[0] * len(marks)


def _list_item(body: str) -> tuple[str, str] | None:
    """(marker as painted, item text) when `body` opens a list item."""
    if body[:1] in _BULLET_MARKERS and body[1:2] in ("", " "):
        return f"{BULLET} ", body[1:].lstrip(" ")
    digits = body[: len(body) - len(body.lstrip(_DIGITS))]
    if not 1 <= len(digits) <= _MAX_ORDINAL_DIGITS:
        return None
    rest = body[len(digits) :]
    if rest[:1] in _ORDERED_DELIMITERS and rest[1:2] in ("", " "):
        return f"{digits}{rest[0]} ", rest[1:].lstrip(" ")
    return None


def _inline_block(text: str, state: MarkdownState, theme: Theme) -> tuple[int, Line, Line, MarkdownState] | None:
    """For a list item or a paragraph line: where in `text` its inline text starts, the prefix of its first row and
    of every other, and the state after it. None for a heading, a rule, a quote or a table row."""
    indent = _leading_spaces(text)
    body = text[indent:]
    if body.startswith("|") or indent <= _MAX_BLOCK_INDENT and (
        _heading_text(body) is not None or _is_rule(body) or body.startswith(">")
    ):
        return None
    pad: Line = (Span(" " * indent),) if indent else ()
    item = _list_item(body)
    if item is not None:
        marker, content = item
        column = indent + cell_width(marker)
        first = (*pad, Span(marker, theme.muted))
        return len(text) - len(content), first, (Span(" " * column),), replace(state, list_indent=column)
    if not indent:
        state = replace(state, list_indent=0)
    elif state.list_indent:
        pad = (Span(" " * state.list_indent),)  # a continuation line hangs under its item's text
    return indent, pad, pad, state


def _block_rows(text: str, state: MarkdownState, width: int, theme: Theme) -> tuple[list[Line], MarkdownState]:
    inline = _inline_block(text, state, theme)
    if inline is not None:
        start, first, rest, after = inline
        return wrap_prefixed(_inline_spans(text[start:], theme.text, theme), first, rest, width), after
    indent = _leading_spaces(text)
    body = text[indent:]
    if indent <= _MAX_BLOCK_INDENT:
        heading = _heading_text(body)
        if heading is not None:
            return wrap_prefixed(_inline_spans(heading, theme.heading, theme), (), (), width), replace(state, list_indent=0)
        if _is_rule(body):
            return [(Span(RULE * width, theme.dim),)], replace(state, list_indent=0)
        if body.startswith(">"):
            return _quote_rows(body, width, theme), state
    pad: Line = (Span(" " * indent),) if indent else ()
    return wrap_prefixed((Span(body, theme.text),), pad, pad, width), state  # a table row


def _quote_rows(body: str, width: int, theme: Theme) -> list[Line]:
    depth = 0
    rest = body
    while rest.startswith(">"):
        depth += 1
        rest = rest[1:]
        if rest.startswith(" "):
            rest = rest[1:]
    bar: Line = (Span(QUOTE_BAR * depth, theme.quote),)
    return wrap_prefixed(_inline_spans(rest, theme.quote, theme), bar, bar, width)


# ── fenced code ───────────────────────────────────────────────────────────


def hard_wrap(spans: Sequence[Span], width: int) -> list[Line]:
    """Styled spans cut into rows of at most `width` cells, keeping every space and never splitting a cluster."""
    rows: list[Line] = []
    row: list[Span] = []
    used = 0
    for span in spans:
        piece = ""
        for cluster in clusters(span.text):
            cluster_cells = cluster_width(cluster)
            if (row or piece) and used + cluster_cells > width:
                if piece:
                    row.append(Span(piece, span.style))
                    piece = ""
                rows.append(tuple(row))
                row, used = [], 0
            piece += cluster
            used += cluster_cells
        if piece:
            row.append(Span(piece, span.style))
    rows.append(tuple(row))
    return rows


def band_rows(text: str, width: int, band: Style) -> list[Line]:
    """`text` hard-wrapped, each row padded to `width` in the band style (the TUI paints the whole row)."""
    rows: list[Line] = []
    for row in hard_wrap((Span(text, band),), width):
        filled = "".join(span.text for span in row)
        rows.append((Span(filled + " " * max(0, width - line_width(row)), band),))
    return rows


def _verbatim_rows(text: str, width: int, style: Style) -> list[Line]:
    return hard_wrap((Span(text, style),), width)


def _code_rows(text: str, state: MarkdownState, width: int, theme: Theme) -> tuple[list[Line], MarkdownState]:
    if state.fence_lang in DIFF_LANGUAGES:
        return _diff_fence_rows(text, state, width, theme), state
    if not highlights(state.fence_lang):
        return _verbatim_rows(text, width, theme.code), state
    spans, carry = highlight_line(unicodedata.normalize("NFC", text), state.fence_lang, state.code_carry, theme)
    return hard_wrap(spans, width), replace(state, code_carry=carry)


def _diff_fence_rows(text: str, state: MarkdownState, width: int, theme: Theme) -> list[Line]:
    body = text[min(state.fence_indent, _leading_spaces(text)) :]
    if body.startswith(("+++", "---")):
        return _verbatim_rows(text, width, theme.label)
    if body.startswith("@@"):
        return _verbatim_rows(text, width, theme.muted)
    if body.startswith("+"):
        return band_rows(text, width, theme.diff_add)
    if body.startswith("-"):
        return band_rows(text, width, theme.diff_remove)
    return _verbatim_rows(text, width, theme.code)


# ── inline ────────────────────────────────────────────────────────────────


def _cluster_each(text: str, index: int) -> bool:
    """Whether the character at `index`, the one before it and the one before that are a cluster each: a cut
    there breaks no glyph (a ZWJ joins the space after it, a combining mark the space before it)."""
    piece = text[max(index - 2, 0) : index + 1]
    return len(clusters(piece)) == len(piece)


def _code_span(text: str, start: int) -> tuple[str, int] | None:
    """(code text, index after the closing run) for a backtick run at `start`, or None if unclosed."""
    ticks = _run_of(text[start:], "`")
    search = start + len(ticks)
    while True:
        close = text.find(ticks, search)
        if close < 0:
            return None
        after = close + len(ticks)
        if text[after : after + 1] != "`":
            break
        search = after + len(_run_of(text[after:], "`"))
    code = text[start + len(ticks) : close]
    if len(code) >= 2 and code[0] == " " and code[-1] == " " and code.strip():
        code = code[1:-1]
    return code, after


def _link(text: str, start: int) -> tuple[str, str, int] | None:
    """(label, url, index after the link) for `[label](url)` at `start`."""
    close = text.find("]", start + 1)
    if close < 0 or text[close + 1 : close + 2] != "(":
        return None
    end = text.find(")", close + 2)
    if end < 0:
        return None
    label = text[start + 1 : close]
    url = text[close + 2 : end].strip()
    if not label or not url:
        return None
    return label, url, end + 1


def _opens_emphasis(text: str, start: int, marker: str) -> bool:
    after = start + len(marker)
    if text[after : after + 1] in ("", " "):
        return False
    return not (marker[0] == "_" and start > 0 and text[start - 1].isalnum())


def _closes_emphasis(text: str, at: int, marker: str) -> bool:
    if text[at - 1] == " ":
        return False
    if len(marker) == 1 and (text[at - 1] == marker or text[at + 1 : at + 2] == marker):
        return False  # a lone * never closes on half of a ** run
    return not (marker[0] == "_" and text[at + len(marker) : at + len(marker) + 1].isalnum())


def _emphasis(text: str, start: int) -> tuple[str, bool, int] | None:
    """(inner text, strong, index after the closing marker) for emphasis opening at `start`.

    The FIRST valid closer wins, and whether a position closes depends only on
    the text around it. So emphasis never nests inside its own kind (the outer
    would have taken the inner closer), and recursion is at most one level per
    marker kind (`**`, `__`, `*`, `_`) however many markers a line holds.
    """
    marker = text[start : start + 2] if text[start : start + 2] in ("**", "__") else text[start]
    if not _opens_emphasis(text, start, marker):
        return None
    search = start + len(marker) + 1
    while True:
        close = text.find(marker, search)
        if close < 0:
            return None
        if _closes_emphasis(text, close, marker):
            return text[start + len(marker) : close], len(marker) == 2, close + len(marker)
        search = close + 1


def _inline_spans(text: str, style: Style, theme: Theme, stops: list[tuple[int, int]] | None = None) -> list[Span]:
    """Inline markup in one line of block text, as spans over the block's `style`.

    With `stops`, each place `text` can be cut at is added to it as (index in
    `text`, characters shown before it): a word that opens after a space, at
    the top level, each of the three a cluster of its own, with every mark
    before it decided however the text goes on (a closer found, with the
    character after it that a closer is checked against, or a mark that can
    open nothing). The spans then break at each stop, which wrapping them
    does not see (`wrap_line` joins a style's neighbouring runs).
    """
    spans: list[Span] = []
    plain: list[str] = []
    end = len(text)
    settled, counted, shown = stops is not None, 0, 0

    def take_plain() -> None:
        if plain:
            spans.append(Span("".join(plain), style))
            plain.clear()

    index = 0
    while index < len(text):
        ch = text[index]
        if settled and index and text[index - 1] == " " and ch != " " and _cluster_each(text, index):
            take_plain()
            shown += sum(len(span.text) for span in spans[counted:])
            counted = len(spans)
            stops.append((index, shown))  # type: ignore[union-attr]  # `settled` holds only with `stops`
        if ch == "\\" and text[index + 1 : index + 2] in _ESCAPABLE:
            plain.append(text[index + 1])
            index += 2
            continue
        if ch == "\\":
            settled = settled and index + 1 < end
        if ch == "`":
            code = _code_span(text, index)
            settled = settled and code is not None and code[1] < end
            if code is None:
                ticks = _run_of(text[index:], "`")
                plain.append(ticks)
                index += len(ticks)
                continue
            take_plain()
            if code[0]:
                spans.append(Span(code[0], theme.code))
            index = code[1]
            continue
        if ch == "[":
            link = _link(text, index)
            if settled and link is None:  # stays plain only when its `]` is there and is not followed by `(`
                close = text.find("]", index + 1)
                settled = close >= 0 and close + 1 < end and text[close + 1] != "("
            if link is not None:
                take_plain()
                label, url, index = link
                spans.append(Span(label, theme.link))
                if url != label:
                    spans.append(Span(f" ({url})", theme.muted))
                continue
        if ch in "*_":
            emphasis = _emphasis(text, index)
            if settled:
                marker = text[index : index + 2] if text[index : index + 2] in ("**", "__") else ch
                settled = emphasis[2] < end if emphasis else index + 2 < end and not _opens_emphasis(text, index, marker)
            if emphasis is not None:
                take_plain()
                inner, strong, index = emphasis
                inner_style = replace(style, bold=True) if strong else replace(style, italic=True)
                spans.extend(_inline_spans(inner, inner_style, theme))
                continue
        plain.append(ch)
        index += 1
    take_plain()
    return spans
