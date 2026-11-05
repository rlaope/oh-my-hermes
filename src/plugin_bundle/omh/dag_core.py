"""The one DAG core: dependency checks, layers, critical path and bottlenecks for every graph OMH keeps.

An `omh_dag/v1` run (`dag_run.py`), an `omh_team/v1` team
(`omh.workflows.team`), a `fanout_contract/v2` split and its per-unit check
edges (`omh.coding.fanout`), a dag run in the delegation graph and the
graph's drawing (`delegation_graph.py`, `delegation_view.py`) decide their
topology here. Each caller keeps its own error type and wording. Two older
walks in `delegation_graph.py` stay on their own code, because the core
answers differently on inputs they can see: the graph's layers (a repeated
node id) and a team's stages (a hand-edited record with a cycle).

Pure and stdlib only, and it imports nothing from `omh`: Hermes loads this
directory with its own interpreter (#1623), and the core-side callers import
it from here the way they import `run_records`.

A graph is a sequence of node ids and, per node, the ids it depends on (its
parents). A parent that is not one of the ids is ignored by the topology
functions (`layer_of` can instead hold what waits on it), so a caller checks
its references first (`edge_problem`). A layer is a node's longest path from
a node with no parent; it orders, it never gates.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence

UNKNOWN_DEPENDENCY = "unknown_dependency"
SELF_DEPENDENCY = "self_dependency"
BOTTLENECK_LIMIT = 3


def _unique(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for node in ids:
        if node not in seen:
            seen.add(node)
            ordered.append(node)
    return ordered


def edge_problem(node: str, parents: Iterable[str], known: Collection[str]) -> tuple[str, str] | None:
    """The first wrong reference in ``parents``: (`UNKNOWN_DEPENDENCY` | `SELF_DEPENDENCY`, the parent), or None."""
    for parent in parents:
        if parent not in known:
            return UNKNOWN_DEPENDENCY, parent
        if parent == node:
            return SELF_DEPENDENCY, parent
    return None


def layer_of(
    ids: Sequence[str], parents: Mapping[str, Iterable[str]], *, strict: bool = False
) -> tuple[dict[str, int], list[str]]:
    """Each placed node's layer, and the nodes left unplaced (on a cycle or below one), in ``ids`` order.

    A node is placed in the round after the last of its parents was, so its
    layer is its longest path from a node with no parent. A self edge is a
    cycle. A parent outside ``ids`` is ignored, unless ``strict``: then it is
    never placed, and neither is anything that waits on it (the fanout merge
    order's own rule).
    """
    order = _unique(ids)
    known = set(order)
    edges = {node: {parent for parent in parents.get(node, ()) if strict or parent in known} for node in order}
    placed: dict[str, int] = {}
    remaining = order
    depth = 0
    while remaining:
        ready = [node for node in remaining if all(parent in placed for parent in edges[node])]
        if not ready:
            break
        for node in ready:
            placed[node] = depth
        remaining = [node for node in remaining if node not in placed]
        depth += 1
    return placed, remaining


def layers(ids: Sequence[str], parents: Mapping[str, Iterable[str]]) -> list[list[str]] | None:
    """The nodes by layer, in ``ids`` order within each; None when the graph holds a cycle."""
    placed, stuck = layer_of(ids, parents)
    if stuck:
        return None
    order = _unique(ids)
    depth = max(placed.values(), default=-1) + 1
    return [[node for node in order if placed[node] == index] for index in range(depth)]


def ready(candidates: Iterable[str], parents: Mapping[str, Iterable[str]], satisfied: Collection[str]) -> list[str]:
    """The candidates every one of whose parents is satisfied, in candidate order."""
    return [node for node in _unique(candidates) if all(parent in satisfied for parent in parents.get(node, ()))]


def critical_path(ids: Sequence[str], parents: Mapping[str, Iterable[str]]) -> list[str]:
    """The longest chain of nodes, first to last; ties go to the smaller id. Empty for a cyclic or empty graph."""
    placed, stuck = layer_of(ids, parents)
    if stuck or not placed:
        return []
    known = set(placed)
    length: dict[str, int] = {}
    previous: dict[str, str] = {}
    for node in sorted(placed, key=lambda item: (placed[item], item)):
        best = ""
        for parent in sorted({parent for parent in parents.get(node, ()) if parent in known}):
            if not best or length[parent] > length[best]:
                best = parent
        length[node] = 1 + (length[best] if best else 0)
        if best:
            previous[node] = best
    end = min(placed, key=lambda item: (-length[item], item))
    path = [end]
    while path[-1] in previous:
        path.append(previous[path[-1]])
    return path[::-1]


def bottlenecks(
    ids: Sequence[str], parents: Mapping[str, Iterable[str]], *, limit: int = BOTTLENECK_LIMIT
) -> list[tuple[str, int]]:
    """The nodes the most others wait on, directly or not, as (id, how many); only nodes something waits on."""
    order = _unique(ids)
    known = set(order)
    children: dict[str, set[str]] = {node: set() for node in order}
    for node in order:
        for parent in parents.get(node, ()):
            if parent in known and parent != node:
                children[parent].add(node)
    counts: list[tuple[str, int]] = []
    for node in order:
        below: set[str] = set()
        frontier = list(children[node])
        while frontier:
            current = frontier.pop()
            if current not in below and current != node:
                below.add(current)
                frontier.extend(children[current])
        if below:
            counts.append((node, len(below)))
    return sorted(counts, key=lambda item: (-item[1], item[0]))[:limit]


def _scope_path(entry: str) -> tuple[str, ...]:
    """A write-scope entry as the path segments it may write under, for `shared_scope_pairs` ``as_paths``.

    Case-folded; empty and ``.`` segments dropped, so a leading ``./``, a
    repeated ``/`` and a trailing ``/`` change nothing; a leading ``/`` stays
    as a first ``/`` segment. A glob (``*`` or ``?``) is cut to the directory
    before the segment holding it: ``src/*.py`` writes under ``src``, and
    ``*.py`` under the whole tree. ``[`` is a literal, since ``app/[slug]/page.tsx``
    names a file far more often than a write scope holds a character class.
    """
    segments = ["/"] if entry.startswith("/") else []
    for segment in entry.casefold().split("/"):
        if "*" in segment or "?" in segment:
            break
        if segment not in ("", "."):
            segments.append(segment)
    return tuple(segments)


def shared_scope_pairs(
    scopes: Sequence[tuple[str, Iterable[str]]], parents: Mapping[str, Iterable[str]], *, as_paths: bool = False
) -> list[tuple[str, str, list[str], bool]]:
    """Every pair of nodes whose scopes name a same entry: (first, second, the shared entries, joined by an edge).

    Entries are compared as written, unless ``as_paths``: then two entries
    meet when one's `_scope_path` is the other's or a whole-segment prefix of it
    (``src`` and ``src/x.py`` meet, ``src/a`` and ``src/ab`` do not), and the
    shared entries are every entry of either node that meets one of the
    other's, as written. Joined means one of the two lists the other as a
    parent directly; an order through a third node does not count.
    """
    edges = {(node, parent) for node, listed in parents.items() for parent in listed}
    indexed = [(node, {entry: _scope_path(entry) if as_paths else (entry,) for entry in scope})
               for node, scope in scopes]
    pairs: list[tuple[str, str, list[str], bool]] = []
    for position, (first, first_scope) in enumerate(indexed):
        for second, second_scope in indexed[position + 1:]:
            shared: set[str] = set()
            for first_entry, first_path in first_scope.items():
                for second_entry, second_path in second_scope.items():
                    if first_path == second_path[:len(first_path)] or second_path == first_path[:len(second_path)]:
                        shared.update((first_entry, second_entry))
            if shared:
                pairs.append((first, second, sorted(shared), (first, second) in edges or (second, first) in edges))
    return pairs
