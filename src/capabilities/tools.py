from __future__ import annotations

from ..skills.catalog import builtin_definitions
from .schema import TOOL_REQUIREMENT_SCHEMA_VERSION


def tool_requirements_manifest() -> dict[str, object]:
    items = []
    for definition in sorted(builtin_definitions(), key=lambda item: item.name):
        items.append(
            {
                "skill": definition.name,
                "derivation_status": "partial",
                "required_tools": [],
                "required_mcps": [],
                "fallback": "Use Hermes-native guidance or selected executor handoff; no concrete tool/MCP requirement is declared by the current catalog.",
                "source_refs": ["src/skills/catalog.py"],
            }
        )
    return {
        "schema_version": TOOL_REQUIREMENT_SCHEMA_VERSION,
        "derivation_status": "partial",
        "items": items,
        "claim_boundary": "Tool requirements are advisory until a host/plugin/wrapper reports observed tool availability.",
    }
