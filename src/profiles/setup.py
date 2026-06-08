from __future__ import annotations

from typing import Any

from ..local_store import atomic_write_json, read_json_object, utc_now
from ..paths import OmhPaths


SETUP_PROFILE_SCHEMA_VERSION = "setup_profile/v1"

SETUP_PROFILE_CATEGORIES = (
    {
        "id": "hermes-retained",
        "choice": "1",
        "label": "Hermes retained workflows",
        "default_executor": "hermes",
        "description": "Keep research, planning, interviews, triage, and status narration in Hermes.",
    },
    {
        "id": "prompt-only-coding",
        "choice": "2",
        "label": "Prompt-only coding handoffs",
        "default_executor": "generic",
        "description": "Prepare portable coding-agent prompts without claiming dispatch or execution.",
    },
    {
        "id": "codex-lifecycle",
        "choice": "3",
        "label": "Codex lifecycle handoffs",
        "default_executor": "codex",
        "description": "Use Codex for run-backed dispatch/result/review/CI evidence when selected.",
    },
    {
        "id": "plugin-runtime",
        "choice": "4",
        "label": "Plugin/runtime profiles",
        "default_executor": "omx-runtime",
        "description": "Prepare handoffs for OMX/OMO/OMC-style runtime or plugin workflows.",
    },
    {
        "id": "safety-first",
        "choice": "5",
        "label": "Safety-first evidence mode",
        "default_executor": "choose",
        "description": "Require explicit executor choice and preserve prepared-vs-observed boundaries.",
    },
)

_CATEGORY_BY_ID = {str(item["id"]): item for item in SETUP_PROFILE_CATEGORIES}
_CATEGORY_BY_CHOICE = {str(item["choice"]): item for item in SETUP_PROFILE_CATEGORIES}


def setup_profile_choices() -> list[dict[str, str]]:
    return [{key: str(value) for key, value in item.items()} for item in SETUP_PROFILE_CATEGORIES]


def build_setup_profile(values: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    selected = _selected_categories(values)
    default_executor = _default_executor_for_categories(selected)
    return {
        "schema_version": SETUP_PROFILE_SCHEMA_VERSION,
        "updated_at": utc_now(),
        "selected_categories": [str(item["id"]) for item in selected],
        "default_executor": default_executor,
        "dispatch_policy": "ask_before_dispatch" if default_executor in {"codex", "choose"} else "prepare_only",
        "normal_user_surface": "Hermes Agent chat and installed Hermes skills",
        "local_only": True,
        "network_calls": False,
        "hidden_execution": False,
        "choices": setup_profile_choices(),
        "claim_boundary": "Setup records routing defaults only; it does not prove Hermes used a skill or any executor ran.",
    }


def write_setup_profile(paths: OmhPaths, values: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    profile = build_setup_profile(values)
    atomic_write_json(paths.setup_profile_path, profile, private=True)
    return profile


def read_setup_profile(paths: OmhPaths) -> dict[str, Any] | None:
    return read_json_object(paths.setup_profile_path)


def _selected_categories(values: list[str] | tuple[str, ...] | None) -> list[dict[str, object]]:
    if not values:
        return [_CATEGORY_BY_ID["safety-first"]]
    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        item = _CATEGORY_BY_CHOICE.get(value) or _CATEGORY_BY_ID.get(value)
        if not item:
            valid = ", ".join(sorted(set(_CATEGORY_BY_CHOICE) | set(_CATEGORY_BY_ID)))
            raise ValueError(f"unsupported setup profile choice: {value}; expected one of {valid}")
        item_id = str(item["id"])
        if item_id not in seen:
            selected.append(item)
            seen.add(item_id)
    return selected


def _default_executor_for_categories(selected: list[dict[str, object]]) -> str:
    ids = {str(item["id"]) for item in selected}
    if "safety-first" in ids:
        return "choose"
    if "codex-lifecycle" in ids:
        return "codex"
    if "plugin-runtime" in ids:
        return "omx-runtime"
    if "prompt-only-coding" in ids:
        return "generic"
    return "hermes"
