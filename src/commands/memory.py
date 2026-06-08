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
        inspection = build_memory_inspection(_paths(args), wrapper_snapshot=_read_optional_json(args.fixture))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(inspection)
    return 0


def cmd_memory_pack(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        inspection = build_memory_inspection(paths, wrapper_snapshot=_read_optional_json(args.fixture))
        pack = build_handoff_context_pack(
            paths,
            inspection=inspection,
            executor_target=args.executor,
            session_id=args.session_id,
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


def _add_memory_commands(sub) -> None:
    memory = sub.add_parser("memory")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)

    inspect = memory_sub.add_parser("inspect")
    inspect.add_argument(
        "--fixture",
        default=None,
        help="Optional memory_snapshot/v1 JSON fixture supplied by a wrapper for deterministic inspection.",
    )
    inspect.set_defaults(func=cmd_memory_inspect)

    pack = memory_sub.add_parser("pack")
    pack.add_argument(
        "--fixture",
        default=None,
        help="Optional memory_snapshot/v1 JSON fixture supplied by a wrapper before packing handoff context.",
    )
    pack.add_argument("--executor", default="generic", help="Executor target label to record in the context pack.")
    pack.add_argument("--session-id", default="", help="Optional wrapper session id to bind to the context pack.")
    pack.set_defaults(func=cmd_memory_pack)

    apply = memory_sub.add_parser("apply")
    apply.add_argument(
        "--batch",
        required=True,
        help="Path to memory_update_batch/v1 JSON, or '-' to read from stdin.",
    )
    apply.add_argument("--dry-run", action="store_true", help="Validate and preview the batch without writing .omh/memory.")
    apply.set_defaults(func=cmd_memory_apply)
