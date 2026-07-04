from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload
from omh.hermes_harness import build_hermes_coding_harness, validate_hermes_coding_harness


class HermesCodingHarnessTests(unittest.TestCase):
    def test_hermes_runtime_handoff_includes_read_only_harness_projection(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor, test it, update docs, and prepare a PR",
            executor_target="hermes",
        )["runtime_handoff"]
        harness = handoff["hermes_coding_harness"]

        self.assertEqual(validate_hermes_coding_harness(harness), [])
        self.assertEqual(harness["schema_version"], "hermes_coding_harness/v1")
        self.assertEqual(harness["status"], "prepared_not_observed")
        self.assertEqual(harness["selected_owner"], "hermes")
        self.assertEqual(harness["start_mode"], "solo")
        self.assertIn("read-only projection", harness["claim_boundary"])
        self.assertEqual(
            [stage["id"] for stage in harness["workflow_graph"]],
            ["intake", "scope", "plan", "workspace", "build", "verify", "review", "docs_sync", "pr_prep", "handover"],
        )
        self.assertEqual(
            [lane["id"] for lane in harness["lanes"]],
            ["builder_lane", "verifier_lane", "reviewer_lane", "docs_lane", "pr_lane"],
        )
        self.assertIn("runtime_observation:verification", harness["verification_matrix"]["missing_evidence"])
        self.assertIn("GitHub PR creation", harness["pr_preparation"]["not_observed"])
        self.assertIn("github_pr_created", harness["pr_preparation"]["missing_evidence"])
        self.assertTrue(any("Verification evidence is still missing" in line for line in harness["safe_status_lines"]))

    def test_observed_runtime_events_upgrade_only_matching_stages_and_lanes(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            start_mode="team",
            runtime_observation={
                "observed_events": ["runtime_start", "worker_dispatch", "worker_result", "verification"],
                "blocked_events": [],
                "failed_events": [],
                "latest": {
                    "worker_dispatch": {"worker_ref": "hermes-builder-1", "worktree_ref": "wt-1"},
                    "worker_result": {"worker_ref": "hermes-builder-1", "worktree_ref": "wt-1"},
                    "verification": {"worker_ref": "hermes-verifier-1", "worktree_ref": "wt-1"},
                },
            },
        )

        self.assertEqual(validate_hermes_coding_harness(harness), [])
        self.assertEqual(harness["status"], "in_progress")
        self.assertEqual(harness["start_mode"], "team")
        stage_states = {stage["id"]: stage["state"] for stage in harness["workflow_graph"]}
        self.assertEqual(stage_states["build"], "observed")
        self.assertEqual(stage_states["verify"], "observed")
        self.assertEqual(stage_states["review"], "pending")
        lanes = {lane["id"]: lane for lane in harness["lanes"]}
        self.assertEqual(lanes["builder_lane"]["state"], "observed")
        self.assertEqual(lanes["builder_lane"]["worker_ref"], "hermes-builder-1")
        self.assertTrue(lanes["builder_lane"]["worker_ref_required"])
        self.assertFalse(lanes["builder_lane"]["evidence_gap"])
        self.assertEqual(lanes["reviewer_lane"]["state"], "pending")
        self.assertIn("github_pr_created", harness["pr_preparation"]["missing_evidence"])

    def test_docs_sync_gap_is_not_cleared_by_review_evidence(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]
        handoff["acceptance_criteria"] = [*handoff["acceptance_criteria"], "Update README and generated docs."]

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            runtime_observation={
                "observed_events": ["review"],
                "blocked_events": [],
                "failed_events": [],
                "latest": {"review": {"summary": "review observed"}},
            },
        )

        self.assertEqual(harness["docs_sync"]["status"], "prepared_not_observed")
        self.assertEqual(harness["docs_sync"]["missing_evidence"], ["docs_sync_evidence_ref"])
        self.assertIn("does not prove files were edited", harness["docs_sync"]["claim_boundary"])

    def test_merge_observation_alone_does_not_complete_the_harness(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            runtime_observation={
                "observed_events": ["merge"],
                "blocked_events": [],
                "failed_events": [],
                "latest": {"merge": {"summary": "merge observed without upstream evidence"}},
            },
        )

        self.assertEqual(harness["status"], "in_progress")
        self.assertIn("runtime_observation:verification", harness["verification_matrix"]["missing_evidence"])
        self.assertIn("github_pr_created", harness["pr_preparation"]["missing_evidence"])
        self.assertIn("runtime_observation:merge_readiness", harness["pr_preparation"]["missing_evidence"])

    def test_merge_readiness_does_not_clear_github_pr_creation_gap(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            runtime_observation={
                "observed_events": ["merge_readiness"],
                "blocked_events": [],
                "failed_events": [],
                "latest": {"merge_readiness": {"summary": "PR package ready"}},
            },
        )

        self.assertNotIn("runtime_observation:merge_readiness", harness["pr_preparation"]["missing_evidence"])
        self.assertIn("github_pr_created", harness["pr_preparation"]["missing_evidence"])
        self.assertNotIn("merge readiness", harness["pr_preparation"]["not_observed"])
        self.assertIn("GitHub PR creation", harness["pr_preparation"]["not_observed"])

    def test_full_runtime_ladder_still_waits_for_docs_and_pr_creation_gaps(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor and update docs",
            executor_target="hermes",
        )["runtime_handoff"]
        handoff["acceptance_criteria"] = [*handoff["acceptance_criteria"], "Update README and generated docs."]
        all_events = [
            "runtime_start",
            "worktree_creation",
            "worker_dispatch",
            "worker_result",
            "verification",
            "review",
            "ci",
            "merge_readiness",
            "merge",
        ]

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            runtime_observation={
                "observed_events": all_events,
                "blocked_events": [],
                "failed_events": [],
                "unsatisfied_events": [],
                "latest": {event: {"summary": f"{event} observed"} for event in all_events},
            },
        )

        self.assertEqual(harness["status"], "in_progress")
        self.assertEqual(harness["docs_sync"]["missing_evidence"], ["docs_sync_evidence_ref"])
        self.assertEqual(harness["pr_preparation"]["missing_evidence"], ["github_pr_created"])
        self.assertNotIn("review passed", harness["pr_preparation"]["not_observed"])
        self.assertNotIn("CI passed", harness["pr_preparation"]["not_observed"])
        self.assertNotIn("merge readiness", harness["pr_preparation"]["not_observed"])
        self.assertNotIn("merge", harness["pr_preparation"]["not_observed"])
        self.assertTrue(any("Docs sync evidence is still missing" in line for line in harness["safe_status_lines"]))
        self.assertTrue(any("GitHub PR creation is still not observed" in line for line in harness["safe_status_lines"]))

    def test_full_runtime_ladder_with_explicit_docs_and_pr_refs_completes(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor and update docs",
            executor_target="hermes",
        )["runtime_handoff"]
        handoff["acceptance_criteria"] = [*handoff["acceptance_criteria"], "Update README and generated docs."]
        all_events = [
            "runtime_start",
            "worktree_creation",
            "worker_dispatch",
            "worker_result",
            "verification",
            "review",
            "ci",
            "merge_readiness",
            "merge",
        ]
        latest = {event: {"summary": f"{event} observed"} for event in all_events}
        latest["verification"] = {
            "summary": "verification and docs generation observed",
            "evidence_refs": ["docs_sync:docs/WORKFLOWS.md"],
        }
        latest["merge_readiness"] = {
            "summary": "PR created and ready for merge",
            "evidence_refs": ["github_pr_created:https://github.com/rlaope/oh-my-hermes/pull/123"],
        }

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            runtime_observation={
                "observed_events": all_events,
                "blocked_events": [],
                "failed_events": [],
                "unsatisfied_events": [],
                "latest": latest,
            },
        )

        self.assertEqual(validate_hermes_coding_harness(harness), [])
        self.assertEqual(harness["status"], "completed")
        self.assertEqual(harness["docs_sync"]["status"], "observed")
        self.assertEqual(harness["docs_sync"]["missing_evidence"], [])
        self.assertEqual(harness["pr_preparation"]["missing_evidence"], [])
        self.assertNotIn("GitHub PR creation", harness["pr_preparation"]["not_observed"])
        self.assertFalse(any("evidence is still missing" in line for line in harness["safe_status_lines"]))
        self.assertFalse(any("creation is still not observed" in line for line in harness["safe_status_lines"]))

    def test_non_observed_evidence_refs_do_not_clear_docs_or_pr_gaps(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor and update docs",
            executor_target="hermes",
        )["runtime_handoff"]
        handoff["acceptance_criteria"] = [*handoff["acceptance_criteria"], "Update README and generated docs."]

        for status in ("not_observed", "blocked", "failed"):
            with self.subTest(status=status):
                harness = build_hermes_coding_harness(
                    runtime_handoff=handoff,
                    runtime_observation={
                        "observed_events": ["merge_readiness"] if status == "not_observed" else [],
                        "blocked_events": ["verification", "merge_readiness"] if status == "blocked" else [],
                        "failed_events": ["verification", "merge_readiness"] if status == "failed" else [],
                        "latest": {
                            "verification": {
                                "status": status,
                                "summary": f"docs ref exists but verification is {status}",
                                "evidence_refs": ["docs_sync:docs/WORKFLOWS.md"],
                            },
                            "merge_readiness": {
                                "status": status,
                                "summary": f"PR ref exists but merge readiness is {status}",
                                "evidence_refs": ["github_pr_created:https://github.com/rlaope/oh-my-hermes/pull/123"],
                            },
                        },
                    },
                )

                self.assertEqual(harness["docs_sync"]["status"], "prepared_not_observed")
                self.assertEqual(harness["docs_sync"]["missing_evidence"], ["docs_sync_evidence_ref"])
                self.assertIn("github_pr_created", harness["pr_preparation"]["missing_evidence"])
                self.assertIn("GitHub PR creation", harness["pr_preparation"]["not_observed"])

    def test_validator_rejects_drifted_nested_projection_sections(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]
        harness = dict(handoff["hermes_coding_harness"])
        harness["verification_matrix"] = {**harness["verification_matrix"], "schema_version": "wrong"}
        harness["docs_sync"] = {**harness["docs_sync"], "claim_boundary": "files changed"}
        harness["pr_preparation"] = {**harness["pr_preparation"], "missing_evidence": []}

        errors = validate_hermes_coding_harness(harness)

        self.assertTrue(any("verification_matrix schema_version" in error for error in errors))
        self.assertTrue(any("docs_sync claim_boundary" in error for error in errors))
        self.assertTrue(any("github_pr_created" in error for error in errors))

    def test_validator_rejects_drifted_stage_and_lane_shapes(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]
        harness = dict(handoff["hermes_coding_harness"])
        first_stage = dict(harness["workflow_graph"][0])
        first_stage.pop("not_evidence")
        first_stage["unexpected"] = "drift"
        harness["workflow_graph"] = [first_stage, *harness["workflow_graph"][1:]]
        first_lane = dict(harness["lanes"][0])
        first_lane["evidence_gap"] = "no"
        first_lane["claim_boundary"] = "not enough"
        harness["lanes"] = [first_lane, *harness["lanes"][1:]]

        errors = validate_hermes_coding_harness(harness)

        self.assertTrue(any("workflow_graph[0] has unsupported keys" in error for error in errors))
        self.assertTrue(any("workflow_graph[0].not_evidence must be a list" in error for error in errors))
        self.assertTrue(any("lanes[0].evidence_gap must be a boolean" in error for error in errors))
        self.assertTrue(any("lanes[0].claim_boundary must mention runtime_observation/v1" in error for error in errors))

    def test_non_hermes_executor_does_not_get_harness_projection(self) -> None:
        handoff = build_coding_delegation_payload("risky refactor", executor_target="omx-runtime")["runtime_handoff"]

        self.assertEqual(build_hermes_coding_harness(runtime_handoff=handoff), {})

    def test_team_observation_without_worker_ref_keeps_evidence_gap(self) -> None:
        handoff = build_coding_delegation_payload(
            "coordinate a safe Hermes coding team for a risky refactor",
            executor_target="hermes",
        )["runtime_handoff"]

        harness = build_hermes_coding_harness(
            runtime_handoff=handoff,
            start_mode="team",
            runtime_observation={
                "observed_events": ["worker_result"],
                "blocked_events": [],
                "failed_events": [],
                "latest": {"worker_result": {"summary": "result observed without worker identity"}},
            },
        )

        lanes = {lane["id"]: lane for lane in harness["lanes"]}
        self.assertEqual(lanes["builder_lane"]["state"], "observed")
        self.assertTrue(lanes["builder_lane"]["worker_ref_required"])
        self.assertTrue(lanes["builder_lane"]["evidence_gap"])


if __name__ == "__main__":
    unittest.main()
