from __future__ import annotations

import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERMES_PROCESS_SCHEMA_VERSION = "hermes_process_observation/v1"
_SHELL_NAMES = {"sh", "bash", "zsh", "dash"}
# Long-lived web backends: `serve` (desktop app) and `dashboard`, matching the backend
# set Hermes itself uses (hermes_cli/profiles.py `_BACKEND_TOKENS`).
_PERSISTENT_MAIN_COMMANDS = {"chat", "acp", "serve", "dashboard"}
_PERSISTENT_MAIN_FLAGS = {"--tui", "--cli"}
_PYTHON_COMMAND = re.compile(
    r"^(?P<executable>.*?python(?:\d+(?:\.\d+)*)?)\s+(?P<arguments>.+)$"
)
# Hermes' launchers run entry points as `python -I -c <script> <args>`, in two shapes:
#   * the published launcher (hermes_cli/_launchers.py `_launcher_script`): a multi-line
#     script ending `from hermes_cli.main import main` / `sys.exit(main())` plus a trailing
#     newline. macOS `ps` flattens each newline to a literal backslash-012.
#   * `runtime_command()` (same file), used when `hermes update` respawns a gateway: one
#     line ending `runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)`.
# Whatever follows the script's last statement is the real Hermes argv.
_LAUNCHER_COMMAND = re.compile(
    r"^(?P<executable>\S*python(?:\d+(?:\.\d+)*)?)\s+(?:-[A-Za-z]+\s+)*-c\s+(?P<script>.*)$"
)
_PS_NEWLINE = "\\012"
_LAUNCHER_IMPORT = _PS_NEWLINE + "from hermes_cli.main import main" + _PS_NEWLINE
_LAUNCHER_EXIT = "sys.exit(main())"
_RUNTIME_ENTRY = "runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)"
_CLAIM_BOUNDARY = (
    "Local process observation is bounded, best-effort, and is not execution, review, CI, or merge evidence."
)


def observe_hermes_processes(
    *,
    now: datetime | str | None = None,
    ps_output: str | None = None,
) -> dict[str, Any]:
    observed_at = _format_datetime(_coerce_datetime(now) or datetime.now(timezone.utc))
    if ps_output is None:
        try:
            result = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,command="],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return _observation(observed=False, reason="ps_unavailable", rows=[], observed_at=observed_at)
        if result.returncode != 0:
            return _observation(observed=False, reason="ps_unavailable", rows=[], observed_at=observed_at)
        ps_output = result.stdout

    kept = _process_rows(ps_output)
    kept_pids = {row["pid"] for row in kept}
    rows = [
        {
            "pid": row["pid"],
            "ppid": row["ppid"],
            "role": "child" if row["ppid"] in kept_pids else "agent",
            "label": _process_label(row["argv"]),
        }
        for row in kept
    ]
    return _observation(observed=True, reason="", rows=rows, observed_at=observed_at)


def _process_rows(ps_output: str) -> list[dict[str, Any]]:
    self_pids = {os.getpid(), os.getppid()}
    rows: list[dict[str, Any]] = []
    for raw_line in ps_output.splitlines():
        parts = raw_line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        raw_pid, raw_ppid, command = parts
        try:
            pid = int(raw_pid)
            ppid = int(raw_ppid)
        except ValueError:
            continue
        parsed_argv = _command_argv(command)
        if pid in self_pids:
            continue
        launcher_argv = _launcher_argv(command)
        if launcher_argv is not None:
            if _is_persistent_main_command(launcher_argv[2:]):
                rows.append({"pid": pid, "ppid": ppid, "argv": launcher_argv})
            continue
        if _is_filtered_command(parsed_argv):
            continue
        argv = parsed_argv if _is_hermes_command(parsed_argv) else _unquoted_hermes_argv(command)
        if not _is_hermes_command(argv):
            continue
        rows.append({"pid": pid, "ppid": ppid, "argv": argv})
    return rows


def _launcher_argv(command: str) -> list[str] | None:
    """`[python, "hermes", *argv]` for a Hermes launcher process, else None."""
    match = _LAUNCHER_COMMAND.match(command)
    if not match or not _is_python_executable(Path(match.group("executable")).name):
        return None
    script = match.group("script")
    script_end = _launcher_script_end(script)
    if script_end is None:
        return None
    trailing = script[script_end:]
    while trailing.startswith(_PS_NEWLINE):
        trailing = trailing[len(_PS_NEWLINE):]
    if trailing and not trailing[0].isspace():
        return None
    try:
        return [match.group("executable"), "hermes", *shlex.split(trailing)]
    except ValueError:
        return None


def _launcher_script_end(script: str) -> int | None:
    """Index just past the launcher script's final statement, or None if not a launcher."""
    import_at = script.find(_LAUNCHER_IMPORT)
    if import_at >= 0:
        exit_at = script.find(_LAUNCHER_EXIT, import_at + len(_LAUNCHER_IMPORT))
        return None if exit_at < 0 else exit_at + len(_LAUNCHER_EXIT)
    entry_at = script.find(_RUNTIME_ENTRY)
    return None if entry_at < 0 else entry_at + len(_RUNTIME_ENTRY)


def _command_argv(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _unquoted_hermes_argv(command: str) -> list[str]:
    match = _PYTHON_COMMAND.match(command)
    if not match:
        return []

    executable = match.group("executable")
    arguments = match.group("arguments")
    if arguments.startswith("-m "):
        try:
            return [executable, *shlex.split(arguments)]
        except ValueError:
            return []

    entrypoint_suffix = "/hermes-agent/hermes"
    entrypoint_end = arguments.find(entrypoint_suffix)
    if entrypoint_end < 0:
        return []
    entrypoint_end += len(entrypoint_suffix)
    if len(arguments) > entrypoint_end and not arguments[entrypoint_end].isspace():
        return []
    entrypoint = arguments[:entrypoint_end]
    try:
        trailing_argv = shlex.split(arguments[entrypoint_end:])
    except ValueError:
        return []
    return [executable, entrypoint, *trailing_argv]


def _is_hermes_command(argv: list[str]) -> bool:
    if not argv:
        return False

    executable = Path(argv[0]).name
    if _is_python_executable(executable):
        if len(argv) >= 2 and Path(argv[1]).parts[-2:] == ("hermes-agent", "hermes"):
            return _is_persistent_main_command(argv[2:])
        if len(argv) < 3 or argv[1] != "-m":
            return False
        if argv[2] == "tui_gateway.entry":
            return True
        return argv[2] == "hermes_cli.main" and _is_persistent_main_command(argv[3:])

    if executable == "node":
        entrypoint = next((argument for argument in argv[1:] if not argument.startswith("-")), "")
        return Path(entrypoint).parts[-3:] == ("ui-tui", "dist", "entry.js")

    return False


def _is_persistent_main_command(arguments: list[str]) -> bool:
    if arguments and arguments[0] in {"--profile", "-p"}:
        if len(arguments) < 2 or not arguments[1]:
            return False
        arguments = arguments[2:]
    elif arguments and arguments[0].startswith("--profile="):
        if not arguments[0].partition("=")[2]:
            return False
        arguments = arguments[1:]
    if not arguments:
        return True
    command = arguments[0]
    if command in _PERSISTENT_MAIN_COMMANDS or command in _PERSISTENT_MAIN_FLAGS:
        return True
    return command == "gateway" and (len(arguments) == 1 or arguments[1] == "run")


def _is_python_executable(executable: str) -> bool:
    suffix = executable.removeprefix("python")
    return executable.startswith("python") and (not suffix or all(part.isdigit() for part in suffix.split(".")))


def _is_filtered_command(argv: list[str]) -> bool:
    if not argv:
        return True
    executable = Path(argv[0]).name
    if executable in _SHELL_NAMES or "-c" in argv:
        return True
    return executable in {"grep", "rg"}


def _process_label(argv: list[str]) -> str:
    names = [Path(token).name for token in argv[:2]]
    return _short_text(" ".join(names), limit=40)


def _short_text(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _observation(
    *,
    observed: bool,
    reason: str,
    rows: list[dict[str, Any]],
    observed_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": HERMES_PROCESS_SCHEMA_VERSION,
        "observed": observed,
        "reason": reason,
        "agent_count": sum(1 for row in rows if row.get("role") == "agent"),
        "process_count": len(rows),
        "rows": rows,
        "source": "local_process_scan",
        "observed_at": observed_at,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = ["HERMES_PROCESS_SCHEMA_VERSION", "observe_hermes_processes"]
