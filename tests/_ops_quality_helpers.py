from __future__ import annotations

from omh.ops_service_quality import JsonObject


def object_items(record: JsonObject, key: str) -> list[JsonObject]:
    value = record.get(key)
    if not isinstance(value, list):
        raise AssertionError(f"{key} must be a list")
    objects: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            raise AssertionError(f"{key} must contain objects")
        objects.append(item)
    return objects


def string_items(record: JsonObject, key: str) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list):
        raise AssertionError(f"{key} must be a list")
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AssertionError(f"{key} must contain strings")
        strings.append(item)
    return strings


def string_field_values(record: JsonObject, key: str, field: str) -> set[str]:
    values: set[str] = set()
    for item in object_items(record, key):
        value = item.get(field)
        if not isinstance(value, str):
            raise AssertionError(f"{key}.{field} must contain strings")
        values.add(value)
    return values
