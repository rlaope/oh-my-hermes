from __future__ import annotations

CAPABILITY_MANIFEST_SCHEMA_VERSION = "omh_capability_manifest/v1"
AGENT_ROLE_CAPABILITY_SCHEMA_VERSION = "agent_role_capability/v1"
SKILL_CAPABILITY_SCHEMA_VERSION = "skill_capability/v1"
HOOK_EVENT_CAPABILITY_SCHEMA_VERSION = "omh_hook_manifest/v1"
KEYWORD_DETECTOR_SCHEMA_VERSION = "keyword_detector_manifest/v1"
ORCHESTRATION_PATTERN_SCHEMA_VERSION = "orchestration_pattern/v1"
PLAYBOOK_CAPABILITY_SCHEMA_VERSION = "playbook_capability/v1"
TOOL_REQUIREMENT_SCHEMA_VERSION = "tool_requirement_manifest/v1"

CAPABILITY_SECTIONS = (
    "omh_awareness",
    "agent_roles",
    "skills",
    "hooks",
    "keywords",
    "orchestration_patterns",
    "playbooks",
    "tool_requirements",
    "achievement_evidence",
    "evidence_boundaries",
)

CAPABILITY_SECTION_ALIASES = {
    "awareness": "omh_awareness",
    "agent": "agent_roles",
    "agents": "agent_roles",
    "role": "agent_roles",
    "roles": "agent_roles",
    "hook": "hooks",
    "keyword": "keywords",
    "pattern": "orchestration_patterns",
    "patterns": "orchestration_patterns",
    "orchestration": "orchestration_patterns",
    "playbook": "playbooks",
    "tool": "tool_requirements",
    "tools": "tool_requirements",
    "tooling": "tool_requirements",
    "achievement": "achievement_evidence",
    "achievements": "achievement_evidence",
    "badge": "achievement_evidence",
    "badges": "achievement_evidence",
    "boundary": "evidence_boundaries",
    "boundaries": "evidence_boundaries",
    "evidence": "evidence_boundaries",
}

CAPABILITY_SECTION_CHOICES = (*CAPABILITY_SECTIONS, *CAPABILITY_SECTION_ALIASES.keys())

PREPARED_NOT_OBSERVED = (
    "Prepared OMH capability, handoff, topology, or routing metadata is not execution, "
    "worker dispatch, worktree creation, review, CI, merge-readiness, or merge evidence."
)


def normalize_capability_section(section: str | None) -> str | None:
    if not section:
        return None
    normalized = section.strip()
    return CAPABILITY_SECTION_ALIASES.get(normalized, normalized)
