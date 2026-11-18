"""What Hermes' own hooks said about delegated work, kept so it can be drawn as a graph.

`delegate_task` leaves no record that ties a child session to the call and
the task that made it: `state.db`, the delegation manifests and the live logs
name no child session next to a task. Three host callbacks do, and this module
writes what they say, metadata only, into one record per conversation
(`delegation_ledger/v1` at ``<omh_home>/runtime/delegation/<key>.json``):

* `subagent_start` (one per child, as Hermes builds it, before it runs):
  the child's session id and subagent id, its parent session and parent
  subagent (set when the parent is itself a child), the turn that dispatched
  it, and the route OMH itself had prepared for that session at that moment
  (`delegation_route_provenance/v1`, the record `omh_delegate_route` writes).
  A dag-ulw node's child also gets the Hermes process it runs in
  (`host_process.this_process`).
* `post_tool_call` for `delegate_task`: the host's own result. A background
  dispatch lists ``subagent_ids`` in task order with its ``delegation_id``,
  which gives each child its task index and the delegation Hermes recorded
  its goals under. A synchronous call (a nested orchestrator, a one-shot
  run) lists results by task index only; its children are the ones that
  call started, in the order Hermes built them.
* `subagent_stop`: the child's own status and duration.

A second `subagent_start` naming a child already held, with the same session,
is Hermes continuing that child (`delegation.auto_resume` after a usage limit
or a restart, or the parent's `delegate_task(action='continue')`): its earlier
stop is dropped, ``resumed_at`` and ``resumes`` are kept, and a dag-ulw
child's process is the one it resumed in, so the resumed run's own stop is
the one that counts.

Each top-level child (one whose parent is the session's own agent, not
another child) is also counted in memory per conversation, whether or not its
record is written (`oneshot_children_spawned`): Hermes charges a one-shot
session's child budget per process, at `subagent_start`, and keeps no count
on disk either.

No goal, summary, prompt or tool history is written. A title is drawn from
Hermes' records when the graph is read, or, within this process, from the
goal `subagent_start` carried, held in memory only (`child_title`). The
last ``[dag:<run>/<node>]`` marker in a goal binds the child to that node:
the two ids are kept (`dag_binding`), the goal is not, and `subagent_stop`
reaches the node through the child session id. `omh_dag` ends each goal with
its marker, a goal handed out before an update opens with it, and text a
model adds after it leaves the binding as it was.

Every entry point here is an observer: it never blocks or changes a call and
never raises into the host. A failed write leaves the graph with less in it,
never with something wrong, and is counted (`ledger_declines`).
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any, Final

from . import runtime_paths
from .awareness_delivery import _awareness_delivery_lock
from .hermes_delegation import load_delegation_route_provenance
from .host_process import recorded_process, this_process
from .sqlite_readonly import connect_readonly

LEDGER_SCHEMA_VERSION: Final = "delegation_ledger/v1"
LEDGER_DIRNAME: Final = "delegation"
LEDGER_CALL_LIMIT: Final = 32
LEDGER_CHILD_LIMIT: Final = 128
LEDGER_STOP_LIMIT: Final = 32
LEDGER_MAX_AGE_SECONDS: Final = 24 * 3600
LEDGER_MAX_BYTES: Final = 262_144
LEDGER_LOCK_SECONDS: Final = 2.0
ID_LIMIT: Final = 160
WORD_LIMIT: Final = 40
# A route OMH prepared more than this long before a child started is not the route that child was built under.
ROUTE_FRESHNESS_SECONDS: Final = 900.0
# A nested child's conversation is found through `_delegate_from`; deeper than this is not followed.
ROOT_WALK_LIMIT: Final = 6
TITLE_LIMIT: Final = 120
TITLE_CACHE_LIMIT: Final = 512
DURATION_MS_LIMIT: Final = 10**12  # about 31 years: a duration past it is not a duration
ROOT_CACHE_LIMIT: Final = 1024
RESUME_LIMIT: Final = 64  # times one child's resumes are counted; Hermes itself resumes a child at most twice
SPAWNED_ID_LIMIT: Final = 512  # top-level subagent ids already counted, so a repeated start counts once
CLOSED_LIMIT: Final = 256  # lane keys a chat end post closed: ledger children and team parts alike
SEEN_LIMIT: Final = 256  # lane keys a chat post already showed, so a dag run names the nodes it added once
PRUNE_INTERVAL_SECONDS: Final = 3600.0  # how often one process looks for records that aged out
PRUNE_LOCK_SECONDS: Final = 0.1
LEDGER_CLAIM_BOUNDARY: Final = (
    "Delegation structure as Hermes' own hooks reported it: session and subagent ids, task order, turn ids, "
    "times, status words and the route OMH had prepared. It holds no goal, summary, prompt or tool history, and "
    "it is not execution, verification, review, CI or merge evidence."
)
ROUTE_FIELDS: Final = ("category", "alias", "wire_model", "reasoning_effort", "origin")
# What Hermes' own result says a backend-routed child ran on (`delegate_tool_child_run._route_report`).
OBSERVED_ROUTE_FIELDS: Final = ("backend", "label", "provider", "model", "reasoning_effort", "service_tier")
# What a chat reply last carried (`delegation_snapshot.py`): the moment, and whether its run is still open.
POST_MOMENTS: Final = ("start", "count", "end")
RUN_PHASES: Final = ("open", "closed")

# The markers OMH ends a delegated goal with (`dag_run.task_for`, `team._delegate_entry`), so Hermes' 40-character
# previews show the task first. The last whole marker in a goal binds: a goal handed out before an update opens with
# one, and a model may add text after it. The ids are ones OMH minted, matched whole or not at all. No label or title
# OMH accepts holds a marker (`dag_run._validated_node`, `team._validated_units`); a goal whose last marker is a team
# key is a team helper's, even when an older title quoted a dag marker before it (`team._MARKER` reads the mirror).
_DAG_ID: Final = r"[a-z0-9][a-z0-9-]{0,31}"
_TEAM_KEY: Final = r"omh-team:[a-z0-9][a-z0-9-]{0,47}/[a-z0-9][a-z0-9_-]{0,47}/attempt-[1-9][0-9]?"
_DAG_MARKER: Final = re.compile(rf"\[(?:dag:({_DAG_ID})/({_DAG_ID})|{_TEAM_KEY})\]")
_GOAL_MARKER: Final = rf"\[(?:dag:{_DAG_ID}/{_DAG_ID}|omh-team:[^\]]{{1,200}})\]"
_GOAL_MARKER_TEXT: Final = re.compile(rf"\A\s*{_GOAL_MARKER}\s*|\s?{_GOAL_MARKER}")
_TASK_LABEL: Final = re.compile(r"^(?:TASK|Task)\s*:\s*")
_roots: OrderedDict[str, str] = OrderedDict()
_titles: OrderedDict[str, str] = OrderedDict()
# Top-level children started in this process, per conversation root; never written to disk.
_spawned: OrderedDict[str, int] = OrderedDict()
_spawned_ids: OrderedDict[str, str] = OrderedDict()
ledger_declines: Counter[str] = Counter()
_pruned_at: list[float] = [0.0]


def ledger_key(session_id: str) -> str:
    """The file stem for one conversation: a legible slug and a digest of the exact id (the todo store's scheme)."""
    reference = str(session_id or "")[:ID_LIMIT]
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", reference).strip("_-")[:48]
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]
    return f"{slug}-{digest}" if slug else digest


def ledger_dir(omh_home: Path) -> Path:
    return Path(omh_home) / "runtime" / LEDGER_DIRNAME


def ledger_path(omh_home: Path, session_id: str) -> Path:
    return ledger_dir(omh_home) / f"{ledger_key(session_id)}.json"


def title_from_goal(goal: object) -> str:
    """A child's title from its goal: the first line, without a team or dag marker or a leading ``TASK:`` label."""
    if not isinstance(goal, str):
        return ""
    for line in goal.splitlines():
        text = _TASK_LABEL.sub("", without_goal_marker(line.strip())).strip()
        if text:
            return " ".join(text.split())[:TITLE_LIMIT]
    return ""


def without_goal_marker(goal: str) -> str:
    """``goal`` without its dag or team markers, wherever they are: a marker binds the child, a person reads the rest."""
    return _GOAL_MARKER_TEXT.sub("", goal)


def dag_binding(goal: object) -> dict[str, str]:
    """The dag run and node the last whole marker in a child's goal names, or {}: two ids, never goal text.

    Every line counts, and a goal whose last marker is a team key binds no node.
    """
    if not isinstance(goal, str):
        return {}
    found = _DAG_MARKER.findall(goal)
    if not found or not found[-1][0]:
        return {}
    run, node = found[-1]
    return {"run": run, "node": node}


def child_title(subagent_id: str) -> str:
    """The title this process saw at `subagent_start`, or "" (never written to disk)."""
    return _titles.get(subagent_id, "")


def oneshot_children_spawned(session_ids: Sequence[str]) -> int:
    """How many top-level children this process saw start in these conversation segments (`subagent_start`)."""
    return sum(_spawned.get(_text(session_id), 0) for session_id in set(session_ids))


def _count_spawned(root: str, subagent_id: str) -> None:
    if subagent_id in _spawned_ids:
        return
    _remember(_spawned_ids, subagent_id, root, SPAWNED_ID_LIMIT)
    count = _spawned.get(root, 0) + 1
    _spawned[root] = count
    _spawned.move_to_end(root)
    while len(_spawned) > ROOT_CACHE_LIMIT:
        _spawned.popitem(last=False)


def _remember(cache: OrderedDict[str, str], key: str, value: str, limit: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)


def _text(value: object, limit: int = ID_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip() if ch.isprintable())[:limit]


def _homes(kwargs: dict[str, object]) -> tuple[Path, Path] | None:
    """The OMH and Hermes homes a hook call resolves to, or None (counted) when the host cannot say."""
    try:
        return (
            runtime_paths.plugin_home(kwargs.get("omh_home")),
            runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True),
        )
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as error:
        ledger_declines[f"homes_unresolved:{type(error).__name__}"] += 1
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


# ── whose conversation ───────────────────────────────────────────────────


def _delegated_from(hermes_home: Path, session_id: str) -> str:
    """The parent a child row names in ``model_config._delegate_from``, or ""."""
    state_db = hermes_home / "state.db"
    if not state_db.is_file():
        return ""
    try:
        connection = connect_readonly(state_db, timeout=0.25)
    except sqlite3.Error:
        return ""
    try:
        row = connection.execute("SELECT model_config FROM sessions WHERE id = ?", (session_id,)).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        connection.close()
    if not row or not isinstance(row[0], str):
        return ""
    try:
        config = json.loads(row[0])
    except ValueError:
        return ""
    return _text(config.get("_delegate_from")) if isinstance(config, dict) else ""


def root_session(session_id: str, hermes_home: Path) -> str:
    """The conversation a (possibly nested) child belongs to.

    This process records each child's root when it starts; a child it never
    saw (a restart in between) is followed up its `_delegate_from` chain in
    `state.db`, at most `ROOT_WALK_LIMIT` steps. A session that names no
    parent is its own root.
    """
    current = _text(session_id)
    seen = {current}
    for _ in range(ROOT_WALK_LIMIT):
        if current in _roots:
            return _roots[current]
        parent = _delegated_from(hermes_home, current)
        if not parent or parent in seen:
            return current
        seen.add(parent)
        current = parent
    return current


# ── the record ───────────────────────────────────────────────────────────


def _empty(session_id: str) -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "session_id": session_id,
        "calls": [],
        "children": [],
        "unjoined_stops": [],
        "posted": {},
        "skipped": {},
        "updated_at": 0.0,
        "claim_boundary": LEDGER_CLAIM_BOUNDARY,
    }


def _valid_route(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    route = {field: _text(value.get(field), WORD_LIMIT if field in ("origin", "reasoning_effort") else ID_LIMIT)
             for field in ROUTE_FIELDS}
    return route if route.get("category") or route.get("wire_model") or route.get("origin") else {}


def valid_observed_route(value: object) -> dict[str, Any]:
    """The ``route`` Hermes (0.22.5+) reported on a child's result, field by field; ``{}`` when it is not one.

    Hermes reports it for a backend-routed child only: the backend, the
    user's option or profile (``label``), and the provider, model and effort
    read off the child when its result was assembled. It is the record of
    where the child ran, which no OMH-prepared route replaces.
    """
    if not isinstance(value, dict):
        return {}
    route: dict[str, Any] = {
        field: _text(value.get(field), WORD_LIMIT if field in ("backend", "reasoning_effort", "service_tier")
                     else ID_LIMIT)
        for field in OBSERVED_ROUTE_FIELDS
    }
    route = {field: text for field, text in route.items() if text}
    if not route.get("backend"):
        return {}
    for flag in ("fallback_activated", "refused"):
        if value.get(flag) is True:
            route[flag] = True
    return route


def _valid_child(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    subagent_id, child = _text(value.get("subagent_id")), _text(value.get("child_session_id"))
    started = _number(value.get("started_at"))
    if not subagent_id or not child or started is None:
        return None
    entry: dict[str, Any] = {
        "subagent_id": subagent_id,
        "child_session_id": child,
        "parent_session_id": _text(value.get("parent_session_id")),
        "parent_subagent_id": _text(value.get("parent_subagent_id")),
        "parent_turn_id": _text(value.get("parent_turn_id")),
        "role": _text(value.get("role"), WORD_LIMIT),
        "started_at": started,
        "route": _valid_route(value.get("route")),
    }
    observed = valid_observed_route(value.get("observed_route"))
    if observed:
        entry["observed_route"] = observed
    for key in ("call_id", "delegation_id"):
        if _text(value.get(key)):
            entry[key] = _text(value.get(key))
    dag = value.get("dag")
    if isinstance(dag, dict) and all(re.fullmatch(_DAG_ID, str(dag.get(key))) for key in ("run", "node")):
        entry["dag"] = {"run": str(dag["run"]), "node": str(dag["node"])}
    if (process := recorded_process(value.get("host"))) is not None:
        entry["host"] = process
    resumed = _number(value.get("resumed_at"))
    resumes = value.get("resumes")
    if resumed is not None and isinstance(resumes, int) and not isinstance(resumes, bool) and 0 < resumes <= RESUME_LIMIT:
        entry.update(resumed_at=resumed, resumes=resumes)
    index = value.get("task_index")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < 1024:
        entry["task_index"] = index
    stop = value.get("stop")
    if isinstance(stop, dict) and _number(stop.get("observed_at")) is not None:
        entry["stop"] = {
            "status": _text(stop.get("status"), WORD_LIMIT),
            "observed_at": _number(stop.get("observed_at")),
            "duration_ms": _duration(stop.get("duration_ms")),
        }
    return entry


def _duration(value: object) -> int | None:
    """Milliseconds as Hermes reports them: a non-negative int under `DURATION_MS_LIMIT`, else None."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < DURATION_MS_LIMIT:
        return value
    return None


def _valid_call(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    observed = _number(value.get("observed_at"))
    mode = value.get("mode")
    if observed is None or mode not in ("background", "sync"):
        return None
    count = value.get("task_count")
    ids = value.get("delegation_ids")
    return {
        "call_id": _text(value.get("call_id")),
        "session_id": _text(value.get("session_id")),
        "turn_id": _text(value.get("turn_id")),
        "observed_at": observed,
        "mode": mode,
        "task_count": count if isinstance(count, int) and not isinstance(count, bool) and 0 <= count < 1024 else 0,
        "delegation_ids": [_text(item) for item in ids[:16] if _text(item)] if isinstance(ids, list) else [],
    }


def parse_ledger(raw: object) -> dict[str, Any] | None:
    """One stored record, validated field by field; None when it is not a ledger at all."""
    if not isinstance(raw, dict) or raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        return None
    session_id = _text(raw.get("session_id"))
    if not session_id:
        return None
    record = _empty(session_id)
    for key, validate, limit in (
        ("calls", _valid_call, LEDGER_CALL_LIMIT),
        ("children", _valid_child, LEDGER_CHILD_LIMIT),
    ):
        items = raw.get(key)
        record[key] = [item for item in map(validate, items if isinstance(items, list) else [])
                       if item is not None][-limit:]
    stops = raw.get("unjoined_stops")
    record["unjoined_stops"] = [
        {"child_session_id": _text(item.get("child_session_id")), "status": _text(item.get("status"), WORD_LIMIT),
         "observed_at": _number(item.get("observed_at"))}
        for item in (stops if isinstance(stops, list) else [])
        if isinstance(item, dict) and _text(item.get("child_session_id")) and _number(item.get("observed_at")) is not None
    ][-LEDGER_STOP_LIMIT:]
    posted = raw.get("posted")
    if isinstance(posted, dict) and isinstance(posted.get("fingerprint"), str):
        closed, seen = posted.get("closed"), posted.get("seen")
        record["posted"] = {
            "fingerprint": posted["fingerprint"][:64],
            "observed_at": _number(posted.get("observed_at")),
            "moment": posted.get("moment") if posted.get("moment") in POST_MOMENTS else "",
            "phase": posted.get("phase") if posted.get("phase") in RUN_PHASES else "",
            "counts": _text(posted.get("counts"), 64),
            "closed": [_text(item, 16) for item in (closed if isinstance(closed, list) else []) if _text(item, 16)][
                -CLOSED_LIMIT:
            ],
            "seen": [_text(item, 16) for item in (seen if isinstance(seen, list) else []) if _text(item, 16)][
                -SEEN_LIMIT:
            ],
        }
    skipped = raw.get("skipped")
    if isinstance(skipped, dict) and isinstance(skipped.get("fingerprint"), str):
        record["skipped"] = {"fingerprint": skipped["fingerprint"][:64], "reason": _text(skipped.get("reason"), WORD_LIMIT),
                             "observed_at": _number(skipped.get("observed_at"))}
    record["updated_at"] = _number(raw.get("updated_at")) or 0.0
    return record


def read_ledger(omh_home: Path, session_id: str) -> dict[str, Any] | None:
    """The conversation's record, or None when there is none or it cannot be read as one."""
    if not session_id:
        return None
    path = ledger_path(omh_home, session_id)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > LEDGER_MAX_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    record = parse_ledger(raw)
    return record if record is not None and record["session_id"] == _text(session_id) else None


def newest_ledger_session(omh_home: Path, *, now: float, max_age: float = LEDGER_MAX_AGE_SECONDS) -> str:
    """The conversation whose record changed last, for a reader that names none (`omh hud`), or ""."""
    directory = ledger_dir(omh_home)
    newest: tuple[float, Path] | None = None
    try:
        for path in directory.iterdir():
            if path.suffix != ".json" or path.name.startswith(".") or path.is_symlink():
                continue
            mtime = path.stat().st_mtime
            if now - mtime <= max_age and (newest is None or mtime > newest[0]):
                newest = (mtime, path)
    except OSError:
        return ""
    if newest is None:
        return ""
    try:
        raw = json.loads(newest[1].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return ""
    record = parse_ledger(raw)
    return record["session_id"] if record else ""


def prune_ledgers(omh_home: Path, *, now: float | None = None) -> int:
    """Remove the conversation records no hook has written for `LEDGER_MAX_AGE_SECONDS`; everything in them aged out.

    A record's age is its file's modification time against the wall clock
    (``now`` defaults to it). Each is removed under its own lock, after its age
    is read again there, so a record a hook is writing is never removed. The
    lock files stay: another process may be waiting on one, and a lock removed
    under a waiter would let two writers in at once. Returns how many records
    were removed.
    """
    now = time.time() if now is None else now
    try:
        paths = [path for path in ledger_dir(omh_home).iterdir()
                 if path.suffix == ".json" and not path.name.startswith(".") and not path.is_symlink()]
    except OSError:
        return 0
    removed = 0
    for path in paths:
        try:
            if now - path.stat().st_mtime <= LEDGER_MAX_AGE_SECONDS:
                continue
            with _awareness_delivery_lock(path, timeout_seconds=PRUNE_LOCK_SECONDS):
                if not path.is_symlink() and now - path.stat().st_mtime > LEDGER_MAX_AGE_SECONDS:
                    path.unlink()
                    removed += 1
        except (OSError, ValueError) as error:  # a record another process holds is left for a later pass
            ledger_declines[f"ledger_prune:{type(error).__name__}"] += 1
    return removed


def _prune(record: dict[str, Any], now: float) -> None:
    cutoff = now - LEDGER_MAX_AGE_SECONDS
    record["calls"] = [call for call in record["calls"] if call["observed_at"] >= cutoff][-LEDGER_CALL_LIMIT:]
    record["children"] = [child for child in record["children"] if child["started_at"] >= cutoff][-LEDGER_CHILD_LIMIT:]
    record["unjoined_stops"] = [stop for stop in record["unjoined_stops"]
                                if (stop["observed_at"] or 0.0) >= cutoff][-LEDGER_STOP_LIMIT:]


def _update(omh_home: Path, session_id: str, change: Any, *, now: float) -> bool:
    """Read-modify-write one record under its lock; False (and a counted decline) on any failure."""
    path = ledger_path(omh_home, session_id)
    try:
        with _awareness_delivery_lock(path, timeout_seconds=LEDGER_LOCK_SECONDS):
            if path.is_symlink():
                ledger_declines["ledger_symlink"] += 1
                return False
            record = read_ledger(omh_home, session_id) or _empty(_text(session_id))
            if not change(record):
                return False
            _prune(record, now)
            record["updated_at"] = now
            data = json.dumps(record, sort_keys=True).encode("utf-8")
            if len(data) > LEDGER_MAX_BYTES:
                ledger_declines["ledger_too_large"] += 1
                return False
            temporary = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(6)}.tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(data + b"\n")
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
            finally:
                if temporary.exists() and not temporary.is_symlink():
                    temporary.unlink()
            return True
    except (OSError, ValueError) as error:  # TimeoutError is an OSError: a busy record is a decline too.
        ledger_declines[f"ledger_write:{type(error).__name__}"] += 1
        return False


def _route_now(omh_home: Path, session_id: str, now: float) -> dict[str, str]:
    """The newest route OMH recorded for ``session_id`` before ``now``, if fresh; {} otherwise."""
    for record in reversed(load_delegation_route_provenance(omh_home)):
        if record.get("session_id") != session_id or record["written_at"] > now:
            continue
        if now - record["written_at"] > ROUTE_FRESHNESS_SECONDS:
            return {}
        route = _valid_route({**record, "origin": record.get("origin", "")})
        return route
    return {}


# ── the three observers ──────────────────────────────────────────────────


def observe_subagent_start(kwargs: dict[str, object], *, now: float | None = None) -> bool:
    child = _text(kwargs.get("child_session_id"))
    subagent_id = _text(kwargs.get("child_subagent_id"))
    parent = _text(kwargs.get("parent_session_id"))
    if not child or not subagent_id or not parent or child == parent:
        ledger_declines["start_missing_identity"] += 1
        return False
    moment = time.time() if now is None else now
    homes = _homes(kwargs)
    top_level = not _text(kwargs.get("parent_subagent_id"))
    if homes is None:
        # Hermes charged its budget for the child all the same: count it under the root this process knows.
        if top_level:
            _count_spawned(_roots.get(parent, parent), subagent_id)
        return False
    omh_home, hermes_home = homes
    root = root_session(parent, hermes_home)
    if top_level:
        _count_spawned(root, subagent_id)
    _remember(_roots, child, root, ROOT_CACHE_LIMIT)
    title = title_from_goal(kwargs.get("child_goal"))
    if title:
        _remember(_titles, subagent_id, title, TITLE_CACHE_LIMIT)
    entry = {
        "subagent_id": subagent_id,
        "child_session_id": child,
        "parent_session_id": parent,
        "parent_subagent_id": _text(kwargs.get("parent_subagent_id")),
        "parent_turn_id": _text(kwargs.get("parent_turn_id")),
        "role": _text(kwargs.get("child_role"), WORD_LIMIT),
        "started_at": moment,
        "route": _route_now(omh_home, parent, moment),
    }
    binding = dag_binding(kwargs.get("child_goal"))
    if binding:
        entry["dag"] = binding
        # The Hermes process the child runs in and ends with: a restart fires no `subagent_stop`, so `omh_dag`
        # tells a node whose child it ended from one still running by this.
        if (process := this_process()) is not None:
            entry["host"] = process

    def add(record: dict[str, Any]) -> bool:
        for item in record["children"]:
            if item["subagent_id"] != subagent_id:
                continue
            if item["child_session_id"] != child:
                return False
            # Hermes continued this child on its own conversation (`delegation.auto_resume`, or the parent's
            # `delegate_task(action='continue')`): the same subagent id and session start again. The earlier
            # stop (a usage limit, a restart) no longer describes it, and it now runs in this process.
            item.pop("stop", None)
            item["resumed_at"] = moment
            item["resumes"] = min(int(item.get("resumes", 0)) + 1, RESUME_LIMIT)
            if "host" in entry:
                item["host"] = entry["host"]
            else:
                item.pop("host", None)
            return True
        record["children"].append(entry)
        return True

    added = _update(omh_home, root, add, now=moment)
    wall = time.time()
    if wall - _pruned_at[0] > PRUNE_INTERVAL_SECONDS:
        _pruned_at[0] = wall
        prune_ledgers(omh_home, now=wall)
    return added


def observe_delegate_call(kwargs: dict[str, object], *, now: float | None = None) -> bool:
    """`post_tool_call` for `delegate_task`: tie each child to its call, task index and delegation."""
    if kwargs.get("tool_name") != "delegate_task":
        return False
    session = _text(kwargs.get("session_id"))
    result = kwargs.get("result")
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        ledger_declines["call_result_unreadable"] += 1
        return False
    if not session or not isinstance(payload, dict):
        return False
    moment = time.time() if now is None else now
    homes = _homes(kwargs)
    if homes is None:
        return False
    omh_home, hermes_home = homes
    root = root_session(session, hermes_home)
    call_id = _text(kwargs.get("tool_call_id"))
    turn = _text(kwargs.get("turn_id"))
    if payload.get("status") == "dispatched" and isinstance(payload.get("subagent_ids"), list):
        order = [_text(item) for item in payload["subagent_ids"]]
        main_id = _text(payload.get("delegation_id"))
        by_index: dict[int, str] = {}
        for unit in payload.get("units") if isinstance(payload.get("units"), list) else []:
            if isinstance(unit, dict) and isinstance(unit.get("task_indexes"), list):
                for index in unit["task_indexes"]:
                    if isinstance(index, int) and not isinstance(index, bool):
                        by_index[index] = _text(unit.get("delegation_id"))
        call = {"call_id": call_id, "session_id": session, "turn_id": turn, "observed_at": moment,
                "mode": "background", "task_count": len(order),
                "delegation_ids": sorted({main_id, *by_index.values()} - {""})}

        def bind(record: dict[str, Any]) -> bool:
            record["calls"].append(call)
            for index, subagent_id in enumerate(order):
                for child in record["children"]:
                    if subagent_id and child["subagent_id"] == subagent_id and "call_id" not in child:
                        child.update(call_id=call_id, task_index=index,
                                     delegation_id=by_index.get(index) or main_id)
            return True

        return _update(omh_home, root, bind, now=moment)
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    count = len(results)
    duration = _number(kwargs.get("duration_ms")) or 0.0
    since = moment - duration / 1000.0 - 2.0
    call = {"call_id": call_id, "session_id": session, "turn_id": turn, "observed_at": moment,
            "mode": "sync", "task_count": count, "delegation_ids": []}

    def bind_sync(record: dict[str, Any]) -> bool:
        record["calls"].append(call)
        started = sorted(
            (child for child in record["children"]
             if child["parent_session_id"] == session and "call_id" not in child
             and (not turn or child["parent_turn_id"] == turn) and since <= child["started_at"] <= moment),
            key=lambda child: child["started_at"],
        )
        # Hermes builds a call's children one by one in task order, and each one's `subagent_start`
        # fires as it is built; only an exact count makes that order the task order.
        if len(started) == count:
            for index, child in enumerate(started):
                child.update(call_id=call_id, task_index=index)
                observed = reported.get(index)
                if observed:
                    child["observed_route"] = observed
        else:
            ledger_declines["sync_children_unpaired"] += 1
        return True

    # Hermes 0.22.5+ reports, per task, where a backend-routed child ran.
    reported: dict[int, dict[str, Any]] = {}
    for position, entry in enumerate(results):
        if not isinstance(entry, dict):
            continue
        index = entry.get("task_index")
        index = index if isinstance(index, int) and not isinstance(index, bool) else position
        observed = valid_observed_route(entry.get("route"))
        if observed:
            reported[index] = observed

    return _update(omh_home, root, bind_sync, now=moment)


def observe_subagent_stop(kwargs: dict[str, object], *, now: float | None = None) -> bool:
    child = _text(kwargs.get("child_session_id"))
    parent = _text(kwargs.get("parent_session_id"))
    if not child or not parent:
        ledger_declines["stop_missing_identity"] += 1
        return False
    moment = time.time() if now is None else now
    homes = _homes(kwargs)
    if homes is None:
        return False
    omh_home, hermes_home = homes
    root = root_session(parent, hermes_home)
    stop = {
        "status": _text(kwargs.get("child_status"), WORD_LIMIT),
        "observed_at": moment,
        "duration_ms": _duration(kwargs.get("duration_ms")),
    }

    def close(record: dict[str, Any]) -> bool:
        for entry in record["children"]:
            if entry["child_session_id"] == child and "stop" not in entry:
                entry["stop"] = stop
                return True
        # A stop naming a session no start named: the child's id moved (compaction) or its start was lost.
        record["unjoined_stops"].append({"child_session_id": child, "status": stop["status"], "observed_at": moment})
        return True

    return _update(omh_home, root, close, now=moment)


def with_unjoined_stop(
    child: dict[str, Any], stops: Sequence[dict[str, Any]], later: Sequence[str] = ()
) -> dict[str, Any]:
    """``child`` with the newest unjoined stop naming it, or one of ``later`` (its continuations), if it has no stop.

    Hermes names the sessions as they are when a child stops: a parent its
    rotating compaction moved since the start files the stop under the new
    segment, whose record holds no start for the child, and a child rotated
    since then is named by its continuation. ``stops`` are the
    ``unjoined_stops`` of every segment of the conversation; the delegation
    graph and `omh_dag` read a child's stop through this one rule. A child
    Hermes resumed (``resumed_at``) takes only a stop observed since then.
    """
    if isinstance(child.get("stop"), dict):
        return child
    names = {child["child_session_id"], *later}
    # A resumed child is answered only by a stop of the run that resumed it, not one an earlier run left behind.
    since = _number(child.get("resumed_at"))
    found = [stop for stop in stops if stop["child_session_id"] in names
             and (since is None or (_number(stop.get("observed_at")) or 0.0) >= since)]
    if not found:
        return child
    stop = max(found, key=lambda item: item["observed_at"])
    return {**child, "stop": {"status": stop["status"], "observed_at": stop["observed_at"], "duration_ms": None}}


def posted_fingerprint(omh_home: Path, session_id: str) -> str:
    return str(posted_record(omh_home, session_id).get("fingerprint", ""))


def posted_record(omh_home: Path, session_id: str) -> dict[str, Any]:
    """What the last chat post recorded (fingerprint, moment, run phase, counts, closed and seen lanes), or {}."""
    record = read_ledger(omh_home, session_id)
    return dict(record["posted"]) if record else {}


def conversation_posted(omh_home: Path, segments: Sequence[str]) -> dict[str, Any]:
    """The newest `posted_record` among a conversation's segments, the first segment's on a tie, or {}.

    Hermes' rotating compaction moves a conversation to a new session id mid-run;
    what an earlier segment posted speaks for the run until the new one posts.
    """
    return max((posted_record(omh_home, segment) for segment in segments),
               key=lambda posted: posted.get("observed_at") or 0.0, default={})


def note_posted(
    omh_home: Path,
    session_id: str,
    fingerprint: str,
    *,
    moment_name: str = "",
    phase: str = "",
    counts: str = "",
    closed: Sequence[str] = (),
    seen: Sequence[str] = (),
    now: float | None = None,
) -> bool:
    """Record what a reply just carried, so the same graph, or the same counts in a run, is not posted again.

    ``closed`` holds the keys of the lanes whose run an end post closed; a
    later run is made of the lanes not in it. ``seen`` holds the keys of the
    lanes a post has shown, so a node added mid-run is named once.
    """
    moment = time.time() if now is None else now

    def mark(record: dict[str, Any]) -> bool:
        record["posted"] = {
            "fingerprint": fingerprint[:64],
            "observed_at": moment,
            "moment": moment_name if moment_name in POST_MOMENTS else "",
            "phase": phase if phase in RUN_PHASES else "",
            "counts": _text(counts, 64),
            "closed": [_text(item, 16) for item in closed if _text(item, 16)][-CLOSED_LIMIT:],
            "seen": [_text(item, 16) for item in seen if _text(item, 16)][-SEEN_LIMIT:],
        }
        record["skipped"] = {}
        return True

    return _update(omh_home, session_id, mark, now=moment)


def note_skipped(omh_home: Path, session_id: str, fingerprint: str, reason: str, *, now: float | None = None) -> bool:
    """Record that a changed graph was not posted, and why; the posted fingerprint stays, so a later reply can post it."""
    moment = time.time() if now is None else now

    def mark(record: dict[str, Any]) -> bool:
        current = record.get("skipped") or {}
        if (current.get("fingerprint"), current.get("reason")) == (fingerprint[:64], reason):
            return False
        record["skipped"] = {"fingerprint": fingerprint[:64], "reason": _text(reason, WORD_LIMIT), "observed_at": moment}
        return True

    return _update(omh_home, session_id, mark, now=moment)
