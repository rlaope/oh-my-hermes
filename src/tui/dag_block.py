"""A dag-ulw run's graph printed into the transcript at the moments its plan takes or changes shape.

The live state stays in the panel; this is what the scrollback keeps (owner
decision 2026-10-21). When an `omh_dag` call completes, the transcript gets
one block holding the run's graph, drawn by `delegation_view`'s public entry
with the box layout, which steps down to the tree where boxes do not fit the
width:

* at ``define``: the plan as it starts, its first layer handed out;
* at ``repair`` and ``extend``: the graph with the added nodes, each box
  naming where it came from (its parents line, and the drawing's own marks:
  ``↻`` before a repair's title, ``+`` before an extend round's);
* once at the run's end (done, out of repair cycles, or cancelled): the
  final states. The app prints it when the turn ends and only if the run is
  still over then, so an end the same turn's extend moved on prints nothing.

Never on ``ready``, ``settle`` or ``status`` (a settle that ends the run is
the end moment, not a settle), never twice for one moment, and never on a
messenger: a chat reply carries its three moments and no boxes.

`topology_lines` is the other half of a run's picture: `/dag` closes the
whole graph with the run's critical path and bottlenecks.

The print holds no Dependencies list and no Node details: the arrows draw
every edge, and `/dag` keeps both. A run of up to `SMALL_GRAPH_LANES` lanes
prints every box, at its end too, where the boxes' final states are the
tally. A bigger run prints condensed (`_condensed`): its header, one row per
layer with its counts, the boxes of the frontier the moment changed (the
first layer at ``define``, the added nodes at ``repair`` and ``extend``),
and `… N more nodes · /dag shows the whole graph`; its end is its tally and
the nodes that failed or are stuck. The switch is the lane count, never the
terminal's height: the owner sees a small run's graph whole.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

from .style import Line, Span
from .theme import Theme
from .width import truncate_line

DAG_TOOL = "omh_dag"
END = "end"  # the title an end moment opens with
END_STATES = ("done", "stopped", "cancelled")
# The goal verdicts an end title adds (`dag_run.VERDICTS`, held equal by tests/test_dag_transcript.py).
VERDICTS = ("verified", "unverified", "verify_failed")
INDENT = "  "


@dataclass
class DagBlock:
    title: str  # what the moment is: "plan", "repair · +1 node", "extend · +3 nodes", "end · done"
    graph: Mapping[str, Any]
    done: bool = True
    added: tuple[str, ...] = ()  # the dag node ids a repair or an extend added: the boxes a condensed print draws


def moment(payload: Mapping[str, Any], ended: set[tuple[str, int]]) -> tuple[str, str, list[str]] | None:
    """(title, run, added node ids) when a completed tool call is a print moment, else None.

    ``ended`` holds the run ends already printed, keyed by run and node count,
    so a run's end prints once, and again only after an extend round reopened
    it.
    """
    if str(payload.get("name") or "") != DAG_TOOL:
        return None
    raw = payload.get("result")
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(result, Mapping) or result.get("status") != "ok" or not isinstance(result.get("run"), str):
        return None
    run, action, settled = result["run"], result.get("action"), result.get("settled")
    added = settled.get(f"{action}_nodes") if isinstance(settled, Mapping) else None
    if action == "define" and not result.get("reused"):
        return "plan", run, []
    if action in ("repair", "extend") and isinstance(added, list) and added:
        count = len(added)
        return f"{action} · +{count} node{'' if count == 1 else 's'}", run, [str(node) for node in added]
    state = result.get("state")
    nodes = result.get("nodes") if isinstance(result.get("nodes"), list) else []
    # The end is the settle (or cancel) that ended the run; a later status or ready reading it says nothing new.
    if action in ("settle", "cancel") and state in END_STATES and (run, len(nodes)) not in ended:
        ended.add((run, len(nodes)))
        # The goal verdict the result carries (`dag_run.goal_verdict`): `end · done · unverified`, and for a run with
        # goal criteria how many are met: `end · done · verified · 3/3 criteria met`.
        verdict = result.get("verdict") if result.get("verdict") in VERDICTS else ""
        return " · ".join([END, str(state), *([verdict] if verdict else []), *_criteria_count(result)]), run, []
    return None


def _criteria_count(result: Mapping[str, Any]) -> list[str]:
    """``["2/3 criteria met"]`` from a result's ``criteria`` (`dag_run.criteria_view`), else ``[]``."""
    view = result.get("criteria")
    if not isinstance(view, Mapping):
        return []
    met, total = view.get("met"), view.get("total")
    if isinstance(met, bool) or isinstance(total, bool) or not isinstance(met, int) or not isinstance(total, int):
        return []
    return [f"{met}/{total} criteria met"]


def read_graph(omh_home: str | None, hermes_home: str | None, session: str) -> Mapping[str, Any] | None:
    """The session's active delegation graph, read the way the HUD panel reads it, or None."""
    from ..plugin_bundle.omh.runtime_reader import read_omh_hud

    if not session:
        return None
    payload = read_omh_hud(omh_home, hermes_home, session_ref=session, session_scoped=True,
                           tui_identity_expected=True)
    graph = payload.get("delegation_graph") if isinstance(payload, Mapping) else None
    return graph if isinstance(graph, Mapping) and graph.get("status") == "active" else None


def rows(block: DagBlock, width: int, theme: Theme) -> list[Line]:
    """The block's rows: its moment, then the graph as boxes without Dependencies and Node details, or the tree
    where boxes do not fit ``width``; condensed past `SMALL_GRAPH_LANES` lanes."""
    from ..plugin_bundle.omh.delegation_view import UNICODE, _box_view, render_delegation_view
    from .panels import dag_line

    if _lane_count(block.graph) > SMALL_GRAPH_LANES:
        return _condensed(block, width, theme)
    lines = [truncate_line((Span(f"{INDENT}dag-ulw {block.title}", theme.muted),), width)]
    drawn = _box_view(block.graph, max(8, width - len(INDENT)), UNICODE, sections=0)
    if drawn is not None:
        return lines + [truncate_line((Span(INDENT), *dag_line(row, 1, theme)), width) for row in drawn.lines]
    view = render_delegation_view(block.graph, width=max(8, width - len(INDENT)), layout="tree")
    return lines + [truncate_line((Span(INDENT), *dag_line(row, view.levels, theme)), width) for row in view.lines]


SMALL_GRAPH_LANES = 12  # a run of up to this many lanes prints every box; a bigger one prints condensed
CONDENSED_BOXES = 6  # the frontier boxes a condensed print draws at most
CONDENSED_FAILURES = 8  # the failed or stuck nodes a condensed end lists at most
MORE_NOTE = "/dag shows the whole graph"


def _lanes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    return [node for node in nodes if isinstance(node, Mapping) and node.get("kind") != "root"]


def _lane_count(graph: Mapping[str, Any]) -> int:
    """The run's lanes, the ones the graph reader left out (`hidden_nodes`) included."""
    hidden = graph.get("hidden_nodes")
    return len(_lanes(graph)) + (hidden if isinstance(hidden, int) and not isinstance(hidden, bool) else 0)


def _layer_lines(graph: Mapping[str, Any], width: int, theme: Theme) -> list[Line]:
    """One row per layer, in the run's order, its counts in the header's words: `layer 2 · 640 nodes · 12 running ·
    160 done`."""
    from ..plugin_bundle.omh.delegation_view import STATE_ORDER, _state
    from .dag_tree import FACT_SEPARATOR

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for node in sorted(_lanes(graph), key=lambda node: int(node.get("order") or 0)):
        groups.setdefault(str(node.get("group") or ""), []).append(node)
    hidden_by_group = graph.get("hidden_by_group") if isinstance(graph.get("hidden_by_group"), Mapping) else {}
    order = graph.get("group_order") if isinstance(graph.get("group_order"), list) else []
    emptied = [group for group in order if isinstance(group, str) and group not in groups and hidden_by_group.get(group)]
    if emptied:  # a layer the graph reader's cap emptied keeps its row (`0 of 161 nodes`), in the run's order
        rank = {group: at for at, group in enumerate(order)}
        groups = dict(sorted({**groups, **{group: [] for group in emptied}}.items(),
                             key=lambda pair: rank.get(pair[0], len(rank))))
    lines: list[Line] = []
    for group, members in groups.items():
        hidden = hidden_by_group.get(group, 0) if isinstance(hidden_by_group.get(group, 0), int) else 0
        total = len(members) + hidden
        counts: dict[str, int] = {}
        for node in members:
            counts[_state(node)] = counts.get(_state(node), 0) + 1
        said = [group or "lanes", f"{len(members):,} of {total:,} nodes" if hidden else f"{total:,} node{'' if total == 1 else 's'}"]
        said += [f"{counts[state]:,} {state}" for state in STATE_ORDER if counts.get(state)]
        lines.append(truncate_line((Span(INDENT), Span(FACT_SEPARATOR.join(said), theme.muted)), width))
    return lines


def _whole_tally(graph: Mapping[str, Any]) -> str:
    """`DAG · <name> · 1,002 nodes · 998 done · 4 failed`: the whole run's lanes by state, the ones the graph
    reader's cap left out (`hidden_by_state`) included, so a big run's end does not tally only what was kept."""
    from ..plugin_bundle.omh.delegation_view import STATE_ORDER, _state
    from .dag_tree import FACT_SEPARATOR

    counts: dict[str, int] = {}
    for node in _lanes(graph):
        counts[_state(node)] = counts.get(_state(node), 0) + 1
    by_state = graph.get("hidden_by_state") if isinstance(graph.get("hidden_by_state"), Mapping) else {}
    for state, count in by_state.items():
        if isinstance(count, int) and not isinstance(count, bool):
            word = state if state in STATE_ORDER else "unknown"
            counts[word] = counts.get(word, 0) + count
    total = _lane_count(graph)
    said = ["DAG", str(graph.get("name") or "delegation"), f"{total:,} node{'' if total == 1 else 's'}"]
    return FACT_SEPARATOR.join(said + [f"{counts[state]:,} {state}" for state in STATE_ORDER if counts.get(state)])


def _frontier(block: DagBlock) -> list[Mapping[str, Any]]:
    """The lanes the moment changed: the ones it added, else the first layer (the plan's start)."""
    lanes = sorted(_lanes(block.graph), key=lambda node: int(node.get("order") or 0))
    if block.added:
        return [node for node in lanes if str(node.get("dag_node") or "") in block.added]
    first = str(lanes[0].get("group") or "") if lanes else ""
    return [node for node in lanes if str(node.get("group") or "") == first]


def _condensed(block: DagBlock, width: int, theme: Theme) -> list[Line]:
    from ..plugin_bundle.omh.delegation_view import UNICODE, _box_view, header_text
    from .panels import dag_line, dag_style

    graph = block.graph
    lanes = _lanes(graph)
    ended = block.title.startswith(END)
    lines = [truncate_line((Span(f"{INDENT}dag-ulw {block.title}", theme.muted),), width),
             truncate_line((Span(INDENT), Span(_whole_tally(graph) if ended else header_text(graph),
                                               dag_style("header", theme))), width)]
    if ended:
        stopped = [node for node in lanes if node.get("state") in ("failed", "stuck")]
        for node in stopped[:CONDENSED_FAILURES]:
            mark = UNICODE.glyphs.get(str(node.get("state")), "✗")
            lines.append(truncate_line((Span(f"{INDENT}{mark} "), Span(str(node.get("title") or ""), dag_style(
                f"glyph:{node.get('state')}", theme)), Span(f" · {node.get('state')}", theme.muted)), width))
        by_state = graph.get("hidden_by_state") if isinstance(graph.get("hidden_by_state"), Mapping) else {}
        more = max(len(stopped) - CONDENSED_FAILURES, 0) + sum(
            count for state, count in by_state.items() if state in ("failed", "stuck") and isinstance(count, int))
        if more > 0:
            lines.append(truncate_line((Span(f"{INDENT}… {more:,} more"),), width))
        return lines
    lines += _layer_lines(graph, width, theme)
    shown = _frontier(block)[:CONDENSED_BOXES]
    if shown:
        # The shown boxes are drawn under their parents, so each names the nodes it waits on, as in the whole print;
        # the rows above the first shown box are not printed.
        ids = {str(node.get("id")) for node in shown}
        edges = [edge for edge in graph.get("edges") or [] if isinstance(edge, Mapping) and edge.get("to") in ids]
        uppers = {str(edge.get("from")) for edge in edges}
        context = [node for node in graph.get("nodes") or [] if isinstance(node, Mapping)
                   and (node.get("kind") == "root" or str(node.get("id")) in uppers - ids)]
        sub = {**graph, "nodes": [*context, *shown], "hidden_nodes": 0, "edges": edges}
        drawn = _box_view(sub, max(8, width - len(INDENT)), UNICODE, sections=0)
        tops = [top for node_id, top, _bottom in drawn.boxes if node_id in ids] if drawn is not None else []
        if drawn is not None and tops:
            lines.append(())
            lines += [truncate_line((Span(INDENT), *dag_line(row, 1, theme)), width) for row in drawn.lines[min(tops):]]
    total = _lane_count(graph)
    if total > len(shown):
        lines.append(truncate_line((Span(f"{INDENT}… {total - len(shown):,} more nodes · {MORE_NOTE}", theme.muted),),
                                   width))
    return lines


def topology_lines(topology: Mapping[str, Any], width: int, theme: Theme) -> list[Line]:
    """`/dag`'s closing lines for a dag-ulw run: its critical path and the nodes the most others wait on."""
    lines: list[Line] = []
    path = [str(label) for label in topology.get("critical_path") or []]
    if path:
        lines.append(truncate_line((Span("critical path: ", theme.muted), Span(" → ".join(path), theme.text)), width))
    neck = [f"{label} (blocks {count})" for label, count in topology.get("bottlenecks") or []]
    if neck:
        lines.append(truncate_line((Span("bottlenecks: ", theme.muted), Span(" · ".join(neck), theme.text)), width))
    return lines
