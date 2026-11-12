"""Refuse a dag-ulw node's child writing outside the write scope its node declared.

`omh_dag define` refuses two nodes that share a write scope with no edge
between them, and that is the whole of what the scope did: once the children
ran, nothing looked at what they wrote. A child told `SCOPE: src/api.py` that
also rewrote its sibling's `src/ui.py` was found, if at all, by the verify node
after both had finished.

`pre_tool_call` therefore blocks a `write_file` or `patch` (every V4A header
and move target) from a session the delegation ledger binds to a dag-ulw node
(`children[].dag`, from the `[dag:run/node]` marker the child's goal carries),
when the target is inside the run's workspace and no entry of that node's
`write_scope` covers it. The workspace is the one `omh_dag define` pinned in
the run record (`workspace_root`), so a child that `cd`s elsewhere is still
judged against the same root; a run defined before the pin falls back to the
session's current workspace. A child the node's child spawned in turn follows
the outermost node binding on its chain, so a descendant's own marker cannot
move it to another node, and a child Hermes' compaction renamed is found
through its earlier segments. An entry covers a target when it names that file
or a directory the target is under (whether or not the directory exists yet),
compared literally first; an entry holding `*` or `?` is also tried as an
`fnmatch` glob over the workspace-relative path, where `*` may cross `/`.
Brackets are always literal, so `app/[slug]/page.tsx` covers itself and not
`app/s/page.tsx`. The node's own handoff
report, on this host or under a Docker/SSH run's `handoff_root`, always passes.

A node defined `read_only` (a review, verify or explore node that reports and
changes nothing; `omh_dag define` refuses one that also declares a write
scope) is held tighter: every `write_file` or `patch` target inside the
workspace is blocked except that same handoff report, and the message tells
the child to write its findings there instead.

What passes, on purpose: a session no ledger binds to a node (every parent and
every ordinary child); a node with an empty write scope and no `read_only`,
which declared nothing to hold it to; a node already settled or a run
cancelled, whose late calls are not this run's work any more; and a target
outside the workspace (scratch files, another checkout). As with the evidence
guard, a shell command is not judged (a read-only node's included), and an
unresolvable lookup passes and warns once.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from . import dag_run
from .consistency_trigger import _edit_targets
from .delegation_ledger import ROOT_WALK_LIMIT, read_ledger, root_session
from .engagement_nudges import FILE_MUTATING_TOOLS
from .kanban_board_reader import conversation_session_ids
from .tools.lsp_nav_tool import _workspace_root

_GLOB_CHARACTERS: Final = frozenset("*?")
_LOG = logging.getLogger("omh.dag_scope_guard")
_warned = False


def dag_scope_directive(
    *, tool_name: object, tool_input: object, session_id: object, task_id: object, omh_home: str, hermes_home: str
) -> dict[str, str] | None:
    """A `block` naming the node and its scope, when a node's child writes outside it; else None."""
    session = str(session_id or "").strip()
    if str(tool_name or "") not in FILE_MUTATING_TOOLS or not isinstance(tool_input, dict) or not session or not omh_home:
        return None
    try:
        bound = _bound_node(session, Path(omh_home).expanduser(), Path(hermes_home).expanduser())
        if bound is None:
            return None
        record, node, owner = bound
        scope = [str(entry) for entry in node.get("write_scope") or []]
        read_only = node.get("read_only") is True
        if not scope and not read_only:
            return None
        pinned = record.get("workspace_root")
        base = _comparable(pinned if isinstance(pinned, str) and pinned else _workspace_root(task_id) or os.getcwd())
        cwd = _workspace_root(task_id) or os.getcwd()
        home = Path(omh_home).expanduser()
        handoffs = {
            _comparable(str(dag_run.handoff_path(home, owner, str(record["run"]), str(node["id"])))),
            _comparable(dag_run.node_handoff(record, home, str(node["id"]))),
        }
        for requested in _edit_targets(str(tool_name), tool_input):
            target = _comparable(os.path.join(cwd, os.path.expanduser(requested)))
            if target in handoffs or not _inside(target, base):
                continue
            if read_only:
                return {"action": "block", "message": dag_read_only_message(requested, str(record["run"]), node)}
            if _covered(target, scope, base):
                continue
            return {"action": "block", "message": dag_scope_message(requested, str(record["run"]), node, scope)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        _warn_once(exc)
    return None


def dag_scope_message(requested: str, run: str, node: Mapping[str, Any], scope: Iterable[str]) -> str:
    listed = ", ".join(scope)
    return (
        f"OMH blocked this write: {requested!r} is outside the write scope of dag-ulw node "
        f"{node['id']} in run {run} ({listed}). Other nodes of the run own the files outside it, and two "
        "children writing the same file overwrite each other. Do not retry this write or route it through the "
        "shell; finish what your scope covers and name the file you could not change in your handoff report, "
        "so the parent can repair or extend the run."
    )


def dag_read_only_message(requested: str, run: str, node: Mapping[str, Any]) -> str:
    return (
        f"OMH blocked this write: dag-ulw node {node['id']} in run {run} is read-only, so its child changes no file "
        f"in the workspace ({requested!r}). Do not retry this write or route it through the shell; write findings "
        "into your handoff report instead."
    )


def _bound_node(session: str, omh_home: Path, hermes_home: Path) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """(run record, node, the session the run is stored under) for a child the ledger binds to a live node."""
    root = root_session(session, hermes_home)
    if root == session:
        return None
    ledger = read_ledger(omh_home, root)
    if not ledger:
        return None
    by_child = {str(child["child_session_id"]): child for child in ledger["children"]}
    current = session
    if current not in by_child:
        # A child Hermes' rotating compaction renamed is in the ledger under an earlier segment's id.
        current = next((segment for segment in sorted(conversation_session_ids(hermes_home, session))
                        if segment in by_child), "")
    binding: Mapping[str, Any] | None = None
    for _ in range(ROOT_WALK_LIMIT):
        entry = by_child.get(current)
        if entry is None:
            break
        if isinstance(entry.get("dag"), Mapping):
            binding = entry["dag"]  # keep walking: the outermost binding on the chain is the node
        current = str(entry.get("parent_session_id") or "")
    if binding is None:
        return None
    run, node_id = str(binding["run"]), str(binding["node"])
    for owner in sorted({root, *conversation_session_ids(hermes_home, root)}):
        record = dag_run.read_run(dag_run.record_path(omh_home, owner, run))
        if record is None:
            continue
        if record.get("cancelled_at") is not None:
            return None
        node = next((item for item in record["nodes"] if str(item.get("id")) == node_id), None)
        if node is None:
            return None
        attempts = node.get("attempts") or []
        if attempts and attempts[-1].get("outcome") in dag_run.OUTCOMES:
            return None
        return record, node, owner
    return None


def _covered(target: str, scope: Iterable[str], base: str) -> bool:
    relative = os.path.relpath(target, base).replace(os.sep, "/")
    for entry in scope:
        if _inside(target, _comparable(os.path.join(base, os.path.expanduser(entry)))):
            return True
        if _GLOB_CHARACTERS & set(entry):
            pattern = (entry[2:] if entry.startswith("./") else entry).replace(os.sep, "/").casefold().replace("[", "[[]")
            if fnmatch.fnmatchcase(relative, pattern):
                return True
    return False


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _comparable(path: str) -> str:
    return os.path.normcase(os.path.realpath(path)).casefold()


def _warn_once(exc: BaseException) -> None:
    global _warned
    if not _warned:
        _warned = True
        _LOG.warning("dag scope guard could not resolve a node or a write target (%s); the write was allowed",
                     type(exc).__name__)
