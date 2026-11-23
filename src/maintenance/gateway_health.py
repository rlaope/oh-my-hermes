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
live here and in `hermes_gateway_formats`, not in the doctor command, so the
TUI bot board can show the same report later.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import time

from ..install.skill_registration import hermes_profile_dirs
from ..skin_pack import TUI_PROFILE
from ..system.hermes_install import hermes_install_dir
from ..system.process_listing import hermes_gateway_processes
from ..tui.bot_board import ON_POSIX, Gateway, process_facts, read_gateway, started_at
from .hermes_gateway_formats import (
    GATEWAY_LOG_RELATIVE,
    GATEWAY_LOG_TAIL_BYTES,
    REASON_NONE,
    REASON_PRIVILEGED_INTENTS,
    REASON_TOKEN_REJECTED,
    REASON_TRANSIENT,
    STATE_CONNECTED,
    STATE_DEGRADED,
    STATUS_MISSING,
    STATUS_READ,
    STATUS_UNREADABLE,
    STATUS_UNRECOGNIZED,
    AdapterEvent,
    BuildStamp,
    FleetRestartState,
    LogRead,
    classify_reason,
    iso_utc,
    read_build_stamp,
    read_fleet_restart_state,
    read_gateway_log,
)

GATEWAY_HEALTH_SCHEMA = "omh_gateway_health/v1"
DEFAULT_PROFILE = "default"
BUILD_CURRENT = "current"
BUILD_BEFORE = "started_before_build"
BUILD_OTHER_COMMIT = "other_commit"
BUILD_UNKNOWN = "unknown"
FINDING_STALE_GATEWAY = "gateway_older_than_build"
FINDING_PENDING_RESTART = "hermes_pending_fleet_restart"
FINDING_INCOMPLETE_RESTART = "hermes_restart_incomplete"
FINDING_UNRECORDED = "unrecorded_gateway_process"
FINDING_SHARED_PROFILE = "profile_served_twice"
FINDING_ADAPTER_DOWN = "adapter_not_connected"
RESTART_NOTE = (
    "while turns are live Hermes asks before interrupting them, refuses when there is no terminal to ask on, "
    "and interrupts them only with `--yes`; OMH restarts nothing"
)
PORTAL_PATH = "the Discord Developer Portal, your application's Bot page, Privileged Gateway Intents"


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


@dataclass(frozen=True)
class AdapterState:
    profile: str
    platform: str
    state: str
    logged: str
    log: str
    reason: str = ""
    code: str = ""
    reason_kind: str = ""
    fix: str = ""


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
    list_processes: Callable[[], tuple[bool, list[tuple[int, str]]]] = hermes_gateway_processes,
    process_start: Callable[[int], float | None] = _process_start,
    log_tail_bytes: int = GATEWAY_LOG_TAIL_BYTES,
) -> GatewayHealth:
    root = hermes_root(hermes_home)
    install_dir = hermes_install_dir(root)
    install_found = install_dir.is_dir()
    build = read_build_stamp(install_dir) if install_found else BuildStamp(STATUS_MISSING, str(install_dir))
    restart = read_fleet_restart_state(root, install_dir, os.environ if environ is None else environ)
    homes = gateway_homes(root)
    recorded, unverified, platform_errors = _recorded_gateways(homes, gateway_reader, build)
    listed_ok, listed = list_processes()
    recorded_pids = {process.pid for process in recorded}
    unrecorded = []
    for pid, profile in listed:
        if pid in recorded_pids:
            continue
        started = process_start(pid)
        unrecorded.append(GatewayProcess(pid, profile, False, started_at=iso_utc(started), build=_build_verdict(build, "", started)))
    shared = _shared_profiles(recorded)
    serving = {profile: process.profile for process in recorded for profile in process.serves}
    logs, adapters = _adapter_states(homes, serving, platform_errors, log_tail_bytes)
    gateways = (*recorded, *unrecorded)
    findings = _findings(gateways, restart, shared, adapters)
    lines, actions = _report(root, install_found, install_dir, build, restart, listed_ok, recorded, unrecorded,
                             unverified, shared, adapters, logs)
    return GatewayHealth(
        GATEWAY_HEALTH_SCHEMA, str(root), install_found, asdict(build), asdict(restart),
        "observed" if listed_ok else "not_available", gateways, tuple(unverified), shared, tuple(adapters),
        tuple(asdict(log) | {"events": len(log.events)} for log in logs), findings, tuple(lines), tuple(actions),
    )


def _recorded_gateways(
    homes: list[tuple[str, Path]], gateway_reader: Callable[[Path], Gateway], build: BuildStamp
) -> tuple[list[GatewayProcess], list[str], dict[str, str]]:
    recorded: list[GatewayProcess] = []
    unverified: list[str] = []
    platform_errors: dict[str, str] = {}  # "profile:platform" -> the error the running gateway's record holds
    for label, home in homes:
        gateway = gateway_reader(home)
        if gateway.problem or gateway.elsewhere:
            continue
        if not gateway.live:
            if not ON_POSIX and gateway.state not in {"stopped", "startup_failed", ""}:
                unverified.append(label)
            continue
        serves = tuple(dict.fromkeys((label, *gateway.served)))
        for platform in gateway.platforms:
            key = platform.name if ":" in platform.name else f"{label}:{platform.name}"
            if platform.error:
                platform_errors[key] = platform.error
        recorded.append(GatewayProcess(
            gateway.pid or 0, label, True, str(home), iso_utc(gateway.started), serves, gateway.active_agents,
            gateway.code_sha, _build_verdict(build, gateway.code_sha, gateway.started),
        ))
    return recorded, unverified, platform_errors


def _build_verdict(build: BuildStamp, code_sha: str, started: float | None) -> str:
    """Whether a gateway runs the installed build: its own commit stamp first, else its start against `builtAt`."""
    if build.status != STATUS_READ:
        return BUILD_UNKNOWN
    if code_sha and build.commit:
        return BUILD_CURRENT if build.commit.startswith(code_sha) else BUILD_OTHER_COMMIT
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
    homes: list[tuple[str, Path]], serving: dict[str, str], platform_errors: dict[str, str], tail_bytes: int
) -> tuple[list[LogRead], list[AdapterState]]:
    logs: list[LogRead] = []
    latest: dict[tuple[str, str], tuple[AdapterEvent, str]] = {}
    for label, home in homes:
        log = read_gateway_log(home / GATEWAY_LOG_RELATIVE, tail_bytes=tail_bytes)
        logs.append(log)
        for event in log.events:
            key = (event.profile or label, event.platform)
            held = latest.get(key)
            if held is None or (event.epoch or 0.0) >= (held[0].epoch or 0.0):
                latest[key] = (event, log.path)
    states = []
    for (profile, platform), (event, log_path) in sorted(latest.items()):
        kind = "" if event.state in {STATE_CONNECTED, STATE_DEGRADED} else classify_reason(event)
        restart = _restart_command(serving.get(profile, DEFAULT_PROFILE))
        fix = _adapter_fix(kind, event, log_path, restart, platform_errors.get(f"{profile}:{platform}", "")) if kind else ""
        states.append(AdapterState(profile, platform, event.state, event.logged, log_path, event.reason, event.code, kind, fix))
    return logs, states


def _restart_command(gateway_profile: str) -> str:
    return "hermes gateway restart" if gateway_profile == DEFAULT_PROFILE else f"hermes --profile {gateway_profile} gateway restart"


def _adapter_fix(kind: str, event: AdapterEvent, log_path: str, restart: str, record_error: str) -> str:
    if kind == REASON_PRIVILEGED_INTENTS:
        # Hermes' own guidance in the record names Server Members only when the adapter requested it
        # (`_needs_server_members_intent`: a role allowlist, or a user allowlist entry that is not a numeric id or `*`).
        intents = (
            "Message Content and Server Members"
            if "Server Members Intent" in record_error
            else "Message Content, and Server Members too when the profile has a role allowlist "
            "(`DISCORD_ALLOWED_ROLES` or `discord.allowed_roles`) or a username rather than a numeric id in "
            "`DISCORD_ALLOWED_USERS`"
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
    if kind == REASON_TRANSIENT:
        return f"Hermes retries `{event.code}` on its own; no later line in the log says it reconnected yet."
    if kind == REASON_NONE:
        return f"no reason this check recognizes was logged with it; read the lines around {event.logged} in {log_path}."
    return f"unrecognized reason (Hermes logged: {event.reason or event.code}); read the lines around it in {log_path}."


def _findings(
    gateways: tuple[GatewayProcess, ...],
    restart: FleetRestartState,
    shared: dict[str, list[int]],
    adapters: list[AdapterState],
) -> tuple[str, ...]:
    found: list[str] = []
    if any(process.build in {BUILD_BEFORE, BUILD_OTHER_COMMIT} for process in gateways):
        found.append(FINDING_STALE_GATEWAY)
    if restart.obligation:
        found.append(FINDING_PENDING_RESTART)
    if restart.restart_incomplete or restart.phase_error or restart.stale_fleet:
        found.append(FINDING_INCOMPLETE_RESTART)
    if any(not process.recorded for process in gateways):
        found.append(FINDING_UNRECORDED)
    if shared:
        found.append(FINDING_SHARED_PROFILE)
    if any(state.reason_kind for state in adapters):
        found.append(FINDING_ADAPTER_DOWN)
    return tuple(found)


def _report(
    root: Path,
    install_found: bool,
    install_dir: Path,
    build: BuildStamp,
    restart: FleetRestartState,
    listed_ok: bool,
    recorded: list[GatewayProcess],
    unrecorded: list[GatewayProcess],
    unverified: list[str],
    shared: dict[str, list[int]],
    adapters: list[AdapterState],
    logs: list[LogRead],
) -> tuple[list[str], list[str]]:
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
    if unrecorded:
        pids = ", ".join(str(process.pid) for process in unrecorded)
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
    lines.append(_fleet_line(root, listed_ok, recorded, unrecorded, shared))
    for profile, pids in shared.items():
        actions.append(f"profile `{profile}` is served by PIDs {', '.join(map(str, pids))}; keep one gateway for it")
    for state in adapters:
        lines.append(_adapter_line(state))
        if state.reason_kind and state.reason_kind != REASON_TRANSIENT:
            actions.append(f"{state.profile} {state.platform}: {state.fix}")
    silent = _silent_logs(logs)
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
    named = f"`--profile {process.profile}` on its command line" if process.profile else "no profile on its command line"
    started = f", started {process.started_at}" if process.started_at else ""
    owner = next((other.pid for other in recorded if (process.profile or DEFAULT_PROFILE) in other.serves), None)
    also = f"; PID {owner} already serves that profile here" if owner is not None else ""
    return (f"PID {process.pid} runs `hermes gateway run` ({named}) and no record under this Hermes root names it"
            f"{started}; {_build_words(process, built)}{also}.")


def _fleet_line(
    root: Path, listed_ok: bool, recorded: list[GatewayProcess], unrecorded: list[GatewayProcess],
    shared: dict[str, list[int]],
) -> str:
    total = len(recorded) + len(unrecorded)
    if not total:
        source = "and none in the process listing" if listed_ok else "(the process listing was not available)"
        return f"no running Hermes gateway: no live gateway record under {root} {source}."
    served = {profile for process in recorded for profile in process.serves}
    shape = f"{total} gateway process(es) running, {len(recorded)} recorded, serving {len(served)} profile(s)"
    if unrecorded:
        shape += f"; {len(unrecorded)} not recorded by this Hermes root"
    if shared:
        shape += f"; {len(shared)} profile(s) served by more than one"
    return shape + "."


def _adapter_line(state: AdapterState) -> str:
    where = f"{state.profile} {state.platform}"
    if state.state == STATE_CONNECTED:
        return f"{where}: connected (latest line {state.logged})."
    if state.state == STATE_DEGRADED:
        return f"{where}: reconnected in degraded mode (latest line {state.logged})."
    verb = "failed to connect" if state.state == "failed" else f"stopped on a fatal error ({state.code or 'no code'})"
    return f"{where}: {verb} at {state.logged}, and no later line says it connected. {state.fix}"


def _silent_logs(logs: list[LogRead]) -> list[str]:
    words = {
        STATUS_MISSING: "no log",
        STATUS_UNREADABLE: "the log could not be read",
        STATUS_UNRECOGNIZED: "no line is in Hermes' log format",
    }
    silent = []
    for log in logs:
        if log.status in words:
            silent.append(f"{log.path} ({words[log.status]})")
        elif not log.events:
            silent.append(f"{log.path} (no adapter line in its last {log.bytes_read // 1024} KiB)")
    return silent
