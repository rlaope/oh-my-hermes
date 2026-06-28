from __future__ import annotations

from typing import Any


CHAT_SOURCES = ("generic", "discord", "slack", "telegram", "hermes")
SOURCE_METADATA_KEYS = (
    "source_event_id",
    "project_ref",
    "channel_ref",
    "thread_ref",
    "user_ref",
    "timestamp",
    "agent_ref",
    "target_ref",
    "runtime_ref",
    "workflow_ref",
    "executor_ref",
    "hermes_home",
    "agent_count",
    "target_count",
    "render_profile",
)

_EVENT_TEXT_PATHS = (
    ("message", "content"),
    ("message", "text"),
    ("event", "text"),
    ("body", "text"),
    ("body", "content"),
    ("data", "text"),
    ("data", "content"),
    ("content",),
    ("text",),
    ("prompt",),
    ("input",),
)

_SOURCE_METADATA_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "source_event_id": (
        ("id",),
        ("event_id",),
        ("update_id",),
        ("message", "id"),
        ("message", "message_id"),
        ("event", "id"),
        ("event", "client_msg_id"),
    ),
    "project_ref": (("project_ref",), ("project", "id"), ("repository", "full_name"), ("repo", "full_name")),
    "channel_ref": (
        ("channel",),
        ("channel_id",),
        ("message", "channel"),
        ("message", "chat", "id"),
        ("event", "channel"),
        ("channel", "id"),
    ),
    "thread_ref": (("thread_ref",), ("thread", "id"), ("message", "thread_ts"), ("event", "thread_ts")),
    "user_ref": (
        ("user",),
        ("user_id",),
        ("author", "id"),
        ("message", "author", "id"),
        ("message", "from", "id"),
        ("event", "user"),
    ),
    "timestamp": (
        ("timestamp",),
        ("created_at",),
        ("ts",),
        ("message", "timestamp"),
        ("message", "date"),
        ("event", "ts"),
        ("event", "event_ts"),
    ),
    "agent_ref": (("agent_ref",), ("agent", "id"), ("bot", "id"), ("message", "agent", "id"), ("event", "agent", "id")),
    "target_ref": (("target_ref",), ("target", "id"), ("workspace", "id"), ("team", "id"), ("guild_id",)),
    "runtime_ref": (("runtime_ref",), ("runtime", "id"), ("hermes", "runtime_id"), ("hermes_runtime", "id")),
    "workflow_ref": (("workflow_ref",), ("workflow", "id"), ("workflow", "name")),
    "executor_ref": (("executor_ref",), ("executor", "id"), ("executor", "profile")),
    "hermes_home": (("hermes_home",), ("runtime", "hermes_home"), ("hermes", "home")),
    "agent_count": (("agent_count",), ("agents_count",), ("target", "agent_count"), ("runtime", "agent_count"), ("hermes", "agent_count")),
    "target_count": (("target_count",), ("targets_count",), ("runtime", "target_count"), ("hermes", "target_count")),
    "render_profile": (("render_profile",), ("rendering", "profile"), ("surface", "render_profile"), ("platform", "render_profile")),
}


def extract_message_text(event: dict[str, Any] | str) -> str:
    if isinstance(event, str):
        return event.strip()
    if not isinstance(event, dict):
        raise ValueError("chat event must be an object or string")
    for path in _EVENT_TEXT_PATHS:
        value = value_at_path(event, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError("chat event does not contain a supported text field")


def extract_source_metadata(event: dict[str, Any] | str) -> dict[str, str]:
    if not isinstance(event, dict):
        return {}
    metadata: dict[str, str] = {}
    for output_key, paths in _SOURCE_METADATA_PATHS.items():
        for path in paths:
            value = value_at_path(event, path)
            if isinstance(value, (str, int, float)) and str(value).strip():
                metadata[output_key] = str(value).strip()
                break
    return metadata


def compact_source_metadata(metadata: Any) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    return {key: str(metadata[key]) for key in SOURCE_METADATA_KEYS if key in metadata and str(metadata[key])}


def value_at_path(event: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = event
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
