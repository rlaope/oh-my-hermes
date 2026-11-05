"""`/gateway restart`: Hermes' own `hermes gateway restart`, run for the person who typed it and confirmed it.

After `omh update` a running Hermes gateway keeps the OMH plugin code it
loaded at its start, and the model inside it cannot restart the gateway it
runs in. The person can: `/gateway restart` asks first, naming what the
gateway's own record says the restart interrupts (`read_impact`), and on
"Restart" runs Hermes' CLI exactly as Hermes' updater runs it for a profile
(`hermes_cli/update_restart_recovery.py`): `<HERMES_PYTHON> -m hermes_cli.main
-p <profile> gateway restart --yes --detach`, with the interpreter and import
path the launcher handed the TUI (`restart_spawn`). A named profile the shared
gateway serves gets two restarts to pick from: Hermes' own for that profile,
which only re-serves it inside the shared process (its code is not loaded
again), and the whole gateway, addressed as `-p default` the way Hermes'
Desktop addresses the process that serves a profile
(`web_server_gateway._gateway_subcommand`). `--yes` is Hermes' own
"interrupt them deliberately" flag, standing for the confirmation the person
just gave; `--detach` keeps this short-lived call from becoming the gateway
itself where no service runs one. Hermes decides everything else: the service
manager, the drain, a profile the shared gateway serves. Nothing here signals a
gateway, lists processes or kills by pattern.

The call runs in a session of its own (`start_new_session`), so Ctrl+Z or the
TUI's exit does not stop a restart half done, and its output goes to an
unnamed temporary file (unlinked as it is created), not a pipe, so it never
dies on a write after the TUI has gone. A worker thread waits for it and
keeps only the output's last lines, in memory, for a failure to name.

The impact is read from files only, the way the bot board reads them
(`bot_board.read_gateway`): `gateway_state.json` of the gateway that serves
the TUI's profile, whose pid is checked with signal 0 against the start time it
records. It counts the work the gateway runs (Hermes' `_active_work_count`:
turns and cron jobs) and names the messenger platforms connected to it; who
else merely has a session open there is not recorded, and a home with no live
record is said to be unknown. A gateway a custom supervisor runs
(`--external-supervisor` in its recorded argv) drains on a restart: Hermes
lets running work finish first, up to `agent.restart_after_turn_timeout` from
the gateway home's config, and new turns wait meanwhile. So does one Hermes'
own systemd or launchd service runs (Hermes sends it SIGUSR1), which its argv
does not tell, so for any other gateway the drain is said to depend on a
service running it. Restarting one profile alone does not drain: Hermes
re-serves it at once, so the profile's running turns stop, and the drain line
names the whole gateway's restart.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import IO, TYPE_CHECKING, Any

from .gateway import GatewaySpawn, gateway_spawn

if TYPE_CHECKING:  # the board's module loads only when something reads a record: most sessions never do
    from .bot_board import Gateway

# Hermes' updater runs exactly this tail for a profile restart (`update_restart_recovery._run_profile_restart`),
# with `--interrupt`, which is `--yes`'s alias.
RESTART_ARGS = ("gateway", "restart", "--yes", "--detach")
HERMES_MAIN = "hermes_cli.main"
DEFAULT_PROFILE = "default"
# Hermes' launcher names a home outside `profiles/` this way; no `-p` can address it.
CUSTOM_PROFILE = "custom"
# What Hermes' updater takes out of a restart's environment (`update_restart_recovery._GATEWAY_MARKERS`): inherited,
# they would make the command read as running inside the gateway.
GATEWAY_MARKERS = ("_HERMES_GATEWAY", "HERMES_GATEWAY", "HERMES_GATEWAY_MODE")
# Hermes' default `agent.restart_after_turn_timeout` (`hermes_cli/config_defaults.py`), in seconds.
DEFAULT_AFTER_TURN_SECONDS = 1800.0
CONFIG_FILE = "config.yaml"
OUTPUT_TAIL_BYTES = 8 << 10
OUTPUT_TAIL_LINES = 6
CONNECTED = "connected"  # a platform adapter Hermes reports as up (`gateway_state.json` `platforms.<name>.state`)
NAMES_SHOWN = 6


def profile_args(profile: str) -> tuple[str, ...]:
    """`-p <profile>` for the profile Hermes named for this session, so Hermes' sticky `active_profile` never picks
    another one; none for a home Hermes calls `custom` (outside `profiles/`), which `-p` cannot name."""
    name = profile.strip()
    if not name or name == CUSTOM_PROFILE or not _profile_name(name):
        return ()
    return ("-p", name)


def _profile_name(name: str) -> bool:
    """Hermes' own profile id rule (`hermes_cli/main.py` `_PROFILE_NAME_RE`): `[a-z0-9][a-z0-9_-]{0,63}`."""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    return 0 < len(name) <= 64 and name[0] not in "_-" and set(name) <= allowed


def manual_command(profile: str, *, explicit: bool = False) -> str:
    """What the person runs in a terminal to do the same: the command Hermes' own refusals print. `explicit` names
    `-p default` too: the whole gateway asked for from a named profile's session."""
    args = profile_args(profile)
    if args and (explicit or args[1] != DEFAULT_PROFILE):
        return f"hermes -p {args[1]} gateway restart"
    return "hermes gateway restart"


def restart_spawn(environ: Mapping[str, str], profile: str) -> GatewaySpawn:
    """Hermes' restart command on Hermes' interpreter, with the environment the gateway child gets
    (`gateway_spawn`): the launcher's import path, none of the TUI's own variables. It runs from Hermes' source
    root, as Hermes' own app runs its CLI actions, not from the session's folder."""
    child = gateway_spawn(environ)
    python, src_root = environ["HERMES_PYTHON"], environ["HERMES_PYTHON_SRC_ROOT"]
    env = {name: value for name, value in child.env.items() if name not in GATEWAY_MARKERS}
    return GatewaySpawn(argv=(python, "-m", HERMES_MAIN, *profile_args(profile), *RESTART_ARGS), cwd=src_root,
                        env=env)


@dataclass(frozen=True)
class RestartResult:
    returncode: int | None  # None: it could not start
    output: tuple[str, ...]  # its last lines, as it printed them
    error: str = ""  # why it could not start


class RestartRun:
    """One `hermes gateway restart` in flight: `result()` is None until it ended, then what it ended with."""

    def __init__(
        self, spawn: GatewaySpawn, wake: Callable[[], None], *, popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._result: RestartResult | None = None
        self._lock = threading.Lock()
        self._wake = wake
        try:
            output: IO[bytes] = tempfile.TemporaryFile()
        except OSError as error:
            self._result = RestartResult(None, (), f"no temporary file for its output ({error})")
            return
        try:
            process = popen(
                list(spawn.argv), cwd=spawn.cwd, env=spawn.env, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        except OSError as error:
            output.close()
            self._result = RestartResult(None, (), f"could not start {spawn.argv[0]}: {error}")
            return
        threading.Thread(target=self._wait, args=(process, output), name="omh-tui-gateway-restart",
                         daemon=True).start()

    def _wait(self, process: Any, output: IO[bytes]) -> None:
        code = process.wait()
        with output:
            lines = _tail(output)
        with self._lock:
            self._result = RestartResult(code, lines)
        self._wake()

    def result(self) -> RestartResult | None:
        with self._lock:
            return self._result


def _tail(output: IO[bytes]) -> tuple[str, ...]:
    """The last `OUTPUT_TAIL_LINES` non-blank lines of what it printed, read from at most its last
    `OUTPUT_TAIL_BYTES`."""
    try:
        size = output.seek(0, os.SEEK_END)
        output.seek(max(size - OUTPUT_TAIL_BYTES, 0))
        text = output.read(OUTPUT_TAIL_BYTES).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ()
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return tuple(lines[-OUTPUT_TAIL_LINES:])


# ── what the restart interrupts ──────────────────────────────────────────


@dataclass(frozen=True)
class RestartImpact:
    """What the gateway's record says a restart interrupts. `gateway` is None when no live record was found."""

    home: Path | None  # the home whose record it is: also where its starts ledger, plugin bundle and config are
    gateway: Gateway | None
    profile: str = ""  # a named profile the shared gateway serves: it can restart alone, or with the whole gateway
    wait_seconds: float = DEFAULT_AFTER_TURN_SECONDS  # how long a draining restart lets running work finish

    @property
    def platforms(self) -> tuple[str, ...]:
        """The messenger platforms connected on it now (stamped by the process that runs now)."""
        if self.gateway is None:
            return ()
        return tuple(platform.name for platform in self.gateway.platforms
                     if platform.current and platform.state == CONNECTED)


def read_impact(environ: Mapping[str, str], profile: str) -> RestartImpact:
    """The record of the gateway that serves this profile: the profile's own when it runs one, else the root's,
    which the shared gateway keeps (only when it is the default profile or the root's record names this one)."""
    from .bot_board import read_gateway

    current = _profile_home(environ)
    if current is None:
        return RestartImpact(None, None)
    named = current.parent.name == "profiles"
    root = current.parent.parent if named else current
    if named:
        own = read_gateway(current)
        if own.live and not own.elsewhere:
            return RestartImpact(current, own, wait_seconds=after_turn_seconds(current))
    host = read_gateway(root)
    if not host.live or host.elsewhere:
        return RestartImpact(None, None)
    if named and current.name not in host.served:
        return RestartImpact(None, None)
    return RestartImpact(root, host, current.name if named else "", after_turn_seconds(root))


def _profile_home(environ: Mapping[str, str]) -> Path | None:
    """The Hermes home of the TUI's profile, as the launcher named it; None when nothing names one."""
    hermes_home = environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        return Path(hermes_home)
    return Path(environ["HOME"]) / ".hermes" if environ.get("HOME") else None


def read_record(environ: Mapping[str, str], profile: str) -> Gateway | None:
    """The record of the gateway that serves this profile, live or not, as `read_impact` picks it: a live one
    first; with none live, the newer of the profile's own record and the root's that names it (a stopped, restarting
    or failed gateway leaves its last word there). None when there is no such record."""
    from .bot_board import read_gateway

    current = _profile_home(environ)
    if current is None:
        return None
    named = current.parent.name == "profiles"
    root = current.parent.parent if named else current
    own = read_gateway(current) if named else None
    if own is not None and own.live and not own.elsewhere:
        return own
    host = read_gateway(root)
    if named and current.name not in host.served:
        host = None
    if host is not None and host.live and not host.elsewhere:
        return host
    kept = [record for record in (own, host)
            if record is not None and not record.problem and not record.elsewhere and record.updated is not None]
    return max(kept, key=lambda record: record.updated or 0.0, default=None)


def after_turn_seconds(home: Path) -> float:
    """`agent.restart_after_turn_timeout` from the gateway home's `config.yaml`, as Hermes reads it (a number of
    seconds, at least 0); Hermes' default when the file, the key or the number is missing."""
    from .bot_board import CONFIG_BYTES, _bounded_text, _config_text

    text, _problem = _bounded_text(home / CONFIG_FILE, CONFIG_BYTES)
    raw = _config_text(text, ("agent", "restart_after_turn_timeout")) if text is not None else None
    if raw is None:
        return DEFAULT_AFTER_TURN_SECONDS
    try:
        seconds = float(raw.strip().strip("'\""))
    except ValueError:
        return DEFAULT_AFTER_TURN_SECONDS
    return max(seconds, 0.0) if seconds == seconds and seconds != float("inf") else DEFAULT_AFTER_TURN_SECONDS


def _names(names: tuple[str, ...]) -> str:
    shown = ", ".join(names[:NAMES_SHOWN])
    return f"{shown} +{len(names) - NAMES_SHOWN}" if len(names) > NAMES_SHOWN else shown


def _duration(seconds: float) -> str:
    return f"{seconds / 60:g} min" if seconds >= 60 else f"{seconds:g} s"


def impact_lines(impact: RestartImpact, busy: bool) -> list[str]:
    """At most three short lines naming what the restart interrupts, as far as the record says; plainly unknown
    without one. `busy`: this session's own turn runs."""
    gateway = impact.gateway
    if gateway is None:
        lines = ["Hermes keeps no live record of this gateway, so who else uses it is unknown here: running work "
                 "and messenger bots on it would be interrupted too."]
        if busy:
            lines.append("This session's running turn would be interrupted too.")
        return lines
    platforms = impact.platforms
    work = gateway.active_agents
    parts = [f"profiles: {_names(gateway.served)}"] if gateway.served else []
    parts.append(f"bots: {_names(platforms)}" if platforms else "no bots connected")
    parts.append(f"{work} running" if work else ("1 running" if busy else "nothing running"))
    lines = [" · ".join(parts)]
    if work or busy:
        mine = ", this session's turn included" if busy else ""
        whole = "On a whole-gateway restart, running" if impact.profile else "Running"
        drain = (f"finishes first, up to {_duration(impact.wait_seconds)} (Hermes' restart_after_turn_timeout); new "
                 "turns wait meanwhile")
        if impact.wait_seconds <= 0:
            lines.append(f"{whole} work (turns, cron jobs{mine}) would be interrupted.")
        elif gateway.supervised:
            lines.append(f"{whole} work (turns, cron jobs{mine}) {drain}.")
        else:  # a systemd or launchd service Hermes installed drains it too, and its argv does not say so
            lines.append(f"{whole} work (turns, cron jobs{mine}) {drain} if a service (systemd, launchd) runs this "
                         "gateway; otherwise it is interrupted.")
    return lines
