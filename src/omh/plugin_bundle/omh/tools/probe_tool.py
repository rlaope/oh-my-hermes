from __future__ import annotations

import json
from json import JSONDecodeError
import os
from pathlib import Path
from typing import Any

from ..host_observation import PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..runtime_reader import read_omh_hud, read_omh_status

OMH_PROBE_SCHEMA = {
    "name": "omh_probe",
    "description": (
        "Read OMH local capability probe and roadmap metadata. Capability presence is not "
        "Hermes runtime load, workflow execution, coding dispatch, review, CI, or merge evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "omh_home": {
                "type": "string",
                "description": "Optional OMH_HOME override. Defaults to $OMH_HOME or ~/.omh.",
            },
            "hermes_home": {
                "type": "string",
                "description": "Optional HERMES_HOME override. Defaults to $HERMES_HOME or ~/.hermes.",
            },
            "include_parity": {
                "type": "boolean",
                "description": "Include the parity matrix when the package backend is available.",
            },
            "include_roadmap": {
                "type": "boolean",
                "description": "Include the capability gap roadmap.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_probe_handler(args: dict, **kwargs) -> str:
    include_parity = bool(args.get("include_parity", False))
    include_roadmap = bool(args.get("include_roadmap", False))
    omh_home = _optional_path_arg(args.get("omh_home"))
    hermes_home = _optional_path_arg(args.get("hermes_home"))
    observation = observe_plugin_tool_call("omh_probe", args, kwargs)
    try:
        payload = _package_probe(
            omh_home=omh_home,
            hermes_home=hermes_home,
            include_parity=include_parity,
            include_roadmap=include_roadmap,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "omh":
            raise
        payload = _standalone_probe(
            omh_home=omh_home,
            hermes_home=hermes_home,
            include_parity=include_parity,
            include_roadmap=include_roadmap,
        )
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _package_probe(
    *,
    omh_home: str | None,
    hermes_home: str | None,
    include_parity: bool,
    include_roadmap: bool,
) -> dict[str, Any]:
    from omh.paths import resolve_paths
    from omh.probe import probe_capabilities

    paths = resolve_paths(omh_home=omh_home, hermes_home=hermes_home)
    payload = probe_capabilities(paths, include_parity=include_parity, include_roadmap=include_roadmap)
    payload["source"] = "package_probe_backend"
    payload["degraded"] = False
    payload["plugin_tool"] = "omh_probe"
    payload["privacy"] = "metadata_only"
    return payload


def _standalone_probe(
    *,
    omh_home: str | None,
    hermes_home: str | None,
    include_parity: bool,
    include_roadmap: bool,
) -> dict[str, Any]:
    # Keep this fallback deliberately smaller than omh.probe: copied plugin bundles
    # must answer setup/status questions without importing the installed package.
    home = _expand_path(omh_home or os.environ.get("OMH_HOME", "~/.omh"))
    hermes = _expand_path(hermes_home or os.environ.get("HERMES_HOME", "~/.hermes"))
    status = read_omh_status(omh_home=home, limit=3)
    hud = read_omh_hud(omh_home=home, hermes_home=hermes, preset="focused", limit=1)
    plugin_observation = _latest_plugin_observation(home)
    plugin_runtime_observed = bool(plugin_observation and plugin_observation.get("observed"))
    plugin_runtime_active = (
        plugin_runtime_observed and str(plugin_observation.get("runtime_readiness", "")) == "active_runtime_observed"
    )
    capabilities = _standalone_capabilities(home, hermes, status, hud, plugin_observation=plugin_observation)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "plugin_tool": "omh_probe",
        "omh_home": str(home),
        "hermes_home": str(hermes),
        "capabilities": capabilities,
        "target_topology": hud.get("target_topology", {}),
        "plugin_distribution_ready": _capability_status(capabilities, "omh_plugin_bundle") == "available",
        "plugin_runtime_observed": plugin_runtime_observed,
        "plugin_runtime_active": plugin_runtime_active,
        "native_integration_claim_ready": plugin_runtime_active,
        "privacy": "metadata_only",
        "claim_boundary": (
            "This standalone plugin probe can read local OMH files and the current plugin bundle metadata. "
            "It does not prove Hermes host load beyond this tool response, executor dispatch, implementation, "
            "review, CI, merge, or unrecorded wrapper activity."
        ),
    }
    if include_roadmap:
        payload["capability_gap_roadmap"] = _standalone_roadmap(payload)
    if include_parity:
        payload["parity_matrix"] = {
            "schema_version": "omh_parity_matrix/v1",
            "source": "standalone_plugin_bundle_fallback",
            "degraded": True,
            "status": "unavailable_without_package_backend",
            "message": "Install or refresh the OMH package backend to compute the full parity matrix.",
            "claim_boundary": "Missing parity detail is a degraded plugin context, not a product capability claim.",
        }
        payload.setdefault("capability_gap_roadmap", _standalone_roadmap(payload))
    return payload


def _standalone_capabilities(
    home: Path,
    hermes: Path,
    status: dict[str, Any],
    hud: dict[str, Any],
    *,
    plugin_observation: dict[str, Any] | None,
) -> list[dict[str, str]]:
    skills_dir = home / "skills"
    managed_skill = skills_dir / "oh-my-hermes" / "SKILL.md"
    hermes_config = hermes / "config.yaml"
    config_text = _read_text(hermes_config)
    plugin_dir = hermes / "plugins" / "omh"
    target_topology = hud.get("target_topology", {}) if isinstance(hud, dict) else {}
    wrapper_paths = []
    runs_dir = home / "runtime" / "runs"
    sessions_dir = home / "runtime" / "wrapper_sessions"
    if runs_dir.exists():
        wrapper_paths.extend(sorted(runs_dir.glob("*/wrapper.json")))
    if sessions_dir.exists():
        wrapper_paths.extend(sorted(sessions_dir.glob("*/session.json")))
    return [
        _capability(
            "external_skill_dirs",
            "available" if str(skills_dir) in config_text else ("missing" if hermes_config.exists() else "unknown"),
            str(hermes_config),
            (
                "Hermes config references the managed OMH skills directory"
                if str(skills_dir) in config_text
                else "Managed OMH skills are not registered in this config from the standalone probe view"
            ),
        ),
        _capability(
            "managed_skills",
            "available" if managed_skill.is_file() else "missing",
            str(managed_skill),
            "Managed oh-my-hermes skill is installed" if managed_skill.is_file() else "Managed OMH skill files are missing",
        ),
        _capability(
            "plugin_dir_exists",
            "available" if (hermes / "plugins").is_dir() else "unknown",
            str(hermes / "plugins"),
            "Hermes plugin directory exists" if (hermes / "plugins").is_dir() else "No Hermes plugin directory detected",
        ),
        _capability(
            "omh_plugin_bundle",
            "available" if _plugin_bundle_ready(plugin_dir) else "missing",
            str(plugin_dir),
            "Managed OMH plugin bundle files are present" if _plugin_bundle_ready(plugin_dir) else "Managed OMH plugin bundle files are missing",
        ),
        _capability(
            "plugin_tool_context",
            "available",
            "omh_probe",
            "This response was produced by the managed OMH plugin tool; persisted host observation remains separate",
        ),
        _standalone_plugin_runtime_capability(home, plugin_observation),
        _capability(
            "wrapper_metadata",
            "available" if wrapper_paths else "missing",
            ", ".join(str(path) for path in wrapper_paths[:3]) if wrapper_paths else str(home / "runtime" / "runs"),
            "Wrapper observation artifacts are present" if wrapper_paths else "No wrapper observation artifacts recorded yet",
        ),
        _capability(
            "target_registry",
            "available" if (home / "targets.json").is_file() else "missing",
            str(home / "targets.json"),
            _target_message(target_topology),
        ),
        _capability(
            "runtime_status",
            "available" if status.get("runtime_state_present") else "unknown",
            str(home / "runtime" / "state.json"),
            "OMH runtime state is present" if status.get("runtime_state_present") else "No OMH runtime state has been recorded yet",
        ),
        _capability(
            "mcp_bridge_server",
            "unknown",
            "omh mcp serve",
            "Standalone plugin fallback cannot prove the package-backed MCP bridge command is installed",
        ),
    ]


def _standalone_roadmap(probe_payload: dict[str, Any]) -> dict[str, Any]:
    capabilities = {
        str(item.get("name")): item
        for item in probe_payload.get("capabilities", [])
        if isinstance(item, dict)
    }
    baseline = [
        _gap(capabilities, name, category="product_gap", severity="blocking")
        for name in ("managed_skills", "external_skill_dirs", "omh_plugin_bundle", "target_registry")
        if _status(capabilities, name) not in {"available"}
    ]
    evidence = [
        _gap(capabilities, name, category="evidence_gap", severity="non_blocking")
        for name in ("plugin_runtime_observed", "wrapper_metadata")
        if _status(capabilities, name) != "available"
    ]
    next_actions: list[dict[str, Any]] = []
    if baseline:
        next_actions.append(
            {
                "id": "run_setup",
                "kind": "product_gap",
                "priority": 10,
                "label": "Run OMH setup",
                "command": "omh setup",
                "why": "Managed skills, Hermes registration, target registry, or the managed plugin bundle is missing.",
                "boundary": "Setup prepares local OMH surfaces; it is not workflow execution evidence.",
                "capabilities": [str(item["capability"]) for item in baseline],
            }
        )
    if _status(capabilities, "plugin_runtime_observed") != "available":
        next_actions.append(
            {
                "id": "observe_plugin_runtime",
                "kind": "evidence_gap",
                "priority": 20,
                "label": "Record Hermes plugin runtime observation",
                "command": "omh plugin observe-host --host hermes-agent --session <session-id> --event plugin_load --evidence-ref <host-log-ref>",
                "why": "The plugin may be locally available, but active host/runtime evidence is still separate.",
                "boundary": "A plugin observation proves only that host plugin event, not coding execution, review, CI, or merge.",
                "capabilities": ["plugin_runtime_observed"],
            }
        )
    if _status(capabilities, "wrapper_metadata") != "available":
        next_actions.append(
            {
                "id": "record_wrapper_usage",
                "kind": "evidence_gap",
                "priority": 30,
                "label": "Record a wrapper-visible OMH workflow run",
                "operator_instruction": "Ask Hermes to use an OMH workflow, then let the wrapper record route/session status.",
                "why": "No wrapper/session artifact has been observed in this OMH home yet.",
                "boundary": "A wrapper record is chat orchestration evidence, not executor implementation evidence.",
                "capabilities": ["wrapper_metadata"],
            }
        )
    next_actions.sort(key=lambda item: int(item.get("priority", 100)))
    return {
        "schema_version": "omh_capability_gap_roadmap/v1",
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "summary": {
            "baseline_product_gaps": len(baseline),
            "evidence_gaps": len(evidence),
            "optional_or_host_unknowns": 1,
            "baseline_ready": len(baseline) == 0,
            "native_runtime_observed": _status(capabilities, "plugin_runtime_observed") == "available",
            "wrapper_usage_observed": _status(capabilities, "wrapper_metadata") == "available",
        },
        "product_gaps": baseline,
        "evidence_gaps": evidence,
        "optional_or_host_unknowns": [
            _gap(capabilities, "mcp_bridge_server", category="host_unknown", severity="informational")
        ],
        "next_actions": next_actions,
        "claim_boundary": (
            "This degraded roadmap separates product setup gaps from missing runtime evidence. "
            "It does not claim host plugin load, wrapper routing, executor work, review, CI, or merge."
        ),
    }


def _optional_path_arg(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def _plugin_bundle_ready(plugin_dir: Path) -> bool:
    return (plugin_dir / "plugin.yaml").is_file() and (plugin_dir / "__init__.py").is_file()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _latest_plugin_observation(home: Path) -> dict[str, Any] | None:
    path = home / "runtime" / "plugin_host_observations.jsonl"
    if not path.exists():
        return None
    latest: dict[str, Any] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("schema_version") == "omh_plugin_host_observation/v1":
            latest = record
    return latest


def _standalone_plugin_runtime_capability(home: Path, observation: dict[str, Any] | None) -> dict[str, str]:
    evidence = str(home / "runtime" / "plugin_host_observations.jsonl")
    if observation and observation.get("observed"):
        host = str(observation.get("host", "unknown") or "unknown")
        event = str(observation.get("event", "unknown") or "unknown")
        session_id = str(observation.get("session_id", "unknown") or "unknown")
        readiness = str(observation.get("runtime_readiness", "") or "")
        active = readiness == "active_runtime_observed"
        message = (
            f"OMH plugin active runtime observed by {host} ({event}, session={session_id})"
            if active
            else f"OMH plugin historical runtime event observed by {host} ({event}, session={session_id}); active readiness requires one of {', '.join(PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS)}"
        )
        return _capability("plugin_runtime_observed", "available", evidence, message)
    if observation:
        host = str(observation.get("host", "unknown") or "unknown")
        status = str(observation.get("status", "unknown") or "unknown")
        event = str(observation.get("event", "unknown") or "unknown")
        return _capability(
            "plugin_runtime_observed",
            "unverified",
            evidence,
            f"Latest plugin host observation from {host} is {status} ({event}); Hermes plugin runtime is not currently observed",
        )
    return _capability(
        "plugin_runtime_observed",
        "unverified",
        evidence,
        "No host-supplied plugin observation is inferred by the standalone probe fallback",
    )


def _capability(name: str, status: str, evidence: str, message: str) -> dict[str, str]:
    return {
        "name": name,
        "status": status,
        "evidence": evidence,
        "message": message,
    }


def _capability_status(capabilities: list[dict[str, str]], name: str) -> str:
    for capability in capabilities:
        if capability.get("name") == name:
            return str(capability.get("status") or "unknown")
    return "unknown"


def _target_message(target_topology: dict[str, Any]) -> str:
    mode = str(target_topology.get("mode", "unknown") or "unknown")
    active = str(target_topology.get("active_agent_count", "unknown") or "unknown")
    return f"Target topology from local registry: mode={mode}; active_agent_count={active}"


def _status(capabilities: dict[str, dict[str, Any]], name: str) -> str:
    return str(capabilities.get(name, {}).get("status", "unknown"))


def _gap(
    capabilities: dict[str, dict[str, Any]],
    name: str,
    *,
    category: str,
    severity: str,
) -> dict[str, Any]:
    capability = capabilities.get(name, {})
    return {
        "capability": name,
        "category": category,
        "severity": severity,
        "status": str(capability.get("status", "unknown")),
        "message": str(capability.get("message", "")),
        "evidence": str(capability.get("evidence", "")),
    }
