"""How many terminal cells text occupies, and how to cut it without breaking a glyph.

Every public function NFC-normalizes first and returns NFC text. macOS pastes
Hangul as decomposed jamo; counted (or painted) jamo by jamo, one syllable
would claim up to three glyph positions, so the screen and the terminal would
disagree about where a line ends.

Text is measured by cluster, not by code point: a base character plus its
combining marks, a Hangul syllable left decomposed, an emoji with a skin tone,
a VS16 emoji, a ZWJ family or a flag pair is one unit that is never split by
`truncate` or `wrap`. Widths follow what current terminals paint: combining
marks and controls 0, East Asian Wide/Fullwidth 2 (which, since Unicode 9,
includes every emoji with default emoji presentation), a symbol made emoji by
VS16 2, a ZWJ sequence one 2-cell glyph, East Asian Ambiguous 1.

`wrap` breaks on "\\n" and on spaces; a word longer than the width is hard
broken after the last `/` that fits (a path or a URL breaks between its
parts) or else at cluster boundaries, and a cluster wider than the width (a
2-cell glyph in 1 cell) gets a line of its own because there is no smaller
unit.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
import unicodedata

from .style import Line, Span, Style

TAB_CELLS = 4  # a tab is drawn as this many spaces, in the composer and in rendered text
ZWJ = "‍"
VS16 = "️"
NEWLINE = "\n"
SPACE = " "

_ZERO_WIDTH_CATEGORIES = frozenset({"Mn", "Me", "Cf"})
_SPACING_MARK = "Mc"
_WIDE = frozenset({"W", "F"})
# Hangul medial vowels and final consonants: zero width after a leading consonant.
_HANGUL_TRAILING_JAMO = ((0x1160, 0x11FF), (0xD7B0, 0xD7FF))
# Every frame measures the same short non-ASCII strings again (the composer's rules, the info line, a
# spinner glyph), so their clusters and cluster widths are kept; longer text is measured afresh.
_KEPT_TEXT_CHARS = 256
_KEPT_ENTRIES = 4096
_EMOJI_MODIFIERS = (0x1F3FB, 0x1F3FF)
_REGIONAL_INDICATORS = (0x1F1E6, 0x1F1FF)


def _in_range(code_point: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= code_point <= bounds[1]


def is_control(ch: str) -> bool:
    """C0 and C1 controls plus DEL: never painted, never part of another glyph."""
    code_point = ord(ch)
    return code_point < 0x20 or 0x7F <= code_point < 0xA0


# Unicode's bidirectional embeddings, overrides and isolates (U+202A to U+202E, U+2066 to U+2069). A
# bidi-aware terminal reorders the rest of the row around them, so the cells it draws would not be the
# cells measured (a click would land on another entry), and a command could read in another order than
# it runs. They are zero width already; they are dropped so that no row the TUI paints carries one.
BIDI_CONTROLS = frozenset(map(chr, (*range(0x202A, 0x202F), *range(0x2066, 0x206A))))


def is_unpainted(ch: str) -> bool:
    """A control (`is_control`) or a bidi control (`BIDI_CONTROLS`): dropped from text the TUI did not write."""
    return is_control(ch) or ch in BIDI_CONTROLS


def _is_zero_width(ch: str) -> bool:
    code_point = ord(ch)
    if any(_in_range(code_point, bounds) for bounds in _HANGUL_TRAILING_JAMO):
        return True
    return unicodedata.category(ch) in _ZERO_WIDTH_CATEGORIES


def _is_emoji_modifier(ch: str) -> bool:
    return _in_range(ord(ch), _EMOJI_MODIFIERS)


def _is_regional_indicator(ch: str) -> bool:
    return _in_range(ord(ch), _REGIONAL_INDICATORS)


def char_width(ch: str) -> int:
    """Cells one code point occupies on its own."""
    if is_control(ch) or _is_zero_width(ch):
        return 0
    if unicodedata.east_asian_width(ch) in _WIDE:
        return 2
    return 1


def _extends(cluster: str, ch: str) -> bool:
    """True when `ch` belongs to the glyph `cluster` started rather than starting one."""
    if not cluster or is_control(cluster[0]) or is_control(ch):
        return False
    if cluster[-1] == ZWJ:
        return True
    if _is_zero_width(ch) or unicodedata.category(ch) == _SPACING_MARK:
        return True
    if _is_emoji_modifier(ch):
        return True
    if _composes(cluster[-1], ch):
        return True
    return len(cluster) == 1 and _is_regional_indicator(cluster) and _is_regional_indicator(ch)


def _composes(before: str, ch: str) -> bool:
    """True when NFC writes `before` and the letter `ch` as one code point (Kirat Rai: U+16D63 U+16D67 is U+16D69).

    Every other character NFC joins to the one before it is a mark, which `_extends` joins already. A narrow letter
    is asked here, so text NFC has not composed yet (`clusters_as_written`) splits where NFC text does."""
    if unicodedata.category(ch) != "Lo" or unicodedata.east_asian_width(ch) in _WIDE:
        return False
    return len(unicodedata.normalize("NFC", before + ch)) == 1


def _segment(text: str) -> list[str]:
    result: list[str] = []
    for ch in text:
        if result and _extends(result[-1], ch):
            result[-1] += ch
        else:
            result.append(ch)
    return result


@lru_cache(maxsize=_KEPT_ENTRIES)
def _kept_clusters(text: str) -> tuple[str, ...]:
    return tuple(_segment(unicodedata.normalize("NFC", text)))


def clusters(text: str) -> list[str]:
    """The NFC text split into the units a cursor steps over and a cut may fall between (a new list each call)."""
    if text.isascii():  # already NFC, and no ASCII character joins another
        return list(text)
    if len(text) <= _KEPT_TEXT_CHARS:
        return list(_kept_clusters(text))
    return _segment(unicodedata.normalize("NFC", text))


def clusters_as_written(text: str) -> list[str]:
    """`clusters` without its NFC step: the same units in `text`'s own code points, for a copy or a cut that must hand
    back what was written (a decomposed macOS path still matches its file). `cell_width` measures one as painted."""
    return list(text) if text.isascii() else _segment(text)


def _ascii_width(text: str) -> int:
    """Cells of ASCII text: one per printable character, none for a control or DEL."""
    return len(text) if text.isprintable() else sum(1 for ch in text if ch.isprintable())


def cluster_width(cluster: str) -> int:
    """Cells one cluster from `clusters()` occupies."""
    if cluster.isascii():
        return _ascii_width(cluster)
    return _wide_cluster_width(cluster)


@lru_cache(maxsize=_KEPT_ENTRIES)
def _wide_cluster_width(cluster: str) -> int:
    if VS16 in cluster:
        return 2
    if ZWJ in cluster and sum(1 for ch in cluster if not _is_zero_width(ch)) > 1:
        return 2
    width = 0
    for index, ch in enumerate(cluster):
        if index and _is_emoji_modifier(ch):
            continue
        width += char_width(ch)
    return width


def cell_width(text: str) -> int:
    if text.isascii():
        return _ascii_width(text)
    return sum(cluster_width(cluster) for cluster in clusters(text))


# An item is one cluster with its width and the style of the span it came from;
# the plain-text functions use `None` as the style. Truncation and wrapping run
# on items so text and styled lines share one implementation.
_Item = tuple[str, int, Style | None]


def _text_items(text: str) -> list[_Item]:
    return [(cluster, cluster_width(cluster), None) for cluster in clusters(text)]


def _line_items(line: Line) -> list[_Item]:
    items: list[_Item] = []
    for span in line:
        items.extend((cluster, cluster_width(cluster), span.style) for cluster in clusters(span.text))
    return items


def _items_text(items: Sequence[_Item]) -> str:
    return "".join(cluster for cluster, _, _ in items)


def _items_line(items: Sequence[_Item]) -> Line:
    spans: list[Span] = []
    for cluster, _, style in items:
        if spans and spans[-1].style == style:
            spans[-1] = Span(spans[-1].text + cluster, spans[-1].style)
        else:
            spans.append(Span(cluster, style if style is not None else Style()))
    return tuple(spans)


def _items_width(items: Sequence[_Item]) -> int:
    return sum(width for _, width, _ in items)


def _fit(items: Sequence[_Item], cells: int) -> tuple[list[_Item], int]:
    """The longest prefix that fits in `cells`, and the index of the first item left out."""
    kept: list[_Item] = []
    used = 0
    for index, item in enumerate(items):
        if used + item[1] > cells:
            return kept, index
        kept.append(item)
        used += item[1]
    return kept, len(items)


def _truncate_items(items: list[_Item], cells: int, ellipsis: str) -> list[_Item]:
    if cells <= 0:
        return []
    if _items_width(items) <= cells:
        return items
    ellipsis_clusters = clusters(ellipsis)
    ellipsis_width = sum(cluster_width(cluster) for cluster in ellipsis_clusters)
    if ellipsis_width > cells:
        return _fit(items, cells)[0]
    kept, cut = _fit(items, cells - ellipsis_width)
    style = items[cut][2] if cut < len(items) else None
    return kept + [(cluster, cluster_width(cluster), style) for cluster in ellipsis_clusters]


def truncate(text: str, cells: int, ellipsis: str = "…") -> str:
    """`text` cut to at most `cells`, ending in `ellipsis` when anything was cut."""
    return _items_text(_truncate_items(_text_items(text), cells, ellipsis))


def _paragraphs(items: list[_Item]) -> list[list[_Item]]:
    paragraphs: list[list[_Item]] = [[]]
    for item in items:
        if item[0] == NEWLINE:
            paragraphs.append([])
        else:
            paragraphs[-1].append(item)
    return paragraphs


def _tokens(items: list[_Item]) -> list[list[_Item]]:
    """Runs of spaces and runs of everything else, in order."""
    tokens: list[list[_Item]] = []
    for item in items:
        if tokens and (tokens[-1][0][0] == SPACE) == (item[0] == SPACE):
            tokens[-1].append(item)
        else:
            tokens.append([item])
    return tokens


def _wrap_paragraph(items: list[_Item], cells: int) -> list[list[_Item]]:
    lines: list[list[_Item]] = []
    line: list[_Item] = []
    width = 0
    pending: list[_Item] = []  # spaces seen since the last word; dropped at a break
    for token in _tokens(items):
        if token[0][0] == SPACE:
            pending = token
            continue
        token_width = _items_width(token)
        gap = _items_width(pending)
        if width + gap + token_width <= cells:
            line.extend(pending + token)
            width += gap + token_width
            pending = []
            continue
        if line:
            lines.append(line)
            line, width = [], 0
        pending = []
        for item in token:  # fits on a fresh line in one go, or is hard broken
            if line and width + item[1] > cells:
                cut = _path_break(line, item)
                lines.append(line[:cut])
                line = line[cut:]
                width = _items_width(line)
            line.append(item)
            width += item[1]
    trailing, _ = _fit(pending, cells - width)
    lines.append(line + trailing)
    return lines


def _path_break(line: list[_Item], following: _Item) -> int:
    """Where a word hard broken at the end of `line`, before `following`, breaks: after the last `/` in it that has
    text before it (a path or a URL breaks between its parts), else at the end of the line. A `/` of a `//` (a URL's
    scheme) is not one, so `https://` never stands alone."""
    for index in range(len(line) - 1, 0, -1):
        after = line[index + 1] if index + 1 < len(line) else following
        if line[index][0] == "/" and line[index - 1][0] != "/" and after[0] != "/":
            return index + 1
    return len(line)


def _wrap_items(items: list[_Item], cells: int) -> list[list[_Item]]:
    cells = max(cells, 1)
    wrapped: list[list[_Item]] = []
    for paragraph in _paragraphs(items):
        wrapped.extend(_wrap_paragraph(paragraph, cells))
    return wrapped


def wrap(text: str, cells: int) -> list[str]:
    """`text` as lines of at most `cells` each (see the module docstring for the rules)."""
    return [_items_text(line) for line in _wrap_items(_text_items(text), cells)]


def line_width(line: Line) -> int:
    return sum(cell_width(span.text) for span in line)


def truncate_left(text: str, cells: int, ellipsis: str = "…") -> str:
    """`text` cut from the LEFT to `cells`, keeping its end: for paths, whose end says what they name."""
    text = unicodedata.normalize("NFC", text)
    if cell_width(text) <= cells:
        return text
    if cells <= cell_width(ellipsis):
        return ellipsis[:cells] if cells > 0 else ""
    kept = ""
    for cluster in reversed(clusters(text)):
        if cell_width(ellipsis + cluster + kept) > cells:
            break
        kept = cluster + kept
    return ellipsis + kept


def truncate_line(line: Line, cells: int, ellipsis: str = "…") -> Line:
    """`truncate` for a styled line; the ellipsis takes the style of the text it replaces."""
    return _items_line(_truncate_items(_line_items(line), cells, ellipsis))


def wrap_line(line: Line, cells: int) -> list[Line]:
    """`wrap` for a styled line; every span keeps its style across the breaks."""
    return [_items_line(row) for row in _wrap_items(_line_items(line), cells)]
