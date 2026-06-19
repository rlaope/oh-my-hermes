from __future__ import annotations

CAPABILITY_MANIFEST_SCHEMA_VERSION = "omh_capability_manifest/v1"
AGENT_ROLE_CAPABILITY_SCHEMA_VERSION = "agent_role_capability/v1"
SKILL_CAPABILITY_SCHEMA_VERSION = "skill_capability/v1"
HOOK_EVENT_CAPABILITY_SCHEMA_VERSION = "omh_hook_manifest/v1"
KEYWORD_DETECTOR_SCHEMA_VERSION = "keyword_detector_manifest/v1"
ORCHESTRATION_PATTERN_SCHEMA_VERSION = "orchestration_pattern/v1"
TOOL_REQUIREMENT_SCHEMA_VERSION = "tool_requirement_manifest/v1"

CAPABILITY_SECTIONS = (
    "omh_awareness",
    "agent_roles",
    "skills",
    "hooks",
    "keywords",
    "orchestration_patterns",
    "tool_requirements",
    "evidence_boundaries",
)

PREPARED_NOT_OBSERVED = (
    "Prepared OMH capability, handoff, topology, or routing metadata is not execution, "
    "worker dispatch, worktree creation, review, CI, merge-readiness, or merge evidence."
)
