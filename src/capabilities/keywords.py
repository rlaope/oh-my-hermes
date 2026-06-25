from __future__ import annotations

from ..routing.policy import EXPLICIT_INVOCATION_PREFIXES, ROUTING_GUARD_RULES
from ..routing.localization import locale_aliases
from ..skills.catalog import capability_definitions, skill_exposure_payload
from .schema import KEYWORD_DETECTOR_SCHEMA_VERSION, PREPARED_NOT_OBSERVED


def keyword_detector_manifest() -> dict[str, object]:
    definitions = sorted(capability_definitions(), key=lambda item: item.name)
    aliases = locale_aliases()
    return {
        "schema_version": KEYWORD_DETECTOR_SCHEMA_VERSION,
        "explicit_invocation_prefixes": [
            {"prefix": prefix, "strength": "exact", "precedence": 1, "surface": _prefix_surface(prefix)}
            for prefix in EXPLICIT_INVOCATION_PREFIXES
        ],
        "natural_language_rules": [
            {
                "skill": definition.name,
                "strength": "strong" if len(definition.triggers) >= 3 else "weak",
                "triggers": list(definition.triggers),
                "category": definition.category,
                "phase": definition.phase,
                **skill_exposure_payload(definition.name),
            }
            for definition in definitions
        ],
        "locale_policy": {
            "derived_from": "src/routing/localization.py",
            "supported_alias_locales": sorted({alias.locale for alias in aliases}),
            "alias_labels": sorted({alias.label for alias in aliases}),
            "fallback": "Unsupported-language or weak multilingual matches should clarify instead of forcing direct dispatch.",
        },
        "conflict_policy": {
            "explicit_wins": True,
            "high_confidence_dispatch": True,
            "tied_scores": "clarify",
            "unsafe_direct_dispatch": "requires_plan_or_explicit_invocation",
        },
        "guard_rules": [
            {
                "id": rule.id,
                "rule": rule.rule,
                "preferred_skills": list(rule.preferred_skills),
                "activation_status": rule.activation_status,
            }
            for rule in ROUTING_GUARD_RULES
            if rule.activation_status == "active"
        ],
        "guard_policy_catalog": [
            {
                "id": rule.id,
                "rule": rule.rule,
                "preferred_skills": list(rule.preferred_skills),
                "activation_status": rule.activation_status,
            }
            for rule in ROUTING_GUARD_RULES
        ],
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "source_refs": ["src/routing/chat.py", "src/routing/recommend.py", "src/routing/localization.py", "src/skills/catalog.py"],
    }


def _prefix_surface(prefix: str) -> str:
    return {
        "$": "Codex/oh-my skill invocation",
        "/": "slash skill invocation",
        "./": "Hermes direct skill invocation",
        "@": "agent or role mention",
    }.get(prefix, "explicit skill invocation")
