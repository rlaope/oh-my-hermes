"""`/gateway restart`: Hermes' own `hermes gateway restart`, run for the person who typed it and confirmed it.

After `omh update` a running Hermes gateway keeps the OMH plugin code it
loaded at its start, and the model inside it cannot restart the gateway it
runs in. The person can: `/gateway restart` asks first, naming what the
gateway's own record says the restart interrupts (`read_impact`), and on
"Restart" runs Hermes' CLI exactly as Hermes' updater runs it for a profile
(`hermes_cli/update_restart_recovery.py`): `<HERMES_PYTHON> -m hermes_cli.main
-p <profile> gateway restart --yes --detach`, with the interpreter and import
path the launcher handed the TUI (`restart_spawn`). `--yes` is Hermes' own
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
records. It counts the turns the gateway runs and names the messenger
platforms connected to it; who else merely has a session open there is not
recorded, and a home with no live record is said to be unknown.
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


def manual_command(profile: str) -> str:
    """What the person runs in a terminal to do the same: the command Hermes' own refusals print."""
    args = profile_args(profile)
    return f"hermes -p {args[1]} gateway restart" if args and args[1] != DEFAULT_PROFILE else "hermes gateway restart"


def restart_spawn(environ: Mapping[str, str], profile: str) -> GatewaySpawn:
    """Hermes' restart command on Hermes' interpreter, with the environment the gateway child gets
    (`gateway_spawn`): the launcher's import path, none of the TUI's own variables. It runs from Hermes' source
    root, as Hermes' own app runs its CLI actions, not from the session's folder."""
    child = gateway_spawn(environ)
    python, src_root = environ["HERMES_PYTHON"], environ["HERMES_PYTHON_SRC_ROOT"]
    return GatewaySpawn(argv=(python, "-m", HERMES_MAIN, *profile_args(profile), *RESTART_ARGS), cwd=src_root,
                        env=child.env)


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


# ── what the restart interrupts ───────────────────────────────────────────


@dataclass(frozen=True)
class RestartImpact:
    """What the gateway's record says a restart interrupts. `gateway` is None when no live record was found."""

    home: Path | None  # the home whose record it is: also where its starts ledger and plugin bundle are
    gateway: Gateway | None
    profile: str = ""  # a named profile the shared gateway serves: Hermes restarts only that profile inside it

    @property
    def platforms(self) -> tuple[str, ...]:
        """The messenger platforms connected on it now; only the profile's own when only the profile restarts."""
        if self.gateway is None:
            return ()
        names = [platform.name for platform in self.gateway.platforms if platform.current and platform.state == CONNECTED]
        if self.profile:
            names = [name for name in names if name.startswith(f"{self.profile}:")]
        return tuple(names)


def read_impact(environ: Mapping[str, str], profile: str) -> RestartImpact:
    """The record of the gateway that serves this profile: the profile's own when it runs one, else the root's,
    which the shared gateway keeps (only when it is the default profile or the root's record names this one)."""
    from .bot_board import read_gateway

    hermes_home = environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        current = Path(hermes_home)
    elif environ.get("HOME"):
        current = Path(environ["HOME"]) / ".hermes"
    else:
        return RestartImpact(None, None)
    named = current.parent.name == "profiles"
    root = current.parent.parent if named else current
    if named:
        own = read_gateway(current)
        if own.live and not own.elsewhere:
            return RestartImpact(current, own)
    host = read_gateway(root)
    if not host.live or host.elsewhere:
        return RestartImpact(None, None)
    if named and current.name not in host.served:
        return RestartImpact(None, None)
    return RestartImpact(root, host, current.name if named else "")


def _names(names: tuple[str, ...]) -> str:
    shown = ", ".join(names[:NAMES_SHOWN])
    return f"{shown} and {len(names) - NAMES_SHOWN} more" if len(names) > NAMES_SHOWN else shown


def impact_lines(impact: RestartImpact, busy: bool) -> list[str]:
    """At most three lines naming what the restart interrupts, as far as the record says; plainly unknown without
    one. `busy`: this session's own turn runs."""
    gateway = impact.gateway
    own_turn = "This session's running turn would be interrupted too." if busy else ""
    if gateway is None:
        return [line for line in (
            "Hermes keeps no live record of this gateway, so who else uses it is unknown here: other sessions' "
            "turns and messenger bots on it would be interrupted too.",
            own_turn,
        ) if line]
    platforms = impact.platforms
    if impact.profile:
        head = (f"Hermes restarts only profile {impact.profile} inside its shared gateway (pid {gateway.pid}).")
    elif gateway.served:
        count = len(gateway.served)
        head = (f"Hermes' gateway (pid {gateway.pid}) serves {count} profile{'' if count == 1 else 's'}: "
                f"{_names(gateway.served)}.")
    else:
        head = f"Hermes' gateway (pid {gateway.pid})."
    bots = (f"Messenger bots stop answering until it is back: {_names(platforms)}." if platforms
            else "No messenger platform is connected to it.")
    turns = gateway.active_agents
    if impact.profile and turns:
        work = (f"It runs {turns} turn{'' if turns == 1 else 's'} across all its profiles; those in profile "
                f"{impact.profile} would be interrupted.")
    elif turns and busy:
        work = f"{turns} running turn{'' if turns == 1 else 's'} would be interrupted, this session's included."
    elif turns:
        work = f"{turns} running turn{'' if turns == 1 else 's'} in other sessions would be interrupted."
    elif busy:
        work = "This session's running turn would be interrupted."
    else:
        work = "No turn is running on it."
    return [head, bots, work]
