from __future__ import annotations

import argparse

from .. import __version__
from ..installer import OmhError
from ..release import (
    DEFAULT_HERMES_SKILL,
    DEFAULT_HERMES_TAP,
    INSTALL_PATHS,
    hermes_release_smoke_plan,
    release_readiness_checklist,
    run_hermes_release_smoke,
    run_installed_command_smoke,
)
from .common import _print_json, _wants_json


def cmd_release_checklist(args: argparse.Namespace) -> int:
    try:
        payload = release_readiness_checklist(version=args.version or __version__, omh_command=args.omh_command)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_release_checklist_summary(payload)
    return 0


def cmd_release_hermes_smoke(args: argparse.Namespace) -> int:
    if args.timeout < 1:
        raise OmhError("release hermes-smoke --timeout must be at least 1")
    if args.live and not args.target_confirmed and not args.hermes_home:
        raise OmhError(
            "release hermes-smoke --live mutates the target Hermes profile; pass --target-confirmed "
            "or set top-level --hermes-home to an explicit smoke profile"
        )
    if args.live:
        payload = run_hermes_release_smoke(
            install_path=args.install_path,
            skill=args.skill,
            tap=args.tap,
            omh_command=args.omh_command,
            omh_home=args.omh_home,
            hermes_home=args.hermes_home,
            timeout_seconds=args.timeout,
            include_command_smoke=args.include_command_smoke,
        )
        _print_json(payload)
        return 0 if payload["ok"] else 1
    installed_command_smoke = (
        run_installed_command_smoke(
            omh_command=args.omh_command,
            omh_home=args.omh_home,
            hermes_home=args.hermes_home,
            timeout_seconds=args.timeout,
        )
        if args.include_command_smoke
        else None
    )
    payload = hermes_release_smoke_plan(
        install_path=args.install_path,
        skill=args.skill,
        tap=args.tap,
        omh_command=args.omh_command,
        omh_home=args.omh_home,
        hermes_home=args.hermes_home,
        installed_command_smoke=installed_command_smoke,
    )
    _print_json(payload)
    return 0 if payload["ok"] else 1


def _add_release_commands(sub) -> None:
    release = sub.add_parser("release", help="Plan or run release smoke checks for real Hermes installation paths.")
    release_sub = release.add_subparsers(dest="release_command", required=True)

    checklist = release_sub.add_parser(
        "checklist",
        help="Print the deterministic release readiness checklist.",
    )
    checklist.add_argument("--version", default="", help="Release version to prepare, such as 1.0.0 or v1.0.0.")
    checklist.add_argument("--omh-command", default="omh", help="Installed OMH executable name or path to show in smoke commands.")
    checklist.add_argument("--json", action="store_true", help="Print the machine-readable release checklist payload.")
    checklist.set_defaults(func=cmd_release_checklist)

    smoke = release_sub.add_parser(
        "hermes-smoke",
        help="Plan or run the release smoke for a real Hermes CLI skill install.",
    )
    smoke.add_argument("--live", action="store_true", help="Actually run the commands against the target Hermes profile.")
    smoke.add_argument(
        "--target-confirmed",
        action="store_true",
        help="Confirm that --live may mutate the resolved Hermes profile when no explicit --hermes-home was provided.",
    )
    smoke.add_argument(
        "--install-path",
        choices=INSTALL_PATHS,
        default="tap",
        help="Install path to exercise before list/check/inspect verification.",
    )
    smoke.add_argument("--skill", default=DEFAULT_HERMES_SKILL, help="Hermes skill identifier to install/check.")
    smoke.add_argument("--tap", default=DEFAULT_HERMES_TAP, help="Hermes skill tap repository to add for tap installs.")
    smoke.add_argument("--omh-command", default="omh", help="OMH executable to use for the setup install path.")
    smoke.add_argument(
        "--include-command-smoke",
        action="store_true",
        help="Also execute installed `omh --help` and installed setup-path plan rendering without mutating Hermes.",
    )
    smoke.add_argument("--timeout", type=int, default=30, help="Per-command timeout in seconds for --live or --include-command-smoke.")
    smoke.set_defaults(func=cmd_release_hermes_smoke)


def _print_release_checklist_summary(payload: dict[str, object]) -> None:
    print(f"OMH release checklist for {payload['version']} ({payload['tag']})")
    print("Mode: plan; observed evidence: no")
    print("Boundary: this command does not run checks, tag releases, or mutate Hermes.")
    print("")
    print("Required gates:")
    items = payload.get("items", [])
    required_items = [item for item in items if isinstance(item, dict) and item.get("required")]
    for index, item in enumerate(required_items, start=1):
        marker = "profile-mutating" if item.get("mutates_profile") else "local"
        if item.get("requires_release_authority"):
            marker = f"{marker}, release authority"
        print(f"  {index}. {item['id']} [{item['phase']}; {marker}]")
        print(f"     {item['command']}")
        print(f"     Evidence: {item['evidence_required']}")
    optional_items = [item for item in items if isinstance(item, dict) and not item.get("required")]
    authority_items = [item for item in optional_items if item.get("requires_release_authority")]
    non_authority_items = [item for item in optional_items if not item.get("requires_release_authority")]
    if authority_items:
        print("")
        print("Manual release-authority actions after evidence is attached:")
        for item in authority_items:
            print(f"  - {item['id']} [{item['phase']}; release authority]")
            print(f"    {item['command']}")
    if non_authority_items:
        print("")
        print("Optional follow-ups after evidence is attached:")
        for item in non_authority_items:
            print(f"  - {item['id']} [{item['phase']}]")
            print(f"    {item['command']}")
    print("")
    print(f"Next: {payload['recommended_next_action']}")
    print("For machine-readable output, rerun with `--json`.")
