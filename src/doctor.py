from __future__ import annotations

from dataclasses import dataclass

from .config_adapter import external_dirs, read_config
from .hashutil import sha256_file
from .local_store import can_write_dir
from .manifest import local_modifications, read_manifest
from .paths import OmhPaths
from .plugin_pack import inspect_plugin_bundle
from .runtime.artifacts import read_state, read_state_error
from .skill_pack import CORE_SKILLS
from .workflow_state import list_workflow_states


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    message: str


def run_doctor(paths: OmhPaths) -> list[Check]:
    checks: list[Check] = []
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
    plugin = inspect_plugin_bundle(paths)
    plugin_expected = bool(plugin["plugin_dir_installed"]) or bool(state and state.get("last_plugin_distribution"))
    if not plugin_expected:
        checks.append(Check("plugin_bundle", True, f"optional OMHM plugin is not installed at {paths.hermes_plugin_dir}"))
    else:
        checks.extend(
            [
                Check("plugin_bundle", bool(plugin["plugin_dir_installed"]), f"{paths.hermes_plugin_dir}"),
                Check("plugin_manifest", bool(plugin["plugin_manifest_valid"]), str(plugin["plugin_manifest_path"])),
                Check(
                    "plugin_import_smoke",
                    bool(plugin["plugin_import_smoke"]),
                    "installed plugin imports without side effects" if plugin["plugin_import_smoke"] else "; ".join(plugin["errors"]),
                ),
                Check(
                    "plugin_register_smoke",
                    bool(plugin["plugin_register_smoke"]),
                    (
                        f"registered tools={plugin['registered_tools']} hooks={plugin['registered_hooks']}"
                        if plugin["plugin_register_smoke"]
                        else "; ".join(plugin["errors"])
                    ),
                ),
                Check(
                    "plugin_runtime_observed",
                    True,
                    "not required for doctor; Hermes runtime load/use must be observed separately before claiming native runtime readiness",
                ),
            ]
        )
    return checks


def doctor_ok(checks: list[Check]) -> bool:
    return all(check.ok for check in checks)
