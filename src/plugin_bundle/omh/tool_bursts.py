"""Parallel tool-call burst observation and in-flight liveness for the HUD.

Hermes executes a model turn's batched tool calls concurrently (its
``_execute_tool_calls_concurrent`` dispatch), but the transcript renders
only a collapsed "Tool calls (N)" group -- nothing tells the user whether
that batch actually ran as a parallel shot, or whether the batch is still
running at all. The ``pre_tool_call`` hook fires once per call, so calls
whose start ticks land inside one short window are the concurrent batch;
this module records those ticks (tool name and timestamp only, never
arguments or results) and projects the latest burst for the ``[OMH]``
status line.

``post_tool_call`` (a second supported Hermes observer hook, paired with
``pre_tool_call`` by ``tool_call_id``) closes what ``pre_tool_call`` opens.
Pairing the two gives an exact in-flight count -- the gap the
ring-buffer-only design could not see: a stopped turn with an incomplete
todo item read identically to 40 tool calls genuinely running, because
nothing distinguished "the ring saturated" from "work is happening". A
host that omits ``tool_call_id`` degrades silently to the pre-pairing
behavior: the tick still lands for burst grouping, but no in-flight entry
opens, and the HUD's liveness signal simply stays quiet for that call.

Scope: the ledger lives at one path per OMH home
(``<omh_home>/runtime/tool-bursts.json``), machine-wide and shared by every
Hermes session pointed at that home -- it is not scoped to one session or
turn. ``record_tool_call`` accepts a ``turn_id`` and stores it on each open
entry, but nothing in this module reads it back to filter or attribute
entries by turn or session; it rides along as inert metadata only. A
sibling session sharing the same OMH home shows up in this session's
liveness signal exactly the same as this session's own calls.
"""
from __future__ import annotations

from . import runtime_paths

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the awareness ledger's portable lock and atomic-write primitives so
# there is exactly one file-locking implementation in the plugin.
from .awareness_delivery import _awareness_delivery_lock, _write_delivery_record

TOOL_BURSTS_SCHEMA_VERSION = "omh_tool_bursts/v1"
TOOL_ACTIVITY_SCHEMA_VERSION = "omh_tool_activity/v1"
TOOL_BURSTS_FILE = "tool-bursts.json"
# Raised from 40 (2026-08, HUD liveness fix): the ring ceiling used to be
# what the "parallel shot x40" badge actually measured -- a fanout wave of
# 40+ short calls saturated the ring long before it went idle, so the badge
# read the buffer filling up, not the truth about what was running. 200 is
# burst HISTORY depth, not a concurrency claim: Hermes caps concurrent tool
# workers well below this (`_MAX_TOOL_WORKERS` in Hermes'
# `agent/tool_executor.py`), so no real dispatch ever has 200 calls open at
# once -- this ceiling exists to keep a long chain of small, fast, strictly
# SEQUENTIAL calls (which the 1.5s grouping window still chains into one
# burst) from growing the file without bound, while keeping each entry
# small (two-three short fields).
MAX_TOOL_BURST_ENTRIES = 200
# Same headroom rationale as MAX_TOOL_BURST_ENTRIES, applied to the
# in-flight ledger: a host that never sends a matching post_tool_call (a
# crash, an unsupported host) must not let open_calls grow without bound.
# Losing the oldest open entry under pathological load is acceptable --
# the ledger is best-effort observation, not a correctness-critical store.
MAX_OPEN_TOOL_CALLS = 200
# Ticks closer together than this belong to one dispatch burst: Hermes
# starts a concurrent batch's workers within milliseconds of each other,
# while consecutive sequential turns are separated by at least one model
# round-trip.
BURST_WINDOW_SECONDS = 1.5
# The HUD shows the latest burst only while it is recent enough to still
# describe "what just happened". Seconds, not minutes, by owner direction
# ('한 몇초만 지나면 바로없어지게'): the badge flags the batch as it lands
# and vanishes right after, refreshed continuously through a busy wave by
# the next batch's ticks.
BURST_FRESH_SECONDS = 8.0
# An open call with no matching post_tool_call this long is not still
# running -- it is a process restart, a crashed host, or a lost tick. It is
# reported as expired rather than kept open forever, and never reported as
# completed (nothing observed it finishing). Known limitation, not fixed
# here: at 100+-way concurrency the file lock `record_tool_call_close`
# takes can itself time out under contention, which strands that close as a
# best-effort no-op -- the entry then rides out this same TTL instead of
# closing promptly, which is an accepted cost of best-effort observation.
TOOL_CALL_OPEN_TTL_SECONDS = 15 * 60
TOOL_BURST_CLAIM_BOUNDARY = (
    "Burst grouping observes pre_tool_call start ticks only; it is evidence "
    "the host dispatched the calls as one batch, not proof every call "
    "overlapped for its full duration."
)
TOOL_ACTIVITY_CLAIM_BOUNDARY = (
    "In-flight state is the local pairing of this host's pre_tool_call and "
    "post_tool_call ticks by tool_call_id. It is evidence of calls this OMH "
    "install observed opening and closing, not a complete accounting of "
    "every tool call Hermes ran."
)
_MAX_TOOL_NAME_CHARS = 48
_MAX_ID_CHARS = 128


def _runtime_dir(omh_home: str = "") -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "runtime"


def tool_bursts_path(omh_home: str = "") -> Path:
    return _runtime_dir(omh_home) / TOOL_BURSTS_FILE


def _normalized_name(tool_name: object) -> str:
    return " ".join(str(tool_name or "").split())[:_MAX_TOOL_NAME_CHARS]


def _normalized_id(value: object) -> str:
    return str(value or "").strip()[:_MAX_ID_CHARS]


def record_tool_call(
    tool_name: object,
    *,
    omh_home: str = "",
    now: float | None = None,
    tool_call_id: object = None,
    turn_id: object = None,
) -> None:
    """Append one pre_tool_call tick and, when the host supplies a
    tool_call_id, open an in-flight entry post_tool_call will close.
    Best-effort: losing a tick is acceptable, breaking the hook that feeds
    the model is not."""
    name = _normalized_name(tool_name)
    if not name:
        return
    tick = float(now if now is not None else time.time())
    call_id = _normalized_id(tool_call_id)
    path = tool_bursts_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            record = _read_record(path)
            open_calls = _prune_expired_opens(record["open_calls"], now=tick)
            # How many calls this install already has open the instant this
            # one starts, counting itself if it opens too. This is the only
            # honest concurrency evidence available: closed entries carry no
            # end time (record_tool_call_close only deletes them), so a
            # group's true peak can only be observed live, at tick time, not
            # reconstructed afterward from start ticks alone.
            open_at_tick = len(open_calls) + (1 if call_id else 0)
            entries = record["entries"]
            entries.append({"tool": name, "ts": tick, "id": call_id, "open_at_tick": open_at_tick})
            entries = entries[-MAX_TOOL_BURST_ENTRIES:]
            if call_id:
                open_calls[call_id] = {
                    "tool": name,
                    "turn_id": _normalized_id(turn_id),
                    "started_at": tick,
                }
                open_calls = _cap_open_calls(open_calls)
            _write_delivery_record(
                path,
                {
                    "schema_version": TOOL_BURSTS_SCHEMA_VERSION,
                    "entries": entries,
                    "open_calls": open_calls,
                    "post_tool_call_observed_at": record["post_tool_call_observed_at"],
                },
            )
    except (OSError, ValueError, TypeError):
        return


def record_tool_call_close(tool_call_id: object, *, omh_home: str = "", now: float | None = None) -> None:
    """post_tool_call: close the in-flight entry pre_tool_call opened, and
    record that this install has observed post_tool_call actually fire.

    The close itself is a no-op when there is nothing to close -- an already
    expired entry, or a host that never sent the matching pre_tool_call tick
    (or any tick at all, for a host that omits tool_call_id). But this
    function running at all is the evidence the HUD's activity block needs:
    ``_host_supports_hook`` skips registering post_tool_call on hosts whose
    ``VALID_HOOKS`` predates it, and on such a host this is simply never
    called. Recording that timestamp unconditionally -- even when there is
    no entry to close -- is what lets the reader tell "this host never
    fires post_tool_call, liveness is unanswerable" apart from "this host
    fires it and nothing happens to be open right now". Best-effort, same
    as ``record_tool_call``."""
    call_id = _normalized_id(tool_call_id)
    tick = float(now if now is not None else time.time())
    path = tool_bursts_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            record = _read_record(path)
            open_calls = _prune_expired_opens(record["open_calls"], now=tick)
            if call_id and call_id in open_calls:
                del open_calls[call_id]
            observed_at = max(tick, record["post_tool_call_observed_at"])
            _write_delivery_record(
                path,
                {
                    "schema_version": TOOL_BURSTS_SCHEMA_VERSION,
                    "entries": record["entries"],
                    "open_calls": open_calls,
                    "post_tool_call_observed_at": observed_at,
                },
            )
    except (OSError, ValueError, TypeError):
        return


def _read_record(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "entries": _sanitized_entries(raw),
        "open_calls": _sanitized_open_calls(raw),
        "post_tool_call_observed_at": _sanitized_observed_at(raw),
    }


def _sanitized_observed_at(raw: dict[str, Any]) -> float:
    value = raw.get("post_tool_call_observed_at")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _sanitized_entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    source = raw.get("entries")
    entries: list[dict[str, Any]] = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        tick = item.get("ts")
        tool = str(item.get("tool", "") or "")
        open_at_tick = item.get("open_at_tick")
        if isinstance(tick, (int, float)) and not isinstance(tick, bool) and tool:
            entries.append(
                {
                    "tool": tool[:_MAX_TOOL_NAME_CHARS],
                    "ts": float(tick),
                    "id": _normalized_id(item.get("id")),
                    "open_at_tick": (
                        int(open_at_tick)
                        if isinstance(open_at_tick, (int, float)) and not isinstance(open_at_tick, bool)
                        else 1
                    ),
                }
            )
    entries.sort(key=lambda entry: entry["ts"])
    return entries


def _sanitized_open_calls(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = raw.get("open_calls")
    open_calls: dict[str, dict[str, Any]] = {}
    for call_id, item in (source.items() if isinstance(source, dict) else ()):
        if not isinstance(item, dict):
            continue
        started_at = item.get("started_at")
        normalized_id = _normalized_id(call_id)
        if not normalized_id or not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
            continue
        open_calls[normalized_id] = {
            "tool": str(item.get("tool", "") or "")[:_MAX_TOOL_NAME_CHARS],
            "turn_id": _normalized_id(item.get("turn_id")),
            "started_at": float(started_at),
        }
    return open_calls


def _prune_expired_opens(open_calls: dict[str, dict[str, Any]], *, now: float) -> dict[str, dict[str, Any]]:
    return {
        call_id: entry
        for call_id, entry in open_calls.items()
        if now - float(entry.get("started_at", now)) <= TOOL_CALL_OPEN_TTL_SECONDS
    }


def _cap_open_calls(open_calls: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(open_calls) <= MAX_OPEN_TOOL_CALLS:
        return open_calls
    newest_first = sorted(open_calls.items(), key=lambda item: item[1]["started_at"], reverse=True)
    return dict(newest_first[:MAX_OPEN_TOOL_CALLS])


def _iso(tick: float) -> str:
    return datetime.fromtimestamp(tick, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_shot_from_entries(
    entries: list[dict[str, Any]],
    open_calls: dict[str, dict[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    idle: dict[str, Any] = {"status": "idle"}
    if not entries:
        return idle
    groups: list[list[dict[str, Any]]] = [[entries[0]]]
    for entry in entries[1:]:
        if entry["ts"] - groups[-1][-1]["ts"] <= BURST_WINDOW_SECONDS:
            groups[-1].append(entry)
        else:
            groups.append([entry])
    latest = next((group for group in reversed(groups) if len(group) >= 2), None)
    if latest is None:
        return idle
    last_tick = latest[-1]["ts"]
    if now - last_tick > BURST_FRESH_SECONDS:
        return idle
    open_count = sum(1 for entry in latest if entry.get("id") and entry["id"] in open_calls)
    return {
        "status": "observed",
        "size": len(latest),
        "distinct_tools": len({entry["tool"] for entry in latest}),
        "observed_at": _iso(last_tick),
        # True in-flight split within this shot's own members, not the ring
        # ceiling: a batch of 40 that saturated the old ring could not tell
        # "still running" from "buffer full".
        "open_count": open_count,
        # NOT a completion claim -- naming it that contradicted
        # TOOL_CALL_OPEN_TTL_SECONDS's own rule that an expired open entry is
        # "never reported as completed (nothing observed it finishing)".
        # This is every member not currently open: a member with no
        # tool_call_id (host degraded to pre-pairing behavior) was never
        # opened, and an expired member's close was never observed either --
        # both land here as "not open", which is the only claim the data
        # backs, not "finished".
        "closed_or_unobserved_count": len(latest) - open_count,
        # The highest open_at_tick observed among this group's own members:
        # at least this many calls were open simultaneously at some point
        # during the shot. This is the group's actual measured concurrency,
        # not `size` -- `size` only proves the host dispatched these calls
        # inside the grouping window, which a long strictly-sequential chain
        # can satisfy just as well as a real parallel batch (Hermes caps
        # concurrent tool workers well under `size` in either case).
        "peak_open_count": max((entry.get("open_at_tick", 1) for entry in latest), default=0),
        "claim_boundary": TOOL_BURST_CLAIM_BOUNDARY,
    }


def _read_snapshot(omh_home: str, *, now: float) -> dict[str, Any]:
    """One ledger read, pruned to `now`. The single point every projection
    below builds from, so a poll that needs more than one projection (the
    HUD reader wants both the parallel-shot and the activity block) sees one
    consistent state instead of two reads that can straddle a concurrent
    writer and disagree about what is currently open."""
    record = _read_record(tool_bursts_path(omh_home))
    return {
        "entries": record["entries"],
        "open_calls": _prune_expired_opens(record["open_calls"], now=now),
        "post_tool_call_observed_at": record["post_tool_call_observed_at"],
    }


def _activity_from_snapshot(snapshot: dict[str, Any], shot: dict[str, Any], *, now: float) -> dict[str, Any]:
    open_calls = snapshot["open_calls"]
    count = len(open_calls)
    if count:
        oldest_id, oldest = min(open_calls.items(), key=lambda item: item[1]["started_at"])
        oldest_started_at = _iso(oldest["started_at"])
        oldest_elapsed_seconds: float | None = max(0.0, now - oldest["started_at"])
    else:
        oldest_started_at = ""
        oldest_elapsed_seconds = None
    return {
        "schema_version": TOOL_ACTIVITY_SCHEMA_VERSION,
        "open_call_count": count,
        "oldest_open_started_at": oldest_started_at,
        "oldest_open_elapsed_seconds": oldest_elapsed_seconds,
        "live": count > 0,
        # Whether this OMH install has ever seen post_tool_call actually
        # fire (record_tool_call_close ran at least once). False on a host
        # `_host_supports_hook` skipped registering post_tool_call for: the
        # ledger's open entries can only expire there, never legitimately
        # close, so `live`/`oldest_open_elapsed_seconds` cannot be trusted
        # either way and the HUD must render liveness as unanswerable
        # rather than inverting silence into a false stall.
        "post_tool_call_observed": snapshot["post_tool_call_observed_at"] > 0,
        "latest_shot": shot,
        "claim_boundary": TOOL_ACTIVITY_CLAIM_BOUNDARY,
    }


def latest_parallel_shot(omh_home: str = "", *, now: float | None = None) -> dict[str, Any]:
    """Project the most recent concurrent batch, or an idle marker."""
    current = float(now if now is not None else time.time())
    snapshot = _read_snapshot(omh_home, now=current)
    return _latest_shot_from_entries(snapshot["entries"], snapshot["open_calls"], now=current)


def tool_call_activity(omh_home: str = "", *, now: float | None = None) -> dict[str, Any]:
    """The HUD's liveness signal: exact open tool-call count plus the shot.

    ``live`` is true precisely while at least one tool call this OMH install
    saw open has not yet closed and has not expired -- it answers "is
    something actually running right now", the question the ring-buffer-only
    badge and a lingering active todo item could not.
    """
    current = float(now if now is not None else time.time())
    snapshot = _read_snapshot(omh_home, now=current)
    shot = _latest_shot_from_entries(snapshot["entries"], snapshot["open_calls"], now=current)
    return _activity_from_snapshot(snapshot, shot, now=current)


def tool_call_projection(omh_home: str = "", *, now: float | None = None) -> dict[str, Any]:
    """`{"parallel_shot": ..., "activity": ...}` from one ledger read.

    The HUD reader needs both projections every poll; calling
    ``latest_parallel_shot`` and ``tool_call_activity`` separately each reads
    the ledger file on its own, so a write landing between the two reads
    could hand the two blocks different snapshots of the same poll. This is
    the single-read equivalent of calling both.
    """
    current = float(now if now is not None else time.time())
    snapshot = _read_snapshot(omh_home, now=current)
    shot = _latest_shot_from_entries(snapshot["entries"], snapshot["open_calls"], now=current)
    return {"parallel_shot": shot, "activity": _activity_from_snapshot(snapshot, shot, now=current)}
