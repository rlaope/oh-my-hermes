from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..installer import OmhError
from ..system.local_store import atomic_write_text
from ..workflows.hermes_achievements import (
    BADGE_STATES,
    filter_badges,
    find_badge,
    observe_achievements,
    render_achievements_markdown,
)
from .common import _paths, _print_json, _wants_json


def cmd_achievements_summary(args: argparse.Namespace) -> int:
    payload = observe_achievements(_paths(args), recent_limit=args.recent)
    if _wants_json(args):
        _print_json(payload)
        return 0
    summary = payload["summary"]
    print("Hermes achievements (OMH observation)")
    if not payload["observed"]:
        print("No local hermes-achievements plugin artifacts were observed.")
        print(f"Looked in: {payload['source']['plugin_dir']}")
        print("Open the Hermes dashboard achievements tab once so the plugin writes its scan snapshot.")
    else:
        print(f"Unlocked: {summary['unlocked_count']} / {summary['total_count']}")
        if summary["top_tier"]:
            print(f"Top tier: {summary['top_tier']}")
        if summary["last_scan_at"]:
            print(f"Last plugin scan: {summary['last_scan_at']}")
        if payload["recent_unlocks"]:
            print("Recent unlocks:")
        for badge in payload["recent_unlocks"]:
            tier = f" [{badge['tier']}]" if badge["tier"] else ""
            unlocked_at = f" ({badge['unlocked_at']})" if badge["unlocked_at"] else ""
            print(f"- {badge['name']}{tier}{unlocked_at}")
        for error in payload["errors"]:
            print(f"Warning: {error}")
    print(f"Boundary: {payload['evidence_boundary']}")
    print("For machine-readable output, rerun with `--json`.")
    return 0


def cmd_achievements_list(args: argparse.Namespace) -> int:
    payload = observe_achievements(_paths(args))
    badges = filter_badges(
        payload["badges"],
        category=args.category or "",
        state=args.state or "",
        limit=args.limit,
    )
    if _wants_json(args):
        _print_json(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "filters": {"category": args.category or "", "state": args.state or "", "limit": args.limit},
                "count": len(badges),
                "badges": badges,
                "errors": payload["errors"],
                "evidence_boundary": payload["evidence_boundary"],
            }
        )
        return 0
    print("Hermes achievements badges (OMH observation)")
    if not badges:
        print("No badges matched the observed artifacts and filters.")
    for badge in badges:
        tier = f" [{badge['tier']}]" if badge["tier"] else ""
        progress = badge.get("progress_percent")
        progress_text = f" {float(progress):g}%" if isinstance(progress, (int, float)) else ""
        print(f"- {badge['name']} (`{badge['badge_id']}`) {badge['category']}/{badge['state']}{tier}{progress_text}")
    print("For machine-readable output, rerun with `--json`.")
    return 0


def cmd_achievements_show(args: argparse.Namespace) -> int:
    payload = observe_achievements(_paths(args))
    badge = find_badge(payload["badges"], args.badge_id)
    if badge is None:
        raise OmhError(f"badge not found in observed artifacts: {args.badge_id}")
    if _wants_json(args):
        _print_json(
            {
                "schema_version": payload["schema_version"],
                "badge": badge,
                "evidence_boundary": payload["evidence_boundary"],
            }
        )
        return 0
    print(f"Badge: {badge['name']} (`{badge['badge_id']}`)")
    for key in ("category", "tier", "state", "unlocked_at"):
        if badge.get(key):
            print(f"{key.replace('_', ' ').title()}: {badge[key]}")
    progress = badge.get("progress_percent")
    if isinstance(progress, (int, float)):
        print(f"Progress: {float(progress):g}%")
    print(f"Boundary: {payload['evidence_boundary']}")
    return 0


def cmd_achievements_export(args: argparse.Namespace) -> int:
    payload = observe_achievements(_paths(args))
    if args.format == "json":
        document = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    else:
        document = render_achievements_markdown(payload)
    if args.out:
        out_path = Path(args.out).expanduser()
        atomic_write_text(out_path, document)
        if _wants_json(args):
            _print_json({"format": args.format, "status": payload["status"], "written_path": str(out_path)})
        else:
            print(f"Wrote {args.format} export to {out_path}")
        return 0
    print(document, end="")
    return 0


def _add_achievements_commands(sub) -> None:
    achievements = sub.add_parser(
        "achievements",
        help="Observe local hermes-achievements plugin badges without rescanning Hermes session history.",
    )
    achievements_sub = achievements.add_subparsers(dest="achievements_command", required=True)

    summary = achievements_sub.add_parser("summary", help="Summarize observed unlocks, top tier, and recent unlocks.")
    summary.add_argument("--recent", type=int, default=5, help="Maximum recent unlocks to include.")
    summary.add_argument("--json", action="store_true", help="Print the full machine-readable observation payload.")
    summary.set_defaults(func=cmd_achievements_summary)

    list_cmd = achievements_sub.add_parser("list", help="List observed badges with optional category/state filters.")
    list_cmd.add_argument("--category", default=None, help="Only include badges in this category.")
    list_cmd.add_argument("--state", choices=BADGE_STATES, default=None, help="Only include badges in this state.")
    list_cmd.add_argument("--limit", type=int, default=0, help="Maximum badges to include (0 means all).")
    list_cmd.add_argument("--json", action="store_true", help="Print machine-readable badge list.")
    list_cmd.set_defaults(func=cmd_achievements_list)

    show = achievements_sub.add_parser("show", help="Show one observed badge by id or name.")
    show.add_argument("badge_id")
    show.add_argument("--json", action="store_true", help="Print the machine-readable badge record.")
    show.set_defaults(func=cmd_achievements_show)

    export = achievements_sub.add_parser("export", help="Export the observation payload as JSON or Markdown.")
    export.add_argument("--format", choices=("json", "md"), default="json")
    export.add_argument("--out", default=None, help="Write the export to this path instead of stdout.")
    export.add_argument("--json", action="store_true", help="Print a machine-readable write receipt with --out.")
    export.set_defaults(func=cmd_achievements_export)
