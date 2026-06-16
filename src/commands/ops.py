from __future__ import annotations

import argparse

from ..installer import OmhError
from ..hermes_ops import (
    build_scheduled_ops_blueprint,
    list_hermes_ops_blueprints,
    show_hermes_ops_blueprint,
    summarize_hermes_ops_blueprint,
    validate_hermes_ops_store,
    write_hermes_ops_blueprint,
)
from ..operations import (
    ARTIFACT_STATUSES,
    KINDS_BY_SURFACE,
    SURFACES,
    build_operation_artifact,
    export_operations_bundle,
    list_operation_artifacts,
    show_operation_artifact,
    summarize_operation_artifact,
    validate_operations_store,
    write_operation_artifact,
)
from .common import _paths, _print_json


DEFAULT_OPS_LIST_LIMIT = 20
DEFAULT_OPS_EXPORT_LIMIT = 20
DEFAULT_BLUEPRINT_LIST_LIMIT = 20


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


def cmd_ops_blueprint(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        blueprint = build_scheduled_ops_blueprint(
            " ".join(args.request),
            title=args.title,
            schedule=args.schedule,
            delivery=args.delivery,
            silence=args.silence,
            source=args.source,
        )
        written = blueprint if args.dry_run else write_hermes_ops_blueprint(paths, blueprint)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_blueprint_result/v1",
            "blueprint": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "hermes_ops_dir": str(paths.hermes_ops_dir),
                "blueprints_dir": str(paths.hermes_ops_blueprints_dir),
                "index_path": str(paths.hermes_ops_index_path),
                "index_authority": "cache_only",
                "written": not args.dry_run,
            },
            "boundary": {
                "prepared_is_not_observed": True,
                "runtime_execution_observed": False,
                "gateway_delivery_observed": False,
                "source_retrieval_observed": False,
            },
        }
    )
    return 0


def cmd_ops_list(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        surface = args.surface or None
        limit = _limit_from_args(args, default=DEFAULT_OPS_LIST_LIMIT)
        all_records = list_operation_artifacts(paths, surface=surface)
        records = all_records if limit is None else all_records[-limit:]
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_list/v1",
            "surface": args.surface or "all",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "artifacts": [summarize_operation_artifact(record) for record in records],
        }
    )
    return 0


def cmd_ops_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        artifact = show_operation_artifact(paths, args.artifact_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_show/v1", "artifact": artifact})
    return 0


def cmd_ops_blueprint_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        blueprint = show_hermes_ops_blueprint(paths, args.blueprint_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_blueprint_show/v1", "blueprint": blueprint})
    return 0


def cmd_ops_validate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    result = validate_operations_store(paths)
    blueprint_result = validate_hermes_ops_store(paths)
    result["hermes_ops_blueprints"] = blueprint_result
    result["ok"] = bool(result["ok"]) and bool(blueprint_result["ok"])
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_ops_blueprint_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        limit = _limit_from_args(args, default=DEFAULT_BLUEPRINT_LIST_LIMIT)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    all_records = list_hermes_ops_blueprints(paths)
    records = all_records if limit is None else all_records[-limit:]
    _print_json(
        {
            "schema_version": "omh_ops_blueprint_list/v1",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "blueprints": [summarize_hermes_ops_blueprint(record) for record in records],
        }
    )
    return 0


def cmd_ops_export(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        surface = args.surface or None
        limit = _limit_from_args(args, default=DEFAULT_OPS_EXPORT_LIMIT)
        total_count = len(list_operation_artifacts(paths, surface=surface))
        exported = export_operations_bundle(paths, surface=surface, format=args.format, limit=limit)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_export_result/v1",
            "format": args.format,
            "surface": args.surface or "all",
            "limit": limit if limit is not None else "all",
            "total_count": total_count,
            "exported_count": total_count if limit is None else min(total_count, limit),
            "truncated": limit is not None and total_count > limit,
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


def _limit_from_args(args: argparse.Namespace, *, default: int) -> int | None:
    if args.all:
        return None
    return _optional_positive_int(args.limit) if args.limit is not None else default


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

    blueprint = ops_sub.add_parser("blueprint", help="Prepare a Hermes scheduled ops blueprint without creating runtime automation.")
    blueprint.add_argument("request", nargs="+", help="Natural-language scheduled ops request.")
    blueprint.add_argument("--title", default="")
    blueprint.add_argument("--schedule", default="", help="Explicit schedule/cadence hint.")
    blueprint.add_argument("--delivery", default="", help="Explicit delivery target hint.")
    blueprint.add_argument("--silence", default="", help="Explicit silence/no-change policy hint.")
    blueprint.add_argument("--source", default="", help="Optional metadata source label.")
    blueprint.add_argument("--dry-run", action="store_true", help="Print the prepared blueprint without writing it.")
    blueprint.set_defaults(func=cmd_ops_blueprint)

    blueprint_list = ops_sub.add_parser("blueprint-list", help="List prepared Hermes scheduled ops blueprints.")
    blueprint_list.add_argument("--limit", type=int, default=None)
    blueprint_list.add_argument("--all", action="store_true", help="Return all blueprint summaries instead of the default bounded window.")
    blueprint_list.set_defaults(func=cmd_ops_blueprint_list)

    blueprint_show = ops_sub.add_parser("blueprint-show", help="Show one prepared Hermes scheduled ops blueprint by id.")
    blueprint_show.add_argument("blueprint_id")
    blueprint_show.set_defaults(func=cmd_ops_blueprint_show)

    list_cmd = ops_sub.add_parser("list", help="List operations artifacts from local storage.")
    list_cmd.add_argument("--surface", choices=SURFACES, default="")
    list_cmd.add_argument("--limit", type=int, default=None)
    list_cmd.add_argument("--all", action="store_true", help="Return all artifact summaries instead of the default bounded window.")
    list_cmd.set_defaults(func=cmd_ops_list)

    show = ops_sub.add_parser("show", help="Show one operations artifact by id.")
    show.add_argument("artifact_id")
    show.set_defaults(func=cmd_ops_show)

    validate = ops_sub.add_parser("validate", help="Validate operations artifacts and cache metadata.")
    validate.set_defaults(func=cmd_ops_validate)

    export = ops_sub.add_parser("export", help="Export operations artifacts as JSON or Markdown content inside JSON output.")
    export.add_argument("--surface", choices=SURFACES, default="")
    export.add_argument("--format", choices=("json", "markdown"), default="json")
    export.add_argument("--limit", type=int, default=None)
    export.add_argument("--all", action="store_true", help="Export all matching artifacts instead of the default bounded window.")
    export.set_defaults(func=cmd_ops_export)
