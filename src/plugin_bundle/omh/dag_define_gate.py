"""A `delegate_task` without a node marker goes back to `omh_dag`, once per turn.

Two gates share one "at most one block per turn per session" record:

* **Define first.** The route hint tells the model to plan the graph and call
  `omh_dag define` first, and `define` hands back the `delegate_task` calls,
  each goal carrying its `[dag:<run>/<node>]` marker (`dag_run.calls_for`). A
  model that skips it and fans out plain children instead runs no graph at
  all: the ledger binds a child to a node only through that marker
  (`delegation_ledger.dag_binding`), so the run view draws nothing and no node
  is ever verified or repaired. So the call is blocked once, with a message
  naming `define`, when `pre_llm_call` recorded this session's current turn as
  one whose primary hint, as rendered, is dag-ulw's `start_dag_run`
  (`note_turn`), the call spawns in that same turn, nothing was blocked in it
  yet, and this conversation has no dag run. One it cannot read counts as one,
  for `define` would be refused there too and the message would point nowhere.

* **Inside a run.** Once the conversation holds an ACTIVE dag run (one whose
  `dag_run.run_state` is no finished state), a markerless spawn draws children
  the run view cannot place: they stand beside the run as outside lanes and
  no node ever gets them. So the call is blocked once, with a message naming
  the run and pointing at `omh_dag` (ready/settle/repair/extend), whenever the
  call spawns in the current turn, nothing was blocked in it yet, and an
  active run is found. No route hint is needed: the turn only has to be the
  session's current one. A store that cannot be read is no active run, so the
  call goes through (fail open).

Both gates: the call must be `delegate_task` spawning children with no `[dag:`
in any goal (`list`, `steer` and `stop` act on children already running), in a
named turn of a named session, and each blocks at most once per turn — so one
blocked call answered with the same call goes through, and neither gate can
deadlock or loop. `omh_dag` itself is never held back, so a refused `define`
does not leave the turn stuck behind this gate either. A delegated child
records nothing: its hint never carries an orchestrating engine, its run store
holds no run of the conversation's, and its own `define` is refused anyway.

Never raises: Hermes logs a hook exception and runs the call, which would
also skip the dispatch ledger the rest of `pre_tool_call` writes.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
import sqlite3
import threading
import time
from typing import Final

from . import dag_run
from .delegation_ledger import read_ledger
from .kanban_board_reader import conversation_session_ids
from .runtime_reader import reading_session_id

DELEGATE_TOOL: Final = "delegate_task"
DAG_MARKER: Final = "[dag:"
# The hint whose turn this gate keeps (`awareness._DIRECT_WORKFLOW_NEXT_ACTIONS`).
DAG_WORKFLOW: Final = "dag-ulw"
DAG_START_ACTION: Final = "start_dag_run"
# `delegate_task` actions that spawn; an absent action is Hermes' default, `spawn`.
_SPAWN_ACTIONS: Final = frozenset({"", "spawn"})
MAX_TRACKED_SESSIONS: Final = 256
RESEND_PASSES: Final = (
    "If these children are intentionally outside the run, send this call again and it goes through."
)
DEFINE_FIRST_MESSAGE: Final = (
    "Not dispatched: this turn asked for a dag-ulw run, and this conversation has none yet. Call omh_dag "
    "action=define with the graph first, then dispatch the delegate_task calls it returns; their "
    "[dag:<run>/<node>] markers are what the run view draws. " + RESEND_PASSES
)


def mid_run_message(run: str) -> str:
    """The mid-run gate's refusal, naming the active run and the calls that move it."""
    return (
        f"Not dispatched: dag run {run} is active in this conversation, and a spawn with no "
        "[dag:<run>/<node>] marker is no node of it — its children would only draw outside the run. "
        "Read the run with omh_dag action=status and move it with the ready, settle, repair or extend "
        "actions instead. " + RESEND_PASSES
    )


_lock = threading.Lock()
# session -> (the session's current turn, whether its hint asks for a dag-ulw start, whether a gate blocked in it)
_turns: "OrderedDict[str, tuple[str, bool, bool]]" = OrderedDict()


def starts_dag_run(rendered_hint: Mapping[str, object]) -> bool:
    """Whether the route hint a turn rendered selects dag-ulw to start a run."""
    return (
        rendered_hint.get("primary_workflow") == DAG_WORKFLOW
        and rendered_hint.get("primary_next_action") == DAG_START_ACTION
    )


def note_turn(session_id: object, turn_id: object, *, starts_run: bool) -> None:
    """Record this session's current turn and whether its hint starts a dag-ulw run; `pre_llm_call` calls it
    every turn, so each turn's first blocked spawn is its only one."""
    key = str(session_id or "").strip()
    turn = str(turn_id or "").strip()
    if not key:
        return
    with _lock:
        _ = _turns.pop(key, None)
        if turn:
            _turns[key] = (turn, bool(starts_run), False)
            while len(_turns) > MAX_TRACKED_SESSIONS:
                _ = _turns.popitem(last=False)


def _spawned_goals(tool_input: object) -> list[str]:
    if not isinstance(tool_input, Mapping):
        return []
    if str(tool_input.get("action") or "").strip() not in _SPAWN_ACTIONS:
        return []
    tasks = tool_input.get("tasks")
    goals = [task.get("goal") for task in tasks if isinstance(task, Mapping)] if isinstance(tasks, list) else []
    goals.append(tool_input.get("goal"))  # the legacy single-goal shape Hermes still accepts
    return [goal for goal in goals if isinstance(goal, str) and goal.strip()]


def _segments(hermes_home: str, session: str) -> set[str]:
    durable = reading_session_id(hermes_home, session)
    if not durable:
        raise ValueError("no durable session id")
    return {durable, *conversation_session_ids(hermes_home, durable)}


def _conversation_has_run(omh_home: str, hermes_home: str, session: str) -> bool:
    try:
        segments = _segments(hermes_home, session)
        return any(dag_run.session_runs(Path(omh_home), segment) for segment in segments)
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
        return True


def _active_run(omh_home: str, hermes_home: str, session: str) -> str:
    """The id of the conversation's unfinished dag run, or "": an unreadable store is no evidence of one
    (fail open), and a run in a finished state (`dag_run.FINISHED_STATES`) does not hold the turn."""
    try:
        segments = _segments(hermes_home, session)
        children = [
            child
            for segment in segments
            for child in ((read_ledger(Path(omh_home), segment) or {}).get("children") or [])
        ]
        for record, _path in sorted(
            (item for segment in segments for item in dag_run.session_runs(Path(omh_home), segment)),
            key=lambda item: float(item[0].get("updated_at") or 0.0),
            reverse=True,
        ):
            if dag_run.run_state(record, dag_run.derive(record, children, time.time())) not in dag_run.FINISHED_STATES:
                return str(record["run"])
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, sqlite3.Error):
        return ""
    return ""


def delegate_before_define_directive(
    *,
    tool_name: object,
    tool_input: object,
    session_id: object = "",
    turn_id: object = "",
    omh_home: str = "",
    hermes_home: str = "",
) -> dict[str, str] | None:
    """`block` for a markerless `delegate_task` spawn the turn's dag gates refuse once, else None."""
    if str(tool_name or "") != DELEGATE_TOOL:
        return None
    goals = _spawned_goals(tool_input)
    if not goals or any(DAG_MARKER in goal for goal in goals):
        return None
    key = str(session_id or "").strip()
    turn = str(turn_id or "").strip()
    if not key or not turn or not omh_home or not hermes_home:
        return None
    with _lock:
        recorded = _turns.get(key)
        if recorded is None or recorded[0] != turn or recorded[2]:
            return None
        starts = recorded[1]
    if starts and not _conversation_has_run(omh_home, hermes_home, key):
        message = DEFINE_FIRST_MESSAGE
    else:
        run = _active_run(omh_home, hermes_home, key)
        if not run:
            return None
        message = mid_run_message(run)
    with _lock:
        # Two calls of one turn can both reach here; the first one to come back blocks.
        recorded = _turns.get(key)
        if recorded is None or recorded[0] != turn or recorded[2]:
            return None
        _turns[key] = (turn, recorded[1], True)
    return {"action": "block", "message": message}


def reset_dag_define_gate() -> None:
    """Test seam: forget every recorded turn."""
    with _lock:
        _turns.clear()


__all__ = [
    "DEFINE_FIRST_MESSAGE",
    "RESEND_PASSES",
    "delegate_before_define_directive",
    "mid_run_message",
    "note_turn",
    "reset_dag_define_gate",
    "starts_dag_run",
]
