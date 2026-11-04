from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from ..plugin_bundle.omh.kanban_board_reader import hermes_root
from ..plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS
from ..system.hermes_install import hermes_install_dir
from ..release_smoke_core import CommandResult, Runner, subprocess_runner_exact_env

_OBSERVATION_PREFIX = "OMH_PLUGIN_LOADER_OBSERVATION="
_PROBE_SCRIPT = r"""
import json

from hermes_cli.plugins import PluginManager

try:
    from hermes_cli.version_info import get_version_info
except ImportError:
    hermes_version = None
else:
    hermes_version = get_version_info().base_version
manager = PluginManager()
manager.discover_and_load(force=True)
loaded = manager._plugins.get("omh")
payload = {
    "enabled": bool(loaded and loaded.enabled),
    "error": None if loaded is None else loaded.error,
    "tools": [] if loaded is None else sorted(loaded.tools_registered),
    "hooks": [] if loaded is None else sorted(loaded.hooks_registered),
    "hermes_version": hermes_version,
}
print("OMH_PLUGIN_LOADER_OBSERVATION=" + json.dumps(payload, sort_keys=True))
"""


def observe_real_loader_registration(
    plugin_dir: Path,
    *,
    python_executable: Path | None = None,
    hermes_code_root: Path | None = None,
    omh_home: Path | str | None = None,
    runner: Runner | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    if not plugin_dir.is_dir():
        return _not_observed("plugin_bundle_not_installed")
    # The code tree owns Hermes' version identity. Without it on the path the
    # isolated host resolves its version as "unknown" and the plugin's
    # requires_hermes gate fails closed -- a mismatch this probe would have
    # manufactured, not a fact about the installed plugin (#2050).
    if hermes_code_root is not None and not (hermes_code_root / "hermes_cli").is_dir():
        return _not_observed("hermes_code_tree_absent")

    execute = runner or subprocess_runner_exact_env
    with TemporaryDirectory(prefix="omh-hermes-loader-") as tmp:
        hermes_home = Path(tmp)
        isolated_plugin = hermes_home / "plugins" / "omh"
        isolated_plugin.parent.mkdir(parents=True)
        shutil.copytree(plugin_dir, isolated_plugin)
        # The plugin refuses to load in a native host whose profile names no
        # store (#2037), and every install `omh setup` makes names one in
        # `plugins.entries.omh.settings.omh_home`. A synthetic config without
        # that binding therefore manufactures a refusal and reports it as a
        # load failure. Copy the binding the real home declares, so the probe
        # observes the load the host would actually get.
        config_lines = ["plugins:", "  enabled:", "    - omh", "  disabled: []"]
        if omh_home is not None:
            # Forward slashes, the way `omh setup` writes the setting: a
            # backslash path would need YAML escaping and reads differently to
            # the text scan the plugin's standalone lane uses.
            # `Path.as_posix()` keeps backslashes on POSIX hosts, so spell the
            # separator out rather than trusting the running platform.
            binding = str(omh_home).replace("\\", "/")
            config_lines.extend(
                [
                    "  entries:",
                    "    omh:",
                    "      settings:",
                    f"        omh_home: {json.dumps(binding)}",
                ]
            )
        (hermes_home / "config.yaml").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
        env = _probe_env(hermes_home, hermes_code_root)
        try:
            command = _loader_command(python_executable, hermes_code_root, execute, env, timeout_seconds)
        except _RuntimeUnavailable as exc:
            return _not_observed(str(exc))
        try:
            result = execute(command, timeout_seconds, env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _not_observed("loader_probe_failed", detail=type(exc).__name__)

    if result.returncode != 0:
        return _not_observed(
            "loader_probe_failed",
            detail=_bounded_detail(result.stderr or result.stdout),
        )
    payload = _parse_observation(result)
    if payload is None:
        return _not_observed("loader_probe_failed", detail="invalid_probe_output")
    if payload.get("hermes_version") == "unknown":
        return _not_observed("hermes_version_unresolved")

    tools = _string_list(payload.get("tools"))
    hooks = _string_list(payload.get("hooks"))
    enabled = payload.get("enabled") is True
    ok = enabled and tools == sorted(PROVIDED_TOOLS) and hooks == sorted(PROVIDED_HOOKS)
    error = payload.get("error")
    return {
        "schema_version": "plugin_loader_observation/v1",
        "observed": True,
        "ok": ok,
        "reason": "registration_matches_manifest" if ok else "registration_mismatch",
        "enabled": enabled,
        "error": "" if error is None else _bounded_detail(str(error)),
        "registered_tools": tools,
        "registered_hooks": hooks,
        "expected_tools": sorted(PROVIDED_TOOLS),
        "expected_hooks": sorted(PROVIDED_HOOKS),
    }


def resolve_hermes_code_root(hermes_home: Path) -> Path:
    """The Hermes checkout a home runs from: its own, else the Hermes root's.

    A profile home (``<root>/profiles/<name>``) carries no checkout of its own;
    the code tree, and the venv ``_find_hermes_python`` prefers, stay at the
    root. Falling back there keeps the probe's interpreter and code tree one
    install, so a healthy profile is not reported as a missing code tree.

    A ``HERMES_PYTHON`` override names the interpreter, so its own tree
    (``<tree>/venv/bin/python``) is the code root when it holds ``hermes_cli``;
    otherwise the home decides, as without the override.
    """
    override = _hermes_python_override()
    if override is not None and len(override.parents) > 2:
        tree = override.parents[2]
        if (tree / "hermes_cli").is_dir():
            return tree
    own = hermes_install_dir(hermes_home)
    if (own / "hermes_cli").is_dir():
        return own
    return hermes_install_dir(hermes_root(hermes_home))


# The OS baseline a Windows child needs to start Python at all. Without
# `SystemRoot` a socket provider cannot initialize, and `import asyncio` dies
# with WinError 10106 before the plugin is ever reached -- which reads as a
# load failure the plugin never caused.
_BASELINE_ENV = ("SystemRoot", "SYSTEMDRIVE", "windir", "TEMP", "TMP", "LOCALAPPDATA")


def _probe_env(hermes_home: Path, hermes_code_root: Path | None) -> dict[str, str]:
    """The isolated child's environment: the probe's own, plus the OS baseline."""
    env = {
        "HOME": str(hermes_home),
        "HERMES_HOME": str(hermes_home),
        "OMH_HOME": str(hermes_home / "omh"),
        "TMPDIR": str(hermes_home),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", ""),
    }
    for key in _BASELINE_ENV:
        value = os.environ.get(key)
        if value:
            env[key] = value
    if hermes_code_root is not None:
        env["PYTHONPATH"] = str(hermes_code_root)
    return env


class _RuntimeUnavailable(ValueError):
    """A present runtime is distinct from an absent installation."""


def _loader_command(python, root, execute, env, timeout):
    override = python or _hermes_python_override()
    if override is not None:
        if not override.is_file():
            raise _RuntimeUnavailable("hermes_python_override_missing")
        return [str(override), "-c", _PROBE_SCRIPT]
    launcher = shutil.which("hermes")
    if launcher:
        direct = _python_shebang(Path(launcher))
        if direct is not None:
            return [str(direct), "-c", _PROBE_SCRIPT]
        try:
            result = execute([launcher, "--print-runtime-command"], min(timeout, 15), env)
            argv = json.loads(result.stdout) if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise _RuntimeUnavailable("hermes_runtime_command_failed") from None
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 64
                or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in argv)
                or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file()):
            raise _RuntimeUnavailable("hermes_runtime_command_failed")
        root = root or _launcher_code_root(Path(launcher))
        if root is None or not (root / "hermes_cli").is_dir():
            raise _RuntimeUnavailable("hermes_code_tree_absent")
        # The printer owns interpreter selection. Read PM's committed dependency
        # environment, never run bootstrap (it repairs/publishes/leases live state).
        # This is a read-only loader observation, not a host startup simulation.
        setup = ("import sys, site; from pathlib import Path; "
                 "sys.dont_write_bytecode = True; "
                 f"sys.path.insert(0, {str(root)!r}); "
                 "from pm.environments import committed_venv, site_packages, owning_home_root; "
                 "from hermes_constants import set_hermes_home_override, reset_hermes_home_override; "
                 f"root = Path({str(root)!r}); "
                 "owner = owning_home_root(root); "
                 "token = set_hermes_home_override(owner); "
                 "environment = committed_venv(root); "
                 "reset_hermes_home_override(token); "
                 "assert environment is not None, 'pm_dependency_environment_absent'; "
                 "selected = site_packages(environment); "
                 "assert selected.is_dir(), 'pm_dependency_site_absent'; "
                 "site.addsitedir(str(selected)); "
                 f"sys.path.insert(0, {str(root)!r}); ")
        return [argv[0], "-I", "-c", setup + _PROBE_SCRIPT]
    legacy = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"
    if legacy.is_file():
        return [str(legacy), "-c", _PROBE_SCRIPT]
    raise _RuntimeUnavailable("hermes_not_installed")


def _launcher_code_root(launcher: Path) -> Path | None:
    target = launcher.resolve()
    for root in target.parents:
        if (root / "hermes_cli").is_dir():
            return root
    return None


def _python_shebang(executable: Path) -> Path | None:
    try:
        first_line = executable.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return None
    if first_line.startswith("#!") and "python" in first_line.lower():
        candidate = Path(first_line[2:].strip())
        return candidate if candidate.is_file() else None
    return None


def _hermes_python_override() -> Path | None:
    override = os.environ.get("HERMES_PYTHON", "").strip()
    return Path(override).expanduser() if override else None


def _find_hermes_python() -> Path | None:
    override = _hermes_python_override()
    if override is not None:
        return override if override.is_file() else None
    candidate = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"
    if candidate.is_file():
        return candidate
    executable = shutil.which("hermes")
    if not executable:
        return None
    try:
        first_line = Path(executable).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return None
    if first_line.startswith("#!") and "python" in first_line.lower():
        candidate = Path(first_line[2:].strip())
        return candidate if candidate.is_file() else None
    return None


def _parse_observation(result: CommandResult) -> dict[str, Any] | None:
    for line in reversed(result.stdout.splitlines()):
        if not line.startswith(_OBSERVATION_PREFIX):
            continue
        try:
            payload = json.loads(line.removeprefix(_OBSERVATION_PREFIX))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if isinstance(item, str))


def _bounded_detail(value: str) -> str:
    return " ".join(value.split())[:300]


def _not_observed(reason: str, *, detail: str = "") -> dict[str, Any]:
    return {
        "schema_version": "plugin_loader_observation/v1",
        "observed": False,
        "ok": False,
        "reason": reason,
        "detail": detail,
        "registered_tools": [],
        "registered_hooks": [],
        "expected_tools": sorted(PROVIDED_TOOLS),
        "expected_hooks": sorted(PROVIDED_HOOKS),
    }


__all__ = ["observe_real_loader_registration", "resolve_hermes_code_root"]
