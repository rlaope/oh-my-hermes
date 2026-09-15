"""`omh setup-profile` -- move one machine's configured OMH profile.

Named for the file it serializes (`setup-profile.json`), and deliberately not
folded into `omh profile`: that group lists and inspects the authored team role
packs in `profiles/team.py`, which are product content, while these two verbs
read and write a machine's own state.

`apply` is a dry run by default and writes only under `--apply`, matching
`omh ops rules-import` -- the other command in this tree that reads a file
someone handed you and changes local configuration from it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..installer import OmhError
from ..profiles.pack import (
    SetupProfilePackError,
    apply_setup_profile_pack,
    build_setup_profile_pack,
    read_setup_profile_pack,
    setup_profile_pack_export_report,
    write_setup_profile_pack,
)
from .common import _paths, _print_json, _wants_json
from .quickstart import _color, _use_color


def cmd_setup_profile_export(args: argparse.Namespace) -> int:
    paths = _paths(args)
    output = getattr(args, "output", None)
    try:
        if output:
            pack = write_setup_profile_pack(paths, Path(output))
        else:
            pack = build_setup_profile_pack(paths)
    except SetupProfilePackError as error:
        raise OmhError(str(error)) from error
    report = setup_profile_pack_export_report(pack, output_path=str(output or ""))
    if not output:
        report["pack"] = pack
    if _wants_json(args):
        _print_json(report)
    else:
        _print_export(report)
    return 0


def cmd_setup_profile_apply(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        pack = read_setup_profile_pack(getattr(args, "from_path"))
        report = apply_setup_profile_pack(
            paths,
            pack,
            dry_run=not bool(getattr(args, "apply", False)),
            with_mcp=bool(getattr(args, "with_mcp", False)),
            mcp_config_path=getattr(args, "mcp_config_path", None),
        )
    except SetupProfilePackError as error:
        raise OmhError(str(error)) from error
    if _wants_json(args):
        _print_json(report)
    else:
        _print_apply(report)
    return 0


def add_setup_profile_commands(sub: argparse._SubParsersAction) -> None:
    setup_profile = sub.add_parser(
        "setup-profile",
        help="Export this machine's configured OMH profile, or apply an exported one.",
    )
    setup_profile_sub = setup_profile.add_subparsers(dest="setup_profile_command", required=True)

    export = setup_profile_sub.add_parser(
        "export",
        help="Serialize the configured profile, capability policy, MCP recipe, and model aliases.",
    )
    export.add_argument(
        "--output",
        default=None,
        help="Write the pack to this local file. Without it, --json carries the pack under `pack` for piping.",
    )
    export.add_argument("--json", action="store_true", help="Print the full machine-readable export report.")
    export.set_defaults(func=cmd_setup_profile_export)

    apply_parser = setup_profile_sub.add_parser(
        "apply",
        help="Apply an exported profile pack to this install; dry-run by default, --apply writes.",
    )
    apply_parser.add_argument(
        "--from",
        dest="from_path",
        required=True,
        help="Local profile pack file to apply. OMH never fetches one; copy it here yourself.",
    )
    apply_parser.add_argument("--apply", action="store_true", help="Write the planned profile (default is dry-run).")
    apply_parser.add_argument(
        "--with-mcp",
        action="store_true",
        help="Also write the pack's MCP host config entry. Without it the recipe is reported, not written.",
    )
    apply_parser.add_argument(
        "--mcp-config-path",
        default=None,
        help="Explicit host config path for --with-mcp instead of the host's default location.",
    )
    apply_parser.add_argument("--json", action="store_true", help="Print the full machine-readable apply report.")
    apply_parser.set_defaults(func=cmd_setup_profile_apply)


def _render_value(value: object) -> str:
    """One field's value as a terminal reads it, not as Python repr writes it."""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    if isinstance(value, dict):
        return ", ".join(f"{key}={value[key]}" for key in sorted(value)) if value else "none"
    return str(value) if value != "" else "none"


def _print_export(report: dict[str, object]) -> None:
    use_color = _use_color()
    print(_color("OMH setup profile export", "1;36", use_color))
    print(f"  Pack id: {report.get('pack_id', '')}")
    print(f"  Built by: OMH {report.get('source_omh_version', '')}")
    sections = report.get("sections", [])
    if isinstance(sections, list):
        print(f"  Sections: {', '.join(str(item) for item in sections)}")
    print(f"  Model aliases: {report.get('model_alias_status', '')} ({report.get('model_alias_count', 0)})")
    print(f"  MCP host config: {report.get('mcp_status', '')}")
    withheld = report.get("withheld", [])
    print(_color("Withheld", "1;32", use_color))
    if isinstance(withheld, list) and withheld:
        for entry in withheld:
            if isinstance(entry, dict):
                print(f"  - {entry.get('field', '')}: {entry.get('reason', '')}")
    else:
        print("  Nothing was withheld.")
    output_path = str(report.get("output_path", ""))
    print(_color("Next", "1;32", use_color))
    if output_path:
        print(f"  Written to {output_path}")
    else:
        print("  Nothing was written. Re-run with --output <pack.json> to write the pack to a file,")
        print("  or with --json to read it under `pack`.")
    print(f"  {report.get('apply_command', '')}")
    print(f"  {report.get('transport_boundary', '')}")


def _print_apply(report: dict[str, object]) -> None:
    use_color = _use_color()
    header = "applied" if report.get("applied") else "dry run, nothing written"
    print(_color(f"OMH setup profile apply ({header})", "1;36", use_color))
    print(f"  Pack id: {report.get('pack_id', '')}")
    print(f"  Built by OMH {report.get('source_omh_version', '')} -> this OMH {report.get('target_omh_version', '')}")
    fields = report.get("fields", [])
    print(_color("Fields", "1;32", use_color))
    if isinstance(fields, list):
        for row in fields:
            if not isinstance(row, dict):
                continue
            mark = "not applied" if row.get("status") == "not_applied" else str(row.get("status", ""))
            print(f"  [{mark}] {row.get('field', '')} = {_render_value(row.get('value'))}")
            reason = str(row.get("reason", ""))
            if reason:
                print(f"      {reason}")
    withheld = report.get("withheld", [])
    if isinstance(withheld, list) and withheld:
        print(_color("Withheld at export", "1;32", use_color))
        for entry in withheld:
            if isinstance(entry, dict):
                print(f"  - {entry.get('field', '')}: {entry.get('reason', '')}")
    next_actions = report.get("next_actions", [])
    if isinstance(next_actions, list) and next_actions:
        print(_color("Next", "1;32", use_color))
        for action in next_actions:
            print(f"  {action}")
    if not report.get("applied"):
        print("  Re-run with --apply to write the profile.")
    print(f"  Profile file: {report.get('setup_profile_path', '')}")
