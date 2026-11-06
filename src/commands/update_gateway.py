"""After `omh update`: offer to restart each running Hermes gateway that still runs the old OMH plugin code.

A running gateway keeps the OMH plugin code it loaded at its start
(`maintenance.hermes_gateway`), and `omh update` used to say so only in a
line of text. Now the process the person started asks, once the update has
finished, for each gateway that runs now and started before the plugin
bundle installed for it (`stale_running_gateways`, the hint's own evidence):
it prints what the gateway's record says a restart interrupts
(`tui.gateway_restart.read_impact` and `impact_lines`, what `/gateway
restart` names), then `Restart the Hermes gateway now so the new OMH plugin
code loads? [y/N]`. No is the default. Yes runs Hermes' own restart, the
command `/gateway restart` runs, with the person's `hermes` on PATH, the
command the hint names: `hermes -p <profile> gateway restart --yes
--detach`. `--yes` stands for the answer just given, and `--detach` keeps
this short call from becoming the gateway itself where no service runs one.
Hermes decides everything else, including the service manager and the
drain. The command runs in a session of its own, so a Ctrl+C here stops
the wait, not the restart.

Nothing is asked off a terminal, with `--json`, `--no-interactive` or
`--yes`, in a dry run, after an update that did not activate, or in a
re-entered update (the run a staged update makes inside its transaction,
whose wait is bounded and whose failure rolls back). `--restart-gateway`
restarts without asking, under `--json` too, with Hermes' output on stderr;
`--no-restart-gateway` neither asks nor restarts. A restart asked for that
fails exits `GATEWAY_RESTART_EXIT_CODE`: the update stays active, and the
code does not call the failure success. Running OMH TUIs are not touched;
each notices the update itself (`tui.generation_watch`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..install.self_update import PROFILE_REPAIR_EXIT_CODE
from ..maintenance.hermes_gateway import stale_running_gateways
from ..tui.gateway_restart import GATEWAY_MARKERS, RESTART_ARGS, impact_lines, manual_command, profile_args, read_impact

RESTART_FLAGS = frozenset({"--restart-gateway", "--no-restart-gateway"})
REENTRY_ENV = "OMH_UPDATE_COMMAND_PACKAGE_REENTERED"
# The update activated: everything refreshed, or all but some bot profiles (`PROFILE_REPAIR_EXIT_CODE`).
ACTIVE_CODES = frozenset({0, PROFILE_REPAIR_EXIT_CODE})
# The update activated, and a gateway restart asked for failed or could not start.
GATEWAY_RESTART_EXIT_CODE = 4
INTERRUPTED_EXIT_CODE = 130
ASK, RESTART, SKIP = "ask", "restart", "skip"

QUESTION = "Restart the Hermes gateway now so the new OMH plugin code loads?"
PROFILE_QUESTION = "Restart the Hermes gateway for profile {profile} now so the new OMH plugin code loads?"
STALE_LINE = "Hermes' gateway{which} still runs the OMH plugin code it started with."
DECLINED_LINE = "  Hermes' gateway was not restarted; run `{command}` when a restart suits the bots it serves."
STARTED_LINE = "Restarting Hermes' gateway (`{command}`)…"
FINISHED_LINE = "  Hermes' restart command finished; `hermes gateway status` shows the gateway it started."
FAILED_LINE = "  warning: Hermes' gateway restart exited {code}, so it may not have restarted; run `{command}`."
UNSTARTED_LINE = "  warning: could not run Hermes' gateway restart ({why}); run `{command}`."
NO_HERMES = "no `hermes` on PATH"
INTERRUPTED_LINE = "  omh stopped waiting; Hermes' restart goes on by itself (`hermes gateway status` shows it)."
NOTHING_STALE_LINE = "No running Hermes gateway runs older OMH plugin code; nothing to restart."


def restart_mode(args: Any, *, terminal: bool, environ: Mapping[str, str]) -> str:
    """ASK, RESTART or SKIP for this run of `omh update` (see the module docstring for when each holds)."""
    if getattr(args, "dry_run", False) or getattr(args, "command_package_updated", False) \
            or environ.get(REENTRY_ENV) == "1":
        return SKIP
    chosen = getattr(args, "restart_gateway", None)
    if chosen is not None:
        return RESTART if chosen else SKIP
    quiet = getattr(args, "json", False) or getattr(args, "no_interactive", False) or getattr(args, "yes", False)
    return ASK if terminal and not quiet else SKIP


def restart_argv(hermes: str, profile: str) -> list[str]:
    """Hermes' restart of `profile`'s gateway through the person's `hermes`, the profile always named so Hermes'
    sticky `active_profile` never picks another one."""
    return [hermes, *profile_args(profile), *RESTART_ARGS]


def restart_env(environ: Mapping[str, str], hermes_home: Path) -> dict[str, str]:
    """This environment with the Hermes root that `-p` resolves against, without the variables that would make the
    command read as running inside a gateway (Hermes' updater drops them too)."""
    env = {name: value for name, value in environ.items() if name not in GATEWAY_MARKERS}
    env["HERMES_HOME"] = str(hermes_home)
    return env


def restart_after_update(
    code: int,
    hermes_home: Path,
    *,
    mode: str,
    ask: Callable[[str], bool],
    run: Callable[[list[str], dict[str, str]], int],
    hermes: str | None,
    environ: Mapping[str, str],
    say: Callable[[str], None],
) -> int:
    """Ask about, or restart, each gateway still on the old OMH plugin code; the exit code `omh update` returns.

    `code` is the update's own. `run` starts Hermes' command and returns its
    exit code (it raises `OSError` when it cannot start, `KeyboardInterrupt`
    when the person stopped the wait).
    """
    if mode == SKIP or code not in ACTIVE_CODES:
        return code
    gateways = [(profile, home) for profile, home in stale_running_gateways(hermes_home) if profile_args(profile)]
    if not gateways:
        if mode == RESTART:
            say(NOTHING_STALE_LINE)
        return code
    failed = False
    for profile, home in gateways:
        named = profile != "default"
        command = manual_command(profile)
        say(STALE_LINE.format(which=f" for profile {profile}" if named else ""))
        for line in impact_lines(read_impact(restart_env(environ, home), profile if named else ""), False):
            say(f"  {line}")
        if mode == ASK and not ask(PROFILE_QUESTION.format(profile=profile) if named else QUESTION):
            say(DECLINED_LINE.format(command=command))
            continue
        if hermes is None:
            say(UNSTARTED_LINE.format(why=NO_HERMES, command=command))
            failed = True
            continue
        say(STARTED_LINE.format(command=command))
        try:
            returncode = run(restart_argv(hermes, profile), restart_env(environ, hermes_home))
        except OSError as error:
            say(UNSTARTED_LINE.format(why=str(error), command=command))
            failed = True
            continue
        except KeyboardInterrupt:
            say(INTERRUPTED_LINE)
            return INTERRUPTED_EXIT_CODE
        if returncode:
            say(FAILED_LINE.format(code=returncode, command=command))
            failed = True
        else:
            say(FINISHED_LINE)
    return GATEWAY_RESTART_EXIT_CODE if failed and code == 0 else code
