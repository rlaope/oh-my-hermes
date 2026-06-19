from __future__ import annotations

import argparse

from ..mcp_bridge import build_mcp_manifest, run_stdio_mcp_server
from .common import _paths, _print_json


def cmd_mcp_manifest(args: argparse.Namespace) -> int:
    payload = build_mcp_manifest(
        _paths(args),
        command=args.command,
        include_absolute_homes=not args.portable,
    )
    _print_json(payload)
    return 0


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    return run_stdio_mcp_server(_paths(args))


def _add_mcp_commands(sub) -> None:
    mcp = sub.add_parser(
        "mcp",
        help="Expose the optional OMH MCP bridge manifest or stdio server for capable hosts.",
    )
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)

    manifest = mcp_sub.add_parser(
        "manifest",
        help="Print the OMH MCP bridge manifest/config snippet for a host that supports stdio MCP servers.",
    )
    manifest.add_argument(
        "--command",
        default="omh",
        help="Command path the MCP host should launch. Use an absolute installed omh path when needed.",
    )
    manifest.add_argument(
        "--portable",
        action="store_true",
        help="Omit absolute --omh-home/--hermes-home args so the host inherits its environment.",
    )
    manifest.set_defaults(func=cmd_mcp_manifest)

    serve = mcp_sub.add_parser(
        "serve",
        help="Run the stdio MCP bridge. This writes only JSON-RPC messages to stdout.",
    )
    serve.set_defaults(func=cmd_mcp_serve)
