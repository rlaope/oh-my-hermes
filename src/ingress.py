from __future__ import annotations

from typing import Any


CHAT_SOURCES = ("generic", "discord", "slack", "hermes")
SOURCE_METADATA_KEYS = ("source_event_id", "channel_ref", "user_ref", "timestamp")

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
    "source_event_id": (("id",), ("event_id",), ("message", "id"), ("event", "id"), ("event", "client_msg_id")),
    "channel_ref": (("channel",), ("channel_id",), ("message", "channel"), ("event", "channel"), ("channel", "id")),
    "user_ref": (("user",), ("user_id",), ("author", "id"), ("message", "author", "id"), ("event", "user")),
    "timestamp": (("timestamp",), ("created_at",), ("ts",), ("message", "timestamp"), ("event", "ts"), ("event", "event_ts")),
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
