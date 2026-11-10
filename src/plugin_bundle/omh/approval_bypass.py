"""Effective approval-bypass (yolo) observation for the HUD.

The Shift+Tab yolo toggle lives in the host process's ``tools.approval``
session state. Hosts that persist it give the HUD a real-time, on-disk
signal: the classic CLI writes every ``/yolo`` toggle (both directions)
and ``--yolo`` launches into the session row's
``model_config.yolo_mode`` in ``state.db`` so ``--resume`` can restore
it — the Modern TUI's gateway toggle gains the same persist upstream
(until then its rows carry no flag and the ledger answers). The reader
projects that row for the most recently active LIVE TUI session only —
Hermes's own MRU discipline — inside the same freshness bound as the
ledger, so a foreign or long-dead row can never answer for the session
a widget is rendering. ``approvals.mode: off`` is read from
``config.yaml`` directly and dominates, as it does in the host.

The hook-observed ledger answers when no persisted surface speaks: a
toggle before the session's first turn (Hermes creates the row lazily),
a host that does not persist the flag, or a stale row. Both
``pre_llm_call`` and ``pre_tool_call`` tick it with the effective-bypass
answer the host's own status surfaces report. Only the boolean and its
timestamp are recorded, never a command or prompt.

The flag is per session, and one gateway runs many sessions (subagents
and cron runs included) whose hooks all tick the same file. So each
observation is also kept under a key for the session it came from
(``sessions``): the first 16 hex digits of the unsalted sha256 of the
session id. That key is pseudonymous, not anonymous: anyone holding a
session id can compute it and find that session's entry. A reader naming
its session reads only that entry: the newest tick of whichever session
ran last says nothing about the session a pane shows. Where the ledger
holds no entry for that session yet (it has not ticked since the install,
or other sessions pushed it out) while the gateway's newest observation
is a fresh ON, the reader answers ON for the gateway: a wrong ON only
shows a chip, a wrong OFF hides that approvals are bypassed.
"""
from __future__ import annotations

from . import runtime_paths

import hashlib
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the awareness ledger's portable lock and atomic-write primitives so
# there is exactly one file-locking implementation in the plugin.
from .awareness_delivery import _awareness_delivery_lock, _write_delivery_record
# One definition of "a live TUI session row", shared with the plan-todo
# session scope so the two readers cannot drift apart on what they scope to.
from .live_session import live_tui_session_rows

APPROVAL_BYPASS_SCHEMA_VERSION = "omh_approval_bypass/v1"
APPROVAL_BYPASS_FILE = "approval-bypass.json"
# A hook-observed flag outlives the turn that observed it, but not forever:
# after a host restart the per-session flag resets to off in a fresh
# process, and nothing re-observes until the next turn. Six hours bounds
# how long a pre-restart observation can keep claiming a state no process
# holds any more.
APPROVAL_BYPASS_FRESH_SECONDS = 6 * 3600.0
# How long an unchanged observation is left alone before it is rewritten.
#
# The flag changes when a person presses Shift+Tab, and the hooks observe it
# twice per tool call and once per turn -- so nearly every one of those
# locks, temp files and renames wrote a value byte-identical to the one
# already on disk. The write is skipped when the observation matches what is
# recorded.
#
# It cannot be skipped indefinitely, because the timestamp is load-bearing:
# `latest_approval_bypass` reads a record older than
# `APPROVAL_BYPASS_FRESH_SECONDS` as idle, so a state that stayed unchanged
# across six hours of steady work would expire while the hooks were still
# observing it every few seconds. Refreshing at a twelfth of the bound
# leaves eleven twelfths of the window as margin and turns "one write per
# hook call" into "at most twice an hour, plus one per actual toggle".
APPROVAL_BYPASS_REFRESH_SECONDS = APPROVAL_BYPASS_FRESH_SECONDS / 12
# How many sessions' observations the ledger keeps. Entries that say OFF go
# first, then the oldest: losing an OFF costs nothing, losing an ON would
# hide the chip of a session whose approvals are bypassed.
APPROVAL_BYPASS_SESSION_LIMIT = 64
# The latest stamp read as a time: 1 January 3000, the last moment Windows'
# gmtime converts. A larger one, or one that is no finite number, is
# unreadable rather than a moment to compare with.
APPROVAL_BYPASS_STAMP_LIMIT = 32_503_680_000.0
APPROVAL_BYPASS_CLAIM_BOUNDARY = (
    "Hook-observed effective approval-bypass state; it can lag Shift+Tab "
    "toggles and host restarts until the next turn or tool call, and is "
    "never approval, execution, or safety evidence."
)
APPROVAL_BYPASS_HOST_STATE_CLAIM_BOUNDARY = (
    "Projected from the most recently active live TUI session row's "
    "persisted /yolo flag and config.yaml approvals.mode — real-time on "
    "toggles the host persists, but a projection of host state, never "
    "approval, execution, or safety evidence."
)


def _runtime_dir(omh_home: str = "") -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "runtime"


def approval_bypass_path(omh_home: str = "") -> Path:
    return _runtime_dir(omh_home) / APPROVAL_BYPASS_FILE


def session_digest(session_id: str) -> str:
    """The key a session's observation is kept under: a truncated unsalted sha256 of the id, pseudonymous.

    ``surrogatepass`` so an id carrying a lone surrogate still has a key instead of raising in the hook.
    """
    return hashlib.sha256(session_id.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def record_approval_bypass(*, omh_home: str = "", session_id: str = "", now: float | None = None) -> None:
    """Record the current effective bypass state. Best-effort: losing an
    observation is acceptable, breaking the hook that feeds the model is not.

    Writes only when the observation is news -- a different boolean, an
    unreadable or absent record, or one whose stamp is older than
    `APPROVAL_BYPASS_REFRESH_SECONDS`, for the record as a whole or, with a
    ``session_id``, for that session's entry. Every other call is a no-op,
    which is almost all of them: this ran on every tool call and every turn
    for a flag that changes when a person presses Shift+Tab.
    """
    try:
        from tools.approval import is_approval_bypass_active

        enabled = bool(is_approval_bypass_active())
    except Exception:
        # No host approval surface in this process (unit tests, a stripped
        # embed, an older Hermes): there is nothing true to record, and the
        # ledger keeps whatever was last observed rather than a guess.
        return
    tick = float(now if now is not None else time.time())
    path = approval_bypass_path(omh_home)
    digest = session_digest(session_id) if session_id else ""
    current = _read_record(path)
    if _still_current(current, enabled=enabled, now=tick) and (
        not digest or _still_current(_sessions(current).get(digest), enabled=enabled, now=tick)
    ):
        return
    try:
        with _awareness_delivery_lock(path):
            # Read again under the lock: another session's hook may have written since.
            sessions = _sessions(_read_record(path))
            if digest:
                sessions[digest] = {"enabled": enabled, "observed_ts": tick}
            # The record is written key-sorted, so age is the stamp, not the order. An ON outranks every OFF.
            newest = sorted(
                sessions.items(),
                key=lambda item: (isinstance(item[1], dict) and item[1].get("enabled") is True, _stamp(item[1])),
                reverse=True,
            )
            kept = dict(newest[:APPROVAL_BYPASS_SESSION_LIMIT])
            _write_delivery_record(path, {
                "schema_version": APPROVAL_BYPASS_SCHEMA_VERSION,
                "enabled": enabled,
                "observed_ts": tick,
                "sessions": kept,
                "claim_boundary": APPROVAL_BYPASS_CLAIM_BOUNDARY,
            })
    except (OSError, ValueError, TypeError):
        return


def _read_record(path: Path, *, strict: bool = True) -> dict[str, Any] | None:
    """The ledger as written, or None where it is absent or unparsable. ``strict`` also refuses a foreign
    schema or claim boundary, so a skipped write can only mean the record is the one this call would write."""
    import json

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        # RecursionError: a record nested deeper than the parser's stack.
        return None
    if not isinstance(record, dict):
        return None
    if strict and (record.get("schema_version") != APPROVAL_BYPASS_SCHEMA_VERSION
                   or record.get("claim_boundary") != APPROVAL_BYPASS_CLAIM_BOUNDARY):
        return None
    return record


def _tick(value: object) -> float | None:
    """A recorded stamp as seconds, or None where it is no number, not finite, or past `APPROVAL_BYPASS_STAMP_LIMIT`.

    An integer too large for a float raises OverflowError in ``float``; it is unreadable here, not an error.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        tick = float(value)
    except OverflowError:
        return None
    return tick if math.isfinite(tick) and abs(tick) <= APPROVAL_BYPASS_STAMP_LIMIT else None


def _stamp(entry: object) -> float:
    tick = _tick(entry.get("observed_ts")) if isinstance(entry, dict) else None
    return 0.0 if tick is None else tick


def _sessions(record: dict[str, Any] | None) -> dict[str, Any]:
    sessions = record.get("sessions") if isinstance(record, dict) else None
    return dict(sessions) if isinstance(sessions, dict) else {}


def _still_current(entry: object, *, enabled: bool, now: float) -> bool:
    """Whether an observation already says exactly this, recently enough to stand.

    A stamp in the future is not current: a clock that moved backwards must
    not freeze the file until it catches up.
    """
    if not isinstance(entry, dict) or entry.get("enabled") is not enabled:
        return False
    tick = _tick(entry.get("observed_ts"))
    if tick is None:
        return False
    age = now - tick
    return 0.0 <= age <= APPROVAL_BYPASS_REFRESH_SECONDS


def _session_yolo_row(
    hermes_home: str = "", *, now: float | None = None
) -> tuple[bool, float] | None:
    """The persisted /yolo flag off the most recently active live TUI session.

    A host that persists the toggle writes ``model_config.yolo_mode`` on
    every flip, so unlike the hook ledger this sees a toggle the moment it
    happens — between turns included. The row may only ever answer for the
    session a TUI widget is plausibly rendering: ``source='tui'``, not
    ended/archived/hidden, not a delegation child, most recent by the
    host's own MRU column (``last_activity_at``), and no older than the
    ledger's freshness bound. Returns ``(enabled, activity_ts)`` or None
    when no such row speaks (missing DB, older schema, no live TUI session,
    or a session the host has not stamped) so the caller can fall back.
    """
    current = float(now if now is not None else time.time())
    for row in live_tui_session_rows(hermes_home):
        activity = row["activity"]
        config = row["model_config"]
        if not isinstance(activity, (int, float)) or (
            current - float(activity) > APPROVAL_BYPASS_FRESH_SECONDS
        ):
            # The freshest live TUI row is already too old to describe a
            # session anyone is looking at; nothing below it is fresher.
            return None
        # A row without the key means the host never persisted a toggle
        # for this session; only the hook ledger can speak for it.
        if "yolo_mode" not in config:
            return None
        return bool(config.get("yolo_mode")), float(activity)
    return None


def _approvals_mode_off(hermes_home: str = "") -> bool:
    """Whether config.yaml sets the global ``approvals.mode: off`` bypass.

    A minimal text scan in the same spirit as the delegation-route reader:
    only the top-level ``approvals:`` section's ``mode`` key is inspected,
    and anything unreadable or oddly shaped reads as False (not bypassed) so
    this can only ever add a truthful ON, never mask one.
    """
    home = Path(hermes_home).expanduser() if hermes_home else runtime_paths.default_hermes_home()
    try:
        text = (home / "config.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    in_section = False
    child_indent: int | None = None
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            in_section = line.split(":", 1)[0].strip() == "approvals"
            child_indent = None
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        # Only the section's DIRECT children are approvals settings; a
        # deeper `mode:` (e.g. approvals.tools.mode) is a different key and
        # must never read as the global bypass.
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        if stripped.startswith("mode:"):
            raw_value = stripped.partition(":")[2].split("#", 1)[0].strip()
            quoted = (
                len(raw_value) >= 2
                and raw_value[0] in {"'", '"'}
                and raw_value[-1] == raw_value[0]
            )
            value = raw_value[1:-1] if quoted else raw_value
            if quoted:
                # A quoted token is a plain string to YAML: 'false' and 'no'
                # normalize to "manual" in the host, NOT to the bypass.
                return value.casefold() == "off"
            # Bare tokens pass through YAML 1.1 boolean resolution before
            # the host normalizer maps False back to "off": off, false, and
            # no all spell the same bypass.
            return value.casefold() in {"off", "false", "no"}
    return False


def effective_approval_bypass(
    omh_home: str = "", hermes_home: str = "", *, session_id: str = "", now: float | None = None
) -> dict[str, Any]:
    """Real-time yolo projection: host-persisted state first, ledger fallback.

    ``approvals.mode: off`` dominates (the host's own /yolo refuses to
    override it), then the session row's persisted toggle; only when neither
    surface speaks does the hook-observed ledger answer — covering the
    pre-first-turn toggle and older hosts, at turn latency. A ``session_id``
    reads that session's own row and ledger entry, never another session's.
    """
    config_off = _approvals_mode_off(hermes_home)
    row = (
        _named_session_yolo_row(hermes_home, session_id, now=now)
        if session_id
        else _session_yolo_row(hermes_home, now=now)
    )
    if config_off or row is not None:
        current = float(now if now is not None else time.time())
        # observed_at carries the row's own activity timestamp, not the
        # read time: the projection must not restamp old state as fresh.
        observed_ts = row[1] if row is not None and not config_off else current
        observed_at = (
            datetime.fromtimestamp(float(observed_ts), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return {
            "status": "observed",
            "enabled": bool(config_off or (row is not None and row[0])),
            "observed_at": observed_at,
            "source": "host_state",
            "claim_boundary": APPROVAL_BYPASS_HOST_STATE_CLAIM_BOUNDARY,
        }
    return latest_approval_bypass(omh_home, session_id=session_id, now=now)


def _named_session_yolo_row(
    hermes_home: str, session_id: str, *, now: float | None = None
) -> tuple[bool, float] | None:
    """The fresh persisted /yolo flag for exactly one live TUI session."""
    current = float(now if now is not None else time.time())
    for row in live_tui_session_rows(hermes_home):
        if row.get("id") != session_id:
            continue
        activity = row.get("activity")
        if not isinstance(activity, (int, float)) or (
            current - float(activity) > APPROVAL_BYPASS_FRESH_SECONDS
        ):
            return None
        config = row.get("model_config")
        if not isinstance(config, dict) or "yolo_mode" not in config:
            return None
        return bool(config.get("yolo_mode")), float(activity)
    return None


def latest_approval_bypass(omh_home: str = "", *, session_id: str = "", now: float | None = None) -> dict[str, Any]:
    """Project the last observed bypass state, or an idle marker; with ``session_id``, that session's own.

    A named session the ledger holds no entry for reads the gateway's newest observation when that one is a fresh
    ON, marked ``scope: gateway``: it may be another session's, and a wrong ON is the error to make, not a wrong OFF.
    """
    current = float(now if now is not None else time.time())
    idle: dict[str, Any] = {"status": "idle"}
    record = _read_record(approval_bypass_path(omh_home), strict=False)
    if record is None:
        return idle
    scope = ""
    if session_id:
        own = _sessions(record).get(session_digest(session_id))
        if isinstance(own, dict):
            record = own
        elif record.get("enabled") is True:
            scope = "gateway"
        else:
            return idle
    tick = _tick(record.get("observed_ts"))
    enabled = record.get("enabled")
    if tick is None or not isinstance(enabled, bool):
        return idle
    if current - tick > APPROVAL_BYPASS_FRESH_SECONDS:
        return idle
    observed_at = (
        datetime.fromtimestamp(max(0.0, tick), tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    observed = {
        "status": "observed",
        "enabled": enabled,
        "observed_at": observed_at,
        "claim_boundary": APPROVAL_BYPASS_CLAIM_BOUNDARY,
    }
    return {**observed, "scope": scope} if scope else observed
