"""The unfinished work OMH holds for a conversation, as facts for Hermes' compaction summary.

When Hermes compacts a session, the summarizer sees the transcript it is
about to drop and whatever the memory provider hands back from
`on_pre_compress`. A dag-ulw run or an `omh_todo` plan lives on disk and
survives, but the summary that replaces the turns does not know it exists
unless the transcript happened to say so clearly. The model then re-derives
its own work after compaction, or forgets a run with nodes still open.

So `on_pre_compress` adds these lines to the text it returns. Hermes
JSON-encodes that text and tells its summarizer to read it "only as source
material to preserve in the summary, not as instructions"
(`agent/context_compressor.py`, `_memory_provider_section`), so every line is
a fact about a record and none asks for anything: no "call", no "continue".

What counts as live work, read the way the other views read it:

* a dag-ulw run of this conversation that is not finished (`dag_run.run_state`
  outside `dag_run.FINISHED_STATES`), looked up under every segment of the
  conversation as `omh_dag` and the open-run nudge look it up, with its
  open nodes and their derived states;
* this session's plan todo when the shared projection says it is
  ``established`` (open items, fresh, this session's own). A plan Hermes'
  native `todo_list` wrote (``source: todo_list``) is left out: Hermes folds
  its own todo list back into the compacted transcript verbatim
  (`_fold_todo_snapshot`, `agent/conversation_compression.py`), so a second
  copy here would only repeat it.

Not here: an `omh_loop` loop is home-wide and carries no session, so nothing
says it belongs to this conversation; the active-workflow reminder is
re-projected on every turn by `pre_llm_call` and needs no carrying.

Bounded and empty when idle. With no live work the result is ``""`` and the
provider's return value is byte-identical to what it was before this
existed. Otherwise at most `MAX_RUNS` runs, `MAX_NODES_LISTED` nodes a run,
`MAX_TODO_ITEMS_LISTED` open items, each text cut to `MAX_TEXT_CHARS`, and
the whole at most `MAX_WORK_STATE_CHARS`: the newest run, then the plan,
then older runs, a line past the room cut to it and the rest counted. That total is Hermes' tail
allowance (`_MEMORY_CONTEXT_TAIL_CHARS` in `agent/context_engine.py`): the
host keeps 6,000 characters of provider text and, past that, the first 4,000
and the last 1,500, so lines this long placed last survive even an elision.
The provider also shrinks its memory-block budget by the same length, so the
blocks and the facts together take no more room than the blocks did alone.

Metadata only: run and node ids, labels, the run's stated goal, item texts
and states -- what the records already hold, model declarations and parent
settlements rather than observed execution. Never raises: a read that fails
adds nothing.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sqlite3
import time
from typing import Any, Final

from . import dag_run
from .kanban_board_reader import conversation_session_ids
from .native_tools import NATIVE_TODO_TOOL
from .runtime_reader import read_omh_todo, reading_session_id
from .tools import dag_tool

MAX_RUNS: Final = 3
MAX_NODES_LISTED: Final = 6
MAX_TODO_ITEMS_LISTED: Final = 10
MAX_TEXT_CHARS: Final = 100
MAX_WORK_STATE_CHARS: Final = 1_500
MIN_LINE_CHARS: Final = 120
HEADER: Final = (
    "OMH records of unfinished work in this conversation, as stored when compaction began "
    "(declared states, not observed execution):"
)
# Nodes a run still counts as open work; satisfied, superseded and cancelled nodes are not listed.
_CLOSED_NODE_STATES: Final = frozenset({*dag_run.SATISFIED, "superseded", "cancelled"})


def _cut(text: object, limit: int = MAX_TEXT_CHARS) -> str:
    plain = " ".join(str(text or "").split())
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"


def _run_line(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> str:
    tally = dag_run.counts(record, derived)
    goal = f", goal: {_cut(record.get('goal'))}" if record.get("goal") else ""
    head = (f"- dag-ulw run {record['run']} ({_cut(record.get('name'), dag_run.MAX_NAME_CHARS)}){goal}. "
            f"Run state {dag_run.run_state(record, derived)}; {tally['done']}/{tally['total']} nodes done.")
    open_nodes = [node for node in record["nodes"] if derived[str(node["id"])]["state"] not in _CLOSED_NODE_STATES]
    shown = [f"{node['id']} \"{_cut(node.get('label'), 60)}\" {derived[str(node['id'])]['state']}"
             for node in open_nodes[:MAX_NODES_LISTED]]
    more = f"; {len(open_nodes) - MAX_NODES_LISTED} more" if len(open_nodes) > MAX_NODES_LISTED else ""
    return f"{head} Open nodes: {'; '.join(shown)}{more}." if shown else head


def _run_lines(omh_home: Path, hermes_home: Path, durable: str, now: float) -> list[str]:
    if not (omh_home / "runtime" / dag_run.DAG_DIRNAME).is_dir():
        return []
    segments = sorted({durable, *conversation_session_ids(hermes_home, durable)})
    runs = [record for segment in segments for record, _path in dag_run.session_runs(omh_home, segment)]
    if not runs:
        return []
    runs.sort(key=lambda record: float(record.get("updated_at") or 0.0), reverse=True)
    children = dag_tool._children(omh_home, segments, hermes_home)
    lines = []
    for record in runs:
        derived = dag_run.derive(record, children, now)
        if dag_run.run_state(record, derived) in dag_run.FINISHED_STATES:
            continue
        lines.append(_run_line(record, derived))
        if len(lines) == MAX_RUNS:
            break
    return lines


def _todo_line(omh_home: Path, hermes_home: Path, session: str) -> str:
    todo = read_omh_todo(omh_home, hermes_home, session_ref=session)
    if todo.get("status") != "established" or todo.get("source") == NATIVE_TODO_TOOL:
        return ""
    counts = todo["counts"]
    stamps = [f"plan stage {todo['plan_stage']}" if todo.get("plan_stage") else "",
              f"template {todo['template']}" if todo.get("template") else "",
              "deferred" if todo.get("deferred_reason") else ""]
    stamped = "; ".join(stamp for stamp in stamps if stamp)
    title = f" \"{_cut(todo.get('title'), 80)}\"" if todo.get("title") else ""
    head = (f"- Plan todo{title}{f' ({stamped})' if stamped else ''}: "
            f"{counts['done']}/{counts['total']} items done.")
    open_items = [item for item in todo["items"] if item["state"] != "done"]
    shown = [f"{item['state']}: {_cut(item['text'])}" for item in open_items[:MAX_TODO_ITEMS_LISTED]]
    more = f"; {len(open_items) - MAX_TODO_ITEMS_LISTED} more open" if len(open_items) > MAX_TODO_ITEMS_LISTED else ""
    return f"{head} Open items: {'; '.join(shown)}{more}."


def _fit(lines: list[str]) -> str:
    """The header and the lines in `MAX_WORK_STATE_CHARS`: a line past the room is cut, and once less than
    `MIN_LINE_CHARS` is left the rest are counted rather than listed."""
    if not lines:
        return ""
    kept = [HEADER]
    for index, line in enumerate(lines):
        rest = len(lines) - index - 1
        reserve = len(f"\n- {rest} more record line(s) not listed.") if rest else 0
        room = MAX_WORK_STATE_CHARS - len("\n".join(kept)) - 1 - reserve
        if room < MIN_LINE_CHARS:
            kept.append(f"- {len(lines) - index} more record line(s) not listed.")
            break
        kept.append(_cut(line, room))
    return "\n".join(kept)


def work_state_facts(
    *, omh_home: Path, hermes_home: Path | None, session_id: object, now: float | None = None,
) -> str:
    """The facts for this conversation's unfinished OMH work, or ``""`` when there is none. Never raises."""
    session = str(session_id or "").strip()
    if not session or hermes_home is None:
        return ""
    try:
        durable = reading_session_id(hermes_home, session)
        if not durable:
            return ""
        lines = _run_lines(omh_home, hermes_home, durable, time.time() if now is None else now)
        todo = _todo_line(omh_home, hermes_home, session)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
        return ""
    # The newest run first, then the plan, so the two most likely to matter keep their heads when room runs out.
    return _fit([*lines[:1], todo, *lines[1:]] if todo else lines)


__all__ = [
    "MAX_NODES_LISTED",
    "MAX_RUNS",
    "MAX_TEXT_CHARS",
    "MAX_TODO_ITEMS_LISTED",
    "MAX_WORK_STATE_CHARS",
    "work_state_facts",
]
