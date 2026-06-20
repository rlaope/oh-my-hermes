from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config_adapter import external_dirs, read_config
from .local_store import read_jsonl_objects
from .parity import build_parity_matrix
from .paths import OmhPaths
from .plugin_observations import (
    PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS,
    PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION,
    plugin_host_runtime_readiness,
    read_plugin_host_observations,
)
from .plugin_pack import inspect_plugin_bundle
from .runtime.artifacts import read_state_result
from .targets import summarize_target_registry
from .team_readiness import build_team_worker_readiness

PROBE_STATUSES = ("available", "missing", "unknown", "unverified")
MCP_HOST_SESSION_SCHEMA_VERSION = "omh_mcp_host_session/v1"


@dataclass(frozen=True)
class Capability:
    name: str
    status: str
    evidence: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "evidence": self.evidence,
            "message": self.message,
        }


def _has_file(path: Path) -> bool:
    return path.exists() and path.is_file()


def _has_dir(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _wrapper_artifacts(paths: OmhPaths) -> list[Path]:
    if not paths.runtime_runs_dir.exists():
        return []
    return sorted(paths.runtime_runs_dir.glob("*/wrapper.json"))


def _has_any_file(paths: list[Path]) -> bool:
    return any(_has_file(path) for path in paths)


def _marker_capability(name: str, markers: list[Path], found_message: str, missing_message: str) -> Capability:
    found = _has_any_file(markers)
    return Capability(
        name,
        "unverified" if found else "unknown",
        ", ".join(str(path) for path in markers),
        found_message if found else missing_message,
    )


def _mcp_preference_capability(paths: OmhPaths) -> Capability:
    state, error = read_state_result(paths)
    evidence = str(paths.runtime_state_path)
    if error:
        return Capability(
            "mcp_preference",
            "unknown",
            evidence,
            f"Could not read OMH setup state for MCP preference: {error}",
        )
    if not isinstance(state, dict):
        return Capability(
            "mcp_preference",
            "unknown",
            evidence,
            "No OMH setup state has recorded an MCP bridge preference",
        )
    last_setup = state.get("last_setup")
    mcp_setup = last_setup.get("mcp_setup") if isinstance(last_setup, dict) else None
    if not isinstance(mcp_setup, dict):
        return Capability(
            "mcp_preference",
            "unknown",
            evidence,
            "No OMH setup state has recorded an MCP bridge preference",
        )

    mode = str(mcp_setup.get("mode", "none"))
    requested = bool(mcp_setup.get("requested", False))
    observed = bool(mcp_setup.get("observed", False))
    if not requested or mode == "none":
        return Capability(
            "mcp_preference",
            "unknown",
            evidence,
            "OMH setup state says no optional MCP bridge preference was requested",
        )
    if observed:
        return Capability(
            "mcp_preference",
            "available",
            evidence,
            f"OMH MCP bridge preference was requested and observed by setup state (mode={mode})",
        )
    return Capability(
        "mcp_preference",
        "unverified",
        evidence,
        f"OMH MCP bridge preference was requested (mode={mode}), but no MCP host session or tool-call evidence is recorded",
    )


def _mcp_bridge_server_capability() -> Capability:
    return Capability(
        "mcp_bridge_server",
        "available",
        "omh mcp manifest; omh mcp serve",
        "OMH ships an allowlisted stdio MCP bridge with omh_status, omh_recommend, and omh_probe tools",
    )


def _worktree_creator_capability() -> Capability:
    return Capability(
        "worktree_creator",
        "available",
        "omh worktree prepare; omh worktree list; omh worktree bind",
        (
            "OMH can explicitly create local Git worktrees, record omh_worktree_observation/v1 "
            "workspace-isolation evidence, and return wrapper binding recipes for opening or attaching "
            "the selected coding agent without launching it"
        ),
    )


def _team_worker_readiness_capability(paths: OmhPaths) -> tuple[Capability, dict]:
    readiness = build_team_worker_readiness(paths)
    status = str(readiness.get("status", "missing"))
    presentation_status = str(readiness.get("presentation_status", "unknown"))
    hermes_visibility = str(readiness.get("hermes_visibility_status", "unknown"))
    observed_runtime = readiness.get("observed_runtime", {})
    observed_status = (
        str(observed_runtime.get("status", "not_observed"))
        if isinstance(observed_runtime, dict)
        else "not_observed"
    )
    if status == "available":
        message = (
            "OMH ships team/swarm worker contract readiness, wrapper actions, and runtime observation ledger support; "
            f"presentation={presentation_status}, Hermes visibility={hermes_visibility}, observed runtime={observed_status}"
        )
        capability_status = "available"
    else:
        message = "OMH team/swarm worker contract readiness is missing required local workflow surfaces"
        capability_status = "missing"
    return (
        Capability(
            "team_worker_readiness",
            capability_status,
            "omh runtime team-readiness",
            message,
        ),
        readiness,
    )


def _mcp_bridge_runtime_capability(paths: OmhPaths) -> Capability:
    state, error = read_state_result(paths)
    evidence = str(paths.runtime_state_path)
    if error:
        return Capability(
            "mcp_bridge_runtime",
            "unknown",
            evidence,
            f"Could not read OMH MCP bridge runtime observation state: {error}",
        )
    bridge = state.get("last_mcp_bridge") if isinstance(state, dict) else None
    if not isinstance(bridge, dict) or not bridge.get("observed"):
        return Capability(
            "mcp_bridge_runtime",
            "unverified",
            evidence,
            "No OMH MCP bridge tool call has been observed in local OMH state",
        )
    tool = str(bridge.get("tool", "unknown"))
    return Capability(
        "mcp_bridge_runtime",
        "available",
        evidence,
        f"OMH MCP bridge observed a local tool call ({tool}); host-specific load evidence remains separate",
    )


def _mcp_host_session_capability(paths: OmhPaths) -> Capability:
    records, errors = read_jsonl_objects(paths.runtime_mcp_host_sessions_path)
    evidence = str(paths.runtime_mcp_host_sessions_path)
    if errors:
        return Capability(
            "mcp_host_session",
            "unknown",
            evidence,
            f"Could not read OMH MCP host session observations: {'; '.join(errors[:3])}",
        )
    latest_observed = next(
        (
            record
            for record in reversed(records)
            if record.get("schema_version") == MCP_HOST_SESSION_SCHEMA_VERSION and record.get("observed")
        ),
        None,
    )
    if latest_observed:
        host = str(latest_observed.get("host", "unknown"))
        event = str(latest_observed.get("event", "unknown"))
        session_id = str(latest_observed.get("session_id", "unknown"))
        return Capability(
            "mcp_host_session",
            "available",
            evidence,
            f"MCP host session observed by {host} ({event}, session={session_id})",
        )
    if records:
        return Capability(
            "mcp_host_session",
            "unverified",
            evidence,
            "MCP host session records exist, but none record observed host load or use",
        )
    return Capability(
        "mcp_host_session",
        "unverified",
        evidence,
        "No MCP host load or session observation has been recorded by a host or wrapper",
    )


def _plugin_runtime_observed_capability(paths: OmhPaths) -> tuple[Capability, bool, bool]:
    records, errors = read_plugin_host_observations(paths, limit=None)
    evidence = str(paths.runtime_plugin_host_observations_path)
    if errors:
        return (
            Capability(
                "plugin_runtime_observed",
                "unknown",
                evidence,
                f"Could not read OMH plugin host observations: {'; '.join(errors[:3])}",
            ),
            False,
            False,
        )
    latest = next(
        (
            record
            for record in records
            if record.get("schema_version") == PLUGIN_HOST_OBSERVATION_SCHEMA_VERSION
        ),
        None,
    )
    if latest and latest.get("observed"):
        host = str(latest.get("host", "unknown"))
        event = str(latest.get("event", "unknown"))
        session_id = str(latest.get("session_id", "unknown"))
        readiness = str(latest.get("runtime_readiness") or plugin_host_runtime_readiness(event=event, status="observed"))
        active = readiness == "active_runtime_observed"
        return (
            Capability(
                "plugin_runtime_observed",
                "available",
                evidence,
                (
                    f"OMH plugin active runtime observed by {host} ({event}, session={session_id})"
                    if active
                    else f"OMH plugin historical runtime event observed by {host} ({event}, session={session_id}); active readiness requires one of {', '.join(PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS)}"
                ),
            ),
            True,
            active,
        )
    if latest:
        host = str(latest.get("host", "unknown"))
        status = str(latest.get("status", "unknown"))
        event = str(latest.get("event", "unknown"))
        return (
            Capability(
                "plugin_runtime_observed",
                "unverified",
                evidence,
                f"Latest plugin host observation from {host} is {status} ({event}); Hermes plugin runtime is not currently observed",
            ),
            False,
            False,
        )
    return (
        Capability(
            "plugin_runtime_observed",
            "unverified",
            evidence,
            "No Hermes runtime load/use observation is recorded; local install smoke is not native runtime evidence",
        ),
        False,
        False,
    )


def _dir_capability(name: str, path: Path, found_message: str, missing_message: str) -> Capability:
    found = _has_dir(path)
    return Capability(
        name,
        "unverified" if found else "unknown",
        str(path),
        found_message if found else missing_message,
    )


def probe_capabilities(paths: OmhPaths, *, include_parity: bool = False) -> dict:
    config_text = read_config(paths.hermes_config_path)
    configured_dirs = external_dirs(config_text)
    skills_registered = str(paths.skills_dir) in configured_dirs
    capabilities: list[Capability] = []
    managed_skill_path = paths.skills_dir / "oh-my-hermes" / "SKILL.md"

    capabilities.append(
        Capability(
            "external_skill_dirs",
            "available" if skills_registered else ("missing" if paths.hermes_config_path.exists() else "unknown"),
            str(paths.hermes_config_path),
            "Hermes config registers the managed skill directory" if skills_registered else "Managed skill directory is not registered in this Hermes config",
        )
    )
    capabilities.append(
        Capability(
            "managed_skills",
            "available" if _has_file(managed_skill_path) else "missing",
            str(paths.skills_dir),
            "Managed oh-my-hermes skill is installed" if _has_file(managed_skill_path) else "Managed skills are not installed",
        )
    )
    hooks_markers = [paths.hermes_home / "hooks.yaml", paths.hermes_home / "hooks.json"]
    capabilities.append(
        _marker_capability(
            "native_hooks",
            hooks_markers,
            "Hook-like files exist, but omh has no stable Hermes hook contract to claim native integration",
            "No stable Hermes hook surface detected by file probe",
        )
    )
    capabilities.append(
        _dir_capability(
            "plugin_bundles",
            paths.hermes_home / "plugins",
            "Plugin directory exists, but omh has no stable Hermes plugin bundle contract",
            "No Hermes plugin directory detected by file probe",
        )
    )
    capabilities.append(
        _dir_capability(
            "apps",
            paths.hermes_home / "apps",
            "Apps directory exists, but omh has no stable Hermes app contract",
            "No Hermes app directory detected by file probe",
        )
    )
    mcp_markers = [paths.hermes_home / ".mcp.json", paths.hermes_home / "mcp.json"]
    team_worker_readiness_capability, team_worker_readiness = _team_worker_readiness_capability(paths)
    capabilities.append(_mcp_preference_capability(paths))
    capabilities.append(_mcp_bridge_server_capability())
    capabilities.append(team_worker_readiness_capability)
    capabilities.append(_worktree_creator_capability())
    capabilities.append(_mcp_bridge_runtime_capability(paths))
    mcp_host_session = _mcp_host_session_capability(paths)
    capabilities.append(mcp_host_session)
    capabilities.append(
        _marker_capability(
            "mcp_host_config",
            mcp_markers,
            "MCP host config exists, but OMH has not verified a Hermes MCP extension contract or host load event",
            "No Hermes MCP host config detected by file probe",
        )
    )
    capabilities.append(
        Capability(
            "native_skill_metadata",
            "unknown",
            str(paths.hermes_config_path),
            "No stable Hermes-native skill metadata contract is known to omh yet",
        )
    )
    wrappers = _wrapper_artifacts(paths)
    plugin = inspect_plugin_bundle(paths)
    plugin_runtime_capability, plugin_runtime_observed, plugin_runtime_active = _plugin_runtime_observed_capability(paths)
    plugins_dir_exists = _has_dir(paths.hermes_plugins_dir)
    capabilities.extend(
        [
            Capability(
                "plugin_dir_exists",
                "available" if plugins_dir_exists else "unknown",
                str(paths.hermes_plugins_dir),
                "Hermes plugin directory exists" if plugins_dir_exists else "No Hermes plugin directory detected by file probe",
            ),
            Capability(
                "omh_plugin_bundle",
                "available" if plugin["plugin_dir_installed"] else "missing",
                str(paths.hermes_plugin_dir),
                "Managed OMH plugin bundle is installed" if plugin["plugin_dir_installed"] else "Managed OMH plugin bundle is not installed",
            ),
            Capability(
                "plugin_import_smoke",
                "available" if plugin["plugin_import_smoke"] else ("missing" if plugin["plugin_dir_installed"] else "unknown"),
                str(paths.hermes_plugin_dir / "__init__.py"),
                "Installed OMH plugin imports locally" if plugin["plugin_import_smoke"] else "Installed OMH plugin has not passed local import smoke",
            ),
            Capability(
                "plugin_register_smoke",
                "available" if plugin["plugin_register_smoke"] else ("missing" if plugin["plugin_dir_installed"] else "unknown"),
                str(paths.hermes_plugin_dir),
                (
                    f"Installed OMH plugin registers tools={plugin['registered_tools']} hooks={plugin['registered_hooks']}"
                    if plugin["plugin_register_smoke"]
                    else "Installed OMH plugin has not passed fake Hermes register smoke"
                ),
            ),
            plugin_runtime_capability,
        ]
    )
    capabilities.append(
        Capability(
            "wrapper_metadata",
            "available" if wrappers else "missing",
            ", ".join(str(path) for path in wrappers[:5]) if wrappers else str(paths.runtime_runs_dir),
            "Wrapper observation artifacts are present" if wrappers else "No wrapper observation artifacts recorded yet",
        )
    )
    target_topology = summarize_target_registry(paths)
    capabilities.extend(
        [
            Capability(
                "target_registry",
                "available" if target_topology["status"] == "available" else ("missing" if target_topology["status"] == "missing" else "unknown"),
                str(paths.target_registry_path),
                (
                    f"{target_topology['known_target_count']} Hermes target(s) known"
                    if target_topology["status"] == "available"
                    else "No OMH target registry has been recorded yet"
                ),
            ),
            Capability(
                "target_topology",
                "available" if target_topology["mode"] in {"single_agent_target", "multi_agent_targets"} else "unknown",
                str(paths.target_registry_path),
                f"mode={target_topology['mode']}; active_agent_count={target_topology['active_agent_count']}; transition={target_topology['transition']}",
            ),
        ]
    )

    payload = {
        "schema_version": 1,
        "omh_home": str(paths.omh_home),
        "hermes_home": str(paths.hermes_home),
        "capabilities": [capability.to_dict() for capability in capabilities],
        "target_topology": target_topology,
        "plugin_distribution_ready": bool(plugin["plugin_distribution_ready"]),
        "plugin_runtime_observed": plugin_runtime_observed,
        "plugin_runtime_active": plugin_runtime_active,
        "mcp_host_session_observed": mcp_host_session.status == "available",
        "team_worker_readiness_ready": team_worker_readiness_capability.status == "available",
        "team_worker_presentation_status": str(team_worker_readiness.get("presentation_status", "unknown")),
        "team_worker_readiness": team_worker_readiness,
        "native_integration_claim_ready": bool(plugin["plugin_distribution_ready"]) and plugin_runtime_active,
        "claim_boundary": (
            "Prompt-level routing is the default unless a stable Hermes extension surface and host-supplied "
            "runtime evidence prove deeper integration. Plugin host observations prove plugin load/use only, "
            "not coding execution, review, CI, or merge."
        ),
    }
    if include_parity:
        payload["parity_matrix"] = build_parity_matrix(payload)
    return payload
