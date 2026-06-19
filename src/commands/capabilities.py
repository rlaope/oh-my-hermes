from __future__ import annotations

import argparse

from ..capabilities.registry import filtered_capability_snapshot, inspect_capability, list_capabilities
from ..capabilities.schema import CAPABILITY_SECTION_CHOICES
from ..installer import OmhError
from .common import _print_json, _wants_json


def cmd_capabilities_export(args: argparse.Namespace) -> int:
    try:
        _print_json(filtered_capability_snapshot(args.section))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_capabilities_list(args: argparse.Namespace) -> int:
    try:
        payload = list_capabilities(args.section)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
        return 0
    print("OMH capabilities")
    for section in payload["sections"]:
        ids = section["ids"]
        print(f"- {section['section']}: {len(ids)}")
        if ids:
            print(f"  {', '.join(str(item) for item in ids[:12])}")
            if len(ids) > 12:
                print(f"  ... {len(ids) - 12} more")
    print("For machine-readable output, rerun with `--json`.")
    return 0


def cmd_capabilities_inspect(args: argparse.Namespace) -> int:
    try:
        payload = inspect_capability(args.identifier, section=args.section)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
        return 0
    capability = payload["capability"]
    print(f"OMH capability: {payload['id']}")
    print(f"Section: {payload['section']}")
    if isinstance(capability, dict):
        for key in ("schema_version", "display_name", "category", "phase", "runtime_claim", "evidence_boundary"):
            if capability.get(key):
                print(f"{key.replace('_', ' ').title()}: {capability[key]}")
    print("For machine-readable output, rerun with `--json`.")
    return 0


def _add_capabilities_commands(sub) -> None:
    capabilities = sub.add_parser("capabilities", help="Inspect OMH capability manifests for Hermes/plugin/wrapper use.")
    capabilities_sub = capabilities.add_subparsers(dest="capabilities_command", required=True)

    export = capabilities_sub.add_parser("export", help="Export the deterministic OMH capability manifest.")
    export.add_argument("--section", choices=CAPABILITY_SECTION_CHOICES, default=None)
    export.add_argument("--json", action="store_true", help="Accepted for consistency; export is always machine-readable JSON.")
    export.set_defaults(func=cmd_capabilities_export)

    list_cmd = capabilities_sub.add_parser("list", help="List capability ids by section.")
    list_cmd.add_argument("--section", choices=CAPABILITY_SECTION_CHOICES, default=None)
    list_cmd.add_argument("--json", action="store_true", help="Print machine-readable capability id lists.")
    list_cmd.set_defaults(func=cmd_capabilities_list)

    inspect = capabilities_sub.add_parser("inspect", help="Inspect one capability by id.")
    inspect.add_argument("identifier")
    inspect.add_argument("--section", choices=CAPABILITY_SECTION_CHOICES, default=None)
    inspect.add_argument("--json", action="store_true", help="Print the full machine-readable capability.")
    inspect.set_defaults(func=cmd_capabilities_inspect)
