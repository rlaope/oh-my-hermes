from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metadata import (
    OPTIONAL_HOOKS,
    PROVIDED_HOOKS,
    PROVIDED_TOOLS,
    REQUIRED_HOOKS,
    TOOL_FILE_STEMS,
    TOOLS_REQUIRING_ROLE_CATALOG,
)

STATUS_SCHEMA_VERSION = "omh_status/v1"
HUD_SCHEMA_VERSION = "omh_hud/v1"
HUD_PRESETS = {"minimal", "focused", "full"}
HUD_REQUIRED_TOOLS = PROVIDED_TOOLS
HUD_REQUIRED_HOOKS = REQUIRED_HOOKS
HUD_OPTIONAL_HOOKS = OPTIONAL_HOOKS
OBSERVATION_EVENT_SCHEMA_VERSION = "omh_observation_event/v1"
JOURNAL_EVENT_ALIASES = {
    "coding_handoff_prepared": "prepared_handoff_created",
    "handoff_prepared": "prepared_handoff_created",
    "runtime_start": "runtime_start_observed",
    "worktree_creation": "worktree_creation_observed",
    "worker_dispatch": "executor_dispatch_observed",
    "executor_dispatch": "executor_dispatch_observed",
    "worker_result": "executor_result_observed",
    "executor_result": "executor_result_observed",
    "verification": "verification_result_observed",
    "review": "review_result_observed",
    "ci": "ci_result_observed",
    "merge_readiness": "merge_gate_observed",
    "merge": "merge_observed",
}
EXECUTOR_PROGRESS_EVENT_TYPES = {
    "executor_dispatched",
    "repo_exploration",
    "running_no_diff_observed",
    "diff_started",
    "tests_started",
    "tests_failed",
    "tests_passed",
    "executor_completed",
    "executor_blocked",
    "executor_failed",
    "progress_observed",
}
EXECUTOR_PROGRESS_PROFILES = {"codex", "claude_code", "hermes_local"}
EXECUTOR_PROGRESS_BINDING_STATES = {"active", "stale", "expired", "closed"}
RAW_OR_HIDDEN_KEYS = {
    "analysis",
    "chain_of_thought",
    "cot",
    "hidden",
    "hidden_reasoning",
    "raw",
    "raw_log",
    "raw_logs",
    "raw_output",
    "reasoning",
    "think",
    "thinking",
    "transcript",
}


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def _default_omh_home() -> Path:
    return _expand_path(os.environ.get("OMH_HOME", "~/.omh"))


def _default_hermes_home() -> Path:
    return _expand_path(os.environ.get("HERMES_HOME", "~/.hermes"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _bool_from_record(record: dict[str, Any], key: str = "observed") -> bool:
    return bool(record.get(key, False)) if record else False


def _summarize_run(run_dir: Path) -> dict[str, Any]:
    run = _read_json(run_dir / "run.json")
    coding = _read_json(run_dir / "coding_delegation.json")
    delegation = _read_json(run_dir / "delegation.json")
    wrapper = _read_json(run_dir / "wrapper.json")
    review = _read_json(run_dir / "review.json")
    ci = _read_json(run_dir / "ci.json")
    merge = _read_json(run_dir / "merge.json")
    legacy = {
        "run_id": str(run.get("run_id", run_dir.name)),
        "workflow": str(coding.get("recommended_workflow") or run.get("skill", "unknown")),
        "harness": str(coding.get("recommended_harness") or run.get("harness", "unknown")),
        "executor_target": _executor_target_from_coding(coding),
        "phase": str(run.get("phase", run.get("status", "unknown"))),
        "artifact_kind": str(run.get("artifact_kind", "")),
        "observation_status": str(run.get("observation_status", coding.get("status", "unknown"))),
        "prepared_handoff": bool(coding) and str(coding.get("status", "")) == "prepared_not_observed",
        "prompt_dispatched": _bool_from_record(wrapper, "prompt_dispatched"),
        "execution_observed": _bool_from_record(delegation),
        "verification_observed": _bool_from_record(wrapper, "verification_observed"),
        "review_observed": _bool_from_record(review),
        "review_status": str(review.get("status", "not_observed" if review else "unknown")),
        "ci_observed": _bool_from_record(ci),
        "ci_status": str(ci.get("status", "not_observed" if ci else "unknown")),
        "merge_observed": _bool_from_record(merge),
        "merge_status": str(merge.get("status", "not_observed" if merge else "unknown")),
    }
    lifecycle = _journal_projection_for_run(run_dir, legacy)
    _apply_lifecycle_to_run_summary(legacy, lifecycle)
    legacy["lifecycle"] = lifecycle
    legacy["journal_event_count"] = lifecycle["journal_event_count"]
    legacy["latest_event"] = lifecycle["latest_event"]
    return legacy


def _executor_target_from_coding(coding: dict[str, Any]) -> str:
    if not isinstance(coding, dict):
        return ""
    handoff = coding.get("executor_handoff")
    if isinstance(handoff, dict):
        value = str(handoff.get("executor_target") or handoff.get("selected_executor_profile") or "").strip()
        if value:
            return value
    prompt_handoff = coding.get("prompt_handoff")
    if isinstance(prompt_handoff, dict):
        value = str(prompt_handoff.get("selected_executor_profile") or "").strip()
        if value:
            return value
    value = str(coding.get("selected_executor_profile") or coding.get("executor_profile") or "").strip()
    return value


def _journal_projection_for_run(run_dir: Path, legacy: dict[str, Any]) -> dict[str, Any]:
    run_id = str(legacy.get("run_id", run_dir.name))
    runtime_dir = run_dir.parents[1]
    events = [
        event
        for event in _read_jsonl(runtime_dir / "journal" / "events.jsonl")
        if event.get("schema_version") == OBSERVATION_EVENT_SCHEMA_VERSION
        and str(event.get("run_id", "")) == run_id
    ]
    projection: dict[str, Any] = {
        "schema_version": "omh_lifecycle_projection/v1",
        "run_id": run_id,
        "workflow": str(legacy.get("workflow", "")),
        "harness": str(legacy.get("harness", "")),
        "phase": str(legacy.get("phase", "")),
        "prepared_handoff": bool(legacy.get("prepared_handoff", False)),
        "plan_artifact": "",
        "plan_status": "",
        "prompt_dispatched": bool(legacy.get("prompt_dispatched", False)),
        "runtime_start_observed": False,
        "worktree_observed": False,
        "execution_observed": bool(legacy.get("execution_observed", False)),
        "verification_observed": bool(legacy.get("verification_observed", False)),
        "review_observed": bool(legacy.get("review_observed", False)),
        "ci_observed": bool(legacy.get("ci_observed", False)),
        "merge_gate_observed": False,
        "merge_observed": bool(legacy.get("merge_observed", False)),
        "observation_status": str(legacy.get("observation_status", "unknown")),
        "journal_event_count": len(events),
        "latest_event_id": "",
        "latest_event": {},
    }
    for event in events:
        name = JOURNAL_EVENT_ALIASES.get(str(event.get("event", "")), str(event.get("event", "")))
        status = str(event.get("status", "observed"))
        projection["latest_event_id"] = str(event.get("event_id", ""))
        projection["latest_event"] = {
            "event": name,
            "status": status,
            "summary": str(event.get("summary", "")),
            "observed_at": str(event.get("observed_at", "")),
        }
        if event.get("plan_artifact"):
            projection["plan_artifact"] = str(event.get("plan_artifact", ""))
        if event.get("plan_status"):
            projection["plan_status"] = str(event.get("plan_status", ""))
        if status != "observed":
            if status in {"blocked", "failed"}:
                projection["observation_status"] = status
            continue
        if name == "prepared_handoff_created":
            projection["prepared_handoff"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "prepared_not_observed")
        elif name == "runtime_start_observed":
            projection["runtime_start_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "runtime_start_observed")
        elif name == "worktree_creation_observed":
            projection["worktree_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "worktree_creation_observed")
        elif name == "executor_dispatch_observed":
            projection["prompt_dispatched"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "dispatch_observed")
        elif name == "executor_result_observed":
            projection["execution_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "execution_observed")
        elif name == "verification_result_observed":
            projection["verification_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "verification_observed")
        elif name == "review_result_observed":
            projection["review_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "review_observed")
        elif name == "ci_result_observed":
            projection["ci_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "ci_observed")
        elif name == "merge_gate_observed":
            projection["merge_gate_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "merge_gate_observed")
        elif name == "merge_observed":
            projection["merge_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "merge_observed")
    return projection


def _apply_lifecycle_to_run_summary(summary: dict[str, Any], lifecycle: dict[str, Any]) -> None:
    for key in (
        "prepared_handoff",
        "prompt_dispatched",
        "execution_observed",
        "verification_observed",
        "review_observed",
        "ci_observed",
        "merge_observed",
    ):
        summary[key] = bool(summary.get(key, False)) or bool(lifecycle.get(key, False))
    if lifecycle.get("observation_status") and lifecycle.get("observation_status") != "unknown":
        summary["observation_status"] = str(lifecycle["observation_status"])
    if lifecycle.get("plan_artifact"):
        summary["plan_artifact"] = lifecycle["plan_artifact"]
    if lifecycle.get("plan_status"):
        summary["plan_status"] = lifecycle["plan_status"]


def _later_status(current: str, candidate: str) -> str:
    order = [
        "unknown",
        "prepared_not_observed",
        "runtime_start_observed",
        "worktree_creation_observed",
        "dispatch_observed",
        "execution_observed",
        "verification_observed",
        "review_observed",
        "ci_observed",
        "merge_gate_observed",
        "merge_observed",
    ]
    if current in {"blocked", "failed", "cancelled"}:
        return current
    try:
        return candidate if order.index(candidate) >= order.index(current) else current
    except ValueError:
        return candidate


def read_omh_hud(
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    *,
    preset: str = "focused",
    limit: int = 3,
    token_metadata: dict[str, Any] | None = None,
    package_version: str = "",
) -> dict[str, Any]:
    safe_preset = preset if preset in HUD_PRESETS else "focused"
    home = _expand_path(omh_home) if omh_home else _default_omh_home()
    hermes = _expand_path(hermes_home) if hermes_home else _default_hermes_home()
    safe_limit = _safe_limit(limit, default=3)
    status = read_omh_status(home, limit=safe_limit)
    state = _read_json(home / "runtime" / "state.json")
    profile = _read_json(home / "setup-profile.json")
    target_registry = _read_json(home / "targets.json")
    runs = status.get("runs", [])
    latest_run = runs[0] if runs else {}
    payload: dict[str, Any] = {
        "schema_version": HUD_SCHEMA_VERSION,
        "preset": safe_preset,
        "package": "oh-my-hermes",
        "version": _package_version(state, package_version),
        "omh_home": str(home),
        "hermes_home": str(hermes),
        "plugin": _plugin_summary(hermes, state),
        "target_topology": _target_topology_summary(target_registry),
        "executor": _executor_summary(profile),
        "runtime": _hud_runtime_summary(status, latest_run),
        "achievements": _achievements_summary(hermes),
        "tokens": _token_summary(token_metadata or {}),
        "evidence_boundary": (
            "HUD is metadata-only. Prepared handoffs are not execution, review, CI, merge, or token-usage evidence."
        ),
        "privacy": "metadata_only",
    }
    payload["display"] = {
        "line": format_omh_hud_line(payload, preset=safe_preset),
        "segments": _hud_segments(payload, preset=safe_preset),
    }
    return payload


def format_omh_hud_line(payload: dict[str, Any], *, preset: str = "focused") -> str:
    return " | ".join(_hud_segments(payload, preset=preset))


def _package_version(state: dict[str, Any], fallback: str) -> str:
    value = str(state.get("version", "") or fallback or "").strip()
    if value:
        return value
    last_install = state.get("last_install", {})
    if isinstance(last_install, dict):
        release_update = last_install.get("release_update", {})
        current = release_update.get("current", {}) if isinstance(release_update, dict) else {}
        value = str(current.get("package_version", "") if isinstance(current, dict) else "").strip()
    return value or "unknown"


def _plugin_summary(hermes_home: Path, state: dict[str, Any]) -> dict[str, Any]:
    plugin_dir = hermes_home / "plugins" / "omh"
    installed = plugin_dir.is_dir()
    last_distribution = state.get("last_plugin_distribution", {})
    observed = bool(last_distribution.get("observed", False)) if isinstance(last_distribution, dict) else False
    capabilities = _plugin_capabilities(plugin_dir, last_distribution if isinstance(last_distribution, dict) else {})
    complete_files = bool(capabilities["files"]["plugin_yaml"] and capabilities["files"]["init_py"])
    required_tools_ready = all(capabilities["tools"].values())
    required_hooks_ready = all(capabilities["hooks"].get(hook, False) for hook in HUD_REQUIRED_HOOKS)
    if installed and complete_files and required_tools_ready and required_hooks_ready:
        status = "ready"
    elif installed and complete_files:
        status = "stale"
    elif installed:
        status = "installed"
    else:
        status = "missing"
    return {
        "status": status,
        "plugin_dir": str(plugin_dir),
        "distribution_observed": observed,
        "runtime_observed": False,
        "required_tools": list(HUD_REQUIRED_TOOLS),
        "required_hooks": list(HUD_REQUIRED_HOOKS),
        "optional_hooks": list(HUD_OPTIONAL_HOOKS),
        "capabilities": capabilities,
        "stale": status == "stale",
    }


def _plugin_capabilities(plugin_dir: Path, last_distribution: dict[str, Any]) -> dict[str, Any]:
    files = {
        "plugin_yaml": (plugin_dir / "plugin.yaml").is_file(),
        "init_py": (plugin_dir / "__init__.py").is_file(),
        "role_catalog": any((plugin_dir / "references").glob("role-*.md")) if (plugin_dir / "references").is_dir() else False,
        "managed_manifest": (plugin_dir / ".omh-plugin-manifest.json").is_file(),
    }
    files.update(
        {
            stem: (plugin_dir / "tools" / f"{stem}.py").is_file()
            for stem in sorted(set(TOOL_FILE_STEMS.values()))
        }
    )
    yaml_text = _read_text(plugin_dir / "plugin.yaml")
    advertised_tools = set(_yaml_list_values(yaml_text, "provides_tools"))
    advertised_hooks = set(_yaml_list_values(yaml_text, "provides_hooks"))
    registered_tools = set(_string_list(last_distribution.get("registered_tools", [])))
    registered_hooks = set(_string_list(last_distribution.get("registered_hooks", [])))
    tool_sources = advertised_tools | registered_tools
    hook_sources = advertised_hooks | registered_hooks
    return {
        "files": files,
        "tools": _plugin_tool_capabilities(files, tool_sources),
        "hooks": {hook: hook in hook_sources for hook in PROVIDED_HOOKS},
        "advertised_tools": sorted(advertised_tools),
        "advertised_hooks": sorted(advertised_hooks),
    }


def _plugin_tool_capabilities(files: dict[str, bool], tool_sources: set[str]) -> dict[str, bool]:
    capabilities = {}
    for tool in HUD_REQUIRED_TOOLS:
        file_ready = files[TOOL_FILE_STEMS[tool]]
        if tool in TOOLS_REQUIRING_ROLE_CATALOG:
            file_ready = file_ready and files["role_catalog"]
        capabilities[tool] = file_ready and tool in tool_sources
    return capabilities


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _yaml_list_values(text: str, key: str) -> list[str]:
    values: list[str] = []
    in_list = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_list:
            if stripped.startswith("- "):
                values.append(_unquote_yaml_scalar(stripped[2:].strip()))
                continue
            if not raw_line.startswith((" ", "\t")):
                in_list = False
        if stripped.startswith(f"{key}:"):
            remainder = stripped.split(":", 1)[1].strip()
            if not remainder:
                in_list = True
            elif remainder.startswith("[") and remainder.endswith("]"):
                values.extend(_unquote_yaml_scalar(item.strip()) for item in remainder[1:-1].split(",") if item.strip())
            else:
                values.append(_unquote_yaml_scalar(remainder))
    return values


def _unquote_yaml_scalar(value: str) -> str:
    cleaned = value.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _target_topology_summary(registry: dict[str, Any]) -> dict[str, Any]:
    topology = registry.get("topology", {}) if isinstance(registry, dict) else {}
    if not isinstance(topology, dict):
        topology = {}
    targets = registry.get("targets", {}) if isinstance(registry, dict) else {}
    known_count = _safe_int(topology.get("known_target_count"), len(targets) if isinstance(targets, dict) else 0)
    active_count = _safe_int(topology.get("active_agent_count"), known_count)
    mode = str(topology.get("mode", "") or "").strip()
    if not mode:
        mode = "multi_agent_targets" if active_count > 1 else "single_agent_target" if active_count == 1 else "unknown"
    return {
        "mode": mode,
        "known_target_count": known_count,
        "active_agent_count": active_count,
        "transition": str(topology.get("transition", "unknown") or "unknown"),
    }


def _executor_summary(profile: dict[str, Any]) -> dict[str, Any]:
    executor = str(profile.get("default_executor", "") or "").strip() if isinstance(profile, dict) else ""
    if not executor:
        executor = "choose"
    return {
        "default": executor,
        "configured": bool(profile),
        "dispatch_policy": str(profile.get("dispatch_policy", "ask_before_dispatch") if isinstance(profile, dict) else "ask_before_dispatch"),
    }


def _achievements_summary(hermes_home: Path) -> dict[str, Any]:
    # The plugin bundle stays standalone, so this mirrors the tolerant reading
    # in workflows/hermes_achievements.py at HUD granularity: counts only.
    plugin_dir = hermes_home / "plugins" / "hermes-achievements"
    snapshot = _read_json(plugin_dir / "scan_snapshot.json")
    state = _read_json(plugin_dir / "state.json")
    total = 0
    unlocked_flags = 0
    for key in ("achievements", "badges", "catalog", "items"):
        entries = snapshot.get(key)
        if isinstance(entries, dict):
            entries = list(entries.values())
        if isinstance(entries, list):
            total = len(entries)
            unlocked_flags = sum(
                1
                for entry in entries
                if isinstance(entry, dict)
                and (entry.get("unlocked") is True or str(entry.get("state", "")).lower() == "unlocked")
            )
            break
    unlocked = 0
    for key in ("unlocked", "unlocks", "unlocked_badges"):
        container = state.get(key)
        if isinstance(container, (dict, list)):
            unlocked = len(container)
            break
    return {
        "observed": bool(snapshot or state),
        "unlocked_count": max(unlocked, unlocked_flags),
        "total_count": total,
    }


def _hud_runtime_summary(status: dict[str, Any], latest_run: dict[str, Any]) -> dict[str, Any]:
    runs = status.get("runs", [])
    run_count = len(runs) if isinstance(runs, list) else 0
    if not latest_run:
        return {
            "state_present": bool(status.get("runtime_state_present", False)),
            "recent_run_count": run_count,
            "latest_run_id": "",
            "executor_target": "",
            "workflow": "idle",
            "phase": "idle",
            "observation_status": "idle",
            "evidence_state": "idle",
        }
    return {
        "state_present": bool(status.get("runtime_state_present", False)),
        "recent_run_count": run_count,
        "latest_run_id": str(latest_run.get("run_id", "")),
        "executor_target": str(latest_run.get("executor_target", "")),
        "workflow": str(latest_run.get("workflow", "unknown")),
        "phase": str(latest_run.get("phase", "unknown")),
        "observation_status": str(latest_run.get("observation_status", "unknown")),
        "evidence_state": _evidence_state(latest_run),
    }


def _evidence_state(run: dict[str, Any]) -> str:
    if run.get("merge_observed"):
        return "merge_observed"
    if run.get("ci_observed"):
        return "ci_observed"
    if run.get("review_observed"):
        return "review_observed"
    if run.get("verification_observed"):
        return "verification_observed"
    if run.get("execution_observed"):
        return "execution_observed"
    if run.get("prompt_dispatched"):
        return "dispatch_observed"
    if run.get("prepared_handoff"):
        return "prepared_not_observed"
    return str(run.get("observation_status", "unknown") or "unknown")


def _token_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    values = {
        key: value
        for key, value in (
            ("tokens_remaining", _optional_number(metadata.get("tokens_remaining"))),
            ("token_budget", _optional_number(metadata.get("token_budget"))),
            ("input_tokens", _optional_number(metadata.get("input_tokens"))),
            ("output_tokens", _optional_number(metadata.get("output_tokens"))),
            ("context_remaining_percent", _optional_number(metadata.get("context_remaining_percent"))),
        )
        if value is not None
    }
    if not values:
        return {
            "status": "unobserved",
            "summary": "unobserved",
            "values": {},
        }
    summary = _token_display(values)
    return {
        "status": "observed_from_host_metadata",
        "summary": summary,
        "values": values,
    }


def _token_display(values: dict[str, int | float]) -> str:
    remaining = values.get("tokens_remaining")
    budget = values.get("token_budget")
    percent = _token_percent(values)
    if percent is not None:
        return f"{_format_percent(percent)}%"
    if remaining is not None and budget is not None:
        return f"{remaining}/{budget}"
    if remaining is not None:
        return f"remaining={remaining}"
    parts = []
    if values.get("input_tokens") is not None:
        parts.append(f"in={values['input_tokens']}")
    if values.get("output_tokens") is not None:
        parts.append(f"out={values['output_tokens']}")
    return ",".join(parts) if parts else "observed"


def _token_percent(values: dict[str, int | float]) -> float | None:
    supplied = values.get("context_remaining_percent")
    if supplied is not None:
        return float(supplied)
    remaining = values.get("tokens_remaining")
    budget = values.get("token_budget")
    if remaining is None or budget is None or float(budget) <= 0:
        return None
    return float(remaining) / float(budget) * 100


def _format_percent(value: float) -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}"


def _hud_segments(payload: dict[str, Any], *, preset: str) -> list[str]:
    version = str(payload.get("version", "unknown"))
    plugin = payload.get("plugin", {})
    topology = payload.get("target_topology", {})
    executor = payload.get("executor", {})
    runtime = payload.get("runtime", {})
    base = [f"[omh] v{version}"]
    if preset == "minimal":
        return [*base, _activity_label(runtime)]
    focused = [*base, f"plugin:{_plugin_display_status(plugin)}"]
    topology_label = _topology_label(topology)
    if topology_label != "unknown":
        focused.append(f"target:{topology_label}")
    focused.append(_coding_agent_segment(runtime, executor))
    evidence_state = str(runtime.get("evidence_state", "unknown") or "unknown")
    if preset == "full" and evidence_state not in {"idle", "unknown"}:
        focused.append(f"evidence:{_evidence_display_status(evidence_state)}")
    achievements = payload.get("achievements", {})
    if preset == "full" and isinstance(achievements, dict) and achievements.get("observed"):
        focused.append(f"ach:{achievements.get('unlocked_count', 0)}/{achievements.get('total_count', 0)}")
    return focused


def _plugin_display_status(plugin: dict[str, Any]) -> str:
    status = str(plugin.get("status", "unknown") or "unknown")
    labels = {
        "missing": "not-installed",
        "stale": "update-needed",
    }
    return labels.get(status, status)


def _evidence_display_status(state: str) -> str:
    labels = {
        "prepared_not_observed": "prepared",
        "dispatch_observed": "dispatched",
        "execution_observed": "executed",
        "verification_observed": "verified",
        "review_observed": "reviewed",
        "ci_observed": "ci-pass",
        "merge_observed": "merged",
    }
    return labels.get(state, state.replace("_", "-"))


def _coding_agent_segment(runtime: dict[str, Any], executor: dict[str, Any]) -> str:
    agent = _coding_agent_label(runtime.get("executor_target") or executor.get("default"))
    state = _coding_agent_state(runtime)
    return f"coding-agent:{state}({agent})"


def _coding_agent_label(value: Any) -> str:
    default = str(value or "choose").strip() or "choose"
    labels = {
        "choose": "ask",
        "generic": "prompt",
        "hermes": "hermes",
        "codex": "codex",
        "claude-code": "claude-code",
        "omx-runtime": "omx-runtime",
        "omo-runtime": "omo-runtime",
        "omc-runtime": "omc-runtime",
    }
    return labels.get(default, default)


def _activity_label(runtime: dict[str, Any]) -> str:
    workflow = str(runtime.get("workflow", "idle"))
    phase = str(runtime.get("phase", "idle"))
    return "idle" if workflow == "idle" else f"{workflow}:{phase}"


def _coding_agent_state(runtime: dict[str, Any]) -> str:
    if not str(runtime.get("latest_run_id", "")):
        return "idle"
    if not str(runtime.get("executor_target", "")).strip():
        return "idle"
    return str(runtime.get("phase", "unknown") or "unknown")


def _topology_label(topology: dict[str, Any]) -> str:
    mode = str(topology.get("mode", "unknown"))
    active = _safe_int(topology.get("active_agent_count"), 0)
    if mode == "single_agent_target":
        return "single"
    if mode == "multi_agent_targets":
        return f"multi:{active}"
    return "unknown"


def _optional_number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed.is_integer():
        return int(parsed)
    return parsed


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_limit(value: Any, *, default: int, maximum: int = 20) -> int:
    return max(0, min(_safe_int(value, default), maximum))


def read_omh_status(omh_home: str | Path | None = None, limit: int = 5) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, default=5)
    home = _expand_path(omh_home) if omh_home else _default_omh_home()
    runtime_dir = home / "runtime"
    runs_dir = runtime_dir / "runs"
    state = _read_json(runtime_dir / "state.json")
    runs: list[dict[str, Any]] = []
    if runs_dir.exists():
        for run_json in sorted(runs_dir.glob("*/run.json"), reverse=True)[:safe_limit]:
            runs.append(_summarize_run(run_json.parent))
    progress = _executor_progress_projection(runtime_dir, limit=max(safe_limit * 10, safe_limit))
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "omh_home": str(home),
        "runtime_dir": str(runtime_dir),
        "journal_path": str(runtime_dir / "journal" / "events.jsonl"),
        "runtime_state_present": bool(state),
        "latest_run_id": str(state.get("last_run_id", "")) if state else "",
        "plugin_session_end": _read_json(runtime_dir / "plugin-session-end.json"),
        "runs": runs,
        "active_executors": progress["active_executors"],
        "stale_executors": progress["stale_executors"],
        "latest_progress_events": progress["latest_progress_events"],
        "evidence_boundary": {
            "prepared_handoff": "not execution evidence",
            "execution": "requires observed delegation result",
            "verification": "requires observed wrapper verification",
            "review": "requires separate review record",
            "ci": "requires separate CI record",
            "merge": "requires separate merge record",
        },
        "privacy": "metadata_only",
    }


def _executor_progress_projection(runtime_dir: Path, *, limit: int) -> dict[str, Any]:
    bindings = _progress_bindings(runtime_dir, limit=limit)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in bindings:
        binding = item["binding"]
        binding = dict(binding)
        binding["state"] = _projected_binding_state(runtime_dir, binding)
        if binding["state"] == "expired":
            continue
        item["binding"] = binding
        groups.setdefault(str(binding.get("correlation_root", "")), []).append(item)
    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    latest_events: list[dict[str, Any]] = []
    for group in groups.values():
        primary = _choose_progress_primary(group)
        event = _latest_progress_payload(group, "event")
        report = _latest_progress_payload(group, "report")
        if not event and not report:
            continue
        if event:
            latest_events.append(_compact_progress_event(event, primary["binding"]))
        row = _progress_row(primary, group, event, report)
        if primary["binding"].get("state") == "active":
            active.append(row)
        elif primary["binding"].get("state") == "stale":
            stale.append(row)
    active.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    stale.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    latest_events.sort(key=lambda item: str(item.get("observed_at", "")), reverse=True)
    return {
        "active_executors": active[:limit],
        "stale_executors": stale[:limit],
        "latest_progress_events": latest_events[:limit],
    }


def _progress_bindings(runtime_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    roots = (
        (runtime_dir / "runs", "run"),
        (runtime_dir / "wrapper_sessions", "wrapper_session"),
    )
    for root, target_type in roots:
        if not root.exists():
            continue
        for binding_path in sorted(root.glob("*/executor_progress/binding.json"), reverse=True):
            binding = _read_json(binding_path)
            if not _valid_progress_binding(binding, target_type):
                continue
            progress_dir = binding_path.parent
            events = _read_jsonl(progress_dir / "events.jsonl")
            reports = _read_jsonl(progress_dir / "reports.jsonl")
            binding_id = str(binding.get("binding_id", ""))
            instance_id = str(binding.get("instance_id", ""))
            matching_events = [event for event in events if _valid_progress_event(event, binding_id, instance_id)]
            matching_reports = [report for report in reports if _valid_progress_report(report, binding_id, instance_id)]
            items.append(
                {
                    "binding": binding,
                    "latest_event": matching_events[-1] if matching_events else {},
                    "latest_report": matching_reports[-1] if matching_reports else {},
                }
            )
    items.sort(key=lambda item: str(item["binding"].get("updated_at", "")), reverse=True)
    return items[:limit]


def _projected_binding_state(runtime_dir: Path, binding: dict[str, Any]) -> str:
    target_type = str(binding.get("target_type", ""))
    target_id = str(binding.get("target_id", ""))
    if _target_has_terminal_result(runtime_dir, target_type, target_id):
        return "closed"
    if str(binding.get("state", "")) == "closed":
        return "closed"
    age = _seconds_since(str(binding.get("last_observed_at") or binding.get("updated_at") or ""))
    if age is None:
        return "stale"
    expiry = _safe_int(binding.get("expiry_seconds"), 86400)
    freshness = _safe_int(binding.get("freshness_seconds"), 900)
    if age > expiry:
        return "expired"
    if age > freshness:
        return "stale"
    return "active"


def _target_has_terminal_result(runtime_dir: Path, target_type: str, target_id: str) -> bool:
    if target_type == "run":
        delegation = _read_json(runtime_dir / "runs" / target_id / "delegation.json")
        return bool(delegation.get("observed")) and str(delegation.get("result", "")) in {"completed", "blocked", "failed"}
    if target_type == "wrapper_session":
        record = _read_json(runtime_dir / "wrapper_sessions" / target_id / "executor_session.json")
        return bool(record.get("result_observed")) and str(record.get("result", "")) in {"completed", "blocked", "failed"}
    return False


def _choose_progress_primary(group: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        binding = item["binding"]
        target_type = str(binding.get("target_type", ""))
        state = str(binding.get("state", ""))
        precedence = {
            ("wrapper_session", "active"): 5,
            ("run", "active"): 4,
            ("wrapper_session", "stale"): 3,
            ("run", "stale"): 2,
        }.get((target_type, state), 1)
        return precedence, str(binding.get("updated_at", ""))

    return sorted(group, key=sort_key, reverse=True)[0]


def _latest_progress_payload(group: list[dict[str, Any]], key: str) -> dict[str, Any]:
    payload_key = f"latest_{key}"
    timestamp_key = "observed_at" if key == "event" else "reported_at"
    payloads = [item[payload_key] for item in group if isinstance(item.get(payload_key), dict) and item[payload_key]]
    payloads.sort(key=lambda item: str(item.get(timestamp_key, "")), reverse=True)
    return payloads[0] if payloads else {}


def _progress_row(primary: dict[str, Any], group: list[dict[str, Any]], event: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    binding = primary["binding"]
    linked = [
        {
            "binding_id": item["binding"].get("binding_id", ""),
            "instance_id": item["binding"].get("instance_id", ""),
            "target_type": item["binding"].get("target_type", ""),
            "target_id": item["binding"].get("target_id", ""),
            "correlation_root": item["binding"].get("correlation_root", ""),
            "state": item["binding"].get("state", ""),
        }
        for item in group
        if item["binding"].get("binding_id") != binding.get("binding_id")
    ]
    return {
        "primary_binding_id": binding.get("binding_id", ""),
        "primary_instance_id": binding.get("instance_id", ""),
        "binding_id": binding.get("binding_id", ""),
        "instance_id": binding.get("instance_id", ""),
        "target_type": binding.get("target_type", ""),
        "target_id": binding.get("target_id", ""),
        "executor": binding.get("executor_profile", ""),
        "executor_profile": binding.get("executor_profile", ""),
        "correlation_root": binding.get("correlation_root", ""),
        "state": binding.get("state", ""),
        "latest_event": _compact_progress_event(event, binding) if event else {},
        "latest_report": _compact_progress_report(report) if report else {},
        "latest_observed_at": str(event.get("observed_at") or binding.get("last_observed_at") or binding.get("updated_at") or ""),
        "linked_bindings": linked,
        "claim_boundary": binding.get("claim_boundary", ""),
    }


def _compact_progress_event(event: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": event.get("binding_id") or binding.get("binding_id", ""),
        "instance_id": event.get("instance_id") or binding.get("instance_id", ""),
        "executor_profile": event.get("executor_profile") or binding.get("executor_profile", ""),
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", ""),
        "observed_at": event.get("observed_at", ""),
        "claim_boundary": event.get("claim_boundary", binding.get("claim_boundary", "")),
    }


def _compact_progress_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": report.get("binding_id", ""),
        "instance_id": report.get("instance_id", ""),
        "event_type": report.get("event_type", ""),
        "status": report.get("status", ""),
        "summary": report.get("summary", ""),
        "reported_at": report.get("reported_at", ""),
        "claim_boundary": report.get("claim_boundary", ""),
    }


def _valid_progress_binding(binding: dict[str, Any], expected_target_type: str) -> bool:
    if not isinstance(binding, dict) or _has_raw_or_hidden_content(binding):
        return False
    if binding.get("schema_version") != "omh_executor_progress_binding/v1":
        return False
    target_value = binding.get("target")
    target = target_value if isinstance(target_value, dict) else {}
    target_type = str(binding.get("target_type") or target.get("type") or "")
    target_id = str(binding.get("target_id") or target.get("id") or "")
    profile = str(binding.get("executor_profile") or binding.get("executor") or "")
    if target_type != expected_target_type or target_type not in {"run", "wrapper_session"}:
        return False
    if not target_id:
        return False
    if profile not in EXECUTOR_PROGRESS_PROFILES:
        return False
    if str(binding.get("binding_id", "")) != f"{target_type}:{target_id}:{profile}":
        return False
    if not str(binding.get("instance_id", "")).strip():
        return False
    if not str(binding.get("correlation_root", "")).strip():
        return False
    if str(binding.get("state", "")) not in EXECUTOR_PROGRESS_BINDING_STATES:
        return False
    return "not result" in str(binding.get("claim_boundary", ""))


def _valid_progress_event(event: dict[str, Any], binding_id: str, instance_id: str) -> bool:
    if not isinstance(event, dict) or _has_raw_or_hidden_content(event):
        return False
    if event.get("schema_version") != "omh_progress_event/v1":
        return False
    if str(event.get("binding_id", "")) != binding_id:
        return False
    if str(event.get("instance_id", "")) != instance_id:
        return False
    if str(event.get("event_type", "")) not in EXECUTOR_PROGRESS_EVENT_TYPES:
        return False
    if str(event.get("executor_profile", "")) not in EXECUTOR_PROGRESS_PROFILES:
        return False
    summary = str(event.get("summary", "")).strip()
    if not summary or len(summary) > 360:
        return False
    if not str(event.get("transition_fingerprint", "")).strip():
        return False
    return "not result" in str(event.get("claim_boundary", ""))


def _valid_progress_report(report: dict[str, Any], binding_id: str, instance_id: str) -> bool:
    if not isinstance(report, dict) or _has_raw_or_hidden_content(report):
        return False
    if report.get("schema_version") != "omh_progress_report/v1":
        return False
    if str(report.get("binding_id", "")) != binding_id:
        return False
    if str(report.get("instance_id", "")) != instance_id:
        return False
    if str(report.get("executor_profile", "")) not in EXECUTOR_PROGRESS_PROFILES:
        return False
    summary = str(report.get("summary", "")).strip()
    if not summary or len(summary) > 360:
        return False
    return "not result" in str(report.get("claim_boundary", ""))


def _has_raw_or_hidden_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in RAW_OR_HIDDEN_KEYS:
                return True
            if _has_raw_or_hidden_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_raw_or_hidden_content(item) for item in value)
    if isinstance(value, str):
        return len(value) > 2000
    return False


def _seconds_since(value: str) -> float | None:
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - parsed.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None
