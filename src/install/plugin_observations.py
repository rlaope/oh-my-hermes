from __future__ import annotations

import json
from typing import Any

from ..local_store import ensure_dir, ensure_file, read_jsonl_objects, utc_now
from ..paths import OmhPaths
from ..runtime.artifacts import update_state

PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION = "omh_plugin_host_observation/v1"
PLUGIN_HOST_OBSERVATION_EVENTS = (
    "plugin_load",
    "tool_call",
    "hook_call",
    "status_query",
    "session_end",
    "plugin_unload",
)
PLUGIN_HOST_OBSERVATION_STATUSES = ("observed", "not_observed", "blocked")
PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS = ("plugin_load", "tool_call", "hook_call", "status_query")
PLUGIN_HOST_HISTORICAL_OBSERVATION_EVENTS = ("session_end", "plugin_unload")
PLUGIN_HOST_TEXT_LIMITS = {
    "host": 96,
    "session": 160,
    "source": 64,
    "tool": 96,
    "hook": 96,
    "evidence_ref": 180,
    "message": 280,
}
PLUGIN_HOST_SENSITIVE_PATTERNS = (
    "api_key",
    "apikey",
    "authorization:",
    "bearer ",
    "ghp_",
    "password",
    "private-token",
    "raw prompt",
    "secret",
    "token",
    "xoxb-",
    "xoxp-",
)

PLUGIN_HOST_OBSERVATION_CLAIM_BOUNDARY = (
    "An OMH plugin host observation is metadata supplied by a Hermes host or wrapper "
    "that observed plugin load or use. It proves only that host plugin event, not coding "
    "dispatch, implementation, verification, review, CI, merge, or unrecorded tool/hook calls."
)


def record_plugin_host_observation(
    paths: OmhPaths,
    *,
    host: str,
    session_id: str,
    event: str,
    status: str,
    evidence_refs: list[str] | None = None,
    message: str = "",
    source: str = "wrapper",
    tool: str = "",
    hook: str = "",
) -> dict[str, Any]:
    host = _bounded_metadata_text(host, field="host")
    session_id = _bounded_metadata_text(session_id, field="session")
    event = event.strip()
    status = status.strip()
    source = _bounded_metadata_text(source, field="source") or "wrapper"
    tool = _bounded_metadata_text(tool, field="tool")
    hook = _bounded_metadata_text(hook, field="hook")
    message = _bounded_metadata_text(message, field="message")
    evidence_refs = [
        _bounded_metadata_text(item, field="evidence_ref") for item in (evidence_refs or []) if item and item.strip()
    ]

    if not host:
        raise ValueError("plugin host observation requires --host")
    if not session_id:
        raise ValueError("plugin host observation requires --session")
    if event not in PLUGIN_HOST_OBSERVATION_EVENTS:
        raise ValueError(f"plugin host observation event must be one of: {', '.join(PLUGIN_HOST_OBSERVATION_EVENTS)}")
    if status not in PLUGIN_HOST_OBSERVATION_STATUSES:
        raise ValueError(
            f"plugin host observation status must be one of: {', '.join(PLUGIN_HOST_OBSERVATION_STATUSES)}"
        )
    if status == "observed" and not evidence_refs:
        raise ValueError("observed plugin host events require at least one --evidence-ref")
    if event == "tool_call" and not tool:
        raise ValueError("plugin host tool_call observation requires --tool")
    if event == "hook_call" and not hook:
        raise ValueError("plugin host hook_call observation requires --hook")

    recorded_at = utc_now()
    runtime_readiness = plugin_host_runtime_readiness(event=event, status=status)
    record: dict[str, Any] = {
        "schema_version": PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION,
        "host": host,
        "session_id": session_id,
        "event": event,
        "status": status,
        "observed": status == "observed",
        "runtime_readiness": runtime_readiness,
        "native_integration_active": runtime_readiness == "active_runtime_observed",
        "source": source,
        "tool": tool,
        "hook": hook,
        "evidence_refs": evidence_refs,
        "message": message,
        "redaction_policy": "metadata_only_bounded",
        "recorded_at": recorded_at,
        "claim_boundary": PLUGIN_HOST_OBSERVATION_CLAIM_BOUNDARY,
    }
    if status == "observed":
        record["observed_at"] = recorded_at
    _append_plugin_host_observation(paths, record)
    patch: dict[str, Any] = {"last_plugin_host_observation": record}
    patch["last_plugin_runtime_observed"] = record if record["native_integration_active"] else None
    patch["last_plugin_runtime_readiness"] = runtime_readiness
    update_state(paths, patch)
    return record


def read_plugin_host_observations(paths: OmhPaths, *, limit: int | None = 20) -> tuple[list[dict[str, Any]], list[str]]:
    records, errors = read_jsonl_objects(paths.runtime_plugin_host_observations_path)
    records = list(reversed(records))
    if limit is not None:
        records = records[:limit]
    return records, errors


def latest_plugin_host_observation(paths: OmhPaths) -> tuple[dict[str, Any] | None, list[str]]:
    records, errors = read_jsonl_objects(paths.runtime_plugin_host_observations_path)
    for record in reversed(records):
        if record.get("schema_version") == PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION:
            return record, errors
    return None, errors


def plugin_host_runtime_readiness(*, event: str, status: str) -> str:
    if status == "blocked":
        return "blocked"
    if status != "observed":
        return "not_observed"
    if event in PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS:
        return "active_runtime_observed"
    if event in PLUGIN_HOST_HISTORICAL_OBSERVATION_EVENTS:
        return "historical_runtime_observed"
    return "observed_unknown_event"


def _append_plugin_host_observation(paths: OmhPaths, record: dict[str, Any]) -> None:
    ensure_dir(paths.runtime_dir, private=True)
    ensure_file(paths.runtime_plugin_host_observations_path, private=True)
    with paths.runtime_plugin_host_observations_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _bounded_metadata_text(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    limit = PLUGIN_HOST_TEXT_LIMITS[field]
    if len(text) > limit:
        raise ValueError(f"plugin host observation --{field.replace('_', '-')} must be {limit} characters or fewer")
    if _looks_sensitive_metadata(text):
        raise ValueError(
            f"plugin host observation --{field.replace('_', '-')} must be metadata-only and must not include secrets, tokens, passwords, or raw prompts"
        )
    return text


def _looks_sensitive_metadata(text: str) -> bool:
    lowered = text.lower()
    if any(pattern in lowered for pattern in PLUGIN_HOST_SENSITIVE_PATTERNS):
        return True
    words = lowered.replace("=", " ").replace(":", " ").replace(",", " ").split()
    return any(word.startswith("sk-") for word in words)
