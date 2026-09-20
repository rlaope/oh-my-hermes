"""Persistent policy, cache, and installed-identity state for update checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from ..local_store import atomic_write_json, ensure_dir, file_lock, read_json_object_result
from ..paths import OmhPaths

UPDATE_CHECK_POLICY_SCHEMA_VERSION = "omh_update_check_policy/v1"
UPDATE_CHECK_CACHE_SCHEMA_VERSION = "omh_update_check_cache/v2"
UPDATE_CHECK_RESULT_SCHEMA_VERSION = "omh_update_check_result/v1"
UPDATE_CHECK_MODES = ("off", "notify", "auto")
DEFAULT_UPDATE_CHECK_MODE = "off"
DEFAULT_UPDATE_CHECK_INTERVAL_HOURS = 24.0
MIN_UPDATE_CHECK_INTERVAL_HOURS = 1.0
MAX_UPDATE_CHECK_INTERVAL_HOURS = 8760.0
WATCHED_BRANCH = "main"
_FULL_GIT_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


def update_check_cache_path(paths: OmhPaths) -> Path:
    return paths.runtime_dir / "update-check.json"


def read_update_check_policy(paths: OmhPaths) -> dict[str, Any]:
    profile, _error = read_json_object_result(paths.setup_profile_path)
    raw = (profile or {}).get("update_check")
    mode, interval_hours = DEFAULT_UPDATE_CHECK_MODE, DEFAULT_UPDATE_CHECK_INTERVAL_HOURS
    if isinstance(raw, dict):
        candidate_mode = str(raw.get("mode", "")).strip()
        if candidate_mode in UPDATE_CHECK_MODES:
            mode = candidate_mode
        candidate_interval = raw.get("interval_hours")
        if isinstance(candidate_interval, (int, float)) and not isinstance(candidate_interval, bool) and MIN_UPDATE_CHECK_INTERVAL_HOURS <= candidate_interval <= MAX_UPDATE_CHECK_INTERVAL_HOURS:
            interval_hours = float(candidate_interval)
    return {"schema_version": UPDATE_CHECK_POLICY_SCHEMA_VERSION, "mode": mode, "interval_hours": interval_hours}


def update_check_policy_recorded(paths: OmhPaths) -> bool:
    """Whether a mode was ever recorded, which `read_update_check_policy` cannot say.

    That reader normalizes an absent, malformed, or unrecognized record to the
    shipped `off` default, so what it returns answers "what is in effect" and
    never "was this ever answered". Setup's wizard needs the second question:
    somebody who chose `off` must not be asked again, and somebody who has
    never been asked must be. Only the record separates the two, so this reads
    the record rather than the resolved policy. `write_update_check_policy`
    always stores a recognized mode, so a stored recognized mode is exactly
    the set of homes something wrote one into; a corrupt or hand-edited value
    reads as unanswered here, which matches what the policy reader already
    does with it.
    """
    profile, _error = read_json_object_result(paths.setup_profile_path)
    raw = (profile or {}).get("update_check")
    if not isinstance(raw, dict):
        return False
    return str(raw.get("mode", "")).strip() in UPDATE_CHECK_MODES


def write_update_check_policy(paths: OmhPaths, *, mode: str | None = None, interval_hours: float | None = None) -> dict[str, Any]:
    current = read_update_check_policy(paths)
    resolved_mode = current["mode"] if mode is None else mode
    if resolved_mode not in UPDATE_CHECK_MODES:
        raise ValueError(f"unsupported update-check mode: {resolved_mode!r}; expected one of {', '.join(UPDATE_CHECK_MODES)}")
    resolved_interval = current["interval_hours"] if interval_hours is None else interval_hours
    if isinstance(resolved_interval, bool) or not isinstance(resolved_interval, (int, float)) or not MIN_UPDATE_CHECK_INTERVAL_HOURS <= resolved_interval <= MAX_UPDATE_CHECK_INTERVAL_HOURS:
        raise ValueError(f"update-check interval-hours must be a number between {MIN_UPDATE_CHECK_INTERVAL_HOURS} and {MAX_UPDATE_CHECK_INTERVAL_HOURS}")
    policy = {"schema_version": UPDATE_CHECK_POLICY_SCHEMA_VERSION, "mode": resolved_mode, "interval_hours": float(resolved_interval)}
    profile, _error = read_json_object_result(paths.setup_profile_path)
    profile = profile or {}
    profile["update_check"] = policy
    atomic_write_json(paths.setup_profile_path, profile, private=True)
    return policy


def read_update_check_cache(paths: OmhPaths) -> dict[str, Any]:
    cache, _error = read_json_object_result(update_check_cache_path(paths))
    if not cache:
        return {}
    normalized = dict(cache)
    if "remote_commit" in normalized:
        normalized["remote_commit"] = normalize_git_sha(normalized["remote_commit"])
    return normalized


def write_update_check_cache(paths: OmhPaths, patch: dict[str, Any]) -> dict[str, Any]:
    normalized_patch = dict(patch)
    if "remote_commit" in normalized_patch:
        raw_commit = normalized_patch["remote_commit"]
        normalized_commit = normalize_git_sha(raw_commit)
        if raw_commit not in (None, "") and not normalized_commit:
            raise ValueError("remote commit must be a full 40-character hexadecimal identity")
        normalized_patch["remote_commit"] = normalized_commit
    merged = {**read_update_check_cache(paths), **normalized_patch, "schema_version": UPDATE_CHECK_CACHE_SCHEMA_VERSION}
    path = update_check_cache_path(paths)
    ensure_dir(path.parent, private=True)
    atomic_write_json(path, merged, private=True)
    return merged


def acquire_auto_update_lock(paths: OmhPaths):
    return file_lock(update_check_cache_path(paths), timeout_seconds=0.0, private=True)


def read_runtime_state(paths: OmhPaths) -> dict[str, Any]:
    state, _error = read_json_object_result(paths.runtime_state_path)
    return state or {}


def local_installed_commit(paths: OmhPaths) -> str:
    return normalize_git_sha(read_runtime_state(paths).get("release_source_commit"))


def local_installed_channel(paths: OmhPaths) -> str:
    return str(read_runtime_state(paths).get("release_channel", "") or "")


def interval_elapsed(cache: dict[str, Any], interval_hours: float, now: datetime) -> bool:
    try:
        last_checked = datetime.fromisoformat(str(cache.get("last_checked_at", "")))
    except ValueError:
        return True
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    return (now - last_checked) >= timedelta(hours=interval_hours)


def normalize_git_sha(value: object) -> str:
    if not isinstance(value, str) or not _FULL_GIT_SHA_RE.fullmatch(value):
        return ""
    return value.lower()
