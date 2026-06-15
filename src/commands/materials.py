from __future__ import annotations

import argparse

from ..installer import OmhError
from ..materials import (
    EXPORT_STATUSES,
    MATERIAL_FORMATS,
    MATERIAL_KINDS,
    build_material_artifact,
    export_materials_bundle,
    list_material_artifacts,
    material_qa_ladder,
    show_material_artifact,
    summarize_material_artifact,
    validate_materials_store,
    write_material_artifact,
)
from .common import _paths, _print_json


DEFAULT_MATERIALS_LIST_LIMIT = 20
DEFAULT_MATERIALS_EXPORT_LIMIT = 20


def cmd_materials_plan(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        artifact = build_material_artifact(
            kind=args.kind,
            title=args.title,
            target_formats=args.target_format or ["md"],
            summary=args.summary,
            audience=args.audience,
            source_inputs=args.source_input or [],
            outline_sections=args.section or [],
            assumptions=args.assumption or [],
            missing_inputs=args.missing_input or [],
            export_status=_export_status(args),
            handoff_target=args.handoff_target,
            observed_files=args.observed_file or [],
            qa_checks=_qa_checks_from_args(args),
            approvals=args.approval or [],
        )
        written = write_material_artifact(paths, artifact)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_materials_plan_result/v1",
            "artifact": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "materials_dir": str(paths.materials_dir),
                "index_path": str(paths.materials_index_path),
                "index_authority": "cache_only",
            },
            "boundary": {
                "prepared_is_not_observed": written["export_status"] in {"prepared", "handoff_prepared", "not_requested"},
                "binary_export_observed": written["export_status"] == "observed",
                "qa_observed": any(check["status"] == "observed" for check in written["qa_checks"]),
                "normal_user_surface": "Hermes chat or installed skills; CLI is backend/verifier infrastructure.",
            },
        }
    )
    return 0


def cmd_materials_list(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        kind = args.kind or None
        limit = _limit_from_args(args, default=DEFAULT_MATERIALS_LIST_LIMIT)
        all_records = list_material_artifacts(paths, kind=kind)
        records = all_records if limit is None else all_records[-limit:]
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_materials_list/v1",
            "kind": args.kind or "all",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "artifacts": [summarize_material_artifact(record) for record in records],
        }
    )
    return 0


def cmd_materials_show(args: argparse.Namespace) -> int:
    try:
        artifact = show_material_artifact(_paths(args), args.material_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_materials_show/v1", "artifact": artifact})
    return 0


def cmd_materials_validate(args: argparse.Namespace) -> int:
    result = validate_materials_store(_paths(args))
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_materials_export(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        kind = args.kind or None
        limit = _limit_from_args(args, default=DEFAULT_MATERIALS_EXPORT_LIMIT)
        total_count = len(list_material_artifacts(paths, kind=kind))
        exported = export_materials_bundle(paths, kind=kind, format=args.format, limit=limit)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_materials_export_result/v1",
            "format": args.format,
            "kind": args.kind or "all",
            "limit": limit if limit is not None else "all",
            "total_count": total_count,
            "exported_count": total_count if limit is None else min(total_count, limit),
            "truncated": limit is not None and total_count > limit,
            "index_authority": "cache_only",
            "export": exported,
        }
    )
    return 0


def cmd_materials_qa_ladder(args: argparse.Namespace) -> int:
    try:
        _print_json(material_qa_ladder(args.format or None))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _export_status(args: argparse.Namespace) -> str:
    if args.not_requested:
        return "not_requested"
    if args.handoff_prepared:
        return "handoff_prepared"
    if args.observed:
        return "observed"
    if args.blocked:
        return "blocked"
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


def _add_materials_commands(sub) -> None:
    materials = sub.add_parser(
        "materials",
        help="Create, inspect, validate, and export material-processing artifacts.",
    )
    materials_sub = materials.add_subparsers(dest="materials_command", required=True)

    plan = materials_sub.add_parser(
        "plan",
        help="Create a material_artifact/v1 plan for decks, documents, spreadsheets, PDFs, HWP, or upload packages.",
    )
    plan.add_argument("--kind", choices=MATERIAL_KINDS, default="document")
    plan.add_argument("--title", required=True)
    plan.add_argument("--target-format", action="append", choices=MATERIAL_FORMATS)
    plan.add_argument("--summary", default="")
    plan.add_argument("--audience", default="")
    plan.add_argument("--source-input", action="append")
    plan.add_argument("--section", action="append")
    plan.add_argument("--assumption", action="append")
    plan.add_argument("--missing-input", action="append")
    plan.add_argument("--handoff-target", default="")
    plan.add_argument("--observed-file", action="append")
    plan.add_argument(
        "--qa-observed",
        action="append",
        metavar="FORMAT:CHECK:EVIDENCE",
        help="Record an observed QA check, for example pdf:render_preview:/tmp/render.png.",
    )
    plan.add_argument("--approval", action="append")
    export_status = plan.add_mutually_exclusive_group()
    export_status.add_argument("--not-requested", action="store_true")
    export_status.add_argument("--handoff-prepared", action="store_true")
    export_status.add_argument("--observed", action="store_true")
    export_status.add_argument("--blocked", action="store_true")
    plan.set_defaults(func=cmd_materials_plan)

    list_cmd = materials_sub.add_parser("list", help="List local material artifacts.")
    list_cmd.add_argument("--kind", choices=MATERIAL_KINDS, default="")
    list_cmd.add_argument("--limit", type=int, default=None)
    list_cmd.add_argument("--all", action="store_true", help="Return all artifact summaries.")
    list_cmd.set_defaults(func=cmd_materials_list)

    show = materials_sub.add_parser("show", help="Show one material artifact by id.")
    show.add_argument("material_id")
    show.set_defaults(func=cmd_materials_show)

    validate = materials_sub.add_parser("validate", help="Validate material artifacts and cache metadata.")
    validate.set_defaults(func=cmd_materials_validate)

    export = materials_sub.add_parser("export", help="Export material artifacts as JSON or Markdown content.")
    export.add_argument("--kind", choices=MATERIAL_KINDS, default="")
    export.add_argument("--format", choices=("json", "markdown"), default="json")
    export.add_argument("--limit", type=int, default=None)
    export.add_argument("--all", action="store_true", help="Export all matching artifacts.")
    export.set_defaults(func=cmd_materials_export)

    qa = materials_sub.add_parser("qa-ladder", help="Show planned QA checks by target format.")
    qa.add_argument("--format", action="append", choices=MATERIAL_FORMATS)
    qa.set_defaults(func=cmd_materials_qa_ladder)


def _qa_checks_from_args(args: argparse.Namespace) -> list[dict[str, str]] | None:
    if not args.qa_observed:
        return None
    checks: list[dict[str, str]] = []
    for value in args.qa_observed:
        parts = str(value).split(":", 2)
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError("--qa-observed must use FORMAT:CHECK:EVIDENCE")
        material_format, check, evidence = (part.strip() for part in parts)
        checks.append({"format": material_format, "check": check, "status": "observed", "evidence": evidence})
    return checks
