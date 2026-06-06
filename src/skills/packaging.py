from __future__ import annotations

from .catalog import builtin_definitions
from .render import SkillTemplate, router_skill, workflow_skill


def builtin_skill_templates() -> list[SkillTemplate]:
    names = [definition.name for definition in builtin_definitions()]
    return [router_skill(), *[workflow_skill(name) for name in names if name != "oh-my-hermes"]]
