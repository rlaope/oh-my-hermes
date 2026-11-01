"""One turn-start line for a dag-ulw run nothing will wake: which run, and the one `omh_dag` call to make.

A dag-ulw parent re-enters a run only when a child completes. When no
child is running, no completion is coming, and the run sits open until the
person happens to write again and the model happens to look. Measured on 17
real run records, 3 were left open that way: two had a parked node whose
``wake_at`` had passed with nothing else live (OMH deliberately starts no
timer), and one had a verification node ready that was never handed out.
The stuck warning (`dag_run.stuck`) said nothing either, because it shows
only on an `omh_dag` call.

So `pre_llm_call` -- the one OMH hook that runs at every turn's start --
names such a run once, with the call that moves it:

* a parked node past its ``wake_at`` while no child is running:
  ``omh_dag action=ready run=<id>`` (the parked node gets its fresh attempt);
* ready nodes while no node is out at all: ``omh_dag action=ready run=<id>``;
* a node open past the stuck mark (the profile's ``dag_stuck_after_s``,
  ``0`` turns it off): ``omh_dag action=status run=<id>``.

Information only: nothing is blocked, and OMH still starts no timer; the
line rides the next turn, whoever opens it.

Once per situation. A situation is the run, the reason, its nodes and, for a
parked node, its ``wake_at``; the same one is not named again on the next
turn, and a new one (another node ready, a new ``wake_at``) is. What was
named is kept in this process only, bounded: the run record has one writer,
the `omh_dag` tool, and a reminder is not part of the plan it keeps. A
gateway restart may name a situation once more.

Read the way `omh_dag` reads it: the conversation's segments
(`conversation_session_ids`), every run stored under them
(`dag_run.session_runs`), the children its delegation ledgers hold
(`dag_tool._children`), the profile's marks (`dag_tool.dag_limits`), and
the derived state (`dag_run.derive`, `dag_run.run_state`). A delegated
child, a conversation with no run, a finished run and a record that cannot
be read get nothing. Never raises: a raise in `pre_llm_call` drops every
other OMH line of the turn, so a read that fails says nothing.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Final

from . import dag_run
from .kanban_board_reader import conversation_session_ids
from .runtime_reader import reading_session_id
from .tools import dag_tool

MAX_NAMED_SITUATIONS: Final = 512
MAX_NODES_NAMED: Final = 3
OPEN_RUN_TEXTS: Final = {
    "parked_due": (
        "[OMH dag] Run {run}: parked {nodes} passed wake_at and no child is running, so nothing will wake the "
        "run. Call omh_dag action=ready run={run}; the parked node gets its fresh attempt."
    ),
    "ready_idle": (
        "[OMH dag] Run {run}: {nodes} ready and nothing is out, so nothing will wake the run. Call omh_dag "
        "action=ready run={run} and dispatch the calls it returns."
    ),
    "stuck": (
        "[OMH dag] Run {run}: {nodes} open past the {mark} stuck mark. Call omh_dag action=status run={run} for "
        "what to check."
    ),
}

_lock = threading.Lock()
_named: "OrderedDict[tuple[Any, ...], None]" = OrderedDict()


def wake_needed(
    record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], now: float, *,
    limits: dag_run.Limits = dag_run.DEFAULT_LIMITS,
) -> tuple[str, list[str]] | None:
    """``(reason, node ids)`` when nothing will wake this run and one call would move it, else None.

    ``parked_due`` and ``ready_idle`` come from `dag_run.offerable`, the nodes
    ``ready`` would hand out now; ``stuck`` from `dag_run.stuck`.
    """
    states = {node_id: str(info["state"]) for node_id, info in derived.items()}
    offered = dag_run.offerable(record, derived, now, limits=limits)
    due = [node_id for node_id in offered if states[node_id] == "parked"]
    if due and "running" not in states.values():
        return "parked_due", due
    ready = [node_id for node_id in offered if states[node_id] == "ready"]
    if ready and not any(state in dag_run.OPEN for state in states.values()):
        return "ready_idle", ready
    found = dag_run.stuck(record, derived, now, limits=limits)
    if found:
        return "stuck", [node_id for node_id, _age in found]
    return None


def _situation(record: Mapping[str, Any], reason: str, nodes: list[str]) -> tuple[Any, ...]:
    """What makes two turns' findings the same: the run, the reason, the nodes and each parked node's wake_at."""
    attempts = {str(node["id"]): (node.get("attempts") or [{}])[-1] for node in record["nodes"]}
    wakes = tuple(str(attempts[node_id].get("wake_at")) for node_id in nodes) if reason == "parked_due" else ()
    return str(record.get("session_id")), str(record["run"]), reason, tuple(sorted(nodes)), wakes


def _claim(situation: tuple[Any, ...]) -> bool:
    with _lock:
        if situation in _named:
            return False
        _named[situation] = None
        while len(_named) > MAX_NAMED_SITUATIONS:
            _ = _named.popitem(last=False)
        return True


def _named_nodes(nodes: list[str]) -> str:
    shown = ", ".join(nodes[:MAX_NODES_NAMED])
    more = f" +{len(nodes) - MAX_NODES_NAMED}" if len(nodes) > MAX_NODES_NAMED else ""
    return f"{'node' if len(nodes) == 1 else 'nodes'} {shown}{more}"


def _open_run_line(session: str, omh_home: Path, hermes_home: Path, now: float) -> str:
    if not (omh_home / "runtime" / dag_run.DAG_DIRNAME).is_dir():
        return ""
    durable = reading_session_id(hermes_home, session)
    if not durable:
        return ""
    segments = sorted({durable, *conversation_session_ids(hermes_home, durable)})
    runs = [item for segment in segments for item in dag_run.session_runs(omh_home, segment)]
    if not runs:
        return ""
    runs.sort(key=lambda item: float(item[0].get("updated_at") or 0.0), reverse=True)
    children = dag_tool._children(omh_home, segments, hermes_home)
    limits, _ignored = dag_tool.dag_limits(hermes_home)
    for record, _path in runs:
        derived = dag_run.derive(record, children, now)
        if dag_run.run_state(record, derived) in dag_run.FINISHED_STATES:
            continue
        found = wake_needed(record, derived, now, limits=limits)
        if found is None or not _claim(_situation(record, *found)):
            continue
        reason, nodes = found
        return OPEN_RUN_TEXTS[reason].format(
            run=record["run"], nodes=_named_nodes(nodes), mark=dag_run.age_text(limits.stuck_after_s))
    return ""


def open_run_line(
    *, session_id: object, omh_home: str, hermes_home: str, delegated: bool = False, now: float | None = None,
) -> str:
    """The turn-start line naming this conversation's dag run nothing will wake, or ``""``. Never raises."""
    session = str(session_id or "").strip()
    if delegated or not session or not omh_home or not hermes_home:
        return ""
    try:
        return _open_run_line(session, Path(omh_home), Path(hermes_home), time.time() if now is None else now)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
        return ""


def reset_open_run_nudge() -> None:
    """Test seam: forget every situation already named."""
    with _lock:
        _named.clear()


__all__ = [
    "OPEN_RUN_TEXTS",
    "open_run_line",
    "reset_open_run_nudge",
    "wake_needed",
]
