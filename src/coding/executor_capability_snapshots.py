from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import re
from typing import Final, TypeAlias

from ..local_store import atomic_write_json, read_json_object, utc_now


EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION: Final = "executor_capability_snapshot/v1"
CAPABILITY_STATUSES: Final = frozenset({"prepared", "host_observed", "unavailable", "unknown"})
KNOWN_CAPABILITY_NAMES: Final = frozenset(
    {
        "parallel_agents",
        "background_work",
        "worktree_isolation",
        "visual_qa",
        "browser_or_computer_use",
        "long_running_continuation",
        "scheduled_or_recurring_work",
    }
)
_ROOT_FIELDS: Final = frozenset({"schema_version", "executor", "recorded_at", "capabilities"})
_OBSERVED_CAPABILITY_FIELDS: Final = frozenset({"status", "scope", "evidence_ref", "observed_at"})
_STATUS_ONLY_CAPABILITY_FIELDS: Final = frozenset({"status"})
_FORBIDDEN_KEYS: Final = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "ci",
        "execution",
        "implementation",
        "log",
        "logs",
        "merge",
        "prompt",
        "raw",
        "raw_log",
        "raw_logs",
        "raw_output",
        "raw_prompt",
        "reasoning",
        "result",
        "review",
        "transcript",
        "verification",
    }
)
_MAX_EXECUTOR_LENGTH: Final = 80
_MAX_EVIDENCE_REF_LENGTH: Final = 240
_MAX_SCOPE_ITEMS: Final = 12
_MAX_SCOPE_TEXT_LENGTH: Final = 160
_FORBIDDEN_SCOPE_KEY_TERMS: Final = ("raw", "prompt", "log", "transcript", "reasoning")
_SENSITIVE_METADATA_PATTERNS: Final = ("api_key", "apikey", "authorization:", "bearer ", "ghp_", "github_pat_", "password", "private-token", "secret", "token", "xoxb-", "xoxp-")
_SENSITIVE_METADATA_TOKEN_RE: Final = re.compile(r"(?:^|[\s=:,])(sk-|gh[opsu]_)", re.IGNORECASE)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
CapabilityInput: TypeAlias = Mapping[str, JsonValue]
SnapshotRecord: TypeAlias = dict[str, JsonValue]


class ExecutorCapabilitySnapshotError(ValueError):
    pass


def build_executor_capability_snapshot(
    *,
    executor: str,
    capabilities: Mapping[str, CapabilityInput],
    recorded_at: str | None = None,
) -> SnapshotRecord:
    snapshot: SnapshotRecord = {
        "schema_version": EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
        "executor": executor.strip(),
        "recorded_at": recorded_at or utc_now(),
        "capabilities": {name: _copy_capability(capability) for name, capability in capabilities.items()},
    }
    _raise_if_invalid(snapshot)
    return snapshot


def validate_executor_capability_snapshot(snapshot: Mapping[str, JsonValue]) -> list[str]:
    errors = _forbidden_key_errors(snapshot)
    errors.extend(_root_errors(snapshot))
    capabilities = snapshot.get("capabilities")
    if isinstance(capabilities, Mapping):
        errors.extend(_capability_errors(capabilities))
    return errors


def write_executor_capability_snapshot(path: Path, snapshot: Mapping[str, JsonValue]) -> SnapshotRecord:
    _raise_if_invalid(snapshot)
    persisted = _copy_snapshot(snapshot)
    atomic_write_json(path, persisted, private=True)
    return persisted


def read_executor_capability_snapshot(path: Path) -> SnapshotRecord | None:
    raw = read_json_object(path)
    if raw is None:
        return None
    snapshot = _copy_snapshot(raw)
    _raise_if_invalid(snapshot)
    return snapshot


def executor_capability_snapshot_path(directory: Path, executor: str) -> Path:
    normalized = executor.strip()
    if not normalized or normalized in {".", ".."} or Path(normalized).name != normalized:
        raise ExecutorCapabilitySnapshotError("executor must be a safe snapshot filename")
    return directory / f"{normalized}.json"


def read_matching_executor_capability_snapshot(path: Path, *, expected_executor: str) -> SnapshotRecord | None:
    try:
        snapshot = read_executor_capability_snapshot(path)
    except (ExecutorCapabilitySnapshotError, OSError, ValueError):
        return None
    if snapshot is None or snapshot.get("executor") != expected_executor:
        return None
    return snapshot


def _copy_snapshot(snapshot: Mapping[str, JsonValue]) -> SnapshotRecord:
    return {str(key): _copy_json_value(value) for key, value in snapshot.items()}


def _copy_capability(capability: CapabilityInput) -> dict[str, JsonValue]:
    return {str(key): _copy_json_value(value) for key, value in capability.items()}


def _copy_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {str(key): _copy_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    return value


def _raise_if_invalid(snapshot: Mapping[str, JsonValue]) -> None:
    errors = validate_executor_capability_snapshot(snapshot)
    if errors:
        raise ExecutorCapabilitySnapshotError("; ".join(errors))


def _root_errors(snapshot: Mapping[str, JsonValue]) -> list[str]:
    errors: list[str] = []
    unexpected = set(snapshot) - _ROOT_FIELDS
    if unexpected:
        errors.append(f"snapshot contains unsupported fields: {', '.join(sorted(str(key) for key in unexpected))}")
    if snapshot.get("schema_version") != EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION}")
    executor = snapshot.get("executor")
    if not isinstance(executor, str) or not executor.strip() or len(executor.strip()) > _MAX_EXECUTOR_LENGTH:
        errors.append("executor must be a nonempty bounded string")
    recorded_at = snapshot.get("recorded_at")
    if not _is_timestamp(recorded_at):
        errors.append("recorded_at must be an ISO-8601 timestamp with timezone")
    capabilities = snapshot.get("capabilities")
    if not isinstance(capabilities, Mapping) or not capabilities:
        errors.append("capabilities must be a nonempty mapping")
    return errors


def _capability_errors(capabilities: Mapping[str, JsonValue]) -> list[str]:
    errors: list[str] = []
    for name, value in capabilities.items():
        if name not in KNOWN_CAPABILITY_NAMES:
            errors.append(f"unsupported capability name: {name}")
            continue
        if not isinstance(value, Mapping):
            errors.append(f"{name} capability must be a mapping")
            continue
        status = value.get("status")
        match status:
            case "host_observed":
                errors.extend(_host_observed_errors(name, value))
            case "prepared" | "unavailable" | "unknown":
                errors.extend(_status_only_errors(name, value))
            case _:
                errors.append(f"{name} capability status must be one of {', '.join(sorted(CAPABILITY_STATUSES))}")
    return errors


def _host_observed_errors(name: str, capability: Mapping[str, JsonValue]) -> list[str]:
    errors = _unexpected_capability_field_errors(name, capability, _OBSERVED_CAPABILITY_FIELDS)
    scope = capability.get("scope")
    if not isinstance(scope, Mapping) or not scope:
        errors.append(f"{name} host_observed capability requires a nonempty bounded scope mapping")
    else:
        errors.extend(_scope_errors(name, scope))
    evidence_ref = capability.get("evidence_ref")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip() or len(evidence_ref.strip()) > _MAX_EVIDENCE_REF_LENGTH:
        errors.append(f"{name} host_observed capability requires a nonempty evidence_ref")
    elif _looks_sensitive_metadata(evidence_ref):
        errors.append(f"{name} host_observed capability evidence_ref must not contain sensitive metadata")
    if not _is_timestamp(capability.get("observed_at")):
        errors.append(f"{name} host_observed capability requires an observed_at timestamp")
    return errors


def _status_only_errors(name: str, capability: Mapping[str, JsonValue]) -> list[str]:
    return _unexpected_capability_field_errors(name, capability, _STATUS_ONLY_CAPABILITY_FIELDS)


def _unexpected_capability_field_errors(
    name: str,
    capability: Mapping[str, JsonValue],
    allowed: frozenset[str],
) -> list[str]:
    unexpected = set(capability) - allowed
    if not unexpected:
        return []
    return [f"{name} capability contains unsupported fields: {', '.join(sorted(str(key) for key in unexpected))}"]


def _scope_errors(name: str, scope: Mapping[str, JsonValue]) -> list[str]:
    errors: list[str] = []
    if len(scope) > _MAX_SCOPE_ITEMS:
        errors.append(f"{name} scope must contain at most {_MAX_SCOPE_ITEMS} items")
    for key, value in scope.items():
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > _MAX_SCOPE_TEXT_LENGTH:
            errors.append(f"{name} scope keys must be nonempty bounded strings")
        elif any(term in key.casefold() for term in _FORBIDDEN_SCOPE_KEY_TERMS):
            errors.append(f"{name} scope keys must not contain raw or lifecycle material")
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > _MAX_SCOPE_TEXT_LENGTH:
            errors.append(f"{name} scope values must be nonempty bounded strings")
        elif _looks_sensitive_metadata(key) or _looks_sensitive_metadata(value):
            errors.append(f"{name} scope must not contain sensitive metadata")
    return errors


def _forbidden_key_errors(value: JsonValue | Mapping[str, JsonValue], path: str = "snapshot") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in _FORBIDDEN_KEYS:
                errors.append(f"{path}.{key_text} is forbidden metadata")
            errors.extend(_forbidden_key_errors(item, f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_forbidden_key_errors(item, f"{path}[{index}]"))
    return errors


def _is_timestamp(value: JsonValue | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _looks_sensitive_metadata(value: str) -> bool:
    return any(pattern in value.casefold() for pattern in _SENSITIVE_METADATA_PATTERNS) or bool(_SENSITIVE_METADATA_TOKEN_RE.search(value))
