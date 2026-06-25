from __future__ import annotations

import shutil
import subprocess
from typing import Any

from ..executors import EXECUTOR_PROFILES, executor_label
from ..local_store import atomic_write_json, read_json_object_result, utc_now
from ..paths import OmhPaths


EXECUTOR_READINESS_SCHEMA_VERSION = "executor_readiness/v1"
EXECUTOR_READINESS_PROFILES = EXECUTOR_PROFILES
_PROBE_TIMEOUT_SECONDS = 3
_COMMANDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "codex": ("codex", ("--version",)),
    "claude-code": ("claude", ("--version",)),
    "omx-runtime": ("omx", ("--version",)),
    "omo-runtime": ("omo", ("--version",)),
    "omc-runtime": ("omc", ("--version",)),
}


def executor_readiness_contract(profile: str | None) -> dict[str, object]:
    normalized = _normalize_profile(profile)
    if normalized == "choose":
        return {
            "schema_version": EXECUTOR_READINESS_SCHEMA_VERSION,
            "profile": "choose",
            "status": "choice_required",
            "first_use_only": True,
            "cache_key": "executor_readiness:choose",
            "next_action": "choose_executor_before_probe",
            "fallback_policy": {
                "when_missing": "ask_user_to_choose_executor_or_configure_one",
                "retry_after_state_change": True,
                "retry_limit": 1,
            },
            "claim_boundary": "Executor readiness is not dispatch, execution, verification, review, CI, or merge evidence.",
        }
    command, args = _COMMANDS.get(normalized, ("", ()))
    probe_kind = "local_command" if command else "wrapper_observed_profile"
    return {
        "schema_version": EXECUTOR_READINESS_SCHEMA_VERSION,
        "profile": normalized,
        "label": executor_label(normalized),
        "status": "not_observed",
        "first_use_only": True,
        "cache_key": f"executor_readiness:{normalized}",
        "probe": {
            "kind": probe_kind,
            "command": command,
            "args": list(args),
            "timeout_seconds": _PROBE_TIMEOUT_SECONDS if command else 0,
            "captures": ["available", "exit_code", "summary"],
        },
        "ready_action": _ready_action(normalized),
        "fallback_policy": {
            "when_missing": "ask_user_to_choose_executor_or_configure_one",
            "retry_after_state_change": True,
            "retry_limit": 1,
            "suggested_actions": [
                "choose_executor",
                "show_prompt_handoff",
                "show_runtime_handoff",
                "continue_in_hermes",
            ],
        },
        "not_evidence": [
            "executor dispatch",
            "executor result",
            "execution",
            "implementation",
            "verification",
            "review",
            "CI",
            "merge",
        ],
        "claim_boundary": "Readiness is not dispatch, execution, verification, review, CI, or merge evidence; it only checks whether the selected executor path appears available.",
    }


def executor_readiness_for_selection(
    selected_profile: str | None,
    *,
    choice_required: bool,
) -> dict[str, object]:
    if choice_required or not selected_profile:
        payload = executor_readiness_contract("choose")
        payload["profiles"] = [executor_readiness_contract(profile) for profile in EXECUTOR_READINESS_PROFILES]
        return payload
    return executor_readiness_contract(selected_profile)


def with_executor_readiness_options(options: list[dict[str, object]]) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for option in options:
        profile = str(option.get("profile", ""))
        updated = dict(option)
        updated["readiness_probe"] = executor_readiness_contract(profile)
        enriched.append(updated)
    return enriched


def probe_executor_readiness(
    paths: OmhPaths,
    profile: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    normalized = _normalize_profile(profile)
    if normalized == "choose":
        return executor_readiness_contract("choose")
    contract = executor_readiness_contract(normalized)
    state, state_error = _read_state(paths)
    cached = _cached_profile(state, normalized)
    if cached and not force:
        result = dict(cached)
        result["cache_status"] = "cached"
        result["first_use_skipped"] = True
        result["claim_boundary"] = contract["claim_boundary"]
        return result
    if dry_run:
        result = dict(contract)
        result.update(
            {
                "status": "not_observed",
                "cache_status": "would_probe",
                "first_use_skipped": False,
                "state_error": state_error or "",
            }
        )
        return result
    result = _run_probe(contract)
    _write_state(paths, state, normalized, result)
    return result


def _run_probe(contract: dict[str, object]) -> dict[str, object]:
    result = dict(contract)
    probe = result.get("probe")
    if not isinstance(probe, dict):
        result.update({"status": "not_applicable", "available": False, "observed_once": True})
        return result
    command = str(probe.get("command", ""))
    args = [str(arg) for arg in probe.get("args", [])] if isinstance(probe.get("args"), list) else []
    if not command:
        result.update(
            {
                "status": "not_applicable",
                "available": False,
                "observed_once": True,
                "summary": "This executor profile is wrapper-observed rather than command-probed.",
                "next_action": "ask_wrapper_to_confirm_profile",
            }
        )
        return result
    resolved = shutil.which(command)
    if not resolved:
        result.update(
            {
                "status": "missing",
                "available": False,
                "observed_once": True,
                "summary": f"`{command}` was not found on PATH.",
                "next_action": "choose_executor_or_configure_path",
            }
        )
        return result
    try:
        completed = subprocess.run(
            [resolved, *args],
            text=True,
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update(
            {
                "status": "blocked",
                "available": False,
                "observed_once": True,
                "summary": str(exc),
                "next_action": "choose_executor_or_configure_path",
            }
        )
        return result
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    result.update(
        {
            "status": "ready" if completed.returncode == 0 else "blocked",
            "available": completed.returncode == 0,
            "observed_once": True,
            "exit_code": completed.returncode,
            "command_path": resolved,
            "summary": output[0][:200] if output else f"`{command}` exited with {completed.returncode}.",
            "next_action": _ready_action(str(result.get("profile", ""))) if completed.returncode == 0 else "choose_executor_or_configure_path",
        }
    )
    return result


def _ready_action(profile: str) -> str:
    if profile == "codex":
        return "send_to_executor"
    if profile == "claude-code":
        return "show_prompt_handoff"
    if profile in {"omx-runtime", "omo-runtime", "omc-runtime", "hermes"}:
        return "show_runtime_handoff"
    return "show_prompt_handoff"


def _normalize_profile(profile: str | None) -> str:
    value = str(profile or "choose").strip()
    if value == "choose":
        return value
    if value not in EXECUTOR_READINESS_PROFILES:
        raise ValueError(f"unsupported executor readiness profile: {value}")
    return value


def _read_state(paths: OmhPaths) -> tuple[dict[str, Any], str]:
    state, error = read_json_object_result(paths.executor_readiness_path)
    return state or {"schema_version": "executor_readiness_cache/v1", "profiles": {}}, error or ""


def _cached_profile(state: dict[str, Any], profile: str) -> dict[str, object] | None:
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        return None
    cached = profiles.get(profile)
    if not isinstance(cached, dict):
        return None
    if cached.get("observed_once") is True:
        return {str(key): value for key, value in cached.items()}
    return None


def _write_state(paths: OmhPaths, state: dict[str, Any], profile: str, result: dict[str, object]) -> None:
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    stored = dict(result)
    stored["updated_at"] = utc_now()
    profiles[profile] = stored
    state.update(
        {
            "schema_version": "executor_readiness_cache/v1",
            "updated_at": stored["updated_at"],
            "profiles": profiles,
        }
    )
    atomic_write_json(paths.executor_readiness_path, state, private=True)
