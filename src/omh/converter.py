from __future__ import annotations

import re
from pathlib import Path

from .skill_pack import DESCRIPTIONS, SkillReferenceTemplate, SkillTemplate
from .skills.catalog import (
    OMH_SKILL_DISPLAY_NAME_OVERRIDES,
    OMH_SKILL_NAME_PREFIX,
    ULW_SKILL_NAME_PREFIX,
    omh_description,
    omh_skill_display_name,
)

FRONTMATTER_RE = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.DOTALL)


_CANONICAL_BY_OVERRIDE = {
    display: canonical for canonical, display in OMH_SKILL_DISPLAY_NAME_OVERRIDES.items()
}


def extract_name(raw: str, fallback: str) -> str:
    """Return the canonical install identity for a source SKILL.md.

    The frontmatter `name` is a rendered display label and may already carry a
    display prefix (re-importing OMH's own generated taps through
    `omh setup --source <dir>` hits exactly that). Strip it here so the install
    directory, the manifest key, and the curated `DESCRIPTIONS` lookup all key on
    the canonical name.

    Both prefixes have to be stripped: workflow-engine skills render `ulw-`, so
    stripping only `omh-` would round-trip `ultrawork` back as `ulw-ultrawork`
    and install it into the wrong directory under a name nothing routes to.
    """
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return fallback
    for line in match.group("meta").splitlines():
        if line.startswith("name:"):
            rendered = line.split(":", 1)[1].strip().strip("'\"")
            # A hand-picked label is not `prefix + canonical`, so stripping the
            # prefix invents a name that owns nothing: `omh-routing` became
            # `routing`, `ulw-work` became `work`. Reverse the override map first
            # and only fall back to stripping for the mechanical labels.
            canonical = _CANONICAL_BY_OVERRIDE.get(rendered)
            if canonical is not None:
                return canonical
            for prefix in (OMH_SKILL_NAME_PREFIX, ULW_SKILL_NAME_PREFIX):
                if rendered.startswith(prefix):
                    return rendered.removeprefix(prefix) or fallback
            return rendered or fallback
    return fallback


def convert_skill(raw: str, fallback_name: str) -> SkillTemplate:
    name = extract_name(raw, fallback_name)
    description = DESCRIPTIONS.get(name, omh_description(f"Hermes workflow skill for {name}."))
    # Imported skills are wrapper-installed too, so they render the same display
    # prefix as the generated catalog. `SkillTemplate.name` stays canonical and
    # keeps owning the `skills/<name>/` directory.
    content = _replace_frontmatter_description(
        raw, name=omh_skill_display_name(name), description=description
    ).rstrip() + """

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


def convert_references_from_dir(source_dir: Path) -> list[SkillReferenceTemplate]:
    """Copy progressive references beside each imported skill into the managed pack."""
    templates: list[SkillReferenceTemplate] = []
    for skill_file in discover_skill_files(source_dir):
        raw = skill_file.read_text(encoding="utf-8")
        skill_name = extract_name(raw, skill_file.parent.name)
        references_dir = skill_file.parent / "references"
        if not references_dir.is_dir():
            continue
        for reference_file in sorted(references_dir.rglob("*.md")):
            if ".git" in reference_file.parts:
                continue
            templates.append(
                SkillReferenceTemplate(
                    skill_name=skill_name,
                    relative_path=reference_file.relative_to(skill_file.parent).as_posix(),
                    content=reference_file.read_text(encoding="utf-8"),
                )
            )
    return templates
