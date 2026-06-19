from __future__ import annotations

from copy import deepcopy

from .agents import agent_role_capabilities
from .hooks import hook_manifest
from .keywords import keyword_detector_manifest
from .orchestration import orchestration_patterns
from .playbooks import playbook_capabilities
from .schema import (
    CAPABILITY_SECTION_ALIASES,
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_SECTIONS,
    PREPARED_NOT_OBSERVED,
    normalize_capability_section,
)
from .skills import skill_capabilities
from .tools import tool_requirements_manifest
from ..plugin_bundle.omh.awareness import awareness_lane_examples, awareness_primer_payload

LANE_OWNER_ROLES = {
    "intent_to_plan": "planner",
    "research_and_ops": "researcher",
    "materials_and_visuals": "operator",
    "automation_and_status": "tracker",
    "coding_handoff": "handoff-guide",
}

LANE_PLAYBOOK_IDS = {
    "intent_to_plan": (
        "request-to-handoff",
        "deep-interview-to-plan",
        "safe-feature-change",
        "local-pipeline-buildout",
    ),
    "research_and_ops": (
        "research-department",
        "source-backed-research",
        "feedback-triage",
        "market-scan-to-strategy",
        "research-to-strategy-brief",
        "weekly-ops-review",
    ),
    "materials_and_visuals": (
        "materials-processing",
        "report-package",
        "deliverable-package",
        "meeting-prep-to-record",
    ),
    "automation_and_status": (
        "scheduled-ops-blueprint",
        "agent-board",
        "memory-curation-review",
        "toolbelt-readiness",
        "ops-observability-card",
    ),
    "coding_handoff": (
        "idea-to-deploy",
        "github-event-ops",
        "release-readiness-review",
        "deploy-and-monitor",
        "cto-loop",
    ),
}


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


def capability_summary() -> dict[str, object]:
    snapshot = capability_snapshot()
    awareness = snapshot["omh_awareness"]
    skills = {str(item.get("id")): item for item in snapshot["skills"] if isinstance(item, dict)}
    playbooks = {str(item.get("id")): item for item in snapshot["playbooks"] if isinstance(item, dict)}
    lanes = awareness.get("lanes", []) if isinstance(awareness, dict) else []
    return {
        "schema_version": "omh_capability_summary/v1",
        "manifest_id": snapshot["manifest_id"],
        "determinism": snapshot["determinism"],
        "purpose": (
            "Compact Hermes-facing summary for answering what OMH can do, choosing the nearest workflow, "
            "and rendering a picker/card without requiring shell catalog approval."
        ),
        "chat_rule": awareness.get("chat_rule", "") if isinstance(awareness, dict) else "",
        "totals": snapshot["summary"],
        "lanes": [
            _summary_lane(lane, skills, playbooks)
            for lane in lanes
            if isinstance(lane, dict)
        ],
        "workflow_context_cards": awareness.get("workflow_context_cards", []) if isinstance(awareness, dict) else [],
        "direct_response_guidance": [
            "When a user asks what OMH can do, summarize these lanes and offer the workflow picker.",
            "When a request matches a lane, name the likely workflow and the first safe next action.",
            "When a request crosses lanes, name the adjacent workflow before preparing handoff or status.",
            "Use friendly section aliases for input, but keep canonical names in machine-readable output.",
        ],
        "section_aliases": dict(sorted(CAPABILITY_SECTION_ALIASES.items())),
        "evidence_boundary": snapshot["evidence_boundaries"]["prepared_is_not"],
    }


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


def _summary_lane(
    lane: dict[str, object],
    skills: dict[str, dict[str, object]],
    playbooks: dict[str, dict[str, object]],
) -> dict[str, object]:
    lane_id = str(lane.get("id") or "")
    lane_skills = lane.get("skills", [])
    if not isinstance(lane_skills, list):
        lane_skills = []
    skill_ids = [str(skill) for skill in lane_skills if str(skill) in skills]
    representative_playbooks = [
        _compact_playbook(playbooks[playbook_id])
        for playbook_id in LANE_PLAYBOOK_IDS.get(lane_id, ())
        if playbook_id in playbooks
    ]
    actions = sorted(
        {
            str(action)
            for playbook in representative_playbooks
            for action in playbook.get("available_wrapper_actions", [])
        }
    )
    return {
        "id": lane_id,
        "label": str(lane.get("label") or lane_id),
        "owner_role": LANE_OWNER_ROLES.get(lane_id, "guide"),
        "use_for": str(lane.get("use_for") or ""),
        "primary_skills": skill_ids,
        "representative_playbooks": representative_playbooks,
        "wrapper_actions": actions[:8],
        "examples": awareness_lane_examples(lane_id),
    }


def _compact_playbook(playbook: dict[str, object]) -> dict[str, object]:
    first_stage = playbook.get("first_stage")
    return {
        "id": str(playbook.get("id") or ""),
        "display_name": str(playbook.get("display_name") or playbook.get("id") or ""),
        "summary": str(playbook.get("summary") or ""),
        "owner_role": str(playbook.get("primary_owner_role") or "guide"),
        "first_stage": first_stage if isinstance(first_stage, dict) else {},
        "available_wrapper_actions": [
            str(action)
            for action in playbook.get("available_wrapper_actions", [])
            if str(action)
        ][:8],
    }


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
