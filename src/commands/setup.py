from __future__ import annotations

import argparse
from pathlib import Path

from .. import __version__
from ..config_adapter import ensure_external_dir, read_config, remove_external_dir, write_config
from ..doctor import doctor_ok, recommended_next_action, run_doctor
from ..hashutil import sha256_file
from ..installer import OmhError, install_skill_pack, uninstall_skill_pack
from ..local_store import atomic_write_text
from ..manifest import read_manifest
from ..plugin_pack import PluginPackError, install_plugin_bundle
from ..probe import probe_capabilities
from ..release import RELEASE_CHANNELS, package_url_for
from ..routing.recommend import recommend_skills
from ..runtime.artifacts import update_state
from ..setup_profiles import build_setup_profile, write_setup_profile
from ..snippet import WORKSPACE_SNIPPET
from ..targets import record_target_observation
from ..team_profiles import TeamProfileError, inspect_team_profile_pack, install_team_profile_pack, list_team_profile_packs
from .common import _paths, _print_json


def cmd_install(args: argparse.Namespace) -> int:
    _print_json(_install_result(args))
    return 0


def _install_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.channel == "local" and not (args.from_skills_dir or args.source):
        raise OmhError("local channel requires --from-skills-dir or --source")
    source_dir = Path(args.from_skills_dir or args.source).expanduser().resolve() if (args.from_skills_dir or args.source) else None
    source = str(source_dir) if source_dir else "builtin"
    result = install_skill_pack(paths, source=source, source_dir=source_dir, force=args.force, dry_run=args.dry_run)
    result.update({"release_channel": release.channel, "release_version": release.version, "release_package_url": release.package_url})
    if not args.dry_run:
        update_state(
            paths,
            {
                "package": "oh-my-hermes-agent",
                "version": __version__,
                "manifest_path": str(paths.manifest_path),
                "manifest_sha256": sha256_file(paths.manifest_path),
                "source": source,
                "release_channel": release.channel,
                "release_version": release.version,
                "release_package_url": release.package_url,
                "installed_skills": len(result.get("skills", [])),
                "skills_dir": str(paths.skills_dir),
            },
        )
    return result


def cmd_update(args: argparse.Namespace) -> int:
    return cmd_install(args)


def cmd_convert(args: argparse.Namespace) -> int:
    args.source = args.from_skills_dir
    args.channel = "local"
    args.version = ""
    args.package_url = ""
    return cmd_install(args)


def cmd_apply(args: argparse.Namespace) -> int:
    _print_json(_apply_result(args))
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
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = remove_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    result = uninstall_skill_pack(paths, remove_files=args.remove_files and not args.dry_run)
    result.update({"config_changed": change.changed, "dry_run": args.dry_run})
    _print_json(result)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    manifest = read_manifest(_paths(args).manifest_path)
    _print_json(manifest or {"skills": [], "message": "not installed"})
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = _doctor_result(args)
    _print_json(payload)
    return 0 if payload["ok"] else 1


def _doctor_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    checks = run_doctor(paths)
    runtime_writable = any(check.name == "runtime_artifacts" and check.ok for check in checks)
    runtime_state_readable = not any(check.name == "runtime_state" and not check.ok for check in checks)
    if runtime_writable and runtime_state_readable:
        next_action = recommended_next_action(checks)
        update_state(
            paths,
            {
                "last_doctor": {
                    "ok": doctor_ok(checks),
                    "checks": {check.name: check.ok for check in checks},
                    "recommended_next_action": next_action,
                }
            },
        )
    return {
        "ok": doctor_ok(checks),
        "checks": [check.__dict__ for check in checks],
        "recommended_next_action": recommended_next_action(checks),
    }


def cmd_setup(args: argparse.Namespace) -> int:
    paths = _paths(args)
    steps: dict[str, object] = {"install": _install_result(args)}
    if args.skip_apply:
        steps["apply"] = {"skipped": True, "message": "Skipped Hermes config registration because --skip-apply was set."}
    else:
        steps["apply"] = _apply_result(args)
    if args.with_plugin:
        steps["plugin"] = _plugin_setup_result(args, paths)
    if args.profile_pack:
        steps["team_profiles"] = _team_profile_setup_result(args, paths)
    steps["profile"] = _setup_profile_result(args, paths)
    steps["targets"] = record_target_observation(
        paths,
        source="setup",
        dry_run=args.dry_run,
        ensure_config=not args.skip_apply,
        setup_context={
            "apply_skipped": bool(args.skip_apply),
            "with_plugin": bool(args.with_plugin),
            "profile_packs": list(args.profile_pack),
            "setup_profiles": list(args.profile),
        },
    )
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
        "equivalent_hermes_commands": [
            "hermes skills tap add rlaope/oh-my-hermes-agent",
            "hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes",
        ],
        "bootstrap_final_state": bootstrap_final_state,
        "skills_dir": str(paths.skills_dir),
        "hermes_config_path": str(paths.hermes_config_path),
        "hermes_config_key": "skills.external_dirs",
        "target_topology": steps["targets"]["topology"],
        "wrapper_backend_surface": "omh chat interact and runtime commands are adapter/operator contracts, not the normal chat UX",
    }

    if not args.dry_run:
        update_state(
            paths,
            {
                "last_setup": {
                    "ok": True,
                    "apply_skipped": bool(args.skip_apply),
                    "hermes_native": hermes_native,
                    "setup_profile": steps["profile"],
                    "team_profiles": steps.get("team_profiles", []),
                    "target_observation": steps["targets"],
                }
            },
        )
    payload: dict[str, object] = {"ok": True, "steps": steps, "dry_run": args.dry_run, "hermes_native": hermes_native}
    if args.with_plugin:
        payload["plugin_distribution"] = steps["plugin"]
    if args.profile_pack:
        payload["team_profiles"] = steps["team_profiles"]
    _print_json(payload)
    return 0


def _plugin_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    return result


def _setup_profile_result(args: argparse.Namespace, paths) -> dict[str, object]:
    if args.dry_run:
        profile = build_setup_profile(args.profile)
        return {**profile, "dry_run": True, "written": False, "path": str(paths.setup_profile_path)}
    profile = write_setup_profile(paths, args.profile)
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
    _print_json(list_team_profile_packs())
    return 0


def cmd_profile_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(inspect_team_profile_pack(args.id))
    except TeamProfileError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("recommend --limit must be at least 1")
    query = " ".join(args.task).strip()
    if not query:
        raise OmhError("recommend requires a task description")
    _print_json({"query": query, "recommendations": recommend_skills(query, limit=args.limit)})
    return 0


def cmd_snippet(args: argparse.Namespace) -> int:
    if args.dry_run or not args.output:
        print(WORKSPACE_SNIPPET.rstrip())
        return 0
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(output, WORKSPACE_SNIPPET)
    _print_json({"written": str(output)})
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    _print_json(probe_capabilities(_paths(args)))
    return 0


def _add_common_install_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from-skills-dir", default=None, help="Import skills from a local skill directory.")
    p.add_argument("--source", default=None, help="Mockable local source directory for install/update.")
    p.add_argument("--channel", choices=RELEASE_CHANNELS, default="preview", help="Release channel metadata for this install/update.")
    p.add_argument("--version", default="", help="Stable release version such as 1.0.0 or v1.0.0.")
    p.add_argument("--package-url", default="", help="Explicit release archive URL for support and audit metadata.")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")


def _add_top_level_commands(sub) -> None:
    setup = sub.add_parser("setup")
    _add_common_install_options(setup)
    setup.add_argument("--skip-apply", action="store_true", help="Install skills without registering them in Hermes config.")
    setup.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Setup profile category to record by number or id. Repeat for multiple categories; choices are listed in setup output.",
    )
    setup.add_argument(
        "--with-plugin",
        action="store_true",
        help="Also install the optional OMH Hermes plugin bundle under ~/.hermes/plugins/omh.",
    )
    setup.add_argument(
        "--profile-pack",
        action="append",
        default=[],
        help="Install an optional Hermes agent/profile pack such as startup-delivery, engineering-delivery, research-strategy, or cto-loop.",
    )
    setup.set_defaults(func=cmd_setup)

    install = sub.add_parser("install")
    _add_common_install_options(install)
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update")
    _add_common_install_options(update)
    update.set_defaults(func=cmd_update)

    convert = sub.add_parser("convert")
    convert.add_argument("--from-skills-dir", required=True)
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--dry-run", action="store_true")
    convert.set_defaults(func=cmd_convert)

    apply = sub.add_parser("apply")
    apply.add_argument("--dry-run", action="store_true")
    apply.set_defaults(func=cmd_apply)

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--remove-files", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    list_cmd = sub.add_parser("list")
    list_cmd.set_defaults(func=cmd_list)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    recommend = sub.add_parser("recommend")
    recommend.add_argument("task", nargs="+", help="Task description to map to OMH workflow skills.")
    recommend.add_argument("--limit", type=int, default=5, help="Maximum recommendations to return.")
    recommend.set_defaults(func=cmd_recommend)

    snippet = sub.add_parser("snippet")
    snippet.add_argument("--dry-run", action="store_true")
    snippet.add_argument("--output", default=None)
    snippet.set_defaults(func=cmd_snippet)

    probe = sub.add_parser("probe")
    probe.set_defaults(func=cmd_probe)

    profile = sub.add_parser("profile")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.set_defaults(func=cmd_profile_list)
    profile_inspect = profile_sub.add_parser("inspect")
    profile_inspect.add_argument("id")
    profile_inspect.set_defaults(func=cmd_profile_inspect)
