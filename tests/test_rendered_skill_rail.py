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

from omh.plugin_bundle.omh.awareness import awareness_primer_markdown, awareness_shared_context_markdown
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
from omh.workflows.self_improvement_store_contract import SELF_IMPROVEMENT_DESTINATION_DETAILS

_BACKTICKED = re.compile(r"`([a-z0-9][a-z0-9-]*)`")
_INLINE_CODE = re.compile(r"`[^`]*`")
_DESCRIPTION_TRIGGERS = "Use when the user says:"
# One-word installed names a rendered file writes on purpose: a CLI verb, a tool
# or config field, a board operation or a category, each read in its own line.
# Anything else in backticks is a hand-off and must be a label: write the label in
# the producer, or a hand-off word the rewrite can see. Add a row here only for a
# word that is not a skill in that line.
_ONE_WORD_NON_HANDOFFS = frozenset(
    {
        ("agent-board", "references/board-prepare.md", "context"),
        ("agent-board", "references/board-prepare.md", "research"),
        ("dag-ulw", "SKILL.md", "backend"),
        ("dag-ulw", "references/run-loop.md", "backend"),
        ("frontend", "references/forms-and-input.md", "cancel"),
        ("geospatial-analysis", "references/procedure.md", "backend"),
        ("iac-change", "references/iac-change-method.md", "plan"),
        ("long-document-reading", "SKILL.md", "context"),
        ("maestro", "references/executor-prompt-composition.md", "research"),
        ("research", "references/evidence-records.md", "plan"),
        ("show-reel", "references/craft-audio.md", "plan"),
        ("ultrawork", "references/team-lane.md", "context"),
        ("websearch-setup", "SKILL.md", "backend"),
    }
)
# A path qualified by its owner (`ulw-work`'s `references/tdd-red-green.md`) is a pointer into a sibling.
_REFERENCE_PATH = re.compile(r"(?<!'s )`(references/[A-Za-z0-9_./-]+)`")


def _reader_text(path: str, content: str) -> list[str]:
    """What a model reads as prose: no inline code, no frontmatter beyond the description's own sentence."""
    lines = _prose_lines(content)
    if path == "SKILL.md" and content.startswith("---\n"):
        end = lines.index("---", 1)
        description = [
            line.split(_DESCRIPTION_TRIGGERS, 1)[0].replace("oh-my-hermes", "")
            for line in lines[1:end]
            if line.startswith("description:")
        ]
        lines = description + lines[end + 1 :]
    return [_INLINE_CODE.sub("``", line) for line in lines]


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

    def _texts(self):
        for projection, bodies, refs in self._projections():
            for name, content in bodies.items():
                yield projection, self._owner(name), "SKILL.md", content
            for owner, path, content in refs:
                yield projection, self._owner(owner), path, content

    def _router_registry(self, owner: str, path: str) -> bool:
        return owner == "oh-my-hermes" and (path == "SKILL.md" or path in _ROUTER_CANONICAL_REFERENCES)

    def test_a_plain_hyphenated_sibling_is_a_loadable_label(self) -> None:
        names = sorted(
            (name for name in self.installed if "-" in name and omh_skill_display_name(name) != name),
            key=len,
            reverse=True,
        )
        plain = re.compile(r"(?<![\w./$:'`-])(" + "|".join(map(re.escape, names)) + r")(?![\w/`-])")
        stale = set()
        for projection, owner, path, content in self._texts():
            if self._router_registry(owner, path):
                continue
            for line in _reader_text(path, content):
                stale.update(
                    (projection, owner, path, match.group(1))
                    for match in plain.finditer(line)
                    if match.group(1) != owner
                )
        self.assertEqual(sorted(stale), [], "backtick it in the producer so the rewrite gives it its label")

    def test_a_plain_one_word_hand_off_is_a_loadable_label(self) -> None:
        words = "|".join(
            sorted(name for name in self.installed if "-" not in name and omh_skill_display_name(name) != name)
        )
        hand_off = re.compile(
            r"\b(?:route|routes|routed|send|sends|hand|hands|handed)\b[^.;:`]{0,60}?\bto\s+(" + words + r")\b"
            r"|\buse\s+(" + words + r")\b(?=[,.;]|\s+(?:or|and|before|for|instead)\b)",
            re.IGNORECASE,
        )
        stale = set()
        for projection, owner, path, content in self._texts():
            if self._router_registry(owner, path):
                continue
            for line in _reader_text(path, content):
                for match in hand_off.finditer(line):
                    word = (match.group(1) or match.group(2)).lower()
                    if word != owner:
                        stale.add((projection, owner, path, word))
        self.assertEqual(sorted(stale), [], "backtick it in the producer so the rewrite gives it its label")

    def test_a_backticked_one_word_sibling_is_a_label_unless_read_as_another_word(self) -> None:
        words = {name for name in self.installed if "-" not in name and omh_skill_display_name(name) != name}
        found = set()
        for _projection, owner, path, content in self._texts():
            if self._router_registry(owner, path):
                continue
            for line in _prose_lines(content):
                found.update(
                    (owner, path, token) for token in _BACKTICKED.findall(line) if token in words and token != owner
                )
        self.assertEqual(
            sorted(found - _ONE_WORD_NON_HANDOFFS),
            [],
            "a one-word sibling left canonical: write its label in the producer, or list it if it is not a skill here",
        )
        self.assertEqual(sorted(_ONE_WORD_NON_HANDOFFS - found), [], "a listed word is gone: drop its row")

    def test_every_backticked_label_shaped_name_is_an_installed_label(self) -> None:
        # A label written by hand skips the rewrite, so nothing else checks that it exists.
        # wrapper-routing.md names two earlier label eras that routing still accepts.
        historical = {("oh-my-hermes", "references/wrapper-routing.md", name) for name in ("omh-ultrawork", "ulw-ultrawork")}
        labels = {omh_skill_display_name(name) for name in self.installed}
        shaped = re.compile(r"`((?:omh|ulw|dag)-[a-z0-9]+(?:-[a-z0-9]+)*)`")
        unknown = set()
        for projection, owner, path, content in self._texts():
            for line in _prose_lines(content):
                unknown.update(
                    (projection, owner, path, name)
                    for name in shaped.findall(line)
                    if name not in labels and (owner, path, name) not in historical
                )
        self.assertEqual(sorted(unknown), [], "a hand-written label that no installed skill carries")

    def test_the_rail_checkpoint_names_no_sibling_canonically(self) -> None:
        rail = next(
            r.content
            for r in self.hermes_refs
            if r.skill_name == "oh-my-hermes" and r.relative_path == "references/skill-common-rail.md"
        )
        line = next(row for row in rail.split("\n") if row.startswith("- Generic-tool checkpoint:"))
        targets = re.findall(r"(?:(?<=->)|(?<=/))[a-z0-9-]+", line)
        self.assertIn("omh-image-cards", targets)
        self.assertIn("ulw-work", targets)
        self.assertEqual(
            [t for t in targets if t in self.installed and omh_skill_display_name(t) != t], []
        )

    def test_every_arrow_target_the_model_reads_is_a_loadable_label(self) -> None:
        """The per-turn primer carries its arrow lines as the bundle writes them, with no render pass."""
        labels = {omh_skill_display_name(name) for name in self.installed}
        primer = awareness_primer_markdown().split("\n")
        lines = {
            f"primer {header}": primer[primer.index(header) + 1]
            for header in ("Workflow context cards:", "Common cues before generic tools:", "Generic tool map:")
        }
        lines["shared rail"] = next(
            row for row in awareness_shared_context_markdown().split("\n") if row.startswith("- Generic-tool checkpoint:")
        )
        # The rail page ships only in the Hermes projection.
        rail = next(
            r.content
            for r in self.hermes_refs
            if r.skill_name == "oh-my-hermes" and r.relative_path == "references/skill-common-rail.md"
        )
        lines["rail page"] = next(row for row in rail.split("\n") if row.startswith("- Generic-tool checkpoint:"))
        for surface, line in lines.items():
            with self.subTest(surface=surface):
                # Each `;` part maps a cue to its skills after `->`, listed with `/`, `,` or `or`.
                targets = [
                    target.strip().rstrip(".")
                    for part in line.split(";")
                    for target in re.split(r"/|,|\bor\b", part.split("->", 1)[1])
                    if target.strip().rstrip(".")
                ]
                self.assertIn("omh-frontend", targets)
                self.assertEqual([t for t in targets if t not in labels], [])

    def test_every_lane_key_the_primer_names_is_a_loadable_label(self) -> None:
        """A lane's `Key:` names reach the model through the per-turn primer with no render pass."""
        labels = {omh_skill_display_name(name) for name in self.installed}
        keys = [line for line in awareness_primer_markdown().split("\n") if ". Key: `" in line]
        self.assertTrue(keys)
        for line in keys:
            with self.subTest(line=line[:40]):
                names = re.findall(r"`([^`]+)`", line.split(". Key: ", 1)[1])
                self.assertTrue(names)
                self.assertEqual([name for name in names if name not in labels], [])

    def test_the_lane_line_keeps_its_title_and_names_no_siblings(self) -> None:
        for name, content in self.hermes.items():
            for line in content.split("\n"):
                if line.startswith("- Current lane:"):
                    with self.subTest(skill=name):
                        self.assertNotIn("`", line)
                        self.assertRegex(line, r"^- Current lane: \*\*[^*]+\*\*")

    def test_script_paths_in_toolkit_skill_references_resolve_from_the_skill_folder(self) -> None:
        for owner in ("show-reel", "sprite-forge"):
            for reference in (r for r in self.hermes_refs if self._owner(r.skill_name) == owner):
                with self.subTest(skill=owner, path=reference.relative_path):
                    self.assertNotRegex(reference.content, r"(?m)\b(?:python3?|node|bash) scripts/")
                    self.assertNotIn("`scripts/narrate.py`", reference.content)
                    if "$S/" in reference.content:
                        self.assertIn("S=<skill_dir>/toolkit/scripts", reference.content)

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


class CrossLaneHandOffTests(unittest.TestCase):
    """A skill's claim about a sibling, read against that sibling."""

    def setUp(self) -> None:
        self.bodies = {t.name: t.content for t in builtin_skill_templates()}
        self.refs = {(r.skill_name, r.relative_path): r.content for r in builtin_skill_reference_templates()}

    def test_an_accepted_plan_leaves_the_leadership_loop_for_execution(self) -> None:
        do_not_use = self.bodies["cto-loop"].split("## Do Not Use When", 1)[1].split("\n## ", 1)[0]
        line = next(row for row in do_not_use.split("\n") if "accepted plan" in row)
        self.assertIn("`ulw-work`", line)
        self.assertNotIn("`ulw-plan`", line)

    def test_rejected_decision_records_are_not_the_recall_corpus(self) -> None:
        recall = self.bodies["decision-recall"]
        self.assertIn("omh memory rejected-recall", recall)
        self.assertIn("rejected a staged candidate", recall)
        for text in (self.bodies["strategy-brief"], self.refs[("strategy-brief", "references/decision-records.md")]):
            self.assertIn("decision log", text)
            self.assertIn("memory candidates a person rejected", text)
            self.assertNotIn("corpus", text.split("**Rejected**")[-1].split("\n\n")[0])
            self.assertNotIn("reads later", text)

    def test_every_tool_choice_for_a_plan_todo_keeps_an_accepted_plan_in_omh_todo(self) -> None:
        for name in ("dag-ulw", "ultrawork"):
            with self.subTest(skill=name):
                self.assertIn("an accepted plan stays in `omh_todo`", self.bodies[name])

    def test_a_promoted_instinct_uses_the_artifact_its_receiver_declares(self) -> None:
        self.assertIn("`memory_new_candidate/v1` for `omh-memory-new`", self.bodies["instinct-ledger"])
        self.assertIn("memory_new_candidate/v1", self.bodies["memory-new"])

    def test_durable_facts_go_to_the_memory_skills(self) -> None:
        self.assertIn("use `omh-memory-new`, or `omh-memory-sync` to curate", self.bodies["rules-distill"])

    def test_route_signal_destinations_the_store_can_return_are_listed(self) -> None:
        line = next(row for row in self.bodies["workflow-learning"].split("\n") if "omh learning route-signal" in row)
        for name in SELF_IMPROVEMENT_DESTINATION_DETAILS:
            with self.subTest(destination=name):
                word = name.removesuffix("_candidate").replace("_", "-").split("-")[0]
                self.assertTrue(name in line or word in line, name)
        self.assertIn("`manual_review_candidate`", line)
        self.assertIn("`discard_transient`", line)

    def test_portable_readers_are_told_where_the_hermes_tools_live(self) -> None:
        portable = {t.name: t.content for t in agent_skill_templates()}
        for name in ("omh-verification-gate", "omh-code-review"):
            self.assertIn("On Hermes, for native `omh_todo` checkpoints", portable[name])
        self.assertIn("If `omh memory capture` is unavailable or fails", portable["omh-memory-new"])


class RenderedReferenceShapeTests(unittest.TestCase):
    def test_no_reference_ends_in_a_literal_escape(self):
        from omh.skills.render import _router_human_voice_reference

        self.assertFalse(_router_human_voice_reference().endswith("\\n"))

    def test_rendered_harness_registry_never_stacks_dots(self):
        registry = next(
            t.content
            for t in builtin_skill_reference_templates()
            if t.skill_name == "oh-my-hermes" and t.relative_path == "references/harness-registry.md"
        )
        self.assertNotIn("....", registry)
        self.assertNotIn("..:", registry)


if __name__ == "__main__":
    unittest.main()
