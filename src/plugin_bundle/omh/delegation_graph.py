"""One conversation's delegated work as a graph: `delegation_graph/v1`, nodes, edges and layers.

The structure comes from records, never from timing guesses:

* the delegation ledger (`delegation_ledger.py`): which child each
  `delegate_task` call started, under which parent and in which turn;
* an `omh_team/v1` record for the conversation: parts, their titles and
  their recorded `depends_on`;
* an `omh_dag/v1` run (`dag_run.py`): its nodes, labels, planned
  categories and recorded `depends_on`, and the children the delegation
  ledger bound to its nodes by their goal marker;
* for the opt-in fanout lane, the frozen `fanout_contract/v2` and its roster
  (passed in, already verified, by the HUD reader).

Facts about a child are read from Hermes' own `state.db`, read-only: the model
its session row recorded (or the one model its usage rows observed), its
reasoning effort, whether it has made a model call, the goal Hermes stored
for its task, and the output tokens its row has counted so far (Hermes adds
each API call's to the child's own row as the call returns; ``None`` while
the row says 0 or was not read). Nothing reads current config.

Every field without evidence is ``?``:

* **category** is the route OMH recorded for the parent session when the child
  started, and only while the child's observed model matches that route.
  Otherwise ``inherit`` when the child's observed model equals its parent's
  recorded model, otherwise ``?``. A dag node no child has taken yet shows the
  category its run planned. The mixture-chain projection the HUD rows use is
  not consulted.
* **model** is what Hermes recorded for the child, never the configured route.
* **state** comes from `subagent_stop`, a recorded model call, or the team's
  own lifecycle. A child whose session closed for compaction is read through
  the continuation Hermes recorded for it: its state, model calls and output
  tokens are those of every segment it ran in. With no continuation recorded
  it is ``unknown``, never done and never running.

A conversation is every segment of it (`graph_segments`): Hermes' rotating
compaction (``compression.in_place: false``) moves a conversation to a new
session id mid-run, and its ledger children, team record and dag run stay
under the segment that wrote them. A stop the ledger could not join (it names
a parent segment or a child segment the start did not) joins the child whose
id it names, or whose continuation it names.

A title is never ``?``: where no record names one, a team part or fanout unit
reads its unit id, a dag node its node id, and a child ``session <tail>``
(`session_tail`).

An edge is a dispatch (a parent started this child), a recorded `depends_on`,
or, in a dag run, where a node added mid-run came from: a repair (from the
node it repairs) or an extend (from the node whose check found the work
missing). Dispatch waves of one parent (the children one turn started) are
grouped as ``wave N · HH:MM``; that is order, not dependency, and no edge is
drawn for it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Final
from urllib.parse import quote

from .dag_core import layer_of
from .dag_run import (
    ADDED_ORIGIN_KINDS,
    FINISHED_STATES,
    HANDOFF_NOT_CHECKED,
    bound_children,
    derive,
    goal_verdict,
    handoff_unchecked,
    node_role,
    run_state,
    session_runs,
)
from .delegation_ledger import (
    child_title,
    ledger_key,
    read_ledger,
    title_from_goal,
    valid_observed_route,
    with_unjoined_stop,
)
from .live_session import conversation_segments
from .subagent_graph import _roster_progress_fields as roster_progress_fields

GRAPH_SCHEMA_VERSION: Final = "delegation_graph/v1"
GRAPH_NODE_LIMIT: Final = 48
GRAPH_BYTE_LIMIT: Final = 24_576
# The `sessions` columns a lane's `usage` reads, in the order `_usage` takes them.
USAGE_COLUMNS: Final = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "actual_cost_usd", "estimated_cost_usd")
GRAPH_LINGER_SECONDS: Final = 15 * 60
CHILD_STALE_SECONDS: Final = 30 * 60
TEAM_FILE_LIMIT: Final = 16
TEAM_RECORD_BYTES: Final = 262_144
TITLE_LIMIT: Final = 120
OPENER_CHARS: Final = 400
# A background unit's stored result is read for its per-task `route` only; one past this is not parsed.
RESULT_JSON_BYTES: Final = 1_048_576
COMPACTION_END_REASON: Final = "compression"
GRAPH_CLAIM_BOUNDARY: Final = (
    "Delegation structure and states as Hermes' hooks, state.db and OMH's own records reported them. A category is "
    "OMH's recorded route, shown only where the child's observed model matches it, or a dag node's planned category "
    "before any child took it. Not execution, verification, review, CI or merge evidence."
)
SETTLED_STATES: Final = frozenset({"done", "failed", "interrupted", "unknown"})
_FAILED_STOPS: Final = frozenset({"failed", "error", "timeout"})
_FANOUT_SUCCESS: Final = frozenset({"completed", "already_completed", "dry_run_planned"})


def inactive_graph(reason: str, *, scope: str = "session") -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "status": "inactive",
        "reason": reason,
        "scope": scope,
        "source": "",
        "name": "",
        "nodes": [],
        "edges": [],
        "layers": [],
        "hidden_nodes": 0,
        "claim_boundary": GRAPH_CLAIM_BOUNDARY,
    }


def graph_fingerprint(graph: Mapping[str, Any]) -> str:
    """What a reader would see, minus the clock: structure, states and labels, never elapsed time."""
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    keys = ("id", "kind", "title", "category", "model", "effort", "state", "status", "waits_on", "group")
    shape = {
        "nodes": [{key: node.get(key) for key in keys} for node in nodes if isinstance(node, Mapping)],
        "edges": [[edge.get("from"), edge.get("to"), edge.get("kind")] for edge in edges if isinstance(edge, Mapping)],
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def session_tail(session_id: str) -> str:
    """A child session's short id as the native HUD rows name it (their `task_id`, `hermes_delegation`)."""
    return session_id.rsplit("_", 1)[-1][:8]


SUMMARY_LIMIT: Final = 80
# Where a dag node prompt's first clause ends: a field label (dag-ulw's node prompt: TASK, DELIVERABLE, SCOPE, VERIFY,
# STOP WHEN, CONTEXT), a line end or a sentence's end.
_PROMPT_CLAUSE_END = re.compile(r"\s(?:TASK|DELIVERABLE|SCOPE|VERIFY|STOP WHEN|CONTEXT):|\n|(?<=[.!?])\s")


def _prompt_summary(prompt: object) -> str:
    """A dag node prompt's first clause, without a leading `TASK:` (any case), in `SUMMARY_LIMIT` characters; "" for
    none.

    The clause is cut from the raw prompt and only then cleaned (`_text`): cleaning first drops the line ends that
    separate dag-ulw's one-field-a-line prompt, and the task would run into `DELIVERABLE:`.
    """
    if not isinstance(prompt, str):
        return ""
    raw = re.sub(r"^\s*TASK:\s*", "", prompt.strip(), flags=re.IGNORECASE)
    return _text(_PROMPT_CLAUSE_END.split(raw, maxsplit=1)[0], 2000).strip().rstrip(".")[:SUMMARY_LIMIT]


def _text(value: object, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip() if ch.isprintable())[:limit]


def same_model(observed: str, recorded: str) -> bool:
    """One model named twice: equal ignoring case, or equal once a provider path is dropped."""
    left, right = observed.strip().casefold(), recorded.strip().casefold()
    if not left or not right:
        return False
    return left == right or left.rsplit("/", 1)[-1] == right.rsplit("/", 1)[-1]


# ── state.db, read-only ──────────────────────────────────────────────────


def _connect(hermes_home: Path) -> sqlite3.Connection | None:
    state_db = Path(hermes_home) / "state.db"
    if not state_db.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{quote(str(state_db))}?mode=ro", uri=True, timeout=0.25)
    except sqlite3.Error:
        return None


def graph_segments(hermes_home: Path, session_id: str) -> list[str]:
    """``session_id``, then the other segments of its conversation (`live_session.conversation_segments`).

    Hermes' default in-place compaction keeps one id and writes no second row,
    so this is ``[session_id]`` there, and wherever the lineage cannot be read.
    """
    try:
        connection = _connect(hermes_home)
    except OSError:  # Python 3.11's `Path.is_file` raises where the home cannot be searched
        return [session_id]
    try:
        return _segments(connection, session_id)
    finally:
        if connection is not None:
            connection.close()


def _segments(connection: sqlite3.Connection | None, session_id: str) -> list[str]:
    """`graph_segments` on a connection the caller owns."""
    if connection is None:
        return [session_id]
    try:
        others = conversation_segments(connection, session_id) - {session_id}
    except sqlite3.Error:
        return [session_id]
    return [session_id, *sorted(others)]


def _continuations(
    connection: sqlite3.Connection | None, facts: Mapping[str, Any], sessions: Sequence[str]
) -> dict[str, list[str]]:
    """Each of ``sessions`` whose row Hermes closed for compaction, with the later segments its conversation ran in.

    Reads only when such a row exists, which Hermes' default in-place
    compaction never writes.
    """
    compacted = [session for session in dict.fromkeys(sessions)
                 if (facts["sessions"].get(session) or {}).get("end_reason") == COMPACTION_END_REASON]
    if not compacted or connection is None:
        return {}
    try:
        later = {session: sorted(conversation_segments(connection, session) - {session}) for session in compacted}
    except sqlite3.Error:
        return {}
    return {session: segments for session, segments in later.items() if segments}


def _carry_on(
    hermes_home: Path, connection: sqlite3.Connection, facts: dict[str, Any], later: Mapping[str, Sequence[str]]
) -> None:
    """Read each compacted session as the conversation it went on in: the facts of its tips, with its segments summed.

    A tip is a later segment Hermes did not close for compaction; the session
    is open while any tip is (a stale sibling beside the continuation is a
    tip too). Model calls, their last time and output tokens add up over the
    segments, the way Hermes' own per-agent count does. A session whose later
    rows cannot be read keeps its own facts, so it stays ``compacted``.
    """
    extra = state_facts(hermes_home, [segment for segments in later.values() for segment in segments], [],
                        connection=connection)
    for session, segments in later.items():
        rows = [extra["sessions"][segment] for segment in segments if segment in extra["sessions"]]
        tips = [row for row in rows if row["end_reason"] != COMPACTION_END_REASON]
        if not tips:
            continue
        live = [tip for tip in tips if tip["ended_at"] is None]
        last = (live or tips)[0]
        row = facts["sessions"][session]
        written = [item["output_tokens"] for item in (row, *rows) if item["output_tokens"]]
        facts["sessions"][session] = {**row, "ended_at": last["ended_at"], "end_reason": last["end_reason"],
                                      "output_tokens": sum(written) if written else None,
                                      "usage": _sum_usage([item["usage"] for item in (row, *rows)])}
        usages = [usage for usage in (facts["usage"].get(session), *(extra["usage"].get(s) for s in segments)) if usage]
        if usages:
            models = {usage["model"] for usage in usages if usage["model"]}
            seen = [usage["last_seen"] for usage in usages if usage["last_seen"] is not None]
            facts["usage"][session] = {"rows": sum(usage["rows"] for usage in usages),
                                       "model": models.pop() if len(models) == 1 else "",
                                       "last_seen": max(seen) if seen else None}


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _price(value: Any) -> float | None:
    """A recorded cost, zero included; None where Hermes recorded none (NULL, or not a finite, non-negative number)."""
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _usage(values: Sequence[Any], output: Any) -> dict[str, Any] | None:
    """What a session's row counted besides its output, in `USAGE_COLUMNS` order; None when it counted none.

    ``output`` is the row's output tokens, kept under ``output`` beside the other counts.
    ``cost_usd`` is Hermes' recorded cost: the actual one wherever the row holds one (a provider-reported 0 too, as
    `actual_cost_usd` stays NULL until a provider reports one), else a positive estimate, marked ``cost_estimated``.
    A session Hermes did not price carries no cost, and no token is converted into one here.
    """
    uncached, read, write = (_count(value) for value in values[:3])
    actual, estimated = _price(values[3]), _price(values[4]) or 0.0
    if not (uncached or read or write or actual is not None or estimated):
        return None
    usage: dict[str, Any] = {"input": uncached, "cache_read": read, "cache_write": write, "output": _count(output)}
    if actual is not None:
        usage["cost_usd"] = actual
    elif estimated:
        usage["cost_usd"] = estimated
        usage["cost_estimated"] = True
    return usage


def _sum_usage(items: Sequence[Mapping[str, Any] | None]) -> dict[str, Any] | None:
    """The usage of a conversation's segments (or of a row and its auxiliary calls) added up.

    The cost is the priced parts' sum, ``cost_partial`` where some counted part (or part of one) has no cost, so the
    figure is a floor; no cost where no part was priced.
    """
    held = [item for item in items if item]
    if not held:
        return None
    total: dict[str, Any] = {key: sum(item[key] for item in held)
                             for key in ("input", "cache_read", "cache_write", "output")}
    priced = [item for item in held if "cost_usd" in item]
    if priced:
        total["cost_usd"] = sum(item["cost_usd"] for item in priced)
        if any(item.get("cost_estimated") for item in priced):
            total["cost_estimated"] = True
        if len(priced) < len(held) or any(item.get("cost_partial") for item in priced):
            total["cost_partial"] = True
    return total


# `session_model_usage` tasks that are main-loop calls, already counted in the `sessions` row: every value Hermes
# gives `agent._turn_route_task`, which `agent/turn_usage.py` passes to `update_token_counts(task=...)` (its docstring
# in `hermes_state_usage.py`: a per-turn route's calls "count in the session totals and land in session_model_usage
# under that task"). Today one, `agent/voice_turn_route.py`'s `TASK`. An auxiliary task, by contrast, is any name a
# caller hands `auxiliary_client` (`agent/aux_accounting.record_aux_usage`) or `background_review`, an open set, so
# the route tasks are the closed list here and a new one must join it.
ROUTE_TASKS: Final = ("voice_chat",)


def _auxiliary_usage(
    connection: sqlite3.Connection, marks: str, ids: Sequence[str], columns: set[str]
) -> dict[str, dict[str, Any]]:
    """Each session's auxiliary calls, summed from `session_model_usage`, in `_usage`'s shape.

    Hermes records an auxiliary call (compression, title generation, vision, ...) only there, under its task name,
    and never in the `sessions` row (`record_auxiliary_usage`), so these add to the row's counts. The main loop's
    own rows there repeat what the row already holds and are left out: task ``''``, a per-turn route's task
    (`ROUTE_TASKS`), and any row with a `cost_status`, which only the main loop writes (`record_auxiliary_usage`
    takes none, and the runtime worker refuses one for an auxiliary call). A table without `task` cannot tell the
    two apart and gives nothing. An auxiliary row records no actual cost, so a positive estimate prices it; one with
    tokens but no estimate is unpriced (Hermes stores an unknown estimate as 0), which makes the sum a floor.
    """
    if "task" not in columns:
        return {}

    def column(name: str) -> str:
        return f"COALESCE({name}, 0)" if name in columns else "0"

    tokens = " + ".join(column(name) for name in
                        ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
    actual, estimated = column("actual_cost_usd"), column("estimated_cost_usd")
    figure = f"CASE WHEN {actual} > 0 THEN {actual} WHEN {estimated} > 0 THEN {estimated} END"
    routes = ", ".join("?" for _ in ROUTE_TASKS)
    unstated = " AND cost_status IS NULL" if "cost_status" in columns else ""
    found: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        f"SELECT session_id, SUM({column('input_tokens')}), SUM({column('cache_read_tokens')}), "
        f"SUM({column('cache_write_tokens')}), SUM({column('output_tokens')}), SUM({figure}), "
        f"SUM(CASE WHEN {actual} > 0 THEN 0 WHEN {estimated} > 0 THEN 1 ELSE 0 END), "
        f"SUM(CASE WHEN ({tokens}) > 0 AND {figure} IS NULL THEN 1 ELSE 0 END) "
        f"FROM session_model_usage WHERE session_id IN ({marks}) AND COALESCE(task, '') <> '' "
        f"AND task NOT IN ({routes}){unstated} GROUP BY session_id",
        (*ids, *ROUTE_TASKS),
    ):
        usage = {"input": _count(row[1]), "cache_read": _count(row[2]), "cache_write": _count(row[3]),
                 "output": _count(row[4])}
        cost = _price(row[5])
        if cost:
            usage["cost_usd"] = cost
            if row[6]:
                usage["cost_estimated"] = True
            if row[7]:
                usage["cost_partial"] = True
        elif not any(usage.values()):
            continue
        found[str(row[0])] = usage
    return found


def session_usage(hermes_home: Path, session_id: str) -> dict[str, Any] | None:
    """What Hermes recorded for one chat, its compaction segments added up: the figures of the pane's usage board.

    ``session_id`` is the chat asked about, so the pane can tell this chat's figures from the last one's.
    ``model`` is the one the chat's own row names, ``output`` its output tokens and, besides
    them, the `_usage` keys; each segment's auxiliary calls count with it (`_auxiliary_usage`). The cost is what
    Hermes priced, marked ``cost_partial`` where some counted part is unpriced, and no token is turned into one.
    ``None`` where the chat has no row or its row counted nothing.
    """
    try:
        connection = _connect(hermes_home)
    except OSError:  # Python 3.11's `Path.is_file` raises where the home cannot be searched
        return None
    if connection is None:
        return None
    try:
        ids = _segments(connection, session_id)
        facts = state_facts(hermes_home, ids, [], connection=connection)
    finally:
        connection.close()
    rows = [facts["sessions"][item] for item in ids if item in facts["sessions"]]
    usage = _sum_usage([row["usage"] for row in rows]) or {}
    output = sum(row["usage"]["output"] if row["usage"] else row["output_tokens"] or 0 for row in rows)
    if not (usage or output):
        return None
    model = (facts["sessions"].get(session_id) or rows[0])["model"]
    return {"session_id": session_id, "model": model, **usage, "output": output}


# How many child sessions one run's usage reads: `state_facts` takes 160 ids a call, and a child's compaction
# segments count among them, so a run past this many children is read in part and says so (`children_unread`).
RUN_USAGE_CHILD_LIMIT: Final = 64


def run_usage(hermes_home: Path, child_sessions: Sequence[str]) -> dict[str, Any] | None:
    """What Hermes recorded for a run's children, added up: the closing figures of a dag-ulw run.

    ``child_sessions`` are the sessions of every child the run bound, each attempt's included, so a retried or
    repaired node's earlier child counts too. Each child is read as `session_usage` reads a chat (its compaction
    segments and auxiliary calls with it). ``children`` counts the children Hermes counted anything for,
    ``children_unrecorded`` those it counted nothing for; ``priced`` the counted ones it put a cost on. The cost is
    Hermes' recorded one only, ``cost_partial`` where a counted child has none, so the figure is a floor; no token
    is turned into a price, and nothing is compared with a model the run did not use. ``None`` where no child
    counted anything or the database cannot be read.
    """
    wanted = [item for item in dict.fromkeys(child_sessions) if item]
    unread = max(0, len(wanted) - RUN_USAGE_CHILD_LIMIT)
    wanted = wanted[:RUN_USAGE_CHILD_LIMIT]
    if not wanted:
        return None
    try:
        connection = _connect(hermes_home)
    except OSError:  # Python 3.11's `Path.is_file` raises where the home cannot be searched
        return None
    if connection is None:
        return None
    try:
        segments = {child: _segments(connection, child) for child in wanted}
        ids = [item for listed in segments.values() for item in listed]
        facts: dict[str, Any] = {"sessions": {}}
        for at in range(0, len(ids), 160):
            facts["sessions"].update(state_facts(hermes_home, ids[at:at + 160], [], connection=connection)["sessions"])
    finally:
        connection.close()
    per_child: list[dict[str, Any]] = []
    for child in wanted:
        rows = [facts["sessions"][item] for item in segments[child] if item in facts["sessions"]]
        usage = _sum_usage([row["usage"] for row in rows])
        output = sum(row["usage"]["output"] if row["usage"] else row["output_tokens"] or 0 for row in rows)
        if usage:
            per_child.append({**usage, "output": output})
        elif output:
            per_child.append({"input": 0, "cache_read": 0, "cache_write": 0, "output": output})
    total = _sum_usage(per_child)
    if total is None:
        return None
    result: dict[str, Any] = {
        **total,
        "children": len(per_child),
        "children_unrecorded": len(wanted) - len(per_child),
        "priced": sum(1 for usage in per_child if "cost_usd" in usage),
    }
    if unread:
        # Children past the cap were not read: their spend is missing, so a cost is a floor.
        result["children_unread"] = unread
        if "cost_usd" in result:
            result["cost_partial"] = True
    return result


def _token_text(count: int) -> str:
    """`410`, `12.6k`, `1.2m`: the pane's and the TUI's token figure (`tokenCountText`, `panels._token_count_text`)."""
    if count < 1000:
        return str(count)
    amount, unit = (count / 1000, "k") if count < 999_950 else (count / 1_000_000, "m")
    return f"{amount:.1f}{unit}"


def run_usage_text(usage: Mapping[str, Any]) -> str:
    """`4 children · 182.4k tokens · cache 71.3% · $0.4210 (3/4 priced)`: `run_usage` as one line of figures.

    Tokens are every count (uncached input, cache read, cache write, output); the cache share is cache read over
    the prompt side, as the pane's figure is. The cost is Hermes' recorded one: ``≥`` where a counted child has
    none, ``~`` where a part is Hermes' estimate, and ``cost not recorded`` where nothing was priced.
    """
    prompt = usage["input"] + usage["cache_read"] + usage["cache_write"]
    said = [f"{usage['children']} child{'' if usage['children'] == 1 else 'ren'}",
            f"{_token_text(prompt + usage['output'])} tokens"]
    if prompt:
        said.append(f"cache {usage['cache_read'] / prompt * 100:.1f}%")
    if "cost_usd" in usage:
        mark = "≥" if usage.get("cost_partial") else "~" if usage.get("cost_estimated") else ""
        said.append(f"{mark}${usage['cost_usd']:.4f} ({usage['priced']}/{usage['children']} priced)")
    else:
        said.append("cost not recorded")
    if usage["children_unrecorded"]:
        said.append(f"{usage['children_unrecorded']} with no record")
    if usage.get("children_unread"):
        said.append(f"{usage['children_unread']} not read")
    return " · ".join(said)


def closing_usage(hermes_home: Path, record: Mapping[str, Any],
                  children: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """What every child this dag run bound used, as Hermes recorded it (`run_usage`), or None.

    Every child bound to the run counts, a retried or repaired attempt's earlier child too, since its spend is
    spent. A node the parent did itself (``lane: parent``) or a fanout owner ran has no child here and is in
    neither the counts nor the cost: those sit in the parent's own row and the fanout receipt.
    """
    bound = bound_children(children, str(record["run"]))
    sessions = [str(child["child_session_id"]) for listed in bound.values() for child in listed
                if child.get("child_session_id")]
    return run_usage(hermes_home, sessions)


def _effort(config: Mapping[str, Any]) -> str:
    reasoning = config.get("reasoning_config")
    if isinstance(reasoning, Mapping) and reasoning.get("enabled"):
        return _text(reasoning.get("effort"), 40)
    return ""


def state_facts(
    hermes_home: Path, session_ids: Sequence[str], delegation_ids: Sequence[str],
    *, connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """What Hermes recorded about these sessions and delegations. Each read is on its own: one that fails is absent.

    ``connection``: the build's own, which the caller closes; without it one
    is opened under ``hermes_home`` for this read.
    """
    facts: dict[str, Any] = {
        "read": False, "usage_read": False, "sessions": {}, "usage": {}, "openers": {}, "delegations": {},
    }
    ids = [item for item in dict.fromkeys(session_ids) if item][:160]
    own = connection is None
    connection = _connect(hermes_home) if own else connection
    if connection is None:
        return facts
    try:
        marks = ",".join("?" for _ in ids)
        if ids:
            try:
                columns = {str(row[1]) for row in connection.execute('PRAGMA table_info("sessions")')}
                ended = "ended_at" if "ended_at" in columns else "NULL"
                reason = "end_reason" if "end_reason" in columns else "NULL"
                written = "output_tokens" if "output_tokens" in columns else "NULL"
                counted = ", ".join(name if name in columns else "NULL" for name in USAGE_COLUMNS)
                for row in connection.execute(
                    f"SELECT id, model, model_config, {ended}, {reason}, {written}, {counted} "
                    f"FROM sessions WHERE id IN ({marks})",
                    ids,
                ):
                    try:
                        config = json.loads(row[2]) if isinstance(row[2], str) else {}
                    except ValueError:
                        config = {}
                    config = config if isinstance(config, dict) else {}
                    facts["sessions"][str(row[0])] = {
                        "model": _text(row[1]),
                        "effort": _effort(config),
                        "ended_at": row[3] if isinstance(row[3], (int, float)) else None,
                        "end_reason": _text(row[4], 40),
                        "output_tokens": row[5] if isinstance(row[5], int) and row[5] > 0 else None,
                        "usage": _usage(row[6:], row[5]),
                    }
                facts["read"] = True
            except sqlite3.Error:
                pass
            try:
                usage_columns = {str(row[1]) for row in connection.execute('PRAGMA table_info("session_model_usage")')}
                # An auxiliary call (compression, vision, ...) is a row under its task name on the aux route's model:
                # a call, so it counts and dates the child's activity, but not the model that answered the child.
                # `hermes_delegation` reads it alike.
                answering = (
                    "GROUP_CONCAT(DISTINCT CASE WHEN COALESCE(task, '') = '' THEN NULLIF(model, '') END)"
                    if "task" in usage_columns
                    else "GROUP_CONCAT(DISTINCT NULLIF(model, ''))"
                )
                for row in connection.execute(
                    f"SELECT session_id, COUNT(*), {answering}, MAX(last_seen) "
                    f"FROM session_model_usage WHERE session_id IN ({marks}) GROUP BY session_id",
                    ids,
                ):
                    models = [part for part in str(row[2] or "").split(",") if part]
                    facts["usage"][str(row[0])] = {
                        "rows": int(row[1] or 0),
                        "model": _text(models[0]) if len(models) == 1 else "",
                        "last_seen": row[3] if isinstance(row[3], (int, float)) else None,
                    }
                facts["usage_read"] = True  # an empty answer now means no model call, not an unread table
            except sqlite3.Error:
                pass
            try:
                auxiliary = _auxiliary_usage(connection, marks, ids, usage_columns) if facts["usage_read"] else {}
            except sqlite3.Error:
                auxiliary = {}
            for session, extra in auxiliary.items():
                row = facts["sessions"].get(session)
                if row is None:
                    continue
                own_usage = row["usage"] or (
                    {"input": 0, "cache_read": 0, "cache_write": 0, "output": row["output_tokens"]}
                    if row["output_tokens"] else None
                )
                row["usage"] = _sum_usage([own_usage, extra])
            try:
                for row in connection.execute(
                    f"SELECT session_id, substr(content, 1, {OPENER_CHARS}) FROM messages WHERE rowid IN ("
                    f"SELECT MIN(rowid) FROM messages WHERE session_id IN ({marks}) AND role = 'user' "
                    "GROUP BY session_id)",
                    ids,
                ):
                    facts["openers"][str(row[0])] = title_from_goal(row[1])
            except sqlite3.Error:
                pass
        delegations = [item for item in dict.fromkeys(delegation_ids) if item][:32]
        if delegations:
            try:
                columns = {str(row[1]) for row in connection.execute('PRAGMA table_info("async_delegations")')}
                # Hermes 0.22.5+ keeps each finished child's result, `route` included, in `result_json`.
                results = (f"CASE WHEN length(result_json) <= {RESULT_JSON_BYTES} THEN result_json END"
                           if "result_json" in columns else "NULL")
                for row in connection.execute(
                    f"SELECT delegation_id, task_json, {results} FROM async_delegations WHERE delegation_id IN ("
                    + ",".join("?" for _ in delegations) + ")",
                    delegations,
                ):
                    try:
                        task = json.loads(row[1]) if isinstance(row[1], str) else {}
                    except ValueError:
                        task = {}
                    if not isinstance(task, dict):
                        continue
                    goals = task.get("goals") if isinstance(task.get("goals"), list) else []
                    facts["delegations"][str(row[0])] = {
                        "goals": [title_from_goal(goal) for goal in goals[:64]],
                        "model": _text(task.get("model")),
                        "routes": _result_routes(row[2]),
                    }
            except sqlite3.Error:
                pass
    finally:
        if own:
            connection.close()
    return facts


# ── omh_team, read-only ──────────────────────────────────────────────────


def team_unit_state(unit: Mapping[str, Any]) -> str:
    """Hand-mirror of `omh.workflows.team.unit_state` (the bundle cannot import it); a parity test holds them."""
    if unit.get("blocked"):
        return "blocked"
    attempts = unit.get("attempts") or []
    attempt = attempts[-1] if attempts else None
    if not isinstance(attempt, Mapping):
        return "waiting"
    check = attempt.get("check")
    if isinstance(check, Mapping) and check.get("outcome") == "passed":
        return "accepted"
    if attempt.get("returned_at"):
        return "awaiting_check"
    if attempt.get("n", 1) > 1:
        return "repairing"
    if attempt.get("dispatch"):
        return "dispatched"
    return "prepared"


def _team_record(omh_home: Path, session_id: str) -> tuple[dict[str, Any], float] | None:
    """The conversation's most recently written `omh_team/v1` record, or None."""
    directory = Path(omh_home) / "runtime" / "teams" / ledger_key(session_id)
    try:
        paths = sorted(
            (path for path in directory.iterdir() if path.suffix == ".json" and not path.name.startswith(".")
             and not path.is_symlink()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:TEAM_FILE_LIMIT]
    except OSError:
        return None
    for path in paths:
        try:
            if path.stat().st_size > TEAM_RECORD_BYTES:
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, UnicodeDecodeError, ValueError, RecursionError):
            continue
        if not isinstance(raw, dict) or raw.get("schema_version") != "omh_team/v1":
            continue
        units = raw.get("units")
        if not isinstance(units, list) or not units:
            continue
        ids = [unit.get("unit_id") for unit in units if isinstance(unit, dict)]
        if len(ids) != len(units) or not all(isinstance(item, str) and item for item in ids):
            continue
        if not all(
            isinstance(unit.get("depends_on"), list) and all(dep in ids for dep in unit["depends_on"])
            and isinstance(unit.get("attempts", []), list)
            for unit in units
        ):
            continue
        return raw, mtime
    return None


_TEAM_VIEW: Final = {
    "waiting": ("waiting", "waiting"),
    "prepared": ("waiting", "prepared"),
    "dispatched": ("dispatched", "dispatched"),
    "awaiting_check": ("waiting", "awaiting check"),
    "repairing": ("waiting", "repair prepared"),  # a repair attempt with no dispatch yet; a dispatched one is read
    "accepted": ("done", "accepted"),
    "blocked": ("failed", "blocked"),
}


# ── the builder ──────────────────────────────────────────────────────────


def _clock(moment: float) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(moment))
    except (OverflowError, OSError, ValueError):
        return "--:--"


def _child_state(
    child: Mapping[str, Any], facts: Mapping[str, Any], now: float
) -> tuple[str, str, float | None]:
    """(state, status word, elapsed seconds) for one native child."""
    session = child["child_session_id"]
    usage = facts["usage"].get(session, {})
    row = facts["sessions"].get(session)
    stop = child.get("stop")
    started = float(child["started_at"])
    if isinstance(stop, Mapping):
        status = _text(stop.get("status"), 40) or "unknown"
        duration = stop.get("duration_ms")
        elapsed = duration / 1000.0 if isinstance(duration, int) else max(0.0, float(stop["observed_at"]) - started)
        if status == "completed":
            # A completed child with no model call did no work: Hermes delivers a provider's error text as a normal
            # result (the native HUD rows' rule, `hermes_delegation`). Only a usage table that was read says "none".
            if facts["read"] and facts["usage_read"] and row is not None and not usage.get("rows"):
                return "failed", "no model call", elapsed
            return "done", "done", elapsed
        if status in _FAILED_STOPS:
            return "failed", status, elapsed
        if status == "interrupted":
            return "interrupted", "interrupted", elapsed
        return "unknown", status, elapsed
    if row is not None and row.get("end_reason") == COMPACTION_END_REASON:
        return "unknown", "compacted", None
    if row is not None and row.get("ended_at") is not None:
        return "unknown", "ended", None
    last = max([started] + [value for value in (usage.get("last_seen"),) if isinstance(value, (int, float))])
    if now - last > CHILD_STALE_SECONDS:
        return "unknown", "no news", None
    if usage.get("rows"):
        return "running", "running", max(0.0, now - started)
    return "dispatched", "dispatched", None


def _result_routes(raw: object) -> dict[int, dict[str, Any]]:
    """Per-task ``route`` from a background unit's stored result (a single task's own result is task 0)."""
    try:
        result = json.loads(raw) if isinstance(raw, str) else None
    except (ValueError, RecursionError):
        return {}
    if not isinstance(result, dict):
        return {}
    listed = result.get("results")
    entries: list[Any] = listed if isinstance(listed, list) else [result]
    routes: dict[int, dict[str, Any]] = {}
    for position, entry in enumerate(entries[:64]):
        if not isinstance(entry, dict):
            continue
        index = entry.get("task_index")
        index = index if isinstance(index, int) and not isinstance(index, bool) else position
        route = valid_observed_route(entry.get("route"))
        if route:
            routes[index] = route
    return routes


def _observed_model(session: str, facts: Mapping[str, Any]) -> str:
    row = facts["sessions"].get(session) or {}
    return row.get("model") or facts["usage"].get(session, {}).get("model", "")


def _category(route: Mapping[str, Any], observed: str, parent_model: str) -> tuple[str, str]:
    """(category, source): the recorded route where the observed model matches it, else inherit by equality, else ?."""
    if route.get("category") and route.get("origin") not in ("cleared", "exhausted_to_inherit"):
        if observed and (same_model(observed, str(route.get("wire_model", "")))
                         or same_model(observed, str(route.get("alias", "")))):
            return str(route["category"]), "route_provenance"
        return "?", "route_model_mismatch" if observed else "model_not_observed"
    if observed and parent_model and same_model(observed, parent_model):
        return "inherit", "parent_model_equality"
    return "?", "no_route_record"


def build_delegation_graph(
    omh_home: Path,
    hermes_home: Path,
    session_id: str,
    *,
    now: float | None = None,
    root_model: str = "",
    titles: Callable[[str], str] = child_title,
    fanout: Mapping[str, Any] | None = None,
    scope: str = "session",
    linger: float | None = GRAPH_LINGER_SECONDS,
    segments: Sequence[str] | None = None,
    dag_run: str = "",
    keep_dag: bool = False,
) -> dict[str, Any]:
    """The graph of one conversation's delegated work, or of the fanout passed in when it has none.

    ``dag_run`` names the dag run to draw instead of the newest. A named run that exists is drawn alone (no team,
    no plain delegations beside it) and does not lapse after ``linger``; one that does not is the newest, as ever.

    A graph whose lanes have all settled is inactive once ``linger`` seconds
    have passed since its last change; ``None`` keeps it, and ``keep_dag`` keeps a dag run's (the Desktop pane, which
    draws a finished run for its node summaries and figures) (the chat end post of
    a run it opened, `delegation_snapshot.py`). ``segments`` is
    `graph_segments`' answer for ``session_id`` when the caller already read
    it. Never raises: an unreadable record or database leaves the graph
    smaller or inactive, and a field it cannot evidence ``?``.
    """
    moment = time.time() if now is None else now
    connection = None
    try:
        # One state.db connection per build: the lineage and every fact are read on it. Opened in here: Python 3.11's
        # `Path.is_file` raises PermissionError where the Hermes home cannot be searched.
        connection = _connect(Path(hermes_home)) if session_id else None
        if session_id and not segments:
            segments = _segments(connection, session_id)
        graph = _build(omh_home, hermes_home, session_id, moment, root_model, titles, scope, linger, segments or [],
                       connection, dag_run, keep_dag)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        graph = inactive_graph(f"unreadable:{type(error).__name__}", scope=scope)
    finally:
        if connection is not None:
            connection.close()
    if graph["status"] != "active" and fanout:
        try:
            graph = fanout_graph(fanout)
        except (ValueError, TypeError, KeyError) as error:
            graph = inactive_graph(f"unreadable_fanout:{type(error).__name__}", scope="global")
    return _bounded(graph)


def _build(
    omh_home: Path,
    hermes_home: Path,
    session_id: str,
    now: float,
    root_model: str,
    titles: Callable[[str], str],
    scope: str,
    linger: float | None,
    segments: Sequence[str],
    connection: sqlite3.Connection | None,
    dag_pick: str = "",
    keep_dag: bool = False,
) -> dict[str, Any]:
    if not session_id:
        return inactive_graph("no_session", scope=scope)
    ledgers = {segment: read_ledger(Path(omh_home), segment) for segment in segments}
    teams = [found for found in (_team_record(Path(omh_home), segment) for segment in segments) if found is not None]
    team = max(teams, key=lambda found: found[1]) if teams else None
    children = [child for ledger in ledgers.values() if ledger for child in ledger["children"]]
    dag = _dag_run(Path(omh_home), session_id, ledgers, dag_pick)
    if dag is not None:
        run = str(dag["record"]["run"])
        # Another run's children are that run's nodes, not waves of this graph.
        children = [child for child in children
                    if not (isinstance(child.get("dag"), Mapping) and child["dag"].get("run") not in (None, run))]
        if dag["picked"]:
            children, team, linger = [], None, None
        known = {child["child_session_id"] for child in children}
        children += [child for child in dag["children"] if child["child_session_id"] not in known]
    if not children and team is None and dag is None:
        return inactive_graph("no_delegation", scope=scope)
    sessions = [session_id] + [child["child_session_id"] for child in children]
    if team is not None:
        for unit in team[0]["units"]:
            for attempt in unit.get("attempts") or []:
                dispatch = attempt.get("dispatch") if isinstance(attempt, dict) else None
                if isinstance(dispatch, dict) and isinstance(dispatch.get("child_session_id"), str):
                    sessions.append(dispatch["child_session_id"])
    delegations = [child.get("delegation_id", "") for child in children]
    facts = state_facts(Path(hermes_home), sessions, delegations, connection=connection)
    later = _continuations(connection, facts, sessions[1:])
    if later and connection is not None:
        _carry_on(Path(hermes_home), connection, facts, later)
    stops = [stop for ledger in ledgers.values() if ledger for stop in ledger["unjoined_stops"]]
    if stops:
        children = [with_unjoined_stop(child, stops, later.get(child["child_session_id"], ())) for child in children]
    if dag is not None:
        dag_children = ([with_unjoined_stop(child, stops, later.get(child["child_session_id"], ()))
                         for child in dag["children"]] if stops else dag["children"])
        derived = derive(dag["record"], dag_children, now)
        dag = {"record": dag["record"], "children": dag_children, "derived": derived,
               "state": run_state(dag["record"], derived)}
    in_conversation = set(segments)
    root_row = facts["sessions"].get(session_id) or {}
    root = {
        "id": "root",
        "kind": "root",
        "title": "main",
        "model": root_row.get("model") or _text(root_model) or "?",
        "effort": root_row.get("effort", ""),
        "state": "root",
        "status": "",
        "order": 0,
        "group": "",
    }
    nodes: list[dict[str, Any]] = [root]
    edges: list[dict[str, str]] = []
    node_of_subagent: dict[str, str] = {}
    node_of_session: dict[str, str] = {}
    model_of_node: dict[str, str] = {"root": root["model"] if root["model"] != "?" else ""}

    team_bound: dict[str, str] = {}
    team_lost: set[str] = set()  # helpers a Hermes restart ended (`team._hand_back_lost`): drawn nowhere
    if team is not None:
        record, _mtime = team
        for unit in record["units"]:
            attempts = unit.get("attempts") or []
            attempt = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
            dispatch = attempt.get("dispatch") if isinstance(attempt.get("dispatch"), dict) else {}
            if isinstance(dispatch.get("child_session_id"), str):
                team_bound[dispatch["child_session_id"]] = str(unit["unit_id"])
            lost = attempt.get("lost") if isinstance(attempt.get("lost"), list) else []
            team_lost.update(item["child_session_id"] for item in lost
                             if isinstance(item, dict) and isinstance(item.get("child_session_id"), str))

    dag_bound = {child["child_session_id"] for child in dag["children"]} if dag is not None else set()
    by_session = {child["child_session_id"]: child for child in children}
    ordered = sorted(children, key=lambda child: child["started_at"])
    waves: dict[tuple[str, str], int] = {}
    wave_start: dict[tuple[str, str], float] = {}
    for child in ordered:
        if (child["parent_session_id"] not in in_conversation or child["child_session_id"] in team_bound
                or child["child_session_id"] in dag_bound or child["child_session_id"] in team_lost):
            continue
        key = (child["parent_session_id"], child["parent_turn_id"] or child.get("call_id", ""))
        if key not in waves:
            waves[key] = len(waves) + 1
            wave_start[key] = child["started_at"]

    def facts_for(child: Mapping[str, Any], parent_model: str) -> dict[str, Any]:
        session = child["child_session_id"]
        observed = _observed_model(session, facts)
        delegation = facts["delegations"].get(child.get("delegation_id", ""), {})
        reported = child.get("observed_route") or (delegation.get("routes") or {}).get(child.get("task_index"), {})
        model = observed or delegation.get("model", "") or reported.get("model", "")
        category, source = _category(child.get("route") or {}, observed, parent_model)
        if reported and not (child.get("route") or {}).get("category"):
            # Hermes' backend picked this child's model: not OMH's route, and not the parent's by inheritance.
            category, source = "?", "backend_route"
        state, status, elapsed = _child_state(child, facts, now)
        stop = child.get("stop")
        row = {
            "model": model or "?",
            "effort": (facts["sessions"].get(session) or {}).get("effort", "") or reported.get("reasoning_effort", ""),
            "category": category,
            "category_source": source,
            "state": state,
            "status": status,
            "elapsed_seconds": elapsed,
            # When Hermes reported the child stopped, so "first failure" can mean first in time.
            "ended_at": float(stop["observed_at"]) if isinstance(stop, Mapping) else None,
            "output_tokens": (facts["sessions"].get(session) or {}).get("output_tokens"),
        }
        usage = (facts["sessions"].get(session) or {}).get("usage")
        if usage:
            row["usage"] = usage
        if reported:
            row["route_backend"] = reported["backend"]
            if reported.get("label"):
                row["route_label"] = reported["label"]
            if reported.get("fallback_activated"):
                row["route_origin"] = "fallback"
        return row

    def title_for(child: Mapping[str, Any]) -> str:
        title = titles(child["subagent_id"])
        index = child.get("task_index")
        delegation = facts["delegations"].get(child.get("delegation_id", ""), {})
        goals = delegation.get("goals", [])
        if not title and isinstance(index, int) and 0 <= index < len(goals):
            title = goals[index]
        return title or facts["openers"].get(child["child_session_id"], "")

    order = 1
    if team is not None:
        record, _mtime = team
        units = record["units"]
        states = {str(unit["unit_id"]): team_unit_state(unit) for unit in units}
        depth: dict[str, int] = {}

        # Kept on its own walk, not the DAG core's layers: a team record is read without a cycle check, and on a
        # hand-edited cyclic record this recursion's stages are not the core's (which leaves cyclic parts unplaced).
        def stage(unit_id: str, seen: frozenset[str] = frozenset()) -> int:
            if unit_id in depth:
                return depth[unit_id]
            unit = next(item for item in units if item["unit_id"] == unit_id)
            parents = [dep for dep in unit["depends_on"] if dep not in seen]
            depth[unit_id] = 1 + max([stage(dep, seen | {unit_id}) for dep in parents] or [0])
            return depth[unit_id]

        for unit in units:
            unit_id = str(unit["unit_id"])
            node_id = f"t:{unit_id}"
            state, status = _TEAM_VIEW.get(states[unit_id], ("unknown", states[unit_id]))
            node: dict[str, Any] = {
                "id": node_id, "kind": "lane", "title": _text(unit.get("title"), TITLE_LIMIT) or unit_id,
                "category": "?", "category_source": "not_dispatched", "model": "?", "effort": "",
                "state": state, "status": status, "elapsed_seconds": None, "order": order,
                "group": f"stage {stage(unit_id)}", "waits_on": 0, "team_unit": unit_id,
            }
            order += 1
            unmet = [dep for dep in unit["depends_on"] if states.get(dep) != "accepted"]
            if states[unit_id] in ("waiting", "prepared") and unmet:
                node["waits_on"] = len(unmet)
            child_session = next((session for session, bound in team_bound.items() if bound == unit_id), "")
            child = by_session.get(child_session)
            if states[unit_id] == "repairing" and child_session and child is None:
                node.update(state="dispatched", status="repair dispatched")
            if child is not None:
                derived = facts_for(child, model_of_node["root"])
                node.update({key: derived[key] for key in ("model", "effort", "category", "category_source",
                                                           "output_tokens", "usage") if key in derived})
                node["session_tail"] = session_tail(child_session)
                if states[unit_id] in ("dispatched", "repairing"):
                    # The team record says the attempt was sent; only the child's own records say it is moving.
                    repairing = states[unit_id] == "repairing" and derived["state"] == "running"
                    node.update(state=derived["state"], status="repairing" if repairing else derived["status"],
                                elapsed_seconds=derived["elapsed_seconds"], ended_at=derived["ended_at"])
                elif derived["elapsed_seconds"] is not None:
                    node["elapsed_seconds"] = derived["elapsed_seconds"]
                node_of_subagent[child["subagent_id"]] = node_id
                model_of_node[node_id] = derived["model"] if derived["model"] != "?" else ""
            if child_session:
                node_of_session[child_session] = node_id
            nodes.append(node)
            if unit["depends_on"]:
                edges.extend({"from": f"t:{dep}", "to": node_id, "kind": "depends_on"} for dep in unit["depends_on"])
            else:
                edges.append({"from": "root", "to": node_id, "kind": "dispatch"})

    if dag is not None:
        order = _dag_nodes(dag, nodes, edges, order, facts_for, model_of_node, node_of_subagent, node_of_session,
                           now)

    def parent_of(child: Mapping[str, Any]) -> str:
        parent_id = node_of_subagent.get(child["parent_subagent_id"], "") if child["parent_subagent_id"] else ""
        if not parent_id:
            parent_id = node_of_session.get(child["parent_session_id"], "")
        if not parent_id:
            parent_id = "root" if child["parent_session_id"] in in_conversation else ""
        return parent_id

    # A child is placed once its parent is: passes repeat until none places, so a child whose parent this graph
    # does not hold is left out (never drawn hanging from the wrong node), and so is everything under it.
    pending = [child for child in ordered
               if child["child_session_id"] not in team_bound and child["child_session_id"] not in dag_bound
               and child["child_session_id"] not in team_lost]
    while True:
        placeable = [child for child in pending if parent_of(child)]
        if not placeable:
            break
        child = placeable[0]
        pending.remove(child)
        parent_id = parent_of(child)
        node_id = f"s:{child['subagent_id']}"
        node_of_subagent[child["subagent_id"]] = node_id
        node_of_session[child["child_session_id"]] = node_id
        derived = facts_for(child, model_of_node.get(parent_id, ""))
        key = (child["parent_session_id"], child["parent_turn_id"] or child.get("call_id", ""))
        group = f"wave {waves[key]} · {_clock(wave_start[key])}" if parent_id == "root" and key in waves else ""
        nodes.append({
            "id": node_id, "kind": "lane",
            "title": _text(title_for(child), TITLE_LIMIT) or f"session {session_tail(child['child_session_id'])}",
            **derived, "order": order, "group": group, "waits_on": 0,
            "session_tail": session_tail(child["child_session_id"]),
        })
        model_of_node[node_id] = derived["model"] if derived["model"] != "?" else ""
        order += 1
        edges.append({"from": parent_id, "to": node_id, "kind": "dispatch"})

    if linger is not None:
        nodes, edges = _without_old_waves(nodes, edges, children, now, linger)
    lanes = [node for node in nodes if node["kind"] != "root"]
    if not lanes:
        return inactive_graph("no_delegation", scope=scope)
    dag_open = dag is not None and dag["state"] in DAG_OPEN_STATES
    settled = all(node["state"] in SETTLED_STATES for node in lanes) and not dag_open
    newest = max([child["started_at"] for child in children]
                 + [float(child["stop"]["observed_at"]) for child in children if isinstance(child.get("stop"), dict)]
                 + ([team[1]] if team is not None else [])
                 + ([float(dag["record"].get("updated_at") or 0.0)] if dag is not None else []))
    if settled and linger is not None and not (keep_dag and dag is not None) and now - newest > linger:
        return inactive_graph("settled", scope=scope)
    if dag is not None:
        name = dag_graph_name(dag["record"])
    elif team is not None and team[0].get("team_id"):
        name = f"team {_text(team[0].get('team_id'), 48)}"
    else:
        name = "delegation"
    graph = _finish(name, nodes, edges, scope)
    # The segment that posted last speaks for the conversation; a rotation does not start its posts over.
    graph["chat"] = _chat_record(max((ledger for ledger in ledgers.values() if ledger), default=None,
                                     key=lambda ledger: ledger["posted"].get("observed_at") or 0.0))
    graph["changed_at"] = newest  # the last start, stop, team-record or dag-record write: when this graph last moved
    if dag is not None:
        # A dag run is not over while a node is out or ready, even when every drawn lane settled. A run that waits
        # on a repair is over for the chat: the reply that did not repair it ends the turn, and a repair added later
        # reopens the run (`delegation_snapshot`).
        graph["dag_open"] = dag_open
        graph["dag_topology"] = _dag_topology(dag["record"])
        if dag["state"] in FINISHED_STATES:
            # A finished run's goal verdict, as `omh_dag` and `omh_run_summary` give it (the same states).
            graph["dag_verdict"] = goal_verdict(dag["record"], dag["derived"])[0]
    return graph


def _dag_topology(record: Mapping[str, Any]) -> dict[str, Any]:
    """The run's critical path and bottlenecks (`dag_run.topology`), by node label, for `/dag`."""
    labels = {str(node["id"]): _text(node.get("label"), TITLE_LIMIT) or str(node["id"]) for node in record["nodes"]}
    topology = record.get("topology") if isinstance(record.get("topology"), Mapping) else {}
    path = [labels.get(str(node), str(node)) for node in topology.get("critical_path") or []]
    bottlenecks = [[labels.get(str(item.get("node")), str(item.get("node"))), int(item.get("blocks") or 0)]
                   for item in topology.get("bottlenecks") or [] if isinstance(item, Mapping)]
    return {"critical_path": path, "bottlenecks": bottlenecks}


# ── omh_dag, read-only ───────────────────────────────────────────────────


DAG_OPEN_STATES: Final = frozenset({"running"})
# A dag node's derived state (`dag_run.derive`) as a graph state and status word; superseded nodes are not drawn.
_DAG_VIEW: Final = {
    "accepted": ("done", "accepted"),
    "repaired": ("done", "repaired"),
    "failed": ("failed", "failed"),
    "blocked": ("failed", "blocked"),
    "handed_out": ("dispatched", "handed out"),
    "running": ("running", "running"),
    "returned": ("dispatched", "returned"),
    "ready": ("waiting", "ready"),
    "waiting": ("waiting", "waiting"),
    "held": ("waiting", "held"),
    "cancelled": ("interrupted", "cancelled"),
    # Settled to wait on a background process or a CI run until its `wake_at` (`dag_run.settle`): not over.
    "parked": ("waiting", "parked"),
}


def dag_graph_name(record: Mapping[str, Any]) -> str:
    """The name a dag run's graph is drawn and posted under."""
    return _text(record.get("name"), 48) or "dag"


def dag_node_id(run: str, node: str) -> str:
    """A dag node's id in the graph."""
    return f"d:{run}:{node}"


def dag_origin(node: Mapping[str, Any]) -> tuple[str, str]:
    """(kind, the node it came from) for a node a repair or an extend round added; ("", "") for a defined one.

    A repair node came from the node it repairs, an extend node from the node
    whose check found the work missing (``found_by``, "" when none was named).
    """
    kind = str(node.get("origin") or "").partition(":")[0]
    if kind not in ADDED_ORIGIN_KINDS:
        return "", ""
    if kind == "repair":
        return kind, str(node.get("repairs") or "")
    return kind, str(node.get("found_by") or "")


def _dag_runs(
    omh_home: Path, session_id: str, ledgers: Mapping[str, Mapping[str, Any] | None]
) -> tuple[list[str], list[tuple[dict[str, Any], Path]]]:
    """The segments a conversation's runs are read from, and those runs.

    The run is stored under the segment that defined it; when this segment
    holds none, the conversation's other segments are read (the keys of
    ``ledgers``, `graph_segments`), so a compacted parent still finds its run.
    """
    segments = [session_id]
    runs = session_runs(omh_home, session_id)
    if not runs:
        segments = sorted(ledgers)
        runs = [item for segment in segments for item in session_runs(omh_home, segment)]
    return segments, runs


def _dag_run(
    omh_home: Path, session_id: str, ledgers: Mapping[str, Mapping[str, Any] | None], pick: str = ""
) -> dict[str, Any] | None:
    """The conversation's newest `omh_dag/v1` run, or the one named ``pick`` (``picked``), with its ledger children.

    The caller derives the states once it has joined the stops.
    """
    segments, runs = _dag_runs(omh_home, session_id, ledgers)
    if not runs:
        return None
    named = next((item[0] for item in runs if pick and str(item[0].get("run")) == pick), None)
    record = named or max(runs, key=lambda item: float(item[0].get("updated_at") or 0.0))[0]
    run = str(record["run"])
    children = [
        child for segment in segments for child in ((ledgers.get(segment) or {}).get("children") or [])
        if isinstance(child.get("dag"), Mapping) and child["dag"].get("run") == run
    ]
    return {"record": record, "children": children, "picked": named is not None}


def dag_run_choices(
    omh_home: Path, hermes_home: Path, session_id: str, *, now: float | None = None
) -> list[dict[str, Any]]:
    """Every dag run of one conversation, newest change first: what a pane offers to switch between.

    Each is ``run``, ``name``, ``state`` (as `dag_run.run_state` words it), the ``nodes`` it holds and when it last
    changed (``updated_at``). Never raises: an unreadable store is no choices.
    """
    if not session_id:
        return []
    moment = time.time() if now is None else now
    connection = None
    try:
        connection = _connect(Path(hermes_home))
        ledgers = {segment: read_ledger(Path(omh_home), segment) for segment in _segments(connection, session_id)}
        segments, runs = _dag_runs(Path(omh_home), session_id, ledgers)
        choices = []
        for record, _path in runs:
            run = str(record["run"])
            children = [
                child for segment in segments for child in ((ledgers.get(segment) or {}).get("children") or [])
                if isinstance(child.get("dag"), Mapping) and child["dag"].get("run") == run
            ]
            choices.append({
                "run": run,
                "name": dag_graph_name(record),
                "state": run_state(record, derive(record, children, moment)),
                "nodes": len(record["nodes"]),
                "updated_at": float(record.get("updated_at") or 0.0),
            })
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return []
    finally:
        if connection is not None:
            connection.close()
    return sorted(choices, key=lambda choice: choice["updated_at"], reverse=True)


def _dag_nodes(
    dag: Mapping[str, Any], nodes: list[dict[str, Any]], edges: list[dict[str, str]], order: int,
    facts_for: Callable[[Mapping[str, Any], str], dict[str, Any]], model_of_node: dict[str, str],
    node_of_subagent: dict[str, str], node_of_session: dict[str, str], now: float,
) -> int:
    """Add a dag run's nodes and its recorded edges; returns the next drawing order.

    A node a repair or an extend round added also gets an edge from where it
    came from (`dag_origin`) when nothing else of its own group leads to it,
    so the drawing shows it below that node. Each node carries its role
    (`role`, `dag_run.node_role`: build, baseline, verify or review), which
    the TUI names a finished child's briefing by, and its place in the run's
    definition order (`node_index`: superseded and added nodes keep theirs),
    which picks its handle's hue. A parked node is a waiting one
    marked `parked`, with what its attempt recorded it waits on (`parked_at`,
    `wake_at`, `wait_handle`, `wait_reason`); its elapsed time is the time
    since it parked.
    """
    record, derived = dag["record"], dag["derived"]
    run = str(record["run"])
    # A held node of a run that is not moving (stopped, cancelled, or waiting on a repair) will not run on its own.
    stopped = dag["state"] not in DAG_OPEN_STATES
    drawn = {str(node["id"]) for node in record["nodes"] if derived[str(node["id"])]["state"] != "superseded"}
    defined = {str(node["id"]): index for index, node in enumerate(record["nodes"])}
    for node_id, layer in _dag_layers(record, drawn).items():
        node = next(item for item in record["nodes"] if item["id"] == node_id)
        info = derived[node_id]
        state, status = _DAG_VIEW.get(info["state"], ("unknown", info["state"]))
        if info["state"] == "held" and stopped:
            state = "interrupted"
        # Accepted, though nothing could read its handoff where the child wrote it: the word every view shows says so.
        unchecked = info["state"] == "accepted" and handoff_unchecked(node)
        if unchecked:
            status = HANDOFF_NOT_CHECKED
        graph_id = dag_node_id(run, node_id)
        origin = str(node.get("origin") or "define")
        # An extend round is its own group: its first nodes hang under the node that found the gap, so its layers
        # would otherwise be numbered past ones the tree never shows.
        group = f"extend {origin.partition(':')[2]}" if origin.startswith("extend:") else f"layer {layer + 1}"
        entry: dict[str, Any] = {
            "id": graph_id, "kind": "lane", "title": _text(node.get("label"), TITLE_LIMIT) or node_id,
            "category": _text(node.get("category"), 40) or "?", "category_source": "dag_plan", "model": "?",
            "effort": "", "state": state, "status": status, "elapsed_seconds": None, "order": order,
            "group": group, "waits_on": len(info["waits_on"]) if info["state"] == "waiting" else 0,
            "dag_node": node_id, "dag_origin": origin, "role": node_role(node), "node_index": defined[node_id],
        }
        summary = _prompt_summary(node.get("prompt"))
        if summary:
            entry["summary"] = summary  # the node prompt's first clause, beside a short label in the tree
        if unchecked:
            entry["handoff_checked"] = False
        cycle = node.get("cycle")
        if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle > 0:
            entry["cycle"] = cycle  # a repair node's repair cycle of the node it repairs (`dag_run.repair`)
        order += 1
        child = info["child"]
        if isinstance(child, Mapping):
            facts = facts_for(child, model_of_node["root"])
            # Once a child exists its category is the recorded route's, shown only where its model matches.
            entry.update({key: facts[key] for key in ("model", "effort", "category", "category_source",
                                                       "output_tokens", "usage") if key in facts})
            entry.update({key: facts[key] for key in ("route_backend", "route_label", "route_origin") if key in facts})
            if facts["category_source"] == "backend_route":
                # The plan's lane holds where Hermes ran the option this run handed out; any other option is not it.
                attempts = node.get("attempts") if isinstance(node.get("attempts"), list) else []
                handed = attempts[-1].get("option", "") if attempts and isinstance(attempts[-1], dict) else ""
                if handed and handed == facts.get("route_label"):
                    entry.update(category=_text(node.get("category"), 40) or "?", category_source="backend_option")
                else:
                    entry["category_source"] = "route_option_mismatch" if handed else "backend_route"
            entry["session_tail"] = session_tail(child["child_session_id"])
            if info["state"] == "running":
                # The record says the node is out; only the child's own records say it is moving.
                entry.update(state=facts["state"], status=facts["status"])
            entry.update(elapsed_seconds=facts["elapsed_seconds"], ended_at=facts["ended_at"])
            node_of_subagent[child["subagent_id"]] = graph_id
            node_of_session[child["child_session_id"]] = graph_id
            model_of_node[graph_id] = facts["model"] if facts["model"] != "?" else ""
        if info["state"] == "parked":
            entry.update(_parked_fields(node, now))
        nodes.append(entry)
        parents = [parent for parent in node["depends_on"] if parent in drawn]
        edges.extend({"from": dag_node_id(run, parent), "to": graph_id, "kind": "depends_on"} for parent in parents)
        origin = _origin_parent(node, record, drawn)
        if origin:
            edges.append({"from": dag_node_id(run, origin), "to": graph_id, "kind": dag_origin(node)[0]})
        elif not parents:
            edges.append({"from": "root", "to": graph_id, "kind": "dispatch"})
    return order


def _parked_fields(node: Mapping[str, Any], now: float) -> dict[str, Any]:
    """What a parked node's last attempt says it waits on, and how long it has: `settle` stamps `settled_at`,
    `handle`, `wake_at` and `reason` on a park. A field the attempt does not carry is left out."""
    attempts = node.get("attempts") if isinstance(node.get("attempts"), list) else []
    attempt = attempts[-1] if attempts and isinstance(attempts[-1], Mapping) else {}
    fields: dict[str, Any] = {"parked": True, "elapsed_seconds": None}  # never the child's run time
    parked_at, wake_at = attempt.get("settled_at"), attempt.get("wake_at")
    if isinstance(parked_at, int | float) and not isinstance(parked_at, bool) and 0 < parked_at <= now:
        fields.update(parked_at=float(parked_at), elapsed_seconds=now - float(parked_at))
    if isinstance(wake_at, int | float) and not isinstance(wake_at, bool) and wake_at > 0:
        fields["wake_at"] = float(wake_at)
    handle, reason = _text(attempt.get("handle"), 120), _text(attempt.get("reason"), 120)
    if handle:
        fields["wait_handle"] = handle
    if reason:
        fields["wait_reason"] = reason
    return fields


def _origin_parent(node: Mapping[str, Any], record: Mapping[str, Any], drawn: set[str]) -> str:
    """The drawn node an added node hangs below, or "": none when a node of its own group already leads to it."""
    kind, origin = dag_origin(node)
    if not kind or origin not in drawn or origin in node["depends_on"]:
        return ""
    group = {str(other["id"]) for other in record["nodes"]
             if (other.get("origin"), other.get("cycle")) == (node.get("origin"), node.get("cycle"))}
    return "" if any(parent in group for parent in node["depends_on"]) else origin


def _dag_layers(record: Mapping[str, Any], drawn: set[str]) -> dict[str, int]:
    """The drawn nodes in layer order, each with its layer, an added node counted below the node it came from."""
    parents: dict[str, list[str]] = {}
    for node in record["nodes"]:
        node_id = str(node["id"])
        if node_id in drawn:
            origin = _origin_parent(node, record, drawn)
            parents[node_id] = [parent for parent in node["depends_on"] if parent in drawn] + ([origin] if origin else [])
    ids = [str(node["id"]) for node in record["nodes"] if str(node["id"]) in drawn]
    placed, _stuck = layer_of(ids, parents)
    return dict(sorted(placed.items(), key=lambda item: (item[1], ids.index(item[0]))))


def _without_old_waves(
    nodes: list[dict[str, Any]], edges: list[dict[str, str]], children: Sequence[Mapping[str, Any]], now: float,
    linger: float,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The graph without each dispatch wave that settled more than ``linger`` ago, while some other lane still moves.

    A wave goes with every lane under it, and only when all of them have
    settled and none started or stopped within ``linger``, so a conversation's
    earlier waves stop filling the drawing once newer work is under way.
    """
    if all(node["state"] in SETTLED_STATES for node in nodes if node["kind"] != "root"):
        return nodes, edges
    latest: dict[str, float] = {}
    for child in children:
        stop = child.get("stop")
        latest[f"s:{child['subagent_id']}"] = max(
            [float(child["started_at"])] + ([float(stop["observed_at"])] if isinstance(stop, dict) else [])
        )
    below: dict[str, list[str]] = {}
    for edge in edges:
        below.setdefault(edge["from"], []).append(edge["to"])
    state_of = {node["id"]: node["state"] for node in nodes}
    waves: dict[str, list[str]] = {}
    for edge in edges:
        group = next((node["group"] for node in nodes if node["id"] == edge["to"]), "")
        if edge["from"] == "root" and edge["to"].startswith("s:") and group.startswith("wave "):
            waves.setdefault(group, []).append(edge["to"])
    dropped: set[str] = set()
    for heads in waves.values():
        members, pending = set(), list(heads)
        while pending:
            node_id = pending.pop()
            if node_id not in members:
                members.add(node_id)
                pending.extend(below.get(node_id, []))
        if all(state_of.get(node_id) in SETTLED_STATES and now - latest.get(node_id, now) > linger
               for node_id in members):
            dropped |= members
    if not dropped:
        return nodes, edges
    return ([node for node in nodes if node["id"] not in dropped],
            [edge for edge in edges if edge["from"] not in dropped and edge["to"] not in dropped])


def _chat_record(ledger: Mapping[str, Any] | None) -> dict[str, Any]:
    """What the conversation's last chat post was (`delegation_snapshot.py`) and why the last one due was skipped."""
    posted = ledger.get("posted") if ledger else {}
    skipped = ledger.get("skipped") if ledger else {}
    return {
        "moment": posted.get("moment", "") if posted else "",
        "phase": posted.get("phase", "") if posted else "",
        "posted_at": posted.get("observed_at") if posted else None,
        "skipped": skipped.get("reason", "") if skipped else "",
        "skipped_at": skipped.get("observed_at") if skipped else None,
    }


def fanout_graph(record: Mapping[str, Any]) -> dict[str, Any]:
    """A verified local fanout as a graph: its units, their titles and owners, the recorded dependencies.

    ``record`` carries the frozen contract and the roster the HUD reader
    already checked (`subagent_graph_contract`); this only reshapes them.
    """
    contract = record.get("contract") or {}
    roster = record.get("roster") or {}
    fanout_id = _text(contract.get("fanout_id"), 64)
    units = [unit for unit in contract.get("units", []) if isinstance(unit, Mapping)][:GRAPH_NODE_LIMIT]
    statuses = {
        str(unit.get("unit_id")): unit
        for unit in roster.get("units", []) if isinstance(unit, Mapping)
    }
    ids = {str(unit.get("unit_id")) for unit in units}
    nodes: list[dict[str, Any]] = [{
        "id": "root", "kind": "root", "title": f"fanout {fanout_id}" if fanout_id else "fanout",
        "model": "", "effort": "", "state": "root", "status": "", "order": 0, "group": "",
    }]
    edges: list[dict[str, str]] = []
    done = {
        unit_id for unit_id, entry in statuses.items() if entry.get("status") in _FANOUT_SUCCESS
    }
    for order, unit in enumerate(units, start=1):
        unit_id = str(unit.get("unit_id"))
        entry = statuses.get(unit_id, {})
        status = _text(entry.get("status"), 40) or "unknown"
        depends = [dep for dep in unit.get("depends_on", []) if isinstance(dep, str) and dep in ids]
        if status == "running":
            state = "running"
        elif status in _FANOUT_SUCCESS:
            state = "done"
        elif status == "prepared_not_observed":
            state, status = "waiting", "prepared"
        elif status == "unknown":
            state = "unknown"
        else:
            state = "failed"
        unmet = [dep for dep in depends if dep not in done]
        stuck = roster_progress_fields(entry) if state == "running" else {}
        elapsed = None
        if stuck:
            # `running` only says a process was spawned; a unit whose work stopped moving is never drawn running.
            state = "stuck"
            status = f"stuck: {_text(stuck.get('state_reason'), 60) or stuck['unit_state']}"
            elapsed = stuck.get("stalled_for_seconds")
        nodes.append({
            "id": f"f:{unit_id}", "kind": "lane", "title": _text(unit.get("title"), TITLE_LIMIT) or unit_id,
            "category": _text(unit.get("owner"), 40) or "?", "category_source": "fanout_owner",
            "model": _text(entry.get("model")) or "?", "effort": _text(entry.get("reasoning_effort"), 40),
            "state": state, "status": status, "elapsed_seconds": elapsed, "order": order,
            "group": "", "waits_on": len(unmet) if state == "waiting" else 0,
        })
        if depends:
            edges.extend({"from": f"f:{dep}", "to": f"f:{unit_id}", "kind": "depends_on"} for dep in depends)
        else:
            edges.append({"from": "root", "to": f"f:{unit_id}", "kind": "dispatch"})
    if len(nodes) < 2:
        return inactive_graph("empty_fanout", scope="global")
    return _finish(f"fanout {fanout_id}" if fanout_id else "fanout", nodes, edges, "global", "fanout")


# Kept on its own walk, not the DAG core's `layers`: given a repeated node id this walk answers no layers or
# lists the id twice, where the core reads the id once, and its readers do not drop repeats first.
def _layers(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, str]]) -> list[list[str]]:
    ids = [str(node["id"]) for node in nodes]
    incoming = {node_id: 0 for node_id in ids}
    successors: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for edge in edges:
        if edge["from"] in successors and edge["to"] in incoming:
            successors[edge["from"]].append(edge["to"])
            incoming[edge["to"]] += 1
    layer = {node_id: 0 for node_id in ids}
    ready = [node_id for node_id in ids if incoming[node_id] == 0]
    while ready:
        current = ready.pop(0)
        for lower in successors[current]:
            layer[lower] = max(layer[lower], layer[current] + 1)
            incoming[lower] -= 1
            if incoming[lower] == 0:
                ready.append(lower)
    if any(count for count in incoming.values()):
        return []
    depth = max(layer.values(), default=-1) + 1
    return [[node_id for node_id in ids if layer[node_id] == index] for index in range(depth)]


def _finish(
    name: str, nodes: list[dict[str, Any]], edges: list[dict[str, str]], scope: str, source: str = "native"
) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "status": "active",
        "reason": "",
        "scope": scope,
        "source": source,
        "name": name,
        "nodes": nodes,
        "edges": edges,
        "layers": _layers(nodes, edges),
        "hidden_nodes": 0,
        "claim_boundary": GRAPH_CLAIM_BOUNDARY,
    }


_KEEP_ORDER: Final = {
    "running": 0, "stuck": 0, "failed": 1, "dispatched": 2, "waiting": 3, "interrupted": 4, "unknown": 5, "done": 6,
}


def _bounded(graph: dict[str, Any]) -> dict[str, Any]:
    """At most `GRAPH_NODE_LIMIT` nodes and `GRAPH_BYTE_LIMIT` bytes; what is left out is counted, edges kept whole."""
    nodes = graph.get("nodes") or []
    if graph.get("status") != "active":
        return graph

    def size(candidate: dict[str, Any]) -> int:
        return len(json.dumps(candidate, sort_keys=True, default=str).encode("utf-8"))

    keep = len(nodes)
    while keep > 1 and (keep > GRAPH_NODE_LIMIT or size(_cut(graph, keep)) > GRAPH_BYTE_LIMIT):
        keep -= 1
    return _cut(graph, keep) if keep < len(nodes) else graph


def _cut(graph: dict[str, Any], keep: int) -> dict[str, Any]:
    nodes = graph["nodes"]
    if keep >= len(nodes):
        return graph
    root = [node for node in nodes if node.get("kind") == "root"]
    lanes = sorted(
        (node for node in nodes if node.get("kind") != "root"),
        key=lambda node: (_KEEP_ORDER.get(node.get("state", ""), 5), -int(node.get("order") or 0)),
    )
    kept_ids = {node["id"] for node in root + lanes[: max(0, keep - len(root))]}
    # A kept node's parents are kept too, so no kept edge hangs from nothing.
    changed = True
    while changed:
        changed = False
        for edge in graph["edges"]:
            if edge["to"] in kept_ids and edge["from"] not in kept_ids:
                kept_ids.add(edge["from"])
                changed = True
    kept = [node for node in nodes if node["id"] in kept_ids]
    edges = [edge for edge in graph["edges"] if edge["from"] in kept_ids and edge["to"] in kept_ids]
    # What each group (a dag run's layer) lost, so its row reads `28 of 640 nodes`, not a total of 28; every group in
    # the run's order, so a layer the cut emptied still has its row; and what the cut lanes' states were, so a run's
    # end tallies the whole run.
    hidden_by_group: dict[str, int] = {}
    hidden_by_state: dict[str, int] = {}
    group_order: list[str] = []
    for node in sorted(nodes, key=lambda node: int(node.get("order") or 0)):
        if node.get("kind") == "root":
            continue
        group = str(node.get("group") or "")
        if group not in group_order:
            group_order.append(group)
        if node["id"] not in kept_ids:
            state = str(node.get("state") or "unknown")
            hidden_by_group[group] = hidden_by_group.get(group, 0) + 1
            hidden_by_state[state] = hidden_by_state.get(state, 0) + 1
    return {
        **graph,
        "nodes": kept,
        "edges": edges,
        "layers": _layers(kept, edges),
        "hidden_nodes": len(nodes) - len(kept),
        "hidden_by_group": hidden_by_group,
        "hidden_by_state": hidden_by_state,
        "group_order": group_order,
    }
