from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION = "omh_plugin_host_observation/v1"
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

OBSERVATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "description": (
        "Optional host-supplied metadata for recording that Hermes actually invoked this OMH plugin "
        "tool or hook. This records plugin load/use only; it is not workflow execution evidence."
    ),
    "properties": {
        "host": {"type": "string", "description": "Host or wrapper name, such as hermes-agent."},
        "session_id": {"type": "string", "description": "Stable host session/thread id."},
        "evidence_ref": {"type": "string", "description": "Host log, tool-call, or wrapper event reference."},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional host log, tool-call, or wrapper event references.",
        },
        "source": {"type": "string", "description": "Observation source, such as plugin, host, or wrapper."},
        "message": {"type": "string", "description": "Short metadata-only summary. Do not pass raw prompts."},
    },
}


def observe_plugin_tool_call(tool_name: str, args: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any] | None:
    metadata = _observation_metadata(args, kwargs)
    return _record_observation(metadata, event="tool_call", tool=tool_name, hook="")


def observe_plugin_hook_call(hook_name: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    metadata = _observation_metadata({}, kwargs)
    return _record_observation(metadata, event="hook_call", tool="", hook=hook_name)


def public_observation(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {
        "schema_version": str(record.get("schema_version", "")),
        "event": str(record.get("event", "")),
        "status": str(record.get("status", "")),
        "host": str(record.get("host", "")),
        "session_id": str(record.get("session_id", "")),
        "tool": str(record.get("tool", "")),
        "hook": str(record.get("hook", "")),
        "runtime_readiness": str(record.get("runtime_readiness", "")),
        "claim_boundary": str(record.get("claim_boundary", "")),
    }


def attach_public_observation(payload: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any]:
    public = public_observation(record)
    if public:
        payload["plugin_host_observation"] = public
    return payload


def _observation_metadata(args: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for source in (args.get("observation"), kwargs.get("observation"), kwargs.get("omh_observation")):
        if isinstance(source, dict):
            metadata.update(source)
    for key in ("host", "session_id", "source", "message", "omh_home", "hermes_home"):
        if args.get(key) is not None:
            metadata.setdefault(key, args.get(key))
        if kwargs.get(key) is not None:
            metadata.setdefault(key, kwargs.get(key))
    if args.get("evidence_ref") is not None:
        metadata.setdefault("evidence_ref", args.get("evidence_ref"))
    if kwargs.get("evidence_ref") is not None:
        metadata.setdefault("evidence_ref", kwargs.get("evidence_ref"))
    if args.get("evidence_refs") is not None:
        metadata.setdefault("evidence_refs", args.get("evidence_refs"))
    if kwargs.get("evidence_refs") is not None:
        metadata.setdefault("evidence_refs", kwargs.get("evidence_refs"))
    return metadata


def _record_observation(metadata: dict[str, Any], *, event: str, tool: str, hook: str) -> dict[str, Any] | None:
    raw_host = str(metadata.get("host", "") or "").strip()
    raw_session_id = str(metadata.get("session_id", "") or "").strip()
    if not raw_host or not raw_session_id:
        return None

    try:
        host = _bounded_metadata_text(raw_host, field="host")
        session_id = _bounded_metadata_text(raw_session_id, field="session")
        source = _bounded_metadata_text(str(metadata.get("source", "") or "plugin"), field="source") or "plugin"
        clean_tool = _bounded_metadata_text(tool, field="tool")
        clean_hook = _bounded_metadata_text(hook, field="hook")
        message = _bounded_metadata_text(
            str(metadata.get("message", "") or _default_message(event=event, tool=clean_tool, hook=clean_hook)),
            field="message",
        )
        evidence_refs = _evidence_refs(
            metadata,
            event=event,
            tool=clean_tool,
            hook=clean_hook,
            host=host,
            session_id=session_id,
        )
    except ValueError as exc:
        return _observation_error(
            event=event,
            tool=tool,
            hook=hook,
            error=str(exc),
        )

    try:
        from omh.paths import resolve_paths
        from omh.plugin_observations import record_plugin_host_observation

        paths = resolve_paths(
            omh_home=str(metadata.get("omh_home", "") or "") or None,
            hermes_home=str(metadata.get("hermes_home", "") or "") or None,
        )
        return record_plugin_host_observation(
            paths,
            host=host,
            session_id=session_id,
            event=event,
            status="observed",
            source=source,
            tool=clean_tool,
            hook=clean_hook,
            evidence_refs=evidence_refs,
            message=message,
        )
    except (ImportError, ModuleNotFoundError):
        return _record_standalone_observation(
            metadata,
            host=host,
            session_id=session_id,
            event=event,
            source=source,
            tool=clean_tool,
            hook=clean_hook,
            evidence_refs=evidence_refs,
            message=message,
        )
    except Exception as exc:
        return _observation_error(
            event=event,
            tool=clean_tool,
            hook=clean_hook,
            host=host,
            session_id=session_id,
            error=str(exc),
        )


def _evidence_refs(
    metadata: dict[str, Any],
    *,
    event: str,
    tool: str,
    hook: str,
    host: str,
    session_id: str,
) -> list[str]:
    refs: list[str] = []
    raw_refs = metadata.get("evidence_refs")
    if isinstance(raw_refs, list):
        refs.extend(
            _bounded_metadata_text(str(item or ""), field="evidence_ref")
            for item in raw_refs
            if str(item or "").strip()
        )
    raw_ref = str(metadata.get("evidence_ref", "") or "").strip()
    if raw_ref:
        refs.append(_bounded_metadata_text(raw_ref, field="evidence_ref"))
    if refs:
        return refs
    target = tool or hook or "unknown"
    return [f"plugin:{event}:{target}:host={host}:session={session_id}"]


def _default_message(*, event: str, tool: str, hook: str) -> str:
    if event == "tool_call":
        return f"OMH plugin tool {tool} observed with host/session metadata."
    if event == "hook_call":
        return f"OMH plugin hook {hook} observed with host/session metadata."
    return "OMH plugin host observation recorded with metadata-only context."


def _record_standalone_observation(
    metadata: dict[str, Any],
    *,
    host: str,
    session_id: str,
    event: str,
    source: str,
    tool: str,
    hook: str,
    evidence_refs: list[str],
    message: str,
) -> dict[str, Any]:
    omh_home = _expand_path(str(metadata.get("omh_home", "") or "") or os.environ.get("OMH_HOME", "~/.omh"))
    runtime_dir = omh_home / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    try:
        runtime_dir.chmod(0o700)
    except OSError:
        pass
    recorded_at = _utc_now()
    runtime_readiness = _plugin_host_runtime_readiness(event=event, status="observed")
    record: dict[str, Any] = {
        "schema_version": PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION,
        "host": host,
        "session_id": session_id,
        "event": event,
        "status": "observed",
        "observed": True,
        "runtime_readiness": runtime_readiness,
        "native_integration_active": runtime_readiness == "active_runtime_observed",
        "source": source,
        "tool": tool,
        "hook": hook,
        "evidence_refs": evidence_refs,
        "message": message,
        "redaction_policy": "metadata_only_bounded",
        "recorded_at": recorded_at,
        "observed_at": recorded_at,
        "claim_boundary": PLUGIN_HOST_OBSERVATION_CLAIM_BOUNDARY,
    }
    _append_jsonl(runtime_dir / "plugin_host_observations.jsonl", record)
    _update_standalone_state(runtime_dir / "state.json", record, runtime_readiness)
    return record


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _update_standalone_state(path: Path, record: dict[str, Any], runtime_readiness: str) -> None:
    current: dict[str, Any] = {"schema_version": 1}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, json.JSONDecodeError):
            pass
    patch: dict[str, Any] = {
        "last_plugin_host_observation": record,
        "last_plugin_runtime_observed": record if record["native_integration_active"] else None,
        "last_plugin_runtime_readiness": runtime_readiness,
        "schema_version": 1,
        "updated_at": _utc_now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps({**current, **patch}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)


def _observation_error(
    *,
    event: str,
    tool: str,
    hook: str,
    error: str,
    host: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": "omh_plugin_host_observation_error/v1",
        "event": event,
        "status": "not_recorded",
        "host": host,
        "session_id": session_id,
        "tool": tool,
        "hook": hook,
        "runtime_readiness": "not_observed",
        "message": _safe_error_message(error),
        "claim_boundary": "Plugin observation recording failed; no host runtime evidence was persisted.",
    }


def _safe_error_message(error: str) -> str:
    lowered = str(error or "").lower()
    if any(pattern in lowered for pattern in PLUGIN_HOST_SENSITIVE_PATTERNS):
        return "Plugin observation metadata was rejected because it was not metadata-only."
    return str(error or "Plugin observation recording failed.")[:180]


def _plugin_host_runtime_readiness(*, event: str, status: str) -> str:
    if status != "observed":
        return "not_observed"
    if event in PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS:
        return "active_runtime_observed"
    if event in PLUGIN_HOST_HISTORICAL_OBSERVATION_EVENTS:
        return "historical_runtime_observed"
    return "observed_unknown_event"


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


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
