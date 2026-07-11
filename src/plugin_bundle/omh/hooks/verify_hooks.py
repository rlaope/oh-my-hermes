from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final, TypeGuard

from ..host_observation import observe_plugin_hook_call

_UI_SUFFIXES: Final = frozenset({".css", ".html", ".jsx", ".less", ".sass", ".scss", ".svelte", ".tsx", ".vue"})
_DEPENDENCY_FILES: Final = frozenset(
    {
        "bun.lock",
        "cargo.lock",
        "cargo.toml",
        "go.mod",
        "go.sum",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "uv.lock",
        "yarn.lock",
    }
)
_OBSERVATION_KEYS: Final = ("host", "source", "evidence_ref", "evidence_refs", "omh_home", "hermes_home")


def pre_verify(
    session_id: str = "",
    platform: str = "",
    model: str = "",
    coding: object = False,
    attempt: object = 0,
    final_response: str = "",
    changed_paths: object = None,
    **_kwargs: object,
) -> dict[str, str] | None:
    valid_coding = coding is True
    attempt_value = _attempt_value(attempt)
    paths = _normalized_paths(changed_paths)
    observation = {key: _kwargs[key] for key in _OBSERVATION_KEYS if key in _kwargs}
    observation.update(
        {
            "session_id": session_id,
            "coding": valid_coding,
            "attempt": attempt_value if attempt_value is not None else -1,
            "changed_path_count": len(paths),
            "changed_path_categories": _path_categories(paths),
            "session_present": bool(session_id),
            "platform_present": bool(platform),
            "model_present": bool(model),
            "final_response_present": bool(final_response),
        }
    )
    _ = observe_plugin_hook_call("pre_verify", observation)
    if not valid_coding or attempt_value is None or attempt_value > 0 or not paths:
        return None
    message = _served_surface_message(paths)
    if not message:
        return None
    return {"action": "continue", "message": message}


def _normalized_paths(value: object) -> tuple[str, ...]:
    if not _is_path_sequence(value):
        return ()
    return _normalized_string_paths(value)


def _is_path_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, (list, tuple))


def _normalized_string_paths(paths: Sequence[object]) -> tuple[str, ...]:
    return tuple(path.replace("\\", "/").lower() for path in paths if isinstance(path, str) and path.strip())


def _attempt_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _path_categories(paths: tuple[str, ...]) -> list[str]:
    categories: list[str] = []
    if any(_is_plugin_path(path) for path in paths):
        categories.append("plugin")
    if any(_is_ui_path(path) for path in paths):
        categories.append("ui")
    if any(PurePosixPath(path).name in _DEPENDENCY_FILES for path in paths):
        categories.append("dependency")
    if any(_is_ci_path(path) for path in paths):
        categories.append("ci")
    return categories or (["other"] if paths else [])


def _served_surface_message(paths: tuple[str, ...]) -> str:
    if any(_is_plugin_path(path) for path in paths):
        return (
            "OMH served-surface verification gate: this change affects a Hermes plugin surface. "
            "Run the smallest real plugin load and registration smoke available, then report the observed command and result. "
            "This nudge is guidance, not plugin-load or verification evidence."
        )
    if any(_is_ui_path(path) for path in paths):
        return (
            "OMH served-surface verification gate: this change affects a rendered surface. "
            "Open or render the changed UI at representative desktop and mobile sizes, inspect interaction and text layout, "
            "and report observed evidence. This nudge is guidance, not visual QA evidence."
        )
    if any(PurePosixPath(path).name in _DEPENDENCY_FILES for path in paths):
        return (
            "OMH served-surface verification gate: this change affects dependency or build metadata. "
            "Run the smallest installation or import smoke plus the relevant project check, then report the observed command and result. "
            "This nudge is guidance, not installation or verification evidence."
        )
    if any(_is_ci_path(path) for path in paths):
        return (
            "OMH served-surface verification gate: this change affects CI workflow configuration. "
            "Validate the workflow syntax and exercise the nearest local command path before finishing. "
            "This nudge is guidance, not CI or verification evidence."
        )
    return ""


def _is_ui_path(path: str) -> bool:
    return PurePosixPath(path).suffix in _UI_SUFFIXES


def _is_plugin_path(path: str) -> bool:
    return "/plugin_bundle/" in f"/{path.lstrip('/')}" or path.endswith("plugin.yaml")


def _is_ci_path(path: str) -> bool:
    return "/.github/workflows/" in f"/{path.lstrip('/')}"
