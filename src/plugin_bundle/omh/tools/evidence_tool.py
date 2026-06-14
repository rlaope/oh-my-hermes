from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

OMH_EVIDENCE_SCHEMA = {
    "name": "omh_gather_evidence",
    "description": (
        "Run bounded allowlisted local verification probes and return structured evidence. "
        "This is explicit verification evidence only, not executor dispatch or coding execution."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Commands to run. Each command must match an allowlisted token prefix.",
            },
            "project_root": {
                "type": "string",
                "description": "Root directory that bounds workdir. Defaults to the current working directory.",
            },
            "workdir": {
                "type": "string",
                "description": "Working directory for commands. Must stay inside project_root.",
            },
            "timeout": {
                "type": "integer",
                "description": "Per-command timeout in seconds. Default 60, capped at 180.",
            },
            "truncate": {
                "type": "integer",
                "description": "Maximum output characters per command. Keeps the tail. Default 4000, capped at 20000.",
            },
        },
        "required": ["commands"],
    },
}

SCHEMA_VERSION = "omh_evidence_probe/v1"
_MAX_COMMANDS = 8
_MAX_TIMEOUT_SECONDS = 180
_MAX_TRUNCATE_CHARS = 20_000
_DEFAULT_TIMEOUT_SECONDS = 60
_DEFAULT_TRUNCATE_CHARS = 4_000
_SHELL_METACHAR_RE = re.compile(r"[\n\r;&|`$<>(){}]")
_DEFAULT_ALLOWLIST = (
    "omh --help",
    "omh doctor",
    "omh probe",
    "omh harness validate",
    "omh docs workflows --check",
    "omh release checklist",
    "python -m unittest",
    "python3 -m unittest",
    "python -m compileall",
    "python3 -m compileall",
    "uv run python -m unittest",
    "uv run python -m compileall",
    "uv run python -m src.cli docs workflows --check",
    "uv run python -m src.cli harness validate",
    "git diff --check",
)


def omh_evidence_handler(args: dict, **kwargs) -> str:
    commands = args.get("commands", [])
    if not isinstance(commands, list) or not commands:
        return _json({"error": "commands must be a non-empty list"})
    if len(commands) > _MAX_COMMANDS:
        return _json({"error": f"too many commands: {len(commands)} > {_MAX_COMMANDS}"})

    project_root = _project_root(args, kwargs)
    if not project_root.is_dir():
        return _json({"error": "project_root must be an existing directory", "project_root": str(project_root)})
    workdir = _workdir(args, project_root)
    if isinstance(workdir, dict):
        return _json(workdir)

    timeout = min(_positive_int(args.get("timeout"), _DEFAULT_TIMEOUT_SECONDS), _MAX_TIMEOUT_SECONDS)
    truncate = min(_positive_int(args.get("truncate"), _DEFAULT_TRUNCATE_CHARS), _MAX_TRUNCATE_CHARS)
    allowlist = _allowlist()
    parsed: list[tuple[str, list[str]]] = []
    rejected = []
    for command in commands:
        command_text = str(command or "").strip()
        if not command_text:
            rejected.append({"command": command_text, "reason": "empty command"})
            continue
        if _SHELL_METACHAR_RE.search(command_text):
            rejected.append({"command": command_text, "reason": "shell metacharacters are not allowed"})
            continue
        try:
            tokens = shlex.split(command_text)
        except ValueError as exc:
            rejected.append({"command": command_text, "reason": f"parse failed: {exc}"})
            continue
        if not _matches_allowlist(tokens, allowlist):
            rejected.append({"command": command_text, "reason": "command not in allowlist"})
            continue
        parsed.append((command_text, tokens))

    results = [_rejected_result(item["command"], item["reason"]) for item in rejected]
    for command_text, tokens in parsed:
        results.append(_run_command(command_text, tokens, workdir=workdir, timeout=timeout, truncate=truncate))

    passed_count = sum(1 for result in results if result.get("passed"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "workdir": str(workdir),
        "allowlist": list(allowlist),
        "results": results,
        "all_pass": bool(results) and passed_count == len(results),
        "summary": f"{passed_count}/{len(results)} passed",
        "privacy": "command_output_truncated",
        "claim_boundary": (
            "This is explicit local verification evidence only. It is not executor dispatch, "
            "implementation, review, CI, merge, or Hermes runtime-load evidence."
        ),
    }
    return _json(payload)


def _project_root(args: dict, kwargs: dict) -> Path:
    value = str(args.get("project_root") or kwargs.get("project_root") or os.getcwd())
    return Path(os.path.expandvars(value)).expanduser().resolve()


def _workdir(args: dict, project_root: Path) -> Path | dict[str, str]:
    value = str(args.get("workdir") or project_root)
    workdir = Path(os.path.expandvars(value)).expanduser().resolve()
    try:
        workdir.relative_to(project_root)
    except ValueError:
        return {"error": "workdir must stay within project_root", "workdir": str(workdir), "project_root": str(project_root)}
    if not workdir.is_dir():
        return {"error": "workdir must be an existing directory", "workdir": str(workdir)}
    return workdir


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _allowlist() -> tuple[str, ...]:
    configured = _read_config_allowlist(Path(__file__).resolve().parents[1] / "config.yaml")
    return tuple(configured or _DEFAULT_ALLOWLIST)


def _read_config_allowlist(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    values: list[str] = []
    in_evidence = False
    in_allowlist = False
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_evidence = stripped == "evidence:"
            in_allowlist = False
            continue
        if in_evidence and indent == 2:
            in_allowlist = stripped == "allowlist_prefixes:"
            continue
        if in_evidence and in_allowlist and indent >= 4 and stripped.startswith("- "):
            values.append(_unquote(stripped[2:].strip()))
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _matches_allowlist(tokens: list[str], allowlist: tuple[str, ...]) -> bool:
    for prefix in allowlist:
        prefix_tokens = prefix.split()
        if prefix_tokens and tokens[: len(prefix_tokens)] == prefix_tokens:
            return True
    return False


def _run_command(command_text: str, tokens: list[str], *, workdir: Path, timeout: int, truncate: int) -> dict[str, object]:
    try:
        proc = subprocess.run(
            tokens,
            cwd=str(workdir),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return _rejected_result(command_text, f"command not found: {tokens[0] if tokens else command_text}")
    except subprocess.TimeoutExpired:
        return _rejected_result(command_text, f"timeout after {timeout}s")
    output = (proc.stdout or "") + (proc.stderr or "")
    truncated = len(output) > truncate
    return {
        "command": command_text,
        "exit_code": proc.returncode,
        "output_tail": output[-truncate:] if truncated else output,
        "truncated": truncated,
        "passed": proc.returncode == 0,
        "evidence_type": "observed_local_command",
    }


def _rejected_result(command: str, reason: str) -> dict[str, object]:
    return {
        "command": command,
        "exit_code": -1,
        "output_tail": reason,
        "truncated": False,
        "passed": False,
        "evidence_type": "rejected",
    }


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True)
