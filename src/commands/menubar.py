from __future__ import annotations

import argparse

from ..installer import OmhError
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


def _add_menubar_commands(sub) -> None:
    menubar = sub.add_parser("menubar", help="Print OMH menu bar app view-model payloads.")
    menubar_sub = menubar.add_subparsers(dest="menubar_command", required=True)

    status = menubar_sub.add_parser("status", help="Print the macOS menu bar agent-status view model.")
    status.add_argument("--limit", type=int, default=3, help="Maximum recent runtime runs to inspect.")
    status.add_argument("--overlay", default=None, help="Optional menubar_process_overlay/v1 JSON from the menu bar app.")
    status.add_argument("--now", default=None, help="Optional ISO timestamp for deterministic overlay TTL evaluation.")
    status.set_defaults(func=cmd_menubar_status)
