from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command_path import inspect_omh_command_path
from .config_adapter import external_dirs, read_config
from .hashutil import sha256_file
from .local_store import can_write_dir
from .manifest import local_modifications, read_manifest
from .paths import OmhPaths
from .plugin_observations import (
    PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS,
    latest_plugin_host_observation,
    plugin_host_runtime_readiness,
)
from .plugin_pack import inspect_plugin_bundle
from .runtime.artifacts import read_state, read_state_error
from .skill_pack import CORE_SKILLS
from .targets import read_target_registry_result, summarize_target_registry
from .workflow_state import list_workflow_states

WARNING_NEXT_ACTION_PRIORITY = {
    # These warnings often block first-run usability even when the local OMH
    # health checks are otherwise OK. Lower-priority warnings stay visible in
    # the check list without replacing the beginner next action.
    "command_path": 100,
    "target_topology": 80,
}
DEFAULT_DOCTOR_NEXT_ACTION = "Open Hermes Agent and try: Use OMH request-to-handoff for: I want to safely add a feature to this repo."


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    message: str
    severity: str = "auto"
    remediation: str = ""
    next_action: str = ""
    observed: bool = True

    def __post_init__(self) -> None:
        if self.severity == "auto":
            object.__setattr__(self, "severity", "ok" if self.ok else "blocking")
        if not self.ok and not self.remediation:
            object.__setattr__(self, "remediation", _default_remediation(self.name))
        if not self.ok and not self.next_action:
            object.__setattr__(self, "next_action", _default_next_action(self.name))


def run_doctor(paths: OmhPaths) -> list[Check]:
    checks: list[Check] = []
    command_path = inspect_omh_command_path()
    checks.append(
        Check(
            "command_path",
            True,
            str(command_path["message"]),
            severity="ok" if command_path["found"] else "warning",
            next_action=str(command_path["next_action"]),
            observed=bool(command_path["observed"]),
        )
    )
    manifest = read_manifest(paths.manifest_path)
    state_error = read_state_error(paths)
    state = None if state_error else read_state(paths)
    checks.append(Check("manifest", manifest is not None, f"{paths.manifest_path}"))
    if manifest:
        manifest_skills_dir = manifest.get("skills_dir")
        checks.append(
            Check(
                "manifest_skills_dir",
                manifest_skills_dir == str(paths.skills_dir),
                f"manifest skills_dir={manifest_skills_dir!r}; expected {paths.skills_dir}",
            )
        )
        modified = local_modifications(manifest, paths.skills_dir)
        checks.append(
            Check(
                "local_modifications",
                not modified,
                "managed files match manifest" if not modified else f"changed managed files: {', '.join(modified)}",
            )
        )
    checks.append(Check("skills_dir", paths.skills_dir.exists(), f"{paths.skills_dir}"))
    runtime_writable = can_write_dir(paths.runtime_dir, probe_name=".doctor-write-test")
    checks.append(Check("runtime_artifacts", runtime_writable, f"{paths.runtime_dir} writable"))
    workflow_state_writable = can_write_dir(paths.workflow_state_dir, probe_name=".doctor-write-test")
    states, state_errors = list_workflow_states(paths)
    checks.append(
        Check(
            "workflow_state",
            workflow_state_writable and not state_errors,
            (
                f"{paths.workflow_state_dir} writable; {len(states)} workflow state file(s) readable"
                if workflow_state_writable and not state_errors
                else f"{paths.workflow_state_dir} has unreadable state: {state_errors}"
            ),
        )
    )
    if state_error:
        checks.append(Check("runtime_state", False, f"runtime state unreadable: {state_error}"))
    if manifest and state:
        checks.append(
            Check(
                "runtime_state",
                state.get("manifest_sha256") in {None, sha256_file(paths.manifest_path)},
                "runtime state matches manifest hash" if state.get("manifest_sha256") in {None, sha256_file(paths.manifest_path)} else "runtime state manifest hash is stale",
            )
        )
    for skill in CORE_SKILLS:
        path = paths.skills_dir / skill / "SKILL.md"
        checks.append(Check(f"skill:{skill}", path.exists(), str(path)))
    config_text = read_config(paths.hermes_config_path)
    dirs = external_dirs(config_text)
    checks.append(Check("hermes_config", paths.hermes_config_path.exists(), f"{paths.hermes_config_path}"))
    external_registered = str(paths.skills_dir) in dirs
    checks.append(Check("external_dir", external_registered, f"{paths.skills_dir} in skills.external_dirs"))
    checks.append(
        Check(
            "runtime_context",
            external_registered,
            (
                f"Hermes config {paths.hermes_config_path} points at {paths.skills_dir}; "
                "for a bot or hosted runtime, run doctor with the same --hermes-home used by that process"
            )
            if external_registered
            else (
                f"{paths.skills_dir} is not registered in {paths.hermes_config_path}; "
                "run `omh apply`, or pass --hermes-home matching the Hermes or bot runtime"
            ),
        )
    )
    target_registry, target_registry_error = read_target_registry_result(paths)
    target_topology = summarize_target_registry(paths)
    if target_registry_error:
        checks.append(Check("target_registry", False, f"target registry unreadable: {target_registry_error}"))
    else:
        known_count = int(target_topology.get("known_target_count") or 0)
        active_count = int(target_topology.get("active_agent_count") or 0)
        mode = str(target_topology.get("mode", "unknown"))
        if target_registry:
            checks.append(
                Check(
                    "target_registry",
                    True,
                    f"{known_count} known Hermes target(s); active_agent_count={active_count}; mode={mode}",
                )
            )
        else:
            checks.append(
                Check(
                    "target_registry",
                    True,
                    "no target registry yet; `omh setup` or wrapper target metadata will create it when needed",
                    observed=False,
                )
            )
    checks.append(
        Check(
            "target_topology",
            target_topology.get("status") != "unreadable",
            (
                f"mode={target_topology.get('mode')}; transition={target_topology.get('transition')}; "
                f"skill_scope_awareness={target_topology.get('requires_skill_scope_awareness')}"
            ),
            severity="warning" if target_topology.get("requires_skill_scope_awareness") else "auto",
            observed=target_topology.get("status") == "available",
        )
    )
    plugin = inspect_plugin_bundle(paths)
    latest_plugin_observation, plugin_observation_errors = latest_plugin_host_observation(paths)
    latest_plugin_readiness = ""
    if latest_plugin_observation:
        latest_plugin_readiness = str(
            latest_plugin_observation.get("runtime_readiness")
            or plugin_host_runtime_readiness(
                event=str(latest_plugin_observation.get("event", "")),
                status=str(latest_plugin_observation.get("status", "")),
            )
        )
    latest_plugin_active = latest_plugin_readiness == "active_runtime_observed"
    plugin_expected = bool(plugin["plugin_dir_installed"]) or bool(state and state.get("last_plugin_distribution"))
    if not plugin_expected:
        checks.append(Check("plugin_bundle", True, f"managed OMH plugin bridge is not installed yet at {paths.hermes_plugin_dir}"))
    else:
        checks.extend(
            [
                Check("plugin_bundle", bool(plugin["plugin_dir_installed"]), f"{paths.hermes_plugin_dir}"),
                Check("plugin_manifest", bool(plugin["plugin_manifest_valid"]), str(plugin["plugin_manifest_path"])),
                Check(
                    "plugin_bundle_current",
                    bool(plugin["plugin_manifest_current"]),
                    (
                        "installed plugin bundle matches the current OMH package"
                        if plugin["plugin_manifest_current"]
                        else _plugin_bridge_message(plugin)
                    ),
                    remediation="" if plugin["plugin_manifest_current"] else _plugin_bridge_remediation(plugin),
                    next_action="" if plugin["plugin_manifest_current"] else _plugin_bridge_next_action(plugin),
                ),
                Check(
                    "plugin_import_smoke",
                    bool(plugin["plugin_import_smoke"]),
                    "installed plugin imports without side effects" if plugin["plugin_import_smoke"] else "; ".join(plugin["errors"]),
                    remediation="" if plugin["plugin_import_smoke"] else _plugin_bridge_remediation(plugin),
                    next_action="" if plugin["plugin_import_smoke"] else _plugin_bridge_next_action(plugin),
                ),
                Check(
                    "plugin_register_smoke",
                    bool(plugin["plugin_register_smoke"]),
                    (
                        f"registered tools={plugin['registered_tools']} hooks={plugin['registered_hooks']}"
                        if plugin["plugin_register_smoke"]
                        else _plugin_bridge_message(plugin)
                    ),
                    remediation="" if plugin["plugin_register_smoke"] else _plugin_bridge_remediation(plugin),
                    next_action="" if plugin["plugin_register_smoke"] else _plugin_bridge_next_action(plugin),
                ),
                Check(
                    "plugin_runtime_observed",
                    True,
                    (
                        f"{latest_plugin_readiness} by {latest_plugin_observation.get('host', 'unknown')} "
                        f"({latest_plugin_observation.get('event', 'unknown')}, "
                        f"session={latest_plugin_observation.get('session_id', 'unknown')})"
                        if latest_plugin_observation and latest_plugin_observation.get("observed")
                        else (
                            f"plugin observation ledger unreadable: {'; '.join(plugin_observation_errors[:3])}"
                            if plugin_observation_errors
                            else (
                                f"latest plugin host observation is {latest_plugin_observation.get('status', 'unknown')}; "
                                "Hermes runtime load/use is not currently observed"
                                if latest_plugin_observation
                                else "not required for doctor; Hermes runtime load/use must be observed separately before claiming native runtime readiness"
                            )
                        )
                    ),
                    severity="ok" if latest_plugin_active else "warning",
                    next_action=(
                        ""
                        if latest_plugin_active
                        else (
                            "Record an active Hermes plugin event "
                            f"({', '.join(PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS)}) before claiming native runtime readiness."
                        )
                    ),
                    observed=bool(latest_plugin_observation and latest_plugin_observation.get("observed")),
                ),
            ]
        )
    profile_installs = state.get("last_team_profile_install") if isinstance(state, dict) else None
    if not profile_installs:
        checks.append(Check("team_profile_packs", True, f"optional OMH team profile packs are not installed at {paths.hermes_agents_dir}"))
    else:
        expected_files: list[str] = []
        if isinstance(profile_installs, list):
            for install in profile_installs:
                if isinstance(install, dict) and isinstance(install.get("files"), list):
                    expected_files.extend(str(item) for item in install["files"])
        missing = [path for path in expected_files if not Path(path).exists()]
        checks.append(
            Check(
                "team_profile_packs",
                not missing,
                (
                    f"{len(expected_files)} optional team profile file(s) installed under {paths.hermes_agents_dir}"
                    if not missing
                    else f"missing optional team profile files: {', '.join(missing)}"
                ),
            )
        )
    return checks


def doctor_ok(checks: list[Check]) -> bool:
    return all(check.ok for check in checks)


def recommended_next_action(checks: list[Check]) -> str:
    for check in checks:
        if not check.ok and check.severity == "blocking":
            return check.next_action or check.remediation
    prioritized_warnings = sorted(
        (
            check
            for check in checks
            if check.severity == "warning" and check.next_action and WARNING_NEXT_ACTION_PRIORITY.get(check.name, 0) > 0
        ),
        key=lambda check: WARNING_NEXT_ACTION_PRIORITY[check.name],
        reverse=True,
    )
    if prioritized_warnings:
        return prioritized_warnings[0].next_action
    return DEFAULT_DOCTOR_NEXT_ACTION


def _plugin_bridge_message(plugin: dict) -> str:
    errors = [str(item) for item in plugin.get("errors", []) if str(item)]
    if errors:
        return "; ".join(errors)
    missing_tools = [str(item) for item in plugin.get("missing_registered_tools", [])]
    missing_hooks = [str(item) for item in plugin.get("missing_registered_hooks", [])]
    if missing_tools or missing_hooks:
        details: list[str] = []
        if missing_tools:
            details.append(f"missing tools={missing_tools}")
        if missing_hooks:
            details.append(f"missing hooks={missing_hooks}")
        return "plugin register smoke is incomplete: " + "; ".join(details)
    return "managed plugin bridge is installed but did not pass local import/register smoke"


def _plugin_bridge_remediation(plugin: dict) -> str:
    if plugin.get("plugin_bundle_stale"):
        return "Run `omh setup` to refresh the managed plugin bridge from the current OMH package."
    return "Run `omh setup`; use `omh setup --force` only if replacing local plugin edits is intended."


def _plugin_bridge_next_action(plugin: dict) -> str:
    if plugin.get("plugin_bundle_stale"):
        return "Run `omh setup`, then `omh doctor` again."
    return "Run `omh setup --force`, then `omh doctor` again."


def _default_remediation(name: str) -> str:
    if name == "external_dir" or name == "runtime_context":
        return "Run `omh setup` or `omh apply` with the same --hermes-home used by the Hermes or wrapper runtime."
    if name.startswith("skill:") or name in {"manifest", "manifest_skills_dir", "skills_dir"}:
        return "Run `omh setup` to install the managed skill pack, or reinstall with `omh install --force` if managed files drifted."
    if name == "local_modifications":
        return "Review local edits under the managed skill directory, then run `omh install --force` only if replacing managed files is intended."
    if name in {"runtime_artifacts", "workflow_state", "runtime_state"}:
        return "Repair the local OMH runtime directory or rerun with an --omh-home path that can store metadata-only artifacts."
    if name.startswith("plugin_"):
        return "Run `omh setup` to reinstall the managed plugin bridge, or `omh setup --force` if replacing local plugin edits is intended."
    if name.startswith("target_"):
        return "Repair the OMH target registry or rerun `omh setup` with the Hermes home used by the wrapper runtime."
    if name == "hermes_config":
        return "Run `omh setup` to create or update the Hermes configuration for managed skill discovery."
    return "Run `omh doctor` after repairing the reported path or configuration."


def _default_next_action(name: str) -> str:
    if name == "external_dir" or name == "runtime_context":
        return "Run `omh setup`, then restart or refresh Hermes Agent so it can reload the registered skill directory."
    if name == "local_modifications":
        return "Inspect changed managed skill files; use `omh install --force` only when replacing those edits is acceptable."
    if name.startswith("skill:") or name in {"manifest", "manifest_skills_dir", "skills_dir", "hermes_config"}:
        return "Run `omh setup`, then `omh doctor` again."
    if name.startswith("plugin_"):
        return "Run `omh setup --force`, then `omh doctor` again."
    if name.startswith("target_"):
        return "Run `omh setup` for the current Hermes target, then rerun `omh doctor`."
    if name in {"runtime_artifacts", "workflow_state", "runtime_state"}:
        return "Fix the OMH runtime path or choose a writable --omh-home, then rerun `omh doctor`."
    return "Fix the reported check and rerun `omh doctor`."
