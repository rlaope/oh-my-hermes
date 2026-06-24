from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .config_adapter import ensure_external_dir, read_config, write_config
from .local_store import atomic_write_json, read_json_object_result, utc_now
from .paths import OmhPaths, expand_path


TARGET_REGISTRY_SCHEMA_VERSION = "omh_target_registry/v1"
TARGET_OBSERVATION_SCHEMA_VERSION = "omh_target_observation/v1"
TARGET_TOPOLOGY_SCHEMA_VERSION = "omh_target_topology/v1"
TARGET_NOTICE_SCHEMA_VERSION = "omh_target_change_notice/v1"

TARGET_METADATA_KEYS = (
    "agent_ref",
    "target_ref",
    "runtime_ref",
    "hermes_home",
    "agent_count",
    "target_count",
)


def read_target_registry_result(paths: OmhPaths) -> tuple[dict[str, Any] | None, str | None]:
    registry, error = read_json_object_result(paths.target_registry_path)
    if registry is None or error:
        return registry, error
    if registry.get("schema_version") != TARGET_REGISTRY_SCHEMA_VERSION:
        return None, f"unsupported target registry schema: {registry.get('schema_version')!r}"
    if not isinstance(registry.get("targets", {}), dict):
        return None, "target registry targets must be an object"
    return registry, None


def inspect_target_observation(
    paths: OmhPaths,
    *,
    source: str,
    source_metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    registry, error = read_target_registry_result(paths)
    target = build_target_record(paths, source=source, source_metadata=source_metadata)
    return _observation_payload(paths, registry, error, target, dry_run=True, persisted=False, config_changed=False)


def record_target_observation(
    paths: OmhPaths,
    *,
    source: str,
    source_metadata: dict[str, str] | None = None,
    dry_run: bool = False,
    ensure_config: bool = False,
    setup_context: dict[str, object] | None = None,
) -> dict[str, object]:
    registry, error = read_target_registry_result(paths)
    target = build_target_record(paths, source=source, source_metadata=source_metadata, setup_context=setup_context)
    config_changed = False
    if dry_run:
        return _observation_payload(paths, registry, error, target, dry_run=True, persisted=False, config_changed=False)
    if error:
        registry = None
    if ensure_config:
        config_path = Path(str(target["hermes_config_path"]))
        current = read_config(config_path)
        change = ensure_external_dir(current, paths.skills_dir)
        if change.changed:
            write_config(config_path, change.text)
            config_changed = True
    next_registry = _merge_registry(registry, target)
    atomic_write_json(paths.target_registry_path, next_registry, private=True)
    return _observation_payload(paths, registry, error, target, dry_run=False, persisted=True, config_changed=config_changed)


def build_target_record(
    paths: OmhPaths,
    *,
    source: str,
    source_metadata: dict[str, str] | None = None,
    setup_context: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata = {str(key): str(value) for key, value in (source_metadata or {}).items() if str(value)}
    hermes_home = expand_path(metadata.get("hermes_home") or paths.hermes_home)
    agent_ref = metadata.get("agent_ref", "")
    target_ref = metadata.get("target_ref", "")
    runtime_ref = metadata.get("runtime_ref", "")
    target_id = target_id_for(hermes_home, agent_ref=agent_ref, target_ref=target_ref, runtime_ref=runtime_ref)
    reported_count = _coerce_count(metadata.get("agent_count") or metadata.get("target_count"))
    record: dict[str, object] = {
        "target_id": target_id,
        "display_name": _display_name(hermes_home, agent_ref=agent_ref, target_ref=target_ref, runtime_ref=runtime_ref),
        "hermes_home": str(hermes_home),
        "hermes_config_path": str(hermes_home / "config.yaml"),
        "skills_dir": str(paths.skills_dir),
        "source": source,
        "agent_ref": agent_ref,
        "target_ref": target_ref,
        "runtime_ref": runtime_ref,
        "reported_agent_count": reported_count,
        "observed_at": utc_now(),
    }
    if setup_context:
        record["setup_context"] = setup_context
    return record


def target_id_for(hermes_home: Path, *, agent_ref: str = "", target_ref: str = "", runtime_ref: str = "") -> str:
    basis = "|".join(
        [
            str(hermes_home),
            f"agent={agent_ref}",
            f"target={target_ref}",
            f"runtime={runtime_ref}",
        ]
    )
    return f"hermes-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:12]}"


def build_target_change_notice(observation: dict[str, object], *, auto_applied: bool = False) -> dict[str, object] | None:
    topology = observation.get("topology")
    if not isinstance(topology, dict):
        return None
    changed = bool(topology.get("changed"))
    transition = str(topology.get("transition", "none"))
    target = observation.get("target")
    target_id = str(target.get("target_id", "")) if isinstance(target, dict) else ""
    apply_payload = _apply_payload(target if isinstance(target, dict) else {}, topology)
    if not changed and transition not in {"initial_target_observed"}:
        return None
    if auto_applied and bool(observation.get("persisted")):
        action = "target_change_applied"
        headline = "Hermes target setup was updated."
        body = _notice_body(topology, applied=True)
    else:
        action = "ask_to_apply_target_change"
        headline = "Hermes target setup changed."
        body = _notice_body(topology, applied=False)
    return {
        "schema_version": TARGET_NOTICE_SCHEMA_VERSION,
        "action": action,
        "headline": headline,
        "body": body,
        "target_id": target_id,
        "topology": topology,
        "apply_payload": apply_payload,
        "persistence": "persisted" if auto_applied and bool(observation.get("persisted")) else "pending_user_confirmation",
        "claim_boundary": (
            "Target topology is setup evidence only; it does not prove another Hermes agent observed, accepted, or executed this workflow."
        ),
    }


def summarize_target_registry(paths: OmhPaths) -> dict[str, object]:
    registry, error = read_target_registry_result(paths)
    if error:
        return {
            "schema_version": TARGET_TOPOLOGY_SCHEMA_VERSION,
            "registry_path": str(paths.target_registry_path),
            "status": "unreadable",
            "error": error,
            "mode": "unknown",
            "known_target_count": 0,
            "active_agent_count": 0,
            "changed": False,
            "transition": "registry_unreadable",
        }
    if not registry:
        return {
            "schema_version": TARGET_TOPOLOGY_SCHEMA_VERSION,
            "registry_path": str(paths.target_registry_path),
            "status": "missing",
            "mode": "unknown",
            "known_target_count": 0,
            "active_agent_count": 0,
            "changed": False,
            "transition": "registry_missing",
        }
    existing_topology = registry.get("topology", {})
    return _topology_for(registry, existing_topology if isinstance(existing_topology, dict) else None)


def _observation_payload(
    paths: OmhPaths,
    previous_registry: dict[str, Any] | None,
    registry_error: str | None,
    target: dict[str, object],
    *,
    dry_run: bool,
    persisted: bool,
    config_changed: bool,
) -> dict[str, object]:
    preview_registry = _merge_registry(previous_registry, target)
    if previous_registry:
        existing_topology = previous_registry.get("topology", {})
        previous_topology = _topology_for(previous_registry, existing_topology if isinstance(existing_topology, dict) else None)
    else:
        previous_topology = _empty_topology(paths, registry_error)
    topology = _topology_for(preview_registry, previous_topology)
    if previous_registry is None and not registry_error:
        topology["transition"] = "initial_target_observed"
        topology["changed"] = False
    current_id = str(target["target_id"])
    known_ids = topology.get("known_target_ids")
    if isinstance(known_ids, list) and current_id not in known_ids:
        known_ids.append(current_id)
    return {
        "schema_version": TARGET_OBSERVATION_SCHEMA_VERSION,
        "registry_path": str(paths.target_registry_path),
        "dry_run": dry_run,
        "persisted": persisted,
        "config_changed": config_changed,
        "target": target,
        "topology": topology,
        "registry_error": registry_error or "",
        "skill_scope_rule": _skill_scope_rule(topology),
    }


def _merge_registry(registry: dict[str, Any] | None, target: dict[str, object]) -> dict[str, object]:
    targets = dict(registry.get("targets", {})) if isinstance(registry, dict) else {}
    target_id = str(target["target_id"])
    targets[target_id] = target
    reported_count = _coerce_count(target.get("reported_agent_count"))
    previous_topology = registry.get("topology", {}) if isinstance(registry, dict) else {}
    topology = _topology_for(
        {
            "schema_version": TARGET_REGISTRY_SCHEMA_VERSION,
            "targets": targets,
            "last_seen_target_id": target_id,
            "last_reported_agent_count": reported_count,
            "topology": previous_topology,
        },
        previous_topology if isinstance(previous_topology, dict) else None,
    )
    return {
        "schema_version": TARGET_REGISTRY_SCHEMA_VERSION,
        "targets": targets,
        "last_seen_target_id": target_id,
        "last_reported_agent_count": reported_count,
        "topology": topology,
        "updated_at": utc_now(),
    }


def _topology_for(registry: dict[str, Any] | None, previous_topology: dict[str, Any] | None) -> dict[str, object]:
    targets = registry.get("targets", {}) if isinstance(registry, dict) else {}
    targets = targets if isinstance(targets, dict) else {}
    reported_count = _coerce_count(registry.get("last_reported_agent_count")) if isinstance(registry, dict) else None
    known_count = len(targets)
    active_count = reported_count or known_count
    previous_count = _coerce_count((previous_topology or {}).get("active_agent_count")) or 0
    mode = "multi_agent_targets" if active_count > 1 else "single_agent_target"
    previous_mode = str((previous_topology or {}).get("mode", "unknown"))
    transition = _transition(previous_count, active_count, previous_mode, mode)
    current_id = str(registry.get("last_seen_target_id", "")) if isinstance(registry, dict) else ""
    return {
        "schema_version": TARGET_TOPOLOGY_SCHEMA_VERSION,
        "status": "available" if registry else "missing",
        "mode": mode if active_count else "unknown",
        "previous_mode": previous_mode,
        "changed": transition not in {"none", "initial_target_observed"},
        "transition": transition,
        "known_target_count": known_count,
        "active_agent_count": active_count,
        "active_agent_count_source": "source_metadata" if reported_count else "target_registry",
        "current_target_id": current_id,
        "known_target_ids": sorted(str(key) for key in targets),
        "stale_known_target_count": max(known_count - active_count, 0) if reported_count else 0,
        "requires_skill_scope_awareness": active_count > 1,
    }


def _empty_topology(paths: OmhPaths, error: str | None) -> dict[str, object]:
    return {
        "schema_version": TARGET_TOPOLOGY_SCHEMA_VERSION,
        "registry_path": str(paths.target_registry_path),
        "status": "unreadable" if error else "missing",
        "mode": "unknown",
        "previous_mode": "unknown",
        "changed": False,
        "transition": "registry_unreadable" if error else "registry_missing",
        "known_target_count": 0,
        "active_agent_count": 0,
        "active_agent_count_source": "none",
        "current_target_id": "",
        "known_target_ids": [],
        "stale_known_target_count": 0,
        "requires_skill_scope_awareness": False,
    }


def _transition(previous_count: int, active_count: int, previous_mode: str, mode: str) -> str:
    if previous_count == 0 and active_count > 0:
        return "initial_target_observed"
    if previous_count <= 1 and active_count > 1:
        return "single_to_multi"
    if previous_count > 1 and active_count <= 1:
        return "multi_to_single"
    if previous_mode != "unknown" and previous_mode != mode:
        return f"{previous_mode}_to_{mode}"
    return "none"


def _notice_body(topology: dict[str, object], *, applied: bool) -> str:
    transition = str(topology.get("transition", "none"))
    if transition == "single_to_multi":
        base = "I now see multiple Hermes agent targets for this workspace."
    elif transition == "multi_to_single":
        base = "I now see this workspace back on a single Hermes agent target."
    elif transition == "initial_target_observed":
        base = "I found a Hermes agent target for this workspace."
    else:
        base = "The Hermes agent target topology changed."
    suffix = (
        "I updated the persistent target registry and will bind this workflow to the current thread target."
        if applied
        else "Please confirm before I persist the target registry update; until then I will bind this workflow only to the current thread target."
    )
    return f"{base} {suffix}"


def _apply_payload(target: dict[str, object], topology: dict[str, object]) -> dict[str, object]:
    source_metadata: dict[str, str] = {}
    for key in ("agent_ref", "target_ref", "runtime_ref", "hermes_home"):
        value = str(target.get(key, ""))
        if value:
            source_metadata[key] = value
    reported_count = target.get("reported_agent_count") or topology.get("active_agent_count")
    if reported_count:
        source_metadata["agent_count"] = str(reported_count)
    return {
        "schema_version": "omh_target_apply_payload/v1",
        "source": str(target.get("source", "")),
        "source_metadata": source_metadata,
        "persistence_contract": "Pass this source_metadata back to the OMH wrapper backend with target-change apply enabled; no raw chat prompt is required.",
    }


def _skill_scope_rule(topology: dict[str, object]) -> str:
    if int(topology.get("active_agent_count") or 0) > 1:
        return (
            "Multiple Hermes targets are known. Bind workflow state to the current target/thread, and do not claim other agents saw it "
            "unless their target evidence is recorded."
        )
    return "Use single-target workflow behavior unless source metadata reports multiple Hermes targets."


def _display_name(hermes_home: Path, *, agent_ref: str, target_ref: str, runtime_ref: str) -> str:
    value = target_ref or agent_ref or runtime_ref or hermes_home.name or "hermes"
    slug = re.sub(r"\s+", " ", value).strip()
    return slug[:80] or "hermes"


def _coerce_count(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None
    return min(count, 128)
