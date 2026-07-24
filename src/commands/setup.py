from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unicodedata

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows compatibility guard.
    termios = None
    tty = None

from ..version import __version__
from ..command_path import COMMAND_PATH_MISSING_NEXT_ACTION, inspect_omh_command_path
from ..capabilities.registry import capability_summary
from ..capabilities.skills import skill_capabilities
from ..config_adapter import ensure_external_dir, external_dirs, read_config, remove_external_dir, write_config
from ..doctor import DEFAULT_DOCTOR_NEXT_ACTION, doctor_ok, recommended_next_action, run_doctor
from ..maintenance.doctor import run_doctor_advisories
from ..executors import CODING_EXECUTOR_TARGETS
from ..hashutil import sha256_file
from ..installer import OmhError, install_skill_pack, uninstall_skill_pack
from ..local_store import atomic_write_text
from ..manifest import read_manifest
from ..menubar_app import setup_menubar_app, uninstall_menubar_app
from ..mcp.host_config import install_mcp_host_config
from ..mcp_bridge import MCP_HOST_CONFIG_RECIPE_HOSTS
from ..plugin_pack import PluginPackError, install_plugin_bundle
from ..probe import probe_capabilities
from ..release import RELEASE_CHANNELS, package_url_for
from ..routing.recommend import recommend_skills
from ..routing.route_plan import build_workflow_route_plan, compact_workflow_route_plan
from ..runtime.artifacts import read_state_result, update_state
from ..setup_profiles import (
    PROJECT_MEMORY_MODES,
    build_setup_profile,
    write_setup_profile,
)
from ..snippet import WORKSPACE_SNIPPET
from ..targets import record_target_observation
from ..team_profiles import (
    TeamProfileError,
    inspect_operating_model,
    inspect_team_profile_pack,
    install_team_profile_pack,
    list_team_profile_packs,
    operating_model_ids,
)
from .common import _action_label, _paths, _print_json, _wants_json
from .language import LANGUAGE_CODES, language_from_env, normalize_language, tr

INSTALLER_COMMAND = "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh"
COMMAND_PACKAGE_STATUS_SCHEMA_VERSION = "command_package_status/v1"
RELEASE_UPDATE_SCHEMA_VERSION = "release_update_status/v1"
SETUP_OPERATOR_SUMMARY_SCHEMA_VERSION = "setup_operator_summary/v1"
DOCTOR_SUMMARY_SCHEMA_VERSION = "doctor_summary/v1"
MCP_SETUP_SCHEMA_VERSION = "omh_mcp_setup/v1"
SELF_UPDATE_REENTRY_ENV = "OMH_UPDATE_COMMAND_PACKAGE_REENTERED"
SELF_UPDATE_SKIP_ENV = "OMH_SKIP_COMMAND_PACKAGE_UPDATE"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def cmd_install(args: argparse.Namespace) -> int:
    language = _resolve_language(args)
    if _wants_json(args):
        payload = _install_result(args)
        _print_json(payload)
    else:
        operation = _install_operation(args)
        progress = _HumanProgress(enabled=True, use_color=_use_color())
        progress.header(f"OMH {operation}", tr(language, "install_subtitle"))
        progress.step(1, 1, tr(language, "step_install_skills"))
        payload = _install_result(args)
        skills = payload.get("skills", [])
        progress.done(tr(language, "done_skills_ready", count=len(skills) if isinstance(skills, list) else 0))
        _print_install_summary(payload, command=operation, language=language)
    return 0


def _install_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    language = _resolve_language(args)
    operation = _install_operation(args)
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.channel == "local" and not (args.from_skills_dir or args.source):
        raise OmhError("local channel requires --from-skills-dir or --source")
    source_dir = Path(args.from_skills_dir or args.source).expanduser().resolve() if (args.from_skills_dir or args.source) else None
    source = str(source_dir) if source_dir else "builtin"
    source_ref = _release_source_ref(args, release)
    previous_release = _previous_release_update_state(paths)
    skill_profile = "full" if getattr(args, "full", False) else "core"
    result = install_skill_pack(
        paths,
        source=source,
        source_dir=source_dir,
        force=args.force,
        dry_run=args.dry_run,
        profile=skill_profile,
    )
    result.update(
        {
            "operation": operation,
            "release_channel": release.channel,
            "release_version": release.version,
            "release_package_url": release.package_url,
            "release_source_ref": source_ref,
            "language": language,
        }
    )
    if not args.dry_run:
        result["runtime_state_path"] = str(paths.runtime_state_path)
        result["runtime_state_key"] = f"last_{operation}"
    result["managed_skills"] = _managed_skills_status(result, dry_run=bool(args.dry_run))
    result["command_package"] = _command_package_status_for_install(
        operation=operation,
        source=source,
        dry_run=bool(args.dry_run),
        command_package_updated=bool(getattr(args, "command_package_updated", False)),
    )
    result["release_update"] = _release_update_status(
        release_channel=release.channel,
        release_version=release.version,
        release_package_url=release.package_url,
        source_ref=source_ref,
        explicit_metadata=_explicit_release_metadata_supplied(args),
        previous=previous_release,
        command_package=result["command_package"],
        dry_run=bool(args.dry_run),
    )
    if not args.dry_run:
        operation_log = _install_operation_log(result, source=source)
        update_state(
            paths,
            {
                "package": "oh-my-hermes",
                "version": __version__,
                "manifest_path": str(paths.manifest_path),
                "manifest_sha256": sha256_file(paths.manifest_path),
                "source": source,
                "release_channel": release.channel,
                "release_version": release.version,
                "release_package_url": release.package_url,
                "release_source_ref": source_ref,
                "release_update": result["release_update"],
                "installed_skills": len(result.get("skills", [])),
                "skills_dir": str(paths.skills_dir),
                f"last_{operation}": operation_log,
            },
        )
    return result


def cmd_update(args: argparse.Namespace) -> int:
    self_update = _command_package_self_update_plan(args)
    if self_update.get("should_update"):
        return _run_command_package_self_update(args, self_update)
    return cmd_install(args)


def _command_package_self_update_plan(args: argparse.Namespace) -> dict[str, object]:
    if bool(getattr(args, "command_package_updated", False)):
        return {"should_update": False, "reason": "command package update already observed"}
    if bool(getattr(args, "dry_run", False)):
        return {"should_update": False, "reason": "dry run does not update the command package"}
    if os.environ.get(SELF_UPDATE_REENTRY_ENV):
        return {"should_update": False, "reason": "already re-entered after command package update"}
    if os.environ.get(SELF_UPDATE_SKIP_ENV):
        return {"should_update": False, "reason": f"{SELF_UPDATE_SKIP_ENV} is set"}
    if getattr(args, "from_skills_dir", None) or getattr(args, "source", None):
        return {"should_update": False, "reason": "explicit skill source updates workflows only"}
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if release.channel == "local" and release.package_url == "local":
        return {"should_update": False, "reason": "local updates require an explicit package source"}
    managed = _managed_command_runtime()
    if not managed["managed"]:
        return {"should_update": False, "reason": managed["reason"]}
    return {
        "should_update": True,
        "release": release,
        "python": managed["python"],
        "venv_dir": managed["venv_dir"],
        "reason": "running from install.sh-managed command package venv",
    }


def _run_command_package_self_update(args: argparse.Namespace, plan: dict[str, object]) -> int:
    release = plan.get("release")
    package_url = str(getattr(release, "package_url", "") or "")
    if not package_url:
        raise OmhError("cannot update command package because no package URL is available")
    python = str(plan.get("python") or sys.executable)
    wants_json = _wants_json(args)
    progress = _HumanProgress(enabled=not wants_json, use_color=_use_color())
    progress.header("OMH update", "Refresh the OMH command package and workflow pack.")
    progress.step(1, 2, "Updating omh command package", detail=package_url)
    completed = subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "--force-reinstall",
            "--upgrade",
            package_url,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "pip install failed").strip()
        raise OmhError(f"command package update failed: {detail}")
    progress.done("command package updated")
    if not wants_json:
        progress.step(2, 2, "Refreshing OMH workflows with the updated command")
    argv = _reentry_argv_with_command_package_updated()
    env = dict(os.environ)
    env[SELF_UPDATE_REENTRY_ENV] = "1"
    rerun = subprocess.run([python, "-m", "omh.cli", *argv], env=env)
    return int(rerun.returncode)


def _reentry_argv_with_command_package_updated() -> list[str]:
    argv = list(sys.argv[1:])
    if "--command-package-updated" not in argv:
        argv.append("--command-package-updated")
    return argv


def _managed_command_runtime() -> dict[str, object]:
    venv_dir = _managed_command_venv_dir()
    if venv_dir is None:
        return {"managed": False, "reason": "HOME or OMH_VENV_DIR is not available"}
    executable = Path(sys.executable).expanduser()
    if not _is_relative_to_without_resolving_symlinks(executable, venv_dir):
        return {
            "managed": False,
            "reason": "current omh command is not running from the install.sh-managed OMH venv",
            "python": str(executable.resolve()),
            "venv_dir": str(venv_dir),
        }
    return {"managed": True, "reason": "", "python": str(executable), "venv_dir": str(venv_dir)}


def _managed_command_venv_dir() -> Path | None:
    explicit = os.environ.get("OMH_VENV_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "omh" / "venv").resolve()
    home = os.environ.get("HOME")
    if home:
        return (Path(home).expanduser() / ".local" / "share" / "omh" / "venv").resolve()
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_relative_to_without_resolving_symlinks(path: Path, parent: Path) -> bool:
    try:
        _normalize_without_final_symlink(path).relative_to(_normalize_without_final_symlink(parent))
    except ValueError:
        return False
    return True


def _normalize_without_final_symlink(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.parent.resolve() / expanded.name


def _install_operation(args: argparse.Namespace) -> str:
    command = str(getattr(args, "command", "install"))
    return command if command in {"convert", "update"} else "install"


def _managed_skills_status(result: dict[str, object], *, dry_run: bool) -> dict[str, object]:
    skills = result.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    return {
        "schema_version": "managed_skills_status/v1",
        "status": "would_update" if dry_run else "updated",
        "count": len(skills),
        "skills_dir": str(result.get("skills_dir", "")),
    }


def _command_package_status_for_install(
    *,
    operation: str,
    source: str,
    dry_run: bool,
    command_package_updated: bool = False,
) -> dict[str, object]:
    status = "unchanged"
    reason = "managed skills were refreshed from the currently installed command package"
    updated = False
    if command_package_updated:
        status = "would_update" if dry_run else "updated"
        updated = not dry_run
        reason = "the installer reported that it refreshed the OMH command package before running this command"
    elif dry_run:
        status = "would_remain_unchanged"
        reason = "dry run previews managed skill changes without changing the command package"
    elif operation == "update" and source == "builtin":
        status = "not_updated"
        reason = "managed skills were refreshed, but the omh command package was not updated in this run"
    elif source != "builtin":
        reason = "managed skills were refreshed from an explicit skill source; the command package was not changed"
    return {
        "schema_version": COMMAND_PACKAGE_STATUS_SCHEMA_VERSION,
        "operation": operation,
        "status": status,
        "updated": updated,
        "source": _command_package_source(command_package_updated=command_package_updated, source=source),
        "reason": reason,
        "update_instruction": INSTALLER_COMMAND,
    }


def _command_package_source(*, command_package_updated: bool, source: str) -> str:
    if command_package_updated:
        return "installer"
    if source == "builtin":
        return "installed_command_package"
    return "explicit_skill_source"


def _release_source_ref(args: argparse.Namespace, release) -> str:
    explicit = str(getattr(args, "source_ref", "") or "").strip()
    if explicit:
        return explicit
    return str(getattr(release, "source_label", "") or "").strip()


def _explicit_release_metadata_supplied(args: argparse.Namespace) -> bool:
    return any(
        str(getattr(args, key, "") or "").strip()
        for key in ("source_ref", "version", "package_url")
    )


def _previous_release_update_state(paths) -> dict[str, object]:
    state, _ = read_state_result(paths)
    state = state or {}
    candidates = [state.get("release_update"), state, state.get("last_update"), state.get("last_install")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if isinstance(candidate.get("current"), dict):
            return candidate["current"]
        release_update = candidate.get("release_update")
        if isinstance(release_update, dict) and isinstance(release_update.get("current"), dict):
            return release_update["current"]
        if any(
            candidate.get(key)
            for key in ("release_channel", "release_version", "release_package_url", "release_source_ref")
        ):
            return candidate
    return {}


def _release_update_status(
    *,
    release_channel: str,
    release_version: str,
    release_package_url: str,
    source_ref: str,
    explicit_metadata: bool,
    previous: dict[str, object],
    command_package: dict[str, object],
    dry_run: bool,
) -> dict[str, object]:
    previous_channel = _string_value(previous.get("release_channel") or previous.get("channel"))
    previous_version = _string_value(previous.get("release_version") or previous.get("version"))
    previous_package_url = _string_value(previous.get("release_package_url") or previous.get("package_url"))
    previous_ref = _string_value(previous.get("release_source_ref") or previous.get("source_ref"))
    current = {
        "release_channel": release_channel,
        "release_version": release_version,
        "release_package_url": release_package_url,
        "release_source_ref": source_ref,
        "package_version": __version__,
    }
    command_status = str(command_package.get("status", ""))
    command_package_changed = bool(command_package.get("updated")) or command_status == "would_update"
    metadata_changed = any(
        [
            _metadata_value_changed(previous_channel, release_channel, explicit=explicit_metadata),
            _metadata_value_changed(previous_version, release_version, explicit=explicit_metadata),
            _metadata_value_changed(previous_package_url, release_package_url, explicit=explicit_metadata),
            _metadata_value_changed(previous_ref, source_ref, explicit=explicit_metadata),
        ]
    )
    changed = command_package_changed or metadata_changed
    if dry_run:
        if command_package_changed:
            status = "would_update"
        elif metadata_changed:
            status = "would_record_metadata"
        else:
            status = "would_refresh"
    elif command_package_changed:
        status = "updated"
    elif metadata_changed:
        status = "metadata_recorded"
    else:
        status = "refreshed"
    return {
        "schema_version": RELEASE_UPDATE_SCHEMA_VERSION,
        "status": status,
        "changed": changed,
        "command_package_changed": command_package_changed,
        "metadata_changed": metadata_changed,
        "previous": {
            "release_channel": previous_channel,
            "release_version": previous_version,
            "release_package_url": previous_package_url,
            "release_source_ref": previous_ref,
        },
        "current": current,
        "display": {
            "version_change": _change_label(previous_version, release_version),
            "source_ref_change": _change_label(previous_ref, source_ref),
            "package_url_change": _change_label(previous_package_url, release_package_url),
        },
    }


def _string_value(value: object) -> str:
    return str(value or "").strip()


def _metadata_value_changed(previous: str, current: str, *, explicit: bool) -> bool:
    if explicit and current:
        return previous != current
    return bool(previous and previous != current)


def _change_label(previous: str, current: str) -> str:
    if previous and current:
        return f"{previous} -> {current}"
    if current:
        return f"(none) -> {current}"
    if previous:
        return f"{previous} -> (none)"
    return ""


def _install_operation_log(result: dict[str, object], *, source: str) -> dict[str, object]:
    managed_skills = result.get("managed_skills", {})
    command_package = result.get("command_package", {})
    release_update = result.get("release_update", {})
    return {
        "operation": str(result.get("operation", "")),
        "source": source,
        "release_channel": str(result.get("release_channel", "")),
        "release_version": str(result.get("release_version", "")),
        "release_package_url": str(result.get("release_package_url", "")),
        "release_source_ref": str(result.get("release_source_ref", "")),
        "release_update": release_update if isinstance(release_update, dict) else {},
        "managed_skills": managed_skills if isinstance(managed_skills, dict) else {},
        "command_package": command_package if isinstance(command_package, dict) else {},
    }


def _setup_operator_summary(
    args: argparse.Namespace,
    paths,
    steps: dict[str, object],
    hermes_native: dict[str, object],
) -> dict[str, object]:
    dry_run = bool(getattr(args, "dry_run", False))
    status = "dry_run" if dry_run else "skills_only" if getattr(args, "skip_apply", False) else "configured"
    plugin = steps.get("plugin", {})
    plugin_status = str(plugin.get("status", "installed")) if isinstance(plugin, dict) else "installed"
    menubar = steps.get("menubar", {})
    menubar_status = str(menubar.get("status", "not_requested")) if isinstance(menubar, dict) else "not_requested"
    team_status = "profile_pack" if getattr(args, "profile_pack", []) else "available"
    mcp = steps.get("mcp", {})
    mcp_mode = str(mcp.get("mode", "none")) if isinstance(mcp, dict) else "none"
    mcp_host_config = mcp.get("host_config", {}) if isinstance(mcp, dict) else {}
    mcp_host_config_status = str(mcp_host_config.get("status", "not_requested")) if isinstance(mcp_host_config, dict) else "not_requested"
    profile = steps.get("profile", {})
    operating_model_id = str(profile.get("operating_model_id", "")) if isinstance(profile, dict) else ""
    memory_policy = profile.get("memory_policy", {}) if isinstance(profile, dict) else {}
    memory_mode = str(memory_policy.get("mode", profile.get("memory_mode", "review-first"))) if isinstance(memory_policy, dict) else "review-first"
    summary = {
        "schema_version": SETUP_OPERATOR_SUMMARY_SCHEMA_VERSION,
        "scope": _setup_scope(args),
        "install_mode": "managed_skills",
        "mcp_mode": mcp_mode,
        "mcp_host": str(mcp.get("host", "generic")) if isinstance(mcp, dict) else "generic",
        "mcp_host_config_status": mcp_host_config_status,
        "mcp_host_config_path": str(mcp_host_config.get("path", "")) if isinstance(mcp_host_config, dict) else "",
        "plugin_mode": plugin_status,
        "menubar_mode": menubar_status,
        "team_mode": team_status,
        "operating_model_id": operating_model_id,
        "memory_mode": memory_mode,
        "memory_policy": memory_policy if isinstance(memory_policy, dict) else {},
        "status": status,
        "requires_hermes_reload": bool(hermes_native.get("requires_hermes_reload", False)),
        "paths": {
            "omh_home": str(paths.omh_home),
            "hermes_home": str(paths.hermes_home),
            "skills_dir": str(paths.skills_dir),
            "hermes_config_path": str(paths.hermes_config_path),
        },
        "command_path": inspect_omh_command_path(),
        "state_log": {},
    }
    if not dry_run:
        summary["state_log"] = {"path": str(paths.runtime_state_path), "entry": "last_setup"}
    install = steps.get("install", {})
    if isinstance(install, dict):
        managed_skills = install.get("managed_skills", {})
        if isinstance(managed_skills, dict):
            summary["managed_skills"] = managed_skills
    return summary


def _setup_scope(args: argparse.Namespace) -> str:
    if getattr(args, "omh_home", None) or getattr(args, "hermes_home", None):
        return "custom"
    return "project" if str(getattr(args, "scope", "") or "").strip().lower() == "project" else "user"


def _doctor_operator_summary(checks: list[object]) -> dict[str, object]:
    check_dicts = [
        {
            "name": str(getattr(check, "name", "")),
            "ok": bool(getattr(check, "ok", False)),
            "severity": str(getattr(check, "severity", "")),
        }
        for check in checks
    ]
    passing = sum(1 for check in check_dicts if check["ok"])
    blocking = sum(1 for check in check_dicts if not check["ok"] and check["severity"] == "blocking")
    warnings = sum(1 for check in check_dicts if check["severity"] == "warning")
    return {
        "schema_version": DOCTOR_SUMMARY_SCHEMA_VERSION,
        "status": "ok" if doctor_ok(checks) else "needs_attention",
        "passing": passing,
        "total": len(check_dicts),
        "blocking": blocking,
        "warnings": warnings,
        "groups": [
            _doctor_group("command", check_dicts, ("command_path",)),
            _doctor_group("managed_skills", check_dicts, ("manifest", "manifest_skills_dir", "local_modifications", "skills_dir", "skill:")),
            _doctor_group("runtime", check_dicts, ("runtime_artifacts", "workflow_state", "runtime_state")),
            _doctor_group("hermes_registration", check_dicts, ("hermes_config", "external_dir", "skill_shadowing", "runtime_context")),
            _doctor_group("targets", check_dicts, ("target_registry", "target_topology")),
            _doctor_group("optional_surfaces", check_dicts, ("plugin_", "team_profile_packs")),
        ],
    }


def _doctor_group(name: str, checks: list[dict[str, object]], prefixes: tuple[str, ...]) -> dict[str, object]:
    members = [
        check
        for check in checks
        if any(str(check.get("name", "")).startswith(prefix) for prefix in prefixes)
    ]
    failed = [check for check in members if not check.get("ok")]
    warning = any(str(check.get("severity", "")) == "warning" for check in members)
    status = "needs_attention" if failed else "warning" if warning else "ok"
    return {
        "name": name,
        "status": status,
        "passing": sum(1 for check in members if check.get("ok")),
        "total": len(members),
        "failed": [str(check.get("name", "")) for check in failed],
    }


def _command_package_status_for_uninstall(result: dict[str, object]) -> dict[str, object]:
    removed = _string_list(result.get("command_package_removed_paths", []))
    would_remove = _string_list(result.get("command_package_would_remove", []))
    kept = result.get("command_package_kept", [])
    kept_items = kept if isinstance(kept, list) else []
    removal_requested = bool(result.get("command_package_remove_requested", False))
    dry_run = bool(result.get("dry_run", False))

    if dry_run and would_remove:
        status = "would_remove"
        reason = "dry run found install.sh-managed command package paths"
    elif removed:
        status = "removed"
        reason = "removed install.sh-managed command package paths"
    elif kept_items:
        status = "kept"
        reason = _first_kept_reason(kept_items)
    elif removal_requested:
        status = "not_found"
        reason = "command package removal was requested, but no install.sh-managed command package paths were found"
    else:
        status = "not_requested"
        reason = "command package removal was not requested"

    return {
        "schema_version": COMMAND_PACKAGE_STATUS_SCHEMA_VERSION,
        "operation": "uninstall",
        "status": status,
        "removal_requested": removal_requested,
        "removed": bool(removed),
        "would_remove": bool(would_remove),
        "kept": bool(kept_items),
        "reason": reason,
        "remaining_command_instruction": tr(
            str(result.get("language", "en")),
            "uninstall_command_still_available",
        )
        if kept_items
        else "",
    }


def _first_kept_reason(items: list[object]) -> str:
    for item in items:
        if isinstance(item, dict):
            reason = str(item.get("reason", "")).strip()
            if reason:
                return reason
    return "command package was not removed"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def cmd_convert(args: argparse.Namespace) -> int:
    args.source = args.from_skills_dir
    args.channel = "local"
    args.version = ""
    args.package_url = ""
    return cmd_install(args)


def cmd_apply(args: argparse.Namespace) -> int:
    result = _apply_result(args)
    if _wants_json(args):
        _print_json(result)
    else:
        _print_apply_summary(result)
    return 0


def _apply_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = ensure_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    if not args.dry_run:
        update_state(
            paths,
            {
                "hermes_config_path": str(paths.hermes_config_path),
                "last_applied_skills_dir": str(paths.skills_dir),
                "external_dir_registered": str(paths.skills_dir) in read_config(paths.hermes_config_path),
            },
        )
    return {"changed": change.changed, "message": change.message, "config": str(paths.hermes_config_path), "skills_dir": str(paths.skills_dir), "dry_run": args.dry_run}


def cmd_uninstall(args: argparse.Namespace) -> int:
    language = _resolve_language(args)
    if args.registration_only and (args.remove_files or args.all or args.purge):
        raise OmhError("--registration-only cannot be combined with --remove-files, --all, or --purge")
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = remove_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    remove_all = bool(args.all or args.purge or (not args.registration_only and not args.remove_files))
    menubar_result = (
        uninstall_menubar_app(paths, dry_run=bool(args.dry_run))
        if remove_all and _uninstall_should_remove_menubar(args)
        else {"status": "not_requested", "operation": "uninstall"}
    )
    result = uninstall_skill_pack(
        paths,
        remove_files=bool(args.remove_files),
        remove_all=remove_all,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        remove_command_package=bool(remove_all and not args.keep_command),
    )
    scope = (
        tr(language, "uninstall_scope_all")
        if remove_all
        else tr(language, "uninstall_scope_files")
        if args.remove_files
        else tr(language, "uninstall_scope_registration")
    )
    result.update(
        {
            "operation": "uninstall",
            "config_changed": change.changed,
            "config_message": change.message,
            "scope": scope,
            "registration_only": bool(args.registration_only),
            "dry_run": args.dry_run,
            "menubar_app": menubar_result,
            "language": language,
        }
    )
    result["command_package"] = _command_package_status_for_uninstall(result)
    if _wants_json(args):
        _print_json(result)
    else:
        _print_uninstall_summary(result, language=language)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    manifest = read_manifest(paths.manifest_path)
    payload = _catalog_aware_list_payload(manifest)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_list_summary(payload, manifest_path=paths.manifest_path, skills_dir=paths.skills_dir)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    language = _resolve_language(args)
    payload = _doctor_result(args)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_doctor_summary(payload, language=language)
    return 0 if payload["ok"] else 1


def _catalog_aware_list_payload(manifest: dict[str, object] | None) -> dict[str, object]:
    payload = dict(manifest or {"schema_version": 1, "skills": [], "message": "not installed"})
    raw_skills = payload.get("skills", [])
    if not isinstance(raw_skills, list):
        raw_skills = []
    capabilities = {
        str(item.get("id")): item
        for item in skill_capabilities()
        if isinstance(item, dict) and item.get("id")
    }
    enriched_skills: list[dict[str, object]] = []
    for raw_skill in raw_skills:
        if not isinstance(raw_skill, dict):
            continue
        record = dict(raw_skill)
        capability = capabilities.get(str(record.get("name") or ""))
        if capability:
            record.update(_list_skill_catalog_fields(capability))
        enriched_skills.append(record)
    payload["skills"] = enriched_skills
    payload["catalog_context"] = _list_catalog_context(enriched_skills)
    return payload


def _list_skill_catalog_fields(capability: dict[str, object]) -> dict[str, object]:
    fields = {
        "description": capability.get("description", ""),
        "category": capability.get("category", ""),
        "phase": capability.get("phase", ""),
        "hermes_role": capability.get("hermes_role", ""),
        "use_for": capability.get("use_for", ""),
        "preferred_usage": capability.get("preferred_usage", ""),
        "awareness_lane": capability.get("awareness_lane", ""),
        "awareness_lane_label": capability.get("awareness_lane_label", ""),
        "workflow_routing_hint": capability.get("workflow_routing_hint", ""),
        "handoff_policy": capability.get("handoff_policy", ""),
        "evidence_boundary": capability.get("evidence_boundary", ""),
    }
    triggers = capability.get("triggers", [])
    if isinstance(triggers, list):
        fields["triggers"] = [str(item) for item in triggers[:10] if str(item)]
    required_inputs = capability.get("required_inputs", [])
    if isinstance(required_inputs, list):
        fields["required_inputs"] = [str(item) for item in required_inputs[:8] if str(item)]
    expected_outputs = capability.get("expected_outputs", [])
    if isinstance(expected_outputs, list):
        fields["expected_outputs"] = [str(item) for item in expected_outputs[:8] if str(item)]
    return fields


def _list_catalog_context(skills: list[dict[str, object]]) -> dict[str, object]:
    names = {str(skill.get("name") or "") for skill in skills}
    described_count = sum(1 for skill in skills if skill.get("description"))
    summary = capability_summary()
    lanes = []
    for lane in summary.get("lanes", []):
        if not isinstance(lane, dict):
            continue
        lane_skills = [str(skill) for skill in lane.get("primary_skills", []) if str(skill) in names]
        if not lane_skills:
            continue
        lanes.append(
            {
                "id": lane.get("id", ""),
                "label": lane.get("label", ""),
                "owner_role": lane.get("owner_role", ""),
                "use_for": lane.get("use_for", ""),
                "primary_skills": lane_skills,
                "examples": lane.get("examples", []),
            }
        )
    return {
        "schema_version": "omh_installed_skill_catalog_context/v1",
        "purpose": (
            "Hermes-facing context for answering what installed OMH workflows are available "
            "without asking the user to approve extra shell catalog commands."
        ),
        "skill_count": len(skills),
        "described_skill_count": described_count,
        "lanes": lanes,
        "direct_response_guidance": [
            "Summarize workflow lanes before listing every skill.",
            "Offer `./omh` or the matching clean skill name when the user wants to choose manually.",
            "Use workflow_routing_hint and evidence_boundary before claiming execution or runtime evidence.",
        ],
        "evidence_boundary": summary.get("evidence_boundary", ""),
    }


def _doctor_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    checks = run_doctor(paths)
    next_action = recommended_next_action(checks)
    summary = _doctor_operator_summary(checks)
    runtime_writable = any(check.name == "runtime_artifacts" and check.ok for check in checks)
    runtime_state_readable = not any(check.name == "runtime_state" and not check.ok for check in checks)
    state_log: dict[str, str] = {}
    if runtime_writable and runtime_state_readable:
        update_state(
            paths,
            {
                "last_doctor": {
                    "ok": doctor_ok(checks),
                    "checks": {check.name: check.ok for check in checks},
                    "summary": summary,
                    "recommended_next_action": next_action,
                }
            },
        )
        state_log = {"path": str(paths.runtime_state_path), "entry": "last_doctor"}
    advisories = run_doctor_advisories(paths)
    return {
        "ok": doctor_ok(checks),
        "checks": [check.__dict__ for check in checks],
        "summary": summary,
        "state_log": state_log,
        "recommended_next_action": next_action,
        "advisories": advisories.to_dict(),
        "language": _resolve_language(args),
    }


def cmd_setup(args: argparse.Namespace) -> int:
    args.with_plugin = True
    language = _setup_language(args)
    paths = _paths(args)
    if _setup_should_interact(args):
        if not _setup_paths_were_explicit(args) and not getattr(args, "scope", None):
            args.scope = _ask_setup_scope(use_color=_use_color(), language=language)
            paths = _paths(args)
        _run_setup_wizard(args, paths, language)
    if getattr(args, "star", False):
        _star_github_repo(language=language, use_color=_use_color(), dry_run=bool(args.dry_run))
    if not args.with_mcp and (
        str(getattr(args, "mcp_host", "generic") or "generic") != "generic"
        or getattr(args, "mcp_config_path", None)
    ):
        raise OmhError("--mcp-host and --mcp-config-path require --with-mcp.")

    progress = _HumanProgress(enabled=not _wants_json(args), use_color=_use_color())
    if not _wants_json(args):
        progress.header(tr(language, "setup_title"), tr(language, "setup_subtitle"))
    setup_menubar = _setup_should_attempt_menubar(args)
    total_steps = 5 + (1 if args.with_mcp else 0) + (1 if args.profile_pack else 0) + (1 if setup_menubar else 0)
    step_index = 1

    progress.step(step_index, total_steps, tr(language, "step_install_skills"), detail=str(paths.skills_dir))
    steps: dict[str, object] = {"install": _install_result(args)}
    install_skills = steps["install"].get("skills", []) if isinstance(steps["install"], dict) else []
    progress.done(tr(language, "done_skills_installed", count=len(install_skills) if isinstance(install_skills, list) else 0))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_register"), detail=str(paths.hermes_config_path))
    if args.skip_apply:
        steps["apply"] = {"skipped": True, "message": "Skipped Hermes config registration because --skip-apply was set."}
        progress.skip(tr(language, "skip_by_flag", flag="--skip-apply"))
    else:
        steps["apply"] = _apply_result(args)
        apply_message = steps["apply"].get("message", "configured") if isinstance(steps["apply"], dict) else "configured"
        progress.done(_config_change_label(language, str(apply_message)))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_plugin"), detail=str(paths.hermes_plugin_dir))
    steps["plugin"] = _plugin_setup_result(args, paths)
    plugin_status = steps["plugin"].get("status", "installed") if isinstance(steps["plugin"], dict) else "installed"
    progress.done(_plugin_status_label(language, str(plugin_status)))
    step_index += 1

    if setup_menubar:
        progress.step(step_index, total_steps, tr(language, "step_menubar"), detail=str(paths.omh_home / "menubar"))
        steps["menubar"] = _menubar_setup_result(args, paths)
        menubar_status = str(steps["menubar"].get("status", "unknown")) if isinstance(steps["menubar"], dict) else "unknown"
        if menubar_status in {"running", "installed", "dry_run"}:
            progress.done(_menubar_status_label(language, menubar_status))
        else:
            reason = str(steps["menubar"].get("reason", menubar_status)) if isinstance(steps["menubar"], dict) else menubar_status
            progress.skip(reason)
        step_index += 1
    else:
        steps["menubar"] = {"schema_version": "menubar_app/v1", "status": "not_requested"}

    steps["mcp"] = _mcp_setup_result(args, paths)
    if args.with_mcp:
        progress.step(step_index, total_steps, tr(language, "step_mcp"), detail=str(paths.runtime_state_path))
        mcp_status = steps["mcp"].get("status", "bridge_requested") if isinstance(steps["mcp"], dict) else "bridge_requested"
        progress.done(tr(language, "done_mcp_bridge", status=_mcp_status_label(language, str(mcp_status))))
        step_index += 1

    if args.profile_pack:
        progress.step(step_index, total_steps, tr(language, "step_team"), detail=", ".join(args.profile_pack))
        steps["team_profiles"] = _team_profile_setup_result(args, paths)
        progress.done(
            tr(language, "done_profile_packs", count=len(steps["team_profiles"]) if isinstance(steps["team_profiles"], list) else 0)
        )
        step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_preferences"))
    steps["profile"] = _setup_profile_result(args, paths)
    profile_executor = steps["profile"].get("default_executor", "choose") if isinstance(steps["profile"], dict) else "choose"
    progress.done(tr(language, "done_default_executor", executor=_executor_summary(language, str(profile_executor))))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_targets"))
    steps["targets"] = record_target_observation(
        paths,
        source="setup",
        dry_run=args.dry_run,
        ensure_config=not args.skip_apply,
        setup_context={
            "apply_skipped": bool(args.skip_apply),
            "with_plugin": True,
            "with_menubar": bool(setup_menubar),
            "with_mcp": bool(args.with_mcp),
            "profile_packs": list(args.profile_pack),
            "setup_profiles": list(args.profile),
            "default_executor": str(getattr(args, "default_executor", "") or ""),
            "operating_model": str(getattr(args, "operating_model", "") or ""),
            "memory_mode": str(getattr(args, "memory_mode", "") or "review-first"),
        },
    )
    target_topology = steps["targets"].get("topology", {}) if isinstance(steps["targets"], dict) else {}
    if isinstance(target_topology, dict):
        progress.done(
            tr(
                language,
                "done_target_topology",
                mode=target_topology.get("mode", "unknown"),
                count=target_topology.get("known_target_count", 0),
            )
        )
    else:
        progress.done(tr(language, "target_recorded"))
    if args.dry_run:
        bootstrap_final_state = (
            "dry run would install generated skills and register the managed OMH skills directory for Hermes discovery"
            if not args.skip_apply
            else "dry run would install generated skills, but Hermes discovery registration would be skipped"
        )
    elif args.skip_apply:
        bootstrap_final_state = "generated skills are installed, but Hermes discovery registration was skipped"
    else:
        bootstrap_final_state = "generated skills are installed in the managed OMH skills directory and registered for Hermes discovery"
    discovery_status = (
        "dry_run_not_observed"
        if args.dry_run
        else "not_registered_skip_apply"
        if args.skip_apply
        else "config_registered_reload_required"
    )
    hermes_native = {
        "schema_version": "hermes_native_setup/v1",
        "mode": "omh_bootstrap",
        "dry_run": bool(args.dry_run),
        "observed": not args.dry_run and not args.skip_apply,
        "observed_scope": "local install/apply steps only; this does not prove Hermes reloaded or used the skill",
        "discovery_status": discovery_status,
        "requires_hermes_reload": not args.skip_apply,
        "normal_user_surface": "Hermes Agent chat and installed Hermes skills",
        "setup_scope": _setup_scope(args),
        "equivalent_hermes_commands": [
            "hermes skills tap add rlaope/oh-my-hermes",
            "hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes",
        ],
        "bootstrap_final_state": bootstrap_final_state,
        "skills_dir": str(paths.skills_dir),
        "hermes_config_path": str(paths.hermes_config_path),
        "hermes_config_key": "skills.external_dirs",
        "mcp_setup": steps["mcp"],
        "target_topology": steps["targets"]["topology"],
        "wrapper_backend_surface": "omh chat interact and runtime commands are adapter/operator contracts, not the normal chat UX",
    }

    if not args.dry_run:
        operator_summary = _setup_operator_summary(args, paths, steps, hermes_native)
        state_patch: dict[str, object] = {
            "last_setup": {
                "ok": True,
                "apply_skipped": bool(args.skip_apply),
                "hermes_native": hermes_native,
                "operator_summary": operator_summary,
                "setup_profile": steps["profile"],
                "mcp_setup": steps["mcp"],
                "menubar_app": steps["menubar"],
                "team_profiles": steps.get("team_profiles", []),
                "target_observation": steps["targets"],
            }
        }
        durable_mcp_host_config = _durable_mcp_host_config_record(steps["mcp"])
        if durable_mcp_host_config:
            state_patch["last_mcp_host_config_install"] = durable_mcp_host_config
        update_state(paths, state_patch)
    else:
        operator_summary = _setup_operator_summary(args, paths, steps, hermes_native)
    payload: dict[str, object] = {
        "ok": True,
        "steps": steps,
        "dry_run": args.dry_run,
        "hermes_native": hermes_native,
        "operator_summary": operator_summary,
        "language": language,
    }
    payload["plugin_distribution"] = steps["plugin"]
    if args.profile_pack:
        payload["team_profiles"] = steps["team_profiles"]
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_setup_summary(payload, language=language)
    return 0


def _setup_should_interact(args: argparse.Namespace) -> bool:
    if getattr(args, "interactive", False):
        return True
    if getattr(args, "no_interactive", False) or getattr(args, "yes", False):
        return False
    if _wants_json(args) or getattr(args, "dry_run", False):
        return False
    if (
        args.profile
        or getattr(args, "default_executor", None)
        or args.profile_pack
        or args.with_mcp
        or getattr(args, "memory_mode", None)
        or getattr(args, "with_menubar", False)
        or getattr(args, "no_menubar", False)
        or args.skip_apply
        or getattr(args, "scope", None)
    ):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _setup_should_attempt_menubar(args: argparse.Namespace) -> bool:
    if getattr(args, "no_menubar", False):
        return False
    if getattr(args, "with_menubar", False):
        return True
    if os.environ.get("OMH_MENUBAR", "1") == "0":
        return False
    if _wants_json(args) or getattr(args, "dry_run", False):
        return False
    if _setup_scope(args) != "user":
        return False
    if _setup_paths_were_explicit(args):
        return False
    return sys.platform == "darwin"


def _uninstall_should_remove_menubar(args: argparse.Namespace) -> bool:
    return _setup_scope(args) == "user" and not _setup_paths_were_explicit(args)


def _resolve_language(args: argparse.Namespace) -> str:
    raw = getattr(args, "language", None)
    try:
        return normalize_language(raw) if raw else language_from_env()
    except ValueError as exc:
        raise OmhError(str(exc)) from exc


def _setup_language(args: argparse.Namespace) -> str:
    # English-first product surface: localized output is explicit opt-in via
    # --language or OMH_LANG, never inferred from the OS locale.
    if _language_was_explicit(args):
        return _resolve_language(args)
    return "en"


def _language_was_explicit(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "language", None) or os.environ.get("OMH_LANG") or os.environ.get("OMH_LANGUAGE"))


def _setup_paths_were_explicit(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "omh_home", None) or getattr(args, "hermes_home", None))


def _ask_setup_scope(*, use_color: bool, language: str) -> str:
    return _ask_single_choice(
        tr(language, "scope_title"),
        [
            tr(language, "scope_intro_1"),
            tr(language, "scope_intro_2"),
        ],
        [
            {
                "choice": "1",
                "value": "user",
                "label": tr(language, "scope_user_label"),
                "description": tr(language, "scope_user_desc"),
            },
            {
                "choice": "2",
                "value": "project",
                "label": tr(language, "scope_project_label"),
                "description": tr(language, "scope_project_desc"),
            },
        ],
        default_choice="1",
        use_color=use_color,
        language=language,
    )


def _run_setup_wizard(args: argparse.Namespace, paths, language: str) -> None:
    use_color = _use_color()
    explicit_profile_packs = list(getattr(args, "profile_pack", []) or [])
    print(_color(tr(language, "setup_title"), "1;36", use_color))
    print(tr(language, "wizard_subtitle"))
    print(f"{tr(language, 'hermes_home')}: {_color(str(paths.hermes_home), '36', use_color)}")
    if paths.hermes_config_path.exists():
        config_text = read_config(paths.hermes_config_path)
        registered = str(paths.skills_dir) in external_dirs(config_text)
        status = tr(language, "status_already_registered") if registered else tr(language, "status_will_register")
        print(f"{tr(language, 'hermes_config')}: {_color(str(paths.hermes_config_path), '36', use_color)} ({status})")
    else:
        print(f"{tr(language, 'hermes_config')}: {_color(str(paths.hermes_config_path), '36', use_color)} ({tr(language, 'status_will_create')})")
    print(f"{tr(language, 'managed_skills')}: {_color(str(paths.skills_dir), '36', use_color)}")

    if not args.profile and not getattr(args, "default_executor", None):
        # No upfront coding-owner question: safety-first records "choose" so
        # Hermes asks at the first coding request instead of setup time.
        args.profile = ["safety-first"]
    if args.with_mcp and str(getattr(args, "mcp_host", "generic") or "generic") == "generic":
        args.mcp_host = _ask_mcp_host(
            use_color=use_color,
            language=language,
            default_host=_default_mcp_host_for_executor(str(getattr(args, "default_executor", "") or "")),
        )
    args.profile_pack = explicit_profile_packs
    print("")


def _star_github_repo(*, language: str, use_color: bool, dry_run: bool = False) -> None:
    if dry_run:
        print(_color(tr(language, "github_star_dry_run"), "33", use_color))
        print("")
        return
    result = _try_star_github_repo()
    if result["ok"]:
        print(_color(tr(language, "github_star_thanks"), "1;32", use_color))
    else:
        reason = str(result.get("reason") or "GitHub star was not recorded")
        print(_color(tr(language, "github_star_failed", reason=reason), "33", use_color))
        print(tr(language, "github_star_continue"))
    print("")


def _try_star_github_repo() -> dict[str, object]:
    command = ["gh", "api", "-X", "PUT", "/user/starred/rlaope/oh-my-hermes"]
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except FileNotFoundError:
        return {"ok": False, "reason": "GitHub CLI `gh` is not installed or not on PATH."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "GitHub CLI star command timed out."}
    except OSError as exc:
        return {"ok": False, "reason": f"GitHub CLI could not run: {exc}"}
    if completed.returncode == 0:
        return {"ok": True, "reason": "starred_or_already_starred"}
    detail = (completed.stderr or completed.stdout or "gh repo star failed").strip()
    return {"ok": False, "reason": detail}


def _ask_mcp_host(*, use_color: bool, language: str, default_host: str = "generic") -> str:
    options = [
        {"choice": "1", "value": "generic", "label": "Generic MCP", "description": tr(language, "mcp_host_generic_desc")},
        {"choice": "2", "value": "codex", "label": "Codex", "description": tr(language, "mcp_host_codex_desc")},
        {"choice": "3", "value": "claude-code", "label": "Claude Code", "description": tr(language, "mcp_host_claude_desc")},
        {"choice": "4", "value": "opencode", "label": "OpenCode", "description": tr(language, "mcp_host_opencode_desc")},
        {"choice": "5", "value": "cursor", "label": "Cursor", "description": tr(language, "mcp_host_cursor_desc")},
    ]
    default_choice = next((option["choice"] for option in options if option["value"] == default_host), "1")
    return _ask_single_choice(
        tr(language, "mcp_host_title"),
        [tr(language, "mcp_host_intro")],
        options,
        default_choice=default_choice,
        use_color=use_color,
        language=language,
    )


def _default_mcp_host_for_executor(executor: str) -> str:
    normalized = executor.strip().lower()
    if normalized == "codex":
        return "codex"
    if normalized == "claude-code":
        return "claude-code"
    return "generic"


def _ask_yes_no(prompt: str, *, default: bool, use_color: bool, note: str = "", language: str = "en") -> bool:
    if _keyboard_menu_available():
        value = _ask_single_choice(
            prompt,
            [note] if note else [],
            [
                {"choice": "1", "value": "yes", "label": tr(language, "yes"), "description": tr(language, "yes_desc")},
                {"choice": "2", "value": "no", "label": tr(language, "no"), "description": tr(language, "no_desc")},
            ],
            default_choice="1" if default else "2",
            use_color=use_color,
            language=language,
        )
        return value == "yes"
    suffix = "Y/n" if default else "y/N"
    if note:
        print(f"  {note}")
    while True:
        value = _ask(prompt, default=suffix, use_color=use_color).strip().lower()
        if not value or value == suffix.lower():
            return default
        if value in {"y", "yes", "1", "예", "네", "はい", "是"}:
            return True
        if value in {"n", "no", "2", "아니요", "いいえ", "否"}:
            return False
        print(_color(tr(language, "invalid_yes_no"), "31", use_color))


def _ask_single_choice(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    *,
    default_choice: str,
    use_color: bool,
    language: str = "en",
) -> str:
    normalized = [_normalize_choice_option(option) for option in options]
    if _keyboard_menu_available():
        return _keyboard_single_choice(title, intro_lines, normalized, default_choice=default_choice, use_color=use_color, language=language)

    print("")
    print(_color(title, "1;32", use_color))
    for line in intro_lines:
        print(f"  {line}")
    for option in normalized:
        suffix = f" ({tr(language, 'recommended')})" if option["choice"] == default_choice else ""
        print(f"  {option['choice']}) {option['label']}{suffix}")
        if option["description"]:
            print(f"     {option['description']}")
    values_by_choice = {option["choice"]: option["value"] for option in normalized}
    values_by_value = {option["value"]: option["value"] for option in normalized}
    while True:
        raw = _ask(tr(language, "select"), default=default_choice, use_color=use_color).strip()
        value = raw or default_choice
        if value in values_by_choice:
            return values_by_choice[value]
        if value in values_by_value:
            return values_by_value[value]
        valid = ", ".join(option["choice"] for option in normalized)
        print(_color(tr(language, "invalid_selection", valid=valid), "31", use_color))


def _normalize_choice_option(option: dict[str, str]) -> dict[str, str]:
    return {
        "choice": str(option.get("choice", "")).strip(),
        "value": str(option.get("value", "")).strip(),
        "label": str(option.get("label", "")).strip(),
        "description": str(option.get("description", "")).strip(),
    }


def _keyboard_single_choice(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    *,
    default_choice: str,
    use_color: bool,
    language: str = "en",
) -> str:
    cursor = _default_choice_index(options, default_choice)
    rendered_option_rows = 0
    first_render = True
    while True:
        lines = _choice_menu_lines(
            title,
            intro_lines,
            options,
            cursor,
            default_choice=default_choice,
            use_color=use_color,
            language=language,
        )
        option_lines = _choice_menu_option_lines(lines, intro_lines)
        if first_render:
            sys.stdout.write("\n".join(lines) + "\n")
            first_render = False
        else:
            sys.stdout.write(f"\033[{rendered_option_rows}F\033[J")
            sys.stdout.write("\n".join(option_lines) + "\n")
        sys.stdout.flush()
        rendered_option_rows = _rendered_terminal_rows(option_lines)
        key = _read_tui_key()
        if key in {"\x03", "\x04"}:
            raise KeyboardInterrupt
        if key in {"\x1b[A", "k"}:
            cursor = (cursor - 1) % len(options)
            continue
        if key in {"\x1b[B", "j"}:
            cursor = (cursor + 1) % len(options)
            continue
        if key in {"\r", "\n", " "}:
            return options[cursor]["value"]
        for index, option in enumerate(options):
            if key == option["choice"]:
                cursor = index
                return option["value"]


def _choice_menu_lines(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    cursor: int,
    *,
    default_choice: str,
    use_color: bool,
    language: str = "en",
) -> list[str]:
    lines = ["", _color(title, "1;32", use_color)]
    for line in intro_lines:
        lines.append(f"  {line}")
    lines.append(_color(f"  {tr(language, 'menu_hint')}", "2", use_color))
    for index, option in enumerate(options):
        active = index == cursor
        pointer = ">" if active else " "
        suffix = f" ({tr(language, 'recommended')})" if option["choice"] == default_choice else ""
        label = f"  {pointer} {option['choice']}) {option['label']}{suffix}"
        if active:
            label = _color(label, "1;36", use_color)
        lines.append(label)
        if option["description"]:
            lines.append(f"      {option['description']}")
    return lines


def _choice_menu_option_lines(lines: list[str], intro_lines: list[str]) -> list[str]:
    option_start = 3 + len(intro_lines)
    return lines[option_start:]


def _rendered_terminal_rows(lines: list[str], columns: int | None = None) -> int:
    if columns is None:
        columns = shutil.get_terminal_size((80, 24)).columns
    columns = max(1, columns)
    rows = 0
    for line in lines:
        width = _visible_text_width(line)
        rows += max(1, (width + columns - 1) // columns)
    return rows


def _visible_text_width(text: str) -> int:
    visible = ANSI_ESCAPE_RE.sub("", text)
    width = 0
    for character in visible:
        if unicodedata.combining(character):
            continue
        category = unicodedata.category(character)
        if category in {"Cc", "Cf"}:
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
    return width


def _default_choice_index(options: list[dict[str, str]], default_choice: str) -> int:
    for index, option in enumerate(options):
        if option["choice"] == default_choice:
            return index
    return 0


def _keyboard_menu_available() -> bool:
    return (
        termios is not None
        and tty is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.environ.get("TERM", "") != "dumb"
        and os.environ.get("OMH_NO_TUI", "") != "1"
    )


def _read_tui_key() -> str:
    if termios is None or tty is None:
        return "\n"
    file_descriptor = sys.stdin.fileno()
    old_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        key = sys.stdin.read(1)
        if key == "\x1b":
            key += sys.stdin.read(2)
        return key
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)


def _ask(prompt: str, *, default: str, use_color: bool) -> str:
    try:
        return input(f"{_color('?', '1;36', use_color)} {prompt} [{default}]: ").strip()
    except EOFError:
        print("")
        return ""


def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


class _HumanProgress:
    def __init__(self, *, enabled: bool, use_color: bool) -> None:
        self.enabled = enabled
        self.use_color = use_color

    def header(self, title: str, subtitle: str) -> None:
        if not self.enabled:
            return
        print(_color(title, "1;36", self.use_color))
        print(subtitle)
        print("")

    def step(self, index: int, total: int, label: str, *, detail: str = "") -> None:
        if not self.enabled:
            return
        prefix = _color(f"[{index}/{total}]", "1;36", self.use_color)
        print(f"{prefix} {label}...", flush=True)
        if detail:
            print(f"      {detail}", flush=True)
        self._brief_tty_pause()

    def done(self, message: str = "done") -> None:
        if not self.enabled:
            return
        print(f"      {_color('[ok]', '1;32', self.use_color)} {message}", flush=True)
        self._brief_tty_pause()

    def skip(self, message: str) -> None:
        if not self.enabled:
            return
        print(f"      {_color('[skip]', '1;33', self.use_color)} {message}", flush=True)
        self._brief_tty_pause()

    @staticmethod
    def _brief_tty_pause() -> None:
        if sys.stdout.isatty() and os.environ.get("OMH_PROGRESS", "1") != "0":
            time.sleep(0.04)


def _print_setup_summary(payload: dict[str, object], *, language: str = "en") -> None:
    use_color = _use_color()
    steps = payload.get("steps", {})
    hermes_native = payload.get("hermes_native", {})
    operator_summary = payload.get("operator_summary", {})
    if not isinstance(steps, dict):
        steps = {}
    if not isinstance(hermes_native, dict):
        hermes_native = {}
    if not isinstance(operator_summary, dict):
        operator_summary = {}

    install = steps.get("install", {})
    profile = steps.get("profile", {})
    targets = steps.get("targets", {})
    skills = install.get("skills", []) if isinstance(install, dict) else []
    topology = targets.get("topology", {}) if isinstance(targets, dict) else {}

    dry_run = bool(payload.get("dry_run", False))
    title = tr(language, "setup_preview_complete") if dry_run else tr(language, "setup_complete")
    print("")
    print(_color(title, "1;36", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    scope_label = tr(language, "setup_scope_" + str(operator_summary.get("scope", "custom")))
    mcp_mode_label = tr(language, "setup_mcp_mode_" + str(operator_summary.get("mcp_mode", "none")))
    status_label = tr(language, "setup_status_" + str(operator_summary.get("status", "configured")))
    print(f"  {tr(language, 'setup_scope', scope=scope_label)}")
    print(f"  {tr(language, 'setup_status', status=status_label)}")
    command_path = operator_summary.get("command_path", {})
    if isinstance(command_path, dict):
        if command_path.get("found"):
            print(f"  {tr(language, 'command_path_found', path=command_path.get('path', 'omh'))}")
        else:
            print(f"  {tr(language, 'command_path_missing')}")
            print(f"  {tr(language, 'command_path_missing_next')}")
    print(f"  {tr(language, 'skills_line', count=len(skills), path=hermes_native.get('skills_dir', ''))}")

    discovery_status = str(hermes_native.get("discovery_status", ""))
    if discovery_status == "config_registered_reload_required":
        print(
            f"  {tr(language, 'registration_configured', path=hermes_native.get('hermes_config_path', ''))}"
        )
    elif discovery_status == "dry_run_not_observed":
        print(f"  {tr(language, 'registration_dry_run')}")
    elif discovery_status == "not_registered_skip_apply":
        print(f"  {tr(language, 'registration_skipped')}")
    else:
        print(f"  {tr(language, 'registration_unknown', status=discovery_status or 'unknown')}")

    if isinstance(profile, dict):
        executor = str(profile.get("default_executor", ""))
        if executor:
            print(f"  {tr(language, 'default_handoff', summary=_executor_summary(language, executor))}")
            if executor == "choose":
                print(f"  {tr(language, 'default_handoff_pin_hint')}")

    if isinstance(topology, dict):
        print(
            f"  {tr(language, 'target_topology', mode=topology.get('mode', 'unknown'), count=topology.get('known_target_count', 0))}"
        )
    plugin = payload.get("plugin_distribution")
    if isinstance(plugin, dict):
        print(f"  {tr(language, 'plugin_bridge', status=_plugin_status_label(language, str(plugin.get('status', 'installed'))))}")

    menubar = steps.get("menubar")
    if isinstance(menubar, dict) and str(menubar.get("status", "not_requested")) != "not_requested":
        status = str(menubar.get("status", "unknown"))
        print(f"  {tr(language, 'menubar_helper', status=_menubar_status_label(language, status))}")

    if str(operator_summary.get("mcp_mode", "none")) == "bridge_requested":
        print(f"  {tr(language, 'setup_mcp_mode', mode=mcp_mode_label)}")

    team_profiles = payload.get("team_profiles")
    if isinstance(team_profiles, list) and team_profiles:
        print(f"  {tr(language, 'team_activated', count=len(team_profiles))}")

    print(_color(tr(language, "next"), "1;32", use_color))
    if dry_run:
        print(f"  {tr(language, 'setup_next_dry')}")
    else:
        print(f"  {tr(language, 'setup_next_reload')}")
        print(f"  {tr(language, 'setup_next_prompt')}")
        print(f"  {tr(language, 'setup_next_verify')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_doctor_summary(payload: dict[str, object], *, language: str = "en") -> None:
    use_color = _use_color()
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    ok = bool(payload.get("ok", False))
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    passing = int(summary.get("passing", sum(1 for check in checks if isinstance(check, dict) and check.get("ok"))))
    total = int(summary.get("total", len(checks)))
    title_key = "doctor_complete" if ok else "doctor_needs_attention"
    print(_color(tr(language, title_key), "1;36" if ok else "1;33", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'doctor_status', status=tr(language, 'doctor_status_ok' if ok else 'doctor_status_needs_attention'))}")
    print(f"  {tr(language, 'doctor_checks', passing=passing, total=total)}")
    print(
        f"  {tr(language, 'doctor_issue_counts', blocking=summary.get('blocking', 0), warnings=summary.get('warnings', 0))}"
    )
    groups = summary.get("groups", [])
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_key = "doctor_group_" + str(group.get("name", "unknown"))
            status_key = "doctor_group_status_" + str(group.get("status", "ok"))
            print(
                f"  {tr(language, group_key)}: {tr(language, status_key)} "
                f"({group.get('passing', 0)}/{group.get('total', 0)})"
            )
    observation_lines = _doctor_observation_boundary_lines(checks, language=language)
    if observation_lines:
        print(_color(tr(language, "doctor_observation_boundaries"), "1;32", use_color))
        for line in observation_lines:
            print(f"  {line}")
    state_log = payload.get("state_log", {})
    if isinstance(state_log, dict) and state_log.get("path") and state_log.get("entry"):
        print(f"  {tr(language, 'state_log', path=state_log.get('path'), entry=state_log.get('entry'))}")
    for check in checks:
        if not isinstance(check, dict) or (check.get("ok") and check.get("severity") != "warning"):
            continue
        name = check.get("name", "unknown")
        message = check.get("message", "")
        remediation = check.get("remediation", "") or check.get("next_action", "")
        print(f"  - {name}: {message}")
        if remediation:
            print(f"    {tr(language, 'doctor_fix')}: {remediation}")
    _print_doctor_advice(payload, use_color=use_color)
    next_action = str(payload.get("recommended_next_action", "")).strip()
    print(_color(tr(language, "next"), "1;32", use_color))
    if next_action:
        print(f"  {_doctor_human_next_action(next_action, language=language)}")
    print(f"  {tr(language, 'doctor_boundary')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_doctor_advice(payload: dict[str, object], *, use_color: bool) -> None:
    """Render the read-only Advice lane, separate from doctor checks.

    Advice never affects the doctor status or exit code; it is a default-on,
    plain-text section that surfaces the ``hermes_config_advice`` advisory lane.
    """
    advisories = payload.get("advisories", {})
    if not isinstance(advisories, dict):
        return
    entries = advisories.get("entries", [])
    if not isinstance(entries, list):
        return
    actionable = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("status") == "advice"
    ]
    if not actionable:
        return
    print(_color("Advice (read-only; does not affect doctor status)", "1;36", use_color))
    for entry in actionable:
        check_id = entry.get("check_id", "unknown")
        observed = entry.get("observed", "")
        remediation = entry.get("remediation", "")
        print(f"  - {check_id}: {observed}")
        if remediation:
            print(f"    Suggestion: {remediation}")


def _doctor_human_next_action(next_action: str, *, language: str) -> str:
    if next_action == DEFAULT_DOCTOR_NEXT_ACTION:
        return tr(language, "doctor_default_next_action")
    if next_action == COMMAND_PATH_MISSING_NEXT_ACTION:
        return tr(language, "command_path_missing_next")
    return next_action


def _doctor_observation_boundary_lines(checks: list[object], *, language: str) -> list[str]:
    check_map = {str(check.get("name", "")): check for check in checks if isinstance(check, dict)}
    lines: list[str] = []
    plugin_bundle = check_map.get("plugin_bundle")
    plugin_register = check_map.get("plugin_register_smoke")
    plugin_runtime = check_map.get("plugin_runtime_observed")

    if plugin_register:
        if plugin_register.get("ok"):
            lines.append(tr(language, "doctor_plugin_bridge_ready"))
        else:
            lines.append(tr(language, "doctor_plugin_bridge_needs_attention"))
    elif plugin_bundle:
        lines.append(tr(language, "doctor_plugin_bridge_not_installed"))

    if plugin_runtime:
        if plugin_runtime.get("observed") and str(plugin_runtime.get("severity", "")) == "ok":
            lines.append(tr(language, "doctor_plugin_runtime_observed"))
        elif plugin_runtime.get("observed"):
            lines.append(tr(language, "doctor_plugin_runtime_historical"))
        else:
            lines.append(tr(language, "doctor_plugin_runtime_not_observed"))

    return lines


def _print_uninstall_summary(payload: dict[str, object], *, language: str = "en") -> None:
    use_color = _use_color()
    dry_run = bool(payload.get("dry_run", False))
    title = tr(language, "uninstall_preview_complete") if dry_run else tr(language, "uninstall_complete")
    removed = payload.get("removed_paths", [])
    would_remove = payload.get("would_remove", [])
    kept = payload.get("kept_paths", [])
    if not isinstance(removed, list):
        removed = []
    if not isinstance(would_remove, list):
        would_remove = []
    if not isinstance(kept, list):
        kept = []
    command_kept = payload.get("command_package_kept", [])
    if not isinstance(command_kept, list):
        command_kept = []
    command_kept_paths = {
        item.get("path", "")
        for item in command_kept
        if isinstance(item, dict)
    }

    print("")
    print(_color(title, "1;36", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'scope')}: {payload.get('scope', '')}")
    config_message = _config_change_label(language, str(payload.get("config_message", "")))
    print(f"  {tr(language, 'uninstall_config', message=config_message)}")
    if dry_run:
        print(f"  {tr(language, 'uninstall_would_remove', count=len(would_remove))}")
        for path in would_remove[:8]:
            print(f"    - {path}")
    else:
        print(f"  {tr(language, 'uninstall_removed', count=len(removed))}")
        for path in removed[:8]:
            print(f"    - {path}")
    if not removed and not would_remove:
        print(f"  {tr(language, 'uninstall_none')}")
    for item in kept:
        if isinstance(item, dict):
            if item.get("path", "") in command_kept_paths:
                continue
            print(f"  {tr(language, 'kept')}: {item.get('path', '')} ({item.get('reason', '')})")
    print(_color(tr(language, "next"), "1;32", use_color))
    command_removed = payload.get("command_package_removed_paths", [])
    command_would_remove = payload.get("command_package_would_remove", [])
    if not isinstance(command_removed, list):
        command_removed = []
    if not isinstance(command_would_remove, list):
        command_would_remove = []
    if dry_run and command_would_remove:
        print(f"  {tr(language, 'uninstall_command_would_remove', count=len(command_would_remove))}")
    elif command_removed:
        print(f"  {tr(language, 'uninstall_command_removed', count=len(command_removed))}")
    elif command_kept:
        print(f"  {tr(language, 'uninstall_command_kept')}")
        print(f"  {tr(language, 'uninstall_command_still_available')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_install_summary(payload: dict[str, object], *, command: str, language: str = "en") -> None:
    use_color = _use_color()
    skills = payload.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    dry_run = bool(payload.get("dry_run", False))
    label = "update" if command == "update" else "install"
    title = tr(language, "install_preview_complete", label=label) if dry_run else tr(language, "install_complete", label=label)
    source = str(payload.get("source", "builtin"))
    source_label = tr(language, "source_builtin") if source == "builtin" else source
    print("")
    print(_color(title, "1;36", use_color))
    if label == "update":
        _print_update_release_card(payload, source_label=source_label, language=language, use_color=use_color)
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'skills_line', count=len(skills), path=payload.get('skills_dir', ''))}")
    release_update = payload.get("release_update", {})
    command_package = payload.get("command_package", {})
    if isinstance(command_package, dict):
        command_status = str(command_package.get("status", "")).strip()
        if command_status == "updated":
            change = _command_package_display_change(payload, release_update if isinstance(release_update, dict) else {})
            print(_color(f"  {tr(language, 'command_package_update_line', change=change)}", "1;32", use_color))
        elif label == "update" and source == "builtin" and not dry_run:
            print(_color(f"  {tr(language, 'command_package_not_updated_line')}", "1;33", use_color))
    print(f"  {tr(language, 'source', source=source_label)}")
    channel = str(payload.get("release_channel", "")).strip()
    package_url = str(payload.get("release_package_url", "")).strip()
    if channel:
        print(f"  {tr(language, 'release_channel', channel=channel)}")
    if package_url and package_url != "local":
        package_url_key = "recorded_package_url" if source == "builtin" else "package_url"
        print(f"  {tr(language, package_url_key, url=package_url)}")
    if isinstance(release_update, dict):
        display = release_update.get("display", {})
        if isinstance(display, dict):
            version_change = str(display.get("version_change", "")).strip()
            source_ref_change = str(display.get("source_ref_change", "")).strip()
            if version_change and str(payload.get("release_channel", "")) == "stable":
                print(f"  {tr(language, 'release_version_change', change=version_change)}")
            if source_ref_change:
                print(f"  {tr(language, 'release_source_ref_change', change=source_ref_change)}")
        status = str(release_update.get("status", "")).strip()
        if status:
            print(f"  {tr(language, 'release_update_status', status=status)}")
    state_path = str(payload.get("runtime_state_path", "")).strip()
    state_key = str(payload.get("runtime_state_key", "")).strip()
    if state_path and state_key:
        print(f"  {tr(language, 'state_log', path=state_path, entry=state_key)}")
    print(_color(tr(language, "next"), "1;32", use_color))
    if dry_run:
        print(f"  {tr(language, 'install_next_dry')}")
    elif label == "update":
        print(f"  {tr(language, 'update_next')}")
        if source == "builtin" and not (isinstance(command_package, dict) and command_package.get("updated")):
            print(f"  {tr(language, 'update_command_next')}")
    else:
        print(f"  {tr(language, 'install_next')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_update_release_card(
    payload: dict[str, object], *, source_label: str, language: str, use_color: bool
) -> None:
    release_update = payload.get("release_update", {})
    if not isinstance(release_update, dict):
        release_update = {}
    previous = release_update.get("previous", {})
    if not isinstance(previous, dict):
        previous = {}
    current = release_update.get("current", {})
    if not isinstance(current, dict):
        current = {}
    skills = payload.get("skills", [])
    workflow_count = len(skills) if isinstance(skills, list) else 0
    dry_run = bool(payload.get("dry_run", False))
    command_package = payload.get("command_package", {})
    command_updated = isinstance(command_package, dict) and bool(command_package.get("updated"))
    command_key = (
        "update_card_command_preview"
        if dry_run
        else "update_card_command_updated"
        if command_updated
        else "update_card_command_unchanged"
    )
    previous_release = _release_card_identity(previous, language=language)
    current_release = _release_card_identity(current, language=language)
    current_label = "update_card_available_release" if dry_run else "update_card_installed_release"
    notes_label = "update_card_release_preview" if dry_run else "update_card_release_notes"
    workflows_label = "update_card_workflows_to_refresh" if dry_run else "update_card_workflows_refreshed"
    title = tr(language, "update_card_title")

    print(_color("╔═══════════════════════════════════════════════════════════╗", "1;34", use_color))
    print(_color(f"║{title:^59}║", "1;34", use_color))
    print(_color("╚═══════════════════════════════════════════════════════════╝", "1;34", use_color))
    print(f"  {tr(language, 'update_card_previous_release', release=previous_release)}")
    print(f"  {tr(language, current_label, release=current_release)}")
    print(f"  {tr(language, 'update_card_install_method', source=source_label)}")
    print("")
    print(f"  {tr(language, notes_label)}")
    print(f"    - {tr(language, workflows_label, count=workflow_count)}")
    print(f"    - {tr(language, command_key)}")
    if previous_release != current_release:
        print(f"    - {tr(language, 'release_version_change', change=f'{previous_release} -> {current_release}')}")
    print("")


def _release_card_identity(release: dict[str, object], *, language: str) -> str:
    version = _string_value(release.get("release_version") or release.get("version"))
    if version:
        return version
    source_ref = _string_value(release.get("release_source_ref") or release.get("source_ref"))
    if source_ref:
        return source_ref
    return tr(language, "update_card_release_not_recorded")


def _command_package_display_change(payload: dict[str, object], release_update: dict[str, object]) -> str:
    display = release_update.get("display", {})
    if not isinstance(display, dict):
        display = {}
    previous = release_update.get("previous", {})
    if not isinstance(previous, dict):
        previous = {}
    current = release_update.get("current", {})
    if not isinstance(current, dict):
        current = {}
    channel = str(payload.get("release_channel", "")).strip()
    version_change = str(display.get("version_change", "")).strip()
    source_ref_change = str(display.get("source_ref_change", "")).strip()
    package_url_change = str(display.get("package_url_change", "")).strip()
    previous_version = str(previous.get("release_version", "")).strip()
    current_version = str(current.get("release_version", "")).strip()
    previous_ref = str(previous.get("release_source_ref", "")).strip()
    current_ref = str(current.get("release_source_ref", "")).strip()
    previous_package_url = str(previous.get("release_package_url", "")).strip()
    current_package_url = str(current.get("release_package_url", "")).strip()
    version_changed = bool(current_version and previous_version != current_version)
    source_ref_changed = bool(current_ref and previous_ref != current_ref)
    package_url_changed = bool(current_package_url and previous_package_url != current_package_url)
    if channel == "stable" and version_changed and version_change:
        return version_change
    if channel == "stable" and current_version and source_ref_changed and source_ref_change:
        return f"{current_version} ({source_ref_change})"
    if channel == "stable" and current_version and package_url_changed and package_url_change:
        return f"{current_version} (package URL changed)"
    if source_ref_changed and source_ref_change:
        return source_ref_change
    if package_url_changed and package_url_change:
        return package_url_change
    if channel == "stable" and current_version:
        return f"{current_version} -> {current_version}" if previous_version == current_version else current_version
    if current_ref:
        return f"{current_ref} -> {current_ref}" if previous_ref == current_ref else current_ref
    package_url = str(payload.get("release_package_url", "")).strip()
    return package_url or "updated"


def _print_apply_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    dry_run = bool(payload.get("dry_run", False))
    changed = bool(payload.get("changed", False))
    title = "OMH apply preview complete." if dry_run else "OMH apply complete."
    print(_color(title, "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Config: {payload.get('config', '')}")
    print(f"  Managed skills: {payload.get('skills_dir', '')}")
    if dry_run:
        status = "would update Hermes registration" if changed else "registration already up to date"
    else:
        status = "updated Hermes registration" if changed else "registration already up to date"
    message = str(payload.get("message", "")).strip()
    print(f"  Status: {status}")
    if message:
        print(f"  Detail: {message}")
    print(_color("Next", "1;32", use_color))
    print("  Restart or reload Hermes Agent before expecting chat to see new skills.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_list_summary(payload: dict[str, object], *, manifest_path: Path, skills_dir: Path) -> None:
    use_color = _use_color()
    skills = payload.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    print(_color("OMH managed skills", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    if not skills:
        print("  Status: not installed")
        print(f"  Manifest: {manifest_path}")
        print(f"  Managed skills: {skills_dir}")
        print(_color("Next", "1;32", use_color))
        print("  Run `omh setup` to install managed Hermes skills.")
        print(f"  {tr('en', 'machine_readable')}")
        return
    package = str(payload.get("package", "oh-my-hermes"))
    installed_at = str(payload.get("installed_at", ""))
    print(f"  Package: {package}")
    print(f"  Skills: {len(skills)} managed skill(s) at {skills_dir}")
    if installed_at:
        print(f"  Installed at: {installed_at}")
    print(f"  Manifest: {manifest_path}")
    names = [str(skill.get("name", "")) for skill in skills if isinstance(skill, dict) and skill.get("name")]
    shown = names[:12]
    if shown:
        print("  Names: " + ", ".join(shown) + (" ..." if len(names) > len(shown) else ""))
    catalog = payload.get("catalog_context")
    if isinstance(catalog, dict):
        lanes = catalog.get("lanes", [])
        if isinstance(lanes, list) and lanes:
            print(_color("Workflow lanes", "1;32", use_color))
            for lane in lanes[:6]:
                if not isinstance(lane, dict):
                    continue
                lane_skills = lane.get("primary_skills", [])
                if not isinstance(lane_skills, list):
                    lane_skills = []
                skill_names = ", ".join(str(skill) for skill in lane_skills[:5])
                overflow = f" +{len(lane_skills) - 5}" if len(lane_skills) > 5 else ""
                label = str(lane.get("label") or lane.get("id") or "workflow lane")
                use_for = _short_summary(str(lane.get("use_for", "")), limit=96)
                print(f"  - {label}: {skill_names}{overflow}")
                if use_for:
                    print(f"    Use for: {use_for}")
    print(_color("Next", "1;32", use_color))
    print("  Run `omh doctor` to verify Hermes registration.")
    if skills:
        print("  In chat, ask Hermes what OMH can do or type `./omh` to open the workflow picker.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_recommend_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    recommendations = payload.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    print(_color("OMH recommendation", "1;36", use_color))
    print(f"Query: {payload.get('query', '')}")
    if not recommendations:
        print("No recommendations.")
        print(f"  {tr('en', 'machine_readable')}")
        return
    for index, recommendation in enumerate(recommendations, start=1):
        if not isinstance(recommendation, dict):
            continue
        name = str(recommendation.get("skill", "unknown"))
        confidence = str(recommendation.get("confidence", "unknown"))
        print(f"{index}. {name} [{confidence}]")
        description = _short_summary(str(recommendation.get("description", "")), limit=120)
        if description:
            print(f"   {description}")
        next_action = str(recommendation.get("next_action", "")).strip()
        if next_action:
            print(f"   Next action: {_action_label(next_action)}")
        why = _short_summary(str(recommendation.get("why", "")), limit=120)
        if why:
            print(f"   Why: {why}")
    workflow_route_plan = payload.get("workflow_route_plan")
    if isinstance(workflow_route_plan, dict):
        steps = workflow_route_plan.get("steps", [])
        if isinstance(steps, list) and steps:
            path = " -> ".join(str(step.get("skill", "")) for step in steps if isinstance(step, dict))
            if path:
                print(_color("Workflow path", "1;35", use_color))
                print(f"  {path}")
    print(_color("Boundary", "1;32", use_color))
    print("  A recommendation is routing guidance, not execution or verification evidence.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_profile_list_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    packs = payload.get("packs", [])
    if not isinstance(packs, list):
        packs = []
    models = payload.get("operating_models", [])
    if not isinstance(models, list):
        models = []
    print(_color("OMH profile packs", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Default install: {payload.get('default_install', 'none')}")
    print(f"  Operating models: {len(models)}")
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", "unknown"))
        title = str(model.get("title", model_id))
        summary = _short_summary(str(model.get("summary", "")), limit=110)
        print(f"  - {model_id}: {title}")
        if summary:
            print(f"    {summary}")
    print(f"  Available packs: {len(packs)}")
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        pack_id = str(pack.get("id", "unknown"))
        title = str(pack.get("title", pack_id))
        summary = _short_summary(str(pack.get("summary", "")), limit=110)
        print(f"  - {pack_id}: {title}")
        if summary:
            print(f"    {summary}")
    print(_color("Next", "1;32", use_color))
    print("  Inspect a model or pack with `omh profile inspect <id>`.")
    print("  Install one with `omh setup --profile-pack <id>`.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_profile_inspect_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    if "model" in payload:
        model = payload.get("model", {})
        if not isinstance(model, dict):
            model = {}
        model_id = str(model.get("id", "unknown"))
        print(_color(f"OMH operating model: {model.get('title', model_id)}", "1;36", use_color))
        print(_color("Summary", "1;32", use_color))
        print(f"  ID: {model_id}")
        summary = str(model.get("summary", "")).strip()
        use_when = str(model.get("use_when", "")).strip()
        if summary:
            print(f"  Summary: {summary}")
        if use_when:
            print(f"  Use when: {use_when}")
        print(f"  Default executor: {model.get('default_executor', 'choose')}")
        packs = model.get("recommended_profile_packs", [])
        if isinstance(packs, list) and packs:
            print(f"  Recommended profile packs: {', '.join(str(item) for item in packs)}")
        guidance = model.get("runtime_guidance", [])
        if isinstance(guidance, list) and guidance:
            print(_color("Runtime guidance", "1;32", use_color))
            for item in guidance:
                print(f"  - {item}")
        print(_color("Next", "1;32", use_color))
        print(f"  {model.get('setup_command', f'omh setup --operating-model {model_id}')}")
        boundary = str(model.get("claim_boundary", "")).strip()
        if boundary:
            print(_color("Boundary", "1;32", use_color))
            print(f"  {boundary}")
        print(f"  {tr('en', 'machine_readable')}")
        return
    pack = payload.get("pack", {})
    if not isinstance(pack, dict):
        pack = {}
    roles = pack.get("roles", [])
    if not isinstance(roles, list):
        roles = []
    pack_id = str(pack.get("id", "unknown"))
    print(_color(f"OMH profile pack: {pack.get('title', pack_id)}", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  ID: {pack_id}")
    summary = str(pack.get("summary", "")).strip()
    use_when = str(pack.get("use_when", "")).strip()
    if summary:
        print(f"  Summary: {summary}")
    if use_when:
        print(f"  Use when: {use_when}")
    print(f"  Roles: {len(roles)}")
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("id", "unknown"))
        title = str(role.get("title", role_id))
        purpose = _short_summary(str(role.get("purpose", "")), limit=120)
        print(f"  - {role_id}: {title}")
        if purpose:
            print(f"    {purpose}")
    install_command = str(pack.get("install_command", "")).strip()
    if install_command:
        print(_color("Next", "1;32", use_color))
        print(f"  {install_command}")
    boundary = str(pack.get("claim_boundary", "")).strip()
    if boundary:
        print(_color("Boundary", "1;32", use_color))
        print(f"  {boundary}")
    print(f"  {tr('en', 'machine_readable')}")


def _print_probe_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    counts = {status: 0 for status in ("available", "missing", "unknown", "unverified")}
    for capability in capabilities:
        if isinstance(capability, dict):
            status = str(capability.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
    print(_color("OMH capability probe", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  OMH home: {payload.get('omh_home', '')}")
    print(f"  Hermes home: {payload.get('hermes_home', '')}")
    print(
        "  Capabilities: "
        f"{counts.get('available', 0)} available, "
        f"{counts.get('missing', 0)} missing, "
        f"{counts.get('unknown', 0)} unknown, "
        f"{counts.get('unverified', 0)} unverified"
    )
    topology = payload.get("target_topology", {})
    if isinstance(topology, dict):
        print(
            "  Target topology: "
            f"{topology.get('mode', 'unknown')} "
            f"({topology.get('known_target_count', 0)} known target(s))"
        )
    print(f"  Plugin distribution ready: {payload.get('plugin_distribution_ready', False)}")
    print(f"  Native integration claim ready: {payload.get('native_integration_claim_ready', False)}")
    print(_color("Details", "1;32", use_color))
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        status = str(capability.get("status", "unknown"))
        name = str(capability.get("name", "unknown"))
        message = _short_summary(str(capability.get("message", "")), limit=120)
        print(f"  - {name}: {status}")
        if message:
            print(f"    {message}")
    boundary = str(payload.get("claim_boundary", "")).strip()
    if boundary:
        print(_color("Boundary", "1;32", use_color))
        print(f"  {boundary}")
    parity = payload.get("parity_matrix")
    if isinstance(parity, dict):
        _print_probe_parity_summary(parity, use_color=use_color)
    roadmap = payload.get("capability_gap_roadmap")
    if isinstance(roadmap, dict):
        _print_probe_roadmap_summary(roadmap, use_color=use_color)
    print(f"  {tr('en', 'machine_readable')}")


def _print_probe_parity_summary(payload: dict[str, object], *, use_color: bool) -> None:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    print(_color("Parity matrix", "1;32", use_color))
    print(
        "  Common oh-my runtime axes: "
        f"{summary.get('available', 0)} available, "
        f"{summary.get('partial', 0)} partial, "
        f"{summary.get('planned', 0)} planned, "
        f"{summary.get('deferred', 0)} deferred"
    )
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        title = str(capability.get("title", "unknown"))
        status = str(capability.get("status", "unknown"))
        missing = _short_summary(str(capability.get("missing_piece", "")), limit=108)
        print(f"  - {title}: {status}")
        if missing:
            print(f"    Gap: {missing}")
    boundary = str(payload.get("claim_boundary", "")).strip()
    if boundary:
        print(_color("Parity boundary", "1;32", use_color))
        print(f"  {_short_summary(boundary, limit=132)}")


def _print_probe_roadmap_summary(payload: dict[str, object], *, use_color: bool) -> None:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    print(_color("Capability roadmap", "1;32", use_color))
    print(
        "  Gaps: "
        f"{summary.get('baseline_product_gaps', 0)} product setup, "
        f"{summary.get('evidence_gaps', 0)} evidence, "
        f"{summary.get('optional_or_host_unknowns', 0)} optional/host unknown"
    )
    actions = payload.get("next_actions", [])
    if not isinstance(actions, list):
        actions = []
    for action in actions[:3]:
        if not isinstance(action, dict):
            continue
        label = str(action.get("label", "Next action"))
        kind = str(action.get("kind", "unknown"))
        next_step = _short_summary(_roadmap_next_step(action), limit=100)
        print(f"  - {label} ({kind})")
        if next_step:
            print(f"    Next: {next_step}")
    boundary = str(payload.get("claim_boundary", "")).strip()
    if boundary:
        print(f"  Boundary: {_short_summary(boundary, limit=132)}")


def _roadmap_next_step(action: dict[str, object]) -> str:
    command = str(action.get("command", "")).strip()
    if command:
        return command
    return str(action.get("operator_instruction", "")).strip()


def _short_summary(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _config_change_label(language: str, message: str) -> str:
    key = "config_" + message.replace(".", "_").replace(" ", "_").replace("-", "_")
    translated = tr(language, key)
    return translated if translated != key else message


def _executor_summary(language: str, executor: str) -> str:
    labels = {
        "en": {
            "choose": "Ask every time",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "Other coding agent",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my runtime",
            "omo-runtime": "Oh-my runtime",
            "omc-runtime": "Oh-my runtime",
        },
        "ko": {
            "choose": "매번 물어보기",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "기타 코딩 에이전트",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my 런타임",
            "omo-runtime": "Oh-my 런타임",
            "omc-runtime": "Oh-my 런타임",
        },
        "ja": {
            "choose": "毎回確認",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "その他のコーディングエージェント",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my ランタイム",
            "omo-runtime": "Oh-my ランタイム",
            "omc-runtime": "Oh-my ランタイム",
        },
        "zh": {
            "choose": "每次询问",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "其他编码代理",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my 运行时",
            "omo-runtime": "Oh-my 运行时",
            "omc-runtime": "Oh-my 运行时",
        },
    }
    code = normalize_language(language)
    return labels.get(code, labels["en"]).get(executor, labels.get(code, labels["en"])["choose"])


def _plugin_status_label(language: str, status: str) -> str:
    code = normalize_language(language)
    labels = {
        "en": {"installed": "ready", "would_install": "would be installed", "unchanged": "ready", "updated": "updated"},
        "ko": {"installed": "준비됨", "would_install": "설치 예정", "unchanged": "준비됨", "updated": "업데이트됨"},
        "ja": {"installed": "準備完了", "would_install": "インストール予定", "unchanged": "準備完了", "updated": "更新済み"},
        "zh": {"installed": "已就绪", "would_install": "将安装", "unchanged": "已就绪", "updated": "已更新"},
    }
    return labels.get(code, labels["en"]).get(status, status)


def _menubar_status_label(language: str, status: str) -> str:
    code = normalize_language(language)
    labels = {
        "en": {
            "running": "started",
            "installed": "installed",
            "installed_start_failed": "installed; start failed",
            "dry_run": "would install",
            "skipped": "skipped",
            "failed": "failed",
            "not_requested": "not started",
        },
        "ko": {
            "running": "시작됨",
            "installed": "설치됨",
            "installed_start_failed": "설치됨; 시작 실패",
            "dry_run": "설치 예정",
            "skipped": "건너뜀",
            "failed": "실패",
            "not_requested": "시작 안 함",
        },
        "ja": {
            "running": "起動済み",
            "installed": "インストール済み",
            "installed_start_failed": "インストール済み; 起動失敗",
            "dry_run": "インストール予定",
            "skipped": "スキップ",
            "failed": "失敗",
            "not_requested": "未起動",
        },
        "zh": {
            "running": "已启动",
            "installed": "已安装",
            "installed_start_failed": "已安装；启动失败",
            "dry_run": "将安装",
            "skipped": "已跳过",
            "failed": "失败",
            "not_requested": "未启动",
        },
    }
    return labels.get(code, labels["en"]).get(status, status)


def _mcp_status_label(language: str, status: str) -> str:
    code = normalize_language(language)
    labels = {
        "en": {
            "bridge_requested": "preference recorded",
            "host_config_written": "host config written",
            "host_config_unchanged": "host config already ready",
            "host_config_planned": "host config planned",
            "not_requested": "not enabled",
        },
        "ko": {
            "bridge_requested": "선호 기록됨",
            "host_config_written": "호스트 설정 작성됨",
            "host_config_unchanged": "호스트 설정 이미 준비됨",
            "host_config_planned": "호스트 설정 예정",
            "not_requested": "사용 안 함",
        },
        "ja": {
            "bridge_requested": "設定を記録済み",
            "host_config_written": "ホスト設定を書き込み済み",
            "host_config_unchanged": "ホスト設定は準備済み",
            "host_config_planned": "ホスト設定を予定",
            "not_requested": "無効",
        },
        "zh": {
            "bridge_requested": "偏好已记录",
            "host_config_written": "已写入 host 配置",
            "host_config_unchanged": "host 配置已就绪",
            "host_config_planned": "将写入 host 配置",
            "not_requested": "未启用",
        },
    }
    return labels.get(code, labels["en"]).get(status, status)


def _plugin_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError as exc:
        raise OmhError(_friendly_plugin_error(paths, str(exc))) from exc
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    return result


def _menubar_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = setup_menubar_app(paths, dry_run=bool(args.dry_run), start=True, force=bool(args.force))
    except RuntimeError as exc:
        result = {
            "schema_version": "menubar_app/v1",
            "status": "failed",
            "supported": sys.platform == "darwin",
            "dry_run": bool(args.dry_run),
            "reason": str(exc),
        }
    if not args.dry_run:
        update_state(paths, {"last_menubar_app": result})
    return result


def _friendly_plugin_error(paths, message: str) -> str:
    if "exists without an OMH plugin manifest" in message:
        return (
            "OMH status helper location already exists, but it does not look like an OMH-managed install: "
            f"{paths.hermes_plugin_dir}. Run `omh setup --force` to replace only the OMH status helper files."
        )
    if "managed plugin files changed" in message:
        return (
            "OMH status helper files were changed outside OMH. Run `omh setup --force` to refresh the helper, "
            "or inspect the plugin directory before replacing it."
        )
    return message


def _durable_mcp_host_config_record(mcp_setup: object) -> dict[str, object] | None:
    if not isinstance(mcp_setup, dict):
        return None
    host_config = mcp_setup.get("host_config")
    if not isinstance(host_config, dict):
        return None
    status = str(host_config.get("status", ""))
    path = str(host_config.get("path", "")).strip()
    host = str(host_config.get("host", "generic"))
    if host == "generic" or status not in {"updated", "unchanged"} or not path:
        return None
    return {**host_config, "durable_state_key": "last_mcp_host_config_install"}


def _mcp_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    requested = bool(getattr(args, "with_mcp", False))
    host = str(getattr(args, "mcp_host", "") or "generic")
    command = str(getattr(args, "mcp_command", "") or "omh")
    config_path = getattr(args, "mcp_config_path", None)
    host_config: dict[str, object] = {
        "schema_version": "omh_mcp_host_config_install/v1",
        "host": host,
        "status": "not_requested",
        "changed": False,
        "written": False,
        "dry_run": bool(args.dry_run),
        "path": str(config_path or ""),
    }
    if requested:
        try:
            host_config = install_mcp_host_config(
                paths,
                host=host,
                command=command,
                config_path=config_path,
                scope=_setup_scope(args),
                dry_run=bool(args.dry_run),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise OmhError(f"Could not prepare MCP host config: {exc}") from exc
        host_config_status = str(host_config.get("status", "skipped"))
        if host_config_status == "updated":
            status = "host_config_written"
        elif host_config_status == "unchanged":
            status = "host_config_unchanged"
        elif host_config_status.startswith("dry_run"):
            status = "host_config_planned"
        else:
            status = "bridge_requested"
        mode = "bridge_requested"
    else:
        status = "not_requested"
        mode = "none"
    return {
        "schema_version": MCP_SETUP_SCHEMA_VERSION,
        "mode": mode,
        "host": host,
        "requested": requested,
        "status": status,
        "dry_run": bool(args.dry_run),
        "observed": False,
        "host_config": host_config,
        "scope": _setup_scope(args),
        "paths": {
            "omh_home": str(paths.omh_home),
            "runtime_state_path": str(paths.runtime_state_path),
        },
        "bridge": {
            "manifest_command": "omh mcp manifest",
            "host_config_recipes_command": "omh mcp config-recipe --host <host>",
            "known_recipe_hosts": ["generic", "claude-code", "codex", "opencode", "cursor"],
            "server_command": "omh mcp serve",
            "server_command_configured": f"{command} mcp serve",
            "host_observation_command": (
                f"{command} mcp observe-host --host <host> --session <session-id> "
                "--event host_load --evidence-ref <host-log-or-session-ref>"
            ),
            "transport": "stdio",
            "tools": ["omh_status", "omh_recommend", "omh_probe"],
        },
        "claim_boundary": (
            "OMH setup records the operator MCP bridge preference and may write a local host config entry; "
            "it does not prove an MCP host loaded OMH, called a tool, or observed runtime evidence."
        ),
        "next_action": (
            "Use Hermes skills as the normal surface. If a concrete MCP host config was written, restart or reload "
            "that host and record a concrete load or tool-call event with `omh mcp observe-host`. If the host is generic, "
            "export `omh mcp manifest` or `omh mcp config-recipe --host <host>` and wire the stdio bridge manually."
        ),
    }


def _setup_profile_result(args: argparse.Namespace, paths) -> dict[str, object]:
    default_executor = str(getattr(args, "default_executor", "") or "") or None
    operating_model = str(getattr(args, "operating_model", "") or "") or None
    memory_mode = str(getattr(args, "memory_mode", "") or "") or None
    if args.dry_run:
        profile = build_setup_profile(args.profile, default_executor=default_executor, operating_model=operating_model, memory_mode=memory_mode)
        return {**profile, "dry_run": True, "written": False, "path": str(paths.setup_profile_path)}
    profile = write_setup_profile(paths, args.profile, default_executor=default_executor, operating_model=operating_model, memory_mode=memory_mode)
    return {**profile, "dry_run": False, "written": True, "path": str(paths.setup_profile_path)}


def _team_profile_setup_result(args: argparse.Namespace, paths) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for pack_id in args.profile_pack:
        try:
            result = install_team_profile_pack(paths, pack_id, force=args.force, dry_run=args.dry_run)
        except TeamProfileError as exc:
            raise OmhError(str(exc)) from exc
        results.append(result)
    if not args.dry_run:
        update_state(paths, {"last_team_profile_install": results})
    return results


def cmd_profile_list(args: argparse.Namespace) -> int:
    payload = list_team_profile_packs()
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_profile_list_summary(payload)
    return 0


def cmd_profile_inspect(args: argparse.Namespace) -> int:
    try:
        payload = inspect_team_profile_pack(args.id)
    except TeamProfileError as exc:
        try:
            payload = inspect_operating_model(args.id)
        except TeamProfileError:
            raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_profile_inspect_summary(payload)
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("recommend --limit must be at least 1")
    query = " ".join(args.task).strip()
    if not query:
        raise OmhError("recommend requires a task description")
    full_recommendations = recommend_skills(query, limit=max(args.limit, 8))
    payload = {"query": query, "recommendations": full_recommendations[: args.limit]}
    selected_skill = str(full_recommendations[0].get("skill", "oh-my-hermes")) if full_recommendations else "oh-my-hermes"
    top_score = int(full_recommendations[0].get("score", 0)) if full_recommendations else 0
    workflow_route_plan = compact_workflow_route_plan(
        build_workflow_route_plan(
            query,
            full_recommendations,
            selected_skill=selected_skill,
            action="dispatch" if top_score > 0 else "fallback",
        )
    )
    if workflow_route_plan:
        payload["workflow_route_plan"] = workflow_route_plan
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_recommend_summary(payload)
    return 0


def cmd_snippet(args: argparse.Namespace) -> int:
    if args.dry_run or not args.output:
        print(WORKSPACE_SNIPPET.rstrip())
        return 0
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(output, WORKSPACE_SNIPPET)
    payload = {"written": str(output)}
    if _wants_json(args):
        _print_json(payload)
    else:
        print(f"OMH workspace snippet written: {output}")
        print(f"  {tr('en', 'machine_readable')}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    payload = probe_capabilities(
        _paths(args),
        include_parity=bool(getattr(args, "parity", False)),
        include_roadmap=bool(getattr(args, "roadmap", False)),
    )
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_probe_summary(payload)
    return 0


def _add_common_install_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from-skills-dir", default=None, help="Import skills from a local skill directory.")
    p.add_argument("--source", default=None, help="Mockable local source directory for install/update.")
    p.add_argument("--channel", choices=RELEASE_CHANNELS, default="preview", help="Release channel metadata for this install/update.")
    p.add_argument("--version", default="", help="Stable release version such as 1.0.0 or v1.0.0.")
    p.add_argument("--package-url", default="", help="Explicit release archive URL for support and audit metadata.")
    p.add_argument("--source-ref", default="", help="Release source ref metadata such as main, main@sha, or v1.0.1.")
    p.add_argument("--command-package-updated", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--language", default=None, help=f"Human output language for setup/install/update ({', '.join(LANGUAGE_CODES)}).")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--full",
        action="store_true",
        help=(
            "Install every packaged skill instead of the smaller core default "
            "(chat/plan/status/handoff essentials plus the doctor health floor); "
            "the result records a context-cost warning because every extra skill "
            "adds per-turn context weight."
        ),
    )


def _add_top_level_commands(sub) -> None:
    setup = sub.add_parser("setup", help="Connect OMH workflows to the target Hermes profile.")
    _add_common_install_options(setup)
    setup.add_argument(
        "--scope",
        choices=("user", "project"),
        default=argparse.SUPPRESS,
        help="Install to user-wide ~/.omh/~/.hermes or project-local ./.omh/./.hermes paths.",
    )
    setup.add_argument("--json", action="store_true", help="Print the full machine-readable setup payload.")
    setup.add_argument("--yes", action="store_true", help="Use default setup choices without interactive prompts.")
    setup.add_argument("--interactive", action="store_true", help="Force the interactive setup wizard.")
    setup.add_argument("--no-interactive", action="store_true", help="Disable the interactive setup wizard.")
    setup.add_argument("--skip-apply", action="store_true", help="Install skills without registering them in Hermes config.")
    setup.add_argument("--star", action="store_true", help="Star the oh-my-hermes GitHub repo via gh after setup (opt-in; never prompted).")
    setup.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Setup profile category to record by number or id. Repeat for multiple categories; choices are listed in setup output.",
    )
    setup.add_argument(
        "--default-executor",
        choices=CODING_EXECUTOR_TARGETS,
        default=None,
        help="Durable coding-owner preference for automation and scripted installs. Interactive setup never asks; by default Hermes asks at the first coding request.",
    )
    setup.add_argument(
        "--operating-model",
        choices=operating_model_ids(),
        default=None,
        help="Advanced: record a Hermes-facing operating model for this profile; normal setup lets Hermes choose per request.",
    )
    setup.add_argument(
        "--memory-mode",
        choices=PROJECT_MEMORY_MODES,
        default=None,
        help="Configure OMH project memory: off, review-first, or auto-safe. Defaults to review-first.",
    )
    setup.add_argument(
        "--with-plugin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    setup.add_argument(
        "--with-menubar",
        action="store_true",
        help="Install and start the native macOS OMH menu bar helper when supported.",
    )
    setup.add_argument(
        "--no-menubar",
        action="store_true",
        help="Do not start the native macOS OMH menu bar helper during setup.",
    )
    setup.add_argument(
        "--with-mcp",
        action="store_true",
        help="Prepare the optional OMH MCP bridge. Use --mcp-host to also write a supported host config.",
    )
    setup.add_argument(
        "--mcp-host",
        choices=MCP_HOST_CONFIG_RECIPE_HOSTS,
        default="generic",
        help="MCP host config to prepare when --with-mcp is set. generic keeps recipe-only output.",
    )
    setup.add_argument(
        "--mcp-config-path",
        default=None,
        help="Explicit host config path to update for --with-mcp --mcp-host.",
    )
    setup.add_argument(
        "--mcp-command",
        default="omh",
        help="Command path the MCP host should launch. Use an absolute installed omh path when needed.",
    )
    setup.add_argument(
        "--profile-pack",
        action="append",
        default=[],
        help="Advanced: install optional visible Hermes role/profile files such as startup-delivery, engineering-delivery, research-strategy, or cto-loop.",
    )
    setup.set_defaults(func=cmd_setup)

    install = sub.add_parser("install", help="Refresh the managed OMH skill pack without changing Hermes registration.")
    _add_common_install_options(install)
    install.add_argument("--json", action="store_true", help="Print the full machine-readable install payload.")
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update", help="Refresh OMH from a preview, stable, local, or explicit package source.")
    _add_common_install_options(update)
    update.add_argument("--json", action="store_true", help="Print the full machine-readable update payload.")
    update.set_defaults(func=cmd_update)

    convert = sub.add_parser("convert", help="Import a local skills directory into the managed OMH skill pack.")
    convert.add_argument("--from-skills-dir", required=True)
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--json", action="store_true", help="Print the full machine-readable convert payload.")
    convert.set_defaults(func=cmd_convert)

    apply = sub.add_parser("apply", help="Register the managed OMH skills directory in Hermes config.")
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--json", action="store_true", help="Print the machine-readable apply payload.")
    apply.set_defaults(func=cmd_apply)

    uninstall = sub.add_parser("uninstall", help="Remove OMH-managed registration, local files, and optional command package.")
    uninstall.add_argument("--registration-only", action="store_true", help="Only remove the OMH skills.external_dirs registration from Hermes config.")
    uninstall.add_argument("--remove-files", action="store_true", help="Legacy mode: remove Hermes registration and the managed OMH home directory.")
    uninstall.add_argument("--all", action="store_true", help="Remove all OMH-managed local state, plugin bundle, and generated team role files.")
    uninstall.add_argument("--purge", action="store_true", help="Alias for --all.")
    uninstall.add_argument("--keep-command", action="store_true", help="Keep the install.sh-managed omh command venv/link during full cleanup.")
    uninstall.add_argument("--force", action="store_true", help="Also remove an unmanaged ~/.hermes/plugins/omh directory when using --all.")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--json", action="store_true", help="Print the machine-readable uninstall payload.")
    uninstall.add_argument("--language", default=None, help=f"Human output language ({', '.join(LANGUAGE_CODES)}).")
    uninstall.set_defaults(func=cmd_uninstall)

    list_cmd = sub.add_parser("list", help="Show the installed managed skill manifest.")
    list_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable manifest.")
    list_cmd.set_defaults(func=cmd_list)

    doctor = sub.add_parser("doctor", help="Check local OMH install health and Hermes skill registration.")
    doctor.add_argument("--json", action="store_true", help="Print the full machine-readable doctor payload.")
    doctor.add_argument("--language", default=None, help=f"Human output language ({', '.join(LANGUAGE_CODES)}).")
    doctor.set_defaults(func=cmd_doctor)

    recommend = sub.add_parser("recommend", help="Map a task description to likely OMH workflow skills.")
    recommend.add_argument("task", nargs="+", help="Task description to map to OMH workflow skills.")
    recommend.add_argument("--limit", type=int, default=5, help="Maximum recommendations to return.")
    recommend.add_argument("--json", action="store_true", help="Print the full machine-readable recommendation payload.")
    recommend.set_defaults(func=cmd_recommend)

    snippet = sub.add_parser("snippet", help="Print or write the workspace guidance snippet for agents.")
    snippet.add_argument("--dry-run", action="store_true")
    snippet.add_argument("--output", default=None)
    snippet.add_argument("--json", action="store_true", help="Print machine-readable output when writing to --output.")
    snippet.set_defaults(func=cmd_snippet)

    probe = sub.add_parser("probe", help="Inspect observable OMH/Hermes capability surfaces.")
    probe.add_argument(
        "--parity",
        action="store_true",
        help="Include the OMH parity matrix for common oh-my agent runtime capability axes.",
    )
    probe.add_argument(
        "--roadmap",
        action="store_true",
        help="Include next actions that separate product setup gaps from missing host/runtime evidence.",
    )
    probe.add_argument("--json", action="store_true", help="Print the full machine-readable capability payload.")
    probe.set_defaults(func=cmd_probe)

    profile = sub.add_parser("profile", help="List or inspect optional visible team role/profile packs.")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true", help="Print the full machine-readable profile pack catalog.")
    profile_list.set_defaults(func=cmd_profile_list)
    profile_inspect = profile_sub.add_parser("inspect")
    profile_inspect.add_argument("id")
    profile_inspect.add_argument("--json", action="store_true", help="Print the full machine-readable profile pack payload.")
    profile_inspect.set_defaults(func=cmd_profile_inspect)
