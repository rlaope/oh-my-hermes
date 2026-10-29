from __future__ import annotations

from .. import runtime_paths

import json
from json import JSONDecodeError
import os
from pathlib import Path
from typing import Any

from ..buzz_diagnostics import probe_buzz
from ..host_observation import PLUGIN_HOST_ACTIVE_OBSERVATION_EVENTS
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..loop_bridge import loop_backend_detail, loop_backend_status
from ..package_backend import load_backend, package_backend_detail
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
                "description": "Standalone operator override only. Native Hermes calls reject this field; omit it to use the active profile.",
            },
            "hermes_home": {
                "type": "string",
                "description": "Standalone operator override only. Native Hermes calls reject this field; omit it to use the active profile.",
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
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    omh_home = runtime_paths.plugin_home(args.get("omh_home"))
    hermes_home = runtime_paths.plugin_home(args.get("hermes_home"), hermes=True)
    observation = observe_plugin_tool_call("omh_probe", args, kwargs)
    # Any failure to import the package probe falls back, so a skewed install
    # still gets an answer, and its `package_probe` row says why that import
    # failed; a failure while the imported probe runs is that probe's own
    # fault and is not swallowed here.
    package_probe, failure = load_backend(_import_package_probe)
    if package_probe is None:
        payload = _standalone_probe(
            omh_home=omh_home,
            hermes_home=hermes_home,
            include_parity=include_parity,
            include_roadmap=include_roadmap,
        )
        payload["capabilities"].append(_package_probe_capability(failure))
    else:
        payload = _package_probe(
            *package_probe,
            omh_home=omh_home,
            hermes_home=hermes_home,
            include_parity=include_parity,
            include_roadmap=include_roadmap,
        )
    # Its own row, apart from registration: Hermes registers every tool of a
    # bundle whose interpreter has no `omh` package, and the tools that need
    # the package still have no backend (#2166).
    payload["capabilities"].append(_package_backend_capability())
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _package_probe_capability(failure: dict[str, Any]) -> dict[str, str]:
    # Why this answer came from the bundle: the package probe's own import,
    # which can fail while the Loop backend the next row reports imports fine.
    return _capability(
        "package_probe",
        failure["status"],
        failure["failed_import"] or "omh.probe",
        package_backend_detail(failure, feature="the package probe"),
    )


def _package_backend_capability() -> dict[str, str]:
    backend = loop_backend_status()
    return _capability(
        "package_backend",
        backend["status"],
        backend["failed_import"] or "omh.workflows.loop_operations",
        loop_backend_detail(backend),
    )


def _import_package_probe() -> tuple[Any, Any]:
    from omh.paths import resolve_paths
    from omh.probe import probe_capabilities

    return resolve_paths, probe_capabilities


def _package_probe(
    resolve_paths: Any,
    probe_capabilities: Any,
    *,
    omh_home: str | None,
    hermes_home: str | None,
    include_parity: bool,
    include_roadmap: bool,
) -> dict[str, Any]:
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
    home, hermes = runtime_paths.resolve_homes(omh_home, hermes_home)
    status = read_omh_status(omh_home=home, limit=3)
    hud = read_omh_hud(omh_home=home, hermes_home=hermes, preset="focused", limit=1, delegation_graph=False)
    plugin_observation = _latest_plugin_observation(home)
    plugin_runtime_observed = bool(plugin_observation and plugin_observation.get("observed"))
    plugin_runtime_active = (
        plugin_runtime_observed and str(plugin_observation.get("runtime_readiness", "")) == "active_runtime_observed"
    )
    capabilities = _standalone_capabilities(home, hermes, status, hud, plugin_observation=plugin_observation)
    buzz = probe_buzz(_StandaloneBuzzPaths(hermes))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "plugin_tool": "omh_probe",
        "omh_home": str(home),
        "hermes_home": str(hermes),
        "capabilities": capabilities,
        "buzz": buzz,
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
    hermes_config = hermes / "config.yaml"
    config_text = _read_text(hermes_config)
    # The pack in use, not `<omh_home>/skills`: on a managed install that is
    # a frozen pre-pointer copy or nothing at all (#2358).
    skills_dir = _standalone_skills_dir(home)
    # `oh-my-hermes` installs under its Hermes category directory and its
    # display label; see skills/catalog.hermes_skill_category and
    # skills/catalog_types.OMH_SKILL_DISPLAY_NAME_OVERRIDES. Literal because a
    # copied plugin bundle has no catalog import.
    managed_skill = skills_dir / "guide" / "omh-routing" / "SKILL.md"
    skills_registered = _standalone_skills_registered(config_text, hermes, home, skills_dir)
    plugin_dir = hermes / "plugins" / "omh"
    buzz = probe_buzz(_StandaloneBuzzPaths(hermes))
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
            "buzz_platform_diagnostics",
            str(buzz["status"]),
            str(buzz["reason_code"]),
            (
                f"Buzz local probe: configured={str(buzz['configured']).lower()}; "
                f"credential_present={str(buzz['credential_present']).lower()}; "
                f"cli={buzz['status']}"
            ),
        ),
        _capability(
            "external_skill_dirs",
            "available" if skills_registered else ("missing" if hermes_config.exists() else "unknown"),
            str(hermes_config),
            (
                "Hermes config references the managed OMH skills directory"
                if skills_registered
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


class _StandaloneBuzzPaths:
    def __init__(self, hermes_home: Path) -> None:
        self.hermes_home = hermes_home
        self.hermes_config_path = hermes_home / "config.yaml"


def _managed_command_root() -> Path | None:
    """Where the installers keep the OMH venv, its generations and the `current` pointer.

    Literal, because a copied bundle has no `omh` import: the same precedence
    as `system.paths.managed_command_venv_dir` (`OMH_VENV_DIR`, then
    `XDG_DATA_HOME`, then `%LOCALAPPDATA%` on Windows, then
    `~/.local/share`), which `tests/test_managed_pack_diagnostics.py` holds against
    the package's own reading.
    """
    explicit = os.environ.get("OMH_VENV_DIR")
    if explicit:
        return Path(explicit).expanduser().parent
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "omh"
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser() / "omh"
    home = os.environ.get("USERPROFILE" if os.name == "nt" else "HOME")
    return Path(home).expanduser() / ".local" / "share" / "omh" if home else None


def _recorded_skills_dir(home: Path) -> Path | None:
    """The pack the last install wrote, as `<omh_home>/manifest.json` records it."""
    try:
        payload = json.loads((home / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    recorded = payload.get("skills_dir") if isinstance(payload, dict) else None
    return Path(recorded) if isinstance(recorded, str) and recorded else None


def _managed_pack_candidates(home: Path) -> list[Path]:
    """The directories this home's managed pack may be in, the pack in use first.

    The pack the manifest records -- a generation's own pack on a managed
    install -- then the pre-pointer `<omh_home>/skills`, the one directory a
    home that predates generations or never had a managed command installs
    into. The shared `current` pointer is not one: it is the machine's, and a
    home with no install of its own does not hold skills because another
    home does.
    """
    candidates: list[Path] = []
    for candidate in (_recorded_skills_dir(home), home / "skills"):
        if candidate is not None and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _standalone_skills_dir(home: Path) -> Path:
    """The managed pack this home uses: the first candidate that exists, else the pre-pointer path."""
    for candidate in _managed_pack_candidates(home):
        if candidate.is_dir():
            return candidate
    return home / "skills"


def _standalone_skills_registered(config_text: str, hermes: Path, home: Path, skills_dir: Path) -> bool:
    """Whether Hermes' `skills.external_dirs` names the managed pack under any spelling OMH writes.

    The pointer (`<root>/current/skills`) is what setup and update register;
    a generation's own pack (`<root>/generations/<id>/skills`), the
    manifest's recorded pack and the pre-pointer `<omh_home>/skills` are each
    a registration of the same managed pack. Matched by real path after
    reading an entry the way Hermes does (`${VAR}` and `~` expanded, a
    relative entry anchored at the Hermes home), so a link or a trailing
    slash is the same entry. Only `<omh_home>/skills` was accepted before,
    and only as a substring of the config text, so a home registered at the
    pointer read as unregistered (#2358). That substring match is kept as a
    floor for a shape the line reader below does not parse.
    """
    root = _managed_command_root()
    pointer = root / "current" / "skills" if root is not None else None
    candidates = [*_managed_pack_candidates(home), skills_dir, *([pointer] if pointer is not None else [])]
    if any(str(candidate) in config_text for candidate in candidates):
        return True
    wanted = {_real_key(candidate) for candidate in candidates}
    generations = _real_key(root / "generations") if root is not None else None
    for entry in _external_dir_entries(config_text):
        anchored = os.path.join(str(hermes), os.path.expanduser(os.path.expandvars(entry)))
        if not os.path.isabs(anchored):
            continue
        if _real_key(anchored) in wanted:
            return True
        normalized = os.path.normpath(anchored)
        if (
            generations is not None
            and os.path.normcase(os.path.basename(normalized)) == "skills"
            and _real_key(os.path.dirname(os.path.dirname(normalized))) == generations
        ):
            return True
    return False


def _real_key(path: str | Path) -> str:
    try:
        return os.path.normcase(os.path.realpath(os.path.expanduser(str(path))))
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(str(path)))


def _external_dir_entries(config_text: str) -> list[str]:
    """`skills.external_dirs` as written: the block list or one inline `[a, b]` list.

    A line reader in the spirit of the bundle's other `config.yaml` scans;
    any shape it does not follow yields no entries, never an error.
    """
    entries: list[str] = []
    in_skills = in_external = False
    external_indent = 0
    for line in config_text.removeprefix("\ufeff").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_skills = stripped.split("#", 1)[0].strip() == "skills:"
            in_external = False
            continue
        if not in_skills:
            continue
        if in_external and (indent > external_indent or (indent == external_indent and stripped.startswith("- "))):
            if stripped.startswith("- "):
                entries.append(stripped[2:].split(" #", 1)[0].strip().strip("'\""))
            continue
        in_external = False
        key, separator, rest = stripped.partition(":")
        if not separator or key.strip() != "external_dirs":
            continue
        value = rest.split(" #", 1)[0].strip()
        if not value:
            in_external, external_indent = True, indent
        elif value.startswith("[") and value.endswith("]"):
            entries.extend(item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip())
    return [entry for entry in entries if entry]


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
