from __future__ import annotations

from functools import lru_cache

from .catalog import installable_skill_definitions
from .render import SkillReferenceTemplate, SkillTemplate, router_reference_templates, router_skill, workflow_skill


def builtin_skill_templates() -> list[SkillTemplate]:
    return list(_builtin_skill_templates_cached())


def builtin_skill_reference_templates() -> list[SkillReferenceTemplate]:
    return router_reference_templates()


@lru_cache(maxsize=1)
def _builtin_skill_templates_cached() -> tuple[SkillTemplate, ...]:
    names = [definition.name for definition in installable_skill_definitions()]
    return (router_skill(), *[workflow_skill(name) for name in names if name != "oh-my-hermes"])
