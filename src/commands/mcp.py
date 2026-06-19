from __future__ import annotations

import argparse

from ..installer import OmhError
from ..mcp_bridge import (
    MCP_HOST_SESSION_EVENTS,
    MCP_HOST_SESSION_STATUSES,
    build_mcp_manifest,
    read_mcp_host_sessions,
    record_mcp_host_session,
    run_stdio_mcp_server,
)
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


def cmd_mcp_observe_host(args: argparse.Namespace) -> int:
    try:
        observation = record_mcp_host_session(
            _paths(args),
            host=args.host,
            session_id=args.session_id,
            event=args.event,
            status=args.status,
            evidence_refs=args.evidence_ref or [],
            message=args.message or "",
            source=args.source or "wrapper",
            tool=args.tool or "",
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"observation": observation})
    return 0


def cmd_mcp_sessions(args: argparse.Namespace) -> int:
    limit = int(args.limit)
    if limit < 1:
        raise OmhError("--limit must be at least 1")
    sessions, errors = read_mcp_host_sessions(_paths(args), limit=limit)
    _print_json(
        {
            "schema_version": "omh_mcp_host_sessions/v1",
            "sessions": sessions,
            "errors": errors,
            "claim_boundary": (
                "MCP host sessions are host/wrapper-supplied metadata. They do not prove connector "
                "execution, coding dispatch, implementation, review, CI, merge, or unrecorded tool calls."
            ),
        }
    )
    return 0


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

    observe_host = mcp_sub.add_parser(
        "observe-host",
        help="Record host-observed MCP bridge load or session evidence without claiming execution.",
    )
    observe_host.add_argument("--host", required=True, help="Host or wrapper name that observed the MCP bridge.")
    observe_host.add_argument("--session", dest="session_id", required=True, help="Host session id or stable session reference.")
    observe_host.add_argument("--event", choices=MCP_HOST_SESSION_EVENTS, required=True)
    observe_host.add_argument("--status", choices=MCP_HOST_SESSION_STATUSES, default="observed")
    observe_host.add_argument("--source", default="wrapper", help="Observation source, such as wrapper, host, operator, or test.")
    observe_host.add_argument("--tool", default="", help="Tool name for tool_call observations.")
    observe_host.add_argument("--evidence-ref", action="append", help="Required for observed records; use host log/session/tool refs.")
    observe_host.add_argument("--message", default="", help="Short metadata-only summary. Do not pass raw prompts.")
    observe_host.set_defaults(func=cmd_mcp_observe_host)

    sessions = mcp_sub.add_parser("sessions", help="List recent MCP host observation records.")
    sessions.add_argument("--limit", type=int, default=20)
    sessions.set_defaults(func=cmd_mcp_sessions)
