from __future__ import annotations

import argparse

from ..installer import OmhError
from ..release import DEFAULT_HERMES_SKILL, DEFAULT_HERMES_TAP, INSTALL_PATHS, hermes_release_smoke_plan, run_hermes_release_smoke
from .common import _print_json


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
        )
        _print_json(payload)
        return 0 if payload["ok"] else 1
    _print_json(
        hermes_release_smoke_plan(
            install_path=args.install_path,
            skill=args.skill,
            tap=args.tap,
            omh_command=args.omh_command,
            omh_home=args.omh_home,
            hermes_home=args.hermes_home,
        )
    )
    return 0


def _add_release_commands(sub) -> None:
    release = sub.add_parser("release", help="Plan or run release smoke checks for real Hermes installation paths.")
    release_sub = release.add_subparsers(dest="release_command", required=True)

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
    smoke.add_argument("--timeout", type=int, default=30, help="Per-command timeout in seconds for --live mode.")
    smoke.set_defaults(func=cmd_release_hermes_smoke)
