from __future__ import annotations

from .catalog import (
    BESPOKE_SKILL_BODY_NAMES,
    CORE_PROFILE_SKILLS,
    CORE_SKILLS,
    DESCRIPTIONS,
    OMH_SKILL_DISPLAY_NAME_OVERRIDES,
    OMH_SKILL_NAME_PREFIX,
    SKILL_PACKS,
    SKILL_PACK_NAMES,
    HarnessDefinition,
    SkillDefinition,
    SkillExample,
    SurfaceExposure,
    builtin_definitions,
    builtin_harnesses,
    capability_definitions,
    core_with_packs_skill_names,
    harness_definition,
    harness_quality_contract,
    hermes_skill_categories,
    hermes_skill_category,
    installable_skill_definitions,
    installable_skill_names,
    omh_skill_display_name,
    omh_skill_install_path,
    resolve_skill_pack_names,
    routable_definitions,
    routable_skill_names,
    skill_exposure_payload,
    surface_exposure_for_skill,
    workflow_reference_definitions,
)

# The render-side exports resolve on first use (PEP 562) instead of at
# package import. Importing any submodule -- `routing.intent` imports
# `catalog_types` -- runs this file, and an eager `from .render import` here
# pulled `render` and, through it, the plugin bundle's `awareness` into every
# router import; `awareness` imports `routing.intent` back, which is the
# cycle #2013 worked around. The catalog names above stay eager: `catalog`
# imports nothing on that path.
_RENDER_SIDE_EXPORTS: dict[str, str] = {
    "builtin_skill_reference_templates": "packaging",
    "builtin_skill_templates": "packaging",
    "builtin_skill_support_templates": "packaging",
    "SkillSupportTemplate": "support_files",
    "SkillReferenceTemplate": "render",
    "SkillTemplate": "render",
    "router_skill": "render",
    "workflow_reference_payload": "render",
    "workflow_skill": "render",
}


def __getattr__(name: str) -> object:
    owner = _RENDER_SIDE_EXPORTS.get(name)
    if owner is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if owner == "packaging":
        from . import packaging as module
    elif owner == "support_files":
        from . import support_files as module
    else:
        from . import render as module
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_RENDER_SIDE_EXPORTS))


__all__ = [
    "BESPOKE_SKILL_BODY_NAMES",
    "CORE_PROFILE_SKILLS",
    "CORE_SKILLS",
    "DESCRIPTIONS",
    "OMH_SKILL_DISPLAY_NAME_OVERRIDES",
    "OMH_SKILL_NAME_PREFIX",
    "SKILL_PACKS",
    "SKILL_PACK_NAMES",
    "HarnessDefinition",
    "SkillDefinition",
    "SkillExample",
    "SurfaceExposure",
    "SkillTemplate",
    "SkillReferenceTemplate",
    "SkillSupportTemplate",
    "builtin_skill_support_templates",
    "builtin_definitions",
    "builtin_harnesses",
    "capability_definitions",
    "core_with_packs_skill_names",
    "harness_definition",
    "harness_quality_contract",
    "hermes_skill_categories",
    "hermes_skill_category",
    "installable_skill_definitions",
    "installable_skill_names",
    "omh_skill_display_name",
    "omh_skill_install_path",
    "resolve_skill_pack_names",
    "routable_definitions",
    "routable_skill_names",
    "skill_exposure_payload",
    "surface_exposure_for_skill",
    "workflow_reference_definitions",
    "builtin_skill_templates",
    "builtin_skill_reference_templates",
    "router_skill",
    "workflow_reference_payload",
    "workflow_skill",
]
