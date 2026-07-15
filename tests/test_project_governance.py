from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding.project_governance import (
    discover_project_governance,
    governance_handoff_attachment,
    validate_project_governance_blocked,
    validate_project_governance_profile,
)
from omh.coding.coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from omh.runtime.records import validate_coding_delegation_record


class ProjectGovernanceTests(unittest.TestCase):
    def test_existing_sources_create_safe_prepared_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Run tests and lint. Require review.", encoding="utf-8")
            (root / ".github").mkdir()
            (root / ".github" / "pull_request_template.md").write_text("Test plan", encoding="utf-8")

            discovery = discover_project_governance(root)

        self.assertEqual(discovery["status"], "existing_project_governance")
        profile = governance_handoff_attachment(discovery)["project_governance_profile"]
        self.assertEqual(validate_project_governance_profile(profile), [])
        encoded = json.dumps(discovery)
        self.assertNotIn(str(root), encoded)
        self.assertNotIn("Run tests", encoded)

    def test_empty_project_requires_explicit_default_decision(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = discover_project_governance(root)
            accepted = discover_project_governance(root, decision="accept")
            declined = discover_project_governance(root, decision="decline")

        self.assertEqual(pending["status"], "pending_user_decision")
        self.assertEqual(governance_handoff_attachment(pending), {})
        self.assertEqual(accepted["status"], "accepted_advisory_defaults")
        self.assertIn("project_governance_profile", governance_handoff_attachment(accepted))
        self.assertEqual(declined["status"], "declined_advisory_defaults")
        self.assertEqual(governance_handoff_attachment(declined), {})

    def test_same_source_polarity_conflict_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Run tests but skip tests here.", encoding="utf-8")
            discovery = discover_project_governance(root)

        self.assertEqual(discovery["status"], "blocked")
        marker = governance_handoff_attachment(discovery)["project_governance_blocked"]
        self.assertEqual(validate_project_governance_blocked(marker), [])

    def test_prepared_handoff_carries_existing_governance_and_family(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Run tests.", encoding="utf-8")
            payload = build_coding_delegation_payload(
                "implement src/example.py tests",
                executor_target="codex",
                project_root=root,
                product_family="web",
            )
            record = coding_delegation_record_payload(payload, "implement src/example.py tests")
            record["updated_at"] = "2026-07-15T00:00:00Z"

        handoff = payload["executor_handoff"]
        self.assertIn("project_governance_profile", handoff)
        self.assertIn("product_family_template", handoff)
        self.assertIn("project_governance_profile", record["executor_handoff"])
        self.assertIn("product_family_template", record["executor_handoff"])
        self.assertEqual(validate_coding_delegation_record(record), [])

    def test_nested_symlink_candidate_is_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            external = root / "external"
            project.mkdir()
            external.mkdir()
            (external / "pull_request_template.md").write_text("Run tests.", encoding="utf-8")
            (project / ".github").symlink_to(external, target_is_directory=True)

            discovery = discover_project_governance(project)

        self.assertEqual(discovery["status"], "blocked")
        self.assertEqual(discovery["conflict_codes"], ["unsafe_source"])

    def test_same_category_expectations_keep_all_source_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Run tests.", encoding="utf-8")
            (root / "CLAUDE.md").write_text("Run lint.", encoding="utf-8")
            discovery = discover_project_governance(root)

        expectations = {item["id"]: item for item in discovery["expectations"]}
        self.assertEqual(expectations["tests_required"]["source_paths"], ["AGENTS.md"])
        self.assertEqual(expectations["lint_required"]["source_paths"], ["CLAUDE.md"])

    def test_same_policy_from_two_instruction_sources_keeps_both_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Run tests.", encoding="utf-8")
            (root / "CLAUDE.md").write_text("Run tests.", encoding="utf-8")
            discovery = discover_project_governance(root)

        expectation = next(item for item in discovery["expectations"] if item["id"] == "tests_required")
        self.assertEqual(expectation["source_paths"], ["AGENTS.md", "CLAUDE.md"])

    def test_compacted_handoffs_keep_governance_and_family(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Run tests.", encoding="utf-8")
            for executor, handoff_key in (("codex", "executor_handoff"), ("claude-code", "prompt_handoff"), ("omx-runtime", "runtime_handoff")):
                with self.subTest(executor=executor):
                    payload = build_coding_delegation_payload(
                        "implement src/example.py tests",
                        executor_target=executor,
                        project_root=root,
                        product_family="web",
                    )
                    record = coding_delegation_record_payload(payload, "implement src/example.py tests")
                    record["updated_at"] = "2026-07-15T00:00:00Z"

                    self.assertIn("project_governance_profile", record[handoff_key])
                    self.assertIn("product_family_template", record[handoff_key])
                    self.assertEqual(validate_coding_delegation_record(record), [])

    def test_github_template_directory_and_workflow_are_discovered(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_dir = root / ".github" / "PULL_REQUEST_TEMPLATE"
            workflow_dir = root / ".github" / "workflows"
            template_dir.mkdir(parents=True)
            workflow_dir.mkdir(parents=True)
            (template_dir / "bug.md").write_text("Run tests.", encoding="utf-8")
            (workflow_dir / "test.yml").write_text("test", encoding="utf-8")
            discovery = discover_project_governance(root)

        self.assertEqual(discovery["status"], "existing_project_governance")
        self.assertEqual({item["category"] for item in discovery["sources"]}, {"pr", "ci"})

    def test_case_variant_pr_template_candidates_are_deduplicated(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            github = root / ".github"
            github.mkdir()
            (github / "pull_request_template.md").write_text("Run tests.", encoding="utf-8")
            discovery = discover_project_governance(root)

        sources = [item for item in discovery["sources"] if item["category"] == "pr"]
        self.assertEqual(len(sources), 1)

    def test_negative_governance_rule_is_not_an_unsafe_source(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Skip tests.", encoding="utf-8")
            discovery = discover_project_governance(root)

        self.assertEqual(discovery["status"], "existing_project_governance")

    def test_sensitive_governance_source_is_blocked_before_attachment(self) -> None:
        for content in ("AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE", "secret=topsecret", "-----BEGIN PRIVATE KEY-----"):
            with self.subTest(content=content), TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "AGENTS.md").write_text(content, encoding="utf-8")
                discovery = discover_project_governance(root)

                self.assertEqual(discovery["status"], "blocked")
                self.assertEqual(governance_handoff_attachment(discovery).keys(), {"project_governance_blocked"})
