from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..awareness import awareness_route_hint
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

OMH_INTERACT_SCHEMA = {
    "name": "omh_interact",
    "description": (
        "Build the OMH chat_interaction/v1 envelope for a natural-language Hermes request and, "
        "by default, record a metadata-only wrapper session. This is chat orchestration evidence, "
        "not executor dispatch, implementation, review, CI, or merge evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Current user request. The plugin returns hash/length metadata instead of echoing it.",
            },
            "source": {
                "type": "string",
                "enum": ["generic", "discord", "slack", "telegram", "hermes"],
                "default": "hermes",
                "description": "Host chat surface that produced the request.",
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "route", "plan", "delegate"],
                "default": "auto",
                "description": "OMH chat interaction mode.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
                "description": "Maximum route recommendations to consider.",
            },
            "min_confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "default": "high",
                "description": "Minimum confidence threshold for auto routing.",
            },
            "executor_target": {
                "type": "string",
                "default": "choose",
                "description": "Preferred coding-agent/runtime target when mode=delegate.",
            },
            "record_session": {
                "type": "boolean",
                "default": True,
                "description": "Record or resume a metadata-only wrapper session under OMH runtime state.",
            },
            "source_metadata": {
                "type": "object",
                "description": "Optional bounded wrapper metadata such as source_event_id, channel_ref, user_ref, target_ref, or runtime_ref.",
            },
            "omh_home": {
                "type": "string",
                "description": "Optional OMH_HOME override. Defaults to $OMH_HOME or ~/.omh.",
            },
            "hermes_home": {
                "type": "string",
                "description": "Optional HERMES_HOME override. Defaults to $HERMES_HOME or ~/.hermes.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
        "required": ["message"],
    },
}

_CLAIM_BOUNDARY = (
    "A wrapper chat/session record proves OMH chat orchestration metadata only. "
    "It is not executor dispatch, implementation, verification, review, CI, merge, "
    "or proof of unrecorded Hermes wrapper behavior."
)
_METADATA_TEXT_LIMIT = 180
_SENSITIVE_PATTERNS = (
    "api_key",
    "apikey",
    "authorization:",
    "bearer ",
    "ghp_",
    "password",
    "private-token",
    "secret",
    "token",
    "xoxb-",
    "xoxp-",
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:sk-[a-z0-9_-]+|github_pat_[a-z0-9_]+|gh[opsu]_[a-z0-9_]+)"
)


def omh_interact_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_interact", args, kwargs)
    message = str(args.get("message") or "").strip()
    if not message:
        payload = {
            "schema_version": "omh_interact_result/v1",
            "status": "error",
            "error": "omh_interact.message is required",
            "claim_boundary": _CLAIM_BOUNDARY,
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    try:
        payload = _package_interaction(args, message, observation=observation)
    except (ImportError, ModuleNotFoundError) as exc:
        payload = _fallback_interaction(args, message, error=str(exc))
    except Exception as exc:
        payload = _backend_error_interaction(args, message, error_type=type(exc).__name__)
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _package_interaction(
    args: dict[str, Any],
    message: str,
    *,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from omh.paths import resolve_paths
    from omh.wrapper.contract import build_chat_interaction_payload
    from omh.wrapper.sessions import create_or_resume_wrapper_session

    paths = resolve_paths(
        omh_home=_optional_path_arg(args.get("omh_home")),
        hermes_home=_optional_path_arg(args.get("hermes_home")),
    )
    source = _source(args)
    mode = _mode(args)
    limit = _bounded_limit(args.get("limit"), default=3)
    min_confidence = _min_confidence(args)
    executor_target = str(args.get("executor_target") or "choose")
    source_metadata = _source_metadata(args)

    if bool(args.get("record_session", True)):
        result = create_or_resume_wrapper_session(
            paths,
            message,
            source=source,
            mode=mode,
            limit=limit,
            min_confidence=min_confidence,
            source_metadata=source_metadata,
            executor_target=executor_target,
            record_provenance={
                "producer": "plugin_tool",
                "producer_detail": "omh_interact plugin tool",
                "observed_by_host": bool(observation and observation.get("status") == "observed"),
            },
        )
        interaction = dict(result["interaction"])
        session = result["session"]
        interaction["wrapper_session"] = {
            "schema_version": "omh_wrapper_session_ref/v1",
            "recorded": True,
            "resumed": bool(result.get("resumed", False)),
            "session_id": str(session.get("session_id", "")),
            "session_status": str(session.get("status", "")),
            "thread_key": str(session.get("thread_key", "")),
            "record_provenance": session.get("record_provenance", {}),
            "status_next_action": str(result.get("status", {}).get("next_action", "")),
            "claim_boundary": _CLAIM_BOUNDARY,
        }
        interaction["wrapper_session_status"] = result.get("status", {})
        return interaction

    interaction = build_chat_interaction_payload(
        message,
        source=source,
        mode=mode,
        limit=limit,
        min_confidence=min_confidence,
        include_message=False,
        executor_target=executor_target,
        source_metadata=source_metadata,
        paths=paths,
    )
    interaction["wrapper_session"] = {
        "schema_version": "omh_wrapper_session_ref/v1",
        "recorded": False,
        "reason": "record_session=false",
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return interaction


def _backend_error_interaction(args: dict[str, Any], message: str, *, error_type: str) -> dict[str, Any]:
    source = _source(args)
    metadata = _source_metadata(args)
    message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return {
        "schema_version": "omh_interact_result/v1",
        "status": "error",
        "error": "package_backend_error",
        "error_type": _safe_error_type(error_type),
        "source": source,
        "source_metadata": metadata,
        "message_sha256": message_hash,
        "message_length": len(message),
        "thread_key": _thread_key(source, metadata, message_hash),
        "wrapper_session": {
            "schema_version": "omh_wrapper_session_ref/v1",
            "recorded": False,
            "reason": "package_backend_error",
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "redaction_policy": "metadata_only",
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _fallback_interaction(args: dict[str, Any], message: str, *, error: str) -> dict[str, Any]:
    source = _source(args)
    metadata = _source_metadata(args)
    route_hint = awareness_route_hint(message, max_hints=_bounded_limit(args.get("limit"), default=3))
    workflow = str(route_hint.get("primary_workflow") or "oh-my-hermes")
    message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": "chat_interaction/v1",
        "source": source,
        "source_metadata": metadata,
        "message_sha256": message_hash,
        "message_length": len(message),
        "thread_key": _thread_key(source, metadata, message_hash),
        "mode": "route",
        "next_action": str(route_hint.get("primary_next_action") or "show_workflow_guidance"),
        "route_hint": route_hint,
        "chat_response": {
            "schema_version": "chat_response/v1",
            "kind": "route_hint",
            "headline": f"[omh] route - {workflow}",
            "body": "OMH can suggest the nearest workflow here, but package-backed chat/session recording is unavailable.",
            "state": {
                "selected_workflow": workflow,
                "recording_status": "not_recorded",
                "recording_error": "package_backend_unavailable",
            },
            "actions": [
                {
                    "id": "show_status",
                    "label": "Show status",
                    "style": "secondary",
                    "enabled": True,
                }
            ],
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "wrapper_session": {
            "schema_version": "omh_wrapper_session_ref/v1",
            "recorded": False,
            "reason": "package_backend_unavailable",
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "redaction_policy": "metadata_only",
        "degraded": True,
        "source_backend": "standalone_plugin_bundle_fallback",
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return payload


def _source(args: dict[str, Any]) -> str:
    value = str(args.get("source") or "hermes")
    return value if value in {"generic", "discord", "slack", "telegram", "hermes"} else "hermes"


def _mode(args: dict[str, Any]) -> str:
    value = str(args.get("mode") or "auto")
    return value if value in {"auto", "route", "plan", "delegate"} else "auto"


def _min_confidence(args: dict[str, Any]) -> str:
    value = str(args.get("min_confidence") or "high")
    return value if value in {"low", "medium", "high"} else "high"


def _bounded_limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 10))


def _source_metadata(args: dict[str, Any]) -> dict[str, str]:
    allowed = {
        "source_event_id",
        "channel_ref",
        "user_ref",
        "timestamp",
        "agent_ref",
        "target_ref",
        "runtime_ref",
        "hermes_home",
        "agent_count",
        "target_count",
        "render_profile",
    }
    raw = args.get("source_metadata")
    metadata: dict[str, str] = {}
    if isinstance(raw, dict):
        metadata.update(
            {
                str(key): cleaned
                for key, value in raw.items()
                if key in allowed and (cleaned := _safe_metadata_text(value))
            }
        )
    for key in allowed:
        if key in args and (cleaned := _safe_metadata_text(args.get(key))):
            metadata.setdefault(key, cleaned)
    return metadata


def _optional_path_arg(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _thread_key(source: str, metadata: dict[str, str], message_hash: str) -> str:
    channel = metadata.get("channel_ref") or "channel"
    event = metadata.get("source_event_id") or message_hash[:12]
    return f"{source}:{channel}:{event}"


def _safe_error_type(error_type: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]", "", str(error_type or ""))
    return text[:80] or "Exception"


def _safe_metadata_text(value: object) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    lowered = text.lower()
    if any(pattern in lowered for pattern in _SENSITIVE_PATTERNS) or _SENSITIVE_VALUE_PATTERN.search(text):
        return ""
    return text[:_METADATA_TEXT_LIMIT]
