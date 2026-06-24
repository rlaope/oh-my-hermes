from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..installer import OmhError
from ..memory import (
    apply_memory_update_batch,
    build_handoff_context_pack,
    build_memory_inspection,
    read_memory_snapshot_file,
)
from .common import _paths, _print_json


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
    memory = sub.add_parser("memory", help="Inspect, pack, or apply OMH memory/context review artifacts.")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)

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
