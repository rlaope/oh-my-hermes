"""This machine's Hermes gateways as `omh doctor` reports them: fleet against build, fleet shape, adapter states.

Read-only and deterministic: no network call, no LLM, no Hermes import, and
nothing is stopped, restarted or written. Three questions, each answered only
from what was read, and each absence said as one:

1. Fleet against build. Every running gateway: the ones Hermes' own records
   name (`<home>/gateway_state.json`, read by the bot board's `read_gateway`,
   whose liveness check ties the record's pid to the process that wrote it),
   plus every `hermes gateway run` the kernel's process table shows
   (`system.process_listing`, read without spawning a process). Each start
   is compared with the installed Hermes build stamp; a record that stamps the
   commit it runs (`code_sha`) is believed over the start time. Hermes' own
   pending-fleet-restart record and its latest update receipt are read beside
   it (`hermes_gateway_formats.read_fleet_restart_state`).
2. Fleet shape. Gateway processes no record under this Hermes root names,
   and a profile two recorded gateways both serve, by PID.
3. Messaging adapters. Per profile and platform, the newest state the gateway
   logs record (`hermes_gateway_formats.read_gateway_log`): a later
   "connected" supersedes an earlier failure and the reverse. A failure with
   a known reason gets its fix; an unknown one shows Hermes' reason text,
   bounded, as unrecognized.

The remedy is always Hermes' own command; OMH runs none of it. The readers
live here and in `hermes_gateway_formats`, not in the doctor command, so every
surface reads the same answer: `bot_platforms` is question 3 alone, per bot,
for the TUI bot board and for `omh hermes platforms` (which omher runs). It
carries only classified states, Hermes' bounded and cleaned reason and
guidance text, and the fix; never a log line.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
import os
from pathlib import Path
import time

from ..install.skill_registration import hermes_profile_dirs
from ..skin_pack import TUI_PROFILE
from ..system.hermes_install import hermes_install_dir
from ..system.process_listing import LAUNCH_SHAPES, GatewayListing, hermes_gateway_processes
from ..tui.bot_board import (
    ON_POSIX,
    PLATFORM_DISCONNECTED,
    PLATFORM_FAILED,
    PLATFORM_RECONNECTING,
    PLATFORM_UNKNOWN,
    BotPlatforms,
    Gateway,
    Platform,
    PlatformStatus,
    process_facts,
    read_gateway,
    started_at,
)
from .hermes_gateway_formats import (
    GATEWAY_LOG_RELATIVE,
    GATEWAY_LOG_TAIL_BYTES,
    REASON_NONE,
    REASON_PRIVILEGED_INTENTS,
    REASON_TOKEN_REJECTED,
    REASON_TRANSIENT,
    STATE_CONNECTED,
    STATE_DEGRADED,
    STATE_DISCONNECTED,
    STATE_FAILED,
    STATE_FATAL,
    STATE_RESERVED,
    STATE_RETRYING,
    STATUS_MISSING,
    STATUS_READ,
    STATUS_UNREADABLE,
    STATUS_UNRECOGNIZED,
    AMBIGUOUS_PROFILE,
    ATTEMPT_WINDOW_SECONDS,
    AdapterEvent,
    BuildStamp,
    FleetRestartState,
    LogRead,
    bounded_reason,
    classify_reason,
    iso_utc,
    read_build_stamp,
    strip_controls,
    read_fleet_restart_state,
    read_gateway_log,
)

GATEWAY_HEALTH_SCHEMA = "omh_gateway_health/v1"
BOT_PLATFORMS_SCHEMA = "omh_bot_platforms/v1"
DEFAULT_PROFILE = "default"
BUILD_CURRENT = "current"
BUILD_BEFORE = "started_before_build"
BUILD_OTHER_COMMIT = "other_commit"
BUILD_UNKNOWN = "unknown"
FINDING_STALE_GATEWAY = "gateway_older_than_build"
FINDING_PENDING_RESTART = "hermes_pending_fleet_restart"
FINDING_INCOMPLETE_RESTART = "hermes_restart_incomplete"
FINDING_UNRECORDED = "unrecorded_gateway_process"  # its build and its home are unknown: never counted as stale
# An idle-exit gateway still running after this long is reported as a stray: six times Hermes' documented default
# `gateway.unmanaged_idle_exit_seconds` (600 s), since the value its own launch home sets cannot be read from here.
IDLE_EXIT_STALE_SECONDS = 3600
FINDING_SHARED_PROFILE = "profile_served_twice"
FINDING_ADAPTER_DOWN = "adapter_not_connected"
STATE_STALE = "no_line_this_run"  # every adapter line for it predates the start of the gateway serving it
STATE_UNSERVED = "not_served"  # no running gateway serves its profile
SOURCE_RECORD = "record"  # the serving gateway's own `gateway_state.json` entry, stamped by that process
SOURCE_LOG = "log"
# States that are not a failure to report: Hermes connected it, or is reconnecting it on its own.
_NOT_DOWN = frozenset({STATE_CONNECTED, STATE_DEGRADED, STATE_RETRYING, STATE_DISCONNECTED, STATE_STALE, STATE_UNSERVED})
# The `platform_state` values Hermes writes into a record entry (`gateway/run_adapters.py`, `run_adapters_recovery.py`,
# `run_startup.py`), each mapped explicitly; a value outside these is said as unknown, never judged up or down.
RECORD_CONNECTING = frozenset({"connecting", "starting"})
RECORD_DISABLED = "disabled"  # a deliberate stand-down (config, `whatsapp_unpaired`, `multiplex_shared_ingress`)
RECORD_DOWN = frozenset({"fatal"})
RECORD_KNOWN = frozenset({STATE_CONNECTED, STATE_DEGRADED, STATE_RETRYING, RECORD_DISABLED, *RECORD_CONNECTING,
                          *RECORD_DOWN})
RESTART_NOTE = (
    "while turns are live Hermes asks before interrupting them, refuses when there is no terminal to ask on, "
    "and interrupts them only with `--yes`; OMH restarts nothing"
)
PORTAL_PATH = "the Discord Developer Portal, your application's Bot page, Privileged Gateway Intents"
# Discord's privileged intents, as Hermes' record names them (`… - Message Content Intent - Server Members Intent`).
PRIVILEGED_INTENTS = ("Message Content", "Server Members", "Presence")
GUIDANCE_CHARS = 600  # Hermes' guidance in a record entry runs longer than a log reason
# Why a platform's state is unknown now (`PlatformStatus.unknown_why`).
UNKNOWN_EARLIER_RUN = "earlier_run"  # its newest line predates the start of the gateway serving it
UNKNOWN_NOT_SERVED = "not_served"  # no running gateway serves its profile
UNKNOWN_AMBIGUOUS = "ambiguous"  # a failure the log cannot give to one of several profiles
UNKNOWN_STATE = "unknown_state"  # a record state this check does not know


@dataclass(frozen=True)
class GatewayProcess:
    pid: int
    profile: str  # the recording home's profile; for an unrecorded process, what its command line names ("" for none)
    recorded: bool
    home: str = ""
    started_at: str = ""
    serves: tuple[str, ...] = ()
    active_turns: int = 0
    code_sha: str = ""
    build: str = BUILD_UNKNOWN  # one of the BUILD_* names
    idle_exit: bool = False  # an unrecorded `gateway run --idle-exit`: a Hermes client's own start, which Hermes ends once idle
    overdue: bool = False  # an idle-exit gateway running longer than IDLE_EXIT_STALE_SECONDS: reported as a stray


@dataclass(frozen=True)
class AdapterState:
    profile: str
    platform: str
    state: str  # the record's state when it has a current entry, else the newest log line's; or STATE_STALE/UNSERVED
    logged: str  # the newest log line's time in UTC (its stamp read in this machine's local time), "" when none
    log: str
    reason: str = ""
    code: str = ""
    reason_kind: str = ""  # set only for a state that is down
    fix: str = ""
    source: str = SOURCE_LOG
    needs_attention: bool = False  # Hermes' own flag: it has retried long enough to want a person
    last_state: str = ""  # for STATE_STALE and STATE_UNSERVED: what the newest (older) line said
    gateway_started: str = ""  # when the gateway serving the profile started
    logged_as_written: str = ""  # the same line's stamp as Hermes wrote it, in the writing process's local time
    since: str = ""  # for a state that is not connected: the first line of this run saying so, none connected after
    restart: str = ""  # Hermes' command that restarts the gateway serving the profile ("" when none serves it)
    guidance: str = ""  # Hermes' own guidance in the serving gateway's record entry, bounded and cleaned
    intents: tuple[str, ...] = ()  # a privileged-intents refusal: the intents that guidance names
    re_served: str = ""  # for STATE_STALE: when Hermes served the profile again, which dropped that line's verdict


@dataclass(frozen=True)
class _Serving:
    """The running gateway that serves a profile: its own profile, its start, its current platform entries."""

    gateway_profile: str
    started: float | None
    platforms: dict[str, Platform]  # "profile:platform" -> the entry this process stamped


@dataclass(frozen=True)
class GatewayHealth:
    schema_version: str
    hermes_root: str
    install_found: bool
    build: dict[str, object]
    fleet_restart: dict[str, object]
    process_listing: str  # "observed", or "not_available" where the platform offers no listing
    gateways: tuple[GatewayProcess, ...]
    unverified_records: tuple[str, ...]  # homes whose record could not be checked against a process (off POSIX)
    shared_profiles: dict[str, list[int]]
    adapters: tuple[AdapterState, ...]
    logs: tuple[dict[str, object], ...]
    findings: tuple[str, ...]
    lines: tuple[str, ...]
    next_actions: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def hermes_root(hermes_home: Path) -> Path:
    """The root Hermes home: a profile home's grandparent, else the home itself."""
    return hermes_home.parent.parent if hermes_home.parent.name == "profiles" else hermes_home


def gateway_homes(root: Path) -> list[tuple[str, Path]]:
    """The root (`default`), each named bot profile, and the OMH TUI's own runtime profile when it exists."""
    homes = [(DEFAULT_PROFILE, root), *hermes_profile_dirs(root)]
    tui_home = root / "profiles" / TUI_PROFILE
    if tui_home.is_dir():
        homes.append((TUI_PROFILE, tui_home))
    return homes


def _process_start(pid: int) -> float | None:
    fingerprint, _zombie = process_facts(pid)
    return started_at(fingerprint, time.time()) if fingerprint is not None else None


def gateway_health(
    hermes_home: Path,
    *,
    environ: Mapping[str, str] | None = None,
    gateway_reader: Callable[[Path], Gateway] = read_gateway,
    list_processes: Callable[[], GatewayListing] = hermes_gateway_processes,
    process_start: Callable[[int], float | None] = _process_start,
    log_tail_bytes: int = GATEWAY_LOG_TAIL_BYTES,
    now: Callable[[], float] | None = None,  # the clock an idle-exit gateway's age is read against; None: `time.time`
) -> GatewayHealth:
    root = hermes_root(hermes_home)
    install_dir = hermes_install_dir(root)
    install_found = install_dir.is_dir()
    build = read_build_stamp(install_dir) if install_found else BuildStamp(STATUS_MISSING, str(install_dir))
    restart = read_fleet_restart_state(root, install_dir, os.environ if environ is None else environ)
    homes = gateway_homes(root)
    recorded, unverified, serving = _recorded_gateways(homes, gateway_reader, build)
    listing = list_processes()
    listed_ok, listed = listing.listed, listing.gateways
    recorded_pids = {process.pid for process in recorded}
    clock = time.time if now is None else now
    unrecorded = []
    for pid, profile in listed:
        if pid in recorded_pids:
            continue
        started = process_start(pid)
        idle_exit = pid in listing.idle_exit
        overdue = idle_exit and started is not None and clock() - started > IDLE_EXIT_STALE_SECONDS
        unrecorded.append(GatewayProcess(pid, profile, False, started_at=iso_utc(started),
                                         build=_build_verdict(build, "", started), idle_exit=idle_exit, overdue=overdue))
    shared = _shared_profiles(recorded)
    logs, adapters = _adapter_states(homes, serving, log_tail_bytes)
    gateways = (*recorded, *unrecorded)
    findings = _findings(gateways, restart, shared, adapters)
    lines, actions = _report(root, install_found, install_dir, build, restart, listing, recorded, unrecorded,
                             unverified, shared, adapters, logs, homes, serving)
    return GatewayHealth(
        GATEWAY_HEALTH_SCHEMA, str(root), install_found, asdict(build), asdict(restart),
        "observed" if listed_ok else "not_available", gateways, tuple(unverified), shared, tuple(adapters),
        tuple(asdict(log) | {"events": len(log.events)} for log in logs), findings, tuple(lines), tuple(actions),
    )


def bot_platforms(
    hermes_home: Path,
    *,
    gateway_reader: Callable[[Path], Gateway] = read_gateway,
    log_tail_bytes: int = GATEWAY_LOG_TAIL_BYTES,
    log_reader: Callable[[Path, int], LogRead] | None = None,
) -> tuple[BotPlatforms, ...]:
    """Question 3 alone, per bot: each profile's messaging platforms as `gateway_health` judges them, for the TUI bot
    board and `omh hermes platforms`. It reads the gateway records and the gateway log tails only (no process listing,
    no build stamp), and each platform comes back as one status with its reason and fix, never a log line.

    A platform the log cannot give to one of several profiles is `unknown` for each of them that has no state of its
    own; one whose every candidate's record says it is up is history and not listed. A profile with no platform in its
    serving gateway's record and no adapter line has an empty list: nothing to show, which is not "connected". Its
    `log` says whether that empty list can be believed: the worse of its own log and the root's, where a served bot's
    lines also land (`unreadable` or `unrecognized` over `read` or `missing`). `log_reader` (path, tail bytes) lets a
    caller that reads often keep a `LogCache`.
    """
    root = hermes_root(hermes_home)
    homes = gateway_homes(root)
    _recorded, _unverified, serving = _recorded_gateways(homes, gateway_reader, BuildStamp(STATUS_MISSING, ""))
    logs, adapters = _adapter_states(homes, serving, log_tail_bytes, log_reader)
    by_profile: dict[str, dict[str, PlatformStatus]] = {label: {} for label, _home in homes}
    unowned: list[AdapterState] = []
    for state in adapters:
        if state.state == STATE_STALE and state.re_served:
            continue  # Hermes dropped the verdict when it served the bot again: a removed platform shows nothing
        if state.last_state == AMBIGUOUS_PROFILE:
            unowned.append(state)
        else:
            by_profile.setdefault(state.profile, {})[state.platform] = _platform_status(state)
    for state in unowned:
        if state.source == SOURCE_RECORD:
            continue  # every candidate's own record says it is up now
        for name in state.profile.split("/"):
            by_profile.setdefault(name, {}).setdefault(state.platform, _platform_status(state))
    own = {label: log.status for (label, _home), log in zip(homes, logs, strict=True)}
    unread = (STATUS_UNREADABLE, STATUS_UNRECOGNIZED)
    root_bad = own.get(DEFAULT_PROFILE) if own.get(DEFAULT_PROFILE) in unread else None
    log_status = {label: status if status in unread else root_bad or status for label, status in own.items()}
    return tuple(
        BotPlatforms(name, log_status.get(name, STATUS_MISSING), tuple(platforms[key] for key in sorted(platforms)))
        for name, platforms in by_profile.items()
    )


def bot_platforms_payload(hermes_home: Path) -> dict[str, object]:
    """`omh hermes platforms`: `bot_platforms` as `omh_bot_platforms/v1` JSON."""
    return {"schema_version": BOT_PLATFORMS_SCHEMA, "bots": [asdict(bot) for bot in bot_platforms(hermes_home)]}


def _platform_status(state: AdapterState) -> PlatformStatus:
    """One adapter state as a surface shows it. Not connected only when known so; every state this check cannot
    place now (an earlier run's line, an unserved profile, an unattributable failure, a record state it does not
    know) is `unknown`, never connected and never disconnected."""
    unknown_why = ""
    if state.last_state == AMBIGUOUS_PROFILE:
        status, unknown_why = PLATFORM_UNKNOWN, UNKNOWN_AMBIGUOUS
    elif state.state == STATE_STALE:
        status, unknown_why = PLATFORM_UNKNOWN, UNKNOWN_EARLIER_RUN
    elif state.state == STATE_UNSERVED:
        status, unknown_why = PLATFORM_UNKNOWN, UNKNOWN_NOT_SERVED
    elif state.source == SOURCE_RECORD and state.state in RECORD_CONNECTING:
        status = "connecting"
    elif state.source == SOURCE_RECORD and state.state == RECORD_DISABLED:
        status = "disabled"
    elif state.source == SOURCE_RECORD and state.state not in RECORD_KNOWN:
        status, unknown_why = PLATFORM_UNKNOWN, UNKNOWN_STATE
    elif state.state in {STATE_CONNECTED, STATE_DEGRADED}:
        status = state.state
    elif state.state == STATE_RETRYING or (state.reason_kind == REASON_TRANSIENT and not state.needs_attention):
        status = PLATFORM_RECONNECTING
    elif state.state == STATE_FAILED:
        status = PLATFORM_FAILED
    elif state.state in {STATE_FATAL, STATE_DISCONNECTED}:
        status = PLATFORM_DISCONNECTED
    else:
        status, unknown_why = PLATFORM_UNKNOWN, UNKNOWN_STATE
    up = status in {STATE_CONNECTED, STATE_DEGRADED}
    clean = strip_controls  # every string leaves on one line, with no escape, control or format character
    return PlatformStatus(
        state.platform, status, _adapter_down(state) and not unknown_why, "" if up else clean(state.since),
        clean(state.logged), state.reason_kind, clean(state.reason), clean(state.guidance), clean(state.fix),
        clean(state.restart), state.intents, unknown_why,
    )


def _recorded_gateways(
    homes: list[tuple[str, Path]], gateway_reader: Callable[[Path], Gateway], build: BuildStamp
) -> tuple[list[GatewayProcess], list[str], dict[str, _Serving]]:
    recorded: list[GatewayProcess] = []
    unverified: list[str] = []
    serving: dict[str, _Serving] = {}
    for label, home in homes:
        gateway = gateway_reader(home)
        if gateway.problem or gateway.elsewhere:
            continue
        if not gateway.live:
            if not ON_POSIX and gateway.state not in {"stopped", "startup_failed", ""}:
                unverified.append(label)
            continue
        serves = tuple(dict.fromkeys((label, *gateway.served)))
        current = {
            platform.name if ":" in platform.name else f"{label}:{platform.name}": platform
            for platform in gateway.platforms if platform.current
        }
        for profile in serves:
            serving[profile] = _Serving(label, gateway.started, current)
        recorded.append(GatewayProcess(
            gateway.pid or 0, label, True, str(home), iso_utc(gateway.started), serves, gateway.active_agents,
            gateway.code_sha, _build_verdict(build, gateway.code_sha, gateway.started),
        ))
    return recorded, unverified, serving


def _build_verdict(build: BuildStamp, code_sha: str, started: float | None) -> str:
    """Whether a gateway runs the installed build: its own commit stamp first, else its start against `builtAt`."""
    if build.status != STATUS_READ:
        return BUILD_UNKNOWN
    if code_sha and build.commit:
        same = build.commit.startswith(code_sha) or code_sha.startswith(build.commit)  # either may be the short one
        return BUILD_CURRENT if same else BUILD_OTHER_COMMIT
    if started is None or build.built_at is None:
        return BUILD_UNKNOWN
    return BUILD_BEFORE if started < build.built_at else BUILD_CURRENT


def _shared_profiles(recorded: list[GatewayProcess]) -> dict[str, list[int]]:
    by_profile: dict[str, list[int]] = {}
    for process in recorded:
        for profile in process.serves:
            by_profile.setdefault(profile, []).append(process.pid)
    return {profile: pids for profile, pids in sorted(by_profile.items()) if len(pids) > 1}


def _adapter_states(
    homes: list[tuple[str, Path]], serving: dict[str, _Serving], tail_bytes: int,
    log_reader: Callable[[Path, int], LogRead] | None = None,
) -> tuple[list[LogRead], list[AdapterState]]:
    """Per profile and platform: the serving gateway's own current record entry first, else the newest log line of
    this gateway run. A line from before the serving gateway started, from before the profile was last served again,
    or for a profile no running gateway serves, is said as such and never as the state now."""
    log_reader = log_reader or (lambda path, tail: read_gateway_log(path, tail_bytes=tail))
    logs = [log_reader(home / GATEWAY_LOG_RELATIVE, tail_bytes) for _label, home in homes]
    # A profile served again starts a run of its own: its adapter lines from before that attempt say nothing about now.
    reserved: dict[str, float] = {}
    for log in logs:
        for event in log.events:
            if event.state == STATE_RESERVED and event.epoch is not None:
                reserved[event.profile] = max(event.epoch, reserved.get(event.profile, event.epoch))
    latest: dict[tuple[str, str], tuple[AdapterEvent, str, AdapterEvent | None]] = {}
    ambiguous: list[AdapterState] = []
    for (label, _home), log in zip(homes, logs, strict=True):
        newest_here: dict[tuple[str, str], AdapterEvent] = {}
        outage_here: dict[tuple[str, str], AdapterEvent] = {}  # the first line of this run not followed by a connect
        unowned: dict[str, AdapterEvent] = {}
        for event in log.events:  # within one log, the line written last wins, whatever its stamp says
            if event.state == STATE_RESERVED:
                continue
            if event.profile == AMBIGUOUS_PROFILE:
                unowned[event.platform] = event
                continue
            key = (event.profile or label, event.platform)
            newest_here[key] = event
            if event.state in {STATE_CONNECTED, STATE_DEGRADED}:
                outage_here.pop(key, None)
            elif _in_run(event, serving.get(key[0]), reserved.get(key[0])):
                outage_here.setdefault(key, event)
        ambiguous.extend(_ambiguous_state(event, log.path, serving) for event in unowned.values())
        for key, event in newest_here.items():  # across logs, the stamps decide
            held = latest.get(key)
            if held is None or (event.epoch or 0.0) >= (held[0].epoch or 0.0):
                latest[key] = (event, log.path, outage_here.get(key))
    keys = set(latest)
    for info in serving.values():
        keys.update(tuple(key.split(":", 1)) for key in info.platforms)  # type: ignore[misc]
    states = []
    for profile, platform in sorted(keys):
        info = serving.get(profile)
        event, log_path, first = latest.get((profile, platform), (None, "", None))
        if info is None:
            if event is not None:
                states.append(AdapterState(profile, platform, STATE_UNSERVED, _utc(event), log_path,
                                           last_state=event.state, logged_as_written=event.logged))
            continue
        record = info.platforms.get(f"{profile}:{platform}")
        this_run = event is not None and _in_run(event, info, reserved.get(profile))
        restart = _restart_command(info.gateway_profile)
        started = iso_utc(info.started)
        if record is None and not this_run:
            if event is not None:
                # in this gateway's run, but from before Hermes served the profile again: that verdict was dropped
                again = iso_utc(reserved.get(profile)) if _in_run(event, info) else ""
                states.append(AdapterState(profile, platform, STATE_STALE, _utc(event), log_path,
                                           last_state=event.state, gateway_started=started,
                                           logged_as_written=event.logged, restart=restart, re_served=again))
            continue
        current = event if this_run else None
        state = _adapter_state(profile, platform, current, log_path, record, restart, started)
        if state.state not in {STATE_CONNECTED, STATE_DEGRADED} and first is not None and current is not None:
            state = replace(state, since=_utc(first))
        states.append(state)
    return logs, states + [state for state in ambiguous if state.reason_kind or state.source == SOURCE_RECORD]


def _in_run(event: AdapterEvent, info: _Serving | None, reserved: float | None = None) -> bool:
    """Whether a line falls in the run of the gateway serving its profile (a line with no readable stamp does) and,
    when the profile was served again since (`reserved`), in that attempt: logged at most ATTEMPT_WINDOW_SECONDS
    before Hermes said so, or after."""
    if info is None:
        return False
    if event.epoch is None:
        return True
    if info.started is not None and event.epoch < info.started - 1:
        return False
    return reserved is None or event.epoch >= reserved - ATTEMPT_WINDOW_SECONDS


def _ambiguous_state(event: AdapterEvent, log_path: str, serving: dict[str, _Serving]) -> AdapterState:
    """A reason the log cannot give one profile: said for the platform, naming the candidates; judged only when it
    falls in the run of a gateway serving them (else it says nothing about now and is left out)."""
    info = next((serving[name] for name in event.candidates if name in serving), None)
    this_run = _in_run(event, info)
    entries = [serving[name].platforms.get(f"{name}:{event.platform}") if name in serving else None
               for name in event.candidates]
    # Every candidate's own current record entry says it is up: the line is history, not a finding.
    all_up = all(entry is not None and entry.state in {STATE_CONNECTED, STATE_DEGRADED} for entry in entries)
    kind = classify_reason(event) if this_run and not all_up else ""
    restart = _restart_command(info.gateway_profile if info is not None else DEFAULT_PROFILE)
    fix = _adapter_fix(kind, event, log_path, restart, "") if kind else ""
    return AdapterState(
        "/".join(event.candidates), event.platform, event.state, _utc(event), log_path, event.reason, event.code,
        kind, fix, SOURCE_RECORD if this_run and all_up else SOURCE_LOG, logged_as_written=event.logged,
        last_state=AMBIGUOUS_PROFILE, since=_utc(event), restart=restart if info is not None else "",
    )


def _adapter_state(
    profile: str, platform: str, event: AdapterEvent | None, log_path: str, record: Platform | None, restart: str,
    started: str,
) -> AdapterState:
    if record is not None:
        state = record.state
        failed_line = event is not None and event.state not in _NOT_DOWN and event.reason
        reason = event.reason if failed_line and event is not None else bounded_reason(record.error)
        code = record.code or (event.code if event is not None else "")
    elif event is not None:
        state, reason, code = event.state, event.reason, event.code
    else:
        state, reason, code = STATE_STALE, "", ""  # unreachable: the caller passes a record or a line of this run
    logged = event.logged if event is not None else ""
    if record is not None:
        down = state in RECORD_DOWN or (state == STATE_RETRYING and record.needs_attention)
    else:
        down = state not in _NOT_DOWN
    probe = AdapterEvent(profile, platform, state, logged, None, reason, code)
    kind = classify_reason(probe) if down else ""
    record_error = record.error if record else ""
    fix = _adapter_fix(kind, probe, log_path, restart, record_error,
                       record is not None and record.needs_attention) if kind else ""
    intents = tuple(name for name in PRIVILEGED_INTENTS if f"{name} Intent" in record_error) \
        if kind == REASON_PRIVILEGED_INTENTS else ()
    return AdapterState(
        profile, platform, state, _utc(event) if event is not None else "", log_path, reason, code, kind, fix,
        SOURCE_RECORD if record is not None else SOURCE_LOG, record is not None and record.needs_attention,
        gateway_started=started, logged_as_written=logged, restart=restart,
        guidance=bounded_reason(record_error, GUIDANCE_CHARS) if record_error else "", intents=intents,
    )


def _utc(event: AdapterEvent) -> str:
    return iso_utc(event.epoch) or f"{event.logged} (local time)"


def _restart_command(gateway_profile: str) -> str:
    """Hermes' restart of one gateway process, its profile always named: a bare `hermes gateway restart` follows
    Hermes' sticky active profile (`hermes profile use`), which may name a served bot rather than the host. omher's
    Restart (BOUNDARY rule 29) names it the same way."""
    return f"hermes -p {gateway_profile} gateway restart"


def _shown_log(log_path: str) -> str:
    """A gateway log as a fix names it, never with a user's home folder spelled out: `~/…` under it, else from the
    Hermes root (`<Hermes root>/profiles/<name>/logs/gateway.log`)."""
    if not log_path:
        return ""
    path = Path(log_path)
    try:
        user = Path.home()
        pairs = ((path, user), (path.resolve(), user.resolve()))  # a resolved Hermes home under a linked one (/var)
    except (RuntimeError, OSError):
        pairs = ()
    for candidate, base in pairs:
        if candidate.is_relative_to(base):
            return "~/" + candidate.relative_to(base).as_posix()
    home = path.parent.parent
    inside = f"profiles/{home.name}/" if home.parent.name == "profiles" else ""
    return f"<Hermes root>/{inside}{GATEWAY_LOG_RELATIVE.as_posix()}"


def _adapter_fix(
    kind: str, event: AdapterEvent, log_path: str, restart: str, record_error: str, needs_attention: bool = False
) -> str:
    log_path = _shown_log(log_path)
    if kind == REASON_PRIVILEGED_INTENTS:
        # Hermes' own guidance in the record names Server Members only when the adapter requested it
        # (`_needs_server_members_intent`: a role allowlist, or a user allowlist entry that is not a numeric id or `*`).
        intents = (
            "Message Content and Server Members"
            if "Server Members Intent" in record_error
            else "Message Content, and Server Members too when the profile has a role allowlist "
            "(`DISCORD_ALLOWED_ROLES`, or `allowed_roles` in its Discord config) or a username rather than a numeric "
            "id in its user allowlist (`DISCORD_ALLOWED_USERS`, or `allow_from`/`allowed_users` in its Discord config)"
        )
        return (
            f"Discord refused the bot's privileged gateway intents; Hermes requests {intents}. Enable them in "
            f"{PORTAL_PATH}, and save (or remove the allowlist that needs Server Members). Hermes does not retry "
            f"this failure on its own: restart the gateway afterwards with `{restart}`."
        )
    if kind == REASON_TOKEN_REJECTED:
        return (
            "Discord rejected the bot token: reset it in the Discord Developer Portal (your application's Bot page) "
            f"and put the new one in the profile's `DISCORD_BOT_TOKEN`, then `{restart}`."
        )
    if kind == REASON_TRANSIENT and not needs_attention:
        return f"Hermes retries `{event.code}` on its own; nothing says it reconnected yet."
    if kind == REASON_TRANSIENT:
        return (f"Hermes has retried `{event.code}` long enough to flag it as needing attention; "
                f"read its log ({log_path or 'the gateway log'}), then `{restart}` if it stays down.")
    where = f"around {event.logged} in {log_path}" if event.logged and log_path else "in the gateway log"
    if kind == REASON_NONE:
        return f"no reason this check recognizes was recorded with it; read the lines {where}."
    return f"unrecognized reason (Hermes recorded: {event.reason or bounded_reason(event.code)}); read the lines {where}."


def _findings(
    gateways: tuple[GatewayProcess, ...],
    restart: FleetRestartState,
    shared: dict[str, list[int]],
    adapters: list[AdapterState],
) -> tuple[str, ...]:
    found: list[str] = []
    if any(process.recorded and process.build in {BUILD_BEFORE, BUILD_OTHER_COMMIT} for process in gateways):
        found.append(FINDING_STALE_GATEWAY)
    if restart.obligation:
        found.append(FINDING_PENDING_RESTART)
    if restart.restart_incomplete or restart.phase_error or restart.stale_fleet:
        found.append(FINDING_INCOMPLETE_RESTART)
    if any(not process.recorded and _stray(process) for process in gateways):
        found.append(FINDING_UNRECORDED)
    if shared:
        found.append(FINDING_SHARED_PROFILE)
    if any(_adapter_down(state) for state in adapters):
        found.append(FINDING_ADAPTER_DOWN)
    return tuple(found)


def _report(
    root: Path,
    install_found: bool,
    install_dir: Path,
    build: BuildStamp,
    restart: FleetRestartState,
    listing: GatewayListing,
    recorded: list[GatewayProcess],
    unrecorded: list[GatewayProcess],
    unverified: list[str],
    shared: dict[str, list[int]],
    adapters: list[AdapterState],
    logs: list[LogRead],
    homes: list[tuple[str, Path]],
    serving: dict[str, _Serving],
) -> tuple[list[str], list[str]]:
    listed_ok = listing.listed
    lines: list[str] = []
    actions: list[str] = []
    built = iso_utc(build.built_at)
    if not install_found:
        lines.append(f"Hermes install not found at {install_dir}; gateway starts are not compared with a build.")
    elif build.status == STATUS_MISSING:
        lines.append(f"no Hermes build stamp at {build.path}; gateway starts are not compared with a build.")
    elif build.status == STATUS_UNRECOGNIZED:
        lines.append(f"the Hermes build stamp {build.path} is not in a shape this check reads (no `builtAt`); "
                     "gateway starts are not compared with a build.")
    else:
        lines.append(f"installed Hermes build: {built}" + (f", commit {build.commit[:8]}" if build.commit else "") + ".")
    lines.extend(_restart_lines(restart))
    if restart.obligation or restart.restart_incomplete or restart.phase_error or restart.stale_fleet:
        actions.append(f"restart the gateways with Hermes' own `hermes gateway restart`; {RESTART_NOTE}")
    for process in recorded:
        lines.append(_recorded_line(process, built))
        if process.build in {BUILD_BEFORE, BUILD_OTHER_COMMIT}:
            command = _restart_command(process.profile)
            turns = f" ({process.active_turns} turn(s) live now)" if process.active_turns else ""
            actions.append(f"restart PID {process.pid}{turns} with `{command}`; {RESTART_NOTE}")
    for process in unrecorded:
        lines.append(_unrecorded_line(process, built, recorded))
    strays = [process for process in unrecorded if _stray(process)]
    if strays:
        pids = ", ".join(str(process.pid) for process in strays)
        actions.append(
            f"find what started PID {pids}: a gateway of another Hermes home (a scratch or test home) or one left "
            "running. Stop it from the home that started it with `hermes gateway stop`, or end that process; "
            "OMH stops nothing"
        )
    for label in unverified:
        lines.append(f"{label}: a gateway record exists, but whether its process still runs cannot be checked on "
                     "this platform.")
    if not listed_ok:
        lines.append("no process listing is available on this platform, so only gateways Hermes' own records "
                     "name are counted; a gateway no record names would not show.")
    else:
        lines.append(f"the process listing recognizes {LAUNCH_SHAPES}; a gateway started any other way is counted "
                     "only when a record names it.")
    if listing.retitled:
        lines.append(f"PID {', '.join(map(str, listing.retitled))}: titled just `hermes` (Hermes' optional "
                     "setproctitle), so whether each is a gateway cannot be read from its command line.")
    lines.append(_fleet_line(root, listed_ok, recorded, unrecorded, shared))
    for profile, pids in shared.items():
        actions.append(f"profile `{profile}` is served by PIDs {', '.join(map(str, pids))}; keep one gateway for it")
    for state in adapters:
        lines.append(_adapter_line(state))
        if _adapter_down(state):
            actions.append(f"{state.profile} {state.platform}: {state.fix}")
    silent = _silent_logs(homes, logs, serving)
    if silent:
        lines.append("no adapter state read from: " + "; ".join(silent) + ".")
    return lines, list(dict.fromkeys(actions))


def _restart_lines(restart: FleetRestartState) -> list[str]:
    lines: list[str] = []
    if restart.obligation:
        lines.append(f"Hermes records a pending fleet restart ({restart.obligation}): an update pulled new code that "
                     "running gateways have not loaded.")
    if restart.receipt_status == STATUS_MISSING:
        lines.append(f"no Hermes update receipt at {restart.receipt_path}.")
    elif restart.receipt_status == STATUS_UNRECOGNIZED:
        lines.append(f"Hermes' update receipt {restart.receipt_path} is not in a shape this check reads.")
    elif restart.receipt_kind != "update":
        if not restart.obligation:
            lines.append(f"Hermes records no pending fleet restart; its latest receipt is a `{restart.receipt_kind}` "
                         "run, which records no gateway restart.")
    else:
        finished = f" (finished {restart.finished_at})" if restart.finished_at else ""
        if restart.restart_incomplete or restart.phase_error:
            error = f": {restart.phase_error}" if restart.phase_error else ""
            lines.append(f"Hermes' latest update{finished} recorded its gateway restart as incomplete{error}.")
        if restart.stale_fleet:
            lines.append(f"that update's fleet check marked {restart.stale_fleet} gateway(s) stale.")
        if not (restart.restart_incomplete or restart.phase_error or restart.stale_fleet or restart.obligation):
            lines.append(f"Hermes' latest update{finished} recorded a complete gateway restart and no pending one.")
    return lines


def _build_words(process: GatewayProcess, built: str) -> str:
    if process.build == BUILD_OTHER_COMMIT:
        return f"its own record says it runs commit {process.code_sha[:8]}, not the installed build"
    if process.build == BUILD_BEFORE:
        return f"that is before the installed build ({built}), so it still serves pre-update code"
    if process.build == BUILD_CURRENT and process.code_sha:
        return "its own record says it runs the installed commit"
    if process.build == BUILD_CURRENT:
        return "started after the installed build"
    return "not compared with a build"


def _recorded_line(process: GatewayProcess, built: str) -> str:
    started = f", started {process.started_at}" if process.started_at else ""
    turns = f"; {process.active_turns} turn(s) live" if process.active_turns else ""
    return (f"PID {process.pid} serves {', '.join(process.serves)} (recorded in {process.home}){started}; "
            f"{_build_words(process, built)}{turns}.")


def _unrecorded_line(process: GatewayProcess, built: str, recorded: list[GatewayProcess]) -> str:
    """Which home and which checkout an unrecorded process runs is not known: nothing here claims either."""
    named = f"`--profile {process.profile}` on its command line" if process.profile else "no profile on its command line"
    started = f", started {process.started_at}" if process.started_at else ""
    if process.idle_exit:
        # Hermes passes `--profile default` as the selector of any home outside `<root>/profiles/` (a throwaway
        # home included), so the shared-name note below would read as a second default gateway.
        head = (f"PID {process.pid} runs `hermes gateway run --idle-exit` ({named}) and no record under this Hermes "
                f"root names it{started}{_unrecorded_build(process, built)}: a Hermes client started it for its own "
                "home (`hermes chat` in a scratch home, such as an OMH dispatch's child, the TUI, or cron)")
        if process.overdue:
            return (f"{head}, and it has not exited after more than {IDLE_EXIT_STALE_SECONDS} s. {IDLE_EXIT_TERMS}")
        unknown = "" if process.started_at else " Its start time could not be read."
        return f"{head}. {IDLE_EXIT_TERMS}{unknown}"
    build = _unrecorded_build(process, built)
    owner = next((other.pid for other in recorded if (process.profile or DEFAULT_PROFILE) in other.serves), None)
    also = (f"; it carries the same profile name as PID {owner} here, and which home it serves is not recorded"
            if owner is not None else "")
    return (f"PID {process.pid} runs `hermes gateway run` ({named}) and no record under this Hermes root names it"
            f"{started}{build}{also}.")


IDLE_EXIT_TERMS = (
    "When its idle exit is armed, Hermes ends it after `gateway.unmanaged_idle_exit_seconds` (600 s by default) "
    "with nothing to do. It is not armed when that home sets the value to 0 or when Hermes detects a supervisor, "
    "and an armed one stays up while an idle check of its own fails (Hermes counts that as work) or while a client, "
    "adapter, cron or kanban job holds it."
)


def _stray(process: GatewayProcess) -> bool:
    """An unrecorded process the person should find: any but an idle-exit gateway still inside the threshold."""
    return not process.idle_exit or process.overdue


def _unrecorded_build(process: GatewayProcess, built: str) -> str:
    if process.build == BUILD_BEFORE:
        return f"; that is before this install's build ({built}): if it runs this install, it serves pre-update code"
    if process.build == BUILD_CURRENT:
        return "; that is after this install's build"
    return ""


def _fleet_line(
    root: Path, listed_ok: bool, recorded: list[GatewayProcess], unrecorded: list[GatewayProcess],
    shared: dict[str, list[int]],
) -> str:
    total = len(recorded) + len(unrecorded)
    if not total:
        source = ("and none the process listing recognizes" if listed_ok
                  else "(the process listing was not available)")
        return f"no running Hermes gateway: no live gateway record under {root} {source}."
    served = {profile for process in recorded for profile in process.serves}
    shape = f"{total} gateway process(es) running, {len(recorded)} recorded, serving {len(served)} profile(s)"
    if unrecorded:
        shape += f"; {len(unrecorded)} not recorded by this Hermes root"
        if idle := sum(process.idle_exit for process in unrecorded):
            shape += f", {idle} of them a client's idle-exit gateway"
    if shared:
        shape += f"; {len(shared)} profile(s) served by more than one"
    return shape + "."


def _adapter_down(state: AdapterState) -> bool:
    """Down and worth a person's action: a failure Hermes will not retry, or one it flags as needing attention."""
    return bool(state.reason_kind) and (state.reason_kind != REASON_TRANSIENT or state.needs_attention)


def _adapter_line(state: AdapterState) -> str:
    where = f"{state.profile} {state.platform}"
    latest = f"latest line {state.logged}" if state.logged else "no log line in this run"
    if state.last_state == AMBIGUOUS_PROFILE and state.source == SOURCE_RECORD:
        return (f"{state.platform}: one of the profiles {state.profile.replace('/', ', ')} failed to connect at "
                f"{state.logged} (the log does not say which); each one's own gateway record says it is connected now.")
    if state.last_state == AMBIGUOUS_PROFILE:
        return (f"{state.platform}: one of the profiles {state.profile.replace('/', ', ')} failed to connect at "
                f"{state.logged}, and the log does not say which (their reconnects were open together); each "
                f"profile's own record entry, when present, is the state now. {state.fix}")
    if state.state == STATE_UNSERVED:
        return (f"{where}: no running gateway serves {state.profile}; its last line, `{state.last_state}` at "
                f"{state.logged}, says nothing about now.")
    if state.state == STATE_STALE and state.re_served:
        return (f"{where}: no adapter line since Hermes served {state.profile} again ({state.re_served}); the last "
                f"one, `{state.last_state}` at {state.logged}, is from before that, and Hermes dropped its verdict.")
    if state.state == STATE_STALE:
        return (f"{where}: no adapter line since the gateway serving it started ({state.gateway_started}); the "
                f"last one, `{state.last_state}` at {state.logged}, is from an earlier run.")
    by = "by the serving gateway's own record, " if state.source == SOURCE_RECORD else ""
    if state.source == SOURCE_RECORD and state.state in RECORD_CONNECTING:
        return f"{where}: connecting now ({by}{latest})."
    if state.source == SOURCE_RECORD and state.state == RECORD_DISABLED:
        why = f": {state.reason or state.code}" if state.reason or state.code else ""
        return f"{where}: disabled by Hermes{why} ({by}{latest})."
    if state.source == SOURCE_RECORD and state.state not in RECORD_KNOWN:
        return f"{where}: state `{state.state}`, which this check does not know ({by}{latest}); not judged."
    if state.state == STATE_CONNECTED:
        return f"{where}: connected ({by}{latest})."
    if state.state == STATE_DEGRADED:
        return f"{where}: connected in degraded mode ({by}{latest})."
    if state.state == STATE_RETRYING and not state.needs_attention:
        return f"{where}: reconnecting; Hermes retries it on its own ({by}{latest})."
    if state.state == STATE_DISCONNECTED:
        return f"{where}: stopped ({by}{latest}), and nothing later says it connected."
    attention = "; Hermes flags it as needing attention" if state.needs_attention else ""
    if state.source == SOURCE_RECORD:
        return f"{where}: `{state.state}` by the serving gateway's own record ({latest}){attention}. {state.fix}"
    verb = "failed to connect" if state.state == "failed" else f"stopped on a fatal error ({state.code or 'no code'})"
    return f"{where}: {verb} at {state.logged}, and no later line says it connected. {state.fix}"


def _silent_logs(homes: list[tuple[str, Path]], logs: list[LogRead], serving: dict[str, _Serving]) -> list[str]:
    words = {
        STATUS_MISSING: "no log",
        STATUS_UNREADABLE: "the log could not be read",
        STATUS_UNRECOGNIZED: "no line is in Hermes' log format",
    }
    silent = []
    for (label, _home), log in zip(homes, logs, strict=True):
        info = serving.get(label)
        if log.status in words:
            silent.append(f"{log.path} ({words[log.status]})")
        elif log.events:
            continue
        elif info is not None and not any(key.startswith(f"{label}:") for key in info.platforms):
            silent.append(f"{label} (no adapter line, and no messaging platform in its gateway's record)")
        else:
            silent.append(f"{log.path} (no adapter line in its last {log.bytes_read // 1024} KiB)")
    return silent
