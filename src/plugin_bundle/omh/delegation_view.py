"""Draw a `delegation_graph/v1` as text: frontiers of boxes, or a compact tree when boxes do not fit.

Pure: no I/O, no clock, nothing imported from `omh`. The OMH TUI draws the
lines with its own styles (every piece of text carries a role), and `omh hud
--graph` joins them as text. A chat reply never carries this drawing
(`delegation_snapshot.py` writes its own short text).

The boxes stand in frontiers under a header that names the task count,
the run and its state (``Running · Done 1/5``). Every node but the root is a
box of four lines: its title, its category and model, its status with its
glyph and duration (and the output tokens its child wrote, ``· ↓1.2k``, while
the line still fits the box whole), and its parents (``← Export API``) or ``Start node``. The
root is no box: what it dispatched starts a frontier, and its model is named
in the header. A node's frontier is the longest path of recorded edges (a
dispatch, a `depends_on`, a repair or an extend) from a node with none, and
what comes after a repaired node (a node that depends on it, or an extend its
check added) sits below that node's repair, which ran first. The
nodes of one frontier sit side by side with a ``· Same frontier`` label
under them. Between two frontiers the edges are drawn: ``│`` under each
parent's middle, a bus joining a group of parents to its children
(``╰──┬──╯``, ``╭──┴──╮``), and ``▼`` over each child's middle. A group is
drawn only when every parent in it leads to every child, so the drawing
never joins two boxes no edge joins; where the edges cannot be drawn so (an
edge that skips a frontier, a frontier that wraps, two groups that would
share a bus cell), one centred connector of its own marks (``╎`` then
``▽``) joins the two frontiers instead: it says the gap's edges are not
drawn, never that its column's boxes are joined (`_edge_rows`). Either way the edges
are exact in each box's parents line and in the ``Dependencies`` section
under the boxes, which lists every edge between two lanes. ``Node details`` then
gives a card to each running or stuck node, and in `/dag` to the highlighted
one: its whole title, category and model, status and output tokens, group and
session. The tree's status column takes the token count too where the row has
room for it. A box
draws no ``?``: a field with no record is left out (a blank line where
neither category nor model is), a node with no title reads ``untitled``, and
an unknown state's glyph is ``◇``.

Every box is one width: as wide as the widest node needs, narrowed to put
each frontier on one row (every line is cut to it with ``…``), and a
frontier that does not fit even then wraps. Under a line or character
budget the boxes give up Node details, then Dependencies; then the tree is
drawn, which nests a node under its dispatcher and draws no edge. So is a
graph whose edges loop, or one too narrow for a box. Widths are terminal
cells: a wide (CJK) character counts 2, and text is folded first so that
what is counted is what is painted. A duration is counted at
`DURATION_CELLS` until it reads wider, so a ticking clock resizes a box only
when its hours gain a digit, one cell from 100 hours (``100h 00m``), and the
duration stays whole.
A box's count is measured as it reads, beside the status as it reads, so it
shows while the line fits and drops out, whole, once a longer duration or
count would not. Once any lane carries a count, a box makes room for one: a
lane bound to a child (one with an `output_tokens` key) needs its status with
a count at a realistic widest (`● Running 59m 59s · ↓999.9k`), within the
same `BOX_INNER_MAX` and the same shrinking to put a frontier on one row; a
graph with no count keeps the widths it always had. The tree's and a card's count are
measured at their widest (`TOKEN_CELLS`), so a growing one never comes and goes.

Every part of a box carries its node's state as its role (``node:running``),
so a painter colours border, title and status by state; the drawing is
the same text without colour. `/dag` passes a `Focus`: each box then opens
with a fold marker, the highlighted one with ``>``, and its role is
``node:selected``.

Choosing a layout tries several drawings. The choice is kept per structure
(node ids, labels, states and edges, never elapsed time but the cells a
status is counted at) and size, so a redraw of the same graph with new
durations lays it out once (`_DECISIONS`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final
import unicodedata

from .dag_core import layer_of
from .hud_text import compact_count, elapsed_text

VIEW_LAYOUTS: Final = ("box", "tree", "header")
NODE_STATES: Final = (
    "root", "waiting", "dispatched", "running", "stuck", "done", "failed", "interrupted", "unknown",
)
UNKNOWN_FIELD: Final = "?"
UNTITLED: Final = "untitled"  # a node's title where the graph records none
# The edges the tree draws as nesting: a child under its dispatcher, an added dag node under where it came from.
NESTING_KINDS: Final = frozenset({"dispatch", "repair", "extend"})
ELAPSED_LIMIT: Final = 10**9  # seconds, about 31 years: a figure past it (or not finite) is not drawn
# The least a duration counts when a line is measured: `59m 59s`, the widest under 100 hours. A wider one counts as
# it reads (`100h 00m`), so a box widens a cell at the 100-hour mark rather than cut it.
DURATION_CELLS: Final = 7
TOKEN_LIMIT: Final = 10**9  # output tokens: a count past it (or not a whole number) is not drawn
TOKEN_CELLS: Final = 6  # a count's width when a line is measured: `999.9M`, the widest under TOKEN_LIMIT
# The realistic widest a box makes room for once a lane carries a count: `● Running 59m 59s · ↓999.9k`.
WIDEST_DURATION_SECONDS: Final = 59 * 60 + 59  # `59m 59s`, the widest duration under an hour
WIDEST_COUNT: Final = 999_900  # `999.9k`, the widest count under a million
DECISION_LIMIT: Final = 64

GAP: Final = 2  # cells between two boxes of a row
BOX_INNER_MIN: Final = 22  # a box's lines are cut down to this many cells, and no further: below it, the tree
BOX_INNER_MAX: Final = 48  # and never drawn wider: a box grows toward its longest title, a PR title's length
BOX_MIN_WIDTH: Final = BOX_INNER_MIN + 4
SECTION_INDENT: Final = "  "
TREE_WIDE_MIN: Final = 72  # below this a tree node takes two lines
TREE_TITLE_MAX: Final = 40
TREE_CATEGORY_MAX: Final = 12  # the category column's width before it grows, with room no status needs, past it
TREE_MODEL_MAX: Final = 24
TREE_MODEL_MIN: Final = 8  # the model column gives way to a wide category down to this, then the title does
TREE_LEAD_ROOM: Final = 16  # cells a tree row keeps past its lead: the branch, the glyph and the start of a title

_L, _R, _U, _D = 1, 2, 4, 8


@dataclass(frozen=True)
class Charset:
    name: str
    lines: Mapping[int, str]
    bends: Mapping[int, str]  # the corners where an edge turns, in place of `lines`' box corners
    arrow: str
    # The one centred connector of a gap whose edges are not drawn: its own marks, so it never reads as the edge a
    # straight `│` over `▼` draws from a parent's middle to a child's.
    undrawn: tuple[str, str]
    glyphs: Mapping[str, str]
    pending: str  # a box's glyph for a waiting node
    unrecorded: str  # a box's glyph for a node whose state has no record (the tree draws `?`)
    left: str  # before a box's parents
    right: str  # between the two ends of a dependency
    dot: str  # before a frontier's label
    repair: str  # before the title of a node added to repair another
    extend: str  # before the title of a node added to extend the run
    separator: str
    written: str  # before a node's output token count
    ellipsis: str
    tee: str
    end: str
    bar: str
    gap: str


UNICODE: Final = Charset(
    name="unicode",
    lines={
        _L | _R: "─", _U | _D: "│", _R | _D: "┌", _L | _D: "┐", _R | _U: "└", _L | _U: "┘",
        _L | _R | _D: "┬", _L | _R | _U: "┴", _U | _D | _R: "├", _U | _D | _L: "┤", _L | _R | _U | _D: "┼",
        _L: "─", _R: "─", _U: "│", _D: "│",
    },
    bends={_R | _D: "╭", _L | _D: "╮", _R | _U: "╰", _L | _U: "╯"},
    arrow="▼",
    undrawn=("╎", "▽"),
    glyphs={
        "root": "◆", "waiting": "·", "dispatched": "◌", "running": "●", "stuck": "!", "done": "✓",
        "failed": "✗", "interrupted": "▪", "unknown": "?",
    },
    pending="○",
    unrecorded="◇",
    left="←",
    right="→",
    dot="·",
    repair="↻",
    extend="+",
    separator=" · ",
    written="↓",
    ellipsis="…",
    tee="├─ ",
    end="└─ ",
    bar="│  ",
    gap="   ",
)
ASCII: Final = Charset(
    name="ascii",
    lines={
        _L | _R: "-", _U | _D: "|", _L: "-", _R: "-", _U: "|", _D: "|",
        **{
            bits: "+"
            for bits in (
                _R | _D, _L | _D, _R | _U, _L | _U, _L | _R | _D, _L | _R | _U, _U | _D | _R, _U | _D | _L,
                _L | _R | _U | _D,
            )
        },
    },
    bends={},
    arrow="v",
    undrawn=(":", "."),
    glyphs={
        "root": "#", "waiting": ".", "dispatched": "o", "running": "*", "stuck": "!", "done": "+",
        "failed": "x", "interrupted": "-", "unknown": "?",
    },
    pending=".",
    unrecorded="<>",
    left="<-",
    right="->",
    dot="-",
    repair="~",
    extend="+",
    separator=" - ",
    written="out ",
    ellipsis="...",
    tee="+- ",
    end="`- ",
    bar="|  ",
    gap="   ",
)
CHARSETS: Final = {UNICODE.name: UNICODE, ASCII.name: ASCII}


@dataclass(frozen=True)
class Segment:
    """Text and what it is. ``level`` places an edge in the drawing (its band, or its depth in the tree), so a
    painter can colour edges by how far down they are; every other role leaves it 0."""

    text: str
    role: str
    level: int = 0


@dataclass(frozen=True)
class View:
    lines: tuple[tuple[Segment, ...], ...]
    layout: str
    hidden_nodes: int = 0
    levels: int = 1  # how many edge levels the drawing has: one more than its deepest edge's level
    boxes: tuple[tuple[str, int, int], ...] = ()  # (node id, first line, last line) per box, in reading order

    def text_lines(self) -> list[str]:
        return ["".join(segment.text for segment in line) for line in self.lines]

    def text(self) -> str:
        return "\n".join(self.text_lines())


# ── text measuring ───────────────────────────────────────────────────────

_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Mn", "Me", "Mc", "Zl", "Zp"})
_BIDI = frozenset(map(chr, (*range(0x202A, 0x202F), *range(0x2066, 0x206A))))


def _droppable(ch: str) -> bool:
    code = ord(ch)
    if ch in _BIDI or 0x1F3FB <= code <= 0x1F3FF or 0x1F1E6 <= code <= 0x1F1FF:
        return True
    if 0x1160 <= code <= 0x11FF or 0xD7B0 <= code <= 0xD7FF or 0xFE00 <= code <= 0xFE0F:
        return True
    return unicodedata.category(ch) in _DROPPED_CATEGORIES


def clean_text(value: object) -> str:
    """One line of paintable text: NFC, whitespace collapsed, every zero-width or control code point dropped.

    What is left is measured one code point at a time (`cells`), which is how
    a terminal paints it: no cluster survives that a terminal would draw as
    one glyph over several code points.
    """
    return _clean(value) if isinstance(value, str) else ""


@lru_cache(maxsize=4096)
def _clean(value: str) -> str:
    text = unicodedata.normalize("NFC", value)
    kept = "".join(" " if ch.isspace() else ch for ch in text if ch.isspace() or not _droppable(ch))
    return " ".join(kept.split())


@lru_cache(maxsize=4096)
def char_cells(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def cells(text: str) -> int:
    return len(text) if text.isascii() else sum(char_cells(ch) for ch in text)


def fit(text: str, width: int, ellipsis: str = "…") -> str:
    """``text`` cut to at most ``width`` cells, ending in ``ellipsis`` when it was cut."""
    if width <= 0:
        return ""
    if cells(text) <= width:
        return text
    room = width - cells(ellipsis)
    if room <= 0:
        return ellipsis[:width]
    kept, used = [], 0
    for ch in text:
        size = char_cells(ch)
        if used + size > room:
            break
        kept.append(ch)
        used += size
    return "".join(kept).rstrip() + ellipsis


def short_model(model: object) -> str:
    """The model as a box names it: provider path dropped, a leading ``claude-`` dropped (``opus-5-5``)."""
    text = clean_text(model)
    if not text or text == UNKNOWN_FIELD:
        return UNKNOWN_FIELD
    text = text.rsplit("/", 1)[-1]
    return text[len("claude-"):] if text.startswith("claude-") and len(text) > len("claude-") else text


# ── node text ────────────────────────────────────────────────────────────


def _state(node: Mapping[str, Any]) -> str:
    state = node.get("state")
    return state if state in NODE_STATES else "unknown"


def _model_text(node: Mapping[str, Any], separator: str) -> str:
    """``opus-5-5 · high`` in a box; the tree passes ``:`` so its facts line keeps one separator per field."""
    model = short_model(node.get("model"))
    effort = clean_text(node.get("effort"))
    return f"{model}{separator}{effort}" if effort and model != UNKNOWN_FIELD else model


def _status_parts(node: Mapping[str, Any]) -> tuple[str, float | None]:
    """The status word and the duration drawn after it, if one is."""
    waits = node.get("waits_on")
    if isinstance(waits, int) and not isinstance(waits, bool) and waits > 0:
        return f"waits on {waits} lane{'' if waits == 1 else 's'}", None
    word = clean_text(node.get("status")) or _state(node)
    elapsed = node.get("elapsed_seconds")
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and 0 <= elapsed < ELAPSED_LIMIT:
        # A parked node's figure is the time since it parked (`delegation_graph._parked_fields`).
        if _state(node) in ("running", "stuck", "done", "failed", "interrupted") or node.get("parked") is True:
            return word, float(elapsed)
    return word, None


def _status_text(node: Mapping[str, Any]) -> str:
    """The status word and its duration: how long it ran, or, for a stuck node, how long it has been stuck and why
    (``stuck 6m 40s: same error``), so a stall is never read as running time."""
    word, elapsed = _status_parts(node)
    if elapsed is None:
        return word
    if _state(node) == "stuck":
        reason = _stuck_reason(word)
        return f"stuck {elapsed_text(elapsed)}" + (f": {reason}" if reason else "")
    return f"{word} {elapsed_text(elapsed)}"


def _tokens_text(node: Mapping[str, Any], charset: Charset) -> str:
    """``↓1.2k``: the output tokens the node's child has written (`output_tokens`), as the agent view counts them;
    "" without a count."""
    count = node.get("output_tokens")
    if not isinstance(count, int) or isinstance(count, bool) or not 0 < count < TOKEN_LIMIT:
        return ""
    return f"{charset.written}{compact_count(count)}"


def _any_count(nodes: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any of ``nodes`` carries a count a drawing would show; boxes make room for one only then."""
    return any(_tokens_text(node, UNICODE) for node in nodes)


def _tokens_room(charset: Charset) -> int:
    """The cells a token count takes after a status, separator included, whatever the count reads."""
    return cells(charset.separator) + cells(charset.written) + TOKEN_CELLS


def _stuck_reason(word: str) -> str:
    return word.removeprefix("stuck").lstrip(":").strip()


def _status_cells(node: Mapping[str, Any]) -> int:
    """The status line's width for measuring: its duration counted at `DURATION_CELLS`, or as it reads where that is
    wider (100 hours and past, `100h 00m`), so neither the status nor a count after it is cut."""
    word, elapsed = _status_parts(node)
    if elapsed is None:
        return cells(word)
    duration = max(DURATION_CELLS, cells(elapsed_text(elapsed)))
    if _state(node) == "stuck":
        reason = _stuck_reason(word)
        return cells("stuck ") + duration + (2 + cells(reason) if reason else 0)
    return cells(word) + 1 + duration


def _title(node: Mapping[str, Any]) -> str:
    return clean_text(node.get("title")) or UNTITLED


def _category(node: Mapping[str, Any]) -> str:
    category = clean_text(node.get("category"))
    if category and category != UNKNOWN_FIELD:
        return category
    # A child Hermes' delegation backend routed has the user's option (or profile) where OMH has no lane.
    label = clean_text(node.get("route_label"))
    return f"@{label}" if label else UNKNOWN_FIELD


STATE_ORDER: Final = (
    "running", "stuck", "failed", "dispatched", "parked", "waiting", "interrupted", "unknown", "done",
)


def header_parts(graph: Mapping[str, Any], charset: Charset = UNICODE) -> tuple[str, str]:
    """``DAG · <name> · N nodes · E edges`` and the state counts, which follow it on one line when they fit.

    The counts are the run's lanes and the edges between them: the `main` root and its dispatch edges are the
    drawing's, not the run's. A count of 1,000 or more has thousands separators.
    """
    lanes = [node for node in _nodes(graph) if _state(node) != "root"]
    edges = _edges(graph, {str(node["id"]) for node in lanes})
    sep = charset.separator
    counts: dict[str, int] = {}
    for node in lanes:
        # A parked node is a waiting one (`delegation_graph._parked_fields`), counted apart as its layer counts it.
        state = "parked" if node.get("parked") is True else _state(node)
        counts[state] = counts.get(state, 0) + 1
    tally = [f"{counts[state]:,} {state}" for state in STATE_ORDER if counts.get(state)]
    hidden = graph.get("hidden_nodes")
    if isinstance(hidden, int) and not isinstance(hidden, bool) and hidden > 0:
        tally.append(f"+{hidden:,} more nodes")
    name = clean_text(graph.get("name")) or "delegation"
    node_word = "node" if len(lanes) == 1 else "nodes"
    edge_word = "edge" if len(edges) == 1 else "edges"
    return sep.join(["DAG", name, f"{len(lanes):,} {node_word}", f"{len(edges):,} {edge_word}"]), sep.join(tally)


def header_text(graph: Mapping[str, Any], charset: Charset = UNICODE) -> str:
    title, tally = header_parts(graph, charset)
    return f"{title}{charset.separator}{tally}" if tally else title


def _header_lines(graph: Mapping[str, Any], width: int, charset: Charset) -> tuple[tuple[Segment, ...], ...]:
    title, tally = header_parts(graph, charset)
    joined = f"{title}{charset.separator}{tally}" if tally else title
    if cells(joined) <= width or not tally:
        return ((Segment(fit(joined, width, charset.ellipsis), "header"),),)
    return (
        (Segment(fit(title, width, charset.ellipsis), "header"),),
        (Segment(fit(tally, width, charset.ellipsis), "header"),),
    )


def _nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = graph.get("nodes")
    seen: set[str] = set()
    nodes: list[Mapping[str, Any]] = []
    for node in raw if isinstance(raw, list) else []:
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id or node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(node)
    return nodes


def _edges(graph: Mapping[str, Any], ids: set[str]) -> list[tuple[str, str]]:
    raw = graph.get("edges")
    seen: set[tuple[str, str]] = set()
    edges: list[tuple[str, str]] = []
    for edge in raw if isinstance(raw, list) else []:
        if not isinstance(edge, Mapping):
            continue
        upper, lower = edge.get("from"), edge.get("to")
        if not isinstance(upper, str) or not isinstance(lower, str) or upper not in ids or lower not in ids:
            continue
        if upper == lower or (upper, lower) in seen:
            continue
        seen.add((upper, lower))
        edges.append((upper, lower))
    return edges


def _order(node: Mapping[str, Any]) -> int:
    value = node.get("order")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# ── the box layout ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Focus:
    """What `/dag` adds to the boxes: the highlighted node, the folded ones, and whether Node details are drawn.

    With a focus every box opens with its fold marker (``[-]``; ``[+]`` for a
    folded box, which is its title line alone) and the highlighted box has
    ``>`` before its title and the accent border. Without one (the
    transcript, `omh hud --graph`) no key acts on the drawing, so it draws
    neither.
    """

    node: str = ""
    folded: frozenset[str] = frozenset()
    details: bool = True


def _layers(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int] | None:
    parents: dict[str, list[str]] = {}
    for upper, lower in edges:
        parents.setdefault(lower, []).append(upper)
    layer, cyclic = layer_of(ids, parents)
    return None if cyclic else {node_id: layer[node_id] for node_id in ids}


@dataclass(frozen=True)
class _Frontiers:
    lanes: Mapping[str, Mapping[str, Any]]  # every node but the root, by id
    rows: list[list[str]]  # the frontiers, first to last, each in drawing order
    layer: Mapping[str, int]
    parents: Mapping[str, list[str]]  # per lane, the lanes it has an edge from, in frontier and drawing order
    edges: list[tuple[str, str, str]]  # (from, to, kind) between lanes, in reading order
    origin: Mapping[str, str]  # a lane added mid-run: "repair" or "extend", from the kind of the edge into it


def _repair_order(
    lanes: Mapping[str, Mapping[str, Any]], pairs: list[tuple[str, str]], kinds: Mapping[tuple[str, str], str],
) -> list[tuple[str, str]]:
    """Edges that only place lanes and are drawn nowhere: what comes after a repaired lane (a lane that depends on it,
    or an extend round its check added) goes below every lane of that lane's repair, which ran first
    (`dag_run.repair`). A lane it dispatched ran during the attempt that failed, and keeps its place. The repair is
    what a repair edge leads to and the lanes under it, up to a lane another repair or an extend added: one a repair
    or extend edge leads to, or an extend round's (`dag_origin`), which has no such edge where it depends on the
    lane that found it."""
    added = {lower for upper, lower in pairs if kinds.get((upper, lower)) in ("repair", "extend")}
    added |= {lane_id for lane_id, lane in lanes.items() if str(lane.get("dag_origin") or "").startswith("extend:")}
    below: dict[str, list[str]] = {}
    for upper, lower in pairs:
        below.setdefault(upper, []).append(lower)
    groups: dict[str, set[str]] = {}
    for upper, lower in pairs:
        if kinds.get((upper, lower)) == "repair":
            group, pending = groups.setdefault(upper, set()), [lower]
            while pending:
                node_id = pending.pop()
                if node_id not in group:
                    group.add(node_id)
                    pending += [kid for kid in below.get(node_id, []) if kid not in added]
    return [(member, dependent) for repaired, group in groups.items() for dependent in below.get(repaired, [])
            if dependent not in group and kinds.get((repaired, dependent)) != "dispatch" for member in sorted(group)]


def _frontiers(graph: Mapping[str, Any]) -> _Frontiers | None:
    """The lanes by frontier: a lane's frontier is its longest path of recorded edges from a lane with none, and a
    lane that comes after a repaired lane sits below that lane's repair (`_repair_order`).

    The root is not a box: what it dispatched has no parent lane and reads
    ``Start node``, and its model is named in the header. None when there is
    no lane, or the edges between lanes loop.
    """
    lanes = {str(node["id"]): node for node in _nodes(graph) if node.get("kind") != "root"}
    if not lanes:
        return None
    ids = list(lanes)
    pairs = _edges(graph, set(ids))
    kinds: dict[tuple[str, str], str] = {}
    for edge in graph.get("edges") if isinstance(graph.get("edges"), list) else []:
        if isinstance(edge, Mapping):
            kinds.setdefault((str(edge.get("from")), str(edge.get("to"))), clean_text(edge.get("kind")))
    order = _repair_order(lanes, pairs, kinds)
    layer = _layers(ids, [*pairs, *order]) if order else None
    if layer is None:  # no repair to place, or placing it would loop: the recorded edges alone
        layer = _layers(ids, pairs)
    if layer is None:
        return None
    rows = [
        sorted((node_id for node_id in ids if layer[node_id] == index), key=lambda i: (_order(lanes[i]), i))
        for index in range(max(layer.values()) + 1)
    ]
    rank = {node_id: (layer[node_id], at) for row in rows for at, node_id in enumerate(row)}
    parents: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for upper, lower in pairs:
        parents[lower].append(upper)
    for listed in parents.values():
        listed.sort(key=rank.__getitem__)
    edges = sorted(((upper, lower, kinds.get((upper, lower), "")) for upper, lower in pairs),
                   key=lambda edge: (rank[edge[0]], rank[edge[1]]))
    origin: dict[str, str] = {}
    for _upper, lower, kind in edges:
        if kind == "repair" or (kind == "extend" and lower not in origin):
            origin[lower] = kind
    return _Frontiers(lanes, rows, layer, parents, edges, origin)


def _glyph(node: Mapping[str, Any], charset: Charset, spinner: str | None) -> str:
    state = _state(node)
    if spinner and state == "running" and charset is UNICODE and cells(spinner) == 1:
        return spinner
    return charset.glyphs.get(state, charset.glyphs["unknown"])


def _box_glyph(node: Mapping[str, Any], charset: Charset, spinner: str | None) -> str:
    """The tree's glyph, but a waiting node's is the hollow ``○`` a box draws for a node not handed out, and an
    unknown one's ``◇``: a box draws no ``?``."""
    state = _state(node)
    if state in ("waiting", "unknown"):
        return charset.pending if state == "waiting" else charset.unrecorded
    return _glyph(node, charset, spinner)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _field_role(text: str, role: str) -> str:
    """A field with no record (`?`) is drawn as unknown, whatever field it is."""
    return "unknown" if text == UNKNOWN_FIELD else role


def _facts(node: Mapping[str, Any], charset: Charset) -> list[Segment]:
    """``quick · glm-5.3-flash:low``: the category, then the model and its effort; a field with no record yet is
    left out (``writing`` for a node no child has taken), and with neither known the line is empty."""
    known = [(text, role) for text, role in ((_category(node), "category"), (_model_text(node, ":"), "model"))
             if text != UNKNOWN_FIELD]
    if not known:
        return []
    pieces = [Segment(known[0][0], known[0][1])]
    for text, role in known[1:]:
        pieces += [Segment(charset.separator, "model"), Segment(text, role)]
    return pieces


def _origin_mark(node_id: str, shape: _Frontiers, charset: Charset) -> str:
    """``↻ `` before a repair's title, ``+ `` before an extend's: where the node came from, in the colour of its state."""
    kind = shape.origin.get(node_id, "")
    return f"{charset.repair} " if kind == "repair" else f"{charset.extend} " if kind == "extend" else ""


def _counted_status_cells(node: Mapping[str, Any], charset: Charset) -> int:
    """The cells a box's status line takes with a count beside it, measured at a realistic widest: the node's own
    status word with `59m 59s` and `↓999.9k` (`● Running 59m 59s · ↓999.9k`)."""
    widest = {**node, "elapsed_seconds": WIDEST_DURATION_SECONDS, "output_tokens": WIDEST_COUNT}
    status = f"{_box_glyph(node, charset, None)} {_capital(_status_text(widest))}"
    return cells(f"{status}{charset.separator}{_tokens_text(widest, charset)}")


def _box_natural(
    node_id: str, shape: _Frontiers, charset: Charset, focus: Focus | None, counted: bool = False,
) -> int:
    """The inner width a box needs for its title, facts and status (`_status_cells`); the parents line
    is cut to the box (the Dependencies section holds every edge whole). A folded box's one line holds its glyph
    and its status word too. With ``counted`` (some lane carries a count), a lane bound to a child also needs its
    status with a count at its widest (`_counted_status_cells`)."""
    node = shape.lanes[node_id]
    glyph = cells(_box_glyph(node, charset, None)) + 1
    lead = 0
    if focus is not None:
        lead = cells("[-] > ")
        if node_id in focus.folded:
            lead += glyph + cells(charset.separator) + cells(_capital(_status_parts(node)[0]))
    status = glyph + _status_cells(node)
    if counted and "output_tokens" in node:
        status = max(status, _counted_status_cells(node, charset))
    facts = sum(cells(segment.text) for segment in _facts(node, charset))
    return max(lead + cells(_origin_mark(node_id, shape, charset)) + cells(_title(node)), status, facts)


def _middle_cut(text: str, width: int, ellipsis: str) -> str:
    """``text`` in ``width`` cells, cut in the middle at word boundaries: its start, `` … ``, then its end, so the
    part that tells two titles apart (`#58281 · part 3`, `(chat_name upstream sync)`) stays. Whole when it fits;
    cut at its end (`fit`) where no word boundary leaves both halves a word."""
    if cells(text) <= width:
        return text
    joint = f" {ellipsis} "
    room = width - cells(joint)
    if room < 8:
        return fit(text, max(width, 1), ellipsis)
    head_room = room - room * 2 // 5
    head = ""
    for char in text:
        if cells(head + char) > head_room:
            break
        head += char
    head = head[: head.rfind(" ")] if " " in head[len(head) // 2:] else head
    tail = ""
    for char in reversed(text[len(head):]):
        if cells(tail) + cells(char) > room - cells(head):
            break
        tail = char + tail
    tail = tail[tail.find(" ") + 1:] if " " in tail[: len(tail) // 2 + 1] else tail
    head, tail = head.rstrip(" ,;:·-—("), tail.lstrip(" ·")
    if not head or not tail:
        return fit(text, max(width, 1), ellipsis)
    return f"{head}{joint}{tail}"


def _box_content(
    node_id: str, shape: _Frontiers, charset: Charset, inner: int, focus: Focus | None, spinner: str | None,
) -> list[tuple[Segment, ...]]:
    """A box's lines: its title; category and model; its status; its parents."""
    node = shape.lanes[node_id]
    state = _state(node)
    glyph = _box_glyph(node, charset, spinner)
    folded = focus is not None and node_id in focus.folded
    selected = focus is not None and focus.node == node_id
    title = _title(node)
    named = "selected" if selected else state
    head: list[Segment] = []
    if focus is not None:
        head += [Segment("[+] " if folded else "[-] ", "fold")]
        if selected:
            head += [Segment(">", "node:selected"), Segment(" ", "")]
    if folded:
        head += [Segment(glyph, f"node:{state}"), Segment(" ", "")]
    head.append(Segment(_origin_mark(node_id, shape, charset), f"node-title:{named}"))
    title_role = "unknown" if title == UNTITLED else f"node-title:{named}"
    if folded:
        # One line: the title gives way so the status word (`Accepted`) stays, as every state keeps its word.
        word = [Segment(charset.separator, "parents"), Segment(_capital(_status_parts(node)[0]), f"node-word:{state}")]
        room = inner - sum(cells(segment.text) for segment in (*head, *word))
        head.append(Segment(fit(title, max(room, cells(charset.ellipsis) + 1), charset.ellipsis), title_role))
        return [_fit_pieces([*head, *word], inner, charset)]
    room = inner - sum(cells(segment.text) for segment in head)
    head.append(Segment(_middle_cut(title, room, charset.ellipsis) if cells(title) > room else title, title_role))
    lines = [head, _facts(node, charset)]
    status = [Segment(glyph, f"node:{state}"), Segment(" " + _capital(_status_text(node)), f"node-word:{state}")]
    tokens = f"{charset.separator}{_tokens_text(node, charset)}" if _tokens_text(node, charset) else ""
    # While the status line as it reads, with the count, fits the box whole: the box is never widened for it, so a
    # count shows in the narrowest box while its line is short, and drops out, never cut, once the line is not.
    if tokens and sum(cells(segment.text) for segment in status) + cells(tokens) <= inner:
        status.append(Segment(tokens, "more"))
    lines.append(status)
    parents = [_title(shape.lanes[upper]) for upper in shape.parents[node_id]]
    if parents:
        lines.append([Segment(f"{charset.left} ", "parents"), Segment(", ".join(parents), "parents")])
    else:
        lines.append([Segment("Start node", "parents")])
    return [_fit_pieces(line, inner, charset) for line in lines]


def _framed(content: list[tuple[Segment, ...]], inner: int, border: str, charset: Charset) -> list[list[Segment]]:
    """``content`` in a box ``inner + 4`` cells wide: a border, a space each side, the lines padded to ``inner``."""
    lines, rule = charset.lines, charset.lines[_L | _R] * (inner + 2)
    rows = [[Segment(lines[_R | _D] + rule + lines[_L | _D], border)]]
    for line in content:
        used = sum(cells(segment.text) for segment in line)
        rows.append([
            Segment(lines[_U | _D], border), Segment(" ", ""), *line, Segment(" " * (inner - used + 1), ""),
            Segment(lines[_U | _D], border),
        ])
    rows.append([Segment(lines[_R | _U] + rule + lines[_L | _U], border)])
    return rows


def _fit_pieces(pieces: Sequence[Segment], width: int, charset: Charset) -> tuple[Segment, ...]:
    """``pieces`` cut to ``width`` cells, a cut line always ending in the ellipsis: the first piece that does not
    fit is cut to it (or is it alone), and where too little room is left even for that, the pieces kept before it
    give way, so a line never ends on a separator or an arrow with nothing after it."""
    kept: list[Segment] = []
    used = 0
    for piece in pieces:
        size = cells(piece.text)
        if used + size <= width:
            kept.append(piece)
            used += size
            continue
        room = width - used
        if room >= cells(charset.ellipsis):
            kept.append(Segment(fit(piece.text, room, charset.ellipsis), piece.role, piece.level))
        while kept and room < cells(charset.ellipsis):
            last = kept.pop()
            room += cells(last.text)
            if room >= cells(charset.ellipsis):
                kept.append(Segment(_ending(last.text, room, charset.ellipsis), last.role, last.level))
        break
    return _tidy(kept)


def _ending(text: str, width: int, ellipsis: str) -> str:
    """``text`` cut to end in ``ellipsis`` within ``width`` cells, whether or not it would fit whole."""
    kept, used = [], 0
    for ch in text:
        if used + char_cells(ch) > width - cells(ellipsis):
            break
        kept.append(ch)
        used += char_cells(ch)
    return "".join(kept).rstrip() + ellipsis


def _tidy(pieces: Sequence[Segment]) -> tuple[Segment, ...]:
    """One line: neighbouring pieces of one role and level joined, nothing painted after its last character."""
    joined: list[Segment] = []
    for piece in pieces:
        if not piece.text:
            continue
        if joined and (joined[-1].role, joined[-1].level) == (piece.role, piece.level):
            joined[-1] = Segment(joined[-1].text + piece.text, piece.role, piece.level)
        else:
            joined.append(piece)
    while joined and not joined[-1].text.strip():
        joined.pop()
    if joined:
        joined[-1] = Segment(joined[-1].text.rstrip(), joined[-1].role, joined[-1].level)
    return tuple(joined)


def _run_state(lanes: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    """The run's word and the state it is painted as: running while a lane is out, else waiting, else settled.

    A run whose unsettled lanes only lost their news (unknown) ended without a failure or a cancel, so it is
    painted as unknown, never in the error colour.
    """
    states = {_state(node) for node in lanes}
    if states & {"running", "stuck", "dispatched"}:
        return "Running", "running"
    if "waiting" in states:
        return "Waiting", "waiting"
    if "failed" in states:
        return "Failed", "failed"
    if states <= {"done"}:
        return "Completed", "done"
    return ("Ended", "interrupted") if "interrupted" in states else ("Ended", "unknown")


def _box_header(graph: Mapping[str, Any], shape: _Frontiers, width: int, charset: Charset) -> list[tuple[Segment, ...]]:
    """``OMH / DAG · 5 tasks``; the run's name, ``1/1`` and main's model; ``Running · Done 1/5``."""
    sep = charset.separator
    lanes = list(shape.lanes.values())
    hidden = graph.get("hidden_nodes")
    hidden = hidden if isinstance(hidden, int) and not isinstance(hidden, bool) and hidden > 0 else 0
    total = len(lanes) + hidden
    first = [Segment(f"OMH / DAG{sep}{total} task{'' if total == 1 else 's'}", "header")]
    second = [Segment(clean_text(graph.get("name")) or "delegation", "title"), Segment(f"{sep}1/1", "header")]
    root = next((node for node in _nodes(graph) if node.get("kind") == "root"), None)
    model = _model_text(root, ":") if root is not None and clean_text(root.get("model")) else UNKNOWN_FIELD
    if model != UNKNOWN_FIELD:
        second += [Segment(f"{sep}main ", "header"), Segment(model, "model")]
    word, state = _run_state(lanes)
    done = sum(1 for node in lanes if _state(node) == "done")
    third = [Segment(word, f"node-word:{state}"), Segment(f"{sep}Done {done}/{len(lanes)}", "header")]
    for alarm in ("failed", "stuck"):
        count = sum(1 for node in lanes if _state(node) == alarm)
        if count:
            third += [Segment(sep, "header"), Segment(f"{count} {alarm}", f"node-word:{alarm}")]
    if hidden:
        third.append(Segment(f"{sep}+{hidden} more node{'' if hidden == 1 else 's'}", "more"))
    return [_fit_pieces(line, width, charset) for line in (first, second, third)]


def _dependencies(shape: _Frontiers, width: int, charset: Charset) -> list[tuple[Segment, ...]]:
    """Every edge between lanes as text, ``Export API → Export button``, its kind named unless it is a
    `depends_on`: where the boxes draw one centred connector for a frontier gap (`_edge_rows`), this is where its
    edges are exact."""
    lines: list[tuple[Segment, ...]] = [(), (Segment("Dependencies", "header"),)]
    arrow = f" {charset.right} "
    for upper, lower, kind in shape.edges:
        source, target = _title(shape.lanes[upper]), _title(shape.lanes[lower])
        suffix = f" ({kind})" if kind and kind != "depends_on" else ""
        room = width - cells(SECTION_INDENT) - cells(arrow) - cells(suffix)
        if cells(source) + cells(target) > room:
            # The kind stays whole and the titles give way, the target first, each keeping a few cells.
            keep = cells(charset.ellipsis) + 3
            target_room = min(cells(target), max(min(cells(target), keep), room - cells(source)))
            source = fit(source, max(min(cells(source), keep), room - target_room), charset.ellipsis)
            target = fit(target, max(min(cells(target), keep), room - cells(source)), charset.ellipsis)
        pieces = [
            Segment(SECTION_INDENT, ""), Segment(source, "dependency"), Segment(arrow, "connector"),
            Segment(target, "dependency"),
        ]
        if suffix:
            pieces.append(Segment(suffix, "parents"))
        lines.append(_fit_pieces(pieces, width, charset))
    return lines


def _wrap(text: str, width: int, limit: int, charset: Charset) -> list[str]:
    """``text`` in lines of at most ``width`` cells, broken between words; past ``limit`` lines the last is cut."""
    lines: list[str] = []
    for word in text.split(" "):
        if lines and cells(f"{lines[-1]} {word}") <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    if len(lines) > limit:
        lines = [*lines[:limit - 1], " ".join(lines[limit - 1:])]
    return [fit(line, width, charset.ellipsis) for line in lines]


def _details(
    shape: _Frontiers, order: Sequence[str], width: int, charset: Charset, focus: Focus | None, spinner: str | None
) -> list[tuple[Segment, ...]]:
    """One card per running or stuck node, and the highlighted one: its whole title, category and model, status,
    output tokens, and the group and session the graph names for it. The graph holds no reply text and no turn or
    tool counts, so a card shows none of those."""
    shown = [
        node_id for node_id in order
        if _state(shape.lanes[node_id]) in ("running", "stuck") or (focus is not None and focus.node == node_id)
    ]
    if not shown:
        return []
    lines: list[tuple[Segment, ...]] = [(), (Segment("Node details", "header"),)]
    deeper = SECTION_INDENT * 2
    for node_id in shown:
        node = shape.lanes[node_id]
        state = _state(node)
        glyph = _box_glyph(node, charset, spinner)
        lead = SECTION_INDENT + glyph + " "
        title = _title(node)
        for at, text in enumerate(_wrap(title, max(1, width - cells(lead)), 3, charset)):
            pieces = [Segment(SECTION_INDENT, ""), Segment(glyph, f"node:{state}"), Segment(" ", "")] if at == 0 else [
                Segment(" " * cells(lead), "")]
            role = "unknown" if title == UNTITLED else f"node-title:{state}"
            lines.append(_fit_pieces([*pieces, Segment(text, role)], width, charset))
        facts = _facts(node, charset)
        if facts:
            lines.append(_fit_pieces([Segment(deeper, ""), *facts], width, charset))
        where = [Segment(_capital(_status_text(node)), f"node-word:{state}")]
        tokens = _tokens_text(node, charset)
        group = _group_label(node.get("group"), charset)
        tail = clean_text(node.get("session_tail"))
        # Whole or not at all, after the status and before the group and session, which give way first: with one of
        # them after it, the room keeps a cell for the ellipsis their cut ends in, which `_fit_pieces` would
        # otherwise take from the count's own unit (`↓999.9k token…`).
        after = cells(charset.ellipsis) if group or tail else 0
        if tokens and cells(deeper) + _status_cells(node) + _tokens_room(charset) + cells(" tokens") + after <= width:
            where.append(Segment(f"{charset.separator}{tokens} tokens", "more"))
        if group:
            where.append(Segment(f"{charset.separator}{group}", "more"))
        if tail:
            where.append(Segment(f"{charset.separator}session {tail}", "more"))
        lines.append(_fit_pieces([Segment(deeper, ""), *where], width, charset))
    return lines


def _edge_rows(
    shape: _Frontiers, upper: int, middle: Mapping[str, int], charset: Charset,
) -> list[tuple[Segment, ...]] | None:
    """The edges from frontier ``upper`` to the next, drawn as they are: ``│`` under each parent's middle, a bus that
    joins one group of parents to its children (``╰──┬──╯``, ``╭──┴──╮``), and ``▼`` over each child's middle.

    A group is the parents and children its edges connect, and it is drawn
    only when every parent in it leads to every child, so a bus never joins
    two boxes no edge joins. None, and the one centred connector is drawn
    in its own marks (``╎`` over ``▽``, `Charset.undrawn`, which read as no
    edge), where the gap holds no edge, an edge into or out of it skips a
    frontier, either frontier wraps (it has no single row to draw to), a
    group is not every parent to every child, or two groups' buses would
    share a cell.
    Each group is dim, and blue where a child of it runs.
    """
    crossing = [(source, target) for source, target, _kind in shape.edges
                if shape.layer[source] <= upper < shape.layer[target]]
    if not crossing or any(shape.layer[source] != upper or shape.layer[target] != upper + 1
                           or source not in middle or target not in middle for source, target in crossing):
        return None
    groups: list[tuple[set[str], set[str], int]] = []  # parents, children, edges
    for source, target in crossing:
        joined = [group for group in groups if source in group[0] or target in group[1]]
        parents, children, count = {source}, {target}, 1
        for group in joined:
            parents, children, count = parents | group[0], children | group[1], count + group[2]
            groups.remove(group)
        groups.append((parents, children, count))
    drawn: list[tuple[int, int, set[int], set[int], str]] = []  # first cell, last cell, parents', children's, role
    for parents, children, count in groups:
        if count != len(parents) * len(children):
            return None
        tops, bottoms = {middle[node_id] for node_id in parents}, {middle[node_id] for node_id in children}
        running = any(_state(shape.lanes[node_id]) == "running" for node_id in children)
        drawn.append((min(tops | bottoms), max(tops | bottoms), tops, bottoms,
                      "connector:running" if running else "connector"))
    drawn.sort()
    if any(earlier[1] >= later[0] for earlier, later in zip(drawn, drawn[1:])):
        return None

    def row(marks: dict[int, tuple[str, str]]) -> tuple[Segment, ...]:
        pieces, at = [], 0
        for cell in sorted(marks):
            mark, role = marks[cell]
            pieces += [Segment(" " * (cell - at), ""), Segment(mark, role)]
            at = cell + 1
        return _tidy(pieces)

    bar = charset.lines[_U | _D]
    stubs = {cell: (bar, role) for _first, _last, tops, _bottoms, role in drawn for cell in tops}
    arrows = {cell: (charset.arrow, role) for _first, _last, _tops, bottoms, role in drawn for cell in bottoms}
    bus: dict[int, tuple[str, str]] = {}
    for first, last, tops, bottoms, role in drawn:
        for cell in range(first, last + 1):
            bits = ((_U if cell in tops else 0) | (_D if cell in bottoms else 0)
                    | (_L if cell > first else 0) | (_R if cell < last else 0))
            bus[cell] = (charset.bends.get(bits) or charset.lines[bits], role)
    if all(first == last for first, last, *_rest in drawn):
        return [row(stubs), row(arrows)]  # every edge is straight down: no bus to draw
    return [row(stubs), row(bus), row(arrows)]


@dataclass(frozen=True)
class _Boxes:
    lines: list[tuple[Segment, ...]]
    boxes: tuple[tuple[str, int, int], ...]


def _box_view(
    graph: Mapping[str, Any], width: int, charset: Charset, *, sections: int = 2, focus: Focus | None = None,
    spinner: str | None = None,
) -> _Boxes | None:
    """The header, the frontiers of boxes, then (``sections`` 1 and up) Dependencies and (2) Node details.

    Every box is one width: as wide as the widest lane needs (with room for
    a count once any lane carries one, `_box_natural`), up to
    `BOX_INNER_MAX`, and narrower where that puts a frontier on one row,
    down to `BOX_INNER_MIN` (each line cut to it with the ellipsis). A
    frontier that does not fit one row even then wraps, at that same width.
    Where one box does not fit `BOX_INNER_MIN`, None, and the tree is drawn.
    """
    shape = _frontiers(graph)
    if shape is None:
        return None
    counted = _any_count(shape.lanes.values())
    natural = max(_box_natural(node_id, shape, charset, focus, counted) for node_id in shape.lanes)
    one_row = [(width - (len(row) - 1) * GAP) // len(row) - 4 for row in shape.rows]
    inner = min([max(natural, BOX_INNER_MIN), BOX_INNER_MAX, width - 4,
                 *(fit for fit in one_row if fit >= BOX_INNER_MIN)])
    if inner < BOX_INNER_MIN:
        return None
    box_width = inner + 4
    per_row = max(1, (width + GAP) // (box_width + GAP))
    widest = min(per_row, max(len(row) for row in shape.rows))
    span = widest * box_width + (widest - 1) * GAP
    connector = (span - box_width) // 2 + box_width // 2  # under a lone box's middle, and every row is centred
    lines = [*_box_header(graph, shape, width, charset), ()]
    boxes: list[tuple[str, int, int]] = []
    order: list[str] = []
    middle: dict[str, int] = {}  # the cell under each box's middle, in a frontier drawn on one row
    for frontier in shape.rows:
        if len(frontier) <= per_row:
            left = (span - len(frontier) * (box_width + GAP) + GAP) // 2 + box_width // 2
            middle.update((node_id, left + at * (box_width + GAP)) for at, node_id in enumerate(frontier))
    for index, frontier in enumerate(shape.rows):
        # A frontier is centred; one that wraps keeps the column its first row starts at, so it reads as one grid.
        offset = (span - min(per_row, len(frontier)) * (box_width + GAP) + GAP) // 2
        for start in range(0, len(frontier), per_row):
            row = frontier[start:start + per_row]
            drawn = [
                _framed(_box_content(node_id, shape, charset, inner, focus, spinner), inner,
                        "node:selected" if focus is not None and focus.node == node_id
                        else f"node:{_state(shape.lanes[node_id])}", charset)
                for node_id in row
            ]
            top = len(lines)
            for node_id, box in zip(row, drawn):
                boxes.append((node_id, top, top + len(box) - 1))
                order.append(node_id)
            for at in range(max(len(box) for box in drawn)):
                pieces = [Segment(" " * offset, "")]
                for column, box in enumerate(drawn):
                    pieces += [Segment(" " * GAP, "")] if column else []
                    pieces += box[at] if at < len(box) else [Segment(" " * box_width, "")]
                lines.append(_tidy(pieces))
        if len(frontier) > 1:
            lines.append(_tidy([Segment(" " * offset, ""), Segment(f"{charset.dot} Same frontier", "frontier")]))
        if index < len(shape.rows) - 1:
            edge_lines = _edge_rows(shape, index, middle, charset)
            if edge_lines is not None:
                lines += edge_lines
                continue
            # Its own marks (`Charset.undrawn`): a straight `│` over `▼` is an edge, and this is none. Dim, and blue
            # where it leads into a frontier with a node running.
            below = {_state(shape.lanes[node_id]) for node_id in shape.rows[index + 1]}
            role = "connector:running" if "running" in below else "connector"
            for mark in charset.undrawn:
                lines.append(_tidy([Segment(" " * connector, ""), Segment(mark, role)]))
    if sections >= 1 and shape.edges:
        lines += _dependencies(shape, width, charset)
    if sections >= 2 and (focus is None or focus.details):
        lines += _details(shape, order, width, charset, focus, spinner)
    if any(cells("".join(segment.text for segment in line)) > width for line in lines):
        return None
    return _Boxes(lines, tuple(boxes))


def _group_label(label: object, charset: Charset) -> str:
    """A group label in this charset: the builder writes ``wave 1 · 14:02``; ASCII draws ``wave 1 - 14:02``."""
    return clean_text(label).replace(UNICODE.separator, charset.separator)


# ── the tree ─────────────────────────────────────────────────────────────


def _tree_structure(graph: Mapping[str, Any]) -> tuple[
    Mapping[str, Any] | None, list[tuple[str, list[str]]], dict[str, list[str]], dict[str, Mapping[str, Any]]
]:
    nodes = _nodes(graph)
    by_id = {str(node["id"]): node for node in nodes}
    root = next((node for node in nodes if node.get("kind") == "root"), None)
    root_id = str(root["id"]) if root else ""
    raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    nested: dict[str, list[str]] = {}
    parent_of: dict[str, str] = {}
    for edge in raw_edges:
        if not isinstance(edge, Mapping) or edge.get("kind") not in NESTING_KINDS:
            continue
        upper, lower = edge.get("from"), edge.get("to")
        if upper in by_id and lower in by_id and upper != root_id and lower not in parent_of and upper != lower:
            parent_of[str(lower)] = str(upper)
    # A parent chain that loops is not drawn as nesting.
    for lower in list(parent_of):
        seen, current = {lower}, parent_of.get(lower)
        while current is not None:
            if current in seen:
                parent_of.pop(lower, None)
                break
            seen.add(current)
            current = parent_of.get(current)
    ordered = sorted((i for i in by_id if i != root_id), key=lambda i: (_order(by_id[i]), i))
    for lower in ordered:
        if lower in parent_of:
            nested.setdefault(parent_of[lower], []).append(lower)
    groups: list[tuple[str, list[str]]] = []
    for node_id in ordered:
        if node_id in parent_of:
            continue
        label = clean_text(by_id[node_id].get("group"))
        for group_label, members in groups:
            if group_label == label:
                members.append(node_id)
                break
        else:
            groups.append((label, [node_id]))
    return root, groups, nested, by_id


def _tree_lines(
    graph: Mapping[str, Any],
    width: int,
    charset: Charset,
    hidden: set[str],
    spinner: str | None,
) -> list[tuple[Segment, ...]]:
    root, groups, nested, by_id = _tree_structure(graph)
    sep = charset.separator
    lines: list[tuple[Segment, ...]] = []
    if root is not None:
        model = f"{sep}{_model_text(root, ':')}" if clean_text(root.get("model")) else ""
        text = fit(f"{charset.glyphs['root']} {_title(root)}{model}", width, charset.ellipsis)
        lines.append((Segment(text, "title"),))
    wide = width >= TREE_WIDE_MIN
    visible_groups = [(label, [m for m in members if m not in hidden]) for label, members in groups]
    visible_groups = [(label, members) for label, members in visible_groups if members]
    labelled = len(visible_groups) > 1 or any(label for label, _members in visible_groups)
    shown = [node for node in by_id if node not in hidden and (root is None or node != str(root["id"]))]
    fields = {node: _tree_fields(by_id[node]) for node in shown}
    title_width = min(TREE_TITLE_MAX, max([cells(_title(by_id[n])) for n in shown] or [12]))
    widest_category = max([cells(category) for category, _model in fields.values()] or [1])
    category_width = min(TREE_CATEGORY_MAX, widest_category)
    model_width = min(TREE_MODEL_MAX, max([cells(model) for _category, model in fields.values()] or [1]))
    deepest = max([_depth(n, nested) for n in shown] or [0])
    base = (cells(charset.tee) if labelled else 0) + cells(charset.tee)
    # Where the title column ends, the same for every depth, so the columns after it line up. Dispatch nesting widens
    # it; a repair or extend row nested deeper pays its indent from its own title, down to 8 cells, so that nesting
    # never takes a status's room on the rows beside it.
    raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    dispatched = {(str(edge.get("from")), str(edge.get("to"))) for edge in raw_edges
                  if isinstance(edge, Mapping) and edge.get("kind") == "dispatch"}
    by_dispatch = {upper: [kid for kid in kids if (upper, kid) in dispatched] for upper, kids in nested.items()}
    dispatch_deepest = max([_depth(n, by_dispatch) for n in shown] or [0])
    title_end = max(base + cells(charset.bar) * dispatch_deepest + 2 + title_width,
                    base + cells(charset.bar) * deepest + 2 + 8)
    room_after = width - title_end - category_width - model_width - 6
    if room_after < 12:
        title_end -= 12 - room_after
        room_after = 12
    # Then the category column grows to the widest category (`unspecified-high` cut to `unspecified…` reads as
    # another category), paid for by room the statuses do not need, then by the model column down to
    # TREE_MODEL_MIN, then by the title column down to 8 cells; never by a status's room, so no status is cut that
    # would have been whole without the widening.
    extra = widest_category - category_width
    if extra:
        needed = max(_status_cells(by_id[node]) for node in shown)
        paid = min(extra, max(0, room_after - needed))
        from_model = min(extra - paid, max(0, model_width - TREE_MODEL_MIN))
        model_width -= from_model
        title_floor = base + cells(charset.bar) * deepest + 2 + 8
        from_title = min(extra - paid - from_model, max(0, title_end - title_floor))
        title_end -= from_title
        category_width += paid + from_model + from_title
    # Room the widest status does not need goes back to the nested repair and extend titles, up to their full width.
    spare = width - title_end - category_width - model_width - 6 - max([12, *(_status_cells(by_id[n]) for n in shown)])
    title_end += max(0, min(spare, base + cells(charset.bar) * deepest + 2 + title_width - title_end))
    step, offset = len(charset.bar), 1 if labelled else 0
    deepest_shown = max(2, (width - TREE_LEAD_ROOM) // step)

    def clamped(lead: str, depth: int) -> str:
        """A lead too deep for the width: its first columns, then the depth as a number in place of the rest."""
        if len(lead) // step <= deepest_shown:
            return lead
        return lead[: (deepest_shown - 1) * step] + f"{min(depth, 10 ** (step - 1) - 1):>{step - 1}} "

    def lead_segments(lead: str) -> list[Segment]:
        """One segment per column of ``lead``: a bar keeps the level of the depth it continues all the way down."""
        return [Segment(lead[at:at + step], "edge", max(0, at // step - offset)) for at in range(0, len(lead), step)]

    def node_lines(node_id: str, lead: str, last: bool, depth: int) -> None:
        node = by_id[node_id]
        state = _state(node)
        glyph = _glyph(node, charset, spinner)
        branch = charset.end if last else charset.tee
        under = lead + (charset.gap if last else charset.bar)
        lead = clamped(lead, depth)
        prefix = lead + branch
        if wide:
            title_room = max(8, title_end - cells(prefix) - cells(glyph) - 1)
            title = fit(_title(node), title_room, charset.ellipsis)
            pad = " " * (title_room - cells(title))
            category, model = _tree_fields(node)
            category = fit(category, category_width, charset.ellipsis)
            model = fit(model, model_width, charset.ellipsis)
            pieces = [
                *lead_segments(lead),
                Segment(branch, "edge", depth),
                Segment(glyph, f"glyph:{state}"),
                Segment(f" {title}{pad}  ", "unknown" if _title(node) == UNTITLED else "title"),
                Segment(_pad(category, category_width) + "  ", _field_role(category, "category")),
                Segment(_pad(model, model_width) + "  ", _field_role(model, "model")),
            ]
            used = sum(cells(piece.text) for piece in pieces)
            pieces.append(Segment(_status_text(node), f"status:{state}"))
            tokens = _tokens_text(node, charset)
            if tokens and used + _status_cells(node) + _tokens_room(charset) <= width:  # never at a status's cost
                pieces.append(Segment(f"{sep}{tokens}", "more"))
            lines.append(_cut_line(pieces, width, charset))
        else:
            title = fit(_title(node), width - cells(prefix) - cells(glyph) - 1, charset.ellipsis)
            lines.append((
                *lead_segments(lead), Segment(branch, "edge", depth), Segment(glyph, f"glyph:{state}"),
                Segment(f" {title}", "unknown" if _title(node) == UNTITLED else "title"),
            ))
            shown_under = clamped(under, depth)
            indent = shown_under + "  "
            (category, model), status = _tree_fields(node), _status_text(node)
            # The status is what a reader came for: the model gives way first when the line is full.
            model_room = width - cells(indent) - cells(category) - cells(status) - 2 * cells(sep)
            whole = cells(indent) + sum(cells(text) + cells(sep) for text in (category, model) if text)
            model = fit(model, max(cells(charset.ellipsis) + 3, model_room), charset.ellipsis) if model else ""
            facts = [*lead_segments(shown_under), Segment("  ", "edge", depth)]
            for text, role in ((category, "category"), (model, "model")):
                if text:  # a field with no record yet is left out with its separator
                    facts += [Segment(text, _field_role(text, role)), Segment(sep, "edge", depth)]
            facts.append(Segment(status, f"status:{state}"))
            tokens = _tokens_text(node, charset)
            if tokens and whole + _status_cells(node) + _tokens_room(charset) <= width:  # the model whole first
                facts.append(Segment(f"{sep}{tokens}", "more"))
            lines.append(_cut_line(facts, width, charset))
        kids = [kid for kid in nested.get(node_id, []) if kid not in hidden]
        for at, kid in enumerate(kids):
            node_lines(kid, under, at == len(kids) - 1, depth + 1)

    # A cut that hid nodes of the last group drawn, and nothing else, is counted under that group; one that hid
    # anything else (a whole group, or part of an earlier one) is counted at the root, after the last group.
    under_last = False
    if hidden and labelled and visible_groups:
        last_members = next(members for label, members in groups if label == visible_groups[-1][0])
        under_last = hidden <= _descendants(last_members, nested)
    for group_at, (label, members) in enumerate(visible_groups):
        group_last = group_at == len(visible_groups) - 1
        cut_here = bool(hidden) and group_last and (under_last or not labelled)
        if labelled:
            label_last = group_last and not (hidden and not under_last)
            prefix = charset.end if label_last else charset.tee
            text = fit(_group_label(label, charset) or "lanes", width - cells(prefix), charset.ellipsis)
            lines.append((Segment(prefix, "edge"), Segment(text, "group")))
            lead = charset.gap if label_last else charset.bar
        else:
            lead = ""
        for at, member in enumerate(members):
            node_lines(member, lead, at == len(members) - 1 and not cut_here, 0)
    if hidden:
        done = sum(1 for node in hidden if _state(by_id[node]) == "done")
        tail = f" ({done} done)" if done else ""
        text = f"+{len(hidden)} more node{'' if len(hidden) == 1 else 's'}{tail}"
        lead = [Segment(charset.gap, "edge")] if under_last else []
        room = width - cells(charset.end) - (cells(charset.gap) if under_last else 0)
        lines.append((*lead, Segment(charset.end, "edge"), Segment(fit(text, room, charset.ellipsis), "more")))
    return lines


def _descendants(members: Sequence[str], nested: Mapping[str, list[str]]) -> set[str]:
    """``members`` and every node nested under them."""
    found: set[str] = set()
    pending = list(members)
    while pending:
        node = pending.pop()
        if node not in found:
            found.add(node)
            pending += nested.get(node, [])
    return found


def _tree_fields(node: Mapping[str, Any]) -> tuple[str, str]:
    """The tree's category and model columns: a field with no record yet is blank, and ``?`` stands in the category
    column only when neither is known, as in a box."""
    category, model = _category(node), _model_text(node, ":")
    if category == UNKNOWN_FIELD and model == UNKNOWN_FIELD:
        return UNKNOWN_FIELD, ""
    return ("" if category == UNKNOWN_FIELD else category), ("" if model == UNKNOWN_FIELD else model)


def _depth(node_id: str, nested: Mapping[str, list[str]]) -> int:
    parents = {kid: upper for upper, kids in nested.items() for kid in kids}
    depth, current, seen = 0, node_id, {node_id}
    while current in parents and parents[current] not in seen:
        current = parents[current]
        seen.add(current)
        depth += 1
    return depth


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - cells(text))


def _cut_line(pieces: list[Segment], width: int, charset: Charset) -> tuple[Segment, ...]:
    kept: list[Segment] = []
    used = 0
    for piece in pieces:
        size = cells(piece.text)
        if used + size <= width:
            kept.append(piece)
            used += size
            continue
        room = width - used
        if room > cells(charset.ellipsis):
            kept.append(Segment(fit(piece.text, room, charset.ellipsis), piece.role, piece.level))
        break
    while kept and not kept[-1].text.strip():
        kept.pop()
    if kept:
        kept[-1] = Segment(kept[-1].text.rstrip(), kept[-1].role, kept[-1].level)
    return tuple(kept)


_HIDE_ORDER: Final = {
    "done": 0, "unknown": 1, "waiting": 2, "dispatched": 3, "interrupted": 4, "failed": 5, "running": 6,
    "stuck": 6,
}


def _hide_candidates(graph: Mapping[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    """Nodes in the order a cap drops them (settled first, oldest first; running and failed last), and the nesting."""
    _root, _groups, nested, by_id = _tree_structure(graph)
    candidates = [node_id for node_id, node in by_id.items() if node.get("kind") != "root"]
    ordered = sorted(
        candidates,
        key=lambda node_id: (_HIDE_ORDER.get(_state(by_id[node_id]), 1), _order(by_id[node_id]), node_id),
    )
    return ordered, nested


# ── entry point ──────────────────────────────────────────────────────────


def render_delegation_view(
    graph: Mapping[str, Any] | None,
    *,
    width: int,
    max_lines: int | None = None,
    max_chars: int | None = None,
    charset: str = "unicode",
    layout: str = "auto",
    spinner: str | None = None,
    focus: Focus | None = None,
) -> View:
    """The best drawing of ``graph`` that fits: boxes with their Dependencies and Node details, else boxes with fewer
    sections, else the tree, else the header alone.

    ``layout`` narrows the choice: ``box`` tries the boxes and ``tree`` only
    the tree; each still falls back to the tree and the header. ``focus`` is `/dag`'s
    highlight, folds and details switch. ``max_chars`` counts the joined text,
    newlines included. Never raises on a malformed graph: what cannot be read
    is left out, and what cannot be laid out is drawn as the tree. A graph
    with no nodes draws nothing.
    """
    chosen = CHARSETS.get(charset, UNICODE)
    safe_width = max(8, int(width)) if isinstance(width, int) and not isinstance(width, bool) else 80
    if not isinstance(graph, Mapping) or not _nodes(graph):
        return View((), "header")
    header = _header_lines(graph, safe_width, chosen)
    # Whether any lane carries a count is part of the key: it changes the boxes' widths (`_box_natural`), so a
    # decision made for a graph before its first count must not be replayed for it after, nor the other way round.
    counted = _any_count(_nodes(graph))
    key = (_structure(graph), counted, safe_width, max_lines, max_chars, chosen.name, layout, spinner, focus)

    def fits(lines: Sequence[tuple[Segment, ...]]) -> bool:
        if max_lines is not None and len(lines) > max_lines:
            return False
        if max_chars is not None:
            size = sum(len("".join(segment.text for segment in line)) for line in lines) + max(0, len(lines) - 1)
            if size > max_chars:
                return False
        return True

    def boxes(sections: int) -> View | None:
        drawn = _box_view(graph, safe_width, chosen, sections=sections, focus=focus, spinner=spinner)
        if drawn is None or not fits(drawn.lines):
            return None
        return View(tuple(drawn.lines), "box", boxes=drawn.boxes)

    def tree(hidden: set[str]) -> View | None:
        body = _tree_lines(graph, safe_width, chosen, hidden, spinner)
        if not fits((*header, *body)):
            return None
        levels = 1 + max((segment.level for line in body for segment in line if segment.role == "edge"), default=0)
        return View((*header, *body), "tree", len(hidden), levels)

    decided = _DECISIONS.get(key)
    if decided is not None:
        kind, detail = decided
        replayed = boxes(detail) if kind == "box" else tree(set(detail)) if kind == "tree" else None
        if replayed is not None:
            return replayed
    view, decision = _choose(graph, safe_width, chosen, header, layout, boxes, tree, fits)
    if len(_DECISIONS) >= DECISION_LIMIT:
        _DECISIONS.pop(next(iter(_DECISIONS)))
    _DECISIONS[key] = decision
    return view


_DECISIONS: dict[tuple[Any, ...], tuple[str, Any]] = {}


def _choose(
    graph: Mapping[str, Any],
    width: int,
    charset: Charset,
    header: tuple[tuple[Segment, ...], ...],
    layout: str,
    boxes: Any,
    tree: Any,
    fits: Any,
) -> tuple[View, tuple[str, Any]]:
    """The drawing `render_delegation_view` returns, and the decision that redraws it.

    Under a budget the boxes give up Node details first, then Dependencies
    (each box still names its parents).
    """
    if width >= BOX_MIN_WIDTH and layout in ("auto", "box"):
        for sections in (2, 1, 0):
            drawn = boxes(sections)
            if drawn is not None:
                return drawn, ("box", sections)
    order = _hide_order(graph)
    whole = tree(set())
    if whole is not None:
        return whole, ("tree", ())
    # Past the first (which adds the `+N more` line), each node hidden takes lines away, so the fewest hidden that
    # fit are found by halving, not one at a time.
    low, high, found = 1, len(order), None
    while low <= high:
        middle = (low + high) // 2
        drawn = tree(set(order[:middle]))
        if drawn is not None:
            found, high = (drawn, middle), middle - 1
        else:
            low = middle + 1
    if found is not None:
        return found[0], ("tree", tuple(sorted(order[:found[1]])))
    candidates = order
    if fits(header):
        return View(header, "header", len(candidates)), ("header", None)
    single = ((Segment(fit(header_text(graph, charset), width, charset.ellipsis), "header"),),)
    return View(single if fits(single) else (), "header", len(candidates)), ("header", None)


def _hide_order(graph: Mapping[str, Any]) -> list[str]:
    """Every node in the order a line budget hides them: a parent only after all of its children."""
    candidates, nested = _hide_candidates(graph)
    hidden: list[str] = []
    gone: set[str] = set()
    while True:
        remaining = [node for node in candidates if node not in gone and all(kid in gone for kid in nested.get(node, []))]
        if not remaining:
            return hidden
        hidden.append(remaining[0])
        gone.add(remaining[0])


def _structure(graph: Mapping[str, Any]) -> tuple[Any, ...]:
    """What a layout depends on: every node's labels and state, the edges, the name; never a duration's value, only
    the cells its status is counted at (`_status_cells`), which move only when a duration's hours gain a digit."""
    nodes = _nodes(graph)
    shape = tuple(
        (
            str(node.get("id")), str(node.get("kind")), clean_text(node.get("title")), clean_text(node.get("category")),
            clean_text(node.get("model")), clean_text(node.get("effort")), _state(node), _status_parts(node)[0],
            _status_parts(node)[1] is not None, _status_cells(node), clean_text(node.get("group")), _order(node),
        )
        for node in nodes
    )
    edges = tuple(_edges(graph, {str(node["id"]) for node in nodes}))
    return shape, edges, clean_text(graph.get("name")), str(graph.get("hidden_nodes"))
