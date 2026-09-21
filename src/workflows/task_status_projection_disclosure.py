"""Fail-closed disclosure rendering for task status projections."""

from __future__ import annotations

from collections.abc import Mapping


_SENSITIVE_FIELDS = frozenset(
    {
        "body",
        "prompt",
        "workspace_path",
        "secret",
        "attachments",
        "provider_metadata",
    }
)

_MAX_ALLOWED_FIELDS = 32
_MAX_FIELD_NAME_CHARS = 64


def render_disclosed_fields(
    fields: Mapping[str, object],
    *,
    allowed_fields: list[str] | tuple[str, ...],
    max_field_chars: int,
) -> dict[str, str]:
    if not 1 <= len(allowed_fields) <= _MAX_ALLOWED_FIELDS:
        raise ValueError("invalid allowed_fields")

    if not 1 <= max_field_chars:
        raise ValueError("invalid max_field_chars")

    result: dict[str, str] = {}

    for field in allowed_fields:
        if (
            not isinstance(field, str)
            or not field
            or len(field) > _MAX_FIELD_NAME_CHARS
        ):
            raise ValueError("invalid allowed_field")

        if field in _SENSITIVE_FIELDS:
            continue

        value = fields.get(field)

        if not isinstance(value, str):
            continue

        result[field] = value[:max_field_chars]

    return result
