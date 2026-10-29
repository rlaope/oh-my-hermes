from __future__ import annotations
from ..skills.catalog import omh_skill_install_path

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

from .advisory import AdvisoryReport, run_config_advisories
from .structural_search import inspect_structural_search
from ..command_path import inspect_omh_command_path
from ..config_adapter import (
    external_dir_registered,
    external_dirs,
    memory_provider_selection,
    skill_create_dir_selection,
    plugin_enablement,
    plugin_enablement_is_readable,
    plugin_enablement_shape_error,
    plugin_is_enabled,
    plugin_load_timeout_setting,
    plugins_enabled_extension_error,
    read_config,
)
from ..hashutil import sha256_file, sha256_text
from ..local_store import can_write_dir, read_json_object
from ..install.guidance_projection import build_guidance_projection_status, catalog_revision
from ..install.hook_integrity import HOOK_HOST_TARGET, VALID_HOOK_EVENTS, build_hook_integrity_status
from ..install.curator_ledger import LedgerWrite, read_ledger_writes
from ..install.identity_conflicts import build_identity_conflict_report, skill_conflict_outcome
from ..install.installer import (
    DEFAULT_SKILL_PROFILE,
    SKILL_PROFILES,
    hermes_edited_skills,
    installed_skill_directories,
    installed_skill_names,
    manifest_pack,
    missing_managed_skills,
    profile_skill_names,
)
from ..install.plugin_bundle_import_scan import describe_findings, scan_bundle_core_imports
from ..install.support_materialization import legacy_support_paths
from ..install.plugin_load_deadline import (
    ABANDONED_LOADER_CAP,
    LOAD_TIMEOUT_RECORDED,
    read_recorded_load_timeouts,
)
from ..install.plugin_loader_observation import observe_real_loader_registration, resolve_hermes_code_root
from ..install.skill_registration import (
    AMBIGUOUS_REGISTRATION_NEXT_ACTION,
    ambiguous_registration_message,
    external_dir_key,
    hermes_profile_dirs,
    managed_skill_dir_candidates,
    registered_managed_entries,
    registration_home_label,
)
from ..manifest import local_modifications, read_manifest
from ..core.errors import OmhError
from ..paths import (
    OmhPaths,
    managed_command_generations_dir,
    managed_command_self_update_state_path,
    managed_current_workflow_pack_dir,
)
from ..plugin_bundle.omh import runtime_paths
from ..plugin_bundle.omh.installed_skills import installed_skill_names as hint_installed_skill_names
from ..plugin_bundle.omh.installed_skills import skill_not_installed
from ..plugin_bundle.omh.memory_dreaming import read_dreaming_state, read_latest_consolidation
from ..workflows.memory import (
    _OPEN_MAX_DAYS,
    _cadence_value,
    _record_resolution,
    _record_staleness,
    _redacted_metadata_label,
    read_project_memory_policy,
    scan_project_memory_records,
)
from ..plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from ..plugin_bundle.omh.provider_detection import env_key_names
from ..plugin_observations import (
    PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS,
    latest_plugin_host_observation,
    plugin_host_runtime_readiness,
    read_plugin_host_observations,
)
from ..plugin_pack import PLUGIN_NAME, inspect_plugin_bundle
from ..install.plugin_pack import HERMES_PLUGIN_UPDATE_COMMAND, host_managed_plugin
from ..install.config_reversal import MANAGED_CONFIG_WRITES_STATE_KEY, PLUGIN_OMH_HOME_KEY, load_managed_config_writes
from ..runtime.artifacts import read_state, read_state_error
from ..skill_pack import CORE_SKILLS, builtin_skill_templates
from ..system.security_posture import SECURITY_POSTURE_ENV_VAR, STRICT_POSTURE, resolve_security_posture
from ..targets import read_target_registry_result, summarize_target_registry
from ..workflow_state import list_workflow_states

WARNING_NEXT_ACTION_PRIORITY = {
    # These warnings often block first-run usability even when the local OMH
    # health checks are otherwise OK. Lower-priority warnings stay visible in
    # the check list without replacing the beginner next action.
    "command_path": 100,
    # A home naming two managed skills directories has lost every OMH skill
    # by name (#1857); the row's `run \`omh update\`` is the headline action
    # too. Per-profile rows are named `external_dir_ambiguity:<profile>` and
    # read the same priority through `_warning_priority`.
    "external_dir_ambiguity": 90,
    "target_topology": 80,
    "awareness_delivery": 70,
}


def _warning_priority(name: str) -> int:
    """The promotion priority of a warning row, by its name or its `name:qualifier` prefix."""
    return WARNING_NEXT_ACTION_PRIORITY.get(name) or WARNING_NEXT_ACTION_PRIORITY.get(name.split(":", 1)[0], 0)
AWARENESS_ZERO_DELIVERY_WARNING_DAYS = 7
# How far back doctor looks in the plugin host observation journal for a hook
# call that did not come back observed. The same default the `omh plugin
# observations` reader uses, so the two surfaces answer over one window.
_HOOK_OBSERVATION_WINDOW = 20
# How many unread plugin directories the Jev posture check names inline before
# it reports the rest as a count. The `--json` payload always carries them all.
_JEV_SKIPPED_NAMED_LIMIT = 3
# The one sentence every Jev next action opens with, because the first step is
# the same whichever state made the check visible. Every sentence after it is
# printed only when the read that produced it happened -- see
# `_jev_next_action`.
_JEV_NEXT_ACTION_OPENING = (
    "Read the full posture with `omh doctor --json` and decide whether the named plugin should stay enabled."
)
# What a declaration OMH could not read costs, per field. Each says what is
# NOT established rather than naming the field and leaving the consequence to
# the reader: an unread `provides_hooks` is why a plugin can show an empty
# hook overlap and still be sharing one.
#
# Looked up with a fallback, never by indexing. The keys are a vocabulary
# another module owns, and a field added there must cost one generic clause in
# one note -- not a `KeyError` that takes the whole `omh doctor` command down.
# `tests/test_jev_sidekick_posture.py` pins that every field that vocabulary
# declares has a specific clause here, so the fallback stays unreached.
_JEV_UNREAD_DECLARATION_NOTES = {
    "name": "declares a name in a form OMH does not read, so it was not classified by name at all",
    "provides_tools": "declares tools in a form OMH does not read, so its Jev-class tools are not established",
    "provides_hooks": (
        "declares hooks in a form OMH does not read, so its hook overlap with the OMH bridge is not established"
    ),
}
DEFAULT_DOCTOR_NEXT_ACTION = "Open Hermes Agent and try: Use OMH request-to-handoff for: I want to safely add a feature to this repo."


@dataclass(frozen=True)
class Check:
    """One doctor finding, as `omh doctor` prints it and `--json` serializes it.

    `observed` stays a bool and keeps its one meaning -- whether this check
    reached the thing it describes -- because every reader of the JSON report
    treats it as one. A check whose finding is a structured payload rather
    than a sentence carries it in `detail`, which is `None` for every check
    that has none, so the sentence and the payload are never two spellings of
    the same field.
    """

    name: str
    ok: bool
    message: str
    severity: str = "auto"
    remediation: str = ""
    next_action: str = ""
    observed: bool = True
    detail: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.severity == "auto":
            object.__setattr__(self, "severity", "ok" if self.ok else "blocking")
        if not self.ok and not self.remediation:
            object.__setattr__(self, "remediation", _default_remediation(self.name))
        if not self.ok and not self.next_action:
            object.__setattr__(self, "next_action", _default_next_action(self.name))


def _writable_without_probe(path: Path) -> bool:
    """Whether the OS reports `path` (or the ancestor that would hold it) writable, without writing.

    The `--no-state-write` stand-in for `can_write_dir`: no directory is
    created and no probe file is written, so the answer is the permission
    bits' claim, not an observed write.
    """
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK)


def _dir_write_access(path: Path, *, state_write: bool) -> tuple[bool, str]:
    """The writability verdict for one OMH directory and the words that say how it was reached."""
    if state_write:
        return can_write_dir(path, probe_name=".doctor-write-test"), "writable"
    writable = _writable_without_probe(path)
    return writable, (
        "write access not probed (--no-state-write); "
        + ("permissions allow writing" if writable else "permissions do not allow writing")
    )


def run_doctor(paths: OmhPaths, *, state_write: bool = True) -> list[Check]:
    """Every doctor check, in report order.

    ``state_write=False`` replaces the two `.doctor-write-test` probe writes
    with a permission check that writes nothing under the OMH home; those two
    checks then report ``observed=False``.
    """
    checks: list[Check] = []
    # Read the pack where the installer reads it. On a host migrated from the
    # pre-pointer layout, the running bootstrap generation's `skills` is a
    # directory link to `<omh_home>/skills`, and the support reader refuses
    # every link component, so reading through the alias aborted the whole
    # report on exactly those hosts (#2378). A link the translation refuses
    # is reported here rather than raised.
    paths, skills_dir_link = _support_readable_paths(paths)
    if skills_dir_link is not None:
        checks.append(skills_dir_link)
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
    # Hermes' curator ledger, read once for every check below and cut to the
    # directories an OMH install may serve skills from.
    ledger_writes, ledger_unread = read_ledger_writes(paths.hermes_home, within=_managed_skill_roots(paths, manifest))
    # Judged once: it hashes every managed SKILL.md, and two checks below read it.
    hermes_edits = hermes_edited_skills(manifest, paths, writes=ledger_writes)
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
        # Neither a Hermes edit nor a removed skill refuses an install any
        # more: the installer keeps the first (`hermes_skill_edits`) and
        # renders the second again (`missing_managed_skills`), so both are
        # left out of the blocking local-modification count, whose
        # refuse-until-`--force` advice is for a hand edit.
        hermes_edited_paths = {str(item["path"]) for item in hermes_edits}
        missing = _missing_skills_on_next_install(paths, manifest)
        missing_paths = {str(item["path"]) for item in missing}
        try:
            modified = [
                rel
                for rel in local_modifications(manifest, paths.skills_dir)
                if rel not in hermes_edited_paths and rel not in missing_paths
            ]
        except OmhError as exc:
            # A support path the reader refuses (a link inside the pack, or a
            # bootstrap link it would not translate) is a finding about this
            # pack, not a reason to withhold every other check.
            checks.append(Check("local_modifications", False, f"managed files not compared: {exc}"))
        else:
            checks.append(
                Check(
                    "local_modifications",
                    not modified,
                    "managed files match manifest" if not modified else f"changed managed files: {', '.join(modified)}",
                )
            )
        checks.append(_skill_freshness_check(paths, manifest, exclude=hermes_edited_paths))
        if missing:
            checks.append(_missing_managed_skills_check(manifest, missing))
    checks.append(_hermes_skill_edits_check(hermes_edits, ledger_writes, ledger_unread))
    checks.append(Check("skills_dir", paths.skills_dir.exists(), f"{paths.skills_dir}"))
    checks.append(_route_hint_skills_check(paths))
    runtime_writable, runtime_access = _dir_write_access(paths.runtime_dir, state_write=state_write)
    checks.append(
        Check("runtime_artifacts", runtime_writable, f"{paths.runtime_dir} {runtime_access}", observed=state_write)
    )
    workflow_state_writable, workflow_access = _dir_write_access(paths.workflow_state_dir, state_write=state_write)
    states, state_errors = list_workflow_states(paths)
    checks.append(
        Check(
            "workflow_state",
            workflow_state_writable and not state_errors,
            (
                f"{paths.workflow_state_dir} {workflow_access}; {len(states)} workflow state file(s) readable"
                if workflow_state_writable and not state_errors
                else f"{paths.workflow_state_dir} has unreadable state: {state_errors}"
            ),
            observed=state_write,
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
        path = paths.skills_dir / omh_skill_install_path(skill) / "SKILL.md"
        checks.append(Check(f"skill:{skill}", path.exists(), str(path)))
    config_text = read_config(paths.hermes_config_path)
    dirs = external_dirs(config_text)
    hermes_config_present = paths.hermes_config_path.exists()
    checks.append(Check("hermes_config", hermes_config_present, f"{paths.hermes_config_path}"))
    # By text or by real path: the installer registers the `current` pointer,
    # the running command knows its generation, and both name this directory.
    external_registered = external_dir_registered(dirs, paths.skills_dir, hermes_home=paths.hermes_home)
    checks.append(Check("external_dir", external_registered, f"{paths.skills_dir} in skills.external_dirs"))
    # Both named with the `external_dir` prefix so the summary groups them
    # under Hermes registration beside the check above.
    checks.extend(_external_dir_ambiguity_checks(paths, config_text))
    checks.append(_external_dir_unregistered_copy_check(paths, config_text))
    # Named with the `hermes_config` prefix so the summary groups it under
    # Hermes registration. Setup refuses a `plugins.enabled` it cannot extend
    # before it installs the bundle, and the plugin checks below run only once
    # a bundle exists, so this is the one line that names that cause (#1825).
    checks.append(_plugins_enabled_extension_check(paths, config_text, hermes_config_present))
    # `None`, not `dirs`, when the config is absent: `read_config` returns "" for
    # a missing file, so an empty list there would read as "Hermes registers no
    # foreign directory" when the truth is that Hermes was never asked.
    checks.append(
        _identity_conflicts_check(paths, dirs if hermes_config_present else None, manifest, config_text=config_text)
    )
    checks.append(_memory_provider_check(config_text))
    checks.append(_memory_consolidation_check(paths))
    checks.append(_memory_record_readability_check(paths))
    checks.append(_memory_open_records_check(paths))
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
    checks.append(_guidance_projection_check(paths, manifest, registered=external_registered))
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
    manifest_conformance = plugin["plugin_manifest_conformance"]
    loader_observation = (
        observe_real_loader_registration(
            paths.hermes_plugin_dir,
            hermes_code_root=resolve_hermes_code_root(paths.hermes_home),
            omh_home=paths.omh_home,
        )
        if plugin["plugin_dir_installed"]
        else None
    )
    bundle_import_scan = scan_bundle_core_imports(paths.hermes_plugin_dir)
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
    host_managed = bool(plugin["plugin_host_managed"])
    plugin_expected = bool(plugin["plugin_dir_installed"]) or bool(state and state.get("last_plugin_distribution"))
    if not plugin_expected:
        checks.append(Check("plugin_bundle", True, f"managed OMH plugin bridge is not installed yet at {paths.hermes_plugin_dir}"))
    else:
        checks.extend(
            [
                Check("plugin_bundle", bool(plugin["plugin_dir_installed"]), f"{paths.hermes_plugin_dir}"),
                Check(
                    "plugin_manifest",
                    bool(plugin["plugin_manifest_valid"]) or host_managed,
                    _plugin_host_managed_message(plugin) if host_managed else str(plugin["plugin_manifest_path"]),
                ),
                Check(
                    "plugin_bundle_current",
                    bool(plugin["plugin_manifest_current"]) or host_managed,
                    (
                        _plugin_host_managed_message(plugin)
                        if host_managed
                        else "installed plugin bundle matches the current OMH package"
                        if plugin["plugin_manifest_current"]
                        else _plugin_bridge_message(plugin)
                    ),
                    remediation="" if plugin["plugin_manifest_current"] or host_managed else _plugin_bridge_remediation(plugin),
                    next_action="" if plugin["plugin_manifest_current"] or host_managed else _plugin_bridge_next_action(plugin),
                ),
                Check(
                    "plugin_import_smoke",
                    bool(plugin["plugin_import_smoke"]),
                    "installed plugin imports without side effects" if plugin["plugin_import_smoke"] else "; ".join(plugin["errors"]),
                    remediation="" if plugin["plugin_import_smoke"] else _plugin_bridge_remediation(plugin),
                    next_action="" if plugin["plugin_import_smoke"] else _plugin_bridge_next_action(plugin),
                ),
                Check(
                    "plugin_manifest_conformance",
                    bool(manifest_conformance["ok"]),
                    (
                        f"plugin.yaml declares kind={manifest_conformance['kind']} and "
                        f"tools={len(manifest_conformance['declared_tools'])} "
                        f"hooks={len(manifest_conformance['declared_hooks'])}; "
                        f"requires_hermes={manifest_conformance['declared_hermes_range']}"
                        if manifest_conformance["ok"]
                        else (
                            "plugin.yaml does not match the Hermes standalone loader contract: "
                            + ", ".join(manifest_conformance["invalid_fields"])
                        )
                    ),
                    remediation=(
                        ""
                        if manifest_conformance["ok"]
                        else "Run `omh setup --force` to restore the managed plugin manifest."
                    ),
                    next_action=(
                        ""
                        if manifest_conformance["ok"]
                        else "Run `omh setup --force`, then `omh doctor` again."
                    ),
                ),
                Check(
                    "plugin_register_smoke",
                    bool(plugin["plugin_register_smoke"]),
                    (
                        "register() callable with OMH's fake context: "
                        f"tools={plugin['registered_tools']} hooks={plugin['registered_hooks']}; "
                        "the real Hermes loader is checked separately"
                        if plugin["plugin_register_smoke"]
                        else _plugin_bridge_message(plugin)
                    ),
                    remediation="" if plugin["plugin_register_smoke"] else _plugin_bridge_remediation(plugin),
                    next_action="" if plugin["plugin_register_smoke"] else _plugin_bridge_next_action(plugin),
                ),
                _plugin_enforcement_check(plugin),
                _plugin_loader_observation_check(loader_observation),
                _plugin_load_deadline_check(paths, config_text),
                _plugin_bundle_import_scan_check(bundle_import_scan),
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
                _plugin_enabled_check(paths),
                _plugin_omh_home_binding_check(paths, config_text),
                *_profile_omh_home_binding_checks(paths),
                _plugin_desktop_half_check(paths),
                _awareness_delivery_check(paths),
            ]
        )
    from ..plugin_bundle.omh.group_activity_status import read_group_activity_status
    activity = read_group_activity_status(paths.omh_home, paths.hermes_home)
    checks.append(Check(
        "group_chat_activity", True,
        f"Last profile snapshot: readiness={activity['readiness']}; compatibility={activity['compatibility']}; "
        f"last_outcome={activity['last_outcome']}; dropped={activity['dropped']}; gapped={activity['gapped']}; "
        f"rejected={activity['rejected']}; write_failed={activity['write_failed']}. "
        "Native member activity has no room-terminal guarantee; receipts remain partial.",
        severity="warning" if activity["readiness"] == "unavailable" else "ok", observed=False,
    ))
    checks.append(_hook_integrity_check(paths))
    checks.extend(_toolcall_rule_checks(paths))
    checks.extend(_plugin_hook_error_checks(paths))
    checks.append(_retired_skill_install_check(paths))
    checks.append(_flat_skill_layout_check(paths))
    checks.append(_plugin_ulw_lifecycle_check(paths))
    checks.append(_omh_tui_check(paths))
    checks.append(_delegation_protocol_platform_check(paths))
    checks.append(_hermes_model_routing_check(paths))
    checks.append(_provider_entitlements_check(paths))
    checks.append(_jev_sidekick_check(paths))
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
    checks.append(_structural_search_check())
    checks.append(_trigger_language_pack_check(paths))
    checks.append(_security_posture_check())
    return checks


def _security_posture_check() -> Check:
    """Surface the active `OMH_SECURITY` posture (`P3 -- named strict security posture`).

    Same shape as `_structural_search_check`: this is informational, not a
    health gate, so both branches stay `ok=True`/`severity="ok"` -- `strict`
    is opt-in, not a recommended state, and `default` is not a warning. An
    unrecognized `OMH_SECURITY` value is the one case doctor reports as a
    failing check, since a security knob that fails open on a typo must be
    loud, and a health check is the surface an operator reads for exactly
    that kind of misconfiguration.
    """
    try:
        posture = resolve_security_posture()
    except ValueError as exc:
        return Check(
            "security_posture",
            False,
            str(exc),
            severity="warning",
            next_action=f"Set {SECURITY_POSTURE_ENV_VAR} to `default` or `strict`, or unset it.",
        )
    if posture == STRICT_POSTURE:
        message = f"active security posture: {posture} ({SECURITY_POSTURE_ENV_VAR}=strict)"
    else:
        message = (
            f"active security posture: {posture} "
            f"(set {SECURITY_POSTURE_ENV_VAR}=strict to tighten fanout concurrency, retries, "
            "verification escalation, and the loop stop ladder together)"
        )
    return Check("security_posture", True, message, severity="ok", next_action="")


def _trigger_language_pack_check(paths: OmhPaths) -> Check:
    """Report which input languages this install recognises, and refuse bad packs.

    Shipped packs are product data and always present, so they are reported
    rather than checked. A user pack is the part that can be wrong: it is the
    one place a person edits routing by hand, and a pack that silently failed
    to load looks exactly like a pack whose phrases do not work. So an invalid
    user pack fails this check and the message names the file and the reason
    the parser gave -- the whole point of validating a pack is that the person
    who wrote it finds out.
    """
    from ..routing.trigger_language_packs import trigger_pack_state
    from ..skills.catalog import builtin_definitions

    known_skills = frozenset(definition.name for definition in builtin_definitions())
    state = trigger_pack_state(paths.omh_home, known_skills)
    shipped = ", ".join(
        f"{row['language']} ({row['phrase_count']} phrases)" for row in state["shipped"]
    )
    invalid = [row for row in state["user"] if str(row["status"]).startswith("invalid")]
    applied = [row for row in state["user"] if row["status"] == "applied"]
    if invalid:
        reasons = "; ".join(f"{row['language']}.json {row['status']}" for row in invalid)
        return Check(
            "trigger_language_packs",
            False,
            f"invalid trigger language pack(s) under {state['user_pack_dir']}: {reasons}",
            remediation=f"fix or remove the named file(s) under {state['user_pack_dir']}",
            next_action="correct the pack and rerun `omh doctor`",
        )
    user = (
        "; user packs: " + ", ".join(f"{row['language']} ({row['phrase_count']} phrases)" for row in applied)
        if applied
        else f"; no user packs at {state['user_pack_dir']}"
    )
    return Check(
        "trigger_language_packs",
        True,
        f"trigger language packs shipped: {shipped}{user}",
        severity="ok",
        next_action="",
        observed=True,
    )


def _structural_search_check(*, which: Callable[[str], str | None] | None = None) -> Check:
    """Optional-surface check for the ast-grep structural search tool.

    Absence is the normal case (`team_profile_packs` precedent): both branches
    stay `ok=True`/`severity="ok"` with an informative message and no
    remediation, so an installer without ast-grep never sees a warning, a
    failing doctor, or install advice. The explicit `next_action=""` is
    load-bearing — recommending a package-manager command would put an
    install instruction in OMH's mouth.
    """
    structural = inspect_structural_search(which=which)
    return Check(
        "structural_search_tooling",
        True,
        (
            f"optional structural search tool ast-grep found at {structural['path']}; "
            "presence only, the binary was not executed"
            if structural["found"]
            else "optional structural search tool ast-grep is not on PATH; "
            "code exploration continues with grep/ripgrep as today"
        ),
        severity="ok",
        next_action="",
        observed=True,
    )


def _omh_tui_check(paths: OmhPaths) -> Check:
    """Can bare `omh` open the OMH TUI here, or will it open Hermes' own terminal?

    Read-only and static: the shim OMH ships, Node for Hermes' launcher, and
    the two Hermes files the path relies on (`HERMES_TUI_DIR` in the launcher,
    the gateway entry). A miss is never an error, because bare `omh` falls back
    to Hermes' own terminal; ok stays True, as for the other optional
    surfaces, and the severity says whether the OMH TUI is reachable. Whether
    the gateway still speaks the declared protocol is judged at launch, not
    here; once a Hermes install is found, every message names the commit its
    checkout is at (read from its `.git`, "unknown" when it cannot be) next to
    the one the gateway contract was declared against, and neither value moves
    the severity.
    """
    from ..system.hermes_install import hermes_install_dir, installed_hermes_commit, read_bounded_text
    from ..tui.gateway_contract import DECLARED_AGAINST_HERMES
    from ..tui.launch import FRONTEND_ENTRY, node_available

    fallback = "bare `omh` opens Hermes' own terminal until then"
    if os.name == "nt":
        return Check(
            "omh_tui_support", True,
            "Windows: the OMH TUI needs termios, so bare `omh` opens Hermes' own terminal",
        )
    if not FRONTEND_ENTRY.is_file():
        return Check(
            "omh_tui_support", True, f"the OMH TUI shim is missing ({FRONTEND_ENTRY})",
            severity="warning", next_action=f"reinstall OMH with `omh update`; {fallback}",
        )
    install_dir = hermes_install_dir(paths.hermes_home)
    if not install_dir.is_dir():
        return Check(
            "omh_tui_support", True, f"Hermes install not found at {install_dir}; OMH TUI check skipped",
            observed=False,
        )
    commit = installed_hermes_commit(install_dir)[:len(DECLARED_AGAINST_HERMES)] or "unknown"
    versions = f" (Hermes commit {commit}; the OMH TUI was declared against {DECLARED_AGAINST_HERMES})"
    launcher = read_bounded_text(install_dir / "hermes_cli" / "main_tui_launch.py") or ""
    if "HERMES_TUI_DIR" not in launcher or not (install_dir / "tui_gateway" / "entry.py").is_file():
        return Check(
            "omh_tui_support", True,
            "this Hermes has no HERMES_TUI_DIR launcher hook or no tui_gateway entry, which the OMH TUI needs"
            + versions,
            severity="warning", next_action=f"update Hermes; {fallback}",
        )
    if not node_available(os.environ, paths.hermes_home):
        return Check(
            "omh_tui_support", True,
            "no Node found for Hermes' launcher (HERMES_NODE, PATH, or Hermes' tools/node-*)" + versions,
            severity="warning", next_action=f"install Node (Hermes' modern TUI needs it too); {fallback}",
        )
    return Check(
        "omh_tui_support", True,
        "bare `omh` can open the OMH TUI: shim installed, Hermes launcher hook and gateway present, Node found"
        + versions,
    )


def _delegation_protocol_platform_check(paths: OmhPaths) -> Check:
    """Does the installed Hermes still mark a `delegate_task` child the way the protocol section expects?

    The `omh.delegation-protocol` system prompt section renders only for the
    platform Hermes builds a child with (`delegation_protocol.CHILD_PLATFORM`).
    Hermes is not importable in tests, so that match is pinned on OMH's side
    only, and a rename would leave every child without the protocol while
    nothing said so. This reads the literal from `tools/delegate_tool.py`.
    Read-only and static: a source literal is what the installation declares,
    not what a running host did. A miss warns and never fails, as for the other
    optional surfaces; without an install there is nothing to read.
    """
    from ..plugin_bundle.omh.delegation_protocol import CHILD_PLATFORM
    from ..system.hermes_install import hermes_install_dir, read_bounded_text

    install_dir = hermes_install_dir(paths.hermes_home)
    if not install_dir.is_dir():
        return Check(
            "plugin_delegation_protocol", True,
            f"Hermes install not found at {install_dir}; delegate child platform check skipped",
            observed=False,
        )
    source = install_dir / "tools" / "delegate_tool.py"
    literal = f'platform="{CHILD_PLATFORM}"'
    reach = "the only platform the OMH delegation protocol section renders for"
    next_action = (
        "until OMH matches this Hermes, paste the protocol lines from "
        "`omh coding composition-guide --model <your model>` into each delegate_task goal that needs them"
    )
    text = read_bounded_text(source)
    if text is None:
        return Check(
            "plugin_delegation_protocol", True,
            f"could not read {source}, so whether Hermes still builds a delegate_task child with {literal}, "
            f"{reach}, is not established",
            severity="warning", next_action=next_action, observed=False,
        )
    if literal not in text:
        return Check(
            "plugin_delegation_protocol", True,
            f"{source} no longer builds a delegate_task child with {literal}, {reach}, "
            "so Hermes children may run without the protocol",
            severity="warning", next_action=next_action,
        )
    return Check(
        "plugin_delegation_protocol", True,
        f"Hermes builds a delegate_task child with {literal} ({source}), {reach}",
    )


def _hermes_model_routing_check(paths: OmhPaths) -> Check:
    """Does Hermes' config name the provider that serves `model.default`?

    Users read a mismatch here as OMH hardcoding a model: they authenticate as
    one provider, the picker keeps showing the family pinned in
    `model.default`, and nothing says why. OMH writes only `model.aliases.*`,
    so this is a Hermes user-config fault — doctor names the observed
    disagreement and leaves the repair to the user.

    ok stays True: an inconsistent Hermes model config is not an OMH install
    failure and must not flip the doctor exit code. `severity="warning"`
    plus a next action carries it.
    """
    from .hermes_model_routing import (
        hermes_model_routing_preflight,
        model_routing_consistent_summary,
        model_routing_disagreements,
        model_routing_next_action,
    )

    preflight = hermes_model_routing_preflight(paths)
    config = preflight["config"]
    if not config["readable"]:
        return Check(
            "hermes_model_routing",
            True,
            (
                f"Hermes config not found at {config['path']}; model routing consistency not checked"
                if not config["found"]
                else f"the `model:` block in {config['path']} is user-owned in a shape this check cannot read"
            ),
            observed=False,
        )
    disagreements = model_routing_disagreements(preflight)
    if not disagreements:
        return Check("hermes_model_routing", True, model_routing_consistent_summary(preflight))
    return Check(
        "hermes_model_routing",
        True,
        "; ".join(disagreements),
        severity="warning",
        next_action=model_routing_next_action(preflight),
    )


def _provider_entitlements_check(paths: OmhPaths) -> Check:
    """Which providers routing counts on this machine, and what it cannot place.

    Chains reorder around the providers this machine holds -- linked to
    Hermes (a `hermes auth` login, a `providers:` key, a key name in `.env`)
    or recorded by the setup interview in `providers.json` -- and nothing
    else in the CLI says which ones were counted. Two faults stay silent
    without this check: an invalid `providers.json` yields no document at
    all, so its recorded kinds AND its `excluded_providers` stop applying
    and a provider the operator cleared counts again; and a route in
    `model-providers.json` that names a provider neither recorded nor
    linked makes its alias unserved, so it sinks behind the served entries
    of every chain naming it, with only a `!` mark to explain itself.

    ok stays True like `hermes_model_routing`: a routing document the
    operator owns is not an OMH install failure and must not flip the
    doctor exit code. `severity="warning"` plus a next action carries it.
    Only ids, names, and statuses are read; no key or token reaches a
    message.
    """
    from ..plugin_bundle.omh.hermes_delegation import (
        chains_with_overrides,
        effective_provider_entitlements,
        load_mixture_chain_overrides,
        load_model_provider_routes,
        load_provider_entitlements,
        model_provider_routes_path,
        provider_entitlements_path,
        routes_to_unknown_providers,
        split_unknown_routes,
        unknown_route_labels,
    )

    entitlements, document_status, rows = effective_provider_entitlements(paths.omh_home, paths.hermes_home)
    # The effective document carries only what counts; the exclusions that
    # made a linked row stop counting live in the record itself.
    recorded, _recorded_status = load_provider_entitlements(paths.omh_home)
    routes, routes_status = load_model_provider_routes(paths.omh_home)
    overrides, _overrides_status = load_mixture_chain_overrides(paths.omh_home)
    chains = chains_with_overrides(overrides)
    document_path = provider_entitlements_path(paths.omh_home)
    routes_path = model_provider_routes_path(paths.omh_home)
    parts: list[str] = []
    warnings: list[str] = []
    if document_status.startswith("invalid:"):
        warnings.append(
            f"{document_path} is ignored ({document_status}): its recorded kinds are dropped and any "
            "providers it excluded count again until it is repaired"
        )
    else:
        parts.append(f"providers.json {document_status}")
    if rows:
        parts.append("counted: " + ", ".join(f"{row['id']} ({row['source']}, {row['evidence']})" for row in rows))
    else:
        parts.append("counted: none linked to Hermes or recorded; every model counts as served")
    excluded = list((recorded or {}).get("excluded_providers", []))
    if excluded:
        parts.append("excluded by the record: " + ", ".join(excluded))
    if routes_status.startswith("invalid:"):
        warnings.append(
            f"{routes_path} is ignored ({routes_status}): every alias dispatches unchanged until it is repaired"
        )
    else:
        parts.append(f"model-providers.json {routes_status}")
    demoted, dispatch_only = split_unknown_routes(routes_to_unknown_providers(routes, entitlements, chains))
    if demoted:
        warnings.append(
            "chain entries routed to a provider neither recorded nor linked: "
            + unknown_route_labels(demoted)
            + "; each sorts behind the served entries of every chain naming it"
        )
    if dispatch_only:
        warnings.append(
            "dispatch-only routes to a provider neither recorded nor linked: "
            + unknown_route_labels(dispatch_only)
            + "; no chain names these, so nothing is reordered, but a dispatch pinning one asks Hermes "
            "for a provider it is not linked to"
        )
    # Each warning already carries "; " inside it, so the segments are
    # joined with a separator no warning uses; the status fragments stay
    # one segment at the end.
    message = " | ".join([*warnings, "; ".join(parts)])
    if not warnings:
        return Check("provider_entitlements", True, message)
    return Check(
        "provider_entitlements",
        True,
        message,
        severity="warning",
        next_action=(
            "Repair the named routing document under ~/.omh/routing (rerun `omh setup` interactively to "
            "re-record providers), or link the named provider to Hermes; then rerun `omh doctor`."
        ),
    )


def _jev_sidekick_check(paths: OmhPaths) -> Check:
    """Which Jev-class plugins this Hermes home holds, and what they declare.

    Jev (TypeSafe System One) answers typed questions and cannot write code,
    so OMH never routes it as an executor and never calls a third-party Jev
    plugin; its own `omh_jev_ask` tool is reported in the same check (route by
    variable name, the ask ledger, and what the tool sends). Community Hermes plugins do
    call it, and several of them ask for hooks the OMH bridge also registers
    -- most sharply `pre_llm_call`, where OMH injects its route hint and a Jev
    skill router nominates a skill, so one message can reach the model
    carrying two nominations. Nothing else in the CLI says that is happening.

    Appended in both branches, like every other optional surface: a check that
    appears only on some machines makes the operator summary's `total` vary by
    machine, which no other check does, and a reader comparing two reports
    could not tell a clean home from a check that did not run.

    ok stays True in every branch, including the warning one. A third-party
    plugin an operator installed deliberately is not an OMH install failure
    and must not flip the doctor exit code; `severity="warning"` plus a next
    action carries it. Only names, declared tools, declared hooks and catalog
    text reach the message -- no credential value is read anywhere below, and
    no sentence says what a plugin did, only what it declares.
    """
    from ..workflows.jev_sidekick_posture import (
        build_jev_sidekick_posture,
        omh_jev_ask_sentence,
        posture_overlaps,
        posture_unestablished_hook_overlap,
        posture_unknown_enablement,
    )

    posture = build_jev_sidekick_posture(paths.hermes_home, paths.omh_home)
    ask_sentence = omh_jev_ask_sentence(posture["omh_jev_ask"])
    env_path = paths.hermes_home / ".env"
    plugins = [entry for entry in posture["plugins"] if isinstance(entry, dict)]
    skipped = [entry for entry in posture["skipped"] if isinstance(entry, dict)]
    credential_names = [str(name) for name in posture["credential_names_present"]]
    unestablished = posture_unestablished_hook_overlap(posture)
    unknown_enablement = posture_unknown_enablement(posture)
    if not plugins and not skipped:
        return Check(
            "plugin_jev_sidekick",
            True,
            "optional: no Jev-class plugin installed | " + ask_sentence,
            detail=posture,
        )
    next_action = _jev_next_action(
        env_path,
        plugins=plugins,
        skipped=skipped,
        credential_names=credential_names,
        unestablished=unestablished,
        unknown_enablement=unknown_enablement,
    )
    if not plugins:
        # Not "none installed": a directory OMH could not read is a directory
        # it cannot clear, and a check that reports absence over an
        # incomplete sweep is the absolute assertion this whole posture
        # exists to avoid.
        return Check(
            "plugin_jev_sidekick",
            True,
            "optional: no Jev-class plugin among the plugin directories OMH could read; "
            + _jev_skipped_fragment(skipped)
            + " | "
            + ask_sentence,
            severity="warning",
            detail=posture,
            next_action=next_action,
        )
    segments = [
        f"Jev-class plugin posture: {posture['status']}"
        + (f"; credential names in .env: {', '.join(credential_names)}" if credential_names else "")
    ]
    segments.extend(_jev_plugin_note(entry) for entry in plugins)
    if skipped:
        segments.append(_jev_skipped_fragment(skipped))
    segments.append(ask_sentence)
    # Each note already joins its own fragments with "; ", so the notes are
    # separated by a separator no note uses -- the `provider_entitlements`
    # shape. The claim boundary closes the message because the notes quote a
    # third party verbatim, and a quote an operator reads in a diagnostic
    # should not have to be inferred to be a declaration. `identity_conflicts`
    # closes its message the same way.
    message = " | ".join(segments) + ". " + str(posture["claim_boundary"])
    # Five reasons to raise the message from silent to visible, and a check
    # that is `ok` prints nothing in the text report, so each one has to be
    # here or it is not surfaced at all. A declared overlap means one hook is
    # declared twice over. An unestablished overlap, an unread enablement and
    # a skipped directory each mean nobody looked, which is a different
    # finding from a clean read and must not be reported as one. No
    # credential name means no name a Jev plugin declares as its route was
    # found where OMH looked.
    quiet = (
        not posture_overlaps(posture)
        and not unestablished
        and not unknown_enablement
        and not skipped
        and bool(credential_names)
    )
    if quiet:
        return Check("plugin_jev_sidekick", True, message, detail=posture)
    return Check(
        "plugin_jev_sidekick",
        True,
        message,
        severity="warning",
        detail=posture,
        next_action=next_action,
    )


def _jev_next_action(
    env_path: Path,
    *,
    plugins: list[dict[str, object]],
    skipped: list[dict[str, object]],
    credential_names: list[str],
    unestablished: list[str],
    unknown_enablement: list[str],
) -> str:
    """What to do next, built from the reads that happened and nothing else.

    Three rules, each of which a fixed string broke. A sentence is printed
    only when its own branch fired, so an operator whose credential name is
    right does not read that it is missing. A sentence says what a plugin
    DECLARES, never what it does: OMH did not watch a hook fire, and "shares a
    hook" is true of eight hooks while "nominates twice" is true of one, so
    the overlap is reported as the declaration it is. And a path is the path
    OMH read -- under `--hermes-home` or `HERMES_HOME` the default spelling
    names a file this verdict did not come from.
    """
    sentences = [_JEV_NEXT_ACTION_OPENING]
    for entry in plugins:
        hooks = [str(hook) for hook in entry.get("hook_overlap", [])]
        if hooks:
            sentences.append(f"{entry.get('name', '')} declares the same hook OMH registers: {', '.join(hooks)}.")
    if unestablished:
        sentences.append(
            f"{', '.join(unestablished)} declares hooks in a form OMH does not read, so an overlap with the "
            "OMH bridge is neither established nor ruled out."
        )
    for reason, names in _jev_unknown_enablement_reasons(plugins, unknown_enablement):
        sentences.append(f"OMH did not read whether Hermes enables {', '.join(names)}: {reason}.")
    if plugins and not credential_names:
        sentences.append(f"No name a Jev-class plugin declares as its route appears in {env_path}.")
    if skipped:
        sentences.append("OMH did not read every plugin directory under this home, so this posture is not a complete sweep.")
    return " ".join(sentences)


def _jev_unknown_enablement_reasons(
    plugins: list[dict[str, object]], unknown_enablement: list[str]
) -> list[tuple[str, list[str]]]:
    """The plugins whose enablement went unread, grouped by why.

    Grouped rather than one sentence each: a config OMH could not open leaves
    every plugin unread for one reason, and repeating it per plugin would
    print the same repair five times.
    """
    grouped: dict[str, list[str]] = {}
    unknown = set(unknown_enablement)
    for entry in plugins:
        name = str(entry.get("name", ""))
        if name not in unknown:
            continue
        reason = str(entry.get("enablement_reason", "")) or "the read did not happen"
        grouped.setdefault(reason, []).append(name)
    return sorted(grouped.items())


def _jev_plugin_note(entry: dict[str, object]) -> str:
    """One detected plugin, as its manifest and its catalog entry declare it.

    Every clause says "declares" and names where OMH read it. A plugin whose
    name this build has no catalog record for says exactly that instead of
    borrowing another record's disclosure.
    """
    state = _jev_enablement_label(entry)
    tools = ", ".join(str(tool) for tool in entry.get("jev_tools", [])) or "no Jev-class tool"
    parts = [f"{entry.get('name', '')} ({state}) declares {tools}"]
    hooks = [str(hook) for hook in entry.get("declares_hooks", [])]
    if hooks:
        parts.append("declares hooks " + ", ".join(hooks))
    overlap_hooks = [str(hook) for hook in entry.get("hook_overlap", [])]
    if overlap_hooks:
        parts.append("shares with the OMH bridge the hooks " + ", ".join(overlap_hooks))
    if entry.get("overlap"):
        parts.append(f"its catalog entry says it {entry['overlap']}")
    if entry.get("declared_disclosure"):
        parts.append(f"its catalog entry discloses \"{entry['declared_disclosure']}\"")
    if entry.get("known"):
        parts.append(f"read from {entry.get('read_from', '')} on {entry.get('read_on', '')}")
    else:
        parts.append("no catalog entry for this name was read; classified by its jev_ tool prefix alone")
    unread = [str(field) for field in entry.get("unreadable_declarations", [])]
    for field in unread:
        parts.append(
            _JEV_UNREAD_DECLARATION_NOTES.get(field, f"declares {field} in a form OMH does not read")
        )
    return "; ".join(parts)


def _jev_enablement_label(entry: dict[str, object]) -> str:
    """How one plugin's enablement reads, including when it was not read.

    Three states, not two. `installed, not enabled` is a claim about Hermes'
    config, and OMH may state it only over a config it read: a `plugins:` node
    written in a flow form the block reader walks past, or a plugin whose own
    manifest name OMH could not establish, leaves the answer unread. The
    reason travels with the state so the line says which read is missing
    rather than leaving the operator to guess.
    """
    state = str(entry.get("enablement", ""))
    if state == "enabled":
        return "enabled"
    if state == "not enabled":
        return "installed, not enabled"
    reason = str(entry.get("enablement_reason", ""))
    return f"enablement not established: {reason}" if reason else "enablement not established"


def _jev_skipped_fragment(skipped: list[dict[str, object]]) -> str:
    """Name the plugin directories the posture did not fully read.

    Bounded on purpose: a home with many plugins would otherwise turn one
    check into a page. The count is always exact and `omh doctor --json`
    carries every entry with its reason.
    """
    names = [str(entry.get("plugin", "")) for entry in skipped]
    shown = ", ".join(names[:_JEV_SKIPPED_NAMED_LIMIT])
    if len(names) > _JEV_SKIPPED_NAMED_LIMIT:
        shown = f"{shown}, and {len(names) - _JEV_SKIPPED_NAMED_LIMIT} more"
    # "entry", not "plugin directory": a row can name the first entry a
    # bounded sweep did not reach, which need not be a directory at all, and a
    # line that calls it a plugin directory reports a plugin that may not
    # exist.
    noun = "entry" if len(names) == 1 else "entries"
    return f"{len(names)} {noun} under plugins/ not fully read: {shown}"


def _profile_paths(paths: OmhPaths, profile_dir: Path) -> OmhPaths:
    """A bot profile's homes the way the setup sync resolves them.

    The profile's own Hermes home, the primary's OMH store: every profile
    shares the primary's store for the managed skills, and the registration
    candidates the sync scores are the primary's too.
    """
    return OmhPaths(
        omh_home=paths.omh_home,
        hermes_home=profile_dir,
        omh_home_named=paths.omh_home_named,
        managed_skills_dir=paths.managed_skills_dir,
    )


def _external_dir_ambiguity_checks(paths: OmhPaths, config_text: str) -> list[Check]:
    """A home naming two OMH-managed skills directories is a finding, per home.

    Hermes refuses a bare skill name that resolves to two different files
    across its skill directories, and every generation refresh makes the
    pre-pointer copy and the pointer differ, so a home that names both loses
    every OMH skill by name (#1857). `omh update` migrates such a home; this
    names one it has not reached yet, in the same words update's post-check
    uses. Doctor otherwise reads one Hermes home; bot profiles are walked for
    this one question because the profile sync is where the older entry
    survived, and each affected profile gets its own row so the name says
    which home to look at. `severity="warning"` with `ok=True`: the finding
    carries its own next action and must not flip the doctor exit code for
    a profile the primary home does not share.
    """
    current = managed_current_workflow_pack_dir()
    entries = registered_managed_entries(
        config_text,
        managed_skill_dir_candidates(paths, current=current),
        hermes_home=paths.hermes_home,
        current=current,
    )
    checks = [_ambiguity_check("external_dir_ambiguity", registration_home_label(paths.hermes_config_path), entries)]
    for name, profile_dir in hermes_profile_dirs(paths.hermes_home):
        profile_paths = _profile_paths(paths, profile_dir)
        profile_entries = registered_managed_entries(
            read_config(profile_paths.hermes_config_path),
            managed_skill_dir_candidates(profile_paths, current=current),
            hermes_home=profile_paths.hermes_home,
            current=current,
        )
        if len(profile_entries) > 1:
            checks.append(
                _ambiguity_check(
                    f"external_dir_ambiguity:{name}",
                    registration_home_label(profile_paths.hermes_config_path, profile=name),
                    profile_entries,
                )
            )
    return checks


def _ambiguity_check(name: str, label: str, entries: list[str]) -> Check:
    if len(entries) > 1:
        return Check(
            name,
            True,
            ambiguous_registration_message(label, entries),
            severity="warning",
            next_action=AMBIGUOUS_REGISTRATION_NEXT_ACTION,
        )
    if entries:
        return Check(name, True, f"{label} names one OMH-managed skills directory: {entries[0]}")
    return Check(name, True, f"{label} names no OMH-managed skills directory")


def _external_dir_unregistered_copy_check(paths: OmhPaths, config_text: str) -> Check:
    """The pre-pointer skills copy left on disk after the registration moved off it.

    `omh update` never deletes it: the OMH manifest records the generation
    pack as its skills directory, and no manifest records that copy at the
    catalog revision it froze at, so nothing proves it is unmodified OMH
    output -- the same bar the manifest-checked removals hold every other
    directory to. Read-only evidence instead, and two references are read
    before anything is called deletable. Registrations: a copy a home still
    registers is the migration's job. Generations: on a managed install the
    lazy migration linked `generations/bootstrap-legacy/skills` to this very
    copy, and that generation is always retained as the rollback target, so
    the copy backs a live fallback pack for as long as the generations exist
    and is collected only by `omh uninstall`, which removes them. Only a copy
    no home registers and no generation links is named as safe to delete.
    The time shown is the directory's own mtime -- when a direct child was
    last added or removed -- not the newest file inside it.
    """
    copy = paths.omh_home / "skills"
    if external_dir_key(copy) == external_dir_key(paths.skills_dir):
        return Check("external_dir_unregistered_copy", True, f"managed skills are served from {copy}")
    if not copy.is_dir():
        return Check("external_dir_unregistered_copy", True, f"no pre-pointer skills copy at {copy}")
    registered_by: list[str] = []
    if external_dir_registered(external_dirs(config_text), copy, hermes_home=paths.hermes_home):
        registered_by.append(registration_home_label(paths.hermes_config_path))
    for name, profile_dir in hermes_profile_dirs(paths.hermes_home):
        profile_paths = _profile_paths(paths, profile_dir)
        profile_dirs = external_dirs(read_config(profile_paths.hermes_config_path))
        if external_dir_registered(profile_dirs, copy, hermes_home=profile_paths.hermes_home):
            registered_by.append(registration_home_label(profile_paths.hermes_config_path, profile=name))
    if registered_by:
        return Check(
            "external_dir_unregistered_copy",
            True,
            f"pre-pointer skills copy at {copy} is still registered by {', '.join(registered_by)}; "
            f"`omh update` migrates that registration to {paths.skills_dir}",
        )
    try:
        directory_mtime = (
            datetime.fromtimestamp(copy.stat().st_mtime, UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except OSError:
        directory_mtime = "unknown"
    retained = _retained_generations_backed_by(copy)
    if retained:
        return Check(
            "external_dir_unregistered_copy",
            True,
            f"unregistered managed skills copy at {copy} (directory mtime {directory_mtime}); "
            f"neither {paths.hermes_config_path} nor its profiles register it, and it is retained as the "
            f"{', '.join(retained)} fallback pack under {managed_command_generations_dir()}, "
            "collected only by `omh uninstall`",
        )
    return Check(
        "external_dir_unregistered_copy",
        True,
        f"unregistered managed skills copy at {copy} (directory mtime {directory_mtime}); "
        f"neither {paths.hermes_config_path} nor its profiles register it and no retained generation "
        "links it, safe to delete",
        severity="warning",
        next_action=f"remove {copy}; no manifest records that copy, so `omh update` never deletes it",
    )


def _retained_generations_backed_by(copy: Path) -> list[str]:
    """Names of managed generations whose `skills` link resolves to `copy`.

    Every generation directory on disk is read, plus the names the
    self-update state retains (`retained_generations`, `previous_known_good`)
    in case one is named there but not listed; a name without a directory has
    no link to resolve and contributes nothing. Sorted so the message is
    stable.
    """
    generations = managed_command_generations_dir()
    if generations is None:
        return []
    names: set[str] = set()
    try:
        names.update(entry.name for entry in generations.iterdir() if entry.is_dir())
    except OSError:
        pass
    state_path = managed_command_self_update_state_path()
    try:
        state = read_json_object(state_path) if state_path is not None else None
    except (OSError, ValueError):
        state = None
    if isinstance(state, dict):
        retained = state.get("retained_generations")
        if isinstance(retained, list):
            names.update(item for item in retained if isinstance(item, str))
        previous = state.get("previous_known_good")
        if isinstance(previous, dict) and isinstance(previous.get("id"), str):
            names.add(previous["id"])
    try:
        copy_real = os.path.normcase(os.path.realpath(copy))
    except OSError:
        return []
    backed: list[str] = []
    for name in sorted(names):
        link = generations / name / "skills"
        if not link.exists():
            continue
        try:
            if os.path.normcase(os.path.realpath(link)) == copy_real:
                backed.append(name)
        except OSError:
            continue
    return backed


def _retired_skill_install_check(paths: OmhPaths) -> Check:
    """A retired skill still installed under skills_dir is a finding.

    Retirement removed `ulw-team`/`ulw-ralph`/`ulw-goal`/`ulw-process` (#954
    stage 5) and `omh-performance-goal`/`omh-best-practice-research`/
    `omh-autoresearch-goal` (#1691) from the installable catalog; `omh update`
    prunes them. A leftover install keeps serving guidance for an intent that
    now runs somewhere else, so doctor names the migration instead of staying
    silent. The label set comes from `retired_display_names()`, which reads
    every retired exposure row rather than the ULW engines alone.
    """
    from ..skills.catalog import retired_display_names, retired_skill_migration_error

    if not paths.skills_dir.is_dir():
        return Check("retired_skills", True, "no skills directory yet", observed=False)
    labels = retired_display_names()
    installed = sorted(
        {
            directory.name
            for directory in installed_skill_directories(paths.skills_dir)
            if directory.name in labels
        }
    )
    if not installed:
        return Check("retired_skills", True, "no retired skill is installed")
    messages = "; ".join(
        str(retired_skill_migration_error(name).get("message", name)) for name in installed
    )
    return Check(
        "retired_skills",
        False,
        f"retired skill install(s) found: {messages}",
        severity="warning",
        remediation="each intent now runs in the target home named above; retired installs are pruned on update",
        next_action="run `omh update` to prune the retired skill directories",
    )


def _flat_skill_layout_check(paths: OmhPaths) -> Check:
    """A managed skill still sitting flat under skills_dir is a finding.

    Skills install under `<skills_dir>/<category>/<label>/SKILL.md` so Hermes can
    read a dashboard category off the path. A copy left at the old flat depth is
    a second SKILL.md with the same `name:` frontmatter, and Hermes resolves the
    category of that copy to nothing -- so the banner keeps a "general" group and
    the skill is registered twice. `omh update` prunes them; doctor names the
    ones an interrupted or half-forced update left behind.
    """
    if not paths.skills_dir.is_dir():
        return Check("skill_layout", True, "no skills directory yet", observed=False)
    labels = {omh_skill_install_path(template.name).split("/")[-1] for template in builtin_skill_templates()}
    flat = sorted(
        directory.name
        for directory in installed_skill_directories(paths.skills_dir)
        if directory.parent == paths.skills_dir and directory.name in labels
    )
    if not flat:
        return Check("skill_layout", True, "every managed skill sits under a category directory")
    listed = ", ".join(flat[:5]) + (", ..." if len(flat) > 5 else "")
    return Check(
        "skill_layout",
        False,
        f"{len(flat)} managed skill(s) still installed at the pre-category flat depth: {listed}",
        severity="warning",
        remediation=(
            "a flat copy registers the same skill a second time and keeps a \"general\" group in the "
            "Hermes banner"
        ),
        next_action="run `omh update` to move them under their category directory",
    )


def _plugin_ulw_lifecycle_check(paths: OmhPaths) -> Check:
    """A stale or incompatible plugin bundle's duplicated ULW tables are a finding.

    The bundle duplicates the ULW lifecycle table on purpose (a copied bundle
    has no catalog import). A copy that still lists a retired engine as
    canonical routes legacy cues to a workflow the catalog no longer ships;
    a copy without the table predates the lifecycle contract entirely.
    """
    from ..skills.catalog import ulw_inventory_payload

    awareness_path = paths.hermes_plugin_dir / "awareness.py"
    if not awareness_path.is_file():
        return Check(
            "plugin_ulw_lifecycle",
            True,
            f"managed OMH plugin bridge is not installed yet at {paths.hermes_plugin_dir}",
            observed=False,
        )
    try:
        text = awareness_path.read_text(encoding="utf-8")
    except OSError as exc:
        return Check(
            "plugin_ulw_lifecycle",
            False,
            f"{awareness_path} unreadable: {exc}",
            severity="warning",
            next_action="run `omh setup` to refresh the plugin bundle",
        )
    if "_ULW_ENGINE_LIFECYCLE_STAGES" not in text:
        return Check(
            "plugin_ulw_lifecycle",
            False,
            (
                f"{awareness_path} carries no ULW lifecycle table; the installed bundle version "
                "is incompatible with this OMH package"
            ),
            severity="warning",
            remediation="the bundle predates the ULW lifecycle contract",
            next_action="run `omh setup` to refresh the plugin bundle",
        )
    stale = sorted(
        str(engine["canonical"])
        for engine in ulw_inventory_payload()["retired_engines"]
        if f'"{engine["canonical"]}": "retired"' not in text
    )
    if stale:
        return Check(
            "plugin_ulw_lifecycle",
            False,
            f"installed plugin bundle still lists retired engine(s) as canonical: {', '.join(stale)}",
            severity="warning",
            remediation="the bundle's duplicated ULW tables are stale relative to the catalog",
            next_action="run `omh setup` to refresh the plugin bundle",
        )
    return Check(
        "plugin_ulw_lifecycle",
        True,
        "plugin bundle ULW lifecycle table matches the catalog",
    )


def _plugin_enforcement_check(plugin: dict[str, object]) -> Check:
    """The fourth smoke tier: what the installed bundle actually decided.

    The first three tiers prove the bundle is there, imports, and registers.
    None of them asks it to decide anything, so a bundle whose rule matcher
    answers `None` for every call passes all three. This tier asks, and
    reports the decision it got back rather than that the call completed.

    Three outcomes, kept apart on purpose. `enforced` observed a block on the
    scoped probe and a proceed on the unscoped one. `no_decision` got an
    answer that is not enforcement -- the import and register tiers still pass
    beside it, and that contrast is the finding. `unknown` could not obtain a
    decision at all; it does not pass, because a check that cannot tell must
    not return the safe-looking answer.
    """
    status = str(plugin.get("plugin_enforcement_status", "unknown"))
    detail = str(plugin.get("plugin_enforcement_detail", ""))
    decision = str(plugin.get("plugin_enforcement_decision", ""))
    if status == "enforced":
        return Check(
            "plugin_enforcement_smoke",
            True,
            f"installed plugin decided a benign probe: {decision}; {detail}",
        )
    remediation = "Run `omh setup --force` to reinstall the managed plugin bundle, then `omh doctor` again."
    if status == "unknown":
        return Check(
            "plugin_enforcement_smoke",
            False,
            f"no enforcement decision could be observed: {detail}",
            severity="warning",
            remediation=remediation,
            next_action="Run `omh setup --force`, then `omh doctor` again.",
            observed=False,
        )
    return Check(
        "plugin_enforcement_smoke",
        False,
        f"installed plugin loads and registers but does not enforce: {detail}",
        remediation=remediation,
        next_action="Run `omh setup --force`, then `omh doctor` again.",
    )


def _plugin_loader_observation_check(observation: dict[str, object] | None) -> Check:
    if not observation or not observation.get("observed"):
        reason = str((observation or {}).get("reason", "plugin_bundle_not_installed"))
        return Check(
            "plugin_loader_observed",
            True,
            (
                f"real Hermes loader not observed ({reason}); "
                "fake-context registration does not prove host registration"
            ),
            severity="warning",
            observed=False,
        )
    tools = observation.get("registered_tools", [])
    hooks = observation.get("registered_hooks", [])
    if observation.get("ok"):
        return Check(
            "plugin_loader_observed",
            True,
            f"real Hermes loader registered tools={tools} hooks={hooks} in an isolated HERMES_HOME",
            observed=True,
        )
    error = str(observation.get("error") or observation.get("reason") or "registration_mismatch")
    return Check(
        "plugin_loader_observed",
        False,
        f"real Hermes loader registration mismatch: {error}; tools={tools} hooks={hooks}",
        remediation="Run `omh setup --force`, then reload Hermes and run `omh doctor` again.",
        next_action="Run `omh setup --force`, reload Hermes, then run `omh doctor` again.",
        observed=True,
    )


def _plugin_load_deadline_check(paths: OmhPaths, config_text: str) -> Check:
    """What Hermes' load deadline is set to here, and whether it ever cost this plugin a load.

    Hermes skips a plugin whose import + `register()` overruns
    `plugins.load_timeout_seconds`, and its plugin loader registers none of
    OMH's tools or hooks from a skipped load. `plugin_loader_observed` replays
    the loader in an isolated home under Hermes' own default, so it can
    neither see a deadline the operator shortened nor say what a past session
    did. This row reads the two things on disk that can: the setting, and the
    lines Hermes logs when the deadline costs a plugin its load -- its own
    overrun, or a refusal because other plugins' abandoned loaders hit Hermes'
    cap (`install/plugin_load_deadline.py`).

    The three answers stay apart. A record is a past load, so it warns without
    failing: this check cannot tell whether the next load made it. Files with
    no record are named for exactly what was read of them and nothing more.
    A log that is not there is `observed=False` and says so -- never a pass by
    absence. The record itself rides in `detail`.
    """
    config_path = paths.hermes_config_path
    setting = plugin_load_timeout_setting(config_text)
    setting_clause = (
        f"plugins.load_timeout_seconds={setting} in {config_path}"
        if setting
        else (
            f"no plugins.load_timeout_seconds read from {config_path} "
            "(no such file, the key unset, or a form OMH does not read)"
        )
    )
    record = read_recorded_load_timeouts(paths.hermes_home, PLUGIN_NAME)
    if not record["observed"]:
        why = f"{record['reason']}: {record['detail']}" if record["detail"] else str(record["reason"])
        return Check(
            "plugin_load_deadline",
            True,
            (
                f"{setting_clause}; not_observed ({why}): {record['log_path']} was not read, so whether "
                f"Hermes skipped `{PLUGIN_NAME}` at load is not established"
            ),
            observed=False,
            detail=record,
        )
    limit = f"last {record['read_limit_bytes'] // (1024 * 1024)} MiB only"
    files = ", ".join(
        f"{name} ({limit})" if name in record["truncated_files"] else name for name in record["files_read"]
    )
    scope = f"{files} under {Path(record['log_path']).parent}"
    if record["reason"] != LOAD_TIMEOUT_RECORDED:
        return Check(
            "plugin_load_deadline",
            True,
            (
                f"{setting_clause}; no load-deadline record for `{PLUGIN_NAME}` in {scope}. "
                "That is what was read of those files, not evidence that the plugin loaded"
            ),
            detail=record,
        )
    if record["latest_cause"] == ABANDONED_LOADER_CAP:
        cause = "not loaded: other plugins' abandoned loaders had reached Hermes' cap"
        next_action = (
            f"Restart Hermes; if `/plugins` still shows `{PLUGIN_NAME}` as not loaded, find the plugins "
            "whose load timed out before it."
        )
    else:
        cause = f"load timed out after {record['latest_deadline'] or 'an unread deadline'}"
        next_action = (
            f"Open `/plugins` in a running Hermes session; if `{PLUGIN_NAME}` still shows a load timeout, "
            f"raise `plugins.load_timeout_seconds` in {config_path} and restart Hermes."
        )
    return Check(
        "plugin_load_deadline",
        True,
        (
            f"Hermes recorded skipping `{PLUGIN_NAME}` at load: {record['count']} record(s) in {scope}, "
            f"latest {record['latest_at'] or 'at an unread time'} ({cause}); {setting_clause}. "
            "Hermes' plugin loader registers no OMH tool or hook from a skipped load. "
            "This is a record of a past load, not the current load state"
        ),
        severity="warning",
        remediation=next_action,
        next_action=next_action,
        detail=record,
    )


BUNDLE_IMPORT_SCAN_REMEDIATION = (
    "Run `omh update` to reinstall the managed plugin bundle from the current OMH package "
    "(`omh setup --force` if this copy carries local edits), then restart Hermes Agent."
)


def _plugin_bundle_import_scan_check(scan: dict[str, object]) -> Check:
    """Read the INSTALLED bundle's syntax; the source-tree gate cannot reach it.

    `plugin_loader_observed` drives the plugin lane, where a failed exec is
    dropped from `sys.modules`, and its verdict is registration equality --
    so a bundle whose modules cannot exec on the memory-provider lane passed
    it while the agent-board bridge was dead and every tool call logged a hook
    warning (#1623, #1670). This tier asks the other question, statically: can
    a host with no `omh` package on its path run the top level of every file
    Hermes execs?

    Blocking, not advisory. The advisory lane is for a legitimate, recommended
    configuration that must not move the exit code (#1636); an unguarded
    module-level `omh.*` import in the installed copy is never a configuration
    choice. It means this copy is stale, hand-copied, or locally edited away
    from the managed bundle, the features those modules carry are dead, and
    `omh update` fixes it -- the same profile as `plugin_import_smoke` and
    `plugin_bundle_current`, which are blocking beside it.
    """
    if not scan.get("scanned"):
        reason = str(scan.get("reason", "plugin_bundle_not_installed"))
        return Check(
            "plugin_bundle_standalone_imports",
            True,
            (
                f"installed plugin bundle not scanned ({reason}); "
                "static import shape is unknown, not proven good"
            ),
            severity="warning",
            observed=False,
        )
    findings = [item for item in scan.get("findings", []) if isinstance(item, dict)]
    module_count = scan.get("module_count", 0)
    if not findings:
        return Check(
            "plugin_bundle_standalone_imports",
            True,
            (
                f"{module_count} module(s) under {scan.get('bundle_dir')} import at module level "
                "with no `omh` package on the path, which is what Hermes' interpreter normally has"
            ),
        )
    return Check(
        "plugin_bundle_standalone_imports",
        False,
        (
            f"{len(findings)} module-level import(s) in {scan.get('bundle_dir')} cannot resolve on a "
            f"host without the `omh` package: {describe_findings(findings)}. "
            "Hermes' memory-provider lane execs every file of the bundle and keeps the module that "
            "raised, so each tool call reaching one logs a hook warning and its feature is dead"
        ),
        remediation=BUNDLE_IMPORT_SCAN_REMEDIATION,
        next_action="Run `omh update`, restart Hermes Agent, then run `omh doctor` again.",
    )


def _toolcall_rule_checks(paths: OmhPaths) -> list[Check]:
    """Does the person's tool-call rules file still load, and did the gate fault?

    A `toolcall-rules.json` is how somebody tells OMH to block a tool call, and
    the enforcing hook fails open: a wrong `schema_version` refuses the WHOLE
    document, a bad regex drops one rule, and either way the hook says nothing.
    Until now the only surface that reported it was `omh ops
    toolcall-rules-validate`, which a person has to already suspect in order to
    run. Doctor runs the same validator, so a rules file that stopped blocking
    is visible from the command people run when something feels wrong.

    Absence is silence, deliberately. The file's presence is the opt-in, so
    "you have no rules" is not a finding and emits no check at all -- the same
    posture the optional-surface checks take, one step further, because a
    permanently-green row about a feature nobody uses is noise on the surface
    #1728 is about.

    Two checks rather than one crowded message: `toolcall_rules` is about the
    document, `toolcall_rule_gate` is about evaluating it at runtime. A person
    whose file is valid and whose gate is crashing needs to read the second
    without the first arguing otherwise.
    """
    from ..plugin_bundle.omh.toolcall_rule_faults import read_toolcall_rule_faults
    from ..plugin_bundle.omh.toolcall_rules import (
        MAX_RULES_FILE_BYTES,
        TOOLCALL_RULES_SCHEMA_VERSION,
        toolcall_rules_path,
        validate_toolcall_rules_document,
    )

    checks: list[Check] = []
    try:
        path = toolcall_rules_path(str(paths.omh_home))
        # The message exists to be acted on, so it names the resolved path:
        # the form a person can open and paste into `--path`. Measured, not
        # assumed: `resolve_paths` already resolves `omh_home`, so this line
        # is NOT what fixed the Windows CI failure -- that was a test
        # comparing an 8.3 short temp path (`RUNNER~1`) against the long form
        # doctor had correctly printed. It holds the guarantee where the
        # message is built, for a caller that builds `OmhPaths` itself rather
        # than through `resolve_paths`.
        path = path.resolve()
        present = path.is_file()
    except (OSError, RuntimeError):
        path = paths.omh_home / "rules" / "toolcall-rules.json"
        present = False
    if present:
        try:
            size = path.stat().st_size
            raw: object = json.loads(path.read_text(encoding="utf-8"))
            read_error = ""
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            size = 0
            raw = None
            read_error = f"{type(exc).__name__}: {exc}"
        if read_error:
            checks.append(
                Check(
                    "toolcall_rules",
                    True,
                    f"{path} exists but does not parse ({read_error}), so the enforcing hook loads "
                    "0 of its rules and every tool call it was written to block now proceeds.",
                    severity="warning",
                    remediation=f"Repair the JSON in {path}, then run `omh ops toolcall-rules-validate`.",
                    next_action=f"Run `omh ops toolcall-rules-validate --path {path}` and fix the reported error.",
                    observed=True,
                )
            )
        else:
            errors, accepted = validate_toolcall_rules_document(raw)
            if size > MAX_RULES_FILE_BYTES:
                # Mirrors `omh ops toolcall-rules-validate`: above this bound the
                # enforcing hook refuses the file whole, so any "accepted" count
                # would certify rules that never load.
                errors = [
                    *errors,
                    f"rules file is {size} bytes; the enforcing hook ignores files over "
                    f"{MAX_RULES_FILE_BYTES} bytes, so no rule is loaded",
                ]
                accepted = 0
            if errors:
                skipped = _toolcall_rules_declared_count(raw) - accepted
                # Named only when the validator actually reported it. Keying
                # this off `accepted == 0` instead would assert a wrong
                # schema_version over three bad regexes or an oversized file,
                # which is a cause the reader did not observe.
                whole_document = (
                    f" A wrong schema_version refuses the WHOLE document, so the expected value is "
                    f"{TOOLCALL_RULES_SCHEMA_VERSION}."
                    if any(error.startswith("schema_version must be") for error in errors)
                    else ""
                )
                checks.append(
                    Check(
                        "toolcall_rules",
                        True,
                        f"{path}: {accepted} rule(s) load, {max(skipped, 0)} skipped. "
                        f"First error: {errors[0]}.{whole_document} "
                        "The enforcing hook fails open, so a skipped rule blocks nothing and says nothing.",
                        severity="warning",
                        remediation=f"Fix the reported rule(s) in {path}; the hook never reports them itself.",
                        next_action=f"Run `omh ops toolcall-rules-validate --path {path}` for the full error list.",
                        observed=True,
                    )
                )
            else:
                checks.append(
                    Check(
                        "toolcall_rules",
                        True,
                        f"{path}: {accepted} user tool-call rule(s) load with no defect. "
                        "Loading is not evidence that any rule matched or blocked a call.",
                        severity="ok",
                        next_action="",
                        observed=True,
                    )
                )
    faults = read_toolcall_rule_faults(str(paths.omh_home))
    if faults.get("unreadable"):
        checks.append(
            Check(
                "toolcall_rule_gate",
                True,
                "The tool-call rule-gate fault record is present but unreadable, so whether the "
                "gate has failed cannot be answered from here.",
                severity="warning",
                remediation="Remove the unreadable record under <omh-home>/runtime/ and rerun `omh doctor`.",
                next_action="Remove the unreadable rule-gate fault record, then run `omh doctor` again.",
                observed=True,
            )
        )
    elif int(faults.get("fault_count", 0) or 0) > 0:
        checks.append(
            Check(
                "toolcall_rule_gate",
                True,
                f"Evaluating the tool-call rules failed {faults['fault_count']} time(s), last at "
                f"{faults['last_fault_at'] or 'unknown time'} on tool "
                f"{faults['last_tool'] or 'unknown'}, raising "
                f"{faults['last_error_type'] or 'an unrecorded error type'}. "
                "Each failing call was ALLOWED, so the rules did not block it. "
                "Only the exception's type is recorded: its message is free text that can quote "
                "a rule pattern or a tool argument, and this ledger is metadata-only.",
                severity="warning",
                remediation=(
                    "Validate the rules file, then restart Hermes Agent so the gate re-arms; "
                    "the counter is cumulative and is not cleared by a fix."
                ),
                next_action="Run `omh ops toolcall-rules-validate`, then restart Hermes Agent.",
                observed=True,
            )
        )
    return checks


def _toolcall_rules_declared_count(raw: object) -> int:
    """How many rule entries the document declares, for the skipped count.

    Not the validator's job: it returns how many were ACCEPTED, and the
    difference is what a person wants to read. A document whose `rules` is not
    a list declares nothing, which is also the truth.
    """
    if not isinstance(raw, dict):
        return 0
    entries = raw.get("rules")
    return len(entries) if isinstance(entries, list) else 0


def _plugin_hook_error_checks(paths: OmhPaths) -> list[Check]:
    """Name a hook whose recent host-observed calls did not come back observed.

    Doctor's only hook-runtime signal was `awareness_delivery`, which answers
    one question about one hook. The plugin host observation journal already
    carries per-hook records with a status, and a `hook_call` whose status is
    `blocked` or `not_observed` is a hook the host tried and did not get a
    clean call out of. Nothing new is written for this; it is the journal
    `observe_plugin_hook_call` and `omh plugin observe-host` already append to.

    Silent when there is nothing to say, for the same reason as the rules
    checks: a row that is green on every machine forever is not information.

    Claim boundary, kept narrow on purpose: these are host- and
    wrapper-supplied records. A hook that raised inside Hermes without a
    wrapper recording it leaves nothing here, and this check does not claim
    otherwise.
    """
    records, errors = read_plugin_host_observations(paths, limit=_HOOK_OBSERVATION_WINDOW)
    if errors:
        return [
            Check(
                "plugin_hook_errors",
                True,
                f"plugin host observation ledger unreadable: {'; '.join(errors[:3])}",
                severity="warning",
                remediation="Repair or remove the unreadable observation ledger under <omh-home>/runtime/.",
                next_action="Repair the plugin host observation ledger, then run `omh doctor` again.",
                observed=True,
            )
        ]
    failing: dict[str, list[str]] = {}
    for record in records:
        if str(record.get("event", "")) != "hook_call" or str(record.get("status", "")) == "observed":
            continue
        hook = str(record.get("hook", "")) or "unknown"
        failing.setdefault(hook, []).append(str(record.get("status", "")) or "unknown")
    if not failing:
        return []
    detail = "; ".join(
        f"{hook}: {len(statuses)} of the last {_HOOK_OBSERVATION_WINDOW} record(s) "
        f"({', '.join(sorted(set(statuses)))})"
        for hook, statuses in sorted(failing.items())
    )
    return [
        Check(
            "plugin_hook_errors",
            True,
            f"Host-observed hook calls that did not come back observed -- {detail}. "
            "These are host/wrapper-supplied records; a hook that raised with nothing recording it "
            "leaves no trace here.",
            severity="warning",
            remediation="Read the records with `omh plugin observations` and fix the hook they name.",
            next_action="Run `omh plugin observations` to read the failing hook records.",
            observed=True,
        )
    ]


def _memory_consolidation_check(paths: OmhPaths) -> Check:
    """Say what the newest consolidation brief is asking for.

    The scheduler decided memory was worth consolidating and wrote a brief. Up
    to now nothing read it back, so the decision lived in a JSON file an
    operator had no reason to open: OMH knew memory was nearly full and said so
    only to itself.

    Never a fault. OMH cannot run the consolidation -- that needs a model -- and
    it cannot tell whether Hermes already did, so an outstanding brief is a
    thing to know rather than a thing that is broken.

    Two states hide under one brief, and only one of them is pending work. When
    the pack is over its floor AND something in it is provably redundant, there
    is a consolidation to run and the brief names the clusters. When the pack is
    over its floor and NOTHING is reclaimable, the planner has nothing to
    propose, OMH cannot write Hermes memory by design, and the condition cannot
    clear on its own -- so calling it "due" promises an action that does not
    exist, and the warning stands forever. A standing warning is how people
    learn to skip doctor, which costs more than this one line is worth. That
    state is reported as the fact it is, at `severity="ok"`, naming the move
    that does exist: shorten or remove an entry in Hermes memory.
    """
    brief = read_latest_consolidation(paths.omh_home, paths.hermes_home)
    if not brief:
        return Check("memory_consolidation", True, "No memory consolidation is pending", observed=True)
    reasons = [str(reason) for reason in brief.get("reasons", []) if isinstance(reason, str)]
    if not brief.get("due") or not reasons:
        return Check("memory_consolidation", True, "No memory consolidation is pending", observed=True)
    at = str(brief.get("raised_at", "") or read_dreaming_state(paths.omh_home, paths.hermes_home).get("last_consolidated_at", "") or "unknown time")
    record_expiry = brief.get("record_expiry", {}) if isinstance(brief.get("record_expiry"), dict) else {}
    expired = int(record_expiry.get("expired", 0) or 0)
    full_pack = _unreclaimable_full_pack_message(reasons, brief)
    if full_pack and expired == 0:
        return Check("memory_consolidation", True, full_pack, severity="ok", observed=True)
    if expired > 0:
        # Expired records have an operator-runnable fix; consolidation does not.
        remedy = f"Run `omh memory retire` to archive {expired} expired record(s); OMH never deletes them."
    elif any(reason.startswith("stale_review_required") for reason in reasons):
        # Review-due records also have an operator-runnable fix now.
        remedy = "Run `omh memory confirm --all-due` to re-bless still-true review-due records; refusals are reported, never forced."
    else:
        remedy = "Ask Hermes to review and consolidate its memory; OMH prepared the brief and cannot run it."
    return Check(
        "memory_consolidation",
        True,
        f"Memory consolidation is due ({', '.join(reasons)}), raised at {at} by {brief.get('trigger', 'unknown')}. "
        + remedy,
        severity="warning",
        observed=True,
    )


_HEADROOM_REASON_PREFIX = "headroom_below_floor:"


def _unreclaimable_full_pack_message(reasons: list[str], brief: dict[str, object]) -> str:
    """The full-pack wording, or "" when this brief is asking for real work.

    Read off the brief's own fields, because those are the fields doctor
    already has: the `headroom_below_floor:<chars><=<floor>` reason carries
    both numbers, and the eviction plan the brief was built with carries
    `reclaimable_chars` and `duplicate_clusters`.

    Reasons are `headroom_below_floor:<chars><=<floor>` for MEMORY.md and
    `headroom_below_floor:<file>:<chars><=<floor>` for any other file (USER.md);
    only the first form is described by the plan, and a brief with demote rows
    never qualifies.

    Only a brief whose ENTIRE reason set is the headroom condition qualifies.
    A brief also woken by the turn interval, a compaction, expiring records,
    or a replay reminder is asking for work that can actually be done, and
    downgrading it would hide that.
    """
    if not reasons or any(not reason.startswith(_HEADROOM_REASON_PREFIX) for reason in reasons):
        return ""
    # A per-file reason (`headroom_below_floor:USER.md:34<=187`) is about a file
    # the eviction plan (MEMORY.md's) does not describe, and a brief carrying
    # demote rows is asking for work the model can do.
    if brief.get("demotion_rows") or any(not reason[len(_HEADROOM_REASON_PREFIX) :][:1].isdecimal() for reason in reasons):
        return ""
    plan = brief.get("eviction_plan")
    if not isinstance(plan, dict):
        return ""
    reclaimable = plan.get("reclaimable_chars")
    clusters = plan.get("duplicate_clusters")
    if not isinstance(reclaimable, int) or isinstance(reclaimable, bool) or reclaimable > 0:
        return ""
    if not isinstance(clusters, list) or clusters:
        return ""
    return (
        f"Hermes memory is full ({', '.join(reasons)}) and nothing in it is provably redundant "
        f"(reclaimable_chars=0, 0 duplicate group(s) across {plan.get('entry_count', 'unknown')} entry/entries). "
        "There is no consolidation for OMH to propose and OMH cannot write Hermes memory. "
        "Your move: shorten or remove an entry in Hermes memory, through Hermes' own memory tool. "
        "Reported as a standing fact, not as pending work."
    )


def _memory_record_readability_check(paths: OmhPaths) -> Check:
    """Name the record files this build cannot admit, instead of losing them.

    Refusing an unrecognized record is right; refusing it silently is not. A v1
    record without an approved review status, and any record written by a newer
    schema, were dropped by the store reader with no count in `memory status`,
    no entry in a recall pack's exclusions, and nothing here -- so a store that
    had quietly shrunk was indistinguishable from a smaller store.

    Never a fault. The records are intact on disk and nothing is lost by
    reporting them; what is lost is the operator not knowing.
    """
    _records, unreadable = scan_project_memory_records(paths)
    if not unreadable:
        return Check("memory_records", True, "Every memory record file is readable by this build", observed=True)
    by_reason: dict[str, list[str]] = {}
    for item in unreadable:
        by_reason.setdefault(str(item.get("reason", "")), []).append(str(item.get("path_name", "")))
    detail = "; ".join(f"{reason}: {', '.join(sorted(names)[:5])}" for reason, names in sorted(by_reason.items()))
    return Check(
        "memory_records",
        True,
        f"{len(unreadable)} memory record file(s) are on disk but not admitted by this build ({detail}). "
        "Run `omh memory inventory` for the full ledger; nothing was deleted.",
        severity="warning",
        observed=True,
    )


def _memory_open_records_check(paths: OmhPaths) -> Check:
    """Name the open records that have been unresolved for over half the ceiling.

    An open record is a question a person chose not to settle; it stays
    delivered and keeps costing attention on purpose. Past half of
    ``open_max_days`` the question is closer to dying unanswered than to being
    answered, and that is worth a line here where an operator looks.

    Never a fault. Nothing is broken, and OMH cannot answer the question --
    only the three verbs can -- so it is a thing to know, not a failure.
    """
    records, _unreadable = scan_project_memory_records(paths)
    ceiling = _cadence_value(read_project_memory_policy(paths), "open_max_days") or _OPEN_MAX_DAYS
    threshold = ceiling // 2
    now = datetime.now(UTC)
    aging: list[tuple[int, str]] = []
    for record in records:
        staleness = record.get("staleness") if isinstance(record.get("staleness"), dict) else {}
        if _record_resolution(staleness) != "open":
            continue
        verdict = _record_staleness(record, now=now)
        days = int(verdict.get("open_days", 0) or 0)
        if days > threshold:
            # The same label `omh memory status` prints for the row.
            aging.append((days, _redacted_metadata_label(record.get("record_id", ""))))
    if not aging:
        return Check("memory_open_records", True, f"No unresolved memory record has been open for more than {threshold} days", observed=True)
    aging.sort(key=lambda item: (-item[0], item[1]))
    named = ", ".join(f"{record_id} ({days}d)" for days, record_id in aging[:5])
    return Check(
        "memory_open_records",
        True,
        f"{len(aging)} unresolved memory record(s) have been open for more than {threshold} days "
        f"(half the {ceiling}-day open ceiling): {named}. "
        "Answer them: omh memory confirm / keep-open / retire.",
        severity="warning",
        observed=True,
    )


def _memory_provider_check(config_text: str) -> Check:
    """Report who holds Hermes' single external memory-provider slot.

    Hermes runs at most one. Leaving the slot empty is a perfectly good state --
    Hermes falls back to its built-in memory -- so this never fails on an unset
    provider. It exists because a slot silently held by something else is the
    reason OMH's hooks would not be running, and that is invisible otherwise.
    """
    selection = memory_provider_selection(config_text)
    if selection == MEMORY_PROVIDER_NAME:
        return Check("memory_provider", True, "OMH memory is on; it recalls and consolidates across sessions")
    if selection:
        return Check(
            "memory_provider",
            True,
            f"Hermes memory is handled by {selection}, so OMH memory stays off. Hermes runs one "
            "memory provider at a time; this is a working state, not a fault.",
        )
    # `omh setup` claims a free slot, so an unset one means setup has not run
    # here or someone turned it off. Point at the command an ordinary user
    # already knows rather than at the control-plane one.
    return Check(
        "memory_provider",
        True,
        "OMH memory is off. Run `omh setup` to turn it on so OMH remembers across sessions.",
    )


def _identity_conflicts_check(
    paths: OmhPaths,
    configured_dirs: list[str] | None,
    manifest: dict | None,
    *,
    config_text: str = "",
) -> Check:
    """Name every local source that also claims an OMH-facing skill, command, or hook.

    The question this answers is the one an operator actually asks: a familiar
    request triggered the wrong workflow, or a bridge tool that is installed did
    not answer -- what else on this machine holds that name? So the message
    names both sides of every contest and says which side OMH installed, rather
    than reporting that a foreign directory exists and leaving the operator to
    work out whose it is.

    It never resolves the contest. A contested skill name's outcome is read
    off Hermes' documented tier order, which is why the Hermes home's own
    skills directory and `skills.create_dir` are scanned beside the external
    directories; a contested tool name stays `unknown`, since Hermes' plugin
    load order is not readable here. This check never rewrites, renames, or
    removes anything it found. A shared lifecycle hook is reported as a
    second subscriber, not as a contest with a missing winner.
    """
    report = build_identity_conflict_report(
        skills_dir=paths.skills_dir,
        manifest=manifest,
        plugins_dir=paths.hermes_plugins_dir,
        configured_skill_dirs=configured_dirs,
        local_skills_dir=paths.hermes_home / "skills",
        create_dir=_skill_create_dir(paths, config_text),
    )
    severity = str(report["severity"])
    summary = _identity_conflict_summary(report)
    if severity == "ok":
        return Check("identity_conflicts", True, summary)
    return Check(
        "identity_conflicts",
        severity != "blocking",
        summary,
        severity=severity,
        remediation=str(report["next_action"]),
        next_action=str(report["next_action"]),
    )


def _identity_conflict_summary(report: dict) -> str:
    scanned = report["scanned"]
    header = (
        f"precedence={report['precedence']} conflicts={len(report['conflicts'])} "
        f"scanned skill_dirs={scanned['skill_dirs']} plugin_dirs={scanned['plugin_dirs']}"
    )
    # A hook is shared, not claimed: every subscriber receives the event, so the
    # line must not read as a contest one side lost (#1902). A skill's line says
    # what Hermes does with the name, from the tier order.
    details = [
        f"{conflict['kind']} name {conflict['name']} ({conflict['severity']}): {skill_conflict_outcome(conflict)}"
        if conflict["kind"] == "skill"
        else f"{conflict['kind']} name {conflict['name']} ({conflict['severity']}) "
        + ("subscribed to by " if conflict["kind"] == "hook" else "claimed by ")
        + ", ".join(f"{source['ownership']} at {source['location']}" for source in conflict["sources"])
        for conflict in report["conflicts"]
    ]
    details.extend(f"scan incomplete: {item}" for item in report["unreadable"])
    if details:
        return f"{header}: {'; '.join(details)}. {report['claim_boundary']}"
    return f"{header}. {report['claim_boundary']}"


def _skill_create_dir(paths: OmhPaths, config_text: str) -> Path | None:
    """`skills.create_dir` the way Hermes reads it: `~` and `${VAR}` expanded, relative to the Hermes home."""
    raw = skill_create_dir_selection(config_text)
    if not raw:
        return None
    path = Path(os.path.expanduser(os.path.expandvars(raw)))
    return path if path.is_absolute() else paths.hermes_home / path


# How many Hermes-edited skills the doctor line names before it counts the rest.
_HERMES_EDITS_NAMED_LIMIT = 5


def _managed_skill_roots(paths: OmhPaths, manifest: dict | None) -> list[Path]:
    """Every directory an OMH install may serve skills from: the pack, the pre-pointer copy, every generation."""
    roots = managed_skill_dir_candidates(paths, current=managed_current_workflow_pack_dir())
    generations = managed_command_generations_dir()
    if generations is not None:
        roots.append(generations)
    recorded = (manifest or {}).get("skills_dir")
    if recorded:
        roots.append(Path(str(recorded)))
    return roots


def _hermes_skill_edits_check(edited: list[dict], writes: list[LedgerWrite], unread: list[str]) -> Check:
    """OMH-managed skills holding an edit Hermes made, read from Hermes' curator ledger.

    Hermes may edit a skill in `skills.external_dirs` in place, and its
    background self-improvement review does so without being asked; every
    write lands in the home's curator ledger (`install.curator_ledger`). The
    installer keeps such a skill rather than refusing the update, so the skill
    stops receiving OMH updates, and this is where that is visible. Read only:
    the ledger is Hermes' own, and nothing here trims it or rolls anything back.

    The ledger count covers every directory an OMH install may serve skills
    from -- the managed pack, the pre-pointer copy, and every generation --
    because an edit left in a generation OMH has moved off is the one nobody
    sees otherwise. A warning, not a block: a kept edit is a working skill.
    `edited` is `hermes_edited_skills` over the same writes.
    """
    # `writes` is already cut to the managed roots (`_managed_skill_roots`).
    under_managed = {(write.ledger, write.ts, write.path) for write in writes}
    # Two different outcomes: a kept skill stays as it is on every install; an
    # edit in a directory this release does not render the skill into goes nowhere.
    kept = [item for item in edited if item["disposition"] != "left_behind"]
    left_behind = [item for item in edited if item["disposition"] == "left_behind"]
    parts: list[str] = []
    if kept:
        parts.append(
            f"{len(kept)} OMH-managed skill(s) hold a Hermes edit that installs keep, so they receive no OMH "
            f"update: {_hermes_edit_lines(kept)}"
        )
    if left_behind:
        parts.append(
            f"{len(left_behind)} Hermes edit(s) sit in a directory this release does not render the skill into, "
            f"so installs neither keep nor carry them: {_hermes_edit_lines(left_behind)}"
        )
    parts.append(
        f"Hermes' curator ledger records {len(under_managed)} skill write(s) under OMH-managed skills"
        if under_managed
        else "Hermes' curator ledger records no skill write under OMH-managed skills"
    )
    parts.extend(f"ledger unreadable: {item}" for item in unread)
    message = "; ".join(parts)
    if not edited and not unread:
        return Check("hermes_skill_edits", True, message)
    action = (
        "Move each lesson into a separately named skill you own; `omh install --force` then replaces the edited "
        "OMH skill with the current render."
        if edited
        else "Repair read access to the reported curator ledger, then rerun `omh doctor`."
    )
    return Check("hermes_skill_edits", True, message, severity="warning", remediation=action, next_action=action)


def _missing_skills_on_next_install(paths: OmhPaths, manifest: dict) -> list[dict]:
    """Missing managed skills, judged by the install a plain `omh install` would run.

    The packaged catalog under the profile the manifest records -- the one a
    run without `--core` or `--full` carries forward -- so the verdict here is
    the installer's `restored_skills` verdict, read off the same function.
    """
    names = profile_skill_names(
        paths.skills_dir, _recorded_skill_profile(manifest), [template.name for template in builtin_skill_templates()]
    )
    return missing_managed_skills(manifest, manifest_pack(manifest, paths), names)


def _recorded_skill_profile(manifest: dict) -> str:
    """The profile a run without `--core` or `--full` carries forward (`_resolved_skill_profile` in setup)."""
    profile = str(manifest.get("skill_profile") or "")
    return profile if profile in SKILL_PROFILES else DEFAULT_SKILL_PROFILE


def _missing_managed_skills_check(manifest: dict, missing: list[dict]) -> Check:
    """Managed skills whose SKILL.md is gone, and what the next install does with each.

    A warning, never a block, and never `--force` advice: nothing is refused.
    One the next install includes is rendered again; one it does not include
    (outside the recorded skill profile) is reported `not_restored` and stays
    uninstalled.
    """
    profile = _recorded_skill_profile(manifest)
    lines = [
        f"{item['name']} at {item['path']}: "
        + (
            "the next install renders it again and reports it under restored_skills"
            if item["disposition"] == "restored"
            else f"the recorded {profile} profile does not include it, so the next install reports it "
            "not_restored and leaves it uninstalled"
        )
        for item in missing
    ]
    action = "No --force is needed: the next install handles each missing skill as listed."
    return Check(
        "missing_managed_skills",
        True,
        f"{len(missing)} managed skill(s) are missing their SKILL.md: {'; '.join(lines)}",
        severity="warning",
        remediation=action,
        next_action=action,
    )


def _hermes_edit_lines(items: list[dict]) -> str:
    named = [_hermes_edit_line(item) for item in items[:_HERMES_EDITS_NAMED_LIMIT]]
    if len(items) > _HERMES_EDITS_NAMED_LIMIT:
        named.append(f"and {len(items) - _HERMES_EDITS_NAMED_LIMIT} more")
    return "; ".join(named)


def _hermes_edit_line(item: dict) -> str:
    detail = " ".join(str(item[key]) for key in ("actor", "action", "ts") if item.get(key))
    return f"{item['name']} at {item['path']}" + (f" ({detail})" if detail else "")


def run_doctor_advisories(paths: OmhPaths, *, personal_files: bool = True) -> AdvisoryReport:
    """Read-only Hermes config advisory lane.

    Deliberately SEPARATE from ``run_doctor``: advisory entries are never
    appended to the ``list[Check]`` consumed by ``doctor_ok()`` or
    ``recommended_next_action()``, so they cannot change the doctor exit code.
    ``personal_files=False`` reports the SOUL.md and Hermes memory inspectors
    as ``skipped`` without opening those files.
    """
    return run_config_advisories(
        paths.hermes_home,
        omh_home=paths.omh_home,
        discovery_home=paths.hermes_home.parent,
        personal_files=personal_files,
        # The pack this command resolved, not one rebuilt from `omh_home`,
        # which on a managed install is the pre-pointer copy or nothing (#2358).
        skills_dir=paths.skills_dir,
    )


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
            if check.severity == "warning" and check.next_action and _warning_priority(check.name) > 0
        ),
        key=lambda check: _warning_priority(check.name),
        reverse=True,
    )
    if prioritized_warnings:
        return prioritized_warnings[0].next_action
    return DEFAULT_DOCTOR_NEXT_ACTION


def _awareness_delivery_check(paths: OmhPaths, *, now: datetime | None = None) -> Check:
    """Has OMH's primer and route hint hook returned content for model input?

    The awareness system prompt section counts too, once per session, on the
    first `pre_llm_call` that leaves the primer to it: on a host that renders
    it the primer is in no hook payload. A render with no turn behind it
    (`hermes prompt-size`, a routed review fork) counts nothing.

    Reported, never blocking. A fresh install has legitimately delivered
    nothing, and Hermes may not have been restarted since the bundle changed, so
    a zero here is ambiguous in a way `plugin_enabled_in_hermes` is not. What it
    buys is a way to tell "the hook is on but returning nothing" from "the hook
    returned an injection payload". It does not prove host or model consumption.
    """
    from ..plugin_bundle.omh.awareness_delivery import read_awareness_delivery

    record = read_awareness_delivery(str(paths.omh_home))
    if record.get("unreadable"):
        action = "Delete the ledger and run one Hermes turn to repopulate it."
        return Check(
            "awareness_delivery",
            True,
            "awareness delivery ledger is unreadable",
            severity="warning",
            observed=False,
            remediation=action,
            next_action=action,
        )
    delivered = int(record.get("delivery_count", 0) or 0)
    if not delivered:
        first_attempted_at = str(record.get("first_attempted_at") or "")
        try:
            first_attempted = datetime.fromisoformat(first_attempted_at.replace("Z", "+00:00"))
            if first_attempted.tzinfo is None:
                first_attempted = None
        except ValueError:
            first_attempted = None
        current_time = now or datetime.now(UTC)
        if first_attempted is not None and current_time - first_attempted.astimezone(UTC) >= timedelta(
            days=AWARENESS_ZERO_DELIVERY_WARNING_DAYS
        ):
            action = (
                "Restart Hermes, run one Hermes turn, then rerun `omh doctor`; "
                "if delivery remains zero, inspect the OMH plugin hook logs."
            )
            return Check(
                "awareness_delivery",
                False,
                (
                    "no OMH awareness hook payload returned for model input for at least "
                    f"{AWARENESS_ZERO_DELIVERY_WARNING_DAYS} days; "
                    f"first observed hook attempt: {first_attempted_at}"
                ),
                severity="warning",
                observed=False,
                remediation=action,
                next_action=action,
            )
        return Check(
            "awareness_delivery",
            True,
            (
                "no OMH awareness hook payload returned for model input yet; run one Hermes turn, "
                "restarting Hermes first if the bundle changed"
            ),
            severity="ok",
            observed=False,
        )
    return Check(
        "awareness_delivery",
        True,
        (
            f"{delivered} awareness hook payload(s) or system prompt section deliveries returned, "
            f"{int(record.get('route_hint_count', 0) or 0)} with a route hint; "
            f"last at {record.get('last_delivered_at', 'unknown')}"
        ),
    )


DESKTOP_HALF_FILES = ("desktop/plugin.js", "dashboard/manifest.json", "dashboard/plugin_api.py")


def _plugin_desktop_half_check(paths: OmhPaths) -> Check:
    """Does the installed bundle carry its Hermes Desktop half?

    Hermes Desktop copies ``desktop/plugin.js`` out of the installed bundle
    into its own ``desktop-plugins/omh/``, and the gateway mounts the
    ``dashboard/plugin_api.py`` that ``dashboard/manifest.json`` names. All
    three files ship in the bundle, so a bundle installed before they existed
    is the one condition OMH can observe from here. Whether the app made its
    copy and whether the half is switched on live inside the app (its
    renderer storage), so this check reports presence and never enablement.
    """
    plugin_dir = paths.hermes_plugin_dir
    missing = [relative for relative in DESKTOP_HALF_FILES if not (plugin_dir / relative).is_file()]
    if not missing:
        return Check(
            "plugin_desktop_half",
            True,
            (
                f"Hermes Desktop half present in the installed bundle ({plugin_dir}); "
                "it ships off; switch it on in Hermes Desktop under Capabilities -> Plugins"
            ),
        )
    return Check(
        "plugin_desktop_half",
        True,
        f"installed bundle predates the Hermes Desktop half (missing {', '.join(missing)})",
        severity="warning",
        next_action=(
            f"run `{HERMES_PLUGIN_UPDATE_COMMAND}`; Hermes installed this bundle and OMH does not write it"
            if host_managed_plugin(plugin_dir) is not None
            else "run `omh update` to refresh the managed plugin bundle"
        ),
    )


def _plugin_enabled_check(paths: OmhPaths) -> Check:
    """Is the installed bridge actually switched on in Hermes?

    Every other plugin check asks whether the bundle is installed, importable,
    and registrable. None of them ask whether Hermes will load it, and that is a
    separate switch in `plugins.enabled`. An install can pass all of them while
    the plugin sits disabled, which is exactly what a live check found: doctor
    reported `Hermes registration: ok (4/4)` while no OMH tool was reachable in
    chat, so the whole tool surface was dark with nothing reporting it.
    """
    config_path = paths.hermes_config_path
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Check(
            "plugin_enabled_in_hermes",
            True,
            f"no Hermes config at {config_path} yet; enablement cannot be read",
            severity="ok",
            observed=False,
        )
    except OSError as exc:
        return Check(
            "plugin_enabled_in_hermes",
            True,
            f"Hermes config unreadable: {exc}",
            severity="warning",
            observed=False,
            next_action="Make the Hermes config readable, then rerun `omh doctor`.",
        )
    # A file Hermes cannot read as a list is reported before the switch is:
    # the line reader used to attribute items under `enabled: '[]'` to the
    # key and this check passed over a config Hermes refused (#1825).
    shape_error = plugin_enablement_shape_error(config_text)
    if shape_error:
        return Check(
            "plugin_enabled_in_hermes",
            False,
            f"{config_path}: {shape_error}",
            remediation=(
                f"Edit {config_path} so `plugins.enabled` is a YAML block list "
                f"with `- {PLUGIN_NAME}` under it."
            ),
            next_action=(
                f"Edit {config_path} so `plugins.enabled` is a YAML block list, "
                "then rerun `omh doctor`."
            ),
        )
    # "Not enabled" is a claim about Hermes' config, and this check may state
    # it only over a node it read. A `plugins` node outside the two forms the
    # reader follows leaves the same empty lists a config enabling nothing
    # leaves, and reporting the second as the first told operators to enable a
    # plugin their host already loads (#1814).
    if not plugin_enablement_is_readable(config_text):
        return Check(
            "plugin_enabled_in_hermes",
            True,
            (
                f"{config_path} writes `plugins` in a form OMH does not read, so whether "
                f"`{PLUGIN_NAME}` is enabled was not established"
            ),
            severity="warning",
            observed=False,
            next_action=(
                f"Rewrite `plugins` in {config_path} as a `plugins:` block with "
                f"`  enabled:` under it, then rerun `omh doctor`."
            ),
        )
    if plugin_is_enabled(config_text, PLUGIN_NAME):
        return Check(
            "plugin_enabled_in_hermes",
            True,
            f"`{PLUGIN_NAME}` is enabled in {config_path}",
        )
    listed = plugin_enablement(config_text)
    reason = "listed as disabled" if PLUGIN_NAME in listed["disabled"] else "not in plugins.enabled"
    return Check(
        "plugin_enabled_in_hermes",
        False,
        (
            f"`{PLUGIN_NAME}` is installed but {reason} in {config_path}; "
            "Hermes will not load it, so no OMH tool is reachable in chat"
        ),
        remediation=f"Run `hermes plugins enable {PLUGIN_NAME}`.",
        next_action=f"Run `hermes plugins enable {PLUGIN_NAME}`, then restart or reload Hermes and rerun `omh doctor`.",
    )


def _plugin_omh_home_binding_check(paths: OmhPaths, config_text: str) -> Check:
    """Does the plugin loaded from this Hermes home bind the store doctor is checking?

    The plugin reads its home's `plugins.entries.omh.settings.omh_home`, then
    the Hermes process's `OMH_HOME`, then `~/.omh`. An install at any other
    store with no setting had a plugin reading another install's manifest and
    writing its runtime state there, while every check above passed against
    the store the install was made at (#1960). A warning, not a blocker:
    Hermes may well be started with `OMH_HOME` exported, which doctor cannot
    see from here.

    Binding the right store with nothing named is only half an answer: a
    multiplexed process (a gateway serving several profiles, Desktop
    `serve`) reads neither the process `OMH_HOME` nor `~/.omh`, and refuses
    to load the plugin for a home that names no store in its setting or its
    own `.env`. A default-store install set up before #2037 is exactly that,
    and passed here while no `omh_*` tool registered in any of them.
    """
    config_path = paths.hermes_config_path
    repair = (
        f"Run `omh --omh-home {paths.omh_home} --hermes-home {paths.hermes_home} setup` to record "
        f"`plugins.entries.omh.settings.omh_home`, or start Hermes with `OMH_HOME={paths.omh_home}`."
    )
    try:
        found, value = runtime_paths.omh_home_setting(config_text)
        if found:
            bound = runtime_paths.expand_path(value, hermes_home=paths.hermes_home, relative_to=paths.hermes_home)
        else:
            bound = runtime_paths.unset_launch_omh_home(paths.hermes_home)
    except runtime_paths.RuntimeBindingError as exc:
        return Check(
            "plugin_omh_home_binding",
            True,
            f"the OMH home the plugin in {paths.hermes_home} binds could not be read: {exc}",
            severity="warning",
            observed=False,
            next_action=f"Fix `plugins.entries.omh.settings.omh_home` in {config_path}, then rerun `omh doctor`.",
        )
    if bound == paths.omh_home and not found and not env_key_names(paths.hermes_home, allowed=("OMH_HOME",)):
        return Check(
            "plugin_omh_home_binding",
            True,
            (
                f"the plugin in {paths.hermes_home} names no OMH home: it binds {paths.omh_home} as its own "
                "Hermes process, but a multiplexed one (a gateway serving several profiles, Desktop `serve`) "
                "refuses to load it"
            ),
            severity="warning",
            next_action=(
                f"Run `omh --omh-home {paths.omh_home} --hermes-home {paths.hermes_home} update` to record "
                f"`plugins.entries.omh.settings.omh_home` in {config_path}, then restart the gateway."
            ),
        )
    if bound == paths.omh_home:
        return Check(
            "plugin_omh_home_binding",
            True,
            f"the plugin in {paths.hermes_home} binds {paths.omh_home}"
            + (" (plugins.entries.omh.settings.omh_home)" if found else ""),
        )
    if found:
        return Check(
            "plugin_omh_home_binding",
            True,
            (
                f"the plugin in {paths.hermes_home} binds {bound} (plugins.entries.omh.settings.omh_home), "
                f"not {paths.omh_home}, the OMH home this doctor run checked"
            ),
            severity="warning",
            next_action=(
                f"Rerun `omh doctor` with `--omh-home {bound}`, or change "
                f"`plugins.entries.omh.settings.omh_home` in {config_path} if {paths.omh_home} is the store it should use."
            ),
        )
    return Check(
        "plugin_omh_home_binding",
        True,
        (
            f"the plugin in {paths.hermes_home} names no OMH home, so it binds {bound} "
            f"unless Hermes is started with OMH_HOME={paths.omh_home}; this doctor run checked {paths.omh_home}"
        ),
        severity="warning",
        next_action=repair,
    )


def _profile_omh_home_binding_checks(paths: OmhPaths) -> list[Check]:
    """A bot profile whose plugin binds a store other than the one it names, or none.

    Two findings, one row per affected profile, named after it, as
    `_external_dir_ambiguity_checks` does; each a warning with `ok=True`,
    because the primary home does not share it.

    A profile that names no store, under any primary: with neither a
    `settings.omh_home` nor an `.env` `OMH_HOME` its plugin is refused in a
    multiplexed process (#2037), and under a primary whose store is not
    `~/.omh` it binds `~/.omh` when the profile runs as its own Hermes
    process while its managed skills come from the primary's store
    (#1967).

    A profile whose `.env` names `OMH_HOME` beside a `settings.omh_home` OMH
    did not write, under any primary: the setting outranks the `.env` in the
    plugin's resolver, so the profile's `.env` choice (#1679) is ignored.
    Update takes back only a value its record says it wrote (#1973), so this
    one stays until somebody removes it.
    """
    unset = runtime_paths.unset_launch_omh_home()
    state = read_state(paths) or {}
    record = state.get(MANAGED_CONFIG_WRITES_STATE_KEY)
    checks: list[Check] = []
    for name, profile_dir in hermes_profile_dirs(paths.hermes_home):
        config_path = _profile_paths(paths, profile_dir).hermes_config_path
        env_path = profile_dir / ".env"
        env_names_store = bool(env_key_names(profile_dir, allowed=("OMH_HOME",)))
        try:
            found, value = runtime_paths.omh_home_setting(read_config(config_path))
        except runtime_paths.RuntimeBindingError:
            # A setting the plugin's scan refuses is still the profile's own.
            found, value = True, None
        if found and value and env_names_store:
            keys = load_managed_config_writes(record, config_path=config_path).get("keys")
            if isinstance(keys, dict) and keys.get(PLUGIN_OMH_HOME_KEY) == value:
                # OMH's own write: the next update takes it back.
                continue
            checks.append(
                Check(
                    f"plugin_omh_home_binding:{name}",
                    True,
                    (
                        f"bot profile {name} names OMH_HOME in {env_path}, but its "
                        f"plugins.entries.omh.settings.omh_home ({value}) outranks it, and OMH did not write it"
                    ),
                    severity="warning",
                    next_action=(
                        f"Remove `plugins.entries.omh.settings.omh_home` from {config_path} to use the "
                        f"`.env` store, or remove `OMH_HOME` from {env_path} to keep the setting."
                    ),
                )
            )
            continue
        if found or env_names_store:
            continue
        checks.append(
            Check(
                f"plugin_omh_home_binding:{name}",
                True,
                (
                    f"bot profile {name} names no OMH home, so a multiplexed Hermes process (a gateway serving "
                    "several profiles, Desktop `serve`) refuses to load its plugin"
                    + (
                        ""
                        if paths.omh_home == unset
                        else f", and as its own process it binds {unset} while its managed skills come from {paths.omh_home}"
                    )
                ),
                severity="warning",
                next_action=(
                    f"Run `omh --omh-home {paths.omh_home} --hermes-home {paths.hermes_home} update` to record "
                    f"`plugins.entries.omh.settings.omh_home` in {config_path}, or name the profile's own store "
                    f"there or as `OMH_HOME` in {env_path}."
                ),
            )
        )
    return checks


def _plugins_enabled_extension_check(paths: OmhPaths, config_text: str, config_present: bool) -> Check:
    """Can setup read `plugins.enabled` as a list and add to it?"""
    config_path = paths.hermes_config_path
    if not config_present:
        return Check(
            "hermes_config_plugins_enabled",
            True,
            f"no Hermes config at {config_path} yet; setup will write plugins.enabled",
            observed=False,
        )
    error = plugins_enabled_extension_error(config_text, PLUGIN_NAME)
    if not error:
        return Check(
            "hermes_config_plugins_enabled",
            True,
            f"plugins.enabled in {config_path} is a list setup can extend",
        )
    return Check(
        "hermes_config_plugins_enabled",
        False,
        f"{config_path}: {error}",
        remediation=(
            f"Edit {config_path} so `plugins.enabled` is a YAML block list "
            f"(`enabled:` over `    - {PLUGIN_NAME}`)."
        ),
        next_action=(
            f"Edit {config_path} so `plugins.enabled` is a YAML block list, "
            "then rerun `omh setup` and `omh doctor`."
        ),
    )


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


def _skill_freshness_check(paths: OmhPaths, manifest: dict, *, exclude: set[str] | None = None) -> Check:
    """Detect installed skills whose content an older OMH release wrote.

    `local_modifications` compares the skills directory against the manifest
    recorded at install time, so it stays green when the omh package moves on
    and the installed guidance quietly ages: Hermes keeps executing skill
    text from a version the operator no longer runs. This check compares the
    untouched installed files against what the running package would render
    today and points a mismatch at `omh update`. Locally edited files are
    excluded here because `local_modifications` already owns that report, and
    so are the paths in `exclude`: a skill the installer keeps for a Hermes
    edit is held back on purpose, and `hermes_skill_edits` reports it.

    The message reports catalog revisions, not a package version pair, because
    the revision is what the finding was derived from. Catalog content moves
    without a version bump on every preview build, and the version pair then
    read `installed by omh 2.0.3, but this omh is 2.0.3` -- a sentence that
    contradicts itself while asserting a real problem, so a user could not act
    on it. `catalog_revision` is the identifier `guidance_projection` already
    names, so the two checks describe one condition in one vocabulary.

    A revision pair has the same failure mode, so it is printed only when there
    are two revisions to print. A manifest that records the current revision
    over files that do not match it is a real state -- it is what a rewritten
    or partially repaired manifest leaves behind -- and it is reported as that
    disagreement rather than as one digest quoted against itself.
    """
    source = str(manifest.get("source", "builtin"))
    if source != "builtin":
        return Check(
            "skill_freshness",
            True,
            f"skills installed from local source {source!r}; freshness vs the packaged catalog is not comparable",
        )
    manifest_sha_by_rel = {
        str(record.get("path", "")): str(record.get("sha256", ""))
        for record in manifest.get("skills", [])
        if isinstance(record, dict)
    }
    stale: list[str] = []
    for template in builtin_skill_templates():
        rel = f"{omh_skill_install_path(template.name)}/SKILL.md"
        if rel not in manifest_sha_by_rel or rel in (exclude or set()):
            continue
        path = paths.skills_dir / rel
        if not path.is_file():
            continue
        installed_sha = sha256_file(path)
        if installed_sha == sha256_text(template.content):
            continue
        if installed_sha != manifest_sha_by_rel[rel]:
            continue
        stale.append(template.name)
    current_revision = catalog_revision()
    installed_revision = str(manifest.get("catalog_revision", "")) or "unrecorded"
    if not stale:
        return Check(
            "skill_freshness",
            True,
            f"installed managed skills match catalog_revision={current_revision[:12]}",
        )
    listed = ", ".join(sorted(stale)[:5]) + (", ..." if len(stale) > 5 else "")
    if installed_revision == current_revision:
        # The manifest claims the generation this package renders and the files
        # recorded under it do not match it, so there is no second revision to
        # name. Printing the pair anyway would repeat one digest twice, which
        # is the self-contradicting shape the version pair had.
        detail = (
            f"the install manifest records catalog_revision={current_revision[:12]} "
            "but these files do not match it"
        )
    else:
        detail = (
            f"installed_revision={installed_revision[:12]} "
            f"catalog_revision={current_revision[:12]}"
        )
    return Check(
        "skill_freshness",
        False,
        f"{len(stale)} managed skill(s) do not match the catalog this omh renders ({detail}): {listed}",
        remediation="Run `omh update` to regenerate the managed skills from the current package catalog.",
        next_action="Run `omh update`, then `omh doctor` again.",
    )


def _route_hint_skills_check(paths: OmhPaths) -> Check:
    """Do the skills the per-turn route hint can name resolve to installed skills?

    The plugin cuts the route hint and the skill-candidate line to the skills
    the install manifest records (`plugin_bundle/omh/installed_skills.py`),
    and falls back to the whole catalog when it cannot read that record. This
    check asks the plugin's own reader, so it sees what the hint sees, and
    compares the answer with the skill directories on disk. It fires when a
    manifest is missing or unreadable beside a partial install, and when the
    manifest still records a skill whose directory is gone (#1954): in both
    the model is told to `skill_view` a name that returns not found.

    A warning, not a block: the hint only suggests, and a model can recover
    from a missing skill. Whether a running Hermes loaded a plugin that
    filters at all is not observed here.
    """
    on_disk = set(installed_skill_names(paths.skills_dir))
    if not on_disk:
        return Check(
            "route_hint_skills",
            True,
            f"no OMH skills installed under {paths.skills_dir}; nothing for route hints to name",
            observed=False,
        )
    hint_view = hint_installed_skill_names(paths.omh_home)
    catalog = [template.name for template in builtin_skill_templates()]
    nameable = [name for name in catalog if not skill_not_installed(name, hint_view)]
    missing = sorted(omh_skill_install_path(name).split("/")[-1] for name in nameable if name not in on_disk)
    if not missing:
        return Check(
            "route_hint_skills",
            True,
            f"route hints can name {len(nameable)} skill(s), all installed",
        )
    listed = ", ".join(missing[:5]) + (", ..." if len(missing) > 5 else "")
    if hint_view is None:
        cause = (
            f"the install manifest {paths.manifest_path} is missing or unreadable, so route hints fall back "
            "to the whole catalog"
        )
    else:
        cause = f"the install manifest {paths.manifest_path} records skills whose directories are gone"
    return Check(
        "route_hint_skills",
        True,
        f"{cause}; they can name {len(missing)} skill(s) that are not installed: {listed}",
        severity="warning",
        remediation="Run `omh update` to rewrite the install manifest from the skills on disk.",
        next_action="Run `omh update`, then `omh doctor` again.",
        detail={"not_installed": missing},
    )


def _support_readable_paths(paths: OmhPaths) -> tuple[OmhPaths, Check | None]:
    """`paths` with the bootstrap generation's link read as the legacy pack, as the installer reads it.

    `legacy_support_paths` is the installer's own translation, so doctor and
    `omh update` judge the same directory: it accepts only the migration's
    direct link from `generations/bootstrap-legacy/skills` to this home's
    pre-pointer pack and refuses any other link. Every path that is not that
    link comes back unchanged. A refused link is returned as a blocking check
    naming it, with the untranslated paths, because the update the operator
    would run next refuses the same link.
    """
    try:
        return legacy_support_paths(paths), None
    except OmhError as exc:
        return paths, Check(
            "skills_dir_link",
            False,
            f"{paths.skills_dir} is a link OMH does not read through: {exc}",
            remediation=(
                "Point the bootstrap-legacy generation's `skills` link directly at this home's "
                "`<omh_home>/skills`, or remove the stray link, then run `omh update`."
            ),
            next_action="Repair the skills link named here, then run `omh doctor` again.",
        )


def _guidance_projection_check(paths: OmhPaths, manifest: dict | None, *, registered: bool) -> Check:
    """Report the Hermes-visible guidance projection as one answer with four axes.

    `manifest`, `local_modifications`, `skill_freshness`, `external_dir`, and
    `runtime_context` each answer a fragment, and an operator reading them has
    to work out which fragment is the actual problem. This check names the
    catalog revision the projection was rendered from and states freshness,
    drift, registration, and observed host use as four separate values, so the
    repair is not guessed from a list of booleans.

    It fails only on the axis the others do not own: whether the projection is
    current and untampered. Registration keeps its own check, and observed host
    use is never a failure -- OMH cannot see a running Hermes from here, so
    `not_observed` is the honest resting state, not a fault.
    """
    try:
        status = build_guidance_projection_status(
            paths.skills_dir,
            manifest,
            registered=registered,
            host_observed=False,
        )
    except OmhError as exc:
        # The support reader refused a path in the pack; `local_modifications`
        # names the same refusal, and the rest of the report still runs.
        return Check("guidance_projection", False, f"projection not read: {exc}")
    projection = str(status["projection"])
    drift = str(status["drift"])
    current = projection in {"fresh", "not_comparable"} and drift in {"clean", "unknown"}
    summary = (
        f"projection={projection} drift={drift} registration={status['registration']} "
        f"host_observation={status['host_observation']} catalog_revision={str(status['catalog_revision'])[:12]}"
    )
    if current:
        return Check("guidance_projection", True, summary)
    return Check(
        "guidance_projection",
        False,
        summary,
        remediation=str(status["next_action"]),
        next_action=str(status["next_action"]),
    )


def _hook_integrity_check(paths: OmhPaths) -> Check:
    """Report the reviewed native hooks as one answer with six axes.

    `plugin_bundle_current` already notices that *some* managed file drifted,
    but it says so at bundle grain: an operator learns the bundle is stale and
    not that `pre_llm_call` specifically is no longer the hook that was
    reviewed, nor which capability that takes down. This check names the axis
    that failed -- digest, event scope, timeout, review, host target, or
    revocation -- and lists every hook dropped from the managed projection with
    the command that brings it back.

    It fails only on an actual exclusion or an unreadable revocation ledger.
    An uninstalled bundle is not a fault: the reviewed digests are still the
    reviewed digests, nothing has changed them, and failing here would make
    every machine that has not run `omh setup` yet look tampered with.
    """
    status = build_hook_integrity_status(paths)
    records = status["records"]
    excluded = status["excluded_hooks"]
    summary = (
        f"managed={len(status['managed_hooks'])}/{len(records)} digest={status['digest_state']} "
        f"event_scope={len(VALID_HOOK_EVENTS)} review={status['review_state']} "
        f"host_target={HOOK_HOST_TARGET} revocation={status['revocation_state']} "
        f"ledger={status['revocation_ledger']} observed={status['observed_in_this_environment']}"
    )
    if not excluded and status["revocation_ledger"] != "unreadable":
        return Check("plugin_hook_integrity", True, summary)
    # A tree `hermes plugins install` wrote carries the hook bytes of the
    # commit Hermes pinned, which lags or leads the installed OMH package after
    # either side updates. A digest mismatch there is version skew, not
    # tampering, and `omh setup --force` does not write that tree; only a
    # revocation, a missing review, or an unreadable ledger still fails.
    untrusted = [record for record in records if not record["trusted"]]
    skew_only = all(
        record["digest"] in {"changed", "missing"}
        and record["revocation"] != "revoked"
        and record["review"] != "unreviewed"
        for record in untrusted
    )
    if host_managed_plugin(paths.hermes_plugin_dir) is not None and skew_only and status["revocation_ledger"] != "unreadable":
        skewed = ", ".join(str(record["name"]) for record in untrusted)
        return Check(
            "plugin_hook_integrity",
            True,
            (
                f"{summary}; the plugin was installed by Hermes and its hooks ({skewed}) differ from the "
                "installed OMH package's reviewed digests: version skew between the Hermes pin and OMH, "
                "not a local edit OMH can repair"
            ),
            severity="warning",
            next_action=f"Run `{HERMES_PLUGIN_UPDATE_COMMAND}` (or `omh update`) so the two versions meet, then rerun `omh doctor`.",
        )
    detail = "; ".join(str(item["repair"]) for item in excluded)
    if status["revocation_ledger"] == "unreadable":
        detail = f"{status['revocation_ledger_path']} is unreadable" + (f"; {detail}" if detail else "")
    return Check(
        "plugin_hook_integrity",
        False,
        f"{summary}; {detail}",
        remediation=str(status["next_action"]),
        next_action=str(status["next_action"]),
    )


def _plugin_host_managed_message(plugin: dict) -> str:
    host = plugin.get("plugin_host_install") or {}
    revision = str(host.get("revision", ""))[:8] or "unknown revision"
    return (
        f"{plugin['plugin_dir']} was installed by Hermes ({host.get('installer', 'hermes')} @ {revision}); "
        + (
            "its files match the installed OMH package; "
            if plugin.get("plugin_host_matches_package")
            else "its files differ from the installed OMH package (version skew between the Hermes pin and OMH); "
        )
        + "OMH leaves it in place and manages skills and config only; update the plugin with "
        + f"`{host.get('update_command', 'hermes plugins update omh')}`"
    )


def _plugin_bridge_remediation(plugin: dict) -> str:
    if plugin.get("plugin_host_managed"):
        return "Run `hermes plugins update omh`; OMH does not write a plugin directory Hermes installed."
    if plugin.get("plugin_bundle_stale"):
        return "Run `omh setup` to refresh the managed plugin bridge from the current OMH package."
    return "Run `omh setup`; use `omh setup --force` only if replacing local plugin edits is intended."


def _plugin_bridge_next_action(plugin: dict) -> str:
    if plugin.get("plugin_host_managed"):
        return "Run `hermes plugins update omh`, then `omh doctor` again."
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
