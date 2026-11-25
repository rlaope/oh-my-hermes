"""Contract tests for upstream Hermes skill parity and value-mechanism governance."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from _local_package import load_local_package

load_local_package()

from omh.cli import main as cli_main
from omh.quality.reported_rate import reported_rate_shape_errors
from omh.skills.catalog import installable_skill_definitions
from omh.skills.catalog_types import (
    HERMES_BUNDLED_SKILL_NAMES,
    HERMES_FLOOR_BUNDLED_ALIASES,
    HERMES_OPTIONAL_SKILL_NAMES,
    HermesOptionalSkillLine,
    HermesSkillLine,
)
from omh.skills.hermes_parity import (
    HERMES_SKILL_PARITY_SCHEMA_VERSION,
    REQUIRED_BUNDLED_OVERLAP_BOUNDARIES,
    REQUIRED_OPTIONAL_OVERLAP_BOUNDARIES,
    UPSTREAM_MOVED_TO_OPTIONAL,
    hermes_skill_parity_markdown,
    hermes_skill_parity_payload,
)
from omh.skills.render import builtin_skill_templates
from omh.skills.skill_record import skill_records
from omh.skills.value_mechanisms import (
    VALUE_MECHANISM_PROSE_TEMPLATE_REVIEW,
    VALUE_MECHANISMS,
    prose_template_review_skills,
    value_mechanisms_for_skill,
)


class HermesSkillParityTests(unittest.TestCase):
    def test_upstream_inventories_are_disjoint_and_cover_moved_skills(self) -> None:
        self.assertEqual(HERMES_BUNDLED_SKILL_NAMES & HERMES_OPTIONAL_SKILL_NAMES, frozenset())
        self.assertTrue(HERMES_FLOOR_BUNDLED_ALIASES.issubset(HERMES_BUNDLED_SKILL_NAMES))
        self.assertTrue(UPSTREAM_MOVED_TO_OPTIONAL.issubset(HERMES_OPTIONAL_SKILL_NAMES))
        self.assertEqual(UPSTREAM_MOVED_TO_OPTIONAL & HERMES_BUNDLED_SKILL_NAMES, frozenset())

    def test_parity_payload_is_clean_and_uses_reported_rate_v1(self) -> None:
        payload = hermes_skill_parity_payload()
        self.assertEqual(payload["schema_version"], HERMES_SKILL_PARITY_SCHEMA_VERSION)
        self.assertTrue(payload["ok"], payload["findings"])
        self.assertTrue(payload["offline_snapshot_only"])
        self.assertEqual(payload["findings"], [])
        self.assertEqual(
            reported_rate_shape_errors(payload["catalog"]["structured_value_share"]),
            (),
        )
        self.assertEqual(
            reported_rate_shape_errors(payload["upstream_boundaries"]["bundled_overlap_coverage"]),
            (),
        )
        self.assertEqual(payload["upstream_boundaries"]["bundled_overlap_coverage"]["percent"], 100.0)
        self.assertEqual(
            payload["upstream_boundaries"]["bundled_owners"],
            len(REQUIRED_BUNDLED_OVERLAP_BOUNDARIES),
        )
        self.assertEqual(
            payload["upstream_boundaries"]["optional_owners"],
            len(REQUIRED_OPTIONAL_OVERLAP_BOUNDARIES),
        )

    def test_cli_docs_hermes_skill_parity_check_and_json(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = cli_main(["docs", "hermes-skill-parity", "--check", "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["schema_version"], HERMES_SKILL_PARITY_SCHEMA_VERSION)
        self.assertTrue(parsed["ok"])

        markdown = hermes_skill_parity_markdown()
        self.assertIn("# Hermes Skill Parity & Value-Mechanism Audit", markdown)
        self.assertIn("Status: OK (0 finding(s))", markdown)

    def test_every_installable_skill_record_has_valid_value_mechanisms(self) -> None:
        records = {record.name: record for record in skill_records()}
        for definition in installable_skill_definitions():
            with self.subTest(skill=definition.name):
                record = records[definition.name]
                self.assertTrue(record.value_mechanisms)
                for mechanism in record.value_mechanisms:
                    self.assertIn(mechanism, VALUE_MECHANISMS)
                self.assertEqual(
                    record.value_mechanisms,
                    value_mechanisms_for_skill(definition.name, allow_retired=False),
                )

    def test_value_mechanisms_for_unknown_skill_fails_closed(self) -> None:
        with self.assertRaises(KeyError):
            value_mechanisms_for_skill("nonexistent-omh-skill", allow_retired=False)

    def test_prose_template_review_queue_matches_mechanism_table(self) -> None:
        queued = prose_template_review_skills()
        self.assertTrue(queued)
        for name in queued:
            self.assertIn(VALUE_MECHANISM_PROSE_TEMPLATE_REVIEW, value_mechanisms_for_skill(name))

    def test_optional_skill_line_enforces_conditional_phrasing_and_inventory(self) -> None:
        line = HermesOptionalSkillLine("When installed, defer to `llm-wiki` for plain vault maintenance.", ("llm-wiki",))
        self.assertEqual(line.skills, ("llm-wiki",))
        self.assertIsInstance(line, HermesSkillLine)

        with self.assertRaises(ValueError):
            HermesOptionalSkillLine("Defer to `llm-wiki` for plain vault maintenance.", ("llm-wiki",))
        with self.assertRaises(ValueError):
            HermesOptionalSkillLine("When installed, defer to `not-a-known-optional-skill`.", ("not-a-known-optional-skill",))

    def test_skill_health_references_hermes_skill_parity_audit(self) -> None:
        templates = {template.name: template.content for template in builtin_skill_templates()}
        self.assertIn("omh docs hermes-skill-parity --json", templates["skill-health"])


if __name__ == "__main__":
    unittest.main()
