from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config_adapter import ensure_external_dir, read_config, remove_external_dir, write_config
from .doctor import doctor_ok, run_doctor
from .hashutil import sha256_file
from .installer import OmhError, install_skill_pack, uninstall_skill_pack
from .manifest import read_manifest
from .paths import resolve_paths
from .runtime_artifacts import (
    DELEGATION_RESULTS,
    PRIVACY_MODES,
    RUN_STATUSES,
    create_run,
    list_runs,
    read_state,
    show_run,
    update_state,
    write_delegation,
)
from .skill_pack import builtin_harnesses, builtin_definitions
from .snippet import WORKSPACE_SNIPPET


def _paths(args: argparse.Namespace):
    return resolve_paths(args.omh_home, args.hermes_home)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_install(args: argparse.Namespace) -> int:
    paths = _paths(args)
    source_dir = Path(args.from_skills_dir or args.source).expanduser().resolve() if (args.from_skills_dir or args.source) else None
    source = str(source_dir) if source_dir else "builtin"
    result = install_skill_pack(paths, source=source, source_dir=source_dir, force=args.force, dry_run=args.dry_run)
    if not args.dry_run:
        update_state(
            paths,
            {
                "package": "oh-my-hermes-agent",
                "version": __version__,
                "manifest_path": str(paths.manifest_path),
                "manifest_sha256": sha256_file(paths.manifest_path),
                "source": source,
                "installed_skills": len(result.get("skills", [])),
                "skills_dir": str(paths.skills_dir),
            },
        )
    _print_json(result)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    return cmd_install(args)


def cmd_convert(args: argparse.Namespace) -> int:
    args.source = args.from_skills_dir
    return cmd_install(args)


def cmd_apply(args: argparse.Namespace) -> int:
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
    _print_json({"changed": change.changed, "message": change.message, "config": str(paths.hermes_config_path), "skills_dir": str(paths.skills_dir), "dry_run": args.dry_run})
    return 0


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
    paths = _paths(args)
    checks = run_doctor(paths)
    runtime_writable = any(check.name == "runtime_artifacts" and check.ok for check in checks)
    runtime_state_readable = not any(check.name == "runtime_state" and not check.ok for check in checks)
    if runtime_writable and runtime_state_readable:
        update_state(
            paths,
            {
                "last_doctor": {
                    "ok": doctor_ok(checks),
                    "checks": {check.name: check.ok for check in checks},
                }
            },
        )
    _print_json({"ok": doctor_ok(checks), "checks": [check.__dict__ for check in checks]})
    return 0 if doctor_ok(checks) else 1


def _valid_skill_names() -> set[str]:
    return {definition.name for definition in builtin_definitions()}


def _valid_harness_names() -> set[str]:
    return {harness.name for harness in builtin_harnesses()}


def _validate_runtime_names(skill: str, harness: str) -> None:
    if skill not in _valid_skill_names():
        raise OmhError(f"unknown skill for runtime record: {skill}")
    if harness not in _valid_harness_names():
        raise OmhError(f"unknown harness for runtime record: {harness}")


def cmd_runtime_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    _print_json(
        {
            "schema_version": 1,
            "runtime_dir": str(paths.runtime_dir),
            "state_path": str(paths.runtime_state_path),
            "runs_dir": str(paths.runtime_runs_dir),
            "state": read_state(paths),
        }
    )
    return 0


def cmd_runtime_runs(args: argparse.Namespace) -> int:
    _print_json({"runs": list_runs(_paths(args))})
    return 0


def cmd_runtime_show(args: argparse.Namespace) -> int:
    try:
        _print_json(show_run(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_runtime_record(args: argparse.Namespace) -> int:
    _validate_runtime_names(args.skill, args.harness)
    run = create_run(
        _paths(args),
        {
            "skill": args.skill,
            "harness": args.harness,
            "status": args.status,
            "trigger": args.trigger or "",
            "privacy": args.privacy,
            "inputs_summary": args.inputs_summary or "",
            "outputs_summary": args.outputs_summary or "",
            "verification_summary": args.verification_summary or "",
        },
    )
    _print_json({"run": run})
    return 0


def cmd_runtime_delegate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    observed = args.observed
    result = args.result
    if args.not_observed:
        observed = False
        result = result or "not_observed"
    elif observed:
        result = result or "completed"
    else:
        result = result or "not_available"
    participants = [item.strip() for item in (args.participants or "").split(",") if item.strip()]
    try:
        delegation = write_delegation(
            run_dir,
            {
                "requested": args.requested,
                "observed": observed,
                "participants": participants,
                "result": result,
                "evidence_refs": args.evidence_ref or [],
                "message": args.message or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"delegation": delegation})
    return 0


def cmd_snippet(args: argparse.Namespace) -> int:
    if args.dry_run or not args.output:
        print(WORKSPACE_SNIPPET.rstrip())
        return 0
    output = Path(args.output).expanduser().resolve()
    output.write_text(WORKSPACE_SNIPPET, encoding="utf-8")
    _print_json({"written": str(output)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omh", description="Install oh-my-hermes skills for Hermes Agent.")
    parser.add_argument("--omh-home", default=None)
    parser.add_argument("--hermes-home", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_install(p: argparse.ArgumentParser) -> None:
        p.add_argument("--from-skills-dir", default=None, help="Import skills from a local skill directory.")
        p.add_argument("--source", default=None, help="Mockable local source directory for install/update.")
        p.add_argument("--force", action="store_true")
        p.add_argument("--dry-run", action="store_true")

    install = sub.add_parser("install")
    add_common_install(install)
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update")
    add_common_install(update)
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

    snippet = sub.add_parser("snippet")
    snippet.add_argument("--dry-run", action="store_true")
    snippet.add_argument("--output", default=None)
    snippet.set_defaults(func=cmd_snippet)

    runtime = sub.add_parser("runtime")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_status = runtime_sub.add_parser("status")
    runtime_status.set_defaults(func=cmd_runtime_status)

    runtime_runs = runtime_sub.add_parser("runs")
    runtime_runs.set_defaults(func=cmd_runtime_runs)

    runtime_show = runtime_sub.add_parser("show")
    runtime_show.add_argument("run_id")
    runtime_show.set_defaults(func=cmd_runtime_show)

    runtime_record = runtime_sub.add_parser("record")
    runtime_record.add_argument("--skill", required=True)
    runtime_record.add_argument("--harness", required=True)
    runtime_record.add_argument("--status", choices=RUN_STATUSES, default="unknown")
    runtime_record.add_argument("--trigger", default="")
    runtime_record.add_argument("--privacy", choices=PRIVACY_MODES, default="metadata_only")
    runtime_record.add_argument("--inputs-summary", default="")
    runtime_record.add_argument("--outputs-summary", default="")
    runtime_record.add_argument("--verification-summary", default="")
    runtime_record.set_defaults(func=cmd_runtime_record)

    runtime_delegate = runtime_sub.add_parser("delegate")
    runtime_delegate.add_argument("--run", dest="run_id", required=True)
    runtime_delegate.add_argument("--requested", action="store_true")
    observation = runtime_delegate.add_mutually_exclusive_group()
    observation.add_argument("--observed", action="store_true")
    observation.add_argument("--not-observed", action="store_true")
    runtime_delegate.add_argument("--result", choices=DELEGATION_RESULTS, default=None)
    runtime_delegate.add_argument("--participants", default="")
    runtime_delegate.add_argument("--evidence-ref", action="append")
    runtime_delegate.add_argument("--message", default="")
    runtime_delegate.set_defaults(func=cmd_runtime_delegate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except OmhError as exc:
        print(f"omh: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
