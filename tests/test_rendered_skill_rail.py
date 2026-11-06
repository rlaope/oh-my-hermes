"""A rendered skill names only siblings it can load and files it ships.

Three render defects shared one shape: a line a model follows pointed at
something that was not there. A sibling written by its canonical name (`research`)
is not a name `skill_view` loads; a body ending in `advisory local context` lost
its hand-back line; a full contract named `references/procedure.md` for a skill
that ships no such file.
"""

from __future__ import annotations

import re
import unittest

from omh.skills.catalog import installable_skill_definitions, omh_skill_display_name
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import builtin_skill_templates

_BACKTICKED = re.compile(r"`([a-z0-9][a-z0-9-]*)`")
# Lines that list canonical identifiers on purpose: trigger lists and metadata.
_CANONICAL_LINE_PREFIXES = (
    "strong routing signals",
    "routing signals",
    "category:",
    "phase:",
    "hermes role:",
    "quality tier:",
    "reasoning demand:",
    "preferred harness",
    "- current lane:",
    "name:",
    "related_skills:",
)
# A path qualified by its owner (`ulw-work`'s `references/tdd-red-green.md`) is a pointer into a sibling.
# The router speaks catalog names (its registries and keyword lists are what
# `omh_recommend` returns), and these words are an installed skill's name used as
# something else in that file: a Terraform subcommand, a DOM event, a tool argument,
# another project's skill.
_ROUTER = frozenset({"oh-my-hermes", "omh-routing"})
_NOT_A_SIBLING = frozenset(
    {
        ("iac-change", "plan"),
        ("frontend", "cancel"),
        ("show-reel", "plan"),
        ("maestro", "research"),
        ("ultrawork", "context"),
        ("dag-ulw", "backend"),
        ("geospatial-analysis", "backend"),
        ("design-quality-gate", "frontend"),
        ("visual-qa", "frontend"),
    }
)
_REFERENCE_PATH = re.compile(r"(?<!'s )`(references/[A-Za-z0-9_./-]+)`")


def _prose_lines(content: str) -> list[str]:
    """Lines that hand work to a reader: not fenced code, not a canonical-identifier list."""
    lines: list[str] = []
    fenced = False
    for line in content.split("\n"):
        if line.strip().startswith("```"):
            fenced = not fenced
        elif not fenced and not line.strip().lower().startswith(_CANONICAL_LINE_PREFIXES):
            lines.append(line)
    return lines


class RenderedSkillRailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installed = frozenset(definition.name for definition in installable_skill_definitions())
        self.bodies = {template.name: template.content for template in builtin_skill_templates()}
        self.references = builtin_skill_reference_templates()

    def test_every_rendered_body_and_reference_names_siblings_by_loadable_label(self) -> None:
        texts = [(name, f"{name}/SKILL.md", content) for name, content in self.bodies.items()]
        texts += [(ref.skill_name, f"{ref.skill_name}/{ref.relative_path}", ref.content) for ref in self.references]
        stale = sorted(
            (where, token)
            for owner, where, content in texts
            if owner not in _ROUTER
            for line in _prose_lines(content)
            for token in _BACKTICKED.findall(line)
            if token in self.installed
            and omh_skill_display_name(token) != token
            and token != owner
            and (owner, token) not in _NOT_A_SIBLING
        )
        self.assertEqual(stale, [], "a rendered file names an installed skill by its canonical name")

    def test_no_body_ends_in_the_lost_hand_back_fragment(self) -> None:
        for name, content in self.bodies.items():
            with self.subTest(skill=name):
                self.assertFalse(content.rstrip().endswith("advisory local context"), name)
                if "## Workflow Lane" in content:
                    lane = content.split("## Workflow Lane", 1)[1]
                    self.assertIn("\n- ", lane.split("\n## ")[0], f"{name}: the lane section carries no line")

    def test_no_reference_ends_in_the_lost_hand_back_fragment(self) -> None:
        for ref in self.references:
            with self.subTest(skill=ref.skill_name, path=ref.relative_path):
                self.assertFalse(ref.content.rstrip().endswith("advisory local context"))

    def test_every_references_path_a_body_names_ships_with_that_skill(self) -> None:
        shipped: dict[str, set[str]] = {}
        for ref in self.references:
            shipped.setdefault(ref.skill_name, set()).add(ref.relative_path)
        missing = []
        for name, content in self.bodies.items():
            files = [(f"{name}/SKILL.md", content)]
            files += [
                (f"{ref.skill_name}/{ref.relative_path}", ref.content)
                for ref in self.references
                if ref.skill_name == name
            ]
            for where, text in files:
                for line in text.split("\n"):
                    if "skill_view(" in line:
                        continue
                    for path in _REFERENCE_PATH.findall(line):
                        if path not in shipped.get(name, set()):
                            missing.append((where, path))
        self.assertEqual(sorted(set(missing)), [], "a rendered file names a references file the skill does not ship")


if __name__ == "__main__":
    unittest.main()
