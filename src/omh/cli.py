from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config_adapter import ensure_external_dir, read_config, remove_external_dir, write_config
from .doctor import doctor_ok, run_doctor
from .installer import OmhError, install_skill_pack, uninstall_skill_pack
from .manifest import read_manifest
from .paths import resolve_paths
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
    checks = run_doctor(_paths(args))
    _print_json({"ok": doctor_ok(checks), "checks": [check.__dict__ for check in checks]})
    return 0 if doctor_ok(checks) else 1


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
