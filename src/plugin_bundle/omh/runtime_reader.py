from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATUS_SCHEMA_VERSION = "omh_status/v1"
HUD_SCHEMA_VERSION = "omh_hud/v1"
HUD_PRESETS = {"minimal", "focused", "full"}
HUD_REQUIRED_TOOLS = ("omh_gather_evidence", "omh_hud", "omh_role", "omh_status")
HUD_REQUIRED_HOOKS = ("on_session_end", "pre_llm_call", "pre_tool_call")


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
    return {
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
    required_hooks_ready = all(capabilities["hooks"].values())
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
        "capabilities": capabilities,
        "stale": status == "stale",
    }


def _plugin_capabilities(plugin_dir: Path, last_distribution: dict[str, Any]) -> dict[str, Any]:
    files = {
        "plugin_yaml": (plugin_dir / "plugin.yaml").is_file(),
        "init_py": (plugin_dir / "__init__.py").is_file(),
        "evidence_tool": (plugin_dir / "tools" / "evidence_tool.py").is_file(),
        "hud_tool": (plugin_dir / "tools" / "hud_tool.py").is_file(),
        "role_tool": (plugin_dir / "tools" / "role_tool.py").is_file(),
        "status_tool": (plugin_dir / "tools" / "status_tool.py").is_file(),
        "role_catalog": any((plugin_dir / "references").glob("role-*.md")) if (plugin_dir / "references").is_dir() else False,
        "managed_manifest": (plugin_dir / ".omh-plugin-manifest.json").is_file(),
    }
    yaml_text = _read_text(plugin_dir / "plugin.yaml")
    advertised_tools = set(_yaml_list_values(yaml_text, "provides_tools"))
    advertised_hooks = set(_yaml_list_values(yaml_text, "provides_hooks"))
    registered_tools = set(_string_list(last_distribution.get("registered_tools", [])))
    registered_hooks = set(_string_list(last_distribution.get("registered_hooks", [])))
    tool_sources = advertised_tools | registered_tools
    hook_sources = advertised_hooks | registered_hooks
    return {
        "files": files,
        "tools": {
            "omh_gather_evidence": files["evidence_tool"] and "omh_gather_evidence" in tool_sources,
            "omh_hud": files["hud_tool"] and "omh_hud" in tool_sources,
            "omh_role": files["role_tool"] and files["role_catalog"] and "omh_role" in tool_sources,
            "omh_status": files["status_tool"] and "omh_status" in tool_sources,
        },
        "hooks": {
            "on_session_end": "on_session_end" in hook_sources,
            "pre_llm_call": "pre_llm_call" in hook_sources,
            "pre_tool_call": "pre_tool_call" in hook_sources,
        },
        "advertised_tools": sorted(advertised_tools),
        "advertised_hooks": sorted(advertised_hooks),
    }


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
        focused.append(f"evidence:{evidence_state}")
    return focused


def _plugin_display_status(plugin: dict[str, Any]) -> str:
    status = str(plugin.get("status", "unknown") or "unknown")
    labels = {
        "missing": "not-installed",
        "stale": "update-needed",
    }
    return labels.get(status, status)


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
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "omh_home": str(home),
        "runtime_dir": str(runtime_dir),
        "runtime_state_present": bool(state),
        "latest_run_id": str(state.get("last_run_id", "")) if state else "",
        "plugin_session_end": _read_json(runtime_dir / "plugin-session-end.json"),
        "runs": runs,
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
