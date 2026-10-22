"""`SkillRecord` is a reading of the catalog tables; the generated tree is the golden.

Every projection is compared against the checked-in bytes it claims to be a
slice of, so a record that reads a table wrongly fails here before any
generator is moved onto it.
"""
from __future__ import annotations

from collections import Counter
from functools import partial
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _tree(root: Path) -> dict[str, str]:
    from omh.skills.catalog import omh_skill_display_name
    from omh.skills.support_files import builtin_support_owners
    files = [*root.glob("*/SKILL.md"), *root.glob("*/references/*.md"),
             *[p for owner in builtin_support_owners() for p in root.glob(f"{omh_skill_display_name(owner)}/toolkit/**/*") if p.is_file()]]
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in files}


class SkillRecordTests(unittest.TestCase):
    def test_every_builtin_definition_has_a_record_in_catalog_order(self) -> None:
        from omh.skills.catalog import builtin_definitions
        from omh.skills.skill_record import skill_record, skill_records

        names = [definition.name for definition in builtin_definitions()]
        self.assertEqual([record.name for record in skill_records()], names)
        for record in skill_records():
            self.assertIs(skill_record(record.name), record)
        with self.assertRaises(KeyError):
            skill_record("not-a-skill")

    def test_record_policy_is_the_routers_effective_policy(self) -> None:
        from omh.routing.recommend import _policy_for
        from omh.skills.skill_record import skill_records

        for record in skill_records():
            with self.subTest(name=record.name):
                self.assertIs(record.policy, _policy_for(record.definition))

    def test_policy_source_counts(self) -> None:
        from omh.skills.skill_record import skill_records

        # Catalog facts, not targets: these move when a skill gains or loses a
        # `_SKILL_POLICIES` entry or changes category/role. Re-measure then.
        counts = Counter(record.policy_source for record in skill_records())
        # spend-gate adds a `_SKILL_POLICIES` entry (+1 skill). dag-ulw takes its role's policy (+1 role).
        # market-research adds a `_SKILL_POLICIES` entry (+1 skill). show-reel adds one (+1 skill).
        # Three optional science methods each declare a curated policy.
        # Repro-audit adds its own curated policy; remeasured from skill_records.
        self.assertEqual(counts, Counter({"skill": 123, "category": 27, "role": 9}))
        self.assertEqual(counts["default"], 0)

    def test_next_action_label_is_the_action_copy_label(self) -> None:
        from omh.routing.action_copy import NEXT_ACTION_LABELS
        from omh.skills.skill_record import skill_records

        for record in skill_records():
            with self.subTest(name=record.name):
                self.assertTrue(record.next_action_label)
                self.assertEqual(record.next_action_label, NEXT_ACTION_LABELS[record.policy.next_action])

    def test_bespoke_skills_resolve_to_their_own_renderer(self) -> None:
        from omh.skills import render
        from omh.skills.skill_record import skill_records

        bespoke = {
            "oh-my-hermes": render.router_skill,
            "context": render.context_skill,
            "deep-interview": render.deep_interview_skill,
            "product-docs": render.docs_skill,
            "jit-learn": render.jit_learn_skill,
            "loop": render.loop_skill,
            "long-document-reading": render.long_document_reading_skill,
            "memory-new": render.memory_new_skill,
            "memory-sync": render.memory_sync_skill,
            "wiki": render.wiki_skill,
            "buzz": render.buzz_skill,
            "ultrawork": render.ultrawork_skill,
        }
        structural = {"codebase-onboarding", "codegraph-refresh"}
        for record in skill_records():
            with self.subTest(name=record.name):
                if record.name in bespoke:
                    self.assertIs(record.body, bespoke[record.name])
                elif record.name in structural:
                    self.assertIs(record.body.func, render.structural_search_skill)
                    self.assertEqual(record.body.args, (record.name,))
                else:
                    self.assertIsInstance(record.body, partial)
                    self.assertIs(record.body.func, render.workflow_skill)
                    self.assertEqual(record.body.args, (record.name,))

    def test_records_reproduce_the_installed_templates(self) -> None:
        from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
        from omh.skills.skill_record import skill_record, skill_records

        for template in builtin_skill_templates():
            with self.subTest(name=template.name):
                self.assertEqual(skill_record(template.name).body(), template)
        installed = sorted(
            (template.skill_name, template.relative_path, template.content)
            for template in builtin_skill_reference_templates()
        )
        from_records = sorted(
            (template.skill_name, template.relative_path, template.content)
            for record in skill_records()
            for template in record.references()
        )
        self.assertEqual(from_records, installed)

    def test_hermes_projection_is_the_checked_in_skills_tree(self) -> None:
        self._assert_union_is_tree("hermes", ROOT / "skills")

    def test_agent_skills_projection_is_the_checked_in_tree(self) -> None:
        self._assert_union_is_tree("agent-skills", ROOT / "agent-skills")

    def _assert_union_is_tree(self, target: str, root: Path) -> None:
        from omh.skills.skill_record import project, skill_records

        projected: dict[str, str] = {}
        for record in skill_records():
            files = project(record, target)
            self.assertFalse(set(files) & set(projected), record.name)
            projected.update(files)
        tree = _tree(root)
        self.assertEqual(sorted(projected), sorted(tree))
        for path, content in projected.items():
            with self.subTest(path=path):
                self.assertEqual(content, tree[path])

    def test_workflows_doc_is_the_concatenated_skill_sections(self) -> None:
        from omh.skills.skill_record import project, skill_records

        doc = (ROOT / "docs/WORKFLOWS.md").read_text(encoding="utf-8")
        sections = [project(record, "workflows-doc").get("docs/WORKFLOWS.md") for record in skill_records()]
        self.assertNotIn(None, sections)
        region = doc.split("\n## Skills\n\n", 1)[1].split("\n## Representative Harnesses\n", 1)[0]
        self.assertEqual("\n".join(sections), region)

    def test_roles_doc_sections_appear_verbatim(self) -> None:
        from omh.skills.skill_record import project, skill_records

        doc = (ROOT / "docs/ROLES.md").read_text(encoding="utf-8")
        projected = 0
        for record in skill_records():
            section = project(record, "roles-doc").get("docs/ROLES.md")
            if section is None:
                continue
            projected += 1
            with self.subTest(name=record.name):
                self.assertIn(section, doc)
                self.assertIn(f"`{record.name}`", section)
        self.assertGreater(projected, 0)

    def test_shortlist_entries_appear_verbatim_in_the_sidecar(self) -> None:
        from omh.skills.skill_record import project, skill_records

        path = "src/plugin_bundle/omh/tools/skill_shortlist.json"
        raw = (ROOT / path).read_text(encoding="utf-8")
        entries = {entry["name"]: entry for entry in json.loads(raw)["skills"]}
        projected = set()
        for record in skill_records():
            text = project(record, "shortlist").get(path)
            if text is None:
                continue
            projected.add(record.name)
            with self.subTest(name=record.name):
                self.assertIn(text, raw)
                self.assertEqual(json.loads(text), entries[record.name])
        self.assertEqual(projected, set(entries))

    def test_capability_family_slice_is_the_families_listing_the_skill(self) -> None:
        from omh.skills.skill_record import project, skill_records

        path = "src/plugin_bundle/omh/tools/capability_families.json"
        families = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for record in skill_records():
            expected = [family for family in families if record.name in family["primary_workflows"]]
            text = project(record, "capability-family").get(path)
            with self.subTest(name=record.name):
                self.assertEqual(json.loads(text) if text else [], expected)


if __name__ == "__main__":
    unittest.main()
