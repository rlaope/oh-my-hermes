"""Does a recorded Hermes gateway start predate the OMH bundle its home now carries?

A gateway keeps serving the plugin code it loaded at start, so after
`omh update` a bot that was running through the update still answers with
pre-update plugin code until someone restarts it; this module says which
gateways that is, from file evidence alone. Skills are not part of it:
`refresh_skill_dir_caches` makes a running Hermes re-read OMH's skills
directory after the generation pointer moves, with no restart.

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
manifest's ``installed_at``. The stamp is rewritten only when an update
changes the bundle's files (a moved ``package_site`` alone keeps it), so the
hint names a gateway whose last recorded start precedes the bundle bytes it
would now load; it does not prove the running process is the one that start
recorded.

No signal, no process listing, no subprocess, and nothing here raises: a
successful update must not end in a traceback over a ledger line that is
not a number. A pid record Hermes left behind after a crash produces a hint
to restart a gateway that is not running, which costs one line; a missing
record produces no hint even when a gateway runs under some other
supervision, which is the evidence boundary and is said as such. A record
naming a different ``hermes_home`` is another profile's, exactly as Hermes'
own cross-profile guard reads it, and produces nothing.

The same evidence feeds the launch notices the OMH TUI and `omh doctor` show
(`gateway_notices`), read only from a fresh ``<hermes_home>/gateway_state.json``:
the runtime record a running gateway re-stamps every minute. A record older
than Hermes' own 120 s staleness bound, or one in a state Hermes reads as
gone, is no evidence of anything.

Its ``session_store.status`` is Hermes' one aggregate over every store the
gateway holds (``gateway/session_db_recovery.py``), and a restarted gateway
keeps the old process's value until it publishes its own, so ``"unavailable"``
is never said on its own. The newest store failure in
``logs/gateway.error.log`` logged after the last recorded start says what
failed: a deleted profile still referenced (a restart does not clear it), a
served profile Hermes parked, or a store replaced underneath it (the one case
a restart reopens). Only a failure that provably is not the default store
says the person's sessions are unaffected.

A third state is a drain: ``gateway_state`` is ``"draining"`` while Hermes
lets running turns finish and starts no new ones. For a restart
(``restart_requested``) the wait is capped by ``agent.restart_after_turn_timeout``
and Hermes logs it every 30 s (``Restart deferred: waiting on N ...; 749s
remaining before force drain)``), so the awaited count and the time left come
from that line while it is fresh. A ``.drain_request.json`` beside the record
is a drain request: the gateway keeps running and resumes when the request
goes. Anything else is a stop. While a gateway drains, nothing else is said.
OMH stops, restarts and repairs nothing here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from ..install.config_adapter import read_config
from ..install.plugin_pack import PLUGIN_MANAGED_MANIFEST, read_plugin_manifest
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat
from ..paths import OmhPaths
from ..install.skill_registration import hermes_profile_dirs, managed_candidate_entries, registration_home_label

GATEWAY_PID_FILENAME = "gateway.pid"
GATEWAY_STARTS_FILENAME = "gateway-starts.log"
GATEWAY_STATE_FILENAME = "gateway_state.json"
DRAIN_REQUEST_FILENAME = ".drain_request.json"  # Hermes' `gateway/drain_control.py`
GATEWAY_LOG = Path("logs") / "gateway.log"
GATEWAY_ERROR_LOG = Path("logs") / "gateway.error.log"
# Hermes' record is about a kilobyte, its pid record a few hundred bytes and its starts ledger a 40-line ring; a file
# past these bounds is not one it wrote, and the TUI's launch never reads more.
GATEWAY_STATE_BYTES = 1 << 20
PID_RECORD_BYTES = 64 << 10
LEDGER_TAIL_BYTES = 64 << 10
# Hermes logs the restart wait every 30 s; the gateway log's tail keeps the newest lines in one bounded read.
DRAIN_LOG_TAIL_BYTES = 256 << 10
DRAIN_LOG_FRESH_SECONDS = 90.0
# The error log gains a few hundred bytes every few minutes on a quiet gateway; a store failure since the last start
# stays inside this tail for days.
STORE_LOG_TAIL_BYTES = 1 << 20
# Hermes' `_RUNTIME_STATUS_STALE_TTL_S`: a record not re-stamped within this outlived its writer.
RUNTIME_STATUS_STALE_SECONDS = 120.0
SESSION_STORE_UNAVAILABLE = "unavailable"
GATEWAY_DRAINING = "draining"
# What Hermes' `gateway/status.py` reads as a gateway no longer running: no state, a stop, a failed start, or a
# watchdog's hard exit.
_GATEWAY_GONE_STATES = frozenset({"stopped", "startup_failed"})
_WATCHDOG_EXIT_REASONS = frozenset({"loop_liveness_watchdog", "shutdown_watchdog"})
RESTART_WAIT_KNOB = "agent.restart_after_turn_timeout"
NOTICE_STORE_UNAVAILABLE = "session_store_unavailable"
NOTICE_DELETED_PROFILE_STORE = "deleted_profile_store"
NOTICE_PROFILE_NOT_SERVED = "profile_store_unusable"
NOTICE_STALE_BUNDLE = "stale_plugin_bundle"
NOTICE_DRAINING = "draining"
DRAIN_RESTART = "restart"
DRAIN_REQUEST = "drain_request"
DRAIN_STOPPING = "stopping"
_LOG_STAMP = r"^(?P<stamp>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d{3} "
_LOG_STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"  # Python logging's asctime, in the local time of the reading process
# `gateway/run_shutdown.py` `_await_active_work_before_restart`, the only writer of this line.
_WAIT_LINE = re.compile(
    _LOG_STAMP + r"\w+ gateway\.run: Restart deferred: waiting on (?P<units>\d+) active work unit\(s\) "
    r"\([^;)]*; (?P<left>\d+)s remaining before force drain\)"
)
# The store failures Hermes logs, newest first decides: `hermes_constants` (a profile home that is gone),
# `gateway/run_runtime.py` (a served profile parked), `hermes_state_errors` (a store replaced underneath it).
_MISSING_PROFILE = re.compile(
    _LOG_STAMP + r".*session store unavailable, falling back to JSONL: Named profile home does not exist: "
    r"(?P<home>[^\n]+?)\. Create the profile"
)
_NOT_SERVED = re.compile(_LOG_STAMP + r".*Profile '(?P<name>[^']+)' not served: its session store is unusable "
                         r"\((?P<home>[^)]*)\)")
_REPLACED = re.compile(_LOG_STAMP + r".*(?P<what>state\.db was replaced) underneath the gateway")
_UNNAMED = re.compile(_LOG_STAMP + r".*(?P<what>session store unavailable|did not open)")


@dataclass(frozen=True)
class GatewayNotice:
    """One Hermes-gateway line for the OMH TUI's launch and `omh doctor`, and what the person can do about it."""

    kind: str  # one of the NOTICE_* names
    text: str
    restart_command: str  # "" when a restart is not the remedy, or one is already under way
    next_action: str  # doctor's next action: what the person can do; never something OMH does


@dataclass(frozen=True)
class GatewayDrain:
    """A gateway draining, as its record, its home and its log say."""

    reason: str  # DRAIN_RESTART, DRAIN_REQUEST or DRAIN_STOPPING
    turns: int | None  # the work units it waits for; None when nothing names a count
    seconds_left: int | None  # before a restart stops them anyway; None unless a fresh wait line says


@dataclass(frozen=True)
class StoreFailure:
    """The newest store failure Hermes' error log records since the gateway's last start."""

    kind: str  # NOTICE_DELETED_PROFILE_STORE, NOTICE_PROFILE_NOT_SERVED or NOTICE_STORE_UNAVAILABLE
    logged: str  # the line's own stamp, as Hermes wrote it
    what: str  # the failure in Hermes' words, for a store it does not name
    profile: str = ""
    home: str = ""


def gateway_restart_hints(paths: OmhPaths, *, unrefreshed_configs: frozenset[str] = frozenset()) -> list[str]:
    """One line per home whose last recorded gateway start precedes its bundle install.

    `unrefreshed_configs` names the config.yaml files `refresh_skill_dir_caches`
    could not touch; a gateway there also needs the restart for its skills.
    """
    hints: list[str] = []
    primary = gateway_restart_hint(
        paths.hermes_home,
        label=str(paths.hermes_home),
        restart_command="hermes gateway restart",
        skills_reloaded=str(paths.hermes_home / "config.yaml") not in unrefreshed_configs,
    )
    if primary:
        hints.append(primary)
    for name, profile_dir in hermes_profile_dirs(paths.hermes_home):
        hint = gateway_restart_hint(
            profile_dir,
            label=f"profile {name}",
            restart_command=f"hermes --profile {name} gateway restart",
            skills_reloaded=str(profile_dir / "config.yaml") not in unrefreshed_configs,
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


def refresh_skill_dir_caches(hermes_home: Path, skills_pointer: Path | None) -> list[dict[str, str]]:
    """Make every Hermes process re-read OMH's skills directory, without a restart.

    Hermes caches the RESOLVED path of each `skills.external_dirs` entry,
    keyed by config.yaml's file signature (mtime, size, inode, ctime). OMH
    registers `<root>/current/skills`, and `current` is the symlink update
    moves to a new generation, so a running gateway kept resolving the old
    generation -- and lost every OMH skill once that generation was
    collected -- until `hermes gateway restart`. Moving the mtime of each
    config that names the pointer changes that signature, and Hermes
    resolves the pointer again on its next skill lookup.

    Only a home whose config names `skills_pointer` (matched the way the
    registration writer matches it, `managed_candidate_entries`) is touched;
    the content is never rewritten, atime is kept, and a missing config is
    never created. Best effort: a home that could not be touched is a
    `failed` row with the reason, never an exception.
    """
    if skills_pointer is None:
        return []
    homes: list[tuple[str | None, Path]] = [(None, hermes_home), *hermes_profile_dirs(hermes_home)]
    rows: list[dict[str, str]] = []
    for profile, home in homes:
        config = home / "config.yaml"
        label = registration_home_label(config, profile=profile)
        try:
            # The pointer check sits inside the try: a pointer that cannot be
            # stat'ed is a `failed` row for each home, not an exception.
            if not config.is_file() or not skills_pointer.is_dir():
                continue
            if not managed_candidate_entries(read_config(config), [skills_pointer], hermes_home=home):
                continue
            os.utime(config, ns=(config.stat().st_atime_ns, time.time_ns()))
        except (OSError, UnicodeError, ValueError) as exc:
            rows.append({"home": label, "config": str(config), "status": "failed", "error": str(exc)})
            continue
        rows.append({"home": label, "config": str(config), "status": "refreshed"})
    return rows


def gateway_restart_hint(hermes_home: Path, *, label: str, restart_command: str, skills_reloaded: bool = True) -> str | None:
    """The hint for one home, or None when the files do not prove a stale gateway."""
    stale = _stale_bundle_times(hermes_home)
    if stale is None:
        return None
    started_iso, installed_iso = stale
    reload = (
        "OMH skills reload on their own, but the new OMH plugin code loads"
        if skills_reloaded
        else "the new OMH skills and plugin code load"
    )
    return (
        f"Hermes gateway for {label}: last recorded start {started_iso} precedes this bundle's "
        f"install ({installed_iso}); {reload} only after `{restart_command}`"
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

    Nothing is said unless `gateway_state.json` is a fresh record of a gateway
    running in this home (`_running_gateway_record`). Every line names Hermes'
    gateway, and none claims OMH can repair, stop or restart it. A draining
    gateway gets that line alone: whatever else it would say waits on it.
    """
    moment = time.time() if now is None else now
    record = _running_gateway_record(hermes_home, moment)
    if record is None:
        return []
    drain = _drain(hermes_home, record, moment)
    if drain is not None:
        return [_drain_notice(hermes_home, label, drain)]
    notices: list[GatewayNotice] = []
    if _store_status(record) == SESSION_STORE_UNAVAILABLE:
        failure = store_failure(hermes_home)
        if failure is not None:
            notices.append(_store_notice(label, restart_command, failure))
    stale = _stale_bundle_times(hermes_home)
    if stale is not None:
        started_iso, installed_iso = stale
        notices.append(GatewayNotice(
            NOTICE_STALE_BUNDLE,
            f"{label} started before OMH was updated (last start {started_iso}, OMH plugin installed "
            f"{installed_iso}), so it still runs the old OMH plugin code; restarting it with `{restart_command}` "
            "loads the new code, restarts every bot it serves and first waits for their running turns.",
            restart_command,
            f"run `{restart_command}` when a restart suits the bots it serves; OMH does not restart it",
        ))
    return notices


def gateway_session_store_status(hermes_home: Path, *, now: float | None = None) -> str | None:
    """`session_store.status` from a fresh record of the gateway running in this home, or None.

    This is Hermes' one aggregate over every store the gateway holds, kept
    across a restart until the new process publishes its own, so it is never
    said on its own: `store_failure` corroborates it.
    """
    record = _running_gateway_record(hermes_home, time.time() if now is None else now)
    return None if record is None else _store_status(record)


def store_failure(hermes_home: Path) -> StoreFailure | None:
    """The newest store failure in the tail of Hermes' error log, logged after the gateway's last recorded start.

    None without a recorded start, without such a line, or when the newest
    one predates the start: a restart's new process inherits the old one's
    `unavailable` until it publishes its own, so only a failure of this
    process is evidence.
    """
    last_start = _last_gateway_start(hermes_home / GATEWAY_STARTS_FILENAME)
    if last_start is None:
        return None
    for line in reversed(_tail_text(hermes_home / GATEWAY_ERROR_LOG, STORE_LOG_TAIL_BYTES).splitlines()):
        failure = _store_failure_line(line)
        if failure is None:
            continue
        logged = _log_epoch(failure.logged)
        return failure if logged is not None and logged > last_start else None
    return None


def gateway_drain(hermes_home: Path, *, now: float | None = None) -> GatewayDrain | None:
    """The drain of the gateway running in this home, or None when a fresh record does not say `draining`."""
    moment = time.time() if now is None else now
    record = _running_gateway_record(hermes_home, moment)
    return None if record is None else _drain(hermes_home, record, moment)


def _store_status(record: dict[str, object]) -> str | None:
    store = record.get("session_store")
    status = store.get("status") if isinstance(store, dict) else None
    return status if isinstance(status, str) and status else None


def _store_failure_line(line: str) -> StoreFailure | None:
    if (match := _MISSING_PROFILE.match(line)) is not None:
        home = match["home"].strip()
        return StoreFailure(NOTICE_DELETED_PROFILE_STORE, match["stamp"], "", Path(home).name, home)
    if (match := _NOT_SERVED.match(line)) is not None:
        return StoreFailure(NOTICE_PROFILE_NOT_SERVED, match["stamp"], "", match["name"], match["home"].strip())
    for pattern in (_REPLACED, _UNNAMED):
        if (match := pattern.match(line)) is not None:
            return StoreFailure(NOTICE_STORE_UNAVAILABLE, match["stamp"], match["what"])
    return None


def _store_notice(label: str, restart_command: str, failure: StoreFailure) -> GatewayNotice:
    if failure.kind == NOTICE_DELETED_PROFILE_STORE:
        return GatewayNotice(
            failure.kind,
            f"{label} reports its session store unavailable: a deleted profile `{failure.profile}` is still "
            f"referenced in Hermes (a cron job, a kanban board or a served profile; Hermes logged \"Named profile "
            f"home does not exist\" at {failure.logged}). Your own sessions are unaffected. Remove that reference "
            "or recreate the profile; a restart does not clear it.",
            "",
            f"remove what still names profile `{failure.profile}` (a cron job, a kanban board or a served profile) "
            f"or recreate it with `hermes profile create {failure.profile}`; a restart does not clear it, and OMH "
            "changes nothing",
        )
    if failure.kind == NOTICE_PROFILE_NOT_SERVED:
        return GatewayNotice(
            failure.kind,
            f"{label} does not serve profile `{failure.profile}`: Hermes logged its session store as unusable at "
            f"{failure.logged} ({failure.home}). The other profiles' sessions are unaffected.",
            "",
            f"check the store under `{failure.home}`; Hermes' `logs/gateway.error.log` names why it did not "
            "open. OMH changes nothing",
        )
    return GatewayNotice(
        failure.kind,
        f"{label} cannot write a session store it holds (Hermes logged \"{failure.what}\" at {failure.logged}). "
        f"Restarting it with `{restart_command}` reopens its stores; that restarts every bot it serves and first "
        "waits for their running turns.",
        restart_command,
        f"run `{restart_command}` when a restart suits the bots it serves; OMH does not restart it",
    )


def _drain(hermes_home: Path, record: dict[str, object], now: float) -> GatewayDrain | None:
    if record.get("gateway_state") != GATEWAY_DRAINING:
        return None
    if record.get("restart_requested") is True:
        reason = DRAIN_RESTART
    elif _regular_file(hermes_home / DRAIN_REQUEST_FILENAME):
        reason = DRAIN_REQUEST
    else:
        reason = DRAIN_STOPPING
    wait = _fresh_wait_line(hermes_home / GATEWAY_LOG, now) if reason == DRAIN_RESTART else None
    turns = wait[0] if wait is not None else _awaited_units(record)
    return GatewayDrain(reason, turns, wait[1] if wait is not None else None)


def _awaited_units(record: dict[str, object]) -> int | None:
    """The units a drain waits for: `active_work` without the wedged and restart-safe ones Hermes' wait excludes."""
    work = record.get("active_work")
    if isinstance(work, list):
        awaited = sum(
            1 for unit in work
            if not (isinstance(unit, dict) and (unit.get("wedged") is True or unit.get("restart_safe") is True))
        )
        return awaited or None
    agents = record.get("active_agents")
    return agents if isinstance(agents, int) and not isinstance(agents, bool) and agents > 0 else None


def _drain_notice(hermes_home: Path, label: str, drain: GatewayDrain) -> GatewayNotice:
    if drain.turns is None:
        turns = "its running turns"
    else:
        turns = f"{drain.turns} running turn{'' if drain.turns == 1 else 's'}"
    held = "Hermes holds or refuses new messages as `runtime_draining`"
    if drain.reason == DRAIN_REQUEST:
        request = hermes_home / DRAIN_REQUEST_FILENAME
        return GatewayNotice(
            NOTICE_DRAINING,
            f"{label} is paused for new turns by a drain request (`{request}`) and keeps running: it lets {turns} "
            f"finish and does not start new turns until the request is removed or expires; {held}.",
            "",
            f"it takes new turns again once `{request}` is removed or expires; OMH does not touch it",
        )
    left = (
        f" (about {drain.seconds_left}s left before it stops them anyway)" if drain.seconds_left is not None else ""
    )
    if drain.reason == DRAIN_RESTART:
        return GatewayNotice(
            NOTICE_DRAINING,
            f"{label} is restarting: it waits for {turns} to finish first{left}, and does not start new turns until "
            f"it is done; {held}. Hermes caps the wait with `{RESTART_WAIT_KNOB}`.",
            "",
            f"wait for it to finish; the wait is capped by `{RESTART_WAIT_KNOB}`. OMH does not stop or restart it",
        )
    return GatewayNotice(
        NOTICE_DRAINING,
        f"{label} is stopping: it waits for {turns} to finish first, and does not start new turns until it is "
        f"done; {held}.",
        "",
        "wait for it to stop; OMH does not stop or restart it",
    )


def _fresh_wait_line(log_path: Path, now: float) -> tuple[int, int] | None:
    """The units and seconds left in the newest restart-wait line of Hermes' gateway log, the seconds aged to `now`.

    None unless that line is under `DRAIN_LOG_FRESH_SECONDS` old. The stamp is
    read in this process's local time, as Hermes' logging wrote it in the
    gateway's: a different `TZ` makes the age wrong by hours, and the line
    reads as stale rather than as a wrong count.
    """
    tail = _tail_text(log_path, DRAIN_LOG_TAIL_BYTES)
    match = next((found for line in reversed(tail.splitlines()) if (found := _WAIT_LINE.match(line))), None)
    if match is None:
        return None
    logged = _log_epoch(match["stamp"])
    if logged is None:
        return None
    age = now - logged
    if not 0 <= age <= DRAIN_LOG_FRESH_SECONDS:
        return None
    return int(match["units"]), max(0, round(int(match["left"]) - age))


def _running_gateway_record(hermes_home: Path, now: float) -> dict[str, object] | None:
    """`gateway_state.json` when every file agrees its gateway runs in this home now, else None.

    `gateway.pid` names the home (Hermes unlinks it on a clean stop), the
    record names the same home and pid, its `gateway_state` is not one Hermes
    reads as gone, and its `updated_at` is within Hermes' own staleness bound:
    a record no one re-stamps outlived its writer.
    """
    pid_record = _home_pid_record(hermes_home)
    if pid_record is None:
        return None
    record = _bounded_json_object(hermes_home / GATEWAY_STATE_FILENAME, GATEWAY_STATE_BYTES)
    if record is None:
        return None
    recorded_home = record.get("hermes_home")
    if isinstance(recorded_home, str) and recorded_home.strip() and not _same_home(recorded_home, hermes_home):
        return None
    pids = (pid_record.get("pid"), record.get("pid"))
    if all(isinstance(pid, int) and not isinstance(pid, bool) for pid in pids) and pids[0] != pids[1]:
        return None
    state = record.get("gateway_state")
    if state is None or state in _GATEWAY_GONE_STATES:
        return None
    if state == "degraded" and record.get("exit_reason") in _WATCHDOG_EXIT_REASONS:
        return None
    updated = _iso_epoch(record.get("updated_at"))
    if updated is None or abs(now - updated) > RUNTIME_STATUS_STALE_SECONDS:
        return None
    return record


def _stale_bundle_times(hermes_home: Path) -> tuple[str, str] | None:
    """The last recorded gateway start and the bundle's install, as UTC stamps, when the start is the earlier."""
    if not _pid_record_names_home(hermes_home):
        return None
    last_start = _last_gateway_start(hermes_home / GATEWAY_STARTS_FILENAME)
    if last_start is None:
        return None
    plugin_dir = hermes_home / "plugins" / "omh"
    manifest = read_plugin_manifest(plugin_dir) if _regular_file(plugin_dir / PLUGIN_MANAGED_MANIFEST) else None
    installed_at = _installed_at_epoch(manifest)
    if installed_at is None or last_start >= installed_at:
        return None
    started_iso = _iso_utc(last_start)
    installed_iso = _iso_utc(installed_at)
    if started_iso is None or installed_iso is None:
        return None
    return started_iso, installed_iso


def _regular_file(path: Path) -> bool:
    """Whether `path` is a regular file: a FIFO or a device would block, or never end, the read that opens it."""
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except (OSError, ValueError):
        return False


def _bounded_json_object(path: Path, limit: int) -> dict[str, object] | None:
    if not _regular_file(path):
        return None
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            return None
        data = json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _tail_text(path: Path, limit: int) -> str:
    """The last `limit` bytes of a regular file as text, undecodable bytes replaced; "" when it cannot be read."""
    if not _regular_file(path):
        return ""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - limit))
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _log_epoch(stamp: str) -> float | None:
    try:
        return datetime.strptime(stamp, _LOG_STAMP_FORMAT).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _pid_record_names_home(hermes_home: Path) -> bool:
    return _home_pid_record(hermes_home) is not None


def _home_pid_record(hermes_home: Path) -> dict[str, object] | None:
    """The `gateway.pid` record when it is this home's, else None."""
    record = _bounded_json_object(hermes_home / GATEWAY_PID_FILENAME, PID_RECORD_BYTES)
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
    """The latest wall-clock start in the ledger's tail, or None when no line is one.

    Only a finite, positive number is a start: `nan`, `inf`, a negative value
    or bytes that are not UTF-8 are a ledger Hermes did not write, and the
    hint stays silent rather than raising out of `omh update`. A line the tail
    cut through reads as a smaller number than the one it was, never a later
    start.
    """
    if not _regular_file(path):
        return None
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - LEDGER_TAIL_BYTES))
            lines = handle.read(LEDGER_TAIL_BYTES).decode("utf-8").splitlines()
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
    return _iso_epoch(manifest.get("installed_at"))


def _iso_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        # Hermes writes `updated_at`; 3.14 would read T24:00:00 as the next midnight (`iso_datetime`).
        parsed = strict_fromisoformat(value.strip().replace("Z", "+00:00"))
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
