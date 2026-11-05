"""A dag run's live tree under the composer: one header row per node, what its child does now under it, folding.

The owner's ask of 2026-10-22 ("dag 돌면 프롬프트하단은 또 어떻게 뜸? 삼각형 및
탭으로 연관 하위 공백으로 영역 표시"): each node a header row, what that child
is doing indented under it, triangles that fold and unfold, blank rows
between areas.

The rows, top to bottom: the graph's header (`delegation_view.header_text`);
then each layer, a muted label row (`▾ layer 2 · 4 nodes · 2 running`), with
one blank row between two layers when either is open (shut layers stack);
under an open layer, one header row per node, four cells in: `▾` open or `▸`
shut (none on a node with nothing under it), its state glyph in the state's
colour (the running spinner in the running blue), its label in bold (a
running node's in the dag-ulw aura, its band moving through, where the aura
moves: `aura.aura_text`), and
`category · model:effort · status · ↓tokens` muted at the right edge (main's
own fields, `delegation_view._tree_fields`, `_status_text`, `_tokens_text`).
Under an open node, up to `DETAIL_ROWS` rows four cells further in, each led
by a muted `›`: its child's latest tool call (`terminal(gh pr checkout 1)`,
the name in its family's hue), then the newest other line the child sent: a
thinking line or its reply (`Agent.said`), or Hermes' progress line
(`Agent.progress`, the names of its last five calls). A progress line whose
last name is the call the first row already shows gives way to the thinking
or reply line, or, with none, drops that name (`_second_row`). A node
a repair or an extend added hangs under the node it came from, as the tree's
nesting edges say (`delegation_view._tree_structure`), led by `↻ repair N`
(`+ extend`): N is the node's repair cycle (`cycle`, which the graph copies
from the run record), so a second cycle reads `repair 2` once the first
cycle's unaccepted nodes left the drawing; a graph without it counts the
repair edges under the node.

A node's child is the agent whose child session the node names
(`session_tail`), else the newest agent whose goal's `[dag:<run>/<node>]`
marker binds it to the node (`Agent.dag_node`). The roster's other agents
(a helper the parent delegated beside the run; not a lane of this run the
graph no longer draws) close the tree as a group of their own, `other
agents`, each a row like a node's, so the keys reach them as the agent list
did.

Folding. Running, stuck and failed nodes open, and so does a node with one
of them under it (an extend round hangs under the done verification that
found the gap); done, waiting and handed-out ones stay shut. What the person folds or opens (`overrides`) wins. A tree
taller than `cap` rows first shuts the quiet layers (no node running, stuck
or failed), all-done ones first; then, in a layer with work moving, folds its
quiet nodes into one row at the layer's end (`▸ 12 more · 9 waiting · 3
done`); then shuts the open nodes the person did not open, bottom up, except
one with a running or failed node under it. What still does not fit is cut:
the shut all-done layers' rows go first, wherever they stand, so running and
failed nodes keep the rows; then the rows from the bottom, the last row
saying `… N more nodes · ↓ to browse`, with no blank row wasted next to it.
While the tree has the keys (`selected`) the cut is the same, so Down moves
no row, for as long as the highlight is among the rows shown (the last row
then says `below`, or `↑↓ to browse` when it also counts a done layer that
gave way above); past them the rows scroll to the highlight, between
`… N more nodes above` and `… N more nodes below`.

The person's folds belong to one run (`run_key`): the app drops them when
the graph's run changes and when it leaves a session, so a layer shut in one
run never opens shut in the next.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any

from .aura import aura_text
from .markdown import clean_text
from .panels import DAG_INDENT, SPINNER_FRAMES, dag_style
from .session_picker import pointer
from .style import TRUECOLOR, Line, Span
from .subagents import (
    COMPLETED, ENDED, FAILED_STATUSES, INTERRUPTED, LOG_PROGRESS, LOG_THINKING, LOG_TOOL, QUEUED, RUNNING, Agent, LogRow,
    Roster, short_title,
)
from .theme import Theme, kind_style
from .width import cell_width, truncate, truncate_line

OPEN = "▾ "
SHUT = "▸ "
LEAF = "  "
DETAIL_LEAD = "› "
STEP = 4  # cells a node's detail rows and the nodes nested under it sit right of its triangle
DETAIL_ROWS = 2
LAYER_KEY = "layer:"
OTHERS_KEY = "others:"  # the group of the roster's agents no node is bound to; `agent:` + its id for each of them
OTHERS = "other agents"
# An agent's status as a node's state, for a row of the `other agents` group.
AGENT_STATES = {RUNNING: "running", QUEUED: "waiting", INTERRUPTED: "interrupted", COMPLETED: "done", ENDED: "done",
                **{status: "failed" for status in FAILED_STATUSES}}
MORE_KEY = "more:"  # + a layer's label: the row that layer's quiet nodes fold into
OPEN_STATES = frozenset({"running", "stuck", "failed"})  # open by default; a layer holding one is never shut to fit
MIN_TITLE_CELLS = 12
TITLE_CAP = 52  # a node title's cells at most: a PR title's length, with room left for the figure columns
SHORT_LABEL = 24  # a label narrower than this reads with its prompt's first clause after it (`node_title`)
WORD_CUT_SHARE = 7  # tenths of a title's cells a cut at a word boundary keeps at least (`clamp_title`)
FACT_SEPARATOR = " · "
BLANK, YIELDS = "blank", "yields"  # a row's mark for the cut: a blank row; a shut layer whose every node is done


@dataclass
class _Item:
    key: str  # a node's graph id, or `LAYER_KEY` + a layer's label
    depth: int  # 0 a layer, 1 a node of it, 2 and on a node nested under another
    parent: str = ""
    node: Mapping[str, Any] | None = None  # None for a layer
    state: str = ""  # the node's state (`delegation_view` reads it); "" for a layer
    label: str = ""  # a layer's label
    origin: str = ""  # `↻ repair 1` or `+ extend` for a node a repair or an extend added
    kids: list[_Item] = field(default_factory=list)  # a layer's nodes, or the nodes nested under a node
    agent: Agent | None = None
    details: tuple[LogRow, ...] = ()


@dataclass(frozen=True)
class TreeState:
    """What the keys need from the tree as last drawn."""

    order: tuple[str, ...]  # the rows the keys move over, top to bottom; a fold leaves its hidden rows out
    parent: Mapping[str, str]  # each row's parent row: a node's layer or node, a `more` row's layer
    expanded: Mapping[str, bool]
    foldable: frozenset[str]
    first: str  # where Down opens: the first running node, else the first node
    agents: Mapping[str, str] = field(default_factory=dict)  # a node's key -> its child's subagent id
    reveals: Mapping[str, str] = field(default_factory=dict)  # a `more` row -> the first node opening it shows
    rows: tuple[str, ...] = ()  # the key each drawn row selects, top to bottom; "" for a row a click does nothing on


def run_key(graph: Mapping[str, Any]) -> str:
    """Which run `graph` draws: its nodes' `d:<run>` prefixes (an extend keeps them), else its name."""
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    ids = (str(node.get("id")) for node in nodes if isinstance(node, Mapping))
    return " ".join(sorted({node_id.rpartition(":")[0] for node_id in ids if node_id.startswith("d:")})) or (
        f"name:{graph.get('name')}"
    )


def _bound(by_id: Mapping[str, Mapping[str, Any]], roster: Roster) -> dict[str, Agent]:
    """Each node's agent: the one whose child session it names (`session_tail`), else the newest one its goal's
    `[dag:<run>/<node>]` marker bound to it."""
    from ..plugin_bundle.omh.delegation_graph import session_tail

    agents = list(roster.agents.values())
    by_tail = {session_tail(agent.child_session_id): agent for agent in agents if agent.child_session_id}
    by_node = {agent.dag_node: agent for agent in agents if agent.dag_node}
    bound: dict[str, Agent] = {}
    for node_id, node in by_id.items():
        tail = node.get("session_tail")
        agent = by_tail.get(tail) if isinstance(tail, str) and tail else None
        agent = agent or by_node.get(node_id)
        if agent is not None and node.get("kind") != "root":
            bound[node_id] = agent
    return bound


def node_label(graph: Mapping[str, Any], roster: Roster, agent: Agent) -> str:
    """The label of the node `agent` is the child of, as the tree binds them (`_bound`), on one line; "" when no
    node of `graph` is its."""
    from ..plugin_bundle.omh.delegation_view import _tree_structure

    _root, _groups, _nested, by_id = _tree_structure(graph)
    node_id = next((key for key, bound in _bound(by_id, roster).items() if bound is agent), None)
    return " ".join(clean_text(str(by_id[node_id].get("title") or "")).split()) if node_id is not None else ""


def _others(by_id: Mapping[str, Mapping[str, Any]], roster: Roster, bound: set[str]) -> list[Agent]:
    """The roster's agents no node is bound to; a lane of this run the graph no longer draws (a superseded repair
    attempt) is not one of them."""
    runs = {node_id.rpartition(":")[0] for node_id in by_id if node_id.startswith("d:")}
    return [agent for agent in roster.agents.values()
            if agent.subagent_id not in bound and agent.dag_node.rpartition(":")[0] not in runs]


def _second_row(agent: Agent) -> LogRow | None:
    """The newest line besides a call: thinking or reply, or Hermes' progress line, never one that repeats the call
    the first row shows. Hermes joins a progress line's names with ", " (`delegate_tool_progress._flush`)."""
    progress, said, call = agent.progress, agent.said, agent.last_call
    if progress is None or (said is not None and not agent.progress_newest):
        return said or progress
    names = progress.text.split(", ")
    if call is None or names[-1] != call.text:
        return progress
    if said is not None:
        return said
    rest = ", ".join(names[:-1])
    return LogRow(LOG_PROGRESS, rest) if rest else None


def _details(agent: Agent | None) -> tuple[LogRow, ...]:
    if agent is None:
        return ()
    return tuple(row for row in (agent.last_call, _second_row(agent)) if row is not None)[:DETAIL_ROWS]


def _agent_node(agent: Agent, now: float) -> dict[str, Any]:
    """An agent no node is bound to, as a node row draws one: its short title, model, status, time and tokens."""
    state = AGENT_STATES.get(agent.status, "unknown")
    return {"id": f"agent:{agent.subagent_id}", "kind": "lane", "title": short_title(agent.goal) or agent.name,
            "category": "", "model": agent.model or "?", "effort": "", "state": state, "status": state,
            "elapsed_seconds": agent.elapsed(now), "output_tokens": agent.output_tokens}


def _items(graph: Mapping[str, Any], roster: Roster, now: float) -> list[_Item]:
    from ..plugin_bundle.omh.delegation_view import _state, _tree_structure

    _root, groups, nested, by_id = _tree_structure(graph)
    agents = _bound(by_id, roster)
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    kinds = {(edge.get("from"), edge.get("to")): edge.get("kind") for edge in edges if isinstance(edge, Mapping)}

    def node_item(node_id: str, depth: int, parent: str, origin: str = "") -> _Item:
        agent = agents.get(node_id)
        item = _Item(node_id, depth, parent, by_id[node_id], _state(by_id[node_id]), origin=origin, agent=agent,
                     details=_details(agent))
        repairs = 0
        for kid in nested.get(node_id, []):
            kind = kinds.get((node_id, kid))
            repairs += kind == "repair"
            cycle = by_id[kid].get("cycle")
            number = cycle if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle > 0 else repairs
            mark = f"↻ repair {number}" if kind == "repair" else "+ extend" if kind == "extend" else ""
            item.kids.append(node_item(kid, depth + 1, node_id, mark))
        return item

    layers = []
    for label, members in groups:
        key = f"{LAYER_KEY}{label}"
        layer = _Item(key, 0, label=label)
        layer.kids = [node_item(member, 1, key) for member in members]
        layers.append(layer)
    hidden = graph.get("hidden_by_group") if isinstance(graph.get("hidden_by_group"), Mapping) else {}
    order = graph.get("group_order") if isinstance(graph.get("group_order"), list) else []
    drawn = {layer.label for layer in layers}
    emptied = [label for label in order if isinstance(label, str) and label not in drawn and hidden.get(label)]
    if emptied:  # a layer the graph reader's cap emptied keeps its row (`▸ layer 4 · 0 of 161 nodes`), in its place
        rank = {label: at for at, label in enumerate(order)}
        layers += [_Item(f"{LAYER_KEY}{label}", 0, label=label) for label in emptied]
        layers.sort(key=lambda layer: rank.get(layer.label, len(rank)))
    others = _others(by_id, roster, {agent.subagent_id for agent in agents.values()})
    if others:
        group = _Item(OTHERS_KEY, 0, label=OTHERS)
        for agent in others:
            node = _agent_node(agent, now)
            group.kids.append(
                _Item(node["id"], 1, OTHERS_KEY, node, node["state"], agent=agent, details=_details(agent))
            )
        layers.append(group)
    return layers


def _walk(items: Sequence[_Item]) -> list[_Item]:
    found: list[_Item] = []
    for item in items:
        found += [item, *_walk(item.kids)]
    return found


def _foldable(item: _Item) -> bool:
    return bool(item.kids or item.details)


def _active(item: _Item) -> bool:
    """Whether a running, stuck or failed node is the item or under it."""
    return any(each.state in OPEN_STATES for each in _walk([item]))


def _quiet(layer: _Item) -> list[_Item]:
    """A layer's nodes with nothing running or failed in them: what folds into its `more` row."""
    return [item for item in layer.kids if not _active(item)]


def _specs(layers: Sequence[_Item], expanded: Mapping[str, bool]) -> list[tuple[str, _Item | None, Any]]:
    """The rows as (kind, item, detail) before they are drawn: `header`, `blank`, `layer`, `node`, `detail` (its log
    row), and `more` (its layer's folded nodes)."""
    specs: list[tuple[str, _Item | None, Any]] = [("header", None, None)]

    def node_specs(item: _Item) -> None:
        specs.append(("node", item, None))
        if expanded.get(item.key):
            specs.extend(("detail", item, row) for row in item.details)
            for kid in item.kids:
                node_specs(kid)

    labelled = len(layers) > 1 or any(layer.label for layer in layers)  # one unnamed group draws no label row
    for at, layer in enumerate(layers):
        if at and (expanded.get(layer.key) or expanded.get(layers[at - 1].key)):  # shut layers stack as one list
            specs.append(("blank", None, None))
        if labelled:
            specs.append(("layer", layer, None))
        if expanded.get(layer.key) or not labelled:
            folded = [] if expanded.get(MORE_KEY + layer.label, True) else _quiet(layer)
            for item in layer.kids:
                if item not in folded:
                    node_specs(item)
            if folded:
                specs.append(("more", layer, folded))
    return specs


def _fitted(layers: Sequence[_Item], overrides: Mapping[str, bool], cap: int) -> dict[str, bool]:
    """Which rows are open: by state, then the person's folds, then shut to fit `cap` rows (the module says how)."""
    every = _walk(layers)
    # Open by default: a layer, a running, stuck or failed node, and one with such a node under it (an extend round
    # hangs under the verification that found the gap, done itself).
    expanded = {
        item.key: _foldable(item) and overrides.get(item.key, item.node is None or _active(item))
        for item in every
    }
    expanded.update({MORE_KEY + layer.label: overrides.get(MORE_KEY + layer.label, True) for layer in layers})

    def fits() -> bool:
        return len(_specs(layers, expanded)) <= cap

    if fits():
        return expanded
    labelled = len(layers) > 1 or any(layer.label for layer in layers)
    quiet = [layer for layer in layers if labelled and layer.key not in overrides and expanded[layer.key]
             and not _active(layer)]
    quiet.sort(key=lambda layer: not all(item.state == "done" for item in _walk(layer.kids)))  # all-done ones first
    for layer in quiet:
        expanded[layer.key] = False
        if fits():
            return expanded
    for layer in layers:
        key = MORE_KEY + layer.label
        if key not in overrides and (expanded[layer.key] or not labelled) and _active(layer) and len(_quiet(layer)) > 1:
            expanded[key] = False
            if fits():
                return expanded
    for item in reversed([item for item in every if item.node is not None]):
        # A node over a running repair stays open: shutting it would hide work that moves.
        if item.key not in overrides and expanded[item.key] and not any(_active(kid) for kid in item.kids):
            expanded[item.key] = False
            if fits():
                return expanded
    return expanded


def _figure_parts(node: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """The header's figures as columns: category, model:effort, status, ↓tokens ("" where the node has none)."""
    from ..plugin_bundle.omh.delegation_view import UNICODE, _status_text, _tokens_text, _tree_fields

    category, model = _tree_fields(node)
    return category, model, _status_text(node), _tokens_text(node, UNICODE)


def clamp_title(text: str, cells: int) -> str:
    """`text` whole when it fits `cells`, else cut at its last word boundary and closed with "…"; a long token that
    would leave less than `WORD_CUT_SHARE` tenths of the cells is cut itself, never mid-word without the "…"."""
    if cell_width(text) <= cells:
        return text
    cut = truncate(text, max(cells - 1, 1), ellipsis="")
    space = cut.rfind(" ")
    # The cut ends inside a word: back to its start, unless that leaves less than `WORD_CUT_SHARE` tenths of the
    # cells, as before a long token (a path, a PR list); then the token itself is cut.
    if text[len(cut):len(cut) + 1] != " " and space > 0 and cell_width(cut[:space]) >= cells * WORD_CUT_SHARE // 10:
        cut = cut[:space]
    return cut.rstrip(" ,;:·-—(") + "…"


def node_title(node: Mapping[str, Any]) -> str:
    """The title the tree shows: the node's label, and the first clause of its prompt (`summary`) when the label is
    short, in `TITLE_CAP` cells at most (`clamp_title`)."""
    label = str(node.get("title") or "untitled")
    summary = str(node.get("summary") or "")
    if summary and cell_width(label) < SHORT_LABEL and summary.casefold() not in label.casefold():
        label = f"{label}{FACT_SEPARATOR}{summary}"
    return clamp_title(label, TITLE_CAP)


@dataclass(frozen=True)
class _Columns:
    """Where the node rows' parts go: the title column's width, then which figure columns show and how wide."""

    title: int  # cells from the row's start to the end of the title column
    shown: tuple[int, ...]  # indexes into `_figure_parts`, in order
    widths: tuple[int, ...]  # each shown column's width


def _prefix(item: _Item, expanded: bool, glyph: str) -> str:
    lead = " " * (len(DAG_INDENT) + 2 + STEP * (item.depth - 1))
    triangle = (OPEN if expanded else SHUT) if _foldable(item) else LEAF
    origin = f"{item.origin}{FACT_SEPARATOR}" if item.origin else ""
    return f"{lead}{triangle}{glyph} {origin}"


def _columns(rows: Sequence[tuple[_Item, bool]], width: int) -> _Columns:
    """The node rows' layout: titles in one column as wide as the widest shown, then the figures as columns each
    padded to its widest value, starting at the same cell on every row. Where they do not fit `width`, whole
    columns go from the right (tokens, then category, then model), and then the titles give way, down to
    `MIN_TITLE_CELLS`."""
    if not rows:
        return _Columns(0, (), ())
    prefixes = [cell_width(_prefix(item, expanded, "•")) for item, expanded in rows]
    titles = [cell_width(node_title(item.node or {})) for item, _expanded in rows]
    parts = [_figure_parts(item.node or {}) for item, _expanded in rows]
    title = max(prefix + text for prefix, text in zip(prefixes, titles))
    for shown in ((0, 1, 2, 3), (0, 1, 2), (1, 2), (2,), ()):
        shown = tuple(index for index in shown if any(part[index] for part in parts))
        widths = tuple(max(cell_width(part[index]) for part in parts) for index in shown)
        block = sum(widths) + cell_width(FACT_SEPARATOR) * max(len(widths) - 1, 0)
        room = width - (2 + block if widths else 0)
        if room >= max(prefixes) + MIN_TITLE_CELLS or not widths:
            return _Columns(min(title, room), shown, widths)
    return _Columns(min(title, width), (), ())


def _node_row(
    item: _Item, expanded: bool, width: int, theme: Theme, frame: int, columns: _Columns, aura: int | None = None,
) -> list[Span]:
    from ..plugin_bundle.omh.delegation_view import UNICODE

    node = item.node or {}
    glyph = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)] if item.state == "running" else UNICODE.glyphs.get(
        item.state, UNICODE.glyphs["unknown"])
    prefix = _prefix(item, expanded, glyph)
    triangle = (OPEN if expanded else SHUT) if _foldable(item) else LEAF
    origin = f"{item.origin}{FACT_SEPARATOR}" if item.origin else ""
    lead = " " * (len(DAG_INDENT) + 2 + STEP * (item.depth - 1))
    room = max(columns.title - cell_width(prefix), 1)
    title = clamp_title(node_title(node), room)
    parts = _figure_parts(node)
    cells_shown = [parts[index] for index in columns.shown]
    while cells_shown and not cells_shown[-1]:
        cells_shown.pop()  # no trailing separator for a column this node has nothing in
    figure = FACT_SEPARATOR.join(
        text + " " * (columns.widths[at] - cell_width(text)) if at < len(cells_shown) - 1 else text
        for at, text in enumerate(cells_shown)
    )
    pad = " " * max(room - cell_width(title), 0)
    shown = (aura_text(title, theme.aura, theme.aura_glint, aura) if aura is not None and item.state == "running"
             else [Span(title, dag_style("title", theme))])
    return [
        Span(lead), Span(triangle, theme.muted), Span(glyph, dag_style(f"glyph:{item.state}", theme)), Span(" "),
        Span(origin, theme.muted), *shown, Span(f"{pad}  {figure}" if figure else "", theme.muted),
    ]


def _detail_row(item: _Item, row: LogRow, theme: Theme) -> list[Span]:
    lead = [Span(" " * (len(DAG_INDENT) + 2 + STEP * item.depth)), Span(DETAIL_LEAD, theme.muted)]
    if row.kind == LOG_TOOL:
        args = f"({row.detail})" if row.detail else ""
        return [*lead, Span(row.text, replace(kind_style(row.text, theme), bold=False)), Span(args, theme.muted)]
    style = theme.thinking if row.kind == LOG_THINKING else theme.muted if row.kind == LOG_PROGRESS else theme.text
    return [*lead, Span(row.text, style)]


def _layer_row(item: _Item, expanded: bool, theme: Theme, hidden: int = 0) -> list[Span]:
    """`▾ layer 2 · 4 nodes · 2 running`; `hidden` nodes the graph reader left out of the layer read as
    `28 of 640 nodes`, so a capped graph's counts are not taken for the layer's."""
    counts: dict[str, int] = {}
    for kid in item.kids:
        word = "running" if kid.state in ("running", "stuck") else kid.state
        word = word if word in ("running", "failed", "done") else "waiting"
        counts[word] = counts.get(word, 0) + 1
    noun = "agent" if item.key == OTHERS_KEY else "node"
    total = len(item.kids) + hidden
    shown = f"{len(item.kids):,} of {total:,}" if hidden else f"{total:,}"
    said = [f"{shown} {noun}{'' if total == 1 else 's'}"]
    said += [f"{counts[word]:,} {word}" for word in ("running", "failed", "waiting", "done") if counts.get(word)]
    return [Span(DAG_INDENT), Span(OPEN if expanded else SHUT, theme.muted),
            Span(FACT_SEPARATOR.join([item.label or "lanes", *said]), theme.muted)]


def _more_row(folded: Sequence[_Item], theme: Theme) -> list[Span]:
    waiting = sum(1 for item in folded if item.state != "done")
    said = [f"{len(folded)} more", *([f"{waiting} waiting"] if waiting else []),
            *([f"{len(folded) - waiting} done"] if len(folded) - waiting else [])]
    return [Span(DAG_INDENT + "  "), Span(SHUT, theme.muted), Span(FACT_SEPARATOR.join(said), theme.muted)]


def _covers(kind: str, item: _Item | None, expanded: Mapping[str, bool], detail: Any = None) -> int:
    """How many nodes a row stands for: a node's header itself and, shut, what is nested under it; a shut layer's
    nodes; a `more` row's."""
    if kind == "more":
        return len(_walk(detail))
    if item is None or kind == "detail":
        return 0
    if kind == "layer":
        return 0 if expanded.get(item.key) else len(_walk(item.kids))
    return 1 if expanded.get(item.key) else len(_walk([item]))


def _more(count: int, where: str, theme: Theme, depth: str) -> Line:
    """A count row: the nodes cut, or, when the rows cut hold no node (the header, a layer's row, a node's detail
    rows), only that there is more."""
    text = f"… {count} more node{'' if count == 1 else 's'}{where}" if count else f"… more{where}"
    return (Span(DAG_INDENT), Span(text, replace(theme.muted, depth=depth)))


def tree_lines(
    graph: Mapping[str, Any],
    roster: Roster,
    width: int,
    cap: int,
    theme: Theme,
    frame: int,
    overrides: Mapping[str, bool],
    selected: str | None,
    depth: str = TRUECOLOR,
    now: float = 0.0,
    aura: int | None = None,
) -> tuple[list[Line], TreeState]:
    """The tree in `cap` rows at most, none wider than `width`, painted at `depth` as the graph is everywhere
    (`style.color_depth`), and what the keys need from it; `selected` (a key of the state's `order`) is the
    row marked with the menus' pointer and drawn in `menu_current` while the tree has the keys, else None. `aura` is the phase a running node's
    title stands at in the dag-ulw aura; None (the aura does not move here) draws it as every title is drawn."""
    from ..plugin_bundle.omh.delegation_view import header_text

    layers = _items(graph, roster, now)
    expanded = _fitted(layers, overrides, cap)
    specs = list(_specs(layers, expanded))
    columns = _columns([(item, expanded[item.key]) for kind, item, _detail in specs if kind == "node" and item], width)
    hidden_by_group = graph.get("hidden_by_group") if isinstance(graph.get("hidden_by_group"), Mapping) else {}
    rows: list[_Row] = []
    for kind, item, detail in specs:
        if kind == "header":
            spans = [Span(DAG_INDENT), Span(header_text(graph), dag_style("header", theme))]
        elif kind == "blank" or item is None:
            spans = []
        elif kind == "layer":
            hidden = hidden_by_group.get(item.label, 0)
            spans = _layer_row(item, expanded[item.key], theme, hidden if isinstance(hidden, int) else 0)
        elif kind == "node":
            spans = _node_row(item, expanded[item.key], width, theme, frame, columns, aura)
        elif kind == "more":
            spans = _more_row(detail, theme)
        else:
            spans = _detail_row(item, detail, theme)
        key = item.key if item is not None and kind in ("layer", "node") else ""
        key = MORE_KEY + item.label if kind == "more" and item is not None else key
        line: Line = tuple(spans)
        if key and key == selected:  # the pointer in the row's indent and the row bold in the accent, as every menu
            text = "".join(span.text for span in spans)
            line = (pointer(True, theme), Span(text.removeprefix(DAG_INDENT), theme.menu_current))
        line = tuple(span if span.style.depth == depth else Span(span.text, replace(span.style, depth=depth))
                     for span in line)
        done = kind == "layer" and item is not None and not expanded[item.key] and all(
            each.state == "done" for each in _walk(item.kids))
        mark = BLANK if kind == "blank" else YIELDS if done else ""
        rows.append((truncate_line(line, width), key, _covers(kind, item, expanded, detail), mark))
    every = _walk(layers)
    order = tuple(key for _line, key, _count, _mark in rows if key)
    shown = [item for item in every if item.node is not None and item.key in order]
    running = [item.key for item in shown if item.state == "running"]
    state = TreeState(
        order=order,
        parent={item.key: item.parent for item in every} | {MORE_KEY + layer.label: layer.key for layer in layers},
        expanded=expanded,
        foldable=frozenset(item.key for item in every if _foldable(item))
        | {MORE_KEY + layer.label for layer in layers if len(_quiet(layer)) > 1},
        first=(running or [item.key for item in shown] or list(order) or [""])[0],
        agents={item.key: item.agent.subagent_id for item in every if item.agent is not None},
        reveals={MORE_KEY + layer.label: _quiet(layer)[0].key for layer in layers if _quiet(layer)},
    )
    shown = _window(rows, cap, selected, partial(_more, theme=theme, depth=depth))
    return [line for line, _key in shown], replace(state, rows=tuple(key for _line, key in shown))


# A row as `_window` cuts it: (line, the key it selects or "", the nodes it stands for, `BLANK`, `YIELDS` or "").
_Row = tuple[Line, str, int, str]


def _counted(rows: Sequence[_Row]) -> int:
    return sum(count for _line, _key, count, _mark in rows)


def _tidy(rows: list[_Row]) -> list[_Row]:
    """`rows` without a blank row that sets nothing apart: one right under the header, after another, or last."""
    kept: list[_Row] = []
    for at, row in enumerate(rows):
        if row[3] == BLANK and (len(kept) == 1 or kept[-1][3] == BLANK or at == len(rows) - 1):
            continue
        kept.append(row)
    return kept


def _first(rows: list[_Row], count: int) -> list[_Row]:
    """The first `count` rows, a blank one last giving way to the row after it: no blank row stands over a cut."""
    shown = rows[:count]
    return shown[:-1] + [rows[count]] if shown[-1][3] == BLANK and len(rows) > count else shown


def _last(rows: list[_Row], count: int) -> list[_Row]:
    """The last `count` rows, a blank one first giving way to the row before it."""
    shown = rows[len(rows) - count :]
    return [rows[len(rows) - count - 1]] + shown[1:] if shown[0][3] == BLANK and len(rows) > count else shown


def _window(rows: list[_Row], cap: int, selected: str | None, more: Callable[..., Line]) -> list[tuple[Line, str]]:
    """`rows` in `cap` rows, each with the key it selects: all of them when they fit. Else the shut all-done layers
    yield first, wherever they stand, with the keys or without (the highlighted row itself never does), so running
    and failed nodes keep the rows and Down moves nothing. Then, without the keys, the rows from the bottom, a last row
    counting what is cut; with them, the same rows while they show the highlight, else the rows around it between
    counts of what is above and below. A count that holds a yielded layer from the other side of it, or from
    between the rows shown, says `↑↓ to browse`. No blank row stands next to a count row: the next row with something on it takes its place."""

    def drawn(cut: Sequence[_Row]) -> list[tuple[Line, str]]:
        return [(line, key) for line, key, _count, _mark in cut]

    if len(rows) <= cap:
        return drawn(rows)
    if cap < 2:
        return drawn(rows[:cap])
    kept = list(rows)
    for row in [row for row in rows if row[3] == YIELDS and row[1] != selected]:
        if len(_tidy(kept)) < cap:  # a row stays for the count
            break
        kept = [each for each in kept if each is not row]
    kept = _tidy(kept)
    total, at = _counted(rows), {id(row): place for place, row in enumerate(rows)}

    def after(row: _Row) -> int:
        """The nodes the rows past `row` stand for, in the whole tree."""
        return sum(each[2] for each in rows[at[id(row)] + 1 :])

    def before(row: _Row) -> int:
        return sum(each[2] for each in rows[: at[id(row)]])

    first = _first(kept, cap - 1)
    if selected is None or cap < 3 or any(row[1] == selected for row in first):  # under 3 rows no highlight fits
        hidden = total - _counted(first)
        where = " · ↓ to browse" if selected is None else " below" if hidden == after(first[-1]) else " · ↑↓ to browse"
        return drawn(first) + [(more(hidden, where), "")]
    index = next((place for place, row in enumerate(kept) if row[1] == selected), 0)
    body = cap - 2
    start = min(max(index - body // 2, 0), len(kept) - body)
    if start + body >= len(kept):
        shown = _last(kept, cap - 1)
        hidden = total - _counted(shown)
        return [(more(hidden, " above" if hidden == before(shown[0]) else " · ↑↓ to browse"), "")] + drawn(shown)
    # A blank row is never the highlight's: one at either end of the window gives way to the row past the other end.
    if kept[start][3] == BLANK and start + body + 1 < len(kept):
        start += 1
    elif kept[start + body - 1][3] == BLANK and start > 1 and index < start + body - 1:
        start -= 1
    shown = kept[start : start + body]
    below = after(shown[-1])
    above = total - _counted(shown) - below  # with a done layer that gave way between the rows shown, as the others say
    where = " above" if above == before(shown[0]) else " · ↑↓ to browse"
    return [(more(above, where), "")] + drawn(shown) + [(more(below, " below"), "")]
