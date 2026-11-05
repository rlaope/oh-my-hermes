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

import fnmatch
import posixpath
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


def _scope_path(entry: str) -> tuple[tuple[str, ...], str, str]:
    """A write-scope entry for `shared_scope_pairs` ``as_paths``: (the segments it writes under, its glob, its file).

    ``\\`` reads as ``/``, case is folded and the rest goes through
    `posixpath.normpath`, so ``./``, a repeated or trailing ``/`` and ``x/..``
    change nothing; a leading ``/`` stays a first ``/`` segment. A ``*`` or
    ``?`` glob writes under the directory before the segment holding it, and
    keeps its whole pattern, with ``**/`` read as ``*`` (`fnmatch`'s ``*``
    already crosses ``/``, and ``src/**/*.py`` must meet ``src/x.py``) and
    ``[`` escaped (``app/[slug]/page.tsx`` names a file far more often than a
    write scope holds a character class). The file
    is the normalised path when the entry is neither a glob nor written as a
    directory (a trailing ``/``) and its last segment has a suffix; else "".
    """
    text = entry.replace("\\", "/").casefold()
    absolute = text.startswith("/")
    normal = posixpath.normpath(text.lstrip("/") or ".")
    segments = [] if normal == "." else normal.split("/")
    globbed = [index for index, segment in enumerate(segments) if "*" in segment or "?" in segment]
    under = (("/",) if absolute else ()) + tuple(segments[:globbed[0]] if globbed else segments)
    whole = ("/" if absolute else "") + "/".join(segments)
    pattern = whole.replace("**/", "*").replace("[", "[[]") if globbed else ""
    concrete = not globbed and not text.endswith("/") and bool(segments) and posixpath.splitext(segments[-1])[1]
    return under, pattern, whole if concrete else ""


def _meets(first: tuple[tuple[str, ...], str, str], second: tuple[tuple[str, ...], str, str]) -> bool:
    """Whether two `_scope_path` entries may write one path: one writes under the other, and a glob beside a file
    matches it (`fnmatch`: ``*`` crosses ``/``). A glob beside a glob or a directory meets by its directory alone."""
    (first_under, first_glob, first_file), (second_under, second_glob, second_file) = first, second
    if first_under != second_under[:len(first_under)] and second_under != first_under[:len(second_under)]:
        return False
    if first_glob and second_file:
        return fnmatch.fnmatchcase(second_file, first_glob)
    if second_glob and first_file:
        return fnmatch.fnmatchcase(first_file, second_glob)
    return True


def shared_scope_pairs(
    scopes: Sequence[tuple[str, Iterable[str]]], parents: Mapping[str, Iterable[str]], *, as_paths: bool = False
) -> list[tuple[str, str, list[str], bool]]:
    """Every pair of nodes whose scopes name a same entry: (first, second, the shared entries, joined by an edge).

    Entries are compared as written, unless ``as_paths``: then two entries
    meet as `_meets` says (``src`` and ``src/x.py`` meet, ``src/a`` and
    ``src/ab`` do not, ``*.md`` meets ``docs/a.md`` and not ``src/x.py``), and
    the shared entries are every entry of either node that meets one of the
    other's, as written. Joined means one of the two lists the other as a
    parent directly; an order through a third node does not count.
    """
    edges = {(node, parent) for node, listed in parents.items() for parent in listed}
    indexed = [(node, {entry: _scope_path(entry) if as_paths else ((entry,), "", "") for entry in scope})
               for node, scope in scopes]
    pairs: list[tuple[str, str, list[str], bool]] = []
    for position, (first, first_scope) in enumerate(indexed):
        for second, second_scope in indexed[position + 1:]:
            shared: set[str] = set()
            for first_entry, first_path in first_scope.items():
                for second_entry, second_path in second_scope.items():
                    if _meets(first_path, second_path):
                        shared.update((first_entry, second_entry))
            if shared:
                pairs.append((first, second, sorted(shared), (first, second) in edges or (second, first) in edges))
    return pairs
