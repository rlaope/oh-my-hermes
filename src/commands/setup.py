from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows compatibility guard.
    termios = None
    tty = None

from .. import __version__
from ..config_adapter import ensure_external_dir, external_dirs, read_config, remove_external_dir, write_config
from ..doctor import doctor_ok, recommended_next_action, run_doctor
from ..executors import CODING_EXECUTOR_TARGETS
from ..hashutil import sha256_file
from ..installer import OmhError, install_skill_pack, uninstall_skill_pack
from ..local_store import atomic_write_text
from ..manifest import read_manifest
from ..plugin_pack import PluginPackError, install_plugin_bundle
from ..probe import probe_capabilities
from ..release import RELEASE_CHANNELS, package_url_for
from ..routing.recommend import recommend_skills
from ..runtime.artifacts import read_state_result, update_state
from ..setup_profiles import (
    build_setup_profile,
    setup_profile_categories_for_executor,
    write_setup_profile,
)
from ..snippet import WORKSPACE_SNIPPET
from ..targets import record_target_observation
from ..team_profiles import TeamProfileError, inspect_team_profile_pack, install_team_profile_pack, list_team_profile_packs
from .common import _paths, _print_json, _wants_json
from .language import LANGUAGE_CODES, language_from_env, language_options, normalize_language, tr

INSTALLER_COMMAND = "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh"
COMMAND_PACKAGE_STATUS_SCHEMA_VERSION = "command_package_status/v1"
RELEASE_UPDATE_SCHEMA_VERSION = "release_update_status/v1"
SETUP_OPERATOR_SUMMARY_SCHEMA_VERSION = "setup_operator_summary/v1"
DOCTOR_SUMMARY_SCHEMA_VERSION = "doctor_summary/v1"
MCP_SETUP_SCHEMA_VERSION = "omh_mcp_setup/v1"


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
    result = install_skill_pack(paths, source=source, source_dir=source_dir, force=args.force, dry_run=args.dry_run)
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
    return cmd_install(args)


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
    plugin_status = "installed" if getattr(args, "with_plugin", False) else "optional"
    team_status = "profile_pack" if getattr(args, "profile_pack", []) else "available"
    mcp = steps.get("mcp", {})
    mcp_mode = str(mcp.get("mode", "none")) if isinstance(mcp, dict) else "none"
    summary = {
        "schema_version": SETUP_OPERATOR_SUMMARY_SCHEMA_VERSION,
        "scope": _setup_scope(args),
        "install_mode": "managed_skills",
        "mcp_mode": mcp_mode,
        "plugin_mode": plugin_status,
        "team_mode": team_status,
        "status": status,
        "requires_hermes_reload": bool(hermes_native.get("requires_hermes_reload", False)),
        "paths": {
            "omh_home": str(paths.omh_home),
            "hermes_home": str(paths.hermes_home),
            "skills_dir": str(paths.skills_dir),
            "hermes_config_path": str(paths.hermes_config_path),
        },
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
            _doctor_group("managed_skills", check_dicts, ("manifest", "manifest_skills_dir", "local_modifications", "skills_dir", "skill:")),
            _doctor_group("runtime", check_dicts, ("runtime_artifacts", "workflow_state", "runtime_state")),
            _doctor_group("hermes_registration", check_dicts, ("hermes_config", "external_dir", "runtime_context")),
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
    payload = manifest or {"skills": [], "message": "not installed"}
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
    return {
        "ok": doctor_ok(checks),
        "checks": [check.__dict__ for check in checks],
        "summary": summary,
        "state_log": state_log,
        "recommended_next_action": next_action,
        "language": _resolve_language(args),
    }


def cmd_setup(args: argparse.Namespace) -> int:
    language = _setup_language(args)
    paths = _paths(args)
    if _setup_should_interact(args):
        if not _language_was_explicit(args):
            language = _ask_setup_language(use_color=_use_color())
            args.language = language
        if not _setup_paths_were_explicit(args) and not getattr(args, "scope", None):
            args.scope = _ask_setup_scope(use_color=_use_color(), language=language)
            paths = _paths(args)
        _run_setup_wizard(args, paths, language)

    progress = _HumanProgress(enabled=not _wants_json(args), use_color=_use_color())
    if not _wants_json(args):
        progress.header(tr(language, "setup_title"), tr(language, "setup_subtitle"))
    total_steps = 4 + (1 if args.with_plugin else 0) + (1 if args.with_mcp else 0) + (1 if args.profile_pack else 0)
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

    if args.with_plugin:
        progress.step(step_index, total_steps, tr(language, "step_plugin"), detail=str(paths.hermes_plugin_dir))
        steps["plugin"] = _plugin_setup_result(args, paths)
        plugin_status = steps["plugin"].get("status", "installed") if isinstance(steps["plugin"], dict) else "installed"
        progress.done(str(plugin_status))
        step_index += 1

    steps["mcp"] = _mcp_setup_result(args, paths)
    if args.with_mcp:
        progress.step(step_index, total_steps, tr(language, "step_mcp"), detail=str(paths.runtime_state_path))
        mcp_status = steps["mcp"].get("status", "bridge_requested") if isinstance(steps["mcp"], dict) else "bridge_requested"
        progress.done(tr(language, "done_mcp_bridge", status=mcp_status))
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
    progress.done(tr(language, "done_default_executor", executor=profile_executor))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_targets"))
    steps["targets"] = record_target_observation(
        paths,
        source="setup",
        dry_run=args.dry_run,
        ensure_config=not args.skip_apply,
        setup_context={
            "apply_skipped": bool(args.skip_apply),
            "with_plugin": bool(args.with_plugin),
            "with_mcp": bool(args.with_mcp),
            "profile_packs": list(args.profile_pack),
            "setup_profiles": list(args.profile),
            "default_executor": str(getattr(args, "default_executor", "") or ""),
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
        update_state(
            paths,
            {
                "last_setup": {
                    "ok": True,
                    "apply_skipped": bool(args.skip_apply),
                    "hermes_native": hermes_native,
                    "operator_summary": operator_summary,
                    "setup_profile": steps["profile"],
                    "mcp_setup": steps["mcp"],
                    "team_profiles": steps.get("team_profiles", []),
                    "target_observation": steps["targets"],
                }
            },
        )
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
    if args.with_plugin:
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
        or args.with_plugin
        or args.with_mcp
        or args.skip_apply
        or getattr(args, "scope", None)
    ):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _resolve_language(args: argparse.Namespace) -> str:
    raw = getattr(args, "language", None)
    try:
        return normalize_language(raw) if raw else language_from_env()
    except ValueError as exc:
        raise OmhError(str(exc)) from exc


def _setup_language(args: argparse.Namespace) -> str:
    if _language_was_explicit(args):
        return _resolve_language(args)
    return "en"


def _language_was_explicit(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "language", None) or os.environ.get("OMH_LANG") or os.environ.get("OMH_LANGUAGE"))


def _setup_paths_were_explicit(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "omh_home", None) or getattr(args, "hermes_home", None))


def _ask_setup_language(*, use_color: bool) -> str:
    return _ask_single_choice(
        tr("en", "language_title"),
        [tr("en", "language_intro")],
        language_options(),
        default_choice="1",
        use_color=use_color,
        language="en",
    )


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

    args.skip_apply = not _ask_yes_no(
        tr(language, "register_question"),
        default=True,
        use_color=use_color,
        note=tr(language, "register_note"),
        language=language,
    )
    args.default_executor = _ask_default_executor(use_color=use_color, language=language)
    args.profile = setup_profile_categories_for_executor(str(args.default_executor))
    args.with_plugin = _ask_yes_no(
        tr(language, "plugin_question"),
        default=False,
        use_color=use_color,
        note=tr(language, "plugin_note"),
        language=language,
    )
    args.with_mcp = _ask_yes_no(
        tr(language, "mcp_question"),
        default=False,
        use_color=use_color,
        note=tr(language, "mcp_note"),
        language=language,
    )
    args.profile_pack = _ask_team_profile_packs(use_color=use_color, language=language)
    print("")


def _ask_default_executor(*, use_color: bool, language: str) -> str:
    options = [
        {
            "choice": "1",
            "value": "choose",
            "label": tr(language, "executor_choose_label"),
            "description": tr(language, "executor_choose_desc"),
        },
        {
            "choice": "2",
            "value": "codex",
            "label": tr(language, "executor_codex_label"),
            "description": tr(language, "executor_codex_desc"),
        },
        {
            "choice": "3",
            "value": "claude-code",
            "label": tr(language, "executor_claude_label"),
            "description": tr(language, "executor_claude_desc"),
        },
        {
            "choice": "4",
            "value": "generic",
            "label": tr(language, "executor_generic_label"),
            "description": tr(language, "executor_generic_desc"),
        },
        {
            "choice": "5",
            "value": "hermes",
            "label": tr(language, "executor_hermes_label"),
            "description": tr(language, "executor_hermes_desc"),
        },
        {
            "choice": "6",
            "value": "omx-runtime",
            "label": tr(language, "executor_runtime_label"),
            "description": tr(language, "executor_runtime_desc"),
        },
    ]
    value = _ask_single_choice(
        tr(language, "executor_title"),
        [
            tr(language, "executor_intro_1"),
            tr(language, "executor_intro_2"),
        ],
        options,
        default_choice="1",
        use_color=use_color,
        language=language,
    )
    try:
        build_setup_profile(default_executor=value)
    except ValueError as exc:
        print(_color(tr(language, "invalid_executor", error=exc), "31", use_color))
        return "choose"
    return value


def _ask_team_profile_packs(*, use_color: bool, language: str) -> list[str]:
    catalog = list_team_profile_packs()
    packs = catalog.get("packs", []) if isinstance(catalog, dict) else []
    options = [
        {
            "choice": "0",
            "value": "",
            "label": tr(language, "team_none_label"),
            "description": tr(language, "team_none_desc"),
        }
    ]
    for idx, pack in enumerate(packs, start=1):
        pack_id = str(pack["id"])
        options.append(
            {
                "choice": str(idx),
                "value": pack_id,
                "label": str(pack["title"]),
                "description": str(pack["summary"]),
            }
        )
    while True:
        value = _ask_single_choice(
            tr(language, "team_title"),
            [
                tr(language, "team_intro_1"),
                tr(language, "team_intro_2"),
            ],
            options,
            default_choice="0",
            use_color=use_color,
            language=language,
        )
        if not value:
            return []
        return [value]


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
    rendered_lines = 0
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
        if rendered_lines:
            sys.stdout.write(f"\033[{rendered_lines}F\033[J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        rendered_lines = len(lines)
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
        marker = "[x]" if active else "[ ]"
        suffix = f" ({tr(language, 'recommended')})" if option["choice"] == default_choice else ""
        label = f"  {pointer} {marker} {option['choice']}) {option['label']}{suffix}"
        if active:
            label = _color(label, "1;36", use_color)
        lines.append(label)
        if option["description"]:
            lines.append(f"      {option['description']}")
    return lines


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
    apply = steps.get("apply", {})
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
    install_mode_label = tr(language, "setup_install_mode_" + str(operator_summary.get("install_mode", "managed_skills")))
    mcp_mode_label = tr(language, "setup_mcp_mode_" + str(operator_summary.get("mcp_mode", "none")))
    status_label = tr(language, "setup_status_" + str(operator_summary.get("status", "configured")))
    print(f"  {tr(language, 'setup_scope', scope=scope_label)}")
    print(f"  {tr(language, 'setup_install_mode', mode=install_mode_label)}")
    print(f"  {tr(language, 'setup_mcp_mode', mode=mcp_mode_label)}")
    print(f"  {tr(language, 'setup_status', status=status_label)}")
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

    if isinstance(apply, dict) and apply.get("message"):
        print(f"  {tr(language, 'apply_line', message=apply.get('message'))}")

    if isinstance(profile, dict):
        selected = ", ".join(str(item) for item in profile.get("selected_categories", []) or [])
        executor = str(profile.get("default_executor", ""))
        if selected or executor:
            print(f"  {tr(language, 'default_handoff', summary=_executor_summary(executor))}")
            if selected:
                print(f"  {tr(language, 'setup_profile', selected=selected)}")

    if isinstance(topology, dict):
        print(
            f"  {tr(language, 'target_topology', mode=topology.get('mode', 'unknown'), count=topology.get('known_target_count', 0))}"
        )
    state_log = operator_summary.get("state_log", {})
    if isinstance(state_log, dict) and state_log.get("path") and state_log.get("entry"):
        print(f"  {tr(language, 'state_log', path=state_log.get('path'), entry=state_log.get('entry'))}")

    plugin = payload.get("plugin_distribution")
    if isinstance(plugin, dict):
        print(f"  {tr(language, 'plugin_bridge', status=plugin.get('status', 'installed'))}")
    elif not dry_run:
        print(f"  {tr(language, 'plugin_optional')}")

    team_profiles = payload.get("team_profiles")
    if isinstance(team_profiles, list) and team_profiles:
        print(f"  {tr(language, 'team_activated', count=len(team_profiles))}")
    elif not dry_run:
        print(f"  {tr(language, 'team_none')}")

    print(_color(tr(language, "next"), "1;32", use_color))
    if dry_run:
        print(f"  {tr(language, 'setup_next_dry')}")
    else:
        print(f"  {tr(language, 'setup_next_reload')}")
        print(f"  {tr(language, 'setup_next_prompt')}")
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
    state_log = payload.get("state_log", {})
    if isinstance(state_log, dict) and state_log.get("path") and state_log.get("entry"):
        print(f"  {tr(language, 'state_log', path=state_log.get('path'), entry=state_log.get('entry'))}")
    for check in checks:
        if not isinstance(check, dict) or check.get("ok"):
            continue
        name = check.get("name", "unknown")
        message = check.get("message", "")
        remediation = check.get("remediation", "") or check.get("next_action", "")
        print(f"  - {name}: {message}")
        if remediation:
            print(f"    {tr(language, 'doctor_fix')}: {remediation}")
    next_action = str(payload.get("recommended_next_action", "")).strip()
    print(_color(tr(language, "next"), "1;32", use_color))
    if next_action:
        print(f"  {next_action}")
    print(f"  {tr(language, 'doctor_boundary')}")
    print(f"  {tr(language, 'machine_readable')}")


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
    print("")
    print(_color(title, "1;36", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'skills_line', count=len(skills), path=payload.get('skills_dir', ''))}")
    source = str(payload.get("source", "builtin"))
    source_label = tr(language, "source_builtin") if source == "builtin" else source
    print(f"  {tr(language, 'source', source=source_label)}")
    channel = str(payload.get("release_channel", "")).strip()
    package_url = str(payload.get("release_package_url", "")).strip()
    if channel:
        print(f"  {tr(language, 'release_channel', channel=channel)}")
    if package_url and package_url != "local":
        package_url_key = "recorded_package_url" if source == "builtin" else "package_url"
        print(f"  {tr(language, package_url_key, url=package_url)}")
    release_update = payload.get("release_update", {})
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
    command_package = payload.get("command_package", {})
    if isinstance(command_package, dict):
        command_status = str(command_package.get("status", "")).strip()
        if command_status == "updated":
            print(f"  {tr(language, 'command_package_updated')}")
        elif label == "update" and source == "builtin" and not dry_run:
            print(f"  {tr(language, 'command_package_unchanged')}")
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
    print(_color("Next", "1;32", use_color))
    print("  Run `omh doctor` to verify Hermes registration.")
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
            print(f"   Next action: {next_action}")
        why = _short_summary(str(recommendation.get("why", "")), limit=120)
        if why:
            print(f"   Why: {why}")
    print(_color("Boundary", "1;32", use_color))
    print("  A recommendation is routing guidance, not execution or verification evidence.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_profile_list_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    packs = payload.get("packs", [])
    if not isinstance(packs, list):
        packs = []
    print(_color("OMH profile packs", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Default install: {payload.get('default_install', 'none')}")
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
    print("  Inspect a pack with `omh profile inspect <id>`.")
    print("  Install one with `omh setup --profile-pack <id>`.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_profile_inspect_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
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
    print(f"  {tr('en', 'machine_readable')}")


def _short_summary(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _config_change_label(language: str, message: str) -> str:
    key = "config_" + message.replace(".", "_").replace(" ", "_").replace("-", "_")
    translated = tr(language, key)
    return translated if translated != key else message


def _executor_summary(executor: str) -> str:
    labels = {
        "choose": "ask before choosing a coding executor",
        "codex": "Codex tracked handoff when selected",
        "claude-code": "Claude Code prompt handoff",
        "generic": "portable prompt handoff for any coding agent",
        "hermes": "keep small coding-like work in Hermes by default",
        "omx-runtime": "plugin/runtime prompt handoff",
        "omo-runtime": "plugin/runtime prompt handoff",
        "omc-runtime": "plugin/runtime prompt handoff",
    }
    return f"{labels.get(executor, 'unknown')} ({executor or 'unknown'})"


def _plugin_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    return result


def _mcp_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    requested = bool(getattr(args, "with_mcp", False))
    if requested:
        status = "would_record_bridge_preference" if args.dry_run else "bridge_preference_recorded"
        mode = "bridge_requested"
    else:
        status = "not_requested"
        mode = "none"
    return {
        "schema_version": MCP_SETUP_SCHEMA_VERSION,
        "mode": mode,
        "requested": requested,
        "status": status,
        "dry_run": bool(args.dry_run),
        "observed": False,
        "scope": _setup_scope(args),
        "paths": {
            "omh_home": str(paths.omh_home),
            "runtime_state_path": str(paths.runtime_state_path),
        },
        "claim_boundary": (
            "OMH setup records the operator MCP bridge preference only; it does not prove an MCP host "
            "loaded OMH, called a tool, or observed runtime evidence."
        ),
        "next_action": (
            "Use Hermes skills as the normal surface. Treat MCP bridge availability as unobserved until a "
            "Hermes/MCP host records a concrete load or tool-call event."
        ),
    }


def _setup_profile_result(args: argparse.Namespace, paths) -> dict[str, object]:
    default_executor = str(getattr(args, "default_executor", "") or "") or None
    if args.dry_run:
        profile = build_setup_profile(args.profile, default_executor=default_executor)
        return {**profile, "dry_run": True, "written": False, "path": str(paths.setup_profile_path)}
    profile = write_setup_profile(paths, args.profile, default_executor=default_executor)
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
    payload = {"query": query, "recommendations": recommend_skills(query, limit=args.limit)}
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
    payload = probe_capabilities(_paths(args))
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


def _add_top_level_commands(sub) -> None:
    setup = sub.add_parser("setup", help="Install managed skills and connect them to the target Hermes profile.")
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
        help="Default executor preference for coding-shaped handoffs. Use 'choose' to ask each time.",
    )
    setup.add_argument(
        "--with-plugin",
        action="store_true",
        help="Also install the optional OMH Hermes plugin bundle under ~/.hermes/plugins/omh.",
    )
    setup.add_argument(
        "--with-mcp",
        action="store_true",
        help="Record an optional OMH MCP bridge preference without claiming MCP host runtime load.",
    )
    setup.add_argument(
        "--profile-pack",
        action="append",
        default=[],
        help="Install an optional Hermes agent/profile pack such as startup-delivery, engineering-delivery, research-strategy, or cto-loop.",
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
