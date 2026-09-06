from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..plugin_bundle.omh.memory_governance import contains_credential_like_material

MEMORY_OPERATION_SCHEMA_VERSION = "memory_operation/v1"
MEMORY_TOMBSTONE_SCHEMA_VERSION = "memory_tombstone/v1"
MEMORY_OPERATION_STATES = frozenset({"prepared", "applying", "interrupted", "completed", "failed", "corrupt"})
MEMORY_RECEIPT_FIELDS = frozenset({"schema_version", "operation_id", "operation_type", "state", "created_at", "completed_at", "step_count", "recovery_count", "outcome"})
_STEP_FIELDS = frozenset({"name", "action", "source", "target", "scope", "key", "revision", "failure_state", "payload"})
_STORED_STEP_FIELDS = _STEP_FIELDS | {"state", "outcome"}
_STEP_OUTCOMES = frozenset({"applied", "already_present", "copied", "moved", "written", "removed", "already_absent", "rewritten"})
_TOMBSTONE_FIELDS = frozenset({"schema_version", "tombstone_id", "record_id", "revision", "scope", "operation_id", "reason_code", "actor_class", "tombstoned_at", "expires_at"})
_OPERATION_FIELDS = frozenset({"schema_version", "operation_id", "operation_type", "state", "created_at", "updated_at", "recovery_count", "steps", "receipt"})
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


def build_memory_operation(operation_id: str, operation_type: str, steps: Sequence[Mapping[str, object]], timestamp: str) -> dict[str, Any]:
    if not _safe_token(operation_id) or not _safe_token(operation_type):
        raise ValueError("operation identifiers must be safe tokens")
    names: set[str] = set()
    prepared = [_step(value, names) for value in steps]
    if not prepared:
        raise ValueError("operation requires at least one step")
    return {"schema_version": MEMORY_OPERATION_SCHEMA_VERSION, "operation_id": operation_id, "operation_type": operation_type, "state": "prepared", "created_at": timestamp, "updated_at": timestamp, "recovery_count": 0, "steps": prepared}


def validate_memory_receipt(receipt: Mapping[str, object]) -> list[str]:
    errors = _metadata_errors(receipt, MEMORY_RECEIPT_FIELDS)
    for key in ("operation_id", "operation_type", "outcome"):
        if key in receipt and (not isinstance(receipt[key], str) or not _safe_token(receipt[key])):
            errors.append(f"receipt has invalid {key}")
    if "state" in receipt and receipt["state"] not in MEMORY_OPERATION_STATES:
        errors.append("receipt has invalid state")
    for key in ("created_at", "completed_at"):
        if key in receipt and (not isinstance(receipt[key], str) or parse_time(receipt[key]) is None):
            errors.append(f"receipt has invalid {key}")
    for key in ("step_count", "recovery_count"):
        if key in receipt and (isinstance(receipt[key], bool) or not isinstance(receipt[key], int) or receipt[key] < 0):
            errors.append(f"receipt has invalid {key}")
    return sorted(errors)


def validate_memory_tombstone(tombstone: Mapping[str, object]) -> list[str]:
    errors = _metadata_errors(tombstone, _TOMBSTONE_FIELDS)
    if tombstone.get("schema_version") != MEMORY_TOMBSTONE_SCHEMA_VERSION:
        errors.append("unsupported tombstone schema")
    for key in ("tombstone_id", "record_id", "operation_id", "reason_code", "actor_class"):
        if key in tombstone and (not isinstance(tombstone[key], str) or not _safe_token(tombstone[key])):
            errors.append(f"invalid {key}")
    for key in ("tombstone_id", "record_id", "revision", "tombstoned_at"):
        if key not in tombstone:
            errors.append(f"missing {key}")
    revision = tombstone.get("revision")
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision < 1):
        errors.append("invalid revision")
    for key in ("tombstoned_at", "expires_at"):
        if key in tombstone and (not isinstance(tombstone[key], str) or parse_time(tombstone[key]) is None):
            errors.append(f"invalid {key}")
    scope = tombstone.get("scope")
    if scope is not None and (not isinstance(scope, dict) or set(scope) != {"kind", "ref"} or not all(isinstance(scope[key], str) and _safe_token(scope[key]) for key in scope)):
        errors.append("invalid scope")
    return sorted(errors)


def valid_memory_operation(record: Mapping[str, object]) -> bool:
    steps = record.get("steps")
    if set(record) - _OPERATION_FIELDS or record.get("schema_version") != MEMORY_OPERATION_SCHEMA_VERSION:
        return False
    if not all(isinstance(record.get(key), str) and _safe_token(record[key]) for key in ("operation_id", "operation_type")):
        return False
    if record.get("state") not in MEMORY_OPERATION_STATES or not isinstance(steps, list) or not steps:
        return False
    if isinstance(record.get("recovery_count"), bool) or not isinstance(record.get("recovery_count"), int) or record["recovery_count"] < 0:
        return False
    if any(not isinstance(record.get(key), str) or parse_time(record[key]) is None for key in ("created_at", "updated_at")):
        return False
    receipt = record.get("receipt")
    if record["state"] == "completed":
        if not isinstance(receipt, dict) or set(receipt) != MEMORY_RECEIPT_FIELDS or validate_memory_receipt(receipt):
            return False
        if receipt.get("operation_id") != record["operation_id"] or receipt.get("operation_type") != record["operation_type"]:
            return False
    elif receipt is not None:
        return False
    names: set[str] = set()
    return all(_valid_step(step, names) for step in steps)


def safe_token(value: str) -> bool:
    return _safe_token(value)


def safe_json_value(value: object) -> bool:
    return _json_value(value)


def relative_memory_json_path(value: str) -> bool:
    return _relative_memory_path(value, ".json")


def relative_memory_jsonl_path(value: str) -> bool:
    return _relative_memory_path(value, ".jsonl")


def _relative_memory_path(value: str, suffix: str) -> bool:
    if not isinstance(value, str):
        return False
    path = Path(value)
    parts = tuple(part.removesuffix(suffix) if index == len(path.parts) - 1 else part for index, part in enumerate(path.parts))
    return bool(value) and not path.is_absolute() and ".." not in path.parts and path.suffix == suffix and all(_safe_token(part) for part in parts)


def parse_time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _step(value: Mapping[str, object], names: set[str]) -> dict[str, Any]:
    if not all(isinstance(key, str) for key in value):
        raise ValueError("memory operation metadata keys must be strings")
    step = dict(value)
    unknown = set(step) - _STEP_FIELDS
    name, action, target = step.get("name", ""), step.get("action", ""), step.get("target", "")
    valid_target = relative_memory_jsonl_path(target) if action == "rewrite_jsonl" else relative_memory_json_path(target)
    if unknown or not isinstance(name, str) or not isinstance(action, str) or not _safe_token(name) or name in names or not _safe_token(action) or not valid_target:
        raise ValueError("invalid memory operation step")
    if action in {"copy", "move"} and not relative_memory_json_path(step.get("source", "")):
        raise ValueError("copy and move steps require a relative source")
    if "source" in step and not isinstance(step["source"], str):
        raise ValueError("invalid memory operation metadata")
    if any(not isinstance(step[key], str) or not _safe_token(step[key]) for key in ("scope", "key", "revision") if key in step):
        raise ValueError("invalid memory operation metadata")
    if "failure_state" in step and step["failure_state"] not in {"interrupted", "failed"}:
        raise ValueError("invalid step failure_state")
    payload = step.get("payload")
    if action == "write_json":
        if not isinstance(payload, Mapping) or not _json_value(payload):
            raise ValueError("write_json requires an object payload")
        step["payload"] = _json_copy(payload)
    elif action == "rewrite_jsonl":
        if not isinstance(payload, list) or not all(isinstance(item, Mapping) and _json_value(item) for item in payload):
            raise ValueError("rewrite_jsonl requires object payload rows")
        step["payload"] = [_json_copy(item) for item in payload]
    elif "payload" in step:
        raise ValueError("operation action does not accept a payload")
    names.add(name)
    return {**step, "state": "prepared"}


def _valid_step(step: object, names: set[str]) -> bool:
    if not isinstance(step, dict) or set(step) - _STORED_STEP_FIELDS or step.get("state") not in MEMORY_OPERATION_STATES:
        return False
    if "outcome" in step and step["outcome"] not in _STEP_OUTCOMES:
        return False
    try:
        _step({key: value for key, value in step.items() if key not in {"state", "outcome"}}, names)
    except ValueError:
        return False
    return True


def _json_value(value: object) -> bool:
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, str):
        return not contains_credential_like_material(value)
    if isinstance(value, float):
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str)
            and not contains_credential_like_material(key)
            and _json_value(item)
            for key, item in value.items()
        )
    return isinstance(value, list) and all(_json_value(item) for item in value)


def _json_copy(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_copy(item) for item in value]
    return value


def _metadata_errors(value: Mapping[str, object], allowed: frozenset[str]) -> list[str]:
    unknown = sorted(str(key) for key in value if str(key) not in allowed)
    return [f"receipt has unsupported fields: {', '.join(unknown)}"] if unknown else []


def _safe_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(_SAFE_TOKEN.fullmatch(value))
        and not contains_credential_like_material(value)
    )
