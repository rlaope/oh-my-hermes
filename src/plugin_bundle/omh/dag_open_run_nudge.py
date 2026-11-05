"""One turn-start line for a dag-ulw run with no node running: which run, and the one `omh_dag` call to make.

A dag-ulw parent re-enters a run only when a child completes. When no node
of a run is running, no completion of that run is coming, and the run sits
open until the person happens to write again and the model happens to look.
Measured on 17 real run records, 3 were left open that way: two had a parked
node whose ``wake_at`` had passed with nothing else live (OMH deliberately
starts no timer), and one had a verification node ready that was never
handed out. The stuck warning (`dag_run.stuck`) said nothing either, because
it shows only on an `omh_dag` call.

So `pre_llm_call` -- the one OMH hook that runs at every turn's start --
names such a run once, with the call that moves it. A run's only wake source
is one of its nodes whose child is running. With none, the first of:

* a node whose child came back and is not settled: read the handoff and
  ``omh_dag action=settle`` (settle hands out what comes next). Not on the
  first turn start that sees it: that is the completion's own turn, which
  settles it anyway;
* a node a restart ended past the re-offer bound (`dag_run.lost_for_good`),
  which ``ready`` never offers again: ``omh_dag action=status``, then settle;
* a parked node past its ``wake_at``: ``omh_dag action=ready`` (the parked
  node gets its fresh attempt);
* a node out with no child that ``ready`` offers again (a restart ended its
  child, or none took it past ``dag_stale_after_s``): ``omh_dag action=ready``;
* ready nodes: ``omh_dag action=ready``. When every `delegate_task` slot
  of this process is taken (`dag_tool.free_slots`), ``ready`` would hand out
  nothing now, so the line says to call it at a later turn instead. The line
  does not say who holds the slots: between a dispatch and its child's start
  the holder can be this run's own node;
* a failed or blocked node with a repair cycle left, so the run is
  ``needs_repair`` and nothing else moves it: ``omh_dag action=repair``, or
  report what is open and cancel.

And, a child running or not, a node open past the stuck mark (the profile's
``dag_stuck_after_s``, ``0`` turns it off): ``omh_dag action=status``.

Not named: a node out within ``dag_stale_after_s`` (its child may still be
starting), a parked node whose ``wake_at`` is ahead, and a node exported to a
coding owner or left to the parent (``lane`` fanout or parent), which its
fanout result or the parent's own work settles.

The line says what is true of the run: no node of it is running. It does not
claim the parent will not wake, since another run's child may.

Information only: nothing is blocked, and OMH still starts no timer; the
line rides the next turn, whoever opens it.

Once per situation. A situation is the reason, its nodes and each node's
latest attempt (its number, when it went out, its restarts, its ``wake_at``
and its child's stop), so the same one is not named on the next turn and a
new one (another node ready, a new ``wake_at``, a fresh attempt) is. What
was named is kept per run, the latest situation only, so a run that moves
to another situation and back (ready, held for slots, ready again) is named
again. It is kept in this process only, bounded: the run record has one
writer, the `omh_dag` tool, and a reminder is not part of the plan it keeps.
A gateway restart may name a situation once more.

Read the way `omh_dag` reads it: the conversation's segments
(`conversation_session_ids`), every run stored under them (the listing
`dag_run.session_runs` makes), the children its delegation ledgers hold
(`dag_tool._children`), the profile's marks (`dag_tool.dag_limits`), and
the derived state (`dag_run.derive`, `dag_run.run_state`). A finished run is
finished by its record alone, so the verdict is kept per record file (path,
mtime, size), bounded, and a finished run is not read again until its file
changes. A delegated child, a conversation with no run, a finished run and a
record that cannot be read get nothing. Never raises: a raise in
`pre_llm_call` drops every other OMH line of the turn, so a read that fails
says nothing.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Mapping
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Final

from . import dag_run
from .kanban_board_reader import conversation_session_ids
from .runtime_reader import reading_session_id
from .tools import dag_tool

MAX_NAMED_RUNS: Final = 512
MAX_FINISHED_RECORDS: Final = 512
MAX_NODES_NAMED: Final = 3
REASONS: Final = (
    "returned", "lost", "parked_due", "out_no_child", "ready_idle", "ready_held", "needs_repair", "stuck",
)
# The reasons a resumed session goes on with by itself (`waiting_run`): work a turn moves with no node running.
# Not ``needs_repair`` (repair or cancel is the person's call) nor ``stuck`` (a node may still be running).
RESUMABLE_REASONS: Final = ("returned", "lost", "parked_due", "out_no_child", "ready_idle")

_lock = threading.Lock()
_named: "OrderedDict[tuple[str, str], tuple[Any, ...]]" = OrderedDict()
_finished: "OrderedDict[tuple[str, int, int], None]" = OrderedDict()


def wake_needed(
    record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], now: float, *,
    limits: dag_run.Limits = dag_run.DEFAULT_LIMITS,
) -> tuple[str, list[str]] | None:
    """``(reason, node ids)`` when one call would move this run, else None.

    With no node running: ``returned`` (unsettled), ``lost`` (`dag_run.lost_for_good`), then what
    `dag_run.offerable` would hand out now, by state: ``parked_due``, ``out_no_child``, ``ready_idle``; then
    ``needs_repair`` (`dag_run.run_state`), its failed or blocked nodes with a repair cycle left.
    Running or not: ``stuck`` from `dag_run.stuck`.
    """
    states = {node_id: str(info["state"]) for node_id, info in derived.items()}
    if "running" not in states.values():
        returned = [node_id for node_id, state in states.items() if state == "returned"]
        if returned:
            return "returned", returned
        lost = dag_run.lost_for_good(record, derived, limits=limits)
        if lost:
            return "lost", lost
        offered = dag_run.offerable(record, derived, now, limits=limits)
        for reason, state in (("parked_due", "parked"), ("out_no_child", "handed_out"), ("ready_idle", "ready")):
            nodes = [node_id for node_id in offered if states[node_id] == state]
            if nodes:
                return reason, nodes
        if dag_run.run_state(record, derived) == "needs_repair":
            return "needs_repair", [node_id for node_id in dag_run.open_failures(record, derived)
                                    if dag_run.cycles_left(record, node_id) > 0]
    found = dag_run.stuck(record, derived, now, limits=limits)
    if found:
        return "stuck", [node_id for node_id, _age in found]
    return None


def open_run_text(reason: str, run: str, nodes: list[str], mark: str) -> str:
    """The line for one reason. ``mark`` is the stuck mark as `dag_run.age_text` writes it."""
    one = len(nodes) == 1
    shown = ", ".join(nodes[:MAX_NODES_NAMED])
    more = f" +{len(nodes) - MAX_NODES_NAMED}" if len(nodes) > MAX_NODES_NAMED else ""
    named = f"{'node' if one else 'nodes'} {shown}{more}"
    it, each = ("it", "it") if one else ("them", "each")
    idle = "no node of this run is running"
    head = f"[OMH dag] Run {run}:"
    if reason == "returned":
        return (f"{head} {named} came back and {'is' if one else 'are'} not settled, and {idle}. Read "
                f"{'its handoff' if one else 'each handoff'} and call omh_dag action=settle run={run} for {each}; "
                "settle hands out what comes next.")
    if reason == "lost":
        return (f"{head} a Hermes restart ended the child of {named} past the re-offer bound, so ready will not offer "
                f"{it} again, and {idle}. Call omh_dag action=status run={run}, then settle {each} failed or blocked.")
    if reason == "parked_due":
        return (f"{head} parked {named} passed wake_at and {idle}. Call omh_dag action=ready run={run}; "
                f"{'the parked node gets its' if one else 'each parked node gets its'} fresh attempt.")
    if reason == "out_no_child":
        return (f"{head} {named} {'is' if one else 'are'} out with no child (a restart ended {it} or none took {it}) "
                f"and {idle}. Call omh_dag action=ready run={run} and dispatch the calls it returns.")
    if reason == "ready_idle":
        return (f"{head} {named} ready and {idle}. Call omh_dag action=ready run={run} and dispatch the calls it "
                "returns.")
    if reason == "ready_held":
        return (f"{head} {named} ready and {idle}, but every delegate_task slot of this process is taken, so "
                f"ready would hand out nothing now. Call omh_dag action=ready run={run} at a later turn, once a slot "
                "is free.")
    if reason == "needs_repair":
        target = f"node={nodes[0]}" if one else "node=<id> for each"
        return (f"{head} {named} failed or blocked with a repair cycle left, and {idle}. Call omh_dag action=repair "
                f"run={run} {target}, or report what is open and cancel the run.")
    return f"{head} {named} open past the {mark} stuck mark. Call omh_dag action=status run={run} for what to check."


def _situation(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], reason: str,
               nodes: list[str]) -> tuple[Any, ...]:
    """What makes two turns' findings the same: the reason, the nodes and each node's latest attempt."""
    attempts = {str(node["id"]): node.get("attempts") or [{}] for node in record["nodes"]}
    marks = []
    for node_id in sorted(nodes):
        last = attempts[node_id][-1]
        child = derived[node_id].get("child")
        stop = child.get("stop") if isinstance(child, Mapping) else None
        marks.append((node_id, len(attempts[node_id]), last.get("handed_out_at"), last.get("lost"),
                      last.get("wake_at"), stop.get("observed_at") if isinstance(stop, Mapping) else None))
    return reason, tuple(marks)


def _claim(run: tuple[str, str], situation: tuple[Any, ...], *, quiet_first: bool) -> bool:
    """True when ``situation`` is not what was last named for ``run``; it is then the one named.

    ``quiet_first``: the first turn start that sees the situation only notes it, and the next one names it.
    """
    with _lock:
        last = _named.get(run)
        if last == situation:
            return False
        named = not quiet_first or last == ("seen", situation)
        _named[run] = situation if named else ("seen", situation)
        _named.move_to_end(run)
        while len(_named) > MAX_NAMED_RUNS:
            _ = _named.popitem(last=False)
        return named


def _known_finished(key: tuple[str, int, int]) -> bool:
    with _lock:
        if key not in _finished:
            return False
        _finished.move_to_end(key)
        return True


def _note_finished(key: tuple[str, int, int]) -> None:
    with _lock:
        _finished[key] = None
        _finished.move_to_end(key)
        while len(_finished) > MAX_FINISHED_RECORDS:
            _ = _finished.popitem(last=False)


def _unsettled_runs(omh_home: Path, segment: str) -> list[tuple[dict[str, Any], tuple[str, int, int]]]:
    """The runs under one segment not known finished, each with its file's (path, mtime, size)."""
    directory = dag_run.session_dir(omh_home, segment)
    try:
        paths = [path for path in directory.iterdir()
                 if path.suffix == ".json" and not path.name.startswith(".") and not path.is_symlink()]
    except OSError:
        return []
    runs = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if _known_finished(key):
            continue
        record = dag_run.read_run(path)
        if record is not None:
            runs.append((record, key))
    return runs


def _waking_runs(session: str, omh_home: Path, hermes_home: Path, now: float) -> Iterator[
        tuple[dict[str, Any], dict[str, dict[str, Any]], str, list[str], dag_run.Limits]]:
    """This conversation's open runs that one call would move (`wake_needed`), newest first: each with its derived
    state, the reason, its nodes and the profile's marks. A finished run is noted so it is not read again."""
    if not (omh_home / "runtime" / dag_run.DAG_DIRNAME).is_dir():
        return
    durable = reading_session_id(hermes_home, session)
    if not durable:
        return
    segments = sorted({durable, *conversation_session_ids(hermes_home, durable)})
    runs = [item for segment in segments for item in _unsettled_runs(omh_home, segment)]
    if not runs:
        return
    runs.sort(key=lambda item: float(item[0].get("updated_at") or 0.0), reverse=True)
    children = dag_tool._children(omh_home, segments, hermes_home)
    limits, _ignored = dag_tool.dag_limits(hermes_home)
    for record, key in runs:
        derived = dag_run.derive(record, children, now)
        if dag_run.run_state(record, derived) in dag_run.FINISHED_STATES:
            _note_finished(key)
            continue
        found = wake_needed(record, derived, now, limits=limits)
        if found is not None:
            yield record, derived, found[0], found[1], limits


def _open_run_line(session: str, omh_home: Path, hermes_home: Path, now: float) -> str:
    for record, derived, reason, nodes, limits in _waking_runs(session, omh_home, hermes_home, now):
        run = (str(record.get("session_id")), str(record["run"]))
        if reason == "ready_idle" and dag_tool.free_slots(hermes_home)["free"] <= 0:
            reason = "ready_held"
        if not _claim(run, _situation(record, derived, reason, nodes), quiet_first=reason == "returned"):
            continue
        return open_run_text(reason, str(record["run"]), nodes, dag_run.age_text(limits.stuck_after_s))
    return ""


def open_run_line(
    *, session_id: object, omh_home: str, hermes_home: str, delegated: bool = False, now: float | None = None,
) -> str:
    """The turn-start line naming this conversation's dag run no running node will re-open, or ``""``. Never raises."""
    session = str(session_id or "").strip()
    if delegated or not session or not omh_home or not hermes_home:
        return ""
    try:
        return _open_run_line(session, Path(omh_home), Path(hermes_home), time.time() if now is None else now)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
        return ""


def waiting_run(
    *, session_id: object, omh_home: str, hermes_home: str, now: float | None = None,
) -> tuple[str, str, list[str]] | None:
    """``(reason, run, node ids)`` for this conversation's newest open run that a turn would move and that waits on
    nothing running (the reasons in `RESUMABLE_REASONS`), else None. Never raises.

    What a resumed session's OMH TUI reads to go on by itself: the turn it starts brings this module's line at its
    `pre_llm_call`. Unlike `open_run_line` it names a run every time it is asked (it claims nothing), and it does not
    hold ready nodes back for slots: those are the gateway process's, not the caller's.
    """
    session = str(session_id or "").strip()
    if not session or not omh_home or not hermes_home:
        return None
    try:
        for record, _derived, reason, nodes, _limits in _waking_runs(
                session, Path(omh_home), Path(hermes_home), time.time() if now is None else now):
            if reason in RESUMABLE_REASONS:
                return reason, str(record["run"]), nodes
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
        return None
    return None


def reset_open_run_nudge() -> None:
    """Test seam: forget every situation already named and every finished verdict."""
    with _lock:
        _named.clear()
        _finished.clear()


__all__ = [
    "REASONS",
    "RESUMABLE_REASONS",
    "open_run_line",
    "open_run_text",
    "reset_open_run_nudge",
    "waiting_run",
    "wake_needed",
]
