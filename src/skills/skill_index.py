"""The skill index lines Hermes sends on every request, rendered the way Hermes renders them.

A skill costs context in two very different ways, and this module measures the
one that is paid per turn. Hermes puts one line per installed skill into the
system prompt's `<available_skills>` block, every request: the skill's name and
its description cut to `SKILL_PROMPT_DESC_LIMIT` characters. The `SKILL.md`
body is not in that block. It loads when the model calls `skill_view(name)` (or
the person types `/skill-name`), costs about 8k characters per load, and then
stays in the conversation history until compaction. `src/skills/context_cost.py`
measures bodies; this module measures the index.

The rendering follows `agent/prompt_builder.py::_render_skills_index` in
hermes-agent: a `  {category}:` header per category directory, then
`    - {name}: {description}` per skill, names sorted inside a category and
categories sorted. OMH installs into `skills.external_dirs`. Hermes would
render a category `DESCRIPTION.md` found there as `  {category}: {description}`
(`_build_skills_system_prompt_inner` reads them from each external dir), but
OMH ships none, so this producer renders bare headers;
`tests/test_per_turn_budgets.py` fails if the packaged skills ever carry one,
since this count would then be short.

The same visible window is what a model reads to decide whether to load a
skill, and Hermes's index preamble tells it to load anything "even partially
relevant". So two skills whose visible windows open with the same words are
two skills a model cannot tell apart until it has paid for both bodies.
`index_opening_collisions` finds them; the structure lint fails on a group that
is not in `REVIEWED_SHARED_INDEX_OPENINGS`.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Iterable

from .catalog import omh_skill_install_path
from .catalog_types import OMH_DESCRIPTION_PREFIX
from .packaging import builtin_skill_templates

# Copied from hermes-agent `agent/skill_utils.py` (`SKILL_PROMPT_DESC_LIMIT = 60`,
# used by `clip_skill_description`: a longer description is cut at the last
# whitespace inside its first 58 characters, trailing punctuation is dropped,
# and `...` is appended; a single word with no boundary falls back to
# `desc[:SKILL_PROMPT_DESC_LIMIT - 3] + "..."`).
# Copied rather than imported because OMH never imports Hermes at runtime: the
# maintenance CLI and CI run without a Hermes checkout.
# `UpstreamDescriptionLimitPinTests` in `tests/test_per_turn_budgets.py`
# compares this value with the upstream line whenever a Hermes checkout is
# importable, so a Hermes change to the limit fails there rather than skewing
# `skill_index_chars` silently.
SKILL_PROMPT_DESC_LIMIT = 60
_TRUNCATION_SUFFIX = "..."
# The same two patterns `clip_skill_description` uses: the last whitespace run
# and the word after it, and the punctuation stripped from the cut's end.
_LAST_WHITESPACE = re.compile(r"\s\S*$")
_CLIP_TRAIL = re.compile(r"[\s.,;:\-\u2013\u2014(/]+$")

# How many leading words of the visible description make its "opening" for the
# distinctness lint. Measured on the catalog when the lint landed: at two words
# eight groups share an opening, most of them a bare "Hermes <domain>" that the
# third word already separates; at three words exactly the two reviewed groups
# below remain; at four, none. Three is the narrowest count that still catches
# a lead phrase carrying no trigger at all ("Hermes adaptation for").
INDEX_OPENING_WORD_COUNT = 3

# Openings that more than one installable skill shares, each with the exact set
# of skills that share it and why it stands. Empty since every description was
# rewritten to open on the user's situation: the two groups this once recorded
# ("hermes adaptation for" and "policy overlay for") now open on what the user
# is doing. The lint fails when a group gains a member, when a new group
# appears, and (on the full catalog) when a recorded member no longer shares
# its opening.
REVIEWED_SHARED_INDEX_OPENINGS: dict[str, tuple[frozenset[str], str]] = {}

_WORD_EDGE_PUNCTUATION = string.punctuation + "\u2014\u2013"

_FRONTMATTER_HEAD = re.compile(r"^---\nname: (.*)\ndescription: (.*)\n")


def hermes_index_description(description: str) -> str:
    """The description text Hermes shows in the index for one skill.

    Mirrors `extract_skill_description`: strip whitespace, strip surrounding
    quote characters, then, when longer than the limit, cut at the last
    whitespace inside the first 58 characters (so no word is shown half),
    drop trailing punctuation, and append `...`. A description with no
    whitespace to cut at is cut to 57 characters plus `...`.
    """
    text = description.strip().strip("'\"")
    if len(text) <= SKILL_PROMPT_DESC_LIMIT:
        return text
    head = text[: SKILL_PROMPT_DESC_LIMIT - 2]
    boundary = _LAST_WHITESPACE.search(head)
    if boundary is None or boundary.start() == 0:
        return text[: SKILL_PROMPT_DESC_LIMIT - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX
    return _CLIP_TRAIL.sub("", head[: boundary.start()]) + _TRUNCATION_SUFFIX


def index_opening(description: str) -> str:
    """The first `INDEX_OPENING_WORD_COUNT` words a model sees, casefolded.

    Taken from the visible window only (the truncation suffix removed), after
    the `[omh] ` prefix, which every OMH skill shares and so separates none.
    Punctuation around a word is dropped, so a comma or colon cannot separate
    two openings a model reads as the same; a token that is only punctuation
    is not a word.
    """
    visible = hermes_index_description(description).removesuffix(_TRUNCATION_SUFFIX)
    if visible.lower().startswith(OMH_DESCRIPTION_PREFIX):
        visible = visible[len(OMH_DESCRIPTION_PREFIX) :]
    words = [word.strip(_WORD_EDGE_PUNCTUATION).casefold() for word in visible.split()]
    return " ".join([word for word in words if word][:INDEX_OPENING_WORD_COUNT])


def index_opening_collisions(descriptions: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    """Openings shared by two or more distinct skills, from `(skill, description)` pairs."""
    groups: dict[str, set[str]] = {}
    for skill, description in descriptions:
        opening = index_opening(description)
        if opening:
            groups.setdefault(opening, set()).add(skill)
    return {opening: frozenset(skills) for opening, skills in groups.items() if len(skills) > 1}


def _frontmatter_scalar(encoded: str) -> str:
    return str(json.loads(encoded)) if encoded.startswith('"') else encoded


def _full_profile_frontmatter() -> list[tuple[str, str, str]]:
    """`(canonical, installed name, full description)` read from each rendered SKILL.md."""
    rows: list[tuple[str, str, str]] = []
    for template in builtin_skill_templates():
        match = _FRONTMATTER_HEAD.match(template.content)
        if match is None:
            raise ValueError(f"skill {template.name} has no name/description frontmatter head")
        rows.append((template.name, _frontmatter_scalar(match.group(1)), _frontmatter_scalar(match.group(2))))
    return rows


def full_profile_index_descriptions() -> list[tuple[str, str]]:
    """`(canonical skill, description)` exactly as the installed files carry them."""
    return [(canonical, description) for canonical, _name, description in _full_profile_frontmatter()]


def full_profile_skill_index_lines() -> list[str]:
    """Every `<available_skills>` line a full OMH install contributes, in Hermes order."""
    by_category: dict[str, list[tuple[str, str]]] = {}
    for canonical, name, description in _full_profile_frontmatter():
        category = omh_skill_install_path(canonical).split("/", 1)[0]
        by_category.setdefault(category, []).append((name, hermes_index_description(description)))
    lines: list[str] = []
    for category in sorted(by_category):
        lines.append(f"  {category}:")
        for name, description in sorted(by_category[category]):
            lines.append(f"    - {name}: {description}" if description else f"    - {name}")
    return lines


def skill_index_chars() -> int:
    """Characters the full profile adds to every request's skill index (lines joined by newlines)."""
    return len("\n".join(full_profile_skill_index_lines()))


def skill_index_line_max_chars() -> int:
    """The longest single skill line in that index."""
    return max(len(line) for line in full_profile_skill_index_lines() if line.startswith("    - "))


__all__ = [
    "INDEX_OPENING_WORD_COUNT",
    "REVIEWED_SHARED_INDEX_OPENINGS",
    "SKILL_PROMPT_DESC_LIMIT",
    "full_profile_index_descriptions",
    "full_profile_skill_index_lines",
    "hermes_index_description",
    "index_opening",
    "index_opening_collisions",
    "skill_index_chars",
    "skill_index_line_max_chars",
]
