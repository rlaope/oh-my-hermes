from __future__ import annotations

import re
from pathlib import Path

from .skill_pack import DESCRIPTIONS, SkillTemplate
from .skills.catalog import omh_description

FRONTMATTER_RE = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.DOTALL)


def extract_name(raw: str, fallback: str) -> str:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return fallback
    for line in match.group("meta").splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip("'\"") or fallback
    return fallback


def convert_skill(raw: str, fallback_name: str) -> SkillTemplate:
    name = extract_name(raw, fallback_name)
    description = DESCRIPTIONS.get(name, omh_description(f"Hermes workflow skill for {name}."))
    content = _replace_frontmatter_description(raw, name=name, description=description).rstrip() + f"""

## Hermes Compatibility Contract

This skill was imported by `omh` from a local skill source.

- Keep the upstream workflow intent, but adapt runtime behavior to Hermes Agent.
- Do not require runtime features that Hermes Agent does not expose.
- Use Hermes `skills_list`, `skill_view`, file tools, terminal tools, and Hermes delegation when available.
"""
    return SkillTemplate(name=name, content=content + "\n")


def _replace_frontmatter_description(raw: str, *, name: str, description: str) -> str:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return f"---\nname: {name}\ndescription: {description}\n---\n\n{raw}"
    lines = match.group("meta").splitlines()
    output: list[str] = []
    saw_name = False
    saw_description = False
    for line in lines:
        if line.startswith("name:"):
            output.append(f"name: {name}")
            saw_name = True
        elif line.startswith("description:"):
            output.append(f"description: {description}")
            saw_description = True
        else:
            output.append(line)
    if not saw_name:
        output.insert(0, f"name: {name}")
    if not saw_description:
        output.insert(1, f"description: {description}")
    return "---\n" + "\n".join(output) + "\n---\n" + match.group("body")


def discover_skill_files(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(f"source does not exist: {source_dir}")
    return sorted(path for path in source_dir.rglob("SKILL.md") if ".git" not in path.parts)


def convert_from_dir(source_dir: Path) -> list[SkillTemplate]:
    templates: list[SkillTemplate] = []
    for skill_file in discover_skill_files(source_dir):
        raw = skill_file.read_text(encoding="utf-8")
        templates.append(convert_skill(raw, skill_file.parent.name))
    return templates
