from __future__ import annotations

from copy import deepcopy

from .agents import agent_role_capabilities
from .hooks import hook_manifest
from .keywords import keyword_detector_manifest
from .orchestration import orchestration_patterns
from .playbooks import playbook_capabilities
from .schema import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_SECTIONS,
    PREPARED_NOT_OBSERVED,
    normalize_capability_section,
)
from .skills import skill_capabilities
from .tools import tool_requirements_manifest
from ..plugin_bundle.omh.awareness import awareness_primer_payload


def capability_snapshot() -> dict[str, object]:
    agent_roles = agent_role_capabilities()
    skills = skill_capabilities()
    hooks = hook_manifest()
    keywords = keyword_detector_manifest()
    patterns = orchestration_patterns()
    playbooks = playbook_capabilities()
    tools = tool_requirements_manifest()
    awareness = awareness_primer_payload()
    snapshot = {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "manifest_id": "omh_capabilities",
        "determinism": "static_projection_no_runtime_clock",
        "summary": {
            "omh_awareness": 1,
            "agent_roles": len(agent_roles),
            "skills": len(skills),
            "plugin_tools": len(hooks["plugin_tools"]),
            "plugin_hooks": len(hooks["plugin_hooks"]),
            "keyword_rules": len(keywords["natural_language_rules"]),
            "orchestration_patterns": len(patterns),
            "playbooks": len(playbooks),
            "tool_requirements": len(tools["items"]),
        },
        "omh_awareness": awareness,
        "agent_roles": agent_roles,
        "skills": skills,
        "hooks": hooks,
        "keywords": keywords,
        "orchestration_patterns": patterns,
        "playbooks": playbooks,
        "tool_requirements": tools,
        "evidence_boundaries": evidence_boundaries(),
        "non_goals": [
            "no hidden executor dispatch",
            "no worktree creation",
            "no worker or subagent spawn",
            "no MCP server runtime",
            "no Hermes core patching",
            "no runtime_topology schema in this PR",
        ],
    }
    return deepcopy(snapshot)


def evidence_boundaries() -> dict[str, object]:
    return {
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "observed_required_for": [
            "runtime_start",
            "worktree_creation",
            "worker_dispatch",
            "worker_result",
            "verification",
            "review",
            "ci",
            "merge_readiness",
            "merge",
        ],
        "claim_rule": "Capability presence means OMH can prepare guidance or status; it does not prove host/plugin/runtime execution.",
    }


def filtered_capability_snapshot(section: str | None = None) -> dict[str, object]:
    snapshot = capability_snapshot()
    canonical_section = normalize_capability_section(section)
    if not canonical_section:
        return snapshot
    if canonical_section not in CAPABILITY_SECTIONS:
        raise ValueError(f"unknown capability section: {section}")
    return {
        "schema_version": snapshot["schema_version"],
        "manifest_id": snapshot["manifest_id"],
        "section": canonical_section,
        canonical_section: snapshot[canonical_section],
    }


def list_capabilities(section: str | None = None) -> dict[str, object]:
    snapshot = capability_snapshot()
    canonical_section = normalize_capability_section(section)
    sections = [canonical_section] if canonical_section else list(CAPABILITY_SECTIONS)
    unknown = [item for item in sections if item not in CAPABILITY_SECTIONS]
    if unknown:
        raise ValueError(f"unknown capability section: {unknown[0]}")
    return {
        "schema_version": "omh_capability_list/v1",
        "sections": [
            {
                "section": name,
                "ids": _section_ids(name, snapshot[name]),
            }
            for name in sections
        ],
    }


def inspect_capability(identifier: str, section: str | None = None) -> dict[str, object]:
    if not identifier:
        raise ValueError("capabilities inspect requires an id")
    snapshot = capability_snapshot()
    canonical_section = normalize_capability_section(section)
    sections = [canonical_section] if canonical_section else list(CAPABILITY_SECTIONS)
    for name in sections:
        if name not in CAPABILITY_SECTIONS:
            raise ValueError(f"unknown capability section: {name}")
        found = _find_in_section(identifier, snapshot[name])
        if found is not None:
            return {
                "schema_version": "omh_capability_inspect/v1",
                "section": name,
                "id": identifier,
                "requested_id": identifier,
                "resolved_id": _capability_id(found, identifier),
                "capability": found,
            }
    raise ValueError(f"capability not found: {identifier}")


def _section_ids(section: str, payload: object) -> list[str]:
    if section == "omh_awareness":
        return ["omh_awareness", "first_turn_rule", "workflow_lanes", "fallback_rule", "evidence_boundary"]
    if section == "hooks" and isinstance(payload, dict):
        return sorted(
            [
                *[str(item["name"]) for item in payload.get("plugin_tools", []) if isinstance(item, dict)],
                *[str(item["name"]) for item in payload.get("plugin_hooks", []) if isinstance(item, dict)],
            ]
        )
    if section == "keywords" and isinstance(payload, dict):
        return ["explicit_invocation_prefixes", "natural_language_rules", "locale_policy", "guard_rules"]
    if section == "tool_requirements" and isinstance(payload, dict):
        return sorted(str(item["skill"]) for item in payload.get("items", []) if isinstance(item, dict))
    if section == "evidence_boundaries":
        return ["prepared_is_not", "observed_required_for", "claim_rule"]
    if isinstance(payload, list):
        return sorted(str(item.get("id", item.get("name", ""))) for item in payload if isinstance(item, dict))
    return []


def _find_in_section(identifier: str, payload: object) -> object | None:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and _matches_identifier(identifier, item):
                return item
    if isinstance(payload, dict):
        if _matches_identifier(identifier, payload):
            return payload
        for key in ("plugin_tools", "plugin_hooks", "items", "natural_language_rules"):
            values = payload.get(key)
            if isinstance(values, list):
                found = _find_in_section(identifier, values)
                if found is not None:
                    return found
        if identifier in payload:
            return payload[identifier]
    return None


def _matches_identifier(identifier: str, item: dict[str, object]) -> bool:
    aliases = item.get("legacy_ids", ())
    legacy_ids = aliases if isinstance(aliases, list) else ()
    values = {
        str(item.get("id", "")),
        str(item.get("name", "")),
        str(item.get("skill", "")),
        *[str(alias) for alias in legacy_ids],
    }
    return identifier in values


def _capability_id(item: object, fallback: str) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or item.get("name") or item.get("skill") or fallback)
    return fallback
