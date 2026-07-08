from __future__ import annotations

import argparse

from ..installer import OmhError
from ..plugin_observations import (
    PLUGIN_HOST_OBSERVATION_EVENTS,
    PLUGIN_HOST_OBSERVATION_STATUSES,
    read_plugin_host_observations,
    record_plugin_host_observation,
)
from .common import _paths, _print_json


def cmd_plugin_observe_host(args: argparse.Namespace) -> int:
    try:
        observation = record_plugin_host_observation(
            _paths(args),
            host=args.host,
            session_id=args.session_id,
            event=args.event,
            status=args.status,
            evidence_refs=args.evidence_ref or [],
            message=args.message or "",
            source=args.source or "wrapper",
            tool=args.tool or "",
            hook=args.hook or "",
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"observation": observation})
    return 0


def cmd_plugin_observations(args: argparse.Namespace) -> int:
    limit = int(args.limit)
    if limit < 1:
        raise OmhError("--limit must be at least 1")
    observations, errors = read_plugin_host_observations(_paths(args), limit=limit)
    _print_json(
        {
            "schema_version": "omh_plugin_host_observations/v1",
            "observations": observations,
            "errors": errors,
            "claim_boundary": (
                "Plugin host observations are host/wrapper-supplied metadata. They prove only observed "
                "plugin load/use events, not coding dispatch, implementation, review, CI, merge, or "
                "unrecorded tool/hook calls."
            ),
        }
    )
    return 0


def _add_plugin_commands(sub) -> None:
    plugin = sub.add_parser(
        "plugin",
        help="Record host-observed OMH plugin load/use evidence without claiming execution.",
    )
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)

    observe_host = plugin_sub.add_parser(
        "observe-host",
        help="Record Hermes host or wrapper evidence that the OMH plugin was loaded or used.",
    )
    observe_host.add_argument("--host", required=True, help="Hermes host or wrapper name that observed the plugin.")
    observe_host.add_argument("--session", dest="session_id", required=True, help="Host session id or stable session reference.")
    observe_host.add_argument("--event", choices=PLUGIN_HOST_OBSERVATION_EVENTS, required=True)
    observe_host.add_argument("--status", choices=PLUGIN_HOST_OBSERVATION_STATUSES, default="observed")
    observe_host.add_argument("--source", default="wrapper", help="Observation source, such as wrapper, host, operator, or test.")
    observe_host.add_argument("--tool", default="", help="Tool name for tool_call observations.")
    observe_host.add_argument("--hook", default="", help="Hook name for hook_call observations.")
    observe_host.add_argument("--evidence-ref", action="append", help="Required for observed records; use host log/session/tool refs.")
    observe_host.add_argument("--message", default="", help="Short metadata-only summary. Do not pass raw prompts.")
    observe_host.set_defaults(func=cmd_plugin_observe_host)

    observations = plugin_sub.add_parser("observations", help="List recent plugin host observation records.")
    observations.add_argument("--limit", type=int, default=20)
    observations.add_argument("--json", action="store_true", help="Accepted for consistency; observations are always JSON.")
    observations.set_defaults(func=cmd_plugin_observations)
