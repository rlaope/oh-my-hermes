from __future__ import annotations

import re
from pathlib import Path

from .skill_pack import DESCRIPTIONS, SkillTemplate

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
    description = DESCRIPTIONS.get(name, f"Hermes workflow skill for {name}.")
    content = raw.rstrip() + f"""

## Hermes Compatibility Contract

This skill was imported by `omh` from a local skill source.

- Keep the upstream workflow intent, but adapt runtime behavior to Hermes Agent.
- Do not require runtime features that Hermes Agent does not expose.
- Use Hermes `skills_list`, `skill_view`, file tools, terminal tools, and Hermes delegation when available.
"""
    return SkillTemplate(name=name, content=content + "\n")


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
