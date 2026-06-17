from __future__ import annotations

import os
from pathlib import Path
import shutil

COMMAND_PATH_SCHEMA_VERSION = "omh_command_path/v1"
INSTALLED_COMMAND_PATH_CHECK_SCHEMA = "installed_omh_path_check/v1"


def inspect_omh_command_path(command: str = "omh") -> dict[str, object]:
    path_check = inspect_installed_command_path(command)
    found = bool(path_check["ok"])
    path = str(path_check.get("resolved_path") or "")
    return {
        "schema_version": COMMAND_PATH_SCHEMA_VERSION,
        "command": command,
        "found": found,
        "path": path,
        "status": "on_path" if found else "missing_from_path",
        "path_check": path_check,
        "message": (
            f"`{command}` resolves to {path}"
            if found
            else f"`{command}` is not discoverable on PATH for this shell"
        ),
        "next_action": (
            "Run `omh doctor` after setup to verify Hermes registration."
            if found
            else "Use the absolute command path printed by the installer, or add that directory to PATH."
        ),
        "observed": found,
    }


def installed_command_path_check_plan(omh_command: str) -> dict[str, object]:
    command = _normalized_command(omh_command)
    return {
        "schema_version": INSTALLED_COMMAND_PATH_CHECK_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "command_under_test": command,
        "check": path_check_kind(command),
        "resolved_path": None,
        "proof_boundary": (
            "Plan mode does not inspect the operator PATH. Live command smoke resolves the command before running it."
        ),
    }


def inspect_installed_command_path(omh_command: str) -> dict[str, object]:
    command = _normalized_command(omh_command)
    check = path_check_kind(command)
    resolved_path: str | None = None
    ok = False
    if check == "direct_path":
        path = Path(command).expanduser()
        ok = path.is_file() and os.access(path, os.X_OK)
        resolved_path = str(path.resolve()) if path.exists() else None
    else:
        resolved = shutil.which(command)
        ok = bool(resolved)
        resolved_path = str(Path(resolved).resolve()) if resolved else None
    return {
        "schema_version": INSTALLED_COMMAND_PATH_CHECK_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": True,
        "command_under_test": command,
        "check": check,
        "resolved_path": resolved_path,
        "proof_boundary": (
            "This observes command discoverability/executability only; later command smoke steps prove "
            "console-script importability and command behavior."
        ),
    }


def path_check_kind(command: str) -> str:
    separators = [os.sep]
    if os.altsep:
        separators.append(os.altsep)
    return "direct_path" if any(separator in command for separator in separators) else "path_lookup"


def _normalized_command(command: str) -> str:
    return str(command or "omh").strip() or "omh"
