from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from omh.skills.catalog import builtin_definitions


class QualityEvidenceCliTests(unittest.TestCase):
    def test_prepare_rejects_empty_inline_when_file_is_also_given(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenarios.json"
            path.write_text("[]", encoding="utf-8")
            status, _, stderr = run_cli([
                "--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(Path(tmp) / ".hermes"),
                "quality-evidence", "prepare", "--repository", "r", "--commit", "c", "--tree", "t",
                "--title", "gate", "--executor", "executor", "--scenarios-json", "", "--scenarios-file", str(path),
            ])
        self.assertNotEqual(status, 0)
        self.assertIn("either inline JSON or a file", stderr)
    def test_prepare_prints_prepared_boundary_from_inline_requirements(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(Path(tmp) / ".hermes"),
                    "quality-evidence", "prepare", "--repository", "local/omh", "--commit", "abc",
                    "--tree", "tree", "--title", "quality gate", "--executor", "claude-code",
                    "--scenarios", '[{"id":"qa-1","name":"smoke"}]',
                    "--reviews", '[{"id":"review-1","kind":"review"}]',
                    "--claims", '[{"id":"claim-1","statement":"safe"}]',
                ]
            )
        self.assertEqual(status, 0, stderr)
        package = json.loads(stdout)
        self.assertEqual(package["status"], "prepared_not_observed")
        self.assertEqual(package["subject"]["source"]["commit_sha"], "abc")
        self.assertIn("not observed QA", package["claim_boundary"])

    def test_prepare_accepts_self_critique_and_assigns_deterministic_requirement_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli([
                "--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(Path(tmp) / ".hermes"),
                "quality-evidence", "prepare", "--repository", "r", "--commit", "c", "--tree", "t",
                "--title", "gate", "--executor", "executor", "--scenarios", "[{\"name\":\"smoke\"}]",
                "--self-critique", "[\"What is unobserved?\"]",
            ])
        self.assertEqual(status, 0, stderr)
        package = json.loads(stdout)
        self.assertEqual(package["qa_scenarios"][0]["id"], "scenario-1")
        self.assertEqual(package["self_critique_questions"], ["What is unobserved?"])

    def test_assess_keeps_missing_observations_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package.json"
            package.write_text(json.dumps({
                "schema_version": "quality_evidence_package/v1", "status": "prepared_not_observed",
                "subject": {"title": "gate", "executor_target": "codex", "source": {"repository_id": "r", "commit_sha": "c", "tree_sha": "t"}},
                "qa_scenarios": [{"id": "qa-1"}], "review_requirements": [{"id": "review-1"}],
                "claim_requirements": [{"id": "claim-1"}], "self_critique_questions": [],
                "claim_boundary": "Prepared requirements are not observed execution evidence.",
            }), encoding="utf-8")
            status, stdout, stderr = run_cli([
                "quality-evidence", "assess", "--package", str(package), "--observations", "[]",
            ])
        self.assertEqual(status, 0, stderr)
        assessment = json.loads(stdout)
        self.assertFalse(assessment["ready_for_completion"])
        self.assertEqual(assessment["dimensions"]["scenario_coverage"]["status"], "unknown")
        self.assertIn("does not prove external execution", assessment["claim_boundary"])

    def test_catalog_quality_evidence_loop_preserves_boundary(self) -> None:
        definition = next(item for item in builtin_definitions() if item.name == "quality-evidence-loop")
        text = " ".join((*definition.safety_rules, *definition.quality_bar, *definition.final_checklist))
        self.assertIn("preparation as test execution", text)
        self.assertIn("independent review", text)
        self.assertIn("never dispatch", text)
