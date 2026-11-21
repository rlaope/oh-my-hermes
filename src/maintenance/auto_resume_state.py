"""Whether bare `omh` reopens a dropped OMH TUI session by itself, and a read-only view of what waits.

The policy is `auto_resume.mode` in `<omh_home>/setup-profile.json`: `on`
(also when absent, malformed or unknown) or `off`, written only by `omh
auto-resume set`. `OMH_AUTO_RESUME=0` in the environment turns it off for that
process alone, and `omh --new` for one launch. The record of sessions itself
is `tui/live_sessions.py`'s; `dropped_sessions` only reads it, for `omh
auto-resume status`, and changes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, read_json_object_result
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat

AUTO_RESUME_POLICY_SCHEMA_VERSION = "omh_auto_resume_policy/v1"
AUTO_RESUME_MODES = ("on", "off")
DEFAULT_AUTO_RESUME_MODE = "on"
AUTO_RESUME_ENV = "OMH_AUTO_RESUME"
SETUP_PROFILE_FILE = "setup-profile.json"


def _profile_path(omh_home: str | Path) -> Path:
    return Path(omh_home) / SETUP_PROFILE_FILE


def read_auto_resume_mode(omh_home: str | Path) -> str:
    """The stored mode; `on` when none is stored or the file cannot be read."""
    profile, _error = read_json_object_result(_profile_path(omh_home))
    raw = (profile or {}).get("auto_resume")
    if isinstance(raw, dict):
        mode = raw.get("mode")
        if isinstance(mode, str) and mode.strip() in AUTO_RESUME_MODES:
            return mode.strip()
    return DEFAULT_AUTO_RESUME_MODE


def write_auto_resume_mode(omh_home: str | Path, mode: str) -> dict[str, Any]:
    """Store `mode` beside the other setup answers, keeping every other key; the stored policy."""
    if mode not in AUTO_RESUME_MODES:
        raise ValueError(f"unsupported auto-resume mode: {mode!r}; expected one of {', '.join(AUTO_RESUME_MODES)}")
    path = _profile_path(omh_home)
    profile, _error = read_json_object_result(path)
    profile = profile or {}
    profile["auto_resume"] = {"mode": mode}
    atomic_write_json(path, profile, private=True)
    return {"schema_version": AUTO_RESUME_POLICY_SCHEMA_VERSION, "mode": mode}


def environment_off(environ: Mapping[str, str]) -> bool:
    """Whether `OMH_AUTO_RESUME=0` turns auto-resume off for this process."""
    return str(environ.get(AUTO_RESUME_ENV, "")).strip() == "0"


def auto_resume_enabled(omh_home: str | Path, environ: Mapping[str, str]) -> bool:
    """On unless the stored mode is `off` or the environment says `OMH_AUTO_RESUME=0`."""
    return not environment_off(environ) and read_auto_resume_mode(omh_home) == "on"


def _age_seconds(stamp: str, now: datetime) -> float | None:
    try:
        moment = strict_fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max((now - moment).total_seconds(), 0.0)


def dropped_sessions(omh_home: str | Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """The sessions a reopen could still take, newest first, without changing the record.

    A `dropped` entry, and a `live` one whose process is gone (the next launch
    sweeps it to `dropped`). Each row is the id, the folder, the NAME of the
    terminal variable it was keyed by (never its value), the Hermes home, and
    its age in seconds; nothing said in the session is read.
    """
    from ..tui import live_sessions

    now = now or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for entry in reversed(live_sessions.entries(Path(omh_home))):
        gone = bool(entry.get("gone"))
        if entry["state"] != live_sessions.DROPPED and not gone:
            continue
        rows.append({
            "session_id": entry["session_id"],
            "cwd": entry["cwd"],
            "terminal_key_name": entry["terminal_key"].split("=", 1)[0] if entry["terminal_key"] else "",
            "hermes_home": entry["hermes_home"],
            "age_seconds": _age_seconds(entry["updated_at"], now),
            "process_gone": gone,
        })
    return rows
