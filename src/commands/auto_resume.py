"""`omh auto-resume`: whether a dropped OMH session reopens by itself, and the opt-in shell-rc hook.

Path A (on by default): a bare `omh` in the terminal, else the folder, whose
OMH TUI session was dropped (a hang-up, SIGTERM, a crash, a vanished process)
reopens it at once (`commands/bare_launch.py`). `set --mode off`,
`OMH_AUTO_RESUME=0` or `omh --new` turn it off. Path B (off until installed):
`shell install` adds a marked block to the shell rc that runs `shell-start` at
the first prompt of a new terminal when a dropped session waits
(`tui/shell_hook.py`); `shell remove` takes it out. `status` only reads.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from ..maintenance.auto_resume_state import (
    AUTO_RESUME_ENV,
    AUTO_RESUME_MODES,
    auto_resume_enabled,
    dropped_sessions,
    environment_off,
    read_auto_resume_mode,
    write_auto_resume_mode,
)
from ..system.stdin_probe import stdin_is_tty
from ..tui import shell_hook
from .common import _print_json, _wants_json

STATUS_SCHEMA = "omh_auto_resume_status/v1"
# Set inside a Hermes or OMH TUI session, or on CI: a shell there is not a terminal the person reopened.
_INSIDE_SESSION_ENV = ("HERMES_SESSION_ID", "OMH_TUI_SESSION_FILE", "CI")


def _paths(args: argparse.Namespace):
    from .bare_launch import _paths as bare_paths

    return bare_paths(args)


def _age(seconds: object) -> str:
    if not isinstance(seconds, (int, float)):
        return "unknown age"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 120:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"


def _status_payload(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    omh_home = paths.omh_home
    return {
        "schema_version": STATUS_SCHEMA,
        "mode": read_auto_resume_mode(omh_home),
        "environment_off": environment_off(os.environ),
        "enabled": auto_resume_enabled(omh_home, os.environ),
        "shell_hooks": [shell_hook.hook_state(shell, os.environ) for shell in shell_hook.SHELLS],
        "pending_marker": str(shell_hook.marker_path(omh_home)),
        "pending": shell_hook.marker_path(omh_home).is_file(),
        "dropped": dropped_sessions(omh_home),
    }


def cmd_auto_resume_status(args: argparse.Namespace) -> int:
    payload = _status_payload(args)
    if _wants_json(args):
        _print_json(payload)
        return 0
    mode = payload["mode"]
    line = f"Auto-resume: {mode}"
    if mode == "on" and payload["environment_off"]:
        line += f" (off in this shell: {AUTO_RESUME_ENV}=0)"
    print(line)
    for state in payload["shell_hooks"]:  # type: ignore[union-attr]
        installed = state["installed"]
        word = "installed" if installed else ("unreadable" if installed is None else "not installed")
        print(f"Shell hook ({state['shell']}): {word} in {state['rc']}")
    dropped = payload["dropped"]
    if not dropped:
        print("Dropped sessions waiting: none")
    else:
        print("Dropped sessions waiting:")
        for row in dropped:  # type: ignore[union-attr]
            key = f", terminal {row['terminal_key_name']}" if row["terminal_key_name"] else ""
            print(f"  {row['session_id']}  {row['cwd'] or '(no folder)'}{key}, {_age(row['age_seconds'])}")
    print("Change with `omh auto-resume set --mode on|off`; `omh --new` opens a new session once.")
    return 0


def cmd_auto_resume_set(args: argparse.Namespace) -> int:
    try:
        policy = write_auto_resume_mode(_paths(args).omh_home, args.mode)
    except (ValueError, OSError) as error:
        print(f"omh: {error}", file=sys.stderr)
        return 2
    if _wants_json(args):
        _print_json({"schema_version": STATUS_SCHEMA, "mode": policy["mode"]})
        return 0
    print(f"Auto-resume: {policy['mode']}")
    if policy["mode"] == "on":
        print("A bare `omh` reopens the session its terminal or folder dropped; `omh --new` opens a new one.")
    else:
        print("A bare `omh` always opens a new session; `omh --resume` still reopens one you name.")
    return 0


def _chosen_shell(args: argparse.Namespace) -> str | None:
    return getattr(args, "shell", None) or shell_hook.default_shell(os.environ)


def cmd_auto_resume_shell(args: argparse.Namespace) -> int:
    shell = _chosen_shell(args)
    if shell is None:
        print("omh: cannot tell which shell this is; name one with --shell zsh|bash|powershell.", file=sys.stderr)
        return 2
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        if args.shell_action == "install":
            result = shell_hook.install(shell, _paths(args).omh_home, os.environ, dry_run=dry_run)
        else:
            result = shell_hook.remove(shell, os.environ, dry_run=dry_run)
    except (shell_hook.ShellHookError, OSError) as error:
        print(f"omh: {error}", file=sys.stderr)
        return 1
    if _wants_json(args):
        _print_json({"schema_version": STATUS_SCHEMA, "shell": result.shell, "rc": str(result.rc),
                     "action": result.action, "changed": result.changed, "dry_run": result.dry_run,
                     "block": result.block})
        return 0
    would = "would be " if dry_run and result.changed else ""
    sentences = {
        "installed": f"Shell hook {would}added to the end of {result.rc}.",
        "updated": f"Shell hook in {result.rc} {would or 'was '}brought up to date.",
        "unchanged": f"Shell hook already in {result.rc}; nothing changed.",
        "removed": f"Shell hook {would}removed from {result.rc}.",
        "absent": f"No shell hook in {result.rc}; nothing changed.",
    }
    print(sentences[result.action])
    if dry_run and result.block:
        print(result.block)
    if result.action in ("installed", "updated") and not dry_run:
        print("It runs in new terminals; `omh auto-resume shell remove` takes it out.")
    return 0


def cmd_auto_resume_shell_start(args: argparse.Namespace) -> int:
    """What the shell hook runs: reopen the session this terminal dropped, at once, or exit 0 silently."""
    from .bare_launch import _claim_dropped_session, _launch_hermes_tui, _tui_omh_home

    if any(os.environ.get(name) for name in _INSIDE_SESSION_ENV):
        return 0
    if not stdin_is_tty() or not sys.stdout.isatty() or shutil.which("hermes") is None:
        return 0
    paths = _paths(args)
    if not auto_resume_enabled(_tui_omh_home(args, paths), os.environ):
        return 0
    # Unattended: a same-folder session another terminal's key holds stays for that terminal (`strict_keys`).
    if not _claim_dropped_session(args, paths, strict_keys=True):
        return 0
    launched = _launch_hermes_tui(args)
    return 0 if launched is None else launched


def _add_auto_resume_commands(sub) -> None:
    group = sub.add_parser(
        "auto-resume",
        help="Whether a dropped OMH session reopens by itself, and the opt-in shell hook for new terminals.",
    )
    group_sub = group.add_subparsers(dest="auto_resume_command", required=True)

    status = group_sub.add_parser("status", help="Show the mode, the shell hooks and the dropped sessions waiting.")
    status.add_argument("--json", action="store_true", help="Print the machine-readable status payload.")
    status.set_defaults(func=cmd_auto_resume_status)

    set_cmd = group_sub.add_parser("set", help="Turn reopening a dropped session on a bare `omh` on or off.")
    set_cmd.add_argument("--mode", choices=AUTO_RESUME_MODES, required=True, help="on (default) or off.")
    set_cmd.add_argument("--json", action="store_true", help="Print the machine-readable result.")
    set_cmd.set_defaults(func=cmd_auto_resume_set)

    shell = group_sub.add_parser("shell", help="Add or remove the shell-rc block that reopens it in a new terminal.")
    shell.add_argument("shell_action", choices=("install", "remove"), help="install or remove the block.")
    shell.add_argument("--shell", choices=shell_hook.SHELLS, default=None,
                       help="The shell whose rc to change (default: the one $SHELL names; PowerShell on Windows).")
    shell.add_argument("--dry-run", action="store_true", help="Say what would change and write nothing.")
    shell.add_argument("--json", action="store_true", help="Print the machine-readable result.")
    shell.set_defaults(func=cmd_auto_resume_shell)

    start = group_sub.add_parser("shell-start", help="Run by the shell hook: reopen this terminal's dropped session.")
    start.set_defaults(func=cmd_auto_resume_shell_start)
