from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final, TypeGuard

from .. import runtime_paths
from ..host_observation import observe_plugin_hook_call
from ..todo_reconciliation import plan_continuation_reading
from .nudge_budget import plan_nudge_allowed

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
    if not valid_coding or attempt_value is None or not paths:
        return None
    plan_message, stamp = _session_plan_reading(_kwargs, session_id)
    # The host offers `agent.max_verify_nudges` nudges per turn and enforces
    # that bound itself, so the plan line may spend more than the first -- but
    # only while the plan keeps being written. A nudge that produced no movement
    # does not repeat, which is what the idempotency guidance was protecting;
    # `nudge_budget` holds the one piece of per-turn state that tells the two
    # apart.
    if not plan_nudge_allowed(session_id=session_id, attempt=attempt_value, stamp=stamp):
        plan_message = ""
    # The served-surface gate stays one-shot. It asks for the check this turn's
    # edit just earned, and the edits are the same on a later attempt of the
    # same turn, so repeating it would restate a request the turn already has.
    surface_message = _served_surface_message(paths) if attempt_value == 0 else ""
    # Two obligations, one directive. The served-surface gate asks for the
    # check the edit just earned; the plan directive says the run is not
    # finished. Both can be true of the same turn, and dropping either one
    # because the other fired would lose exactly the case each was written for.
    messages = [text for text in (surface_message, plan_message) if text]
    if not messages:
        return None
    return {"action": "continue", "message": "\n".join(messages)}


def _session_plan_reading(kwargs: dict[str, object], session_id: str) -> tuple[str, str]:
    """The open-plan directive for the session whose turn is ending, and its stamp.

    Homes bind the way ``pre_llm_call`` binds them. A binding failure is
    silence: a plugin that cannot read the plan has nothing to say about it
    and must not fail the turn it is decorating. It also has no stamp, so a
    turn whose homes stop binding mid-way spends no further budget.
    """
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        hermes_home = str(runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True))
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError):
        return "", ""
    return plan_continuation_reading(
        omh_home=omh_home, hermes_home=hermes_home, session_ref=session_id
    )


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
