"""Deterministic prompt-context accounting for the generated skill pack.

`omh docs skill-context-cost` renders this payload. It answers one question:
how many bytes of `SKILL.md` body does an install carry, and how much of that
body is text repeated verbatim across skills rather than guidance specific to
one workflow?

Three cost classes load differently, and this module measures two of them:

- the index line: one line per installed skill -- its name and a description
  cut to 60 characters -- that Hermes sends on every request. That is the
  per-turn cost, and `src/skills/skill_index.py` measures it, not this module.
- ``skill_body``: `skills/<name>/SKILL.md`. Loaded when the model calls
  `skill_view` (or the person types the skill's slash command): about 8k
  chars per load, and a loaded body stays in history until compaction. The
  total across a profile is the install footprint.
- ``reference``: `skills/<name>/references/*.md`. Progressive disclosure --
  loaded only when a skill or the router explicitly points at it. Moving an
  invariant section from a body into a reference removes it from every load of
  that body and keeps exactly one copy on disk.

Repetition is derived, never hand-classified: for each `##` heading, sections
whose body text is byte-identical across skills are duplicates, and
``duplicate_bytes`` is what an install pays for the second and later copies.
"""

from __future__ import annotations

from .catalog import omh_skill_display_name

from dataclasses import dataclass
from typing import TypedDict

from .catalog import CORE_PROFILE_SKILLS, SKILL_PACKS, SKILL_PACK_NAMES, core_with_packs_skill_names
from .packaging import builtin_skill_reference_templates, builtin_skill_templates
from .render import SkillReferenceTemplate as _SkillReferenceTemplate
from .render import SkillTemplate as _SkillTemplate

SKILL_CONTEXT_COST_SCHEMA_VERSION = "omh_skill_context_cost/v1"

# Deterministic, dependency-free token estimate. Four characters per token is
# the usual English-prose approximation; it is a comparison unit for before/after
# work in this repo, not a tokenizer result.
CHARS_PER_TOKEN_ESTIMATE = 4
ULW_CONTEXT_SKILL_BODY_BYTE_CEILING = 24_000
ULW_CONTEXT_REFERENCE_BYTE_CEILING = 24_000


class ContextSize(TypedDict):
    bytes: int
    lines: int
    estimated_tokens: int


class ContextShare(ContextSize):
    share_percent: float


class ContextReferences(ContextSize):
    file_count: int
    files: list[str]


class HeadingRepetition(TypedDict):
    heading: str
    occurrences: int
    distinct_bodies: int
    bytes: int
    unique_bytes: int
    duplicate_bytes: int
    estimated_duplicate_tokens: int


class SkillContextCostProfile(TypedDict):
    profile: str
    skill_count: int
    skill_body: ContextSize
    repeated: ContextShare
    skill_specific: ContextShare
    references: ContextReferences
    headings: list[HeadingRepetition]


class ContextIncrement(TypedDict):
    skill_body_bytes: int
    reference_file_count: int
    reference_bytes: int
    project_specific_bytes: int
    source_class: str
    ceilings: dict[str, int]
    ceilings_pass: bool


class SkillContextCostPayload(TypedDict):
    schema_version: str
    description: str
    chars_per_token_estimate: int
    catalog_increment: dict[str, ContextIncrement]
    profiles: list[SkillContextCostProfile]


@dataclass(frozen=True)
class SectionSlice:
    skill: str
    heading: str
    body: str


def _split_sections(content: str) -> list[tuple[str, str]]:
    """Split rendered markdown into `(heading, body)` pairs.

    The `## ` line stays at the head of its own body, and frontmatter plus any
    preamble before the first heading is returned under the synthetic heading
    ``"(preamble)"``. Both rules exist so the section bytes of a skill sum to
    exactly ``len(content)`` -- a repeated heading line is repeated cost too.
    """
    sections: list[tuple[str, str]] = []
    heading = "(preamble)"
    buffer: list[str] = []
    for line in content.splitlines(keepends=True):
        if line.startswith("## "):
            sections.append((heading, "".join(buffer)))
            heading = line[3:].strip()
            buffer = [line]
            continue
        buffer.append(line)
    sections.append((heading, "".join(buffer)))
    return sections


def _estimated_tokens(chars: int) -> int:
    return -(-chars // CHARS_PER_TOKEN_ESTIMATE)


def _size_payload(text_chars: int, line_count: int) -> ContextSize:
    return {
        "bytes": text_chars,
        "lines": line_count,
        "estimated_tokens": _estimated_tokens(text_chars),
    }


def _profile_skill_names(profile: str, templates: list[_SkillTemplate]) -> set[str]:
    names = {template.name for template in templates}
    if profile == "full":
        return names
    return {name for name in names if name in CORE_PROFILE_SKILLS}


def _section_slices(names: set[str], templates: list[_SkillTemplate]) -> list[SectionSlice]:
    slices: list[SectionSlice] = []
    for template in templates:
        if template.name not in names:
            continue
        for heading, body in _split_sections(template.content):
            slices.append(SectionSlice(template.name, heading, body))
    return slices


def _heading_repetition(slices: list[SectionSlice]) -> list[HeadingRepetition]:
    grouped: dict[str, list[str]] = {}
    for section in slices:
        grouped.setdefault(section.heading, []).append(section.body)
    rows: list[HeadingRepetition] = []
    for heading, bodies in grouped.items():
        total_bytes = sum(len(body) for body in bodies)
        distinct = set(bodies)
        unique_bytes = sum(len(body) for body in distinct)
        rows.append(
            {
                "heading": heading,
                "occurrences": len(bodies),
                "distinct_bodies": len(distinct),
                "bytes": total_bytes,
                "unique_bytes": unique_bytes,
                "duplicate_bytes": total_bytes - unique_bytes,
                "estimated_duplicate_tokens": _estimated_tokens(total_bytes - unique_bytes),
            }
        )
    rows.sort(key=lambda row: (-int(row["duplicate_bytes"]), str(row["heading"])))
    return rows


def _reference_payload(names: set[str], reference_templates: list[_SkillReferenceTemplate]) -> ContextReferences:
    templates = [
        template for template in reference_templates if template.skill_name in names
    ]
    total_chars = sum(len(template.content) for template in templates)
    total_lines = sum(len(template.content.splitlines()) for template in templates)
    return {
        "file_count": len(templates),
        **_size_payload(total_chars, total_lines),
        "files": sorted(
            f"{omh_skill_display_name(template.skill_name)}/{template.relative_path}" for template in templates
        ),
    }


def _percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(part * 100 / whole, 2)


def _skill_context_cost_profile(
    profile: str,
    templates: list[_SkillTemplate],
    reference_templates: list[_SkillReferenceTemplate],
) -> SkillContextCostProfile:
    names = _profile_skill_names(profile, templates)
    slices = _section_slices(names, templates)
    headings = _heading_repetition(slices)
    total_chars = sum(len(section.body) for section in slices)
    total_lines = sum(len(section.body.splitlines()) for section in slices)
    duplicate_bytes = sum(int(row["duplicate_bytes"]) for row in headings)
    return {
        "profile": profile,
        "skill_count": len(names),
        "skill_body": _size_payload(total_chars, total_lines),
        "repeated": {
            **_size_payload(duplicate_bytes, 0),
            "share_percent": _percent(duplicate_bytes, total_chars),
        },
        "skill_specific": {
            **_size_payload(total_chars - duplicate_bytes, 0),
            "share_percent": _percent(total_chars - duplicate_bytes, total_chars),
        },
        "references": _reference_payload(names, reference_templates),
        "headings": headings,
    }


def skill_context_cost_profile(profile: str) -> SkillContextCostProfile:
    return _skill_context_cost_profile(profile, builtin_skill_templates(), builtin_skill_reference_templates())


def _ulw_context_increment(
    templates: list[_SkillTemplate],
    reference_templates: list[_SkillReferenceTemplate],
) -> ContextIncrement:
    skill = next((template for template in templates if template.name == "context"), None)
    references = [template for template in reference_templates if template.skill_name == "context"]
    skill_body_bytes = len(skill.content) if skill is not None else 0
    reference_bytes = sum(len(template.content) for template in references)
    ceilings = {
        "skill_body_bytes": ULW_CONTEXT_SKILL_BODY_BYTE_CEILING,
        "reference_bytes": ULW_CONTEXT_REFERENCE_BYTE_CEILING,
    }
    return {
        "skill_body_bytes": skill_body_bytes,
        "reference_file_count": len(references),
        "reference_bytes": reference_bytes,
        "project_specific_bytes": 0,
        "source_class": "static_catalog_templates_only",
        "ceilings": ceilings,
        "ceilings_pass": (
            skill_body_bytes > 0
            and len(references) == 2
            and skill_body_bytes <= ceilings["skill_body_bytes"]
            and reference_bytes <= ceilings["reference_bytes"]
        ),
    }


def _pack_context_cost_summary(
    pack: str,
    templates: list[_SkillTemplate],
    reference_templates: list[_SkillReferenceTemplate],
) -> dict[str, object]:
    selected = set(core_with_packs_skill_names((pack,)))
    names = {template.name for template in templates if template.name in selected}
    slices = _section_slices(names, templates)
    total_chars = sum(len(section.body) for section in slices)
    total_lines = sum(len(section.body.splitlines()) for section in slices)
    return {
        "pack": pack,
        "pack_only_skill_count": len(SKILL_PACKS[pack]),
        "core_plus_pack_skill_count": len(names),
        "skill_body": _size_payload(total_chars, total_lines),
        "references": _reference_payload(names, reference_templates),
    }


def skill_context_cost_payload() -> SkillContextCostPayload:
    templates = builtin_skill_templates()
    reference_templates = builtin_skill_reference_templates()
    return {
        "schema_version": SKILL_CONTEXT_COST_SCHEMA_VERSION,
        "description": (
            "Deterministic prompt-context accounting for generated skill bodies. Byte counts are exact; "
            "token counts are a chars/4 estimate for before/after comparison, not tokenizer output. "
            "Reference files are progressive-disclosure surfaces and are reported outside the "
            "skill-body total. A skill body loads when the model views the skill and stays in history "
            "until compaction; only the skill's index line is sent on every request."
        ),
        "chars_per_token_estimate": CHARS_PER_TOKEN_ESTIMATE,
        "catalog_increment": {
            "ulw-context": _ulw_context_increment(templates, reference_templates),
        },
        "profiles": [
            _skill_context_cost_profile(profile, templates, reference_templates) for profile in ("core", "full")
        ],
        "packs": [
            _pack_context_cost_summary(pack, templates, reference_templates) for pack in SKILL_PACK_NAMES
        ],
    }


def skill_context_cost_markdown() -> str:
    payload = skill_context_cost_payload()
    lines = [
        "# Generated Skill Context Cost",
        "",
        str(payload["description"]),
        "",
    ]
    for profile in payload["profiles"]:
        body = profile["skill_body"]
        repeated = profile["repeated"]
        specific = profile["skill_specific"]
        references = profile["references"]
        lines.extend(
            [
                f"## {profile['profile']} profile",
                "",
                f"- Installed skills: {profile['skill_count']}",
                f"- Skill body total (install footprint; each body loads per skill view): "
                f"{body['bytes']} bytes, {body['lines']} lines, "
                f"~{body['estimated_tokens']} tokens",
                f"- Repeated across skills: {repeated['bytes']} bytes "
                f"(~{repeated['estimated_tokens']} tokens, {repeated['share_percent']}%)",
                f"- Skill-specific: {specific['bytes']} bytes "
                f"(~{specific['estimated_tokens']} tokens, {specific['share_percent']}%)",
                f"- On-demand references: {references['file_count']} files, {references['bytes']} bytes "
                f"(~{references['estimated_tokens']} tokens)",
                "",
                "| Heading | Occurrences | Distinct bodies | Bytes | Duplicate bytes |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in profile["headings"]:
            lines.append(
                f"| {row['heading']} | {row['occurrences']} | {row['distinct_bodies']} | "
                f"{row['bytes']} | {row['duplicate_bytes']} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
