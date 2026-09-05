from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..system.local_store import atomic_write_json, atomic_write_text, ensure_dir, file_lock, read_json_object_result, utc_now
from ..system.paths import OmhPaths
from ._memory_store_validation import (
    MEMORY_OPERATION_SCHEMA_VERSION,
    MEMORY_OPERATION_STATES,
    MEMORY_RECEIPT_FIELDS,
    MEMORY_TOMBSTONE_SCHEMA_VERSION,
    build_memory_operation,
    parse_time,
    relative_memory_json_path,
    relative_memory_jsonl_path,
    safe_json_value,
    safe_token,
    valid_memory_operation,
    validate_memory_receipt,
    validate_memory_tombstone,
)

_INDEX_DIRS = (("scope_files", "scopes"), ("candidate_files", "candidates"), ("record_files", "records"), ("review_files", "reviews"))
StepWriter = Callable[[OmhPaths, dict[str, Any]], str | None]
IndexRebuilder = Callable[[OmhPaths], None]
OperationPreflight = Callable[[OmhPaths], None]


class MemoryOperationIdentityError(ValueError):
    pass


__all__ = [
    "MEMORY_OPERATION_SCHEMA_VERSION",
    "MEMORY_OPERATION_STATES",
    "MEMORY_RECEIPT_FIELDS",
    "MEMORY_TOMBSTONE_SCHEMA_VERSION",
    "MemoryOperationIdentityError",
    "apply_memory_operation_step",
    "checked_memory_directory",
    "checked_memory_json_path",
    "ensure_memory_directory",
    "prune_expired_memory_evidence",
    "recover_memory_operations",
    "run_memory_operation",
    "validate_memory_receipt",
    "validate_memory_tombstone",
    "write_memory_tombstone",
]


def run_memory_operation(
    paths: OmhPaths,
    *,
    operation_id: str,
    operation_type: str,
    steps: Sequence[Mapping[str, object]],
    rebuild_index: IndexRebuilder | None = None,
    step_writer: StepWriter | None = None,
    preflight: OperationPreflight | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    normalized = build_memory_operation(operation_id, operation_type, steps, _stamp(now))
    ensure_memory_directory(paths, "operations")
    with file_lock(paths.memory_index_path, private=True):
        # A candidate-bound writer can only interpret its own operation. Passing
        # it to unrelated interrupted records can poison their recovery state.
        if step_writer is None:
            _recover_unlocked(paths, rebuild_index, None, now, skip=operation_id)
        path = _operation_path(paths, operation_id)
        if path.is_symlink():
            return {"operation_id": operation_id, "state": "corrupt"}
        existing, error = read_json_object_result(path)
        if error or existing is None or not valid_memory_operation(existing):
            if path.exists():
                return _mark_corrupt_operation(paths, operation_id, now)
            if preflight is not None:
                preflight(paths)
            record = normalized
            atomic_write_json(path, record, private=True)
        else:
            if not _operation_request_matches(existing, normalized):
                raise MemoryOperationIdentityError(
                    "memory operation id is already bound to a different request"
                )
            record = existing
        return _resume_unlocked(paths, record, rebuild_index, step_writer, now)


def recover_memory_operations(
    paths: OmhPaths,
    *,
    rebuild_index: IndexRebuilder | None = None,
    step_writer: StepWriter | None = None,
    now: datetime | str | None = None,
) -> list[dict[str, Any]]:
    ensure_memory_directory(paths, "operations")
    with file_lock(paths.memory_index_path, private=True):
        return _recover_unlocked(paths, rebuild_index, step_writer, now)


def _operation_request_matches(existing: Mapping[str, object], requested: Mapping[str, object]) -> bool:
    def request_steps(value: Mapping[str, object]) -> list[dict[str, object]] | None:
        steps = value.get("steps")
        if not isinstance(steps, list) or not all(isinstance(step, Mapping) for step in steps):
            return None
        return [
            {str(key): item for key, item in step.items() if key not in {"state", "outcome"}}
            for step in steps
        ]

    return (
        existing.get("operation_id") == requested.get("operation_id")
        and existing.get("operation_type") == requested.get("operation_type")
        and request_steps(existing) == request_steps(requested)
    )


def apply_memory_operation_step(paths: OmhPaths, step: dict[str, Any]) -> str:
    action, target = step["action"], _memory_path(paths, str(step["target"]))
    if target.is_symlink():
        raise ValueError("operation target is a symlink")
    if action == "write_json":
        payload = step.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("write_json payload is invalid")
        atomic_write_json(target, payload, private=True)
        return "written"
    if action == "rewrite_jsonl":
        payload = step.get("payload")
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("rewrite_jsonl payload is invalid")
        text = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in payload)
        atomic_write_text(target, text, private=True)
        return "rewritten"
    if action == "delete":
        if not target.exists():
            return "already_absent"
        target.unlink()
        return "removed"
    if target.exists():
        return "already_present"
    source_value = step.get("source", "")
    if not isinstance(source_value, str) or not source_value:
        raise ValueError("operation step has no source")
    raw_source = paths.memory_dir / source_value
    if raw_source.is_symlink():
        raise ValueError("operation source is a symlink")
    source = _memory_path(paths, source_value)
    if source.is_symlink():
        raise ValueError("operation source is a symlink")
    if action == "copy":
        payload, error = read_json_object_result(source)
        if error or payload is None:
            raise ValueError("operation source is not a JSON object")
        if not safe_json_value(payload):
            raise ValueError("operation source contains unsafe content")
        atomic_write_json(target, payload, private=True)
        return "copied"
    if action == "move":
        if not source.exists():
            raise FileNotFoundError("operation source is missing")
        payload, error = read_json_object_result(source)
        if error or payload is None:
            raise ValueError("operation source is not a JSON object")
        if not safe_json_value(payload):
            raise ValueError("operation source contains unsafe content")
        ensure_dir(target.parent, private=True)
        os.replace(source, target)
        target.chmod(0o600)
        return "moved"
    raise ValueError(f"unsupported operation action: {action}")


def write_memory_tombstone(paths: OmhPaths, tombstone: Mapping[str, object]) -> dict[str, Any]:
    value = {str(key): item for key, item in tombstone.items()}
    value.setdefault("schema_version", MEMORY_TOMBSTONE_SCHEMA_VERSION)
    errors = validate_memory_tombstone(value)
    if errors:
        raise ValueError("; ".join(errors))
    ensure_memory_directory(paths, "tombstones")
    with file_lock(paths.memory_index_path, private=True):
        target = checked_memory_json_path(paths, f"tombstones/{value['tombstone_id']}.json")
        atomic_write_json(target, value, private=True)
    return value


def prune_expired_memory_evidence(
    paths: OmhPaths, *, now: datetime | str | None = None, retention_days: int = 30
) -> dict[str, Any]:
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError("retention_days must be positive")
    operations_dir = ensure_memory_directory(paths, "operations")
    tombstones_dir = ensure_memory_directory(paths, "tombstones")
    with file_lock(paths.memory_index_path, private=True):
        current = _as_utc(now)
        operations = _prune_dir(operations_dir, MEMORY_OPERATION_SCHEMA_VERSION, "operation_id", "created_at", current, retention_days)
        tombstones = _prune_dir(tombstones_dir, MEMORY_TOMBSTONE_SCHEMA_VERSION, "tombstone_id", "tombstoned_at", current, retention_days)
    return {"schema_version": "memory_evidence_prune/v1", "removed_operations": operations, "removed_tombstones": tombstones, "retention_days": retention_days}


def _resume_unlocked(paths: OmhPaths, record: dict[str, Any], rebuild: IndexRebuilder | None, writer: StepWriter | None, now: datetime | str | None) -> dict[str, Any]:
    state = record["state"]
    if state in {"completed", "failed", "corrupt"}:
        return record
    if state != "prepared":
        record["recovery_count"] += 1
    for step in record["steps"]:
        if step["state"] in {"completed", "failed"}:
            continue
        step["state"], record["state"], record["updated_at"] = "applying", "applying", _stamp(now)
        _write_operation(paths, record)
        try:
            outcome = (writer or apply_memory_operation_step)(paths, step)
        except ValueError:
            step["state"] = "failed"
            record["state"], record["updated_at"] = "failed", _stamp(now)
            _write_operation(paths, record)
            raise
        except BaseException:
            step["state"] = step.get("failure_state", "interrupted")
            record["state"], record["updated_at"] = step["state"], _stamp(now)
            _write_operation(paths, record)
            raise
        if isinstance(outcome, str):
            step["outcome"] = outcome
        step["state"], record["state"], record["updated_at"] = "completed", "applying", _stamp(now)
        _write_operation(paths, record)
    try:
        (rebuild or _rebuild_index)(paths)
    except Exception:
        record["state"], record["updated_at"] = "failed", _stamp(now)
        _write_operation(paths, record)
        raise
    record["state"], record["updated_at"] = "completed", _stamp(now)
    record["receipt"] = _receipt(record)
    _write_operation(paths, record)
    return record


def _recover_unlocked(paths: OmhPaths, rebuild: IndexRebuilder | None, writer: StepWriter | None, now: datetime | str | None, *, skip: str = "") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(paths.memory_operations_dir.glob("*.json")):
        if path.stem == skip or path.is_symlink() or not path.is_file():
            continue
        record, error = read_json_object_result(path)
        if error or record is None or not valid_memory_operation(record):
            if safe_token(path.stem):
                results.append(_mark_corrupt_operation(paths, path.stem, now))
            else:
                results.append({"operation_id": "", "state": "corrupt"})
        else:
            if writer is None and record.get("state") not in {"completed", "failed", "corrupt"} and any(
                step.get("action") not in {"copy", "delete", "move", "rewrite_jsonl", "write_json"}
                for step in record.get("steps", [])
                if isinstance(step, Mapping)
            ):
                continue
            results.append(_resume_unlocked(paths, record, rebuild, writer, now))
    return results


def _mark_corrupt_operation(paths: OmhPaths, operation_id: str, now: datetime | str | None) -> dict[str, Any]:
    record = build_memory_operation(
        operation_id,
        "memory_recovery",
        [{"name": "mark_corrupt", "action": "corrupt", "target": f"operations/{operation_id}.json"}],
        _stamp(now),
    )
    record["state"] = "corrupt"
    record["steps"][0]["state"] = "failed"
    _write_operation(paths, record)
    return record


def _write_operation(paths: OmhPaths, record: dict[str, Any]) -> None:
    atomic_write_json(_operation_path(paths, record["operation_id"]), record, private=True)


def _operation_path(paths: OmhPaths, operation_id: str) -> Path:
    return checked_memory_json_path(paths, f"operations/{operation_id}.json")


def _rebuild_index(paths: OmhPaths) -> None:
    files = {
        key: [
            path.relative_to(paths.memory_dir).as_posix()
            for path in sorted((paths.memory_dir / directory).rglob("*.json"))
            if _indexable_memory_file(paths, path)
        ]
        for key, directory in _INDEX_DIRS
    }
    atomic_write_json(paths.memory_index_path, {"schema_version": "omh_memory_index/v1", "updated_at": utc_now(), **files, "claim_boundary": "OMH local memory only; this index is not Hermes internal memory."}, private=True)


def _indexable_memory_file(paths: OmhPaths, path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        relative = path.relative_to(paths.memory_dir).as_posix()
    except ValueError:
        return False
    return relative_memory_json_path(relative)


def _receipt(record: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "memory_operation_receipt/v1", "operation_id": record["operation_id"], "operation_type": record["operation_type"], "state": "completed", "created_at": record["created_at"], "completed_at": record["updated_at"], "step_count": len(record["steps"]), "recovery_count": record["recovery_count"], "outcome": "applied"}


def _prune_dir(directory: Path, schema: str, id_key: str, timestamp_key: str, now: datetime, days: int) -> list[str]:
    removed: list[str] = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        value, error = read_json_object_result(path)
        stamp = parse_time(str(value.get(timestamp_key, ""))) if value and not error else None
        identifier = str(value.get(id_key, "")) if value else ""
        if value and value.get("schema_version") == schema and stamp is not None and safe_token(identifier) and now >= stamp + timedelta(days=days):
            path.unlink()
            removed.append(identifier)
    return removed


def _memory_path(paths: OmhPaths, relative: str) -> Path:
    if not (relative_memory_json_path(relative) or relative_memory_jsonl_path(relative)):
        raise ValueError("memory path must be relative and contained")
    return _checked_memory_relative_path(paths, relative)


def checked_memory_json_path(paths: OmhPaths, relative: str) -> Path:
    if not relative_memory_json_path(relative):
        raise ValueError("memory path must be relative and contained")
    return _checked_memory_relative_path(paths, relative)


def ensure_memory_directory(paths: OmhPaths, relative: str) -> Path:
    directory = checked_memory_directory(paths, relative)
    ensure_dir(directory, private=True)
    return directory


def checked_memory_directory(paths: OmhPaths, relative: str) -> Path:
    path = Path(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or not all(safe_token(part) for part in path.parts)
    ):
        raise ValueError("memory directory must be relative and contained")
    return _checked_memory_relative_path(paths, relative)


def _checked_memory_relative_path(paths: OmhPaths, relative: str) -> Path:
    root = paths.memory_dir
    if root.is_symlink():
        raise ValueError("memory path escapes store")
    path = root / relative
    cursor = root
    for part in Path(relative).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("memory path escapes store")
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        raise ValueError("memory path escapes store")
    return path


def _as_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str) and (parsed := parse_time(value)) is not None:
        return parsed
    raise ValueError("now must be an ISO-8601 timestamp or datetime")


def _stamp(value: datetime | str | None) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")
