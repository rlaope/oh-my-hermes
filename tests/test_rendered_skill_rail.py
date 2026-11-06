"""A rendered skill names only siblings it can load and files it ships.

Three render defects shared one shape: a line a model follows pointed at
something that was not there. A sibling written by its canonical name (`research`)
is not a name `skill_view` loads; a body ending in `advisory local context` lost
its hand-back line; a full contract named `references/procedure.md` for a skill
that ships no such file. The rewrite that fixes the first runs in both projections
and must not touch a word that only shares an installed skill's name.
"""

from __future__ import annotations

import re
import unittest

from omh.skills.catalog import installable_skill_definitions, omh_skill_display_name
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import (
    _CANONICAL_LINE_PREFIXES,
    _ROUTER_CANONICAL_REFERENCES,
    _UPSTREAM_ATTRIBUTION,
    agent_skill_templates,
    builtin_skill_templates,
    portable_reference_templates,
)

_BACKTICKED = re.compile(r"`([a-z0-9][a-z0-9-]*)`")
# A path qualified by its owner (`ulw-work`'s `references/tdd-red-green.md`) is a pointer into a sibling.
_REFERENCE_PATH = re.compile(r"(?<!'s )`(references/[A-Za-z0-9_./-]+)`")


def _prose_lines(content: str) -> list[str]:
    lines: list[str] = []
    fenced = False
    for line in content.split("\n"):
        if line.strip().startswith("```"):
            fenced = not fenced
        elif (
            not fenced
            and not line.strip().lower().startswith(_CANONICAL_LINE_PREFIXES)
            and not _UPSTREAM_ATTRIBUTION.search(line)
        ):
            lines.append(line)
    return lines


class RenderedSkillRailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installed = frozenset(definition.name for definition in installable_skill_definitions())
        self.canonical = {omh_skill_display_name(name): name for name in self.installed}
        self.hermes_refs = builtin_skill_reference_templates()
        self.hermes = {t.name: t.content for t in builtin_skill_templates()}
        self.portable = {t.name: t.content for t in agent_skill_templates()}
        self.portable_refs = portable_reference_templates(self.hermes_refs)

    def _projections(self):
        yield "hermes", self.hermes, [(r.skill_name, r.relative_path, r.content) for r in self.hermes_refs]
        yield "portable", self.portable, [(r.skill_name, r.relative_path, r.content) for r in self.portable_refs]

    def _owner(self, name: str) -> str:
        return self.canonical.get(name, name)

    def test_a_hyphenated_sibling_is_always_a_loadable_label(self) -> None:
        stale = []
        for projection, bodies, refs in self._projections():
            texts = [(name, "SKILL.md", content) for name, content in bodies.items()]
            texts += list(refs)
            for owner, path, content in texts:
                owner = self._owner(owner)
                if owner in {"oh-my-hermes"} and (path == "SKILL.md" or path in _ROUTER_CANONICAL_REFERENCES):
                    continue
                for line in _prose_lines(content):
                    for token in _BACKTICKED.findall(line):
                        if "-" in token and token in self.installed and token != owner and omh_skill_display_name(token) != token:
                            stale.append((projection, owner, path, token))
        self.assertEqual(sorted(set(stale)), [], "a rendered file names an installed skill by its canonical name")

    def test_one_word_pointers_are_labels_and_ordinary_words_are_not_rewritten(self) -> None:
        refs = {
            "hermes": {(o, p): c for o, p, c in self._projections().__next__()[2]},
            "portable": {(self._owner(o), p): c for o, p, c in list(self._projections())[1][2]},
        }

        def text(projection: str, owner: str, path: str) -> str:
            return refs[projection][(owner, path)]

        for projection in ("hermes", "portable"):
            with self.subTest(projection=projection):
                # Words that only share an installed skill's name stay as written.
                self.assertIn("a follow-up `plan` reports no changes", text(projection, "iac-change", "references/iac-change-method.md"))
                self.assertIn("a modal's `cancel` can be prevented", text(projection, "frontend", "references/forms-and-input.md"))
                self.assertIn("`plan` warns", text(projection, "show-reel", "references/craft-audio.md"))
                self.assertIn("Required result fields: `backend`", text(projection, "geospatial-analysis", "references/procedure.md"))
                # An upstream project's skill is credited by its own name.
                self.assertIn("`frontend` skill of `code-yeongyu/oh-my-openagent@", text(projection, "frontend", "references/design-system-contract.md"))
                self.assertIn("`frontend` skill of `code-yeongyu/oh-my-openagent@", text(projection, "design-quality-gate", "references/design-critique-rubric.md"))
        # A Hermes config key in a body, and a real one-word pointer.
        for bodies in (self.hermes, self.portable):
            for name, content in bodies.items():
                if self._owner(name) == "websearch-setup":
                    self.assertIn("(`backend`, `search_backend`", content)
        web = next(c for n, c in self.hermes.items() if n == "web-research")
        self.assertIn("use `ulw-research`", web)

    def test_the_router_keeps_catalog_names_only_in_its_registries(self) -> None:
        refs = {r.relative_path: r.content for r in self.hermes_refs if r.skill_name == "oh-my-hermes"}
        self.assertNotIn("registry in `oh-my-hermes`", refs["references/skill-common-rail.md"])
        self.assertIn("registry in `omh-routing`", refs["references/skill-common-rail.md"])
        self.assertIn("`oh-my-hermes`", refs["references/workflow-registry.md"])

    def test_no_body_or_reference_ends_in_the_lost_hand_back_fragment(self) -> None:
        for projection, bodies, refs in self._projections():
            for name, content in bodies.items():
                with self.subTest(projection=projection, skill=name):
                    self.assertFalse(content.rstrip().endswith("advisory local context"))
                    if "## Workflow Lane" in content:
                        lane = content.split("## Workflow Lane", 1)[1].split("\n## ")[0]
                        self.assertIn("\n- ", lane)
            for owner, path, content in refs:
                with self.subTest(projection=projection, skill=owner, path=path):
                    self.assertFalse(content.rstrip().endswith("advisory local context"))

    def test_every_references_path_a_body_names_ships_with_that_skill(self) -> None:
        missing = []
        for projection, bodies, refs in self._projections():
            shipped: dict[str, set[str]] = {}
            for owner, path, _ in refs:
                shipped.setdefault(self._owner(owner), set()).add(path)
            for name, content in bodies.items():
                owner = self._owner(name)
                files = [(f"{name}/SKILL.md", content)] + [
                    (f"{o}/{p}", c) for o, p, c in refs if self._owner(o) == owner
                ]
                for where, text in files:
                    for line in text.split("\n"):
                        if "skill_view(" in line:
                            continue
                        for path in _REFERENCE_PATH.findall(line):
                            if path not in shipped.get(owner, set()):
                                missing.append((projection, where, path))
        self.assertEqual(sorted(set(missing)), [], "a rendered file names a references file the skill does not ship")


if __name__ == "__main__":
    unittest.main()
