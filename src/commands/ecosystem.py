from __future__ import annotations

import argparse

from ..catalogs.awesome_hermes_agent import (
    AwesomeHermesCatalogError,
    awesome_hermes_coverage_payload,
    awesome_hermes_item,
    awesome_hermes_summary,
)
from ..installer import OmhError
from .common import _print_json, _wants_json


def cmd_ecosystem_awesome_summary(args: argparse.Namespace) -> int:
    payload = awesome_hermes_summary()
    if _wants_json(args):
        _print_json(payload)
        return 0
    print("Awesome Hermes Agent coverage")
    print(f"Source: {payload['source_repo']} @ {payload['source_commit']}")
    print(f"Items: {payload['item_count']} total, {payload['plugin_count']} plugin-section entries")
    status_counts = payload["status_counts"]
    if isinstance(status_counts, dict):
        print("Coverage")
        for status, count in status_counts.items():
            print(f"- {status}: {count}")
    print("Boundary: coverage is OMH routing/readiness context, not plugin installation or safety approval.")
    print("For machine-readable output, rerun with `--json`.")
    return 0


def cmd_ecosystem_awesome_list(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("limit must be a positive integer")
    payload = awesome_hermes_coverage_payload(
        section=args.section,
        subsection=args.subsection,
        maturity=args.maturity,
        status=args.status,
    )
    items = payload["items"]
    if _wants_json(args):
        _print_json(payload)
        return 0
    print("Awesome Hermes Agent items")
    print(f"Matched: {payload['item_count']}")
    if isinstance(items, list):
        displayed = items[: args.limit]
        for item in displayed:
            if not isinstance(item, dict):
                continue
            surfaces = item.get("omh_surfaces", [])
            if isinstance(surfaces, list):
                shown_surfaces = [str(surface) for surface in surfaces[:4]]
                hidden_surfaces = len(surfaces) - len(shown_surfaces)
                if hidden_surfaces > 0:
                    shown_surfaces.append(f"+{hidden_surfaces} more")
                surface_text = ", ".join(shown_surfaces)
            else:
                surface_text = ""
            print(f"- {item.get('id')}: {item.get('coverage_status')} [{item.get('adoption_priority')}]")
            print(f"  {item.get('name')} -> {surface_text}")
        hidden = len(items) - len(displayed)
        if hidden > 0:
            print(f"... {hidden} more")
    print("Boundary: list output does not install, trust, or load any external plugin.")
    return 0


def cmd_ecosystem_awesome_inspect(args: argparse.Namespace) -> int:
    try:
        coverage = awesome_hermes_item(args.item_id)
    except AwesomeHermesCatalogError as exc:
        raise OmhError(str(exc)) from exc
    payload = {
        "schema_version": "awesome_hermes_agent_item_coverage/v1",
        "item": coverage.to_dict(),
        "claim_boundary": (
            "Item coverage is a local OMH comparison. It is not external repository trust, plugin load, "
            "runtime execution, or feature parity evidence."
        ),
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    item = coverage.item
    print(f"Awesome Hermes item: {item.id}")
    print(f"Name: {item.name}")
    print(f"URL: {item.url}")
    print(f"Source: {item.section} / {item.subsection}, README line {item.readme_line}")
    print(f"Coverage: {coverage.status} [{coverage.priority}]")
    print(f"OMH surfaces: {', '.join(coverage.omh_surfaces)}")
    for note in coverage.notes:
        print(f"- {note}")
    return 0


def _add_ecosystem_commands(sub) -> None:
    ecosystem = sub.add_parser("ecosystem", help="Inspect external Hermes ecosystem catalogs against OMH surfaces.")
    ecosystem_sub = ecosystem.add_subparsers(dest="ecosystem_command", required=True)

    awesome = ecosystem_sub.add_parser(
        "awesome-hermes",
        help="Compare the awesome-hermes-agent catalog with OMH workflow surfaces.",
    )
    awesome_sub = awesome.add_subparsers(dest="awesome_command", required=True)

    summary = awesome_sub.add_parser("summary", help="Summarize awesome-hermes-agent coverage.")
    summary.add_argument("--json", action="store_true", help="Print machine-readable coverage summary.")
    summary.set_defaults(func=cmd_ecosystem_awesome_summary)

    list_cmd = awesome_sub.add_parser("list", help="List awesome-hermes-agent items and mapped OMH surfaces.")
    list_cmd.add_argument("--section", default="")
    list_cmd.add_argument("--subsection", default="")
    list_cmd.add_argument("--maturity", default="")
    list_cmd.add_argument("--status", default="")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument("--json", action="store_true", help="Print machine-readable item coverage.")
    list_cmd.set_defaults(func=cmd_ecosystem_awesome_list)

    inspect = awesome_sub.add_parser("inspect", help="Inspect one awesome-hermes-agent item by id or exact name.")
    inspect.add_argument("item_id")
    inspect.add_argument("--json", action="store_true", help="Print machine-readable item coverage.")
    inspect.set_defaults(func=cmd_ecosystem_awesome_inspect)


__all__ = [
    "_add_ecosystem_commands",
    "cmd_ecosystem_awesome_inspect",
    "cmd_ecosystem_awesome_list",
    "cmd_ecosystem_awesome_summary",
]
