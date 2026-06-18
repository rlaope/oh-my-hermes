from __future__ import annotations

import argparse

from ..installer import OmhError
from ..menubar_app import setup_menubar_app, start_menubar_app, stop_menubar_app, uninstall_menubar_app
from ..menubar_status import build_menubar_status_payload, read_process_overlay_file
from .common import _paths, _print_json


def cmd_menubar_status(args: argparse.Namespace) -> int:
    try:
        overlay = read_process_overlay_file(args.overlay) if args.overlay else None
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        build_menubar_status_payload(
            _paths(args),
            limit=args.limit,
            process_overlay=overlay,
            now=args.now,
        )
    )
    return 0


def cmd_menubar_install(args: argparse.Namespace) -> int:
    try:
        payload = setup_menubar_app(
            _paths(args),
            dry_run=bool(args.dry_run),
            start=not bool(args.no_start),
            force=bool(args.force),
        )
    except RuntimeError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_menubar_start(args: argparse.Namespace) -> int:
    _print_json(start_menubar_app(_paths(args)))
    return 0


def cmd_menubar_stop(args: argparse.Namespace) -> int:
    _print_json(stop_menubar_app(_paths(args)))
    return 0


def cmd_menubar_uninstall(args: argparse.Namespace) -> int:
    _print_json(uninstall_menubar_app(_paths(args), dry_run=bool(args.dry_run)))
    return 0


def _add_menubar_commands(sub) -> None:
    menubar = sub.add_parser("menubar", help="Install or inspect the OMH menu bar helper.")
    menubar_sub = menubar.add_subparsers(dest="menubar_command", required=True)

    status = menubar_sub.add_parser("status", help="Print the macOS menu bar agent-status view model.")
    status.add_argument("--limit", type=int, default=3, help="Maximum recent runtime runs to inspect.")
    status.add_argument("--overlay", default=None, help="Optional menubar_process_overlay/v1 JSON from the menu bar app.")
    status.add_argument("--now", default=None, help="Optional ISO timestamp for deterministic overlay TTL evaluation.")
    status.set_defaults(func=cmd_menubar_status)

    install = menubar_sub.add_parser("install", help="Install and start the native macOS OMH menu bar helper when supported.")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--force", action="store_true")
    install.add_argument("--no-start", action="store_true", help="Install the helper without starting the LaunchAgent.")
    install.set_defaults(func=cmd_menubar_install)

    start = menubar_sub.add_parser("start", help="Start the installed OMH menu bar helper.")
    start.set_defaults(func=cmd_menubar_start)

    stop = menubar_sub.add_parser("stop", help="Stop the OMH menu bar helper LaunchAgent.")
    stop.set_defaults(func=cmd_menubar_stop)

    uninstall = menubar_sub.add_parser("uninstall", help="Stop and remove the OMH menu bar helper.")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.set_defaults(func=cmd_menubar_uninstall)
