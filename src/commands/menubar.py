from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence

from ..installer import OmhError
from ..menubar_app import setup_menubar_app, start_menubar_app, stop_menubar_app, uninstall_menubar_app
from ..menubar_status import build_menubar_status_payload, read_process_overlay_file
from .common import _paths, _print_json, _wants_json


def cmd_menubar_status(args: argparse.Namespace) -> int:
    try:
        overlay = read_process_overlay_file(args.overlay) if args.overlay else None
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    payload = build_menubar_status_payload(
        _paths(args),
        limit=args.limit,
        process_overlay=overlay,
        observe_local_processes=bool(args.observe_local_processes),
        now=args.now,
    )
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_format_menubar_status(payload))
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

    status = menubar_sub.add_parser("status", help="Show the OMH menu bar status summary.")
    status.add_argument("--limit", type=int, default=3, help="Maximum recent runtime runs to inspect.")
    status.add_argument("--overlay", default=None, help="Optional menubar_process_overlay/v1 JSON from the menu bar app.")
    status.add_argument(
        "--observe-local-processes",
        action="store_true",
        help="Opt in to local Hermes process observation for the native menu bar helper.",
    )
    status.add_argument("--now", default=None, help="Optional ISO timestamp for deterministic overlay TTL evaluation.")
    status.add_argument("--json", action="store_true", help="Print the full menubar_status/v1 payload.")
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


def _format_menubar_status(payload: Mapping[str, object]) -> str:
    display = _as_mapping(payload.get("display"))
    settings = _as_mapping(payload.get("settings"))
    versions = _as_mapping(payload.get("versions"))
    process_overlay = _as_mapping(payload.get("process_overlay"))

    lines = ["OMH menu bar status", "Summary"]
    headline = _text(display.get("headline")) or "OMH status"
    summary = _text(display.get("summary_line"))
    lines.append(f"  Status: {headline}")
    if summary:
        lines.append(f"  Activity: {summary}")
    omh_version = _as_mapping(versions.get("omh"))
    if omh_version:
        lines.append(f"  OMH version: {_text(omh_version.get('value')) or 'unknown'}")

    for key in ("omh_connection", "hermes_targets", "coding_handoff", "send_mode"):
        setting = _as_mapping(settings.get(key))
        label = _text(setting.get("label")) if setting else ""
        if label:
            lines.append(f"  {label}")

    cards = _as_sequence(display.get("menu_cards"))
    for card_value in cards:
        card = _as_mapping(card_value)
        if not card:
            continue
        title = _text(card.get("title")) or "Status"
        lines.extend(["", title])
        columns = [_text(column) for column in _as_sequence(card.get("columns"))]
        rows = [_as_mapping(row) for row in _as_sequence(card.get("rows"))]
        agent_rows = [row for row in rows if row.get("kind") == "agent_status"]
        if columns and agent_rows:
            lines.append(f"  {_pad(columns[0], 20)} {_pad(columns[1], 14)} {columns[2] if len(columns) > 2 else 'Status'}")
            for row in agent_rows:
                lines.append(
                    "  "
                    f"{_pad(_text(row.get('agent')) or 'unknown', 20)} "
                    f"{_pad(_text(row.get('pid')) or 'not observed', 14)} "
                    f"{_text(row.get('status')) or 'unknown'}"
                )
        else:
            for row in rows:
                label = _text(row.get("label"))
                value = _text(row.get("value"))
                detail = _text(row.get("detail"))
                if not label and not value:
                    continue
                value = _friendly_row_value(label, value)
                line = f"  {label}: {value}" if label and value else f"  {label or value}"
                if detail:
                    line = f"{line} - {detail}"
                lines.append(line)
        footer = _text(card.get("footer"))
        if footer:
            lines.append(f"  Note: {footer}")

    overlay_status = _text(process_overlay.get("status"))
    if overlay_status:
        lines.extend(["", "Observation"])
        lines.append(f"  Process overlay: {overlay_status.replace('_', ' ')}")
        applied_count = _text(process_overlay.get("applied_count"))
        if applied_count and applied_count != "0":
            lines.append(f"  Observed rows: {applied_count}")
        lines.append("  Boundary: configured targets are not PID evidence unless observed by the helper.")

    lines.extend(["", "For machine-readable output, rerun with `--json`."])
    return "\n".join(lines)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _friendly_row_value(label: str, value: str) -> str:
    if label.lower() == "boundary" and value.lower() == "unknown":
        return "no active evidence state"
    return value


def _pad(value: str, width: int) -> str:
    if len(value) > width:
        return f"{value[: max(0, width - 3)]}..."
    return value.ljust(width)
