"""Skill bodies name their siblings by the name the host can load.

`skill_view` loads an installed skill by the label its directory carries
(`omh-apps`, `ulw-research`). The catalog writes siblings by canonical name
(`connector-operator`, `research`) because routing and the deference graph
read those, so the renderer translates them on the way out. These pin the
translation on both projections, the derived `related_skills` frontmatter,
and the lines that hand a request to a skill Hermes bundles.
"""

from __future__ import annotations

from dataclasses import replace
import re
import unittest

from omh.skills.catalog import builtin_definitions, installable_skill_definitions, omh_skill_display_name
from omh.skills.catalog_portable import portable_skill_names
from omh.skills.catalog_types import HERMES_BUNDLED_SKILL_NAMES, HermesSkillLine, PortableLine
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import (
    agent_skill_template,
    builtin_skill_templates,
    loadable_skill_mentions,
    related_skill_names,
)

_BACKTICKED = re.compile(r"`([^`]+)`")

# Each owner and the bundled Hermes skills its `do_not_use_when` hands a request
# to. Every owner names each of them in exactly one line, so a second line or a
# lost one changes this table.
EXPECTED_BUNDLED_DEFERRALS = {
    "agent-board": ("sdlc-review",),
    "ai-job-search": ("grounded-citations",),
    "ai-slop-cleaner": ("simplify-code",),
    "app-debugging": ("systematic-debugging",),
    "biomedical-evidence": ("grounded-citations",),
    "code-review": ("sdlc-review", "requesting-code-review"),
    "codebase-uml": ("architecture-diagram",),
    "content-operator": ("humanizer",),
    "decision-prototype": ("spike",),
    "github-event-ops": ("github",),
    "github-issue-intake": ("github",),
    "maestro": ("claude-code", "codex", "opencode"),
    "materials-package": ("pdf", "docx", "powerpoint", "xlsx"),
    "meeting-brief": ("meeting-action-items",),
    "research-department": ("competitor-news-monitor", "arxiv"),
    "show-reel": ("manim-video", "ascii-video"),
    "skill": ("hermes-agent-skill-authoring",),
    "ultraqa": ("dogfood",),
    "visual-qa": ("dogfood",),
    "web-research": ("grounded-citations", "arxiv"),
    "wiki": ("llm-wiki",),
}


def _do_not_use_section(content: str) -> list[str]:
    match = re.search(r"^## Do Not Use When\n\n(.*?)\n\n(?=## )", content, re.S | re.M)
    if match is None:
        return []
    return [line[2:] for line in match.group(1).split("\n")]


def _handoff_paragraph(content: str) -> str | None:
    match = re.search(r"^Handoff policy:\n\n(.*?)(?:\n\n|\Z)", content, re.S | re.M)
    return match.group(1) if match else None


def _related_line(content: str) -> str | None:
    frontmatter = content.split("---", 2)[1]
    match = re.search(r"^    related_skills: \[(.*)\]$", frontmatter, re.M)
    return match.group(1) if match else None


class LoadableSiblingNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definitions = {definition.name: definition for definition in installable_skill_definitions()}
        self.installed = frozenset(self.definitions)
        self.hermes = {template.name: template.content for template in builtin_skill_templates()}
        # A progressive-disclosure body keeps its boundary lines in the full
        # contract it points at, so that file is where they render on Hermes.
        self.full_contracts = {
            template.skill_name: template.content
            for template in builtin_skill_reference_templates()
            if template.relative_path == "references/full-contract.md"
        }

    def _hermes_boundary(self, name: str) -> list[str]:
        return _do_not_use_section(self.hermes[name]) or _do_not_use_section(self.full_contracts.get(name, ""))

    def test_no_installed_sibling_is_named_canonically_in_a_hermes_body(self) -> None:
        stale = sorted(
            (name, token)
            for name in self.hermes
            for line in self._hermes_boundary(name)
            for token in _BACKTICKED.findall(line)
            if token in self.installed and omh_skill_display_name(token) != token
        )
        self.assertEqual(stale, [], "a Do Not Use When line names an installed skill by its canonical name")

    def test_handoff_policies_name_installed_siblings_by_label_on_every_hermes_surface(self) -> None:
        # The policy renders in the body's Catalog Metadata and, for a
        # progressive-disclosure skill, in `references/full-contract.md`; both
        # are what the model loads, so both are read.
        checked: dict[str, int] = {"SKILL.md": 0, "references/full-contract.md": 0}
        for name, definition in self.definitions.items():
            surfaces = {"SKILL.md": self.hermes[name], "references/full-contract.md": self.full_contracts.get(name, "")}
            for surface, content in surfaces.items():
                paragraph = _handoff_paragraph(content)
                if paragraph is None:
                    continue
                checked[surface] += 1
                with self.subTest(skill=name, surface=surface):
                    stale = [
                        token
                        for token in _BACKTICKED.findall(paragraph)
                        if token in self.installed and omh_skill_display_name(token) != token
                    ]
                    self.assertEqual(stale, [], "a handoff policy names an installed skill by its canonical name")
                    self.assertEqual(paragraph, loadable_skill_mentions(definition.handoff_policy))
        self.assertTrue(all(checked.values()), checked)

    def test_every_catalog_sibling_renders_under_its_label_in_place(self) -> None:
        translated = 0
        for name, definition in self.definitions.items():
            rendered = self._hermes_boundary(name)
            if not rendered:
                # A bespoke body (`omh-docs`) writes its own boundary prose.
                continue
            self.assertEqual(len(rendered), len(definition.do_not_use_when), name)
            for source, line in zip(definition.do_not_use_when, rendered):
                expected = source
                for token in sorted(set(_BACKTICKED.findall(source)) & self.installed, key=len, reverse=True):
                    expected = expected.replace(f"`{token}`", f"`{omh_skill_display_name(token)}`")
                    translated += 1
                self.assertEqual(line, expected, name)
        self.assertGreater(translated, 0, "no sibling was translated; the check above would be vacuous")

    def test_a_retired_sibling_keeps_its_canonical_name(self) -> None:
        # No label loads a skill that is not installed, so a line naming one
        # keeps what the catalog wrote rather than inventing a directory name.
        retired = frozenset(definition.name for definition in builtin_definitions()) - self.installed
        self.assertIn("performance-goal", retired)
        self.assertEqual(loadable_skill_mentions("use `performance-goal`."), "use `performance-goal`.")

    def test_no_installed_body_hands_a_request_to_a_retired_sibling(self) -> None:
        # A retired skill is not installed, so `skill_view` cannot load it: a
        # Do-Not-Use line or an example that sends a request there is a dead
        # end (`ultraperf` pointed at `performance-goal` after #1691 folded it
        # into `ultraperf` itself).
        retired = frozenset(definition.name for definition in builtin_definitions()) - self.installed
        stale = sorted(
            (name, token)
            for name, definition in self.definitions.items()
            for text in (
                *definition.do_not_use_when,
                *(
                    f"{example.expected} {example.why}"
                    for example in (definition.good_example, definition.bad_example)
                    if example is not None
                ),
            )
            for token in _BACKTICKED.findall(text)
            if token in retired
        )
        self.assertEqual(stale, [], "a body hands a request to a skill that is no longer installed")

    def test_portable_bodies_use_labels_and_drop_bundled_hermes_lines(self) -> None:
        portable = frozenset(portable_skill_names())
        unshipped = frozenset(skill for skill in self.installed if omh_skill_display_name(skill) not in portable)
        unshipped_labels = frozenset(omh_skill_display_name(skill) for skill in unshipped)

        def hands_off_to_unshipped_only(line: str) -> bool:
            named = set(_BACKTICKED.findall(line)) & self.installed
            return bool(named) and named <= unshipped

        checked = stripped = 0
        for name, definition in self.definitions.items():
            if omh_skill_display_name(name) not in portable:
                continue
            content = agent_skill_template(definition).content
            rendered = _do_not_use_section(content)
            # A whole-section portable override replaces the lines; otherwise
            # the portable body keeps every line but a bundled-skill one, with
            # a `PortableLine` in its portable wording.
            own = list(
                definition.portable_overrides.get("do_not_use_when")
                or [
                    line.portable if isinstance(line, PortableLine) else line
                    for line in definition.do_not_use_when
                    if not isinstance(line, HermesSkillLine)
                ]
            )
            self.assertEqual(len(rendered), len(own), name)
            if "do_not_use_when" not in definition.portable_overrides:
                # A line handing its request only to a Hermes-only sibling keeps
                # the request and loses the pointer. A bespoke Hermes body
                # (`omh-docs`) writes its own boundary prose, so only a
                # catalog-rendered one is held to the whole line.
                hermes_boundary = self._hermes_boundary(name)
                for line in filter(hands_off_to_unshipped_only, own):
                    stripped += 1
                    request, _, pointer = line.rpartition("; ")
                    if hermes_boundary:
                        self.assertIn(loadable_skill_mentions(line), hermes_boundary, name)
                    self.assertIn(f"{request}.", rendered, name)
                    self.assertNotIn(loadable_skill_mentions(pointer), content, name)
            for token in (token for line in rendered for token in _BACKTICKED.findall(line)):
                self.assertFalse(
                    token in self.installed and omh_skill_display_name(token) != token,
                    f"{name} names `{token}` canonically in its portable body",
                )
                self.assertNotIn(token, unshipped_labels, f"{name} hands a request to a Hermes-only sibling in its portable body")
            for line in definition.do_not_use_when:
                if isinstance(line, HermesSkillLine):
                    checked += 1
                    self.assertIn(str(line), self._hermes_boundary(name))
                    self.assertNotIn(str(line), content)
                    for skill in line.skills:
                        self.assertNotIn(f"`{skill}`", "\n".join(rendered), name)
            self.assertIsNone(_related_line(content), f"{name}: related_skills is Hermes-only")
        self.assertGreater(checked, 0, "no portable owner carries a bundled line; the check above would be vacuous")
        self.assertGreater(stripped, 0, "no portable owner hands a line to a Hermes-only sibling; the check above would be vacuous")

    def test_related_skills_frontmatter_is_derived_from_the_boundary_lines(self) -> None:
        emitted = 0
        for name, definition in self.definitions.items():
            related = related_skill_names(definition)
            line = _related_line(self.hermes[name])
            if not related:
                self.assertIsNone(line, name)
                continue
            emitted += 1
            self.assertEqual(line, ", ".join(related), name)
            self.assertEqual(len(related), len(set(related)), name)
            self.assertNotIn(omh_skill_display_name(name), related, name)
            labels = {omh_skill_display_name(skill) for skill in self.installed}
            for skill in related:
                self.assertTrue(skill in labels or skill in HERMES_BUNDLED_SKILL_NAMES, f"{name}: {skill}")
        self.assertGreater(emitted, 0)

    def test_related_skills_lists_labels_then_bundled_names(self) -> None:
        self.assertEqual(
            related_skill_names(self.definitions["web-research"]),
            (
                "ulw-research",
                "omh-source-finder",
                "omh-research-brief",
                "omh-research-department",
                "omh-websearch-setup",
                "omh-codebase-onboarding",
                "grounded-citations",
                "arxiv",
            ),
        )
        self.assertIn(
            "    related_skills: [ulw-research, omh-source-finder, omh-research-brief, omh-research-department, "
            "omh-websearch-setup, omh-codebase-onboarding, grounded-citations, arxiv]\n",
            self.hermes["web-research"],
        )


class BundledHermesDeferralTests(unittest.TestCase):
    def test_each_owner_names_each_bundled_counterpart_in_one_line(self) -> None:
        actual: dict[str, tuple[str, ...]] = {}
        for definition in builtin_definitions():
            lines = [line for line in definition.do_not_use_when if isinstance(line, HermesSkillLine)]
            if lines:
                actual[definition.name] = tuple(skill for line in lines for skill in line.skills)
        self.assertEqual(actual, EXPECTED_BUNDLED_DEFERRALS)
        for owner, skills in actual.items():
            self.assertEqual(len(skills), len(set(skills)), owner)

    def test_a_compact_body_carries_its_bundled_boundary(self) -> None:
        # A progressive-disclosure body keeps its Do-Not-Use lines in the full
        # contract, which loads only on demand, while Hermes loads the bundled
        # skill beside the body; the line saying which request is the bundled
        # skill's is read in the body or not at all.
        hermes = {template.name: template.content for template in builtin_skill_templates()}
        checked = 0
        for definition in installable_skill_definitions():
            if not definition.progressive_disclosure:
                continue
            for line in definition.do_not_use_when:
                if isinstance(line, HermesSkillLine):
                    checked += 1
                    self.assertIn(f"**Do Not Use When:** {line}", hermes[definition.name], definition.name)
        self.assertGreater(checked, 0, "no compact body hands a request to a bundled skill; the check is vacuous")

    def test_bundled_names_never_collide_with_a_catalog_name_or_label(self) -> None:
        names = {definition.name for definition in builtin_definitions()}
        labels = {omh_skill_display_name(name) for name in names}
        self.assertEqual(sorted(HERMES_BUNDLED_SKILL_NAMES & (names | labels)), [])

    def test_a_bundled_line_must_name_a_known_skill_in_backticks(self) -> None:
        with self.assertRaisesRegex(ValueError, r"must name bundled Hermes skills, got \['llm-wikis'\]"):
            HermesSkillLine("load Hermes' bundled `llm-wikis` skill instead.", ("llm-wikis",))
        with self.assertRaisesRegex(ValueError, r"must name \['llm-wiki'\] in backticks"):
            HermesSkillLine("load Hermes' bundled llm-wiki skill instead.", ("llm-wiki",))
        with self.assertRaisesRegex(ValueError, "got none"):
            HermesSkillLine("load nothing.", ())

    def test_a_bundled_line_outside_do_not_use_when_is_refused(self) -> None:
        definition = next(d for d in installable_skill_definitions() if d.name == "code-review")
        line = HermesSkillLine("Load Hermes' bundled `github` skill.", ("github",))
        misplaced = replace(definition, recovery_notes=(*definition.recovery_notes, line))
        with self.assertRaisesRegex(
            ValueError, r"code-review: HermesSkillLine is honoured only in do_not_use_when, found in \['recovery_notes'\]"
        ):
            agent_skill_template(misplaced)

    def test_a_definition_with_only_bundled_lines_keeps_the_default_boundary(self) -> None:
        wiki = next(d for d in builtin_definitions() if d.name == "wiki")
        self.assertEqual(
            wiki.do_not_use_when[:2],
            (
                "The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.",
                "The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.",
            ),
        )
        self.assertIsInstance(wiki.do_not_use_when[2], HermesSkillLine)
        self.assertEqual(len(wiki.do_not_use_when), 3)


class ReferencePointerTests(unittest.TestCase):
    def test_no_hermes_body_points_at_a_router_reference_by_a_bare_path(self) -> None:
        # `skill_view` takes a skill name and a path inside it, so a pointer at
        # a reference the router skill owns (the shared rail, the Jev rail,
        # structural search, workflow artifacts) is written as that call.
        # Authored catalog lines that point at a skill's own or a sibling's
        # reference are not rendered through this rule.
        from omh.skills.catalog_types import skill_view_call

        self.assertEqual(
            skill_view_call("omh-routing/references/skill-common-rail.md"),
            "skill_view(name='omh-routing', file_path='references/skill-common-rail.md')",
        )
        hits = sorted(
            template.name for template in builtin_skill_templates() if "omh-routing/references/" in template.content
        )
        self.assertEqual(hits, [])


class FrontmatterProvenanceTests(unittest.TestCase):
    def test_license_and_author_are_the_package_metadata(self) -> None:
        import tomllib
        from pathlib import Path

        from omh.skills.render import SKILL_AUTHOR, SKILL_LICENSE

        project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]
        self.assertEqual(SKILL_LICENSE, project["license"])
        self.assertIn(SKILL_AUTHOR, [author["name"] for author in project["authors"]])

    def test_hermes_bodies_carry_license_and_author_and_portable_bodies_license_only(self) -> None:
        from omh.skills.render import agent_skill_templates

        for template in builtin_skill_templates():
            frontmatter = template.content.split("---", 2)[1]
            self.assertIn("\nlicense: MIT\nauthor: \"oh-my-hermes maintainers\"\n", frontmatter, template.name)
        for template in agent_skill_templates():
            frontmatter = template.content.split("---", 2)[1]
            self.assertIn("\nlicense: MIT\n", frontmatter, template.name)
            self.assertNotIn("\nauthor:", frontmatter, template.name)


if __name__ == "__main__":
    unittest.main()
