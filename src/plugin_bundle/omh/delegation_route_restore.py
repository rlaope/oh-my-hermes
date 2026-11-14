"""The way back from a prepared delegation route.

`delegation_routing.write_delegation_route` is the one-way half: it sets the
three routable keys Hermes re-reads per dispatch. Nothing put back what was
there before, so a route chosen for one lane stayed in `config.yaml` as every
later session's delegation default (#1724).

This module owns the way back. It records, beside the route write and under
the same lock:

* the **baseline** -- what the three keys held before OMH first wrote them. A
  key the file did not carry is recorded by being ABSENT from the mapping, so
  restoring it removes the key rather than writing an empty string.
* the **last write** -- the exact three-key mapping OMH left in the file, plus
  the session and task that left it there.
* the **config path** those statements are about.

## The baseline is what the PERSON had, not what OMH left

Reading "whatever the file holds" as the person's value is wrong on exactly
the machine this issue came from, where the file already held a leaked OMH
route: the first new route would have recorded `claude-fable-5-1` as the
baseline and every later restore would have put the most expensive model in
the chain back, permanently.

The evidence to recognise that lives in the same OMH home. Every route OMH
writes appends to `route-provenance.json`, so before capturing a baseline
this compares the current three keys with the newest record there that left a
route in the file. On an exact match of all three the value is OMH's own
leftover, the baseline is recorded as "keys absent", and `baseline_origin`
says `omh_leftover` so a reader is never told a guess was an observation. The
same check runs on a re-capture, which closes the hole a failed record write
would otherwise reopen: the route lands, nothing is recorded, and the next
route would have enshrined it.

## Scope: a task, because `on_session_end` is per turn

`on_session_end` is not a session boundary. Hermes fires it from
`agent/turn_finalizer.py`, whose own comment reads "run_conversation() runs
once per message", and `docs/SESSION-ACTIVITY-RECEIPTS.md` already recorded
that. A route therefore comes back at the end of the turn that wrote it, and
that is the design rather than an accident: "route the NEXT dispatch" is a
turn-local intent, a `delegate_task` is dispatched inside the turn that set
the route, and a child already running keeps its model.

The scope is the TASK, not the turn, because a plugin tool cannot learn the
turn. The host threads `turn_id` to hooks and to `handle_function_call`, but
`model_tools._execute_tool` passes a registry handler only `task_id` and
`session_id`; the turn id exists elsewhere solely in a private ContextVar of
`tools.approval_context` with no getter.

What a task is differs by flow, and both are ordinary:

* **TUI and CLI.** `_bind_turn_identity` defaults `task_id` to a fresh uuid
  per turn, so task scope IS turn scope. A restore that does not happen at
  its own turn end -- see below -- is then never retried by a later turn of
  this session, and waits for the next session start.
* **Every gateway platform** (Slack, Discord, Telegram, Feishu, the API
  server). `gateway/run_turn_runner.py` passes `task_id: ctx.session_id` and
  `gateway/run_turn.py` states that task_id is session-scoped, so the task
  id is constant for the session and the scope is effectively the session.
  A route survives later turns of that session, and a missed restore is
  retried by the next turn end. This is the majority flow on the machine
  #1724 came from, where routes come from `slack` and `subagent` sessions.

A route does not always end with its turn, and two paths are known:

* A `lock_unavailable` at turn end (the budget is 0.1s) leaves the route.
  In the gateway flow the next turn end retries it; in the TUI/CLI flow
  nothing does before the next session start. The party that could not take
  the lock is also the party that cannot record that a restore is owed, so
  there is no cheap durable marker to retry from -- `pre_llm_call` at the
  start of a later turn is where such a retry would go, and it is not built
  here.
* A session killed mid-task, which is what `on_session_start` covers.

In both, the route survives until the next session start. A session start
puts it back once nothing says the writer's conversation is still running:
the writer's row is closed (or, after a compaction, every row Hermes
continued it in is), or that row's activity stamp is more than six hours old
(or unusable) and so is the route. A route whose writer row cannot be found,
or whose compaction continuation cannot be read, is held until the route
itself is six hours old. Only a conversation whose row shows activity within
the last six hours, and whose continuation can be read, holds it past that.
Turn scope makes a leak short and bounded rather than impossible.

`action=fallback` is the one flow that legitimately spans turns: a child that
dies on HTTP 400 is reported in a later turn. It used to read the chain
position out of the live `delegation.*` values, which a turn-end restore
empties, so it now recovers that position from the newest provenance record
the calling conversation wrote. See `delegate_route_tool`.

## A route is one conversation's; the keys are only where Hermes reads it

The three keys are one per profile and every session on it reads them, so a
route written by one conversation was the route of whichever session
dispatched next. Two sessions routing close together lost the earlier one's
route between its `set` and its `delegate_task`, and the child ran on the
other session's model with nothing reported (#2251). A released Hermes gives
a plugin no other way to name a child's model: the model-facing
`delegate_task` takes no model or provider, and its handler resolves the
child from `delegation.*` alone.

So each route is also recorded as the route of the conversation that set it,
in `conversation-routes.json`, under the same lock as the keys. `pre_tool_call`
for `delegate_task` then puts the DISPATCHING conversation's intent into the
keys just before Hermes reads them (`prepare_dispatch_route`): its own route
when it set one in this task; for a delegate child, the route of the
conversation it was delegated from (`_delegate_ancestors`); otherwise the
baseline in place of another conversation's route. Whatever another session
set, cleared, fell back to or restored in between, the dispatch runs on its
own route. A dispatch that cannot be made to run on its own route is
refused, never sent on another's. When the dispatching session's own
`state.db` row cannot be read, its lineage is unknown and another
conversation's route is left in the keys, as every dispatch did before.

Two more files keep an entry that failed to change from being applied, and
each is written before the `conversation-routes.json` write it covers, so it
survives that write failing. `conversation-take-outs.json` names the entries
a `clear` or chain exhaustion released (`_stamp_take_out`).
`conversation-writes.json` holds each writer's newest `set`, keyed like the
entries and in their shape (`_stamp_conversation_write`). An entry older
than its own key's stamp is the route that write failed to replace, so the
stamp stands in for it, and the writer's own dispatch -- or a child that
inherits from it -- runs on the newest route (`_in_force`). An older entry of
the same writer under another key that names another route is superseded,
not its intent (`_not_superseded`). A stamp stands in only for an entry that
survived the take-out filter, and every release -- turn end, session start,
`clear`, chain exhaustion -- marks the writer's stamps released before it
deletes the entries, so neither a release nor a release whose own write
failed brings a route back through a stamp. A child inherits the newest
write of the conversations it descends from, stamps included; each
conversation counts only a route no older than its own newest stamp or
take-out, so a later write in one ancestor never hides another's route
(`_newest_inherited`). The profile-wide
`route-restore.json` cannot hold any of this, because the next writer's `set`
replaces it and a restore deletes it.

What this does not close, stated at its real size: the hook releases the lock
before Hermes reads the keys, so another session's dispatch or `set` landing
between the two -- the hook-to-handler gap, not the model's round trip that
the race used to span -- still wins. A call that another gate sends to a
person (`approve`) has its route written before the person answers, so the
wait for that answer is part of the gap. Only a per-call route from Hermes
removes it. And with `HERMES_IGNORE_USER_CONFIG=1` Hermes reads none of the
file OMH writes, so no route applies at all.

## Ownership, liveness, locking

Every restore is gated on the recorded write. The file's current three keys
are compared with what OMH recorded writing; equal means OMH still owns the
value, different means a person (or another tool) changed it and OMH leaves
it alone and drops its now-meaningless record. The decision reads recorded
values, never wording.

`on_session_start` covers the case a killed session never reaches: it
restores only a route whose recorded writer is not live, asked of that
writer's OWN `state.db` row. Each verdict is named so a caller can tell an
observation from an age bound; see `writer_session_liveness`. A row Hermes
closed to compact the conversation is not that conversation ending: rotating
compaction closes the writer's row mid-turn and goes on in a new one, so the
question is asked of the rows Hermes went on in, and a route whose
continuation cannot be read stays where it is.

The whole read-through-replace sits inside one lock, because two sessions
routing at once would otherwise both read "no baseline recorded" and the
second would record the first's route as the person's. The lock is
`awareness_delivery`'s, the plugin's single file-locking implementation
(`approval_bypass` already shares it), with a POSIX and a Windows backend. It
is held on the record file in the OMH home rather than on `config.yaml`,
because the mutual exclusion needed is between OMH writers and because OMH
creates no lock file inside the Hermes home. (It does write there: the route
writer creates and chmods a temp file next to `config.yaml` for its atomic
replace. The lock file is the thing that stays out.)

Contention is an error, not a silent retry: a writer that cannot take the
lock returns `lock_unavailable` and never reports `routed`. A platform with
neither lock backend is different and is reported through `lock_enforced`,
because refusing there would disable routing entirely.

## What a restore does NOT promise

It restores the three keys to their previous VALUES, not to their previous
bytes. The writer normalises quoting, emits the keys in `ROUTABLE_KEYS`
order, and drops an inline comment that sat on one of those three lines.
Every other byte of the file is untouched. Preserving the original lines
verbatim would mean carrying them through a writer shared with the route
path, which is more machinery than the difference is worth; the claim is
stated at its real strength here, in the changelog, and in the docs.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Collection, Mapping

from . import runtime_paths
from .awareness_delivery import LOCK_MECHANISM_NONE, _awareness_delivery_lock
from .delegation_routing import (
    ROUTABLE_KEYS,
    _VALUE_RE,
    delegation_config_path,
    read_delegation_route,
    write_delegation_route,
)
from .hermes_delegation import append_delegation_route_provenance, load_delegation_route_provenance
from .kanban_board_reader import conversation_session_ids
from .sqlite_readonly import connect_readonly
from .live_session import (
    COMPACTION_END_REASON,
    LIVE_TUI_SESSION_FRESH_SECONDS,
    compaction_continuations,
    session_row,
)

DELEGATION_ROUTE_RESTORE_SCHEMA_VERSION = "delegation_route_restore/v2"
DELEGATION_ROUTE_RESTORE_FILE = "route-restore.json"
CONVERSATION_ROUTES_SCHEMA_VERSION = "delegation_conversation_routes/v1"
CONVERSATION_ROUTES_FILE = "conversation-routes.json"
CONVERSATION_TAKE_OUTS_SCHEMA_VERSION = "delegation_conversation_take_outs/v1"
CONVERSATION_TAKE_OUTS_FILE = "conversation-take-outs.json"
CONVERSATION_WRITES_SCHEMA_VERSION = "delegation_conversation_writes/v1"
CONVERSATION_WRITES_FILE = "conversation-writes.json"
_MAX_ID_CHARS = 160
_MAX_CONFIG_PATH_CHARS = 4096
# A conversation's route lives as long as its task, so an entry older than
# the liveness bound belongs to a session that is gone; the count bound
# keeps a busy gateway from growing the file without limit.
_MAX_CONVERSATION_ROUTES = 64
# `pre_tool_call` may wait for the lock longer than a tool's 0.1 s budget:
# what is at stake is which model a child runs on, and the hook's own budget
# is the host's `plugins.hook_callback_timeout` (30 s by default).
_DISPATCH_LOCK_SECONDS = 2.0
# Hermes routes plugin loggers into its own log files; a fallback here is
# not a failure the call sees, so the log is where an operator finds it.
_LOG = logging.getLogger("omh.delegation_route")
# How far up a delegate child's `_delegate_from` chain the dispatch looks for
# the conversation it was delegated from; the same bound the delegation
# ledger walks (`delegation_ledger.ROOT_WALK_LIMIT`).
_LINEAGE_WALK_LIMIT = 6

# Where a baseline came from. `person` is an observation of the file before
# OMH first wrote it; `omh_leftover` says the file already held a route OMH
# had written and not recorded, so the baseline is "keys absent" by
# derivation rather than by observation. A reader must be able to tell.
BASELINE_ORIGIN_PERSON = "person"
BASELINE_ORIGIN_OMH_LEFTOVER = "omh_leftover"

# Provenance origins that leave a route IN the file. `cleared` and
# `exhausted_to_inherit` describe one being taken out, so they say nothing
# about what the keys hold now.
_ROUTE_LEAVING_ORIGINS = ("head", "explicit", "fallback")

# The liveness verdicts that let a restore proceed, as an explicit allow-set
# rather than an inequality against "live". An inequality is how this went
# wrong twice: `!= "live"` would let `unknown_within_age_bound` through, and
# `!= "not_live"` refused the age-bound answers. Anything not listed here
# holds the route.
#
# `not_live` is the only observation in the set: the host closed the writer's
# row. The other two are the age bound, named so a reader can tell a bound
# from an observation.
LIVENESS_CLEARS_RESTORE = frozenset(
    {"not_live", "not_live_by_age", "unclosed_and_stale_by_age", "continuation_unverified_expired"}
)
# The verdicts a compaction continuation can give, the ones that hold the
# route first.
_CONTINUATION_VERDICT_ORDER = (
    "live", "unclosed_within_age_bound", "unclosed_and_stale_by_age", "not_live"
)

RESTORE_CLAIM_BOUNDARY = (
    "Baseline bookkeeping for the delegation.* keys of one config.yaml: what "
    "those three keys held before OMH first wrote them and what OMH wrote "
    "last. It is not evidence that any dispatch ran, which model a child "
    "used, or that a lane completed."
)


def delegation_route_restore_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "routing" / DELEGATION_ROUTE_RESTORE_FILE


def route_write_lock(omh_home: str | Path | None = None, *, timeout_seconds: float = 5.0):
    """The lock every writer of this OMH home's routes holds, for CLI writers too.

    `write_route_with_baseline` serializes on the restore record because the
    route write and its bookkeeping have to be one act. A `config.yaml`
    write from `omh setup`, `omh memory`, self-update or `system/targets`
    can land in the middle of that, so it takes the same
    lock rather than a second one of its own (#1742).

    The default wait is longer than the telemetry budget the lock ships
    with: a person is waiting on a CLI command, and dropping their write is
    worse than making them wait. A timeout raises `TimeoutError`, which the
    caller reports as a refusal.

    The asymmetry that makes this safe, written down because nothing else
    records it. `write_route_with_baseline` waits only the lock's own 0.1 s
    budget and returns an error rather than blocking a dispatch, so a CLI
    command holding this lock for longer than that DROPS a concurrent route
    write. The margin is the only reason that direction is safe, and it is
    not fixed: the hold grows with the size of the config, because every
    writer under it scans the whole file several times.

    Measured, mean of four runs each, against the 100 ms budget:

    | command        | 163-line config | 800-line synthetic |
    | -------------- | --------------- | ------------------ |
    | `omh apply`    | 2.0 ms          | 7.6 ms             |
    | `omh uninstall`| 3.4 ms          | 43.0 ms            |

    `omh uninstall` is the worst case, not `omh apply`: in the full scope it
    runs the registration removal and then the seven-key reversal. On a
    real config the headroom is ~30x; on a config four times that size it
    is closer to 2x. So two things break this: holding the lock across
    anything slow -- a network call, an interactive prompt, a subprocess --
    and adding another whole-file pass to a command that already holds it.
    Either should release the lock first.
    """
    return _awareness_delivery_lock(
        delegation_route_restore_path(omh_home), timeout_seconds=timeout_seconds
    )


def _valid_route_mapping(value: object) -> dict[str, str] | None:
    """A three-key subset whose values the route writer would accept.

    An absent key is the recorded spelling of "the file did not carry this
    key", so an empty mapping is valid and means "all three absent". A value
    the writer would refuse makes the whole record unusable rather than
    producing a write error later, which is why this refuses instead of
    dropping the offending key.
    """
    if not isinstance(value, dict):
        return None
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if key not in ROUTABLE_KEYS or not isinstance(item, str):
            return None
        if not _VALUE_RE.match(item):
            return None
        cleaned[key] = item
    return cleaned


def _valid_timestamp(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not value == value:  # NaN
        return None
    return float(value)


def _valid_identifier(value: object, limit: int = _MAX_ID_CHARS) -> str | None:
    if not isinstance(value, str) or len(value) > limit:
        return None
    return value


def _valid_restore_record(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != DELEGATION_ROUTE_RESTORE_SCHEMA_VERSION:
        return None
    baseline = _valid_route_mapping(raw.get("baseline"))
    written = _valid_route_mapping(raw.get("written"))
    if baseline is None or written is None:
        return None
    captured_at = _valid_timestamp(raw.get("baseline_captured_at"))
    written_at = _valid_timestamp(raw.get("written_at"))
    if captured_at is None or written_at is None:
        return None
    session_id = _valid_identifier(raw.get("writer_session_id", ""))
    task_id = _valid_identifier(raw.get("writer_task_id", ""))
    config_path = _valid_identifier(raw.get("config_path", ""), _MAX_CONFIG_PATH_CHARS)
    if session_id is None or task_id is None or not config_path:
        return None
    origin = raw.get("baseline_origin", "")
    if origin not in (BASELINE_ORIGIN_PERSON, BASELINE_ORIGIN_OMH_LEFTOVER):
        return None
    return {
        "schema_version": DELEGATION_ROUTE_RESTORE_SCHEMA_VERSION,
        "config_path": config_path,
        "baseline": baseline,
        "baseline_captured_at": captured_at,
        "baseline_origin": origin,
        "written": written,
        "writer_session_id": session_id,
        "writer_task_id": task_id,
        "written_at": written_at,
    }


def load_route_restore_record(omh_home: str | Path | None = None) -> dict[str, Any]:
    """The current baseline record, or `{}` when there is none to trust.

    A missing, unreadable, or malformed file all read as "no record". That is
    the safe direction in both places it is consulted: with no record nothing
    is restored and `config.yaml` is left exactly as it is.
    """
    path = delegation_route_restore_path(omh_home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return _valid_restore_record(raw) or {}


def _write_restore_record(path: Path, record: dict[str, Any]) -> None:
    payload = dict(record)
    payload["claim_boundary"] = RESTORE_CLAIM_BOUNDARY
    _write_private_json(path, payload)


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    created = False
    try:
        with temp.open("x", encoding="utf-8") as handle:
            created = True
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temp.chmod(0o600)
        temp.replace(path)
        path.chmod(0o600)
    except OSError:
        if created and temp.exists() and not temp.is_symlink():
            temp.unlink()
        raise


def _discard_restore_record(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def conversation_routes_path(omh_home: str | Path | None = None) -> Path:
    return delegation_route_restore_path(omh_home).with_name(CONVERSATION_ROUTES_FILE)


def _valid_conversation_route(key: object, raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not _valid_identifier(key) or not key:
        return None
    route = _valid_route_mapping(raw.get("route"))
    written_at = _valid_timestamp(raw.get("written_at"))
    session_id = _valid_identifier(raw.get("session_id", ""))
    task_id = _valid_identifier(raw.get("task_id", ""))
    config_path = _valid_identifier(raw.get("config_path", ""), _MAX_CONFIG_PATH_CHARS)
    if not route or written_at is None or session_id is None or task_id is None or not config_path:
        return None
    if not (session_id or task_id):
        return None
    return {
        "config_path": config_path,
        "route": route,
        "session_id": session_id,
        "task_id": task_id,
        "written_at": written_at,
    }


def _conversation_route_key(session_id: str, task_id: str) -> str:
    """One entry per session; a host that named no session is keyed by its task."""
    return session_id if session_id else f"task:{task_id}"[:_MAX_ID_CHARS]


def load_conversation_routes(omh_home: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Each conversation's own route, keyed by the session (or task) that set it.

    An unreadable file reads as "no conversation has a route", which is the
    behaviour before this record existed: a dispatch then runs on whatever
    the keys hold. A malformed entry is dropped alone, since one session's
    bad entry says nothing about another's.
    """
    try:
        raw = json.loads(conversation_routes_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema_version") != CONVERSATION_ROUTES_SCHEMA_VERSION:
        return {}
    routes = raw.get("routes")
    if not isinstance(routes, dict):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for key, entry in routes.items():
        valid = _valid_conversation_route(key, entry)
        if valid is not None:
            cleaned[key] = valid
    return cleaned


def _write_conversation_routes(omh_home: str | Path | None, routes: dict[str, dict[str, Any]]) -> None:
    path = conversation_routes_path(omh_home)
    if not routes:
        _discard_restore_record(path)
        return
    _write_private_json(
        path,
        {
            "schema_version": CONVERSATION_ROUTES_SCHEMA_VERSION,
            "routes": routes,
            "claim_boundary": (
                "The route each conversation asked omh_delegate_route for, so its own "
                "delegate_task dispatch can be put back on it. It is not evidence that "
                "any dispatch ran or which model a child used."
            ),
        },
    )


def _store_conversation_route(
    omh_home: str | Path | None,
    *,
    session_id: str,
    task_id: str,
    config_path: str,
    route: dict[str, str],
    written_at: float,
) -> str:
    """Record `route` as this session's; the caller holds `route_write_lock`.

    Like `_store_record`, a failure is named rather than raised: the route is
    already in the keys, and without this entry the dispatch runs on whatever
    the keys hold, which is how every dispatch ran before it existed.
    """
    if not (session_id or task_id):
        return "unrecorded: no session or task"
    routes = {
        key: entry
        for key, entry in load_conversation_routes(omh_home).items()
        if written_at - entry["written_at"] <= LIVE_TUI_SESSION_FRESH_SECONDS
    }
    routes[_conversation_route_key(session_id, task_id)] = {
        "config_path": config_path,
        "route": dict(route),
        "session_id": session_id,
        "task_id": task_id,
        "written_at": written_at,
    }
    newest = sorted(routes.items(), key=lambda item: item[1]["written_at"])[-_MAX_CONVERSATION_ROUTES:]
    try:
        _write_conversation_routes(omh_home, dict(newest))
    except OSError as exc:
        return f"unrecorded: {type(exc).__name__}"
    return "recorded"


def _release_locked(
    omh_home: str | Path | None, *, task_id: str, conversation: Collection[str]
) -> dict[str, Any]:
    """Drop the entries whose task is `task_id` or whose session is in `conversation`.

    The caller holds `route_write_lock`.
    """
    routes = load_conversation_routes(omh_home)
    kept = {key: entry for key, entry in routes.items() if not _released_by(entry, task_id, conversation)}
    if len(kept) != len(routes) or not kept:
        _write_conversation_routes(omh_home, kept)
    return {"status": "released", "released": len(routes) - len(kept)}


def _released_by(entry: Mapping[str, Any], task_id: str, conversation: Collection[str]) -> bool:
    """Is `entry` one a release of `task_id` and `conversation` drops?"""
    return bool(task_id and entry["task_id"] == task_id) or bool(
        entry["session_id"] and entry["session_id"] in conversation
    )


def conversation_take_outs_path(omh_home: str | Path | None = None) -> Path:
    return delegation_route_restore_path(omh_home).with_name(CONVERSATION_TAKE_OUTS_FILE)


def load_conversation_take_outs(omh_home: str | Path | None = None) -> dict[str, float]:
    """The entries a `clear` or chain exhaustion took out: entry key to its `written_at`.

    An unreadable file reads as "nothing taken out", which is the behaviour
    before this file existed, and a malformed stamp is dropped alone.
    """
    try:
        raw = json.loads(conversation_take_outs_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema_version") != CONVERSATION_TAKE_OUTS_SCHEMA_VERSION:
        return {}
    stamps = raw.get("taken_out")
    if not isinstance(stamps, dict):
        return {}
    cleaned: dict[str, float] = {}
    for key, value in stamps.items():
        at = _valid_timestamp(value)
        if _valid_identifier(key) and key and at is not None:
            cleaned[key] = at
    return cleaned


def _stamp_take_out(omh_home: str | Path | None, *, task_id: str, conversation: Collection[str]) -> str:
    """Record which entries a `clear` or chain exhaustion is about to release.

    The caller holds `route_write_lock` and releases right after. When that
    release fails, the entries stay in `conversation-routes.json`, and
    without a stamp the same task's next dispatch put the cleared route -- or,
    for exhaustion, the failing model -- back (#2258 and #2264 reviews). So
    the stamp is written first, to its own file, whatever the restore
    decided, and names each entry by its key (the session, or `task:<id>`
    for a host that names no session) and its `written_at`: a later `set`
    of the same conversation writes a newer entry, which no stamp covers.
    A stamp is kept only while its entry is still in the routes file, so the
    file holds no more stamps than that file holds entries.

    Like `_store_conversation_route`, a failure is named rather than raised.
    """
    routes = load_conversation_routes(omh_home)
    taking = {
        key: entry["written_at"] for key, entry in routes.items() if _released_by(entry, task_id, conversation)
    }
    if not taking:
        return "nothing_to_stamp"
    stamps = {
        key: at
        for key, at in load_conversation_take_outs(omh_home).items()
        if key in routes and routes[key]["written_at"] <= at
    }
    stamps.update(taking)
    try:
        _write_private_json(
            conversation_take_outs_path(omh_home),
            {
                "schema_version": CONVERSATION_TAKE_OUTS_SCHEMA_VERSION,
                "taken_out": stamps,
                "claim_boundary": (
                    "The conversation-routes entries a clear or a chain exhaustion released, "
                    "so an entry whose release failed is not put back at a later dispatch. "
                    "It is not evidence that any dispatch ran or which model a child used."
                ),
            },
        )
    except OSError as exc:
        return f"unrecorded: {type(exc).__name__}"
    return "recorded"


def conversation_writes_path(omh_home: str | Path | None = None) -> Path:
    return delegation_route_restore_path(omh_home).with_name(CONVERSATION_WRITES_FILE)


def load_conversation_writes(omh_home: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Each writer's newest routed `set`, keyed like the entries, in the entry's own shape.

    An unreadable file reads as "no newer write", which is the behaviour
    before this file existed, and a malformed stamp is dropped alone.
    """
    try:
        raw = json.loads(conversation_writes_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema_version") != CONVERSATION_WRITES_SCHEMA_VERSION:
        return {}
    writes = raw.get("writes")
    if not isinstance(writes, dict):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for key, stamp in writes.items():
        valid = _valid_conversation_route(key, stamp)
        if valid is not None:
            if stamp.get("released") is True:
                valid["released"] = True
            cleaned[key] = valid
    return cleaned


def _write_conversation_writes(omh_home: str | Path | None, writes: dict[str, dict[str, Any]]) -> None:
    _write_private_json(
        conversation_writes_path(omh_home),
        {
            "schema_version": CONVERSATION_WRITES_SCHEMA_VERSION,
            "writes": writes,
            "claim_boundary": (
                "The route each writer's newest omh_delegate_route set wrote, so an older "
                "conversation-routes entry whose replacement failed to write is not put back. "
                "It is not evidence that any dispatch ran or which model a child used."
            ),
        },
    )


def _release_conversation_writes(
    omh_home: str | Path | None, *, task_id: str, conversation: Collection[str]
) -> str:
    """Mark the stamps a release of `task_id` and `conversation` covers as released.

    The caller holds `route_write_lock` and runs this BEFORE the entries'
    own release, because the two live in different files: when the entries'
    release then fails, a stamp left unmarked would stand in for the entry a
    turn end or `clear` meant to take out, and put the writer's newest route
    back at a later turn. A released stamp still supersedes an older entry of
    its writer (`_not_superseded`); it never stands in for one or is
    inherited (`_in_force`, `_newest_inherited`). The writer's next `set`
    replaces it with a live stamp.

    Like `_store_conversation_route`, a failure is named rather than raised.
    """
    writes = load_conversation_writes(omh_home)
    marking = [
        key
        for key, stamp in writes.items()
        if not stamp.get("released") and _released_by(stamp, task_id, conversation)
    ]
    if not marking:
        return "nothing_to_release"
    for key in marking:
        writes[key] = {**writes[key], "released": True}
    try:
        _write_conversation_writes(omh_home, writes)
    except OSError as exc:
        return f"unreleased: {type(exc).__name__}"
    return "released"


def _stamp_conversation_write(
    omh_home: str | Path | None,
    *,
    session_id: str,
    task_id: str,
    config_path: str,
    route: dict[str, str],
    written_at: float,
) -> str:
    """Record the entry a `set` is about to write as its writer's newest; the caller holds `route_write_lock`.

    Written before the entry, to its own file, so that when the entry's write
    fails the stamp stands in for the writer's older entry under the same key
    (`_in_force`), and an older entry of the same writer under another key is
    recognised as superseded (`_not_superseded`). The profile-wide restore
    record said the same thing only until another writer's `set` replaced it.
    Stamps are bounded the way entries are: one older than the liveness
    bound is dropped, and at most `_MAX_CONVERSATION_ROUTES` are kept, the
    newest. A stamp is not dropped with its entry, because the entry it
    matters to may be another session's of the same conversation -- the one
    a compaction continued from (`_newest_inherited`) -- which nothing here
    can see without `state.db`. A release marks it released instead
    (`_release_conversation_writes`).

    Like `_store_conversation_route`, a failure is named rather than raised.
    """
    if not (session_id or task_id):
        return "unrecorded: no session or task"
    writes = {
        key: stamp
        for key, stamp in load_conversation_writes(omh_home).items()
        if written_at - stamp["written_at"] <= LIVE_TUI_SESSION_FRESH_SECONDS
    }
    writes[_conversation_route_key(session_id, task_id)] = {
        "config_path": config_path,
        "route": dict(route),
        "session_id": session_id,
        "task_id": task_id,
        "written_at": written_at,
    }
    newest = sorted(writes.items(), key=lambda item: item[1]["written_at"])[-_MAX_CONVERSATION_ROUTES:]
    try:
        _write_conversation_writes(omh_home, dict(newest))
    except OSError as exc:
        return f"unrecorded: {type(exc).__name__}"
    return "recorded"


def _routable_subset(applied: Mapping[str, Any]) -> dict[str, str]:
    """The three routable keys of a writer result, as a later read returns them.

    `omh_delegate_route` decorates the writer's `applied` mapping with an
    `alias` afterwards, so the subset is taken by key rather than by copying
    the mapping.
    """
    return {
        key: str(applied[key])
        for key in ROUTABLE_KEYS
        if isinstance(applied.get(key), str) and applied.get(key)
    }


def newest_written_provenance(
    omh_home: str | Path | None = None,
    *,
    session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """The newest provenance record that left a route in the file, or `{}`.

    Two callers need it: recognising a leaked OMH route so it is never
    recorded as a person's baseline, and recovering a chain position for
    `fallback` after the route was restored at the end of the turn that
    wrote it.

    They ask different questions, which is what `session_ids` is for. The
    leftover check is about the `delegation.*` keys, which are profile-wide,
    so it reads every session's records (`None`). A chain position belongs to
    one conversation, so `fallback` passes that conversation's session ids
    and gets only a record one of them wrote. A record that names no session
    is nobody's there, and an empty set matches nothing.
    """
    for record in reversed(load_delegation_route_provenance(omh_home)):
        if record.get("origin") not in _ROUTE_LEAVING_ORIGINS:
            continue
        if session_ids is not None and record.get("session_id") not in session_ids:
            continue
        return record
    return {}


def provenance_route_keys(record: Mapping[str, Any]) -> dict[str, str]:
    """The three routable keys a provenance record says OMH wrote."""
    pairs = (
        ("model", str(record.get("wire_model", "") or record.get("alias", ""))),
        ("reasoning_effort", str(record.get("reasoning_effort", ""))),
        ("provider", str(record.get("provider", ""))),
    )
    return {key: value for key, value in pairs if value}


# What provenance was able to say about the keys currently in the file.
LEFTOVER_MATCH = "omh_leftover"
LEFTOVER_MISMATCH = "person"
LEFTOVER_UNANSWERED = "person_provenance_unavailable"


def leftover_verdict(previous: Mapping[str, str], omh_home: str | Path | None) -> str:
    """Whether the keys in the file are a route OMH wrote and never recorded.

    An exact match on all three keys, never a partial one: a person who
    changed one of the three has made the value theirs, and a subset match
    would quietly discard it.

    The flip side, and the reason this is worth stating where a user reads
    it: a person who pins by hand exactly the triple OMH last wrote is
    indistinguishable from OMH's own leftover, and their pin is treated as
    one. Nothing on disk separates those two cases.

    `LEFTOVER_UNANSWERED` is the third answer and exists so the degradation
    is visible. Provenance can be missing, corrupt, or have lost its newest
    route record to the unlocked append it documents, and in each of those
    the honest report is "the check could not run", not "this is the
    person's".
    """
    if not previous:
        return LEFTOVER_MISMATCH
    record = newest_written_provenance(omh_home)
    if not record:
        return LEFTOVER_UNANSWERED
    return (
        LEFTOVER_MATCH
        if dict(previous) == provenance_route_keys(record)
        else LEFTOVER_MISMATCH
    )


def omh_wrote_current_keys(
    current: Mapping[str, str],
    omh_home: str | Path | None,
    *,
    record: Mapping[str, Any] | None = None,
) -> bool:
    """Can OMH prove it wrote the three keys the file holds right now?

    Chain exhaustion asks this before it clears, and may not act on a "no":
    after a turn-end restore the keys hold the PERSON's pinned model, and
    clearing it deleted the pin the moment a lane failed. Any OMH writer
    counts here, because the keys are profile-wide. `action=fallback` used
    to ask the same question for its chain position and no longer does: a
    position is one conversation's, so it asks whose write it is
    (`delegate_route_tool._fallback_position`).

    The record is the first authority, provenance the second, because the
    record is the only one written under a lock.
    """
    if not current:
        return False
    if record is None:
        record = load_route_restore_record(omh_home)
    if record and dict(current) == record["written"]:
        return True
    return leftover_verdict(current, omh_home) == LEFTOVER_MATCH


def write_route_with_baseline(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
    session_id: str = "",
    task_id: str = "",
    model: str = "",
    reasoning_effort: str = "",
    provider: str = "",
    expected_previous: Mapping[str, str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Write a route and keep the baseline bookkeeping in step, under one lock.

    Returns the writer's own result mapping with a `route_restore` field
    naming what the bookkeeping did (`baseline_captured`,
    `baseline_captured_over_omh_leftover`, `baseline_retained`,
    `baseline_recaptured`, `baseline_recaptured_over_omh_leftover`, or
    `unrecorded: <reason>`), plus `lock_enforced`. A lock this writer could
    not take returns `status: error` with `lock_unavailable`, so the caller
    reports a refusal rather than a route.

    A routed write is also recorded as the route of the calling session's
    conversation (`conversation_route`), so its own next dispatch can be put
    back on it whatever another session writes in between.
    """
    record_path = delegation_route_restore_path(omh_home)
    tick = float(now if now is not None else time.time())
    config_path = str(delegation_config_path(hermes_home))
    session_id = str(session_id or "")[:_MAX_ID_CHARS]
    task_id = str(task_id or "")[:_MAX_ID_CHARS]
    try:
        with _awareness_delivery_lock(record_path) as mechanism:
            result = _write_route_locked(
                hermes_home,
                omh_home,
                enforced=mechanism != LOCK_MECHANISM_NONE,
                config_path=config_path,
                tick=tick,
                session_id=session_id,
                task_id=task_id,
                model=model,
                reasoning_effort=reasoning_effort,
                provider=provider,
                expected_previous=expected_previous,
            )
            if result.get("status") == "routed":
                entry = {
                    "session_id": session_id,
                    "task_id": task_id,
                    "config_path": config_path,
                    "route": _routable_subset(result.get("applied") or {}),
                    "written_at": tick,
                }
                # The stamp first: it is what still names this write when
                # the entry's own write fails.
                result["conversation_write"] = _stamp_conversation_write(omh_home, **entry)
                result["conversation_route"] = _store_conversation_route(omh_home, **entry)
                if result["conversation_route"] != "recorded":
                    result["conversation_route_note"] = (
                        "The route is in the delegation.* keys but was not recorded as this "
                        f"conversation's ({result['conversation_route']}), so another session "
                        "can replace it before this conversation's delegate_task and it will "
                        "not be put back."
                    )
            return result
    except TimeoutError:
        return {
            "status": "error",
            "error": (
                "another session is writing the delegation route; no route was "
                "written, so the next delegate_task dispatch uses the route "
                "already in place"
            ),
            "error_type": "TimeoutError",
            "route_restore": "lock_unavailable",
        }
    except (OSError, ValueError) as exc:
        return {
            "status": "error",
            "error": f"route restore bookkeeping failed: {type(exc).__name__}",
            "error_type": type(exc).__name__,
            "route_restore": "unrecorded: bookkeeping unavailable",
        }


def _write_route_locked(
    hermes_home: str | Path | None,
    omh_home: str | Path | None,
    *,
    enforced: bool,
    config_path: str,
    tick: float,
    session_id: str,
    task_id: str,
    model: str,
    reasoning_effort: str,
    provider: str,
    expected_previous: Mapping[str, str] | None,
) -> dict[str, Any]:
    """The route write and its baseline bookkeeping; the caller holds the lock."""
    record_path = delegation_route_restore_path(omh_home)
    previous = read_delegation_route(hermes_home)
    record = load_route_restore_record(omh_home)
    if record and record["config_path"] != config_path:
        # The record describes another profile's config. Treat this
        # one as unrecorded rather than acting on a statement that
        # was never about it.
        record = {}
    result = write_delegation_route(
        hermes_home,
        model=model,
        reasoning_effort=reasoning_effort,
        provider=provider,
        expected_previous=expected_previous,
        guard_route_endpoint=True,
    )
    result["lock_enforced"] = enforced
    if result.get("status") != "routed":
        return result
    written = _routable_subset(result.get("applied") or {})
    if record and record["written"] == previous:
        # OMH still owned the value it is overwriting: the baseline
        # already describes what the person had.
        baseline = record["baseline"]
        captured_at = record["baseline_captured_at"]
        origin = record["baseline_origin"]
        note = "baseline_retained"
    else:
        # Either nothing was recorded, or someone changed the keys
        # since OMH last wrote them. Both mean this write is over a
        # value OMH cannot prove it recorded -- so a baseline is
        # captured, unless provenance says OMH wrote that value
        # itself and only failed to record it.
        stem = "baseline_recaptured" if record else "baseline_captured"
        verdict = leftover_verdict(previous, omh_home)
        if verdict == LEFTOVER_MATCH:
            baseline, origin = {}, BASELINE_ORIGIN_OMH_LEFTOVER
            note = f"{stem}_over_omh_leftover"
        else:
            baseline, origin = previous, BASELINE_ORIGIN_PERSON
            note = (
                f"{stem}_provenance_unavailable"
                if verdict == LEFTOVER_UNANSWERED
                else stem
            )
        captured_at = tick
    result["route_restore"] = _store_record(
        record_path,
        note=note,
        config_path=config_path,
        baseline=baseline,
        baseline_captured_at=captured_at,
        baseline_origin=origin,
        written=written,
        writer_session_id=session_id,
        writer_task_id=task_id,
        written_at=tick,
    )
    result["baseline_origin"] = origin
    if origin == BASELINE_ORIGIN_OMH_LEFTOVER:
        result["baseline_note"] = (
            "The delegation.* keys already held the exact route OMH last "
            "wrote, so they were treated as OMH's own leftover and the "
            "baseline is 'no keys'. If a person had pinned that same "
            "model, provider and effort by hand, nothing on disk "
            "distinguishes the two and their pin will not come back."
        )
    return result


def _store_record(path: Path, *, note: str, **fields: Any) -> str:
    """Persist the bookkeeping; a failure degrades the restore, not the route.

    The route is already in `config.yaml` by the time this runs. Failing the
    whole call here would report an error over a write that happened, so the
    failure is named in the returned note instead. The route then reads as
    unrecorded, and the next write recognises it through provenance rather
    than enshrining it as a baseline.

    That recovers the leak half and not the other one: whatever the three
    keys held before this write is gone with the record, so a model the
    person had pinned will not come back. Nothing can recover it once the
    only copy failed to reach disk, which is why the note is returned rather
    than swallowed -- an operator who sees `unrecorded: <reason>` has been
    told their pin is at risk while they can still act on it.
    """
    record = {"schema_version": DELEGATION_ROUTE_RESTORE_SCHEMA_VERSION, **fields}
    try:
        _write_restore_record(path, record)
    except OSError as exc:
        return f"unrecorded: {type(exc).__name__}"
    return note


def restore_delegation_baseline(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
    trigger: str = "",
    require_writer_session: str | None = None,
    require_writer_task: str | None = None,
    require_writer_not_live: bool = False,
    unrecorded_clear: str = "",
    expected_previous: Mapping[str, str] | None = None,
    release_writer: str | None = None,
    release_task: str | None = None,
    release_conversation: Collection[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Put the recorded baseline back, when OMH still owns the value.

    `require_writer_task` restricts the restore to the task that wrote the
    route, and `require_writer_session` to the session. The turn-end hook
    passes both, but a RECORDED task wins on its own: see
    `_writer_matches`.  `require_writer_not_live` is the session-start
    path's extra gate.

    `unrecorded_clear` is the escape hatch for a route with no record, and
    it has two strengths because its two callers differ. `"always"` is the
    explicit `clear` action: a person asked for the keys to come off and OMH
    cannot know what preceded them, so removing is both what clearing did
    before baselines existed and the only way to get an unrecorded route off
    a machine. `"if_omh_wrote"` is chain exhaustion, which is automatic and
    so may only remove a value OMH can prove it wrote; without that proof it
    reports `unrecorded_value_not_ours` and changes nothing, because the
    alternative was deleting the person's pinned model at the exact moment a
    lane had failed. Both run inside this lock, with the caller's
    `expected_previous`, because doing either outside left a window in which
    a concurrent route recorded a person's pinned model as a baseline that
    the next restore then discarded as a foreign edit.

    Every outcome is a `status` a caller can report: `restored`, `cleared` (a
    baseline with no keys to put back), `no_baseline_recorded`,
    `unrecorded_value_not_ours`, `foreign_edit`, `foreign_config`,
    `not_last_writer`, `writer_live`, `lock_unavailable`, or `error`.

    `release_writer` is the turn end's: the session whose own conversation
    routes end with this task. `clear` and chain exhaustion pass
    `release_conversation` and `release_task` instead: the caller's whole
    conversation, which says it wants no route any more. Either way the
    caller's routes are dropped inside the same lock as the restore, and only
    after it, so the two cannot come apart: a release that timed out after a
    restore succeeded left the route recorded, and the next dispatch of the
    same task put it back (#2251 review); a release BEFORE a restore that
    was then refused dropped the record of a route still in the keys. A
    restore that ends in `error` releases nothing. Other sessions' routes are
    never released by these callers.
    An automatic restore (turn end, session start) that takes a record out
    also drops that writer's conversation routes, so a route whose keys are
    gone cannot come back at a later dispatch.
    """
    record_path = delegation_route_restore_path(omh_home)
    # A release has work to do even when no record does: an entry to drop,
    # or a live stamp to mark released, which outlives the routes file when
    # the entry it was written for failed to land (#2273 review, R1/R3). A
    # stamp past the liveness bound is never inherited (`_newest_inherited`)
    # and so is no work: counting it would keep every session's turn end off
    # the fast path until some later `set` pruned it.
    tick = float(now if now is not None else time.time())
    must_release = (release_writer is not None or release_conversation is not None) and (
        conversation_routes_path(omh_home).exists()
        or any(
            not stamp.get("released") and tick - stamp["written_at"] <= LIVE_TUI_SESSION_FRESH_SECONDS
            for stamp in load_conversation_writes(omh_home).values()
        )
    )
    if not unrecorded_clear and not record_path.exists() and not must_release:
        # The common case by far: every turn of every session reaches here,
        # and almost none of them has a route to take back. A few `stat`s
        # and at most one small JSON read, no lock, no sqlite. The race it
        # accepts is a record created between this check and a lock that is
        # never taken, which costs one missed
        # restore that the next turn end or the next session start makes
        # good -- never a wrong write.
        return {"status": "no_baseline_recorded", "trigger": trigger, "fast_path": True}
    config_path = str(delegation_config_path(hermes_home))
    if not unrecorded_clear:
        # A second cheap reject before the lock. In a shared OMH home the
        # non-owning profile otherwise paid the full locked path on every
        # turn end and contended with the owning profile's routing on a
        # 0.1s budget. The record is replaced atomically, so an unlocked
        # read sees a whole old or a whole new file, never a torn one -- and
        # the authoritative check still runs under the lock below, so the
        # worst this can do is skip a decision that was going to be
        # `foreign_config` anyway.
        peek = load_route_restore_record(omh_home)
        if peek and peek["config_path"] != config_path and not must_release:
            return {
                "status": "foreign_config",
                "trigger": trigger,
                "recorded_config": peek["config_path"],
                "this_config": config_path,
                "fast_path": True,
            }
    release: Collection[str] | None = None
    if must_release:
        # The caller's conversation set, read before the lock so the lock is
        # held only for the file work (#2177's identity: the session plus
        # its compression continuations).
        if release_conversation is not None:
            release = release_conversation
        elif release_writer:
            release = {release_writer} | conversation_session_ids(
                hermes_home or runtime_paths.default_hermes_home(), release_writer
            )
        else:
            release = set()
    task = release_task if release_task is not None else (require_writer_task or "")
    try:
        with _awareness_delivery_lock(record_path) as mechanism:
            result = _restore_locked(
                hermes_home,
                omh_home,
                record_path=record_path,
                config_path=config_path,
                enforced=mechanism != LOCK_MECHANISM_NONE,
                trigger=trigger,
                require_writer_session=require_writer_session,
                require_writer_task=require_writer_task,
                require_writer_not_live=require_writer_not_live,
                unrecorded_clear=unrecorded_clear,
                expected_previous=expected_previous,
                now=now,
            )
            if release is not None and result.get("status") != "error":
                # `clear` and chain exhaustion stamp what they release first,
                # whatever the restore decided: a `foreign_edit` releases too.
                take_out = (
                    _stamp_take_out(omh_home, task_id=task, conversation=release)
                    if release_conversation is not None
                    else ""
                )
                result["conversation_route"] = _release_reported(
                    omh_home, task_id=task, conversation=release
                )
                if take_out:
                    result["conversation_route"]["take_out"] = take_out
            return result
    except TimeoutError:
        return {
            "status": "lock_unavailable",
            "trigger": trigger,
            "error_type": "TimeoutError",
        }
    except (OSError, ValueError) as exc:
        return {
            "status": "error",
            "error": f"route restore failed: {type(exc).__name__}",
            "error_type": type(exc).__name__,
            "trigger": trigger,
        }


def _restore_locked(
    hermes_home: str | Path | None,
    omh_home: str | Path | None,
    *,
    record_path: Path,
    config_path: str,
    enforced: bool,
    trigger: str,
    require_writer_session: str | None,
    require_writer_task: str | None,
    require_writer_not_live: bool,
    unrecorded_clear: str,
    expected_previous: Mapping[str, str] | None,
    now: float | None,
) -> dict[str, Any]:
    """`restore_delegation_baseline`'s decision and write; the caller holds the lock."""
    record = load_route_restore_record(omh_home)
    if not record:
        unprotected = (
            unrecorded_clear == "if_omh_wrote"
            and (keys := read_delegation_route(hermes_home))
            and not omh_wrote_current_keys(keys, omh_home, record={})
        )
        if unprotected:
            # Automatic removal of a value OMH cannot prove it wrote
            # is how the person's pinned model got deleted the moment
            # a lane failed. Report instead.
            #
            # EMPTY keys are nothing to protect, not a value that is
            # not ours, and the difference is the ordinary flow: a
            # route, its turn end, then fallback until the chain runs
            # out leaves the three keys absent. Refusing there gave
            # the model a status no description mentions, skipped the
            # `exhausted_to_inherit` rename, and skipped the
            # superseding provenance record the neighbouring `clear`
            # branch needs -- all over a file that was already in the
            # state being asked for.
            return {
                "status": "unrecorded_value_not_ours",
                "trigger": trigger,
                "lock_enforced": enforced,
            }
        if unrecorded_clear:
            removed = write_delegation_route(
                hermes_home, clear=True, expected_previous=expected_previous
            )
            removed["route_restore"] = "no_baseline_recorded"
            removed["trigger"] = trigger
            removed["lock_enforced"] = enforced
            return removed
        return {
            "status": "no_baseline_recorded",
            "trigger": trigger,
            "lock_enforced": enforced,
        }
    if record["config_path"] != config_path:
        # Two profiles can share one OMH home by design. A record
        # about the other profile's file is not a foreign edit and
        # must NOT be dropped: dropping it stranded the route it
        # described, with no record left to take that route back.
        return {
            "status": "foreign_config",
            "trigger": trigger,
            "recorded_config": record["config_path"],
            "this_config": config_path,
            "lock_enforced": enforced,
        }
    if not _writer_matches(record, require_writer_session, require_writer_task):
        return {
            "status": "not_last_writer",
            "trigger": trigger,
            "lock_enforced": enforced,
        }
    liveness, writer_source, lineage_report = "not_checked", "", {}
    if require_writer_not_live:
        liveness, writer_source, lineage_report = _writer_liveness(
            record["writer_session_id"],
            hermes_home=hermes_home,
            written_at=record["written_at"],
            now=now,
        )
        if liveness not in LIVENESS_CLEARS_RESTORE:
            return {
                "status": "writer_live",
                "trigger": trigger,
                "liveness": liveness,
                # Report only, never a gate: which surface held the
                # route is what an operator wants beside a withheld
                # restore. It comes out of the row the verdict was
                # already read from, not a second query.
                "writer_source": writer_source,
                "lock_enforced": enforced,
                **lineage_report,
            }
    current = read_delegation_route(hermes_home)
    if current != record["written"]:
        # Someone else owns the value now. Drop the record: keeping it
        # would let a later restore act on a baseline that no longer
        # describes anything in the file.
        _discard_restore_record(record_path)
        writer_routes = _release_writer(omh_home, record, unrecorded_clear)
        return {
            "status": "foreign_edit",
            "writer_routes": writer_routes,
            "trigger": trigger,
            "liveness": liveness,
            "lock_enforced": enforced,
        }
    baseline = record["baseline"]
    result = _put_baseline_back(hermes_home, baseline, current)
    if result.get("status") not in ("routed", "cleared"):
        return {
            "status": "error",
            "error": str(result.get("error", "route restore write failed")),
            "error_type": "RouteWriteRefused",
            "trigger": trigger,
            "lock_enforced": enforced,
        }
    _discard_restore_record(record_path)
    writer_routes = _release_writer(omh_home, record, unrecorded_clear)
    return {
        "writer_routes": writer_routes,
        # Two outcomes a reader acts on differently, so they keep
        # separate names: `restored` put values back, `cleared` is the
        # baseline that had no keys to put back, which is the same
        # end state the tool reported before baselines existed.
        "status": "restored" if baseline else "cleared",
        "trigger": trigger,
        "restored": baseline,
        "baseline_origin": record["baseline_origin"],
        "replaced": current,
        "liveness": liveness,
        "lock_enforced": enforced,
        **lineage_report,
    }


def _release_reported(
    omh_home: str | Path | None, *, task_id: str, conversation: Collection[str]
) -> dict[str, Any]:
    """`_release_locked`, with a write failure named rather than raised.

    The restore has already written the keys by now, so failing the whole
    call would report an error over a write that happened.
    """
    _release_writes_logged(omh_home, task_id=task_id, conversation=conversation)
    try:
        return _release_locked(omh_home, task_id=task_id, conversation=conversation)
    except OSError as exc:
        _LOG.warning(
            "OMH could not release a conversation's delegation route after restoring the keys "
            "(%s); only the take-out stamp written before it keeps a later dispatch of the same "
            "task from putting it back",
            type(exc).__name__,
        )
        return {"status": "error", "error_type": type(exc).__name__}


def _release_writes_logged(
    omh_home: str | Path | None, *, task_id: str, conversation: Collection[str]
) -> None:
    """`_release_conversation_writes` before an entry release, its failure logged.

    The release result keeps its shape; a stamp left unmarked can stand in
    for an entry whose own release then also fails, so an operator is told.
    """
    stamps = _release_conversation_writes(omh_home, task_id=task_id, conversation=conversation)
    if stamps.startswith("unreleased"):
        _LOG.warning(
            "OMH could not mark a conversation's delegation route stamps released (%s); if the "
            "release of its entries fails too, the newest route can come back at a later dispatch",
            stamps.removeprefix("unreleased: "),
        )


def _release_writer(omh_home: str | Path | None, record: Mapping[str, Any], unrecorded_clear: str) -> str:
    """After an AUTOMATIC restore took a record out, drop its writer's routes too.

    `clear` and chain exhaustion (`unrecorded_clear` set) keep them: another
    session asking for the keys to come off must not take this session's
    own route away, which comes back at its next dispatch.
    """
    if unrecorded_clear:
        return "kept"
    session_id = record["writer_session_id"]
    conversation = {session_id} if session_id else set()
    _release_writes_logged(omh_home, task_id=record["writer_task_id"], conversation=conversation)
    try:
        _release_locked(omh_home, task_id=record["writer_task_id"], conversation=conversation)
    except OSError as exc:
        # The keys are already back; failing the restore over its bookkeeping
        # would report an error over a write that happened. The age bound in
        # `_dispatch_plan` still retires the entry, but not silently: the
        # hooks turn `unreleased` into a degradation, and it is logged here.
        _LOG.warning(
            "OMH restored the delegation keys but could not release the writer's conversation "
            "route (%s); the six-hour bound will retire it",
            type(exc).__name__,
        )
        return f"unreleased: {type(exc).__name__}"
    return "released"


def _put_baseline_back(
    hermes_home: str | Path | None, baseline: Mapping[str, str], current: Mapping[str, str]
) -> dict[str, Any]:
    return write_delegation_route(
        hermes_home,
        model=baseline.get("model", ""),
        reasoning_effort=baseline.get("reasoning_effort", ""),
        provider=baseline.get("provider", ""),
        expected_previous=current,
    )


# What `prepare_dispatch_route` returns when the dispatch must not go ahead.
# A routed conversation whose route could not be put back is told whose route
# holds the keys; a conversation with no route of its own is told that
# another session's route is in the keys and could not be taken out.
DISPATCH_ROUTE_REFUSALS = frozenset(
    {"route_overwritten_by_other_session", "route_not_applied", "other_session_route_live"}
)


def _owned_by_caller(
    item_session: str, item_task: str, task_id: str, conversation: Callable[[], set[str]]
) -> bool:
    """Is a route record or entry the dispatching conversation's own?

    The rule `_writer_matches` applies at the turn end, so a route lives as
    long at the dispatch as it does there: a recorded task decides alone, and
    it is what survives a compression split. A TUI turn is one task, so a
    route set in an earlier turn is not this dispatch's. Only an item with no
    task falls back to the session, asked of the whole conversation (#2177).
    """
    if item_task:
        return item_task == task_id
    return bool(item_session) and item_session in conversation()


def _delegate_ancestors(hermes_home: str | Path, session_id: str) -> set[str] | None:
    """Every session of the conversations this session was delegated from, or None when unknown.

    The union of `_delegate_ancestry`.
    """
    ancestry = _delegate_ancestry(hermes_home, session_id)
    return None if ancestry is None else set().union(*ancestry)


def _delegate_ancestry(hermes_home: str | Path, session_id: str) -> list[set[str]] | None:
    """The conversations this session was delegated from, nearest first, or None when unknown.

    Hermes stamps a delegate child's `sessions.model_config` with
    `_delegate_from` naming its parent (`tools/delegate_tool.py`, beside
    `_build_child_agent`), and a child's compaction continuation carries the
    same marker. The walk follows that marker upward, adding each parent's
    whole conversation (#2177), so an orchestrator child's worker dispatch
    can tell its parent's route from a stranger's. `[]` is an answer: a
    top-level session. None means the caller's own row could not be read,
    and the caller then leaves the keys alone, which is what every dispatch
    did before conversation routes existed.
    """
    state_db = Path(hermes_home).expanduser() / "state.db"
    if not session_id or not state_db.is_file():
        return None
    try:
        connection = connect_readonly(state_db, timeout=0.25)
    except sqlite3.Error:
        return None
    parents: list[str] = []
    try:
        current = session_id
        for _ in range(_LINEAGE_WALK_LIMIT):
            row = connection.execute(
                "SELECT model_config FROM sessions WHERE id = ?", (current,)
            ).fetchone()
            config: object = None
            if row is not None:
                try:
                    config = json.loads(row[0]) if isinstance(row[0], str) else {}
                except ValueError:
                    config = None
            if not isinstance(config, dict):
                if current == session_id:
                    return None
                break
            parent = config.get("_delegate_from")
            if not isinstance(parent, str) or not parent or parent == current or parent in parents:
                break
            parents.append(parent)
            current = parent
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return [{parent} | conversation_session_ids(hermes_home, parent) for parent in parents]


def _dispatch_plan(
    hermes_home: str | Path | None,
    omh_home: str | Path | None,
    *,
    config_path: str,
    session_id: str,
    task_id: str,
    now: float,
    conversation: Callable[[], set[str]],
    ancestors: Callable[[], list[set[str]] | None],
) -> dict[str, Any]:
    """What the keys must hold for this dispatch, read from the three stores.

    `action` is `none`, `reapply` (a route this dispatch should run on is
    not in the keys) or `restore_baseline` (the caller has no route and the
    keys hold another conversation's).

    The route a dispatch should run on is, in order: the caller's own; for
    a delegate child, the route of the conversation it was delegated from,
    which is what a worker under a routed orchestrator ran on before this
    record existed; otherwise the baseline. An entry older than the liveness
    bound belongs to a session that is gone and is ignored.

    The keys are left alone -- never stripped -- for a route whose writer
    recorded no conversation entry (an older OMH still running, or an entry
    that failed to write), since its owner could not put it back, and when
    the caller's lineage cannot be read, since it might be that route's
    child.

    `current` is read last, after the record and the entries it is compared
    with, so a decision is never made on keys older than the record.
    """
    record = load_route_restore_record(omh_home)
    if record and record["config_path"] != config_path:
        record = {}
    entries = [
        entry
        for entry in load_conversation_routes(omh_home).values()
        if entry["config_path"] == config_path
        and now - entry["written_at"] <= LIVE_TUI_SESSION_FRESH_SECONDS
    ]
    entries = _in_force(entries, record, omh_home)
    current = read_delegation_route(hermes_home)
    record_live = bool(record) and current == record["written"]
    plan: dict[str, Any] = {
        "record": record,
        "current": current,
        "live_writer": record["writer_session_id"] if record_live else "",
    }
    own = [
        entry
        for entry in entries
        if _owned_by_caller(entry["session_id"], entry["task_id"], task_id, conversation)
    ]
    if own:
        route = max(own, key=lambda entry: entry["written_at"])
        plan.update(entry=route, owner=(session_id, task_id), owners=conversation() | {route["session_id"]})
        if current == route["route"]:
            return {**plan, "action": "none", "status": "route_in_place"}
        return {**plan, "action": "reapply", "status": "route_reapplied"}
    record_is_callers = bool(record) and _owned_by_caller(
        record["writer_session_id"], record["writer_task_id"], task_id, conversation
    )
    if not entries and (not record_live or record_is_callers):
        return {**plan, "action": "none", "status": "no_conversation_route"}
    ancestry = ancestors()
    lineage: set[str] | None = None if ancestry is None else set().union(*ancestry)
    if lineage:
        # A corrupt `_delegate_from` cycle must not make the caller its own
        # ancestor: it would then inherit its own stale route from an
        # earlier task, the one thing the task-first ownership rule refuses.
        own = conversation()
        lineage = lineage - own
        ancestry = [group - own for group in ancestry or []]
    if lineage:
        route = _newest_inherited(entries, ancestry or [], record, omh_home, config_path=config_path, now=now)
        if route:
            # Written back on behalf of the parent, so the record names the
            # parent's task and the parent's own turn end takes it out.
            plan.update(
                entry=route,
                owner=(route["session_id"], route["task_id"]),
                owners=lineage | {route["session_id"]},
            )
            if current == route["route"]:
                return {**plan, "action": "none", "status": "parent_route_in_place"}
            return {**plan, "action": "reapply", "status": "parent_route_reapplied"}
        if record_live and record["writer_session_id"] in lineage:
            return {**plan, "action": "none", "status": "parent_route_in_place"}
    if not record_live or record_is_callers:
        return {**plan, "action": "none", "status": "no_conversation_route"}
    writer_has_entry = any(
        (entry["task_id"] and entry["task_id"] == record["writer_task_id"])
        or (entry["session_id"] and entry["session_id"] == record["writer_session_id"])
        for entry in entries
    )
    if not writer_has_entry:
        return {**plan, "action": "none", "status": "unrecorded_writer"}
    if lineage is None:
        return {**plan, "action": "none", "status": "lineage_unresolved"}
    return {**plan, "action": "restore_baseline", "status": "baseline_restored_for_dispatch"}


def _newest_inherited(
    entries: list[dict[str, Any]],
    ancestry: list[set[str]],
    record: Mapping[str, Any],
    omh_home: str | Path | None,
    *,
    config_path: str,
    now: float,
) -> dict[str, Any] | None:
    """The newest route the conversations a child descends from set, or None.

    `ancestry` holds each ancestor's #2177 conversation set, so a session a
    compaction continued in counts as the one it continued from. Each
    conversation is read on its own. Its live stamps are candidates beside
    its entries: after a compaction the newer `set` may have lost its entry
    under the continuation's key, where no entry of its own stands for it.
    Its newest candidate is dropped when it is older than that same
    conversation's newest stamp (live or released) or take-out: that is the
    conversation's own later write, or a release of it, and an older route
    coming back over it is what this filter is for. Another ancestor's later
    write says nothing about this one's route. Of what each conversation
    leaves, the newest is inherited, which is what a dispatch chose before
    stamps existed.
    """
    writes = load_conversation_writes(omh_home)
    take_outs = load_conversation_take_outs(omh_home)
    left = []
    for group in ancestry:
        stamps = [
            stamp
            for stamp in writes.values()
            if stamp["session_id"] in group
            and stamp["config_path"] == config_path
            and now - stamp["written_at"] <= LIVE_TUI_SESSION_FRESH_SECONDS
        ]
        marks = [stamp["written_at"] for stamp in stamps] + [at for key, at in take_outs.items() if key in group]
        live = [
            stamp
            for stamp in stamps
            if not stamp.get("released")
            and take_outs.get(_conversation_route_key(stamp["session_id"], stamp["task_id"]), -1.0)
            < stamp["written_at"]
        ]
        candidates = [entry for entry in entries if entry["session_id"] in group]
        candidates += _not_superseded(live, record, {})
        if not candidates:
            continue
        newest = max(candidates, key=lambda entry: entry["written_at"])
        if not marks or newest["written_at"] >= max(marks):
            left.append(newest)
    return max(left, key=lambda entry: entry["written_at"]) if left else None


def _not_taken_out(entries: list[dict[str, Any]], omh_home: str | Path | None) -> list[dict[str, Any]]:
    """`entries` less those a `clear` or chain exhaustion stamped before its release.

    That release deletes them; this covers the release whose write failed.
    See `_stamp_take_out`.
    """
    if not entries:
        return entries
    stamps = load_conversation_take_outs(omh_home)
    if not stamps:
        return entries

    def taken_out(entry: Mapping[str, Any]) -> bool:
        stamp = stamps.get(_conversation_route_key(entry["session_id"], entry["task_id"]))
        return stamp is not None and entry["written_at"] <= stamp

    return [entry for entry in entries if not taken_out(entry)]


def _in_force(
    entries: list[dict[str, Any]], record: Mapping[str, Any], omh_home: str | Path | None
) -> list[dict[str, Any]]:
    """`entries` as a dispatch reads them: taken-out ones gone, each at its writer's newest write.

    The take-out filter runs first, so an entry a `clear` or chain exhaustion
    released is gone before its writer's stamp is consulted, and a newer stamp
    of that writer cannot bring a route back past the take-out. An entry that
    survives and has an older `written_at` than its own key's stamp lost its
    replacement to a failed write (`_stamp_conversation_write`), so the stamp
    -- the entry that write meant to leave, in the same shape -- stands in for
    it. A stamp with no surviving entry of its key stands for nothing: the
    entry was released, by a turn end or a `clear`, and the route with it.
    """
    entries = _not_taken_out(entries, omh_home)
    writes = load_conversation_writes(omh_home) if entries else {}
    return _not_superseded([_newest_write(entry, writes) for entry in entries], record, writes)


def _newest_write(entry: dict[str, Any], writes: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """The newer of `entry` and the stamp under the same key, for the same config."""
    stamp = writes.get(_conversation_route_key(entry["session_id"], entry["task_id"]))
    if (
        stamp
        and not stamp.get("released")
        and stamp["config_path"] == entry["config_path"]
        and stamp["written_at"] > entry["written_at"]
    ):
        return stamp
    return entry


def _not_superseded(
    entries: list[dict[str, Any]], record: Mapping[str, Any], stamps: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """`entries` less one its own writer has since replaced in the keys.

    A route write stores the restore record, then the writer's stamp
    (`_stamp_conversation_write`), then the conversation entry. An entry
    whose own key has a newer stamp is replaced by that stamp before this
    runs (`_in_force`); what is left to catch is an older entry of the same
    writer under another key, such as the session a compaction continued
    from. So an entry is ignored when a newer write by the same writer (by
    task, or by session for an entry with no task) holds another route. The
    writes compared with are the per-writer stamps, which another writer's
    `set` does not replace, and the restore record, which still covers a
    stamp that failed to write. A write that names the entry's own route --
    a reapply's record, or a `set` of the same route again -- changes
    nothing.
    """
    if not entries:
        return entries
    writes = list(stamps.values())
    if record:
        writes.append(
            {
                "config_path": record["config_path"],
                "route": record["written"],
                "session_id": record["writer_session_id"],
                "task_id": record["writer_task_id"],
                "written_at": record["written_at"],
            }
        )
    if not writes:
        return entries

    def superseded(entry: Mapping[str, Any]) -> bool:
        return any(
            _same_writer(entry, write)
            and write["config_path"] == entry["config_path"]
            and write["written_at"] > entry["written_at"]
            and write["route"] != entry["route"]
            for write in writes
        )

    return [entry for entry in entries if not superseded(entry)]


def _same_writer(entry: Mapping[str, Any], write: Mapping[str, Any]) -> bool:
    """The same task, or the same session when neither has a task."""
    if entry["task_id"] or write["task_id"]:
        return entry["task_id"] == write["task_id"]
    return entry["session_id"] == write["session_id"]


# Plan statuses an unlocked read may return on: each says the keys already
# hold the route this dispatch should run on, which a write landing after the
# read cannot make wrong any sooner than the documented window does. Every
# other decision is re-read under the lock, because it compares the keys with
# a record that an unlocked read may see one write behind them.
_UNLOCKED_ANSWERS = frozenset({"route_in_place", "parent_route_in_place"})


def prepare_dispatch_route(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
    session_id: str = "",
    task_id: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Put the route this dispatch should run on in the keys, or refuse.

    `pre_tool_call` runs this for every `delegate_task` spawn. A dispatch
    whose keys already hold its own route -- every single-session dispatch
    -- takes no lock and writes nothing; anything else is decided again and
    acted on under the lock. A status in `DISPATCH_ROUTE_REFUSALS` means the
    keys could not be made to hold this dispatch's route, and the caller
    must not dispatch.
    """
    record_path = delegation_route_restore_path(omh_home)
    if not record_path.exists() and not conversation_routes_path(omh_home).exists():
        return {"status": "no_conversation_route", "fast_path": True}
    config_path = str(delegation_config_path(hermes_home))
    task_id = str(task_id or "")[:_MAX_ID_CHARS]
    session_id = str(session_id or "")[:_MAX_ID_CHARS]
    home = hermes_home or runtime_paths.default_hermes_home()
    tick = float(now if now is not None else time.time())
    cache: dict[str, Any] = {}

    def conversation() -> set[str]:
        if "conversation" not in cache:
            cache["conversation"] = (
                {session_id} | conversation_session_ids(home, session_id) if session_id else set()
            )
        return cache["conversation"]

    def ancestors() -> list[set[str]] | None:
        if "ancestors" not in cache:
            cache["ancestors"] = _delegate_ancestry(home, session_id)
        return cache["ancestors"]

    def plan() -> dict[str, Any]:
        return _dispatch_plan(
            hermes_home,
            omh_home,
            config_path=config_path,
            session_id=session_id,
            task_id=task_id,
            now=tick,
            conversation=conversation,
            ancestors=ancestors,
        )

    peek = plan()
    if peek["status"] in _UNLOCKED_ANSWERS:
        return {"status": peek["status"], "fast_path": True}
    try:
        with _awareness_delivery_lock(record_path, timeout_seconds=_DISPATCH_LOCK_SECONDS) as mechanism:
            decided = plan()
            if decided["action"] == "none":
                if decided["status"] == "lineage_unresolved":
                    return _lineage_fallback(decided, session_id)
                return {"status": decided["status"]}
            if decided["action"] == "reapply":
                return _reapply_route(
                    hermes_home,
                    omh_home,
                    decided,
                    enforced=mechanism != LOCK_MECHANISM_NONE,
                    config_path=config_path,
                    tick=tick,
                    session_id=session_id,
                )
            written = _put_baseline_back(hermes_home, decided["record"]["baseline"], decided["current"])
            if written.get("status") not in ("routed", "cleared"):
                return _dispatch_refusal(
                    decided, session_id, f"write refused: {written.get('error', 'unknown')}"
                )
            _discard_restore_record(record_path)
            return {"status": decided["status"], "displaced_writer": decided["live_writer"]}
    except TimeoutError:
        if peek["action"] != "none":
            return _dispatch_refusal(peek, session_id, "lock_unavailable")
        # The unlocked read found nothing to change, so the keys go to the
        # child as they are, which is what every dispatch did before
        # conversation routes existed. Refusing here blocked a dispatch that
        # would have gone ahead, in another session's name (#2258 review).
        if peek["status"] == "lineage_unresolved":
            return _lineage_fallback(peek, session_id)
        return {"status": peek["status"], "lock_unavailable": True}
    except (OSError, ValueError) as exc:
        return _dispatch_refusal(peek, session_id, type(exc).__name__)


def _reapply_route(
    hermes_home: str | Path | None,
    omh_home: str | Path | None,
    decided: Mapping[str, Any],
    *,
    enforced: bool,
    config_path: str,
    tick: float,
    session_id: str,
) -> dict[str, Any]:
    """Write a dispatch's route back over whatever replaced it.

    The baseline bookkeeping is the route write's own, so a route this puts
    back over another conversation's keeps the person's baseline, and the
    record names the route's owner -- the caller, or for a delegate child
    the parent it inherits from -- as the writer, which is what lets that
    owner's turn end take the route back out. Its provenance record is
    appended again so the newest record names the route really in the keys:
    the leftover check and the HUD label both read the newest one.
    """
    route = decided["entry"]["route"]
    owner_session, owner_task = decided["owner"]
    result = _write_route_locked(
        hermes_home,
        omh_home,
        enforced=enforced,
        config_path=config_path,
        tick=tick,
        session_id=owner_session,
        task_id=owner_task,
        model=route.get("model", ""),
        reasoning_effort=route.get("reasoning_effort", ""),
        provider=route.get("provider", ""),
        expected_previous=decided["current"],
    )
    if result.get("status") != "routed":
        return _dispatch_refusal(
            decided, session_id, f"write refused: {result.get('error', 'unknown')}"
        )
    provenance = newest_written_provenance(omh_home, session_ids=decided["owners"])
    route_provenance = "not_found"
    if provenance and provenance_route_keys(provenance) == route:
        route_provenance = append_delegation_route_provenance(
            {**provenance, "written_at": tick, "session_id": owner_session or provenance.get("session_id", "")},
            omh_home,
        )
    return {
        "status": decided["status"],
        "route": dict(route),
        "displaced_writer": decided["live_writer"],
        "route_provenance": route_provenance,
        "lock_enforced": enforced,
    }


def _lineage_fallback(plan: Mapping[str, Any], session_id: str) -> dict[str, Any]:
    """The dispatch goes ahead on another conversation's route, and says so.

    Its own `state.db` row could not be read, so it might be that route's
    worker, and stripping the route would be the regression #2254's review
    found. Blocking would refuse every dispatch of a session whose row is
    missing. So the call proceeds as it did before #2251 and the fallback
    is named: in the hook's result (which Hermes passes over, since it has
    no `action`) and in the log, which is where an operator looks.
    """
    other = str(plan.get("live_writer", "") or "")
    _LOG.warning(
        "OMH could not read the state.db row of session %r, so its delegate_task runs on the "
        "delegation route session %r set rather than on the profile default",
        session_id,
        other,
    )
    return {
        "status": "lineage_unresolved",
        "session_id": session_id,
        "live_route_writer": other,
        "dispatched_on_other_route": True,
        "note": (
            "This session's state.db row could not be read, so OMH could not tell whether it was "
            "delegated from the session whose route is in the delegation.* keys, and left that "
            "route in place."
        ),
    }


# What `dispatch_route_directive` attaches, without blocking, for a dispatch
# that goes ahead on a fallback.
DISPATCH_ROUTE_NOTES = frozenset({"lineage_unresolved"})


def conversation_route_for(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
    session_id: str = "",
    task_id: str = "",
    now: float | None = None,
) -> dict[str, Any] | None:
    """The caller's own conversation route, as its next dispatch would find it.

    `action=status` reports it beside the profile-wide keys, which may hold
    another session's route. The same ownership rule and age bound as the
    dispatch; `in_keys` says whether the keys hold it right now. None when
    this conversation has no route of its own in this task.
    """
    if not conversation_routes_path(omh_home).exists():
        return None
    config_path = str(delegation_config_path(hermes_home))
    task_id = str(task_id or "")[:_MAX_ID_CHARS]
    session_id = str(session_id or "")[:_MAX_ID_CHARS]
    tick = float(now if now is not None else time.time())
    home = hermes_home or runtime_paths.default_hermes_home()
    cache: dict[str, set[str]] = {}

    def conversation() -> set[str]:
        if "conversation" not in cache:
            cache["conversation"] = (
                {session_id} | conversation_session_ids(home, session_id) if session_id else set()
            )
        return cache["conversation"]

    record = load_route_restore_record(omh_home)
    if record and record["config_path"] != config_path:
        record = {}
    entries = _in_force(list(load_conversation_routes(omh_home).values()), record, omh_home)
    own = [
        entry
        for entry in entries
        if entry["config_path"] == config_path
        and tick - entry["written_at"] <= LIVE_TUI_SESSION_FRESH_SECONDS
        and _owned_by_caller(entry["session_id"], entry["task_id"], task_id, conversation)
    ]
    if not own:
        return None
    entry = max(own, key=lambda item: item["written_at"])
    return {
        "route": dict(entry["route"]),
        "session_id": entry["session_id"],
        "task_id": entry["task_id"],
        "written_at": entry["written_at"],
        "in_keys": read_delegation_route(hermes_home) == entry["route"],
    }


def _dispatch_refusal(plan: Mapping[str, Any], session_id: str, reason: str) -> dict[str, Any]:
    """The typed result a dispatch that must not go ahead is refused with."""
    other = str(plan.get("live_writer", "") or "")
    if plan.get("action") == "reapply":
        status = "route_overwritten_by_other_session" if other and other != session_id else "route_not_applied"
        model = str(plan["entry"]["route"].get("model", ""))
        error = (
            "Not dispatched: this conversation (or the one it was delegated from) routed "
            f"delegate_task to {model!r}, but OMH could not put that route back in the "
            f"delegation.* keys ({reason})"
            + (f", which hold the route session {other!r} set" if status != "route_not_applied" else "")
            + ". Dispatching now would run the child on a route this conversation did not choose. "
            "Call delegate_task again; if this repeats, call omh_delegate_route set first."
        )
    else:
        status = "other_session_route_live"
        setter = f"session {other!r}" if other else "another conversation"
        error = (
            f"Not dispatched: the delegation.* keys hold the route {setter} set for its "
            f"own delegate_task, and OMH could not put this profile's default back ({reason}). "
            "Dispatching now would run the child on that session's route. Call delegate_task "
            "again, or route this lane yourself with omh_delegate_route set first."
        )
    return {
        "status": status,
        "error": error,
        "session_id": session_id,
        "live_route_writer": other,
        "reason": reason,
        "dispatched": False,
    }


def dispatch_route_directive(
    *,
    tool_name: object,
    tool_input: object,
    session_id: str,
    task_id: str,
    omh_home: str | Path | None,
    hermes_home: str | Path | None,
) -> dict[str, Any] | None:
    """`pre_tool_call`'s answer for a `delegate_task` spawn.

    None, a block, or -- for a dispatch that goes ahead on a fallback -- a
    note with no `action` (`omh_route_fallback`), which Hermes passes over
    and the caller returns so the fallback is named. `list`, `steer` and
    `stop` start no child, so they read no route.
    """
    if tool_name != "delegate_task":
        return None
    args = tool_input if isinstance(tool_input, Mapping) else {}
    action = str(args.get("action", "") or "").strip().lower()
    if action not in ("", "spawn"):
        return None
    result = prepare_dispatch_route(
        hermes_home, omh_home=omh_home, session_id=session_id, task_id=task_id
    )
    if result.get("status") in DISPATCH_ROUTE_NOTES:
        return {"omh_route_fallback": result}
    if result.get("status") not in DISPATCH_ROUTE_REFUSALS:
        return None
    return {"action": "block", "message": json.dumps(result, ensure_ascii=False, sort_keys=True)}


def _writer_matches(
    record: Mapping[str, Any],
    require_session: str | None,
    require_task: str | None,
) -> bool:
    """Is the caller the writer this record names?

    A RECORDED task decides on its own, and the session is not also
    required. That is not a loosening: it is what makes a restore survive a
    compression split. The host reassigns `agent.session_id` mid-run when it
    splits a long turn's transcript, so the tool recorded the pre-split id
    while the turn-end hook reports the post-split one, and requiring both
    left the route in place on exactly the long fan-out turns that route.
    The task id does not move across a split -- `_bind_turn_identity` binds
    `effective_task_id` once at turn start and nothing in
    `conversation_compression` rebinds it, and the gateway's `task_id` is
    `ctx.session_id`, which is re-baselined only after the run returns. So
    the task id is the same value at the tool and at the turn end on both
    sides of a split, in both flows.

    A record with no task id falls back to the session, which is what a
    caller that never learned a task can be held to.
    """
    if require_task is not None and record["writer_task_id"]:
        return record["writer_task_id"] == require_task
    if require_session is not None:
        return record["writer_session_id"] == require_session
    return True


def _writer_liveness(
    writer_session_id: str,
    *,
    hermes_home: str | Path | None = None,
    written_at: float,
    now: float | None = None,
) -> tuple[str, str, dict[str, str]]:
    """`(verdict, source, report)` from the writer's own row and, when Hermes
    closed that row for compaction, the rows it went on in.

    `report` names the continuation that decided (`writer_continuation`) or
    why none could be read (`lineage_unverified`); it is empty otherwise.
    """
    home = str(hermes_home) if hermes_home else ""
    row = session_row(home, writer_session_id)
    current = float(now if now is not None else time.time())
    if row is None:
        if current - written_at > LIVE_TUI_SESSION_FRESH_SECONDS:
            return "not_live_by_age", "", {}
        return "unknown_within_age_bound", "", {}
    if row["ended_at"] is None or row.get("end_reason") != COMPACTION_END_REASON:
        return _row_liveness(row, written_at, current), str(row["source"]), {}
    # Hermes closed the writer's row to compact the conversation and went on
    # in another row, so the closure says nothing about the writer stopping.
    # Ask the rows it went on in; if they cannot be read, hold the route.
    lineage = compaction_continuations(home, writer_session_id)
    if lineage["status"] != "resolved":
        # Held, but no longer than an unanswered writer row is: past the same
        # age bound an indefinite hold would leave `delegation.*` changed for
        # every later session of the profile, which is the leak this module
        # exists to end.
        verdict = "continuation_unverified"
        if current - written_at > LIVE_TUI_SESSION_FRESH_SECONDS:
            verdict = "continuation_unverified_expired"
        return verdict, str(row["source"]), {"lineage_unverified": str(lineage["reason"])}
    # A verdict that holds the route wins over one that clears it, so one
    # running continuation is enough to keep it.
    verdict, tip = min(
        ((_row_liveness(tip, written_at, current), tip) for tip in lineage["tips"]),
        key=lambda pair: _CONTINUATION_VERDICT_ORDER.index(pair[0]),
    )
    return verdict, str(tip["source"]), {"writer_continuation": str(tip["id"])}


def _row_liveness(row: Mapping[str, Any], written_at: float, current: float) -> str:
    """The verdict one `sessions` row gives, for a row not closed for compaction."""
    if row["ended_at"] is not None:
        return "not_live"
    activity = row["activity"]
    if isinstance(activity, (int, float)) and not isinstance(activity, bool):
        if current - float(activity) <= LIVE_TUI_SESSION_FRESH_SECONDS:
            return "live"
    if current - written_at > LIVE_TUI_SESSION_FRESH_SECONDS:
        return "unclosed_and_stale_by_age"
    return "unclosed_within_age_bound"


def writer_session_liveness(
    writer_session_id: str,
    *,
    hermes_home: str | Path | None = None,
    written_at: float,
    now: float | None = None,
) -> str:
    """Whether the session that wrote the route is still running.

    The question is asked of the WRITER'S OWN row, never of a list the writer
    may not belong to. Asking the live-TUI list instead was the first version
    of this and it was wrong: that list is scoped to "which session is a
    person looking at", so a writer on any other surface is absent from it by
    construction, and absence read as `not_live` restored a baseline under a
    live writer whenever some unrelated TUI happened to be open. Measured on
    the owner's homes, that is the common case rather than the edge: the
    profile that routes most writes every route from a `slack` or `subagent`
    session (#1737 review).

    No transport-id reconciliation happens here. The only caller records the
    writer from `host_session_id(kwargs)`, which the host sets from
    `agent.session_id` -- already the durable key `state.db` rows carry -- so
    a reconciliation step would be unreachable code presenting itself as a
    necessary one.

    The verdicts, and which of them are observations:

    * `live` -- the row exists, the host has not closed it, and its activity
      stamp is inside the freshness window. An observation.
    * `not_live` -- the row exists and carries an `ended_at`. An observation,
      and the only one that clears a restore.
    * `unclosed_and_stale_by_age` / `unclosed_within_age_bound` -- the row
      exists, the host never closed it, and its activity is stale or
      unusable. This is a killed session, or a gateway session of a kind that
      never ends (55 of 57 slack sessions on the owner's machine are open
      rows). Nothing here observes that the process is gone, so the ROUTE's
      own age decides and the name says a bound answered.
    * `not_live_by_age` / `unknown_within_age_bound` -- no row at all, or the
      host surface could not be read. Same bound, same honesty about which
      question went unanswered.
    * `continuation_unverified` / `continuation_unverified_expired` --
      Hermes closed the writer's row to compact the conversation
      (`end_reason` `compression`), and the rows it went on in could not be
      read or authenticated. A closure for compaction is not the writer
      stopping and nothing read here says the conversation stopped, so the
      route is held -- until the route is older than the bound, as for a
      writer row that cannot be found, and then the age bound answers.

    A row Hermes closed for compaction is never answered from its own
    `ended_at`. Its verdict is the one the conversation's continuation gives
    (`compaction_continuations`): `live` while any continuation is running,
    `not_live` once Hermes closed every one, and the age bound for an
    unclosed one, as for any other row.

    The bound is `LIVE_TUI_SESSION_FRESH_SECONDS`, six hours. Task scope
    makes it matter far less than it did: the ordinary way back is the end of
    the writing task, and this path only covers a session killed mid-task.
    Nothing available shortens it -- the host's lease registry records which
    surfaces are open, not whether their processes are alive.
    """
    return _writer_liveness(
        writer_session_id, hermes_home=hermes_home, written_at=written_at, now=now
    )[0]
