from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Final

from ..system.local_store import read_json_object_result, utc_now
from ..system.paths import OmhPaths
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat
from .pi_family_interop import PI_DISTRIBUTION_HOME

EXECUTOR_AUTH_SIGNALS_SCHEMA_VERSION: Final[str] = "executor_auth_signals/v1"

EXECUTOR_AUTH_SIGNALS_CLAIM_BOUNDARY: Final[str] = (
    "An auth signal is a local file-presence marker only. It is not subscription tier, quota, "
    "entitlement, or login truth — the provider owns those — and no secret value is ever read "
    "into omh state."
)

AUTH_MARKER_STATES: Final[tuple[str, ...]] = ("present", "absent", "unknown")

# Marker sources are local config files the agent CLIs write after login.
# Only presence/shape is observed; values are never copied. API-key or
# environment-token installs legitimately show `absent` while working —
# markers rank candidates, they never veto one.
_CLAUDE_CONFIG_RELATIVE: Final[str] = ".claude.json"
_CLAUDE_LOGIN_KEY: Final[str] = "oauthAccount"
_CODEX_AUTH_RELATIVE: Final[str] = ".codex/auth.json"
# A pi-family host CLI carries the pi-family runtime locally; its credential store is
# a JSON object keyed by provider name. Presence of at least one key in the
# first store found (fixed order mirroring PI_FAMILY_HOST_CANDIDATES: pi,
# then pi's distribution host, then the opencode plugin host's store) is
# the marker — key names and values are never read into state, and an
# absent marker never vetoes. The pi fork host has no entry: it keeps its
# credentials in a database (`agent/agent.db`), not a JSON store, and this
# reader does not open databases, so a fork-only install reads `absent`.
_PI_FAMILY_HOST_AUTH_RELATIVES: Final[tuple[str, ...]] = (
    ".pi/agent/auth.json",
    f"{PI_DISTRIBUTION_HOME}/agent/auth.json",
    ".local/share/opencode/auth.json",
)

AUTH_SIGNAL_PROFILES: Final[tuple[str, ...]] = ("codex", "claude-code", "pi-family-runtime")


def executor_auth_signals(home: Path | None = None) -> dict[str, object]:
    """Return metadata-only login markers for the locally-installed agent CLIs."""
    base = home if home is not None else Path.home()
    return {
        "schema_version": EXECUTOR_AUTH_SIGNALS_SCHEMA_VERSION,
        "observed_at": utc_now(),
        "profiles": {
            "codex": _marker_payload(_codex_marker(base), marker_kind="local_auth_file"),
            "claude-code": _marker_payload(_claude_marker(base), marker_kind="local_config_login_key"),
            "pi-family-runtime": _marker_payload(_pi_family_host_marker(base), marker_kind="local_auth_file"),
        },
        "claim_boundary": EXECUTOR_AUTH_SIGNALS_CLAIM_BOUNDARY,
    }


def auth_signal_for_profile(profile: str, home: Path | None = None) -> dict[str, object]:
    """Return the auth-signal entry for one profile; non-CLI profiles are not_applicable.

    Probes only the requested profile's marker file — readiness calls this once
    per dispatch unit, so probing both files here would multiply reads of the
    potentially large `~/.claude.json` for no signal gain.
    """
    normalized = str(profile or "").strip().casefold()
    if normalized not in AUTH_SIGNAL_PROFILES:
        return {
            "login_marker": "not_applicable",
            "marker_kind": "",
            "observed_at": utc_now(),
            "claim_boundary": EXECUTOR_AUTH_SIGNALS_CLAIM_BOUNDARY,
        }
    base = home if home is not None else Path.home()
    if normalized == "codex":
        entry = _marker_payload(_codex_marker(base), marker_kind="local_auth_file")
    elif normalized == "pi-family-runtime":
        entry = _marker_payload(_pi_family_host_marker(base), marker_kind="local_auth_file")
    else:
        entry = _marker_payload(_claude_marker(base), marker_kind="local_config_login_key")
    entry["claim_boundary"] = EXECUTOR_AUTH_SIGNALS_CLAIM_BOUNDARY
    return entry


# Past this horizon a limit signal is advisory history, not current state: the
# provider windows that produce limit-shaped failures reset within hours.
LIMIT_SIGNAL_STALE_AFTER_SECONDS: Final[int] = 6 * 60 * 60


def last_limit_signal_for_profile(paths: OmhPaths, profile: str) -> dict[str, object]:
    """Return the last observed limit-shaped dispatch failure for one profile, if any.

    The entry gains `age_seconds` and `stale` computed at read time so a
    consumer can never mistake an old observation for current provider state.
    """
    state, error = read_json_object_result(paths.executor_limit_signals_path)
    if error or not isinstance(state, dict):
        return {}
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        return {}
    entry = profiles.get(str(profile or "").strip().casefold())
    if not isinstance(entry, dict):
        return {}
    payload = {str(key): value for key, value in entry.items()}
    age = _age_seconds(str(payload.get("last_limit_shaped_at", "") or ""))
    if age is not None:
        payload["age_seconds"] = age
        payload["stale"] = age > LIMIT_SIGNAL_STALE_AFTER_SECONDS
    return payload


def signal_age_seconds(observed_at: str) -> int | None:
    """Age in whole seconds of one recorded observation timestamp, or None.

    Public because the auth-failure signals in `dispatch_failure_recovery` age
    their records by the same rule; a second copy of this arithmetic is how two
    staleness answers start disagreeing.
    """
    return _age_seconds(observed_at)


def _age_seconds(observed_at: str) -> int | None:
    if not observed_at:
        return None
    try:
        observed = strict_fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))


def _claude_marker(home: Path) -> str:
    config_path = home / _CLAUDE_CONFIG_RELATIVE
    try:
        if not config_path.is_file():
            return "absent"
        parsed = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(parsed, dict):
        return "unknown"
    return "present" if _CLAUDE_LOGIN_KEY in parsed else "absent"


def _pi_family_host_marker(home: Path) -> str:
    for relative in _PI_FAMILY_HOST_AUTH_RELATIVES:
        auth_path = home / relative
        if not auth_path.is_file():
            continue
        try:
            parsed = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return "unknown"
        if not isinstance(parsed, dict):
            return "unknown"
        return "present" if parsed else "absent"
    return "absent"


def _codex_marker(home: Path) -> str:
    auth_path = home / _CODEX_AUTH_RELATIVE
    try:
        if not auth_path.is_file():
            return "absent"
        return "present" if auth_path.stat().st_size > 0 else "absent"
    except OSError:
        return "unknown"


def _marker_payload(marker: str, *, marker_kind: str) -> dict[str, object]:
    return {
        "login_marker": marker,
        "marker_kind": marker_kind,
        "observed_at": utc_now(),
    }
