from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..installer import OmhError
from ..memory import (
    apply_memory_update_batch,
    approve_project_memory_candidate,
    build_handoff_context_pack,
    build_memory_inspection,
    build_project_memory_recall_pack,
    build_project_memory_review,
    build_project_memory_status,
    capture_project_memory_candidate,
    read_memory_snapshot_file,
    reject_project_memory_candidate,
)
from .common import _paths, _print_json


def cmd_memory_status(args: argparse.Namespace) -> int:
    try:
        payload = build_project_memory_status(_paths(args))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_capture(args: argparse.Namespace) -> int:
    try:
        summary = " ".join(args.summary).strip()
        content = sys.stdin.read() if args.stdin else str(args.content or "")
        if not summary:
            raise ValueError("memory capture requires a summary")
        payload = capture_project_memory_candidate(
            _paths(args),
            summary,
            content=content,
            record_type=args.type,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            source=args.source,
            source_ref=args.source_ref,
            tags=args.tag or [],
            ttl_days=args.ttl_days,
            stale_after_days=args.stale_after_days,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_review(args: argparse.Namespace) -> int:
    try:
        payload = build_project_memory_review(
            _paths(args),
            candidate_id=args.candidate,
            limit=_optional_positive_int(args.limit, "--limit") or 20,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_approve(args: argparse.Namespace) -> int:
    try:
        payload = approve_project_memory_candidate(_paths(args), args.candidate_id, approved_by=args.approved_by)
    except FileNotFoundError as exc:
        raise OmhError(f"memory candidate not found: {args.candidate_id}") from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_reject(args: argparse.Namespace) -> int:
    try:
        payload = reject_project_memory_candidate(
            _paths(args),
            args.candidate_id,
            rejected_by=args.rejected_by,
            reason=args.reason,
        )
    except FileNotFoundError as exc:
        raise OmhError(f"memory candidate not found: {args.candidate_id}") from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_recall(args: argparse.Namespace) -> int:
    try:
        query = " ".join(args.query).strip()
        payload = build_project_memory_recall_pack(
            _paths(args),
            query,
            executor_target=args.executor,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            limit=_optional_positive_int(args.limit, "--limit") or 6,
            include_stale=args.include_stale,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_inspect(args: argparse.Namespace) -> int:
    try:
        inspection = build_memory_inspection(
            _paths(args),
            wrapper_snapshot=_read_optional_json(args.fixture),
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
            summary=args.summary,
            review_item_limit=_optional_positive_int(args.review_item_limit, "--review-item-limit"),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(inspection)
    return 0


def cmd_memory_pack(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        inspection = None
        wrapper_snapshot = _read_optional_json(args.fixture)
        if wrapper_snapshot is not None:
            inspection = build_memory_inspection(
                paths,
                wrapper_snapshot=wrapper_snapshot,
                scope_kind=args.scope_kind,
                scope_ref=args.scope_ref,
                session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
                review_item_limit=_optional_positive_int(args.review_item_limit, "--review-item-limit"),
            )
        pack = build_handoff_context_pack(
            paths,
            inspection=inspection,
            executor_target=args.executor,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
            context_limit=_optional_positive_int(args.context_limit, "--context-limit") or 12,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(pack)
    return 0


def cmd_memory_apply(args: argparse.Namespace) -> int:
    try:
        batch = _read_required_json(args.batch)
        result = apply_memory_update_batch(_paths(args), batch, dry_run=args.dry_run)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(result)
    return 0


def _read_optional_json(path: str | None) -> dict[str, object] | None:
    if not path:
        return None
    return read_memory_snapshot_file(path)


def _read_required_json(path: str) -> dict[str, object]:
    raw = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("memory JSON input must be an object")
    return data


def _optional_positive_int(value: int | None, flag: str) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ValueError(f"{flag} must be at least 1")
    return value


def _add_memory_commands(sub) -> None:
    memory = sub.add_parser("memory", help="Capture, review, recall, inspect, or pack OMH project memory/context artifacts.")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)

    status = memory_sub.add_parser("status", help="Show OMH project-memory policy, store paths, and review counts.")
    status.set_defaults(func=cmd_memory_status)

    capture = memory_sub.add_parser("capture", help="Capture an OMH project-memory candidate for review.")
    capture.add_argument("summary", nargs="*", help="Short reviewed-memory summary to capture.")
    capture.add_argument("--type", choices=("fact", "decision", "lesson", "procedure", "episode"), default="fact", help="Typed memory record category.")
    capture.add_argument("--content", default="", help="Optional raw source text. It is hashed/length-counted, not persisted raw.")
    capture.add_argument("--stdin", action="store_true", help="Read optional raw source text from stdin without persisting it raw.")
    capture.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default="project")
    capture.add_argument("--scope-ref", default="default")
    capture.add_argument("--source", default="cli")
    capture.add_argument("--source-ref", default="")
    capture.add_argument("--tag", action="append", default=[])
    capture.add_argument("--ttl-days", type=int, default=None)
    capture.add_argument("--stale-after-days", type=int, default=None)
    capture.set_defaults(func=cmd_memory_capture)

    review = memory_sub.add_parser("review", help="Return review cards for pending OMH project-memory candidates.")
    review.add_argument("--candidate", default=None, help="Limit review output to one candidate id.")
    review.add_argument("--limit", type=int, default=20)
    review.set_defaults(func=cmd_memory_review)

    approve = memory_sub.add_parser("approve", help="Approve a reviewed project-memory candidate.")
    approve.add_argument("candidate_id")
    approve.add_argument("--approved-by", default="operator")
    approve.set_defaults(func=cmd_memory_approve)

    reject = memory_sub.add_parser("reject", help="Reject a project-memory candidate.")
    reject.add_argument("candidate_id")
    reject.add_argument("--rejected-by", default="operator")
    reject.add_argument("--reason", default="")
    reject.set_defaults(func=cmd_memory_reject)

    recall = memory_sub.add_parser("recall", help="Recall reviewed OMH project memory for a task as prepared context.")
    recall.add_argument("query", nargs="*", help="Task/query text used for deterministic keyword recall.")
    recall.add_argument("--executor", default="generic", help="Executor target label to record in the recall pack.")
    recall.add_argument("--session-id", default="", help="Optional wrapper session id to bind to the recall pack.")
    recall.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default=None)
    recall.add_argument("--scope-ref", default=None)
    recall.add_argument("--limit", type=int, default=6)
    recall.add_argument("--include-stale", action="store_true")
    recall.set_defaults(func=cmd_memory_recall)

    inspect = memory_sub.add_parser("inspect")
    inspect.add_argument(
        "--fixture",
        default=None,
        help="Optional memory_snapshot/v1 JSON fixture supplied by a wrapper for deterministic inspection.",
    )
    inspect.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default=None, help="Only inspect snapshots from this scope kind.")
    inspect.add_argument("--scope-ref", default=None, help="Only inspect snapshots with this scope reference.")
    inspect.add_argument("--session-limit", type=int, default=None, help="Maximum recent wrapper session snapshots to inspect.")
    inspect.add_argument("--review-item-limit", type=int, default=None, help="Maximum review items to return.")
    inspect.add_argument("--summary", action="store_true", help="Return snapshot summaries instead of full snapshot items.")
    inspect.set_defaults(func=cmd_memory_inspect)

    pack = memory_sub.add_parser("pack")
    pack.add_argument(
        "--fixture",
        default=None,
        help="Optional memory_snapshot/v1 JSON fixture supplied by a wrapper before packing handoff context.",
    )
    pack.add_argument("--executor", default="generic", help="Executor target label to record in the context pack.")
    pack.add_argument("--session-id", default="", help="Optional wrapper session id to bind to the context pack.")
    pack.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default=None, help="Only pack context from this scope kind.")
    pack.add_argument("--scope-ref", default=None, help="Only pack context with this scope reference.")
    pack.add_argument("--session-limit", type=int, default=None, help="Maximum recent wrapper session snapshots to inspect.")
    pack.add_argument("--review-item-limit", type=int, default=None, help="Maximum review items to build when a fixture is supplied.")
    pack.add_argument("--context-limit", type=int, default=12, help="Maximum context items to include in the handoff pack.")
    pack.set_defaults(func=cmd_memory_pack)

    apply = memory_sub.add_parser("apply")
    apply.add_argument(
        "--batch",
        required=True,
        help="Path to memory_update_batch/v1 JSON, or '-' to read from stdin.",
    )
    apply.add_argument("--dry-run", action="store_true", help="Validate and preview the batch without writing .omh/memory.")
    apply.set_defaults(func=cmd_memory_apply)
