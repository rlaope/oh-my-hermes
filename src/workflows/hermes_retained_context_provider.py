from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SAFE_PROVIDER_ID_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_SECRET_LIKE_PREFIXES: Final = ("sk-", "xox", "ghp_", "gho_", "ghs_", "github_pat_")
_SECRET_LIKE_WORDS: Final = ("secret", "token", "credential", "password", "api_key", "apikey")


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    configured: bool
    provider_id: str
    safe: bool


def clean_config_scalar(value: str) -> str:
    stripped = _strip_unquoted_yaml_comment(value).strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def provider_selection(value: str) -> ProviderSelection:
    if not value:
        return ProviderSelection(configured=False, provider_id="", safe=False)
    if _safe_provider_id(value):
        return ProviderSelection(configured=True, provider_id=value, safe=True)
    return ProviderSelection(configured=True, provider_id="", safe=False)


def marker_exists_under(marker: Path, root: Path) -> bool:
    resolved_marker = marker.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return resolved_marker.is_relative_to(resolved_root) and marker.is_file()


def _strip_unquoted_yaml_comment(value: str) -> str:
    in_single_quote = False
    in_double_quote = False
    for index, character in enumerate(value):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if character == "#" and not in_single_quote and not in_double_quote and _starts_yaml_comment(value, index):
            return value[:index]
    return value


def _starts_yaml_comment(value: str, index: int) -> bool:
    return index == 0 or value[index - 1].isspace()


def _safe_provider_id(value: str) -> bool:
    lowered = value.lower()
    if any(lowered.startswith(prefix) for prefix in _SECRET_LIKE_PREFIXES):
        return False
    if any(word in lowered for word in _SECRET_LIKE_WORDS):
        return False
    return _SAFE_PROVIDER_ID_PATTERN.fullmatch(value) is not None


__all__ = ["ProviderSelection", "clean_config_scalar", "marker_exists_under", "provider_selection"]
