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
timestamp are recorded — never a session key, command, or prompt.
"""
from __future__ import annotations

from . import runtime_paths

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


def record_approval_bypass(*, omh_home: str = "", now: float | None = None) -> None:
    """Record the current effective bypass state. Best-effort: losing an
    observation is acceptable, breaking the hook that feeds the model is not."""
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
    record = {
        "schema_version": APPROVAL_BYPASS_SCHEMA_VERSION,
        "enabled": enabled,
        "observed_ts": tick,
        "claim_boundary": APPROVAL_BYPASS_CLAIM_BOUNDARY,
    }
    try:
        with _awareness_delivery_lock(path):
            _write_delivery_record(path, record)
    except (OSError, ValueError, TypeError):
        return


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
    omh_home: str = "", hermes_home: str = "", *, now: float | None = None
) -> dict[str, Any]:
    """Real-time yolo projection: host-persisted state first, ledger fallback.

    ``approvals.mode: off`` dominates (the host's own /yolo refuses to
    override it), then the session row's persisted toggle; only when neither
    surface speaks does the hook-observed ledger answer — covering the
    pre-first-turn toggle and older hosts, at turn latency.
    """
    config_off = _approvals_mode_off(hermes_home)
    row = _session_yolo_row(hermes_home, now=now)
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
    return latest_approval_bypass(omh_home, now=now)


def latest_approval_bypass(omh_home: str = "", *, now: float | None = None) -> dict[str, Any]:
    """Project the last observed bypass state, or an idle marker."""
    import json

    current = float(now if now is not None else time.time())
    idle: dict[str, Any] = {"status": "idle"}
    try:
        record = json.loads(approval_bypass_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return idle
    if not isinstance(record, dict):
        return idle
    tick = record.get("observed_ts")
    enabled = record.get("enabled")
    if not isinstance(tick, (int, float)) or isinstance(tick, bool) or not isinstance(enabled, bool):
        return idle
    if current - float(tick) > APPROVAL_BYPASS_FRESH_SECONDS:
        return idle
    observed_at = (
        datetime.fromtimestamp(float(tick), tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "status": "observed",
        "enabled": enabled,
        "observed_at": observed_at,
        "claim_boundary": APPROVAL_BYPASS_CLAIM_BOUNDARY,
    }
