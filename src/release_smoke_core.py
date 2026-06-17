from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class CommandResult:
    command: Sequence[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], int, Mapping[str, str] | None], CommandResult]


def subprocess_runner(command: Sequence[str], timeout_seconds: int, env: Mapping[str, str] | None = None) -> CommandResult:
    run_env = os.environ.copy()
    if env:
        run_env.update({key: str(value) for key, value in env.items()})
    return _run_subprocess(command, timeout_seconds, run_env)


def subprocess_runner_exact_env(
    command: Sequence[str],
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run a subprocess with only the explicit smoke environment."""

    return _run_subprocess(
        command,
        timeout_seconds,
        {key: str(value) for key, value in (env or {}).items()},
    )


def _run_subprocess(command: Sequence[str], timeout_seconds: int, run_env: Mapping[str, str]) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=run_env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr) or f"timed out after {timeout_seconds}s"
        return CommandResult(command, 124, stdout, stderr)
    except OSError as exc:
        return CommandResult(command, 127, "", str(exc))
    return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)


def bounded_text(value: str, limit: int = 1200) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 15].rstrip() + "\n...[truncated]"


def expand_home(value: str | Path | None, env_key: str, default: str) -> str:
    source = str(value) if value is not None else os.environ.get(env_key, default)
    expanded = os.path.expandvars(source)
    if expanded.startswith("<"):
        return expanded
    return str(Path(expanded).expanduser().resolve())


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
