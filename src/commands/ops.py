from __future__ import annotations

import argparse

from ..installer import OmhError
from ..operations import (
    ARTIFACT_STATUSES,
    KINDS_BY_SURFACE,
    SURFACES,
    build_operation_artifact,
    export_operations_bundle,
    list_operation_artifacts,
    show_operation_artifact,
    validate_operations_store,
    write_operation_artifact,
)
from .common import _paths, _print_json


def cmd_ops_write(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        artifact = build_operation_artifact(
            surface=args.surface,
            kind=args.kind,
            title=args.title,
            summary=args.summary,
            status=args.status,
            observation_status=_observation_status(args),
            source=args.source,
            inputs_summary=args.inputs_summary,
            sections=args.section or [],
            decisions=args.decision or [],
            action_items=args.action or [],
            metrics=args.metric or [],
            references=args.reference or [],
            assumptions=args.assumption or [],
        )
        written = write_operation_artifact(paths, artifact)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_write_result/v1",
            "artifact": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "operations_dir": str(paths.operations_dir),
                "index_path": str(paths.operations_index_path),
                "index_authority": "cache_only",
            },
            "boundary": {
                "prepared_is_not_observed": written["observation_status"] in {"prepared", "not_observed"},
                "ppt_scope": "markdown_or_json_outline_only",
            },
        }
    )
    return 0


def cmd_ops_list(args: argparse.Namespace) -> int:
    try:
        records = list_operation_artifacts(_paths(args), surface=args.surface or None, limit=_optional_positive_int(args.limit))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_list/v1",
            "surface": args.surface or "all",
            "count": len(records),
            "index_authority": "cache_only",
            "artifacts": records,
        }
    )
    return 0


def cmd_ops_show(args: argparse.Namespace) -> int:
    try:
        artifact = show_operation_artifact(_paths(args), args.artifact_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_show/v1", "artifact": artifact})
    return 0


def cmd_ops_validate(args: argparse.Namespace) -> int:
    result = validate_operations_store(_paths(args))
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_ops_export(args: argparse.Namespace) -> int:
    try:
        exported = export_operations_bundle(_paths(args), surface=args.surface or None, format=args.format)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_export_result/v1",
            "format": args.format,
            "surface": args.surface or "all",
            "index_authority": "cache_only",
            "ppt_scope": "markdown_or_json_outline_only",
            "export": exported,
        }
    )
    return 0


def _observation_status(args: argparse.Namespace) -> str:
    if args.observed:
        return "observed"
    if args.mixed:
        return "mixed"
    if args.not_observed:
        return "not_observed"
    return "prepared"


def _optional_positive_int(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ValueError("--limit must be at least 1")
    return value


def _add_artifact_args(parser: argparse.ArgumentParser, *, surface: str, default_kind: str) -> None:
    parser.set_defaults(func=cmd_ops_write, surface=surface)
    parser.add_argument("--kind", choices=KINDS_BY_SURFACE[surface], default=default_kind)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--status", choices=ARTIFACT_STATUSES, default="draft")
    parser.add_argument("--source", default="")
    parser.add_argument("--inputs-summary", default="")
    parser.add_argument("--section", action="append")
    parser.add_argument("--decision", action="append")
    parser.add_argument("--action", action="append")
    parser.add_argument("--metric", action="append")
    parser.add_argument("--reference", action="append")
    parser.add_argument("--assumption", action="append")
    observation = parser.add_mutually_exclusive_group()
    observation.add_argument("--observed", action="store_true", help="Mark the artifact as observed with supplied evidence.")
    observation.add_argument("--mixed", action="store_true", help="Mark the artifact as a mix of prepared and observed content.")
    observation.add_argument("--not-observed", action="store_true", help="Mark the artifact as explicitly not observed.")


def _add_ops_commands(sub) -> None:
    ops = sub.add_parser("ops", help="Create, inspect, validate, and export local operations artifacts.")
    ops_sub = ops.add_subparsers(dest="ops_command", required=True)

    rhythm = ops_sub.add_parser("rhythm", help="Create an operating rhythm artifact such as a meeting or retro record.")
    _add_artifact_args(rhythm, surface="operating-rhythm", default_kind="meeting")

    report = ops_sub.add_parser("report", help="Create a report package or PPT-ready outline artifact.")
    _add_artifact_args(report, surface="report-package", default_kind="status-package")

    reliability = ops_sub.add_parser("reliability", help="Create a reliability review artifact such as an SLO or postmortem review.")
    _add_artifact_args(reliability, surface="reliability-review", default_kind="service-review")

    list_cmd = ops_sub.add_parser("list", help="List operations artifacts from local storage.")
    list_cmd.add_argument("--surface", choices=SURFACES, default="")
    list_cmd.add_argument("--limit", type=int, default=None)
    list_cmd.set_defaults(func=cmd_ops_list)

    show = ops_sub.add_parser("show", help="Show one operations artifact by id.")
    show.add_argument("artifact_id")
    show.set_defaults(func=cmd_ops_show)

    validate = ops_sub.add_parser("validate", help="Validate operations artifacts and cache metadata.")
    validate.set_defaults(func=cmd_ops_validate)

    export = ops_sub.add_parser("export", help="Export operations artifacts as JSON or Markdown content inside JSON output.")
    export.add_argument("--surface", choices=SURFACES, default="")
    export.add_argument("--format", choices=("json", "markdown"), default="json")
    export.set_defaults(func=cmd_ops_export)
