"""Does a recorded Hermes gateway start predate the OMH bundle its home now carries?

A gateway keeps serving the plugin bundle and skills it loaded at start, so
after `omh update` a bot that was running through the update still answers
with pre-update code until someone restarts it. Update already says
"restart Hermes"; this module says which gateways that sentence is about,
from file evidence alone.

Hermes writes ``<hermes_home>/gateway.pid`` when a gateway starts (a JSON
record: ``pid``, ``kind``, ``argv``, ``start_time``, ``hermes_home``, created
O_EXCL and unlinked on a clean stop) and appends one epoch-seconds line per
start attempt to ``<hermes_home>/gateway-starts.log`` (its respawn-storm
ledger: a bounded ring of ``repr(float)`` lines, written at CLI entry before
the pid-ownership check). The pid record's ``start_time`` is NOT a wall clock
and is never read as one here: Hermes' ``_get_process_start_time`` is
``/proc/<pid>/stat`` field 22 (clock ticks since boot) on Linux and psutil
``create_time() * 100`` (centiseconds) elsewhere -- a per-host PID-reuse
fingerprint. The starts ledger carries the wall clock, so the comparison
reads that: the LAST RECORDED START for the home against the bundle
manifest's ``installed_at``. The stamp is rewritten by every non-dry-run
update, so the hint names a gateway whose last recorded start precedes this
update, which is the restart the update's own restart line is about; it
does not prove the running process is the one that start recorded.

No signal, no process listing, no subprocess, and nothing here raises: a
successful update must not end in a traceback over a ledger line that is
not a number. A pid record Hermes left behind after a crash produces a hint
to restart a gateway that is not running, which costs one line; a missing
record produces no hint even when a gateway runs under some other
supervision, which is the evidence boundary and is said as such. A record
naming a different ``hermes_home`` is another profile's, exactly as Hermes'
own cross-profile guard reads it, and produces nothing.

The same evidence feeds the launch notices the OMH TUI and `omh doctor` show
(`gateway_notices`), with one more Hermes file: ``<hermes_home>/gateway_state.json``,
the runtime record a running gateway rewrites as it goes. Its
``session_store.status`` is Hermes' one aggregate over every store the
gateway holds (``gateway/session_db_recovery.py``): ``"unavailable"`` means
the gateway refuses state.db writes on at least one of them, which on a
shared gateway is often a profile deleted while it was served, whose handle
Hermes reads as "state.db was replaced". The default store and the sessions
already on disk are not touched by it, so the notice says so, says it is
Hermes', and names the restart; OMH restarts nothing and fixes nothing here.

A third state is a restart already under way: ``gateway_state`` is
``"draining"`` while Hermes waits for running turns before it stops
(``gateway/run_shutdown.py``, capped by ``agent.restart_after_turn_timeout``),
and every new message meanwhile is refused with ``runtime_draining``. The
record names each unit it waits for (``active_work``); the time left exists
only in Hermes' memory and in the line it logs every 30 s
(``... 749s remaining before force drain)``), so it is read from the tail of
``<hermes_home>/logs/gateway.log`` and said only while that line is fresh.
While a gateway drains, the other two lines are not said: the restart they
ask for is the one in progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import time

from ..install.plugin_pack import read_plugin_manifest
from ..local_store import read_json_object
from ..paths import OmhPaths
from ..install.skill_registration import hermes_profile_dirs

GATEWAY_PID_FILENAME = "gateway.pid"
GATEWAY_STARTS_FILENAME = "gateway-starts.log"
GATEWAY_STATE_FILENAME = "gateway_state.json"
# Hermes' record is about a kilobyte; a file past this bound is not one it wrote.
GATEWAY_STATE_BYTES = 1 << 20
SESSION_STORE_UNAVAILABLE = "unavailable"
# The `gateway_state` values Hermes leaves once the process is gone (`gateway/status.py`).
_GATEWAY_GONE_STATES = frozenset({"stopped", "startup_failed"})
NOTICE_STORE_UNAVAILABLE = "session_store_unavailable"
NOTICE_STALE_BUNDLE = "stale_plugin_bundle"
NOTICE_DRAINING = "draining"
GATEWAY_DRAINING = "draining"
RESTART_WAIT_KNOB = "agent.restart_after_turn_timeout"
GATEWAY_LOG = Path("logs") / "gateway.log"
# Hermes logs the restart wait every 30 s; the tail read keeps the newest lines and costs one bounded read.
DRAIN_LOG_TAIL_BYTES = 256 << 10
DRAIN_LOG_FRESH_SECONDS = 90.0
_FORCE_DRAIN_MARK = "s remaining before force drain)"
_LOG_STAMP_FORMAT = "%Y-%m-%d %H:%M:%S,%f"  # Python logging's asctime, in local time
_LOG_STAMP_CHARS = 23


@dataclass(frozen=True)
class GatewayNotice:
    """One Hermes-gateway line for the OMH TUI's launch and `omh doctor`, and the command it names."""

    kind: str  # NOTICE_STORE_UNAVAILABLE, NOTICE_STALE_BUNDLE or NOTICE_DRAINING
    text: str
    restart_command: str  # "" for a gateway already restarting: there is nothing to run


@dataclass(frozen=True)
class GatewayDrain:
    """A gateway draining before it stops, as its record and its log say."""

    restarting: bool  # `restart_requested`: it starts again after the wait; else it is shutting down
    turns: int | None  # the work units it waits for; None when the record names no count
    seconds_left: int | None  # before it stops them anyway; None unless a fresh log line says


def gateway_restart_hints(paths: OmhPaths) -> list[str]:
    """One line per home whose last recorded gateway start precedes its bundle install."""
    hints: list[str] = []
    primary = gateway_restart_hint(
        paths.hermes_home,
        label=str(paths.hermes_home),
        restart_command="hermes gateway restart",
    )
    if primary:
        hints.append(primary)
    for name, profile_dir in hermes_profile_dirs(paths.hermes_home):
        hint = gateway_restart_hint(
            profile_dir,
            label=f"profile {name}",
            restart_command=f"hermes --profile {name} gateway restart",
        )
        if hint:
            hints.append(hint)
    return hints


def recorded_gateway_starts(hermes_home: Path) -> list[float]:
    """The last recorded start of each gateway the home and its profiles name.

    Update's generation retention reads this, on the same evidence as the
    hint: a pid record naming the home and a wall-clock start in its ledger.
    """
    starts: list[float] = []
    for home in (hermes_home, *(profile for _name, profile in hermes_profile_dirs(hermes_home))):
        start = _last_gateway_start(home / GATEWAY_STARTS_FILENAME) if _pid_record_names_home(home) else None
        if start is not None:
            starts.append(start)
    return starts


def gateway_restart_hint(hermes_home: Path, *, label: str, restart_command: str) -> str | None:
    """The hint for one home, or None when the files do not prove a stale gateway."""
    stale = _stale_bundle_times(hermes_home)
    if stale is None:
        return None
    started_iso, installed_iso = stale
    return (
        f"Hermes gateway for {label}: last recorded start {started_iso} precedes this bundle's "
        f"install ({installed_iso}); run `{restart_command}`"
    )


def gateway_notice_home(home: Path, profile: str = "") -> tuple[Path, str, str]:
    """A home with the label and restart command its notices use: the primary home's without a profile name."""
    if not profile:
        return home, "Hermes' gateway", "hermes gateway restart"
    return home, f"Hermes' gateway for profile {profile}", f"hermes --profile {profile} gateway restart"


def gateway_notice_homes(hermes_home: Path) -> list[tuple[Path, str, str]]:
    """The primary home and every profile, as `gateway_notice_home` gives each."""
    return [
        gateway_notice_home(hermes_home),
        *(gateway_notice_home(profile_dir, name) for name, profile_dir in hermes_profile_dirs(hermes_home)),
    ]


def gateway_notices(
    hermes_home: Path, *, label: str, restart_command: str, now: float | None = None
) -> list[GatewayNotice]:
    """The lines a person should see about this home's running gateway; empty when its files show nothing to say.

    Every line names Hermes' gateway, and none claims OMH can repair or
    restart it: the store refusal is Hermes' own, the stale bundle clears only
    when the gateway loads the new code, and a draining gateway finishes on
    its own. A draining gateway gets that line alone.
    """
    drain = gateway_drain(hermes_home, now=now)
    if drain is not None:
        return [GatewayNotice(NOTICE_DRAINING, _drain_text(label, drain), "")]
    notices: list[GatewayNotice] = []
    if gateway_session_store_status(hermes_home) == SESSION_STORE_UNAVAILABLE:
        notices.append(GatewayNotice(
            NOTICE_STORE_UNAVAILABLE,
            f"{label} cannot write its session store (Hermes reports it unavailable, often over a deleted "
            f"profile it still holds); your saved sessions on disk are fine. Restart it with `{restart_command}`.",
            restart_command,
        ))
    stale = _stale_bundle_times(hermes_home)
    if stale is not None:
        started_iso, installed_iso = stale
        notices.append(GatewayNotice(
            NOTICE_STALE_BUNDLE,
            f"{label} started before OMH was updated (last start {started_iso}, OMH plugin installed "
            f"{installed_iso}), so it still runs the old OMH plugin code; restart it with `{restart_command}` "
            "to load the new code.",
            restart_command,
        ))
    return notices


def gateway_session_store_status(hermes_home: Path) -> str | None:
    """`session_store.status` from the record of the gateway running in this home, or None.

    None unless every file agrees a gateway runs here: `gateway.pid` names the
    home (Hermes unlinks it on a clean stop), `gateway_state.json` names the
    same home and pid, and its `gateway_state` is not one Hermes leaves after
    the process is gone. A missing or oversized file, JSON that is not an
    object, or a key of the wrong type is no evidence and reads as None.
    """
    record = _running_gateway_record(hermes_home)
    if record is None:
        return None
    store = record.get("session_store")
    status = store.get("status") if isinstance(store, dict) else None
    return status if isinstance(status, str) and status else None


def gateway_drain(hermes_home: Path, *, now: float | None = None) -> GatewayDrain | None:
    """The drain of the gateway running in this home, or None when its record does not say `draining`."""
    record = _running_gateway_record(hermes_home)
    if record is None or record.get("gateway_state") != GATEWAY_DRAINING:
        return None
    work = record.get("active_work")
    agents = record.get("active_agents")
    if isinstance(work, list) and work:
        turns: int | None = len(work)
    elif isinstance(agents, int) and not isinstance(agents, bool) and agents > 0:
        turns = agents
    else:
        turns = None
    return GatewayDrain(
        record.get("restart_requested") is True,
        turns,
        _drain_seconds_left(hermes_home / GATEWAY_LOG, time.time() if now is None else now),
    )


def _drain_text(label: str, drain: GatewayDrain) -> str:
    action = "is restarting" if drain.restarting else "is shutting down"
    waits = (
        f"it waits for {drain.turns} running turn{'' if drain.turns == 1 else 's'} to finish"
        if drain.turns is not None else "it waits for its running turns to finish"
    )
    left = f" (about {drain.seconds_left}s left before it stops them anyway)" if drain.seconds_left is not None else ""
    return (
        f"{label} {action}: {waits} first{left}, and refuses new messages until it is done; bots answer "
        f"them with `runtime_draining`. Hermes caps the wait with `{RESTART_WAIT_KNOB}` in its config."
    )


def _drain_seconds_left(log_path: Path, now: float) -> int | None:
    """What the newest restart-wait line in Hermes' gateway log leaves, aged to `now`; None unless it is fresh."""
    try:
        with log_path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - DRAIN_LOG_TAIL_BYTES))
            tail = handle.read(DRAIN_LOG_TAIL_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    line = next((line for line in reversed(tail.splitlines()) if _FORCE_DRAIN_MARK in line), None)
    if line is None:
        return None
    try:
        logged = datetime.strptime(line[:_LOG_STAMP_CHARS], _LOG_STAMP_FORMAT).timestamp()
        left = float(line[: line.index(_FORCE_DRAIN_MARK)].rsplit(" ", 1)[-1])
    except (ValueError, OverflowError, OSError):
        return None
    age = now - logged
    if not math.isfinite(left) or left < 0 or not 0 <= age <= DRAIN_LOG_FRESH_SECONDS:
        return None
    return max(0, round(left - age))


def _running_gateway_record(hermes_home: Path) -> dict[str, object] | None:
    """`gateway_state.json` when every file agrees its gateway runs in this home, else None."""
    pid_record = _home_pid_record(hermes_home)
    if pid_record is None:
        return None
    record = _bounded_json_object(hermes_home / GATEWAY_STATE_FILENAME)
    if record is None:
        return None
    recorded_home = record.get("hermes_home")
    if isinstance(recorded_home, str) and recorded_home.strip() and not _same_home(recorded_home, hermes_home):
        return None
    pids = (pid_record.get("pid"), record.get("pid"))
    if all(isinstance(pid, int) and not isinstance(pid, bool) for pid in pids) and pids[0] != pids[1]:
        return None
    if record.get("gateway_state") in _GATEWAY_GONE_STATES:
        return None
    return record


def _stale_bundle_times(hermes_home: Path) -> tuple[str, str] | None:
    """The last recorded gateway start and the bundle's install, as UTC stamps, when the start is the earlier."""
    if not _pid_record_names_home(hermes_home):
        return None
    last_start = _last_gateway_start(hermes_home / GATEWAY_STARTS_FILENAME)
    if last_start is None:
        return None
    manifest = read_plugin_manifest(hermes_home / "plugins" / "omh")
    installed_at = _installed_at_epoch(manifest)
    if installed_at is None or last_start >= installed_at:
        return None
    started_iso = _iso_utc(last_start)
    installed_iso = _iso_utc(installed_at)
    if started_iso is None or installed_iso is None:
        return None
    return started_iso, installed_iso


def _bounded_json_object(path: Path) -> dict[str, object] | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(GATEWAY_STATE_BYTES + 1)
        if len(raw) > GATEWAY_STATE_BYTES:
            return None
        data = json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _pid_record_names_home(hermes_home: Path) -> bool:
    return _home_pid_record(hermes_home) is not None


def _home_pid_record(hermes_home: Path) -> dict[str, object] | None:
    """The `gateway.pid` record when it is this home's, else None."""
    try:
        record = read_json_object(hermes_home / GATEWAY_PID_FILENAME)
    except (OSError, ValueError, RecursionError):
        return None
    if record is None:
        return None
    recorded_home = record.get("hermes_home")
    if not isinstance(recorded_home, str) or not recorded_home.strip():
        # A legacy record without a home proves nothing about another
        # profile, so it is read as this home's -- Hermes reads it the same way.
        return record
    return record if _same_home(recorded_home, hermes_home) else None


def _same_home(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(os.path.expanduser(str(left)))) == os.path.normcase(
        os.path.realpath(os.path.expanduser(str(right)))
    )


def _last_gateway_start(path: Path) -> float | None:
    """The latest wall-clock start in the ledger, or None when no line is one.

    Only a finite, positive number is a start: `nan`, `inf`, a negative value
    or bytes that are not UTF-8 are a ledger Hermes did not write, and the
    hint stays silent rather than raising out of `omh update`.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    starts: list[float] = []
    for line in lines:
        try:
            value = float(line.strip())
        except ValueError:
            continue
        if math.isfinite(value) and value > 0:
            starts.append(value)
    return max(starts) if starts else None


def _installed_at_epoch(manifest: dict[str, object] | None) -> float | None:
    if not manifest:
        return None
    value = manifest.get("installed_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _iso_utc(epoch: float) -> str | None:
    try:
        return datetime.fromtimestamp(epoch, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None
