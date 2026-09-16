from __future__ import annotations
from ..skills.catalog import omh_skill_install_path

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .advisory import AdvisoryReport, run_config_advisories
from .structural_search import inspect_structural_search
from ..command_path import inspect_omh_command_path
from ..config_adapter import (
    external_dir_registered,
    external_dirs,
    memory_provider_selection,
    plugin_enablement,
    plugin_is_enabled,
    read_config,
)
from ..hashutil import sha256_file, sha256_text
from ..local_store import can_write_dir
from ..install.guidance_projection import build_guidance_projection_status, catalog_revision
from ..install.hook_integrity import HOOK_HOST_TARGET, VALID_HOOK_EVENTS, build_hook_integrity_status
from ..install.identity_conflicts import build_identity_conflict_report
from ..install.installer import installed_skill_directories
from ..install.plugin_loader_observation import observe_real_loader_registration
from ..manifest import local_modifications, read_manifest
from ..paths import OmhPaths
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
from ..plugin_observations import (
    PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS,
    latest_plugin_host_observation,
    plugin_host_runtime_readiness,
)
from ..plugin_pack import PLUGIN_NAME, inspect_plugin_bundle
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
    "target_topology": 80,
    "awareness_delivery": 70,
}
AWARENESS_ZERO_DELIVERY_WARNING_DAYS = 7
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
        checks.append(_skill_freshness_check(paths, manifest))
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
        path = paths.skills_dir / omh_skill_install_path(skill) / "SKILL.md"
        checks.append(Check(f"skill:{skill}", path.exists(), str(path)))
    config_text = read_config(paths.hermes_config_path)
    dirs = external_dirs(config_text)
    hermes_config_present = paths.hermes_config_path.exists()
    checks.append(Check("hermes_config", hermes_config_present, f"{paths.hermes_config_path}"))
    # By text or by real path: the installer registers the `current` pointer,
    # the running command knows its generation, and both name this directory.
    external_registered = external_dir_registered(dirs, paths.skills_dir)
    checks.append(Check("external_dir", external_registered, f"{paths.skills_dir} in skills.external_dirs"))
    # `None`, not `dirs`, when the config is absent: `read_config` returns "" for
    # a missing file, so an empty list there would read as "Hermes registers no
    # foreign directory" when the truth is that Hermes was never asked.
    checks.append(_identity_conflicts_check(paths, dirs if hermes_config_present else None, manifest))
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
        observe_real_loader_registration(paths.hermes_plugin_dir)
        if plugin["plugin_dir_installed"]
        else None
    )
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
                _plugin_loader_observation_check(loader_observation),
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
    checks.append(_retired_skill_install_check(paths))
    checks.append(_flat_skill_layout_check(paths))
    checks.append(_plugin_ulw_lifecycle_check(paths))
    checks.extend(_hermes_tui_checks(paths))
    checks.append(_hermes_model_routing_check(paths))
    checks.append(_provider_entitlements_check(paths))
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


def _hermes_tui_checks(paths: OmhPaths) -> list[Check]:
    """Hermes-side TUI preflight findings.

    The OMH HUD/todo surface renders only inside Hermes' modern TUI, and none
    of the conditions for that are visible from OMH's own install state. An
    old Hermes, a stripped widget SDK, an unset ``display.interface``, or a
    stale embedded interpreter each degrade to a silent no-render — doctor
    names the condition and the repair instead of leaving the user to diff
    screenshots.
    """
    from .hermes_tui import hermes_tui_preflight

    preflight = hermes_tui_preflight(paths)
    install = preflight["install"]
    if not install["found"]:
        return [
            Check(
                "hermes_tui_support",
                True,
                f"Hermes install not found at {install['path']}; TUI checks skipped",
                observed=False,
            )
        ]
    # Every check keeps ok=True: the HUD is an optional surface, and the
    # sibling degraded-optional checks (command_path, plugin_runtime_observed,
    # memory_records) deliberately never flip the doctor exit code or the
    # persisted last_doctor.ok over one. Degraded states carry
    # severity="warning" plus a next action instead.
    checks: list[Check] = []
    loader = preflight["widget_loader"]
    version = str(install.get("version") or "unknown")
    checks.append(
        Check(
            "hermes_tui_support",
            True,
            (
                f"Hermes {version} ships the TUI widget loader ({loader['marker']})"
                if loader["present"]
                else (
                    f"no TUI widget loader found in Hermes {version} — an old Hermes predates the modern TUI; "
                    "a changed Hermes layout can also hide it from this check"
                )
            ),
            severity="ok" if loader["present"] else "warning",
            next_action=(
                ""
                if loader["present"]
                else "run `hermes update`; if `hermes --tui` already renders the HUD, report this check instead"
            ),
        )
    )
    sdk = preflight["sdk_surface"]
    if sdk["checked"]:
        if not sdk["parsed"]:
            sdk_message = "Hermes widget SDK export changed shape; the OMH surface cannot be verified from here"
            sdk_severity = "warning"
            sdk_action = "if the HUD stops rendering, report the incompatibility"
        elif sdk["missing"]:
            sdk_message = (
                f"Hermes widget SDK no longer exposes: {', '.join(sdk['missing'])} — the loader will skip the OMH widget"
            )
            sdk_severity = "warning"
            sdk_action = "run `omh update` for a compatible widget, or report the incompatibility"
        else:
            sdk_message = "Hermes widget SDK exposes every API the OMH widget uses"
            sdk_severity = "ok"
            sdk_action = ""
        checks.append(
            Check(
                "hermes_tui_sdk_surface",
                True,
                sdk_message,
                severity=sdk_severity,
                next_action=sdk_action,
            )
        )
    # OMH defaults fresh installs to Hermes' modern TUI and may replace a
    # canonical display choice after the operator accepts the setup/update
    # prompt. A declined or noncanonical choice stays user-owned. Doctor names
    # the shared behavior of the two launchers and the exact repair path.
    interface = preflight["display_interface"]
    hud_hint = (
        "run `omh setup` or interactive `omh update` and accept the branded TUI; "
        "`hermes --tui` opens it for one session without changing the setting"
    )
    if interface["explicit"] and interface["value"] not in ("", "tui"):
        message = (
            f"display.interface is {interface['value']!r} — bare `omh` and `hermes` both open the classic REPL, "
            "which loads no OMH HUD widget"
        )
        interface_severity = "ok"
        interface_action = hud_hint
    elif interface["explicit"]:
        message = "display.interface is 'tui' — bare `omh` and `hermes` both open the modern TUI, where the OMH HUD renders"
        interface_severity = "ok"
        interface_action = ""
    else:
        message = (
            "display.interface is unset, so bare `omh` and `hermes` both open Hermes' default classic REPL, "
            "which loads no OMH HUD widget"
        )
        interface_severity = "ok"
        interface_action = hud_hint
    checks.append(
        Check(
            "hermes_tui_interface_default",
            True,
            message,
            severity=interface_severity,
            next_action=interface_action,
        )
    )
    widget = preflight["widget"]
    widget_degraded = not widget["installed"] or (bool(widget["interpreter"]) and not widget["interpreter_ok"])
    if not widget["installed"]:
        widget_message = "OMH status widget is not installed under tui-widgets/"
    elif widget["interpreter"] and not widget["interpreter_ok"]:
        widget_message = (
            f"OMH status widget points at a missing Python interpreter ({widget['interpreter']})"
        )
    else:
        widget_message = "OMH status widget installed and its embedded interpreter resolves"
    checks.append(
        Check(
            "hermes_tui_widget_state",
            True,
            widget_message,
            severity="warning" if widget_degraded else "ok",
            next_action="run `omh setup` to (re)install the managed TUI widget" if widget_degraded else "",
        )
    )
    if widget["installed"]:
        # A widget from an older OMH loads and runs, so every check above
        # stays green while the HUD renders yesterday's surface beside the
        # prompt — the exact "it still looks like the old version" report this
        # check exists to name. Current design: dense text in the host's
        # status-line idiom, themed from the active skin; a bordered card
        # marks the retired interim design.
        skin = preflight["display_skin"]
        checks.append(
            Check(
                "hermes_tui_widget_chrome",
                True,
                (
                    f"OMH status widget renders the current text HUD themed from the active Hermes skin ({skin['value']})"
                    if widget["themed_panel"]
                    else (
                        "installed OMH status widget predates the current text HUD; it renders an older "
                        f"surface instead of the status-line-style HUD themed from the active skin ({skin['value']})"
                    )
                ),
                severity="ok" if widget["themed_panel"] else "warning",
                next_action=(
                    ""
                    if widget["themed_panel"]
                    else "run `omh setup` to refresh the managed TUI widget"
                ),
            )
        )
    return checks


def _hermes_model_routing_check(paths: OmhPaths) -> Check:
    """Does Hermes' config name the provider that serves `model.default`?

    Users read a mismatch here as OMH hardcoding a model: they authenticate as
    one provider, the picker keeps showing the family pinned in
    `model.default`, and nothing says why. OMH writes only `model.aliases.*`,
    so this is a Hermes user-config fault — doctor names the observed
    disagreement and leaves the repair to the user.

    ok stays True like the sibling `hermes_tui_*` checks: an inconsistent
    Hermes model config is not an OMH install failure and must not flip the
    doctor exit code. `severity="warning"` plus a next action carries it.
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


def _retired_skill_install_check(paths: OmhPaths) -> Check:
    """A retired ULW engine still installed under skills_dir is a finding.

    Retirement (#954 stage 5) removed `ulw-team`/`ulw-ralph`/`ulw-goal`/
    `ulw-process` from the installable catalog; `omh update` prunes them. A
    leftover install keeps serving guidance for an intent that now runs as a
    `ulw-work` capability, so doctor names the migration instead of staying
    silent.
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
        return Check("retired_skills", True, "no retired ULW engine skill is installed")
    messages = "; ".join(
        str(retired_skill_migration_error(name).get("message", name)) for name in installed
    )
    return Check(
        "retired_skills",
        False,
        f"retired ULW engine skill install(s) found: {messages}",
        severity="warning",
        remediation="the intents now run as `ulw-work` capabilities; retired installs are pruned on update",
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


def _memory_consolidation_check(paths: OmhPaths) -> Check:
    """Say what the newest consolidation brief is asking for.

    The scheduler decided memory was worth consolidating and wrote a brief. Up
    to now nothing read it back, so the decision lived in a JSON file an
    operator had no reason to open: OMH knew memory was nearly full and said so
    only to itself.

    Never a fault. OMH cannot run the consolidation -- that needs a model -- and
    it cannot tell whether Hermes already did, so an outstanding brief is a
    thing to know rather than a thing that is broken.
    """
    brief = read_latest_consolidation(paths.omh_home)
    if not brief:
        return Check("memory_consolidation", True, "No memory consolidation is pending", observed=True)
    reasons = [str(reason) for reason in brief.get("reasons", []) if isinstance(reason, str)]
    if not brief.get("due") or not reasons:
        return Check("memory_consolidation", True, "No memory consolidation is pending", observed=True)
    at = str(brief.get("raised_at", "") or read_dreaming_state(paths.omh_home).get("last_consolidated_at", "") or "unknown time")
    record_expiry = brief.get("record_expiry", {}) if isinstance(brief.get("record_expiry"), dict) else {}
    expired = int(record_expiry.get("expired", 0) or 0)
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
) -> Check:
    """Name every local source that also claims an OMH-facing skill, command, or hook.

    The question this answers is the one an operator actually asks: a familiar
    request triggered the wrong workflow, or a bridge tool that is installed did
    not answer -- what else on this machine holds that name? So the message
    names both sides of every contest and says which side OMH installed, rather
    than reporting that a foreign directory exists and leaving the operator to
    work out whose it is.

    It never resolves the contest. `build_identity_conflict_report` reads local
    declarations and OMH's install manifests; Hermes' load order is not among
    them, so precedence stays `unknown` and this check never rewrites, renames,
    or removes anything it found.
    """
    report = build_identity_conflict_report(
        skills_dir=paths.skills_dir,
        manifest=manifest,
        plugins_dir=paths.hermes_plugins_dir,
        configured_skill_dirs=configured_dirs,
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
    details = [
        f"{conflict['kind']} name {conflict['name']} ({conflict['severity']}) claimed by "
        + ", ".join(f"{source['ownership']} at {source['location']}" for source in conflict["sources"])
        for conflict in report["conflicts"]
    ]
    details.extend(f"scan incomplete: {item}" for item in report["unreadable"])
    if details:
        return f"{header}: {'; '.join(details)}. {report['claim_boundary']}"
    return f"{header}. {report['claim_boundary']}"


def run_doctor_advisories(paths: OmhPaths) -> AdvisoryReport:
    """Read-only Hermes config advisory lane.

    Deliberately SEPARATE from ``run_doctor``: advisory entries are never
    appended to the ``list[Check]`` consumed by ``doctor_ok()`` or
    ``recommended_next_action()``, so they cannot change the doctor exit code.
    """
    return run_config_advisories(
        paths.hermes_home,
        omh_home=paths.omh_home,
        discovery_home=paths.hermes_home.parent,
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
            if check.severity == "warning" and check.next_action and WARNING_NEXT_ACTION_PRIORITY.get(check.name, 0) > 0
        ),
        key=lambda check: WARNING_NEXT_ACTION_PRIORITY[check.name],
        reverse=True,
    )
    if prioritized_warnings:
        return prioritized_warnings[0].next_action
    return DEFAULT_DOCTOR_NEXT_ACTION


def _awareness_delivery_check(paths: OmhPaths, *, now: datetime | None = None) -> Check:
    """Has OMH's primer and route hint hook returned content for model input?

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
            f"{delivered} awareness hook payload(s) returned, "
            f"{int(record.get('route_hint_count', 0) or 0)} with a route hint; "
            f"last at {record.get('last_delivered_at', 'unknown')}"
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


def _skill_freshness_check(paths: OmhPaths, manifest: dict) -> Check:
    """Detect installed skills whose content an older OMH release wrote.

    `local_modifications` compares the skills directory against the manifest
    recorded at install time, so it stays green when the omh package moves on
    and the installed guidance quietly ages: Hermes keeps executing skill
    text from a version the operator no longer runs. This check compares the
    untouched installed files against what the running package would render
    today and points a mismatch at `omh update`. Locally edited files are
    excluded here because `local_modifications` already owns that report.

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
        if rel not in manifest_sha_by_rel:
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
    status = build_guidance_projection_status(
        paths.skills_dir,
        manifest,
        registered=registered,
        host_observed=False,
    )
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
