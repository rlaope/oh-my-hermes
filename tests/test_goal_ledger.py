from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()
from omh.goal_ledger import (
    MERGE_OBLIGATION_CRITERION_IDS,
    merge_obligation_criterion,
    GOAL_COMPLETION_GATE_SCHEMA,
    GOAL_CONTINUATION_SCHEMA,
    GOAL_FAILURE_REASON_CODES,
    GOAL_LEDGER_SCHEMA,
    GOAL_STATUS_CARD_SCHEMA,
    GOAL_TERMINAL_STATUSES,
    build_goal_completion_gate,
    build_goal_continuation,
    build_goal_status_card,
    cancel_goal_ledger,
    complete_goal_ledger,
    create_goal_ledger,
    fail_goal_ledger,
    goal_ledger_path,
    read_goal_ledger,
    record_goal_blocker,
    record_goal_checkpoint,
    record_goal_quality_gate,
    validate_goal_ledger,
)
from omh.paths import resolve_paths
from omh.record_revision import (
    APPLIED_MUTATIONS_LIMIT,
    ConflictingMutationReplay,
    applied_mutation_key,
)


class GoalLedgerTests(unittest.TestCase):
    def test_create_goal_ledger_is_metadata_only_and_private(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            raw_objective = "Force completion for a long goal with private raw detail SECRET-12345."

            goal = create_goal_ledger(
                paths,
                raw_objective,
                ["All required acceptance criteria are tracked."],
                goal_id="goal-alpha",
                source="hermes-goal-mode",
                linked_runtime_runs=["run-1"],
            )

            saved = json.loads(goal_ledger_path(paths, "goal-alpha").read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], GOAL_LEDGER_SCHEMA)
            self.assertEqual(saved["objective_storage"], "sha256")
            self.assertEqual(len(saved["objective_hash"]), 64)
            self.assertNotIn("objective", saved)
            self.assertNotIn(raw_objective, json.dumps(saved))
            self.assertNotIn("SECRET-12345", json.dumps(saved))
            self.assertEqual(goal["acceptance_criteria"][0]["status"], "pending")
            self.assertTrue((paths.goals_dir / "goal-alpha" / "evidence").is_dir())

    def test_checkpoint_satisfies_referenced_criteria_and_links_runtime_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "Finish the durable goal",
                [{"id": "AC-ledger", "summary": "Ledger is written"}],
                goal_id="goal-checkpoint",
            )

            updated = record_goal_checkpoint(
                paths,
                "goal-checkpoint",
                "Ledger module written and tested",
                criteria_refs=["AC-ledger"],
                evidence_refs=["tests/test_goal_ledger.py"],
                linked_runtime_run_id="run-42",
            )

            self.assertEqual(updated["status"], "active")
            self.assertEqual(updated["current_checkpoint"], updated["checkpoints"][0]["checkpoint_id"])
            self.assertEqual(updated["acceptance_criteria"][0]["status"], "satisfied")
            self.assertEqual(updated["acceptance_criteria"][0]["evidence_refs"], ["tests/test_goal_ledger.py"])
            self.assertEqual(updated["linked_runtime_runs"], ["run-42"])
            self.assertEqual(read_goal_ledger(paths, "goal-checkpoint")["checkpoints"][0]["status"], "done")

    def test_checkpoint_stamps_the_tree_the_work_was_observed_against(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths, "Stamp the observed tree", [{"id": "AC-tree", "summary": "Tree is stamped"}], goal_id="goal-tree"
            )

            updated = record_goal_checkpoint(
                paths,
                "goal-tree",
                "Ran the suite",
                criteria_refs=["AC-tree"],
                evidence_refs=["tests/test_goal_ledger.py"],
                observed_tree="abc1234",
            )

            self.assertEqual(updated["checkpoints"][0]["observed_tree"], "abc1234")
            stored = read_goal_ledger(paths, "goal-tree")
            self.assertEqual(stored["checkpoints"][0]["observed_tree"], "abc1234")

    def test_a_checkpoint_without_an_observed_tree_records_no_tree(self) -> None:
        # The stamp is optional: a caller that cannot answer "which tree" must
        # keep recording checkpoints exactly as before rather than guess one.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths, "Skip the observed tree", [{"id": "AC-none", "summary": "No tree"}], goal_id="goal-no-tree"
            )

            updated = record_goal_checkpoint(paths, "goal-no-tree", "Drafted the notes", status="in_progress")

            self.assertEqual(updated["checkpoints"][0]["observed_tree"], "")
            self.assertTrue(validate_goal_ledger(read_goal_ledger(paths, "goal-no-tree"))["ok"])

    def test_a_checkpoint_written_before_the_field_existed_stays_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths, "Read an older ledger", [{"id": "AC-old", "summary": "Old shape"}], goal_id="goal-old"
            )
            record_goal_checkpoint(paths, "goal-old", "Recorded earlier", status="in_progress")
            path = goal_ledger_path(paths, "goal-old")
            goal = json.loads(path.read_text(encoding="utf-8"))
            goal["checkpoints"][0].pop("observed_tree")
            path.write_text(json.dumps(goal), encoding="utf-8")

            self.assertTrue(validate_goal_ledger(read_goal_ledger(paths, "goal-old"))["ok"])

    def test_a_retry_stamping_a_different_tree_is_refused_not_replayed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths, "Refuse a divergent retry", [{"id": "AC-retry", "summary": "Retry is guarded"}], goal_id="goal-retry-tree"
            )
            record_goal_checkpoint(
                paths, "goal-retry-tree", "Ran the suite", status="in_progress",
                mutation_id="cp-tree-1", observed_tree="abc1234",
            )

            with self.assertRaises(ConflictingMutationReplay):
                record_goal_checkpoint(
                    paths, "goal-retry-tree", "Ran the suite", status="in_progress",
                    mutation_id="cp-tree-1", observed_tree="def5678",
                )

            stored = read_goal_ledger(paths, "goal-retry-tree")
            self.assertEqual(len(stored["checkpoints"]), 1)
            self.assertEqual(stored["checkpoints"][0]["observed_tree"], "abc1234")

    def test_completion_gate_rejects_pending_criteria_with_summary_only_output(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            raw_objective = "Finish a private long-running goal SECRET-GATE"
            create_goal_ledger(paths, raw_objective, ["Criterion one"], goal_id="goal-gate")

            gate = build_goal_completion_gate(paths, "goal-gate")

            self.assertEqual(gate["schema_version"], GOAL_COMPLETION_GATE_SCHEMA)
            self.assertFalse(gate["ready"])
            self.assertEqual(gate["next_action"], "record_checkpoint")
            self.assertNotIn(raw_objective, json.dumps(gate))
            self.assertNotIn("SECRET-GATE", json.dumps(gate))

    def test_complete_goal_requires_gate_then_marks_goal_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Finish a durable goal", ["Criterion one"], goal_id="goal-complete")
            rejected = complete_goal_ledger(paths, "goal-complete")
            self.assertFalse(rejected["completed"])

            record_goal_checkpoint(paths, "goal-complete", "Done", criteria_refs=["AC001"], evidence_refs=["unit"])
            missing_completion_evidence = complete_goal_ledger(paths, "goal-complete")
            self.assertFalse(missing_completion_evidence["completed"])
            self.assertEqual(missing_completion_evidence["completion_gate"]["next_action"], "record_completion")

            completed = complete_goal_ledger(paths, "goal-complete", evidence_refs=["unit"])

            self.assertTrue(completed["completed"])
            self.assertTrue(completed["completion_gate"]["ready"])
            self.assertEqual(completed["goal"]["status"], "complete")
            self.assertEqual(completed["goal"]["quality_gates"][0]["status"], "passed")

    def test_completion_gate_does_not_trust_complete_status_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Finish a durable goal", ["Criterion one"], goal_id="goal-tampered")
            path = goal_ledger_path(paths, "goal-tampered")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["status"] = "complete"
            path.write_text(json.dumps(data), encoding="utf-8")

            gate = build_goal_completion_gate(paths, "goal-tampered")

            self.assertFalse(gate["ready"])
            self.assertEqual(gate["next_action"], "record_checkpoint")

    def test_completion_gate_requires_evidence_for_satisfied_criteria(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Finish a durable goal", ["Criterion one"], goal_id="goal-evidence")
            path = goal_ledger_path(paths, "goal-evidence")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["acceptance_criteria"][0]["status"] = "satisfied"
            data["acceptance_criteria"][0]["evidence_refs"] = []
            path.write_text(json.dumps(data), encoding="utf-8")

            gate = build_goal_completion_gate(paths, "goal-evidence")

            self.assertFalse(gate["ready"])
            self.assertEqual(gate["missing_required_criteria"][0]["id"], "AC001")

    def test_summary_only_checkpoint_cannot_satisfy_criteria(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Finish a durable goal", ["Criterion one"], goal_id="goal-summary-only")

            with self.assertRaisesRegex(ValueError, "require evidence_refs"):
                record_goal_checkpoint(paths, "goal-summary-only", "Summary only", criteria_refs=["AC001"])

    def test_goal_and_runtime_ids_reject_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            with self.assertRaisesRegex(ValueError, "goal_id"):
                create_goal_ledger(paths, "Finish a durable goal", ["Criterion one"], goal_id="../../outside")
            with self.assertRaisesRegex(ValueError, "linked_runtime_run_id"):
                create_goal_ledger(
                    paths,
                    "Finish a durable goal",
                    ["Criterion one"],
                    goal_id="goal-safe",
                    linked_runtime_runs=["../runtime"],
                )
            create_goal_ledger(paths, "Finish a durable goal", ["Criterion one"], goal_id="goal-safe")
            with self.assertRaisesRegex(ValueError, "goal_id"):
                read_goal_ledger(paths, "../goal-safe")
            path = goal_ledger_path(paths, "goal-safe")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["linked_runtime_runs"] = ["../run"]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "linked_runtime_runs"):
                read_goal_ledger(paths, "goal-safe")

    def test_linked_runtime_is_checked_only_when_explicitly_referenced(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "Finish a durable goal",
                ["Criterion one"],
                goal_id="goal-runtime",
                linked_runtime_runs=["missing-run"],
            )
            record_goal_checkpoint(paths, "goal-runtime", "Done", criteria_refs=["AC001"], evidence_refs=["unit"])

            gate = build_goal_completion_gate(paths, "goal-runtime")

            self.assertFalse(gate["ready"])
            self.assertEqual(gate["next_action"], "show_status")
            self.assertEqual(gate["linked_runtime_checks"][0]["schema_version"], "goal_runtime_evidence_check/v1")
            self.assertEqual(gate["linked_runtime_checks"][0]["next_action"], "record_runtime_evidence")

    def test_continuation_payload_is_distinct_from_status_card(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            raw_objective = "Finish a durable goal SECRET-CONTINUATION"
            create_goal_ledger(paths, raw_objective, ["Criterion one"], goal_id="goal-continuation")

            continuation = build_goal_continuation(paths, "goal-continuation")
            status_card = build_goal_status_card(paths, "goal-continuation")

            self.assertEqual(continuation["schema_version"], GOAL_CONTINUATION_SCHEMA)
            self.assertEqual(status_card["schema_version"], GOAL_STATUS_CARD_SCHEMA)
            self.assertNotEqual(continuation["schema_version"], "status_card/v1")
            self.assertNotEqual(status_card["schema_version"], "status_card/v1")
            self.assertEqual(continuation["next_action"], "record_checkpoint")
            self.assertEqual(status_card["progress"]["required_satisfied"], 0)
            self.assertEqual(status_card["missing_criteria"][0]["id"], "AC001")
            self.assertIn("record_checkpoint", continuation["actions"])
            self.assertIn("next_step", continuation["safe_copy"])
            self.assertNotIn("SECRET-CONTINUATION", json.dumps(continuation))

    def test_unknown_criterion_reference_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Finish the durable goal", ["Known criterion"], goal_id="goal-invalid")

            with self.assertRaisesRegex(ValueError, "unknown acceptance criteria"):
                record_goal_checkpoint(paths, "goal-invalid", "Bad checkpoint", criteria_refs=["AC-missing"])

    def test_blocker_and_quality_gate_are_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Finish the durable goal", ["Known criterion"], goal_id="goal-gates")

            blocked = record_goal_blocker(
                paths,
                "goal-gates",
                "Need observed execution evidence",
                attempted_recovery="Checked runtime run records",
                evidence_refs=[".omh/runtime/runs"],
            )
            gated = record_goal_quality_gate(
                paths,
                "goal-gates",
                "Unit test passed",
                evidence_refs=["uv run python -m unittest tests/test_goal_ledger.py -v"],
            )

            self.assertEqual(blocked["blockers"][0]["status"], "active")
            self.assertEqual(gated["quality_gates"][0]["status"], "passed")
            self.assertTrue(validate_goal_ledger(gated)["ok"])

    def test_fail_goal_ledger_records_a_negative_conclusive_terminal_status(self) -> None:
        # #H: a goal that cannot be met at all (the target does not exist, the
        # request is refused by policy) gets its own terminal status, distinct
        # from `blocked` (recoverable) and `cancelled` (an operator decision).
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Migrate a table that turns out not to exist", ["Table migrated"], goal_id="goal-fail")

            failed = fail_goal_ledger(
                paths,
                "goal-fail",
                "The target table was never created in this environment.",
                reason_code="target_not_found",
                evidence_refs=["psql -c dt"],
            )

            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["failure_reason_code"], "target_not_found")
            self.assertIn("target table", failed["failure_summary"])
            self.assertEqual(failed["failure_evidence_refs"], ["psql -c dt"])
            self.assertIn("failed", GOAL_TERMINAL_STATUSES)
            self.assertTrue(validate_goal_ledger(failed)["ok"])

    def test_fail_goal_ledger_requires_a_closed_reason_code(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Goal with an unsupported failure reason", ["AC"], goal_id="goal-bad-reason")

            with self.assertRaises(ValueError):
                fail_goal_ledger(paths, "goal-bad-reason", "because", reason_code="not_a_real_code")

    def test_a_failed_goal_is_terminal_and_refuses_further_mutations(self) -> None:
        # Requirement (a): terminal means retry/resume-shaped paths must not
        # select it -- here, no further checkpoint, blocker, or gate applies.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Goal that will conclusively fail", ["AC"], goal_id="goal-terminal")
            fail_goal_ledger(paths, "goal-terminal", "Refused by policy.", reason_code="refused_by_policy")

            with self.assertRaises(ValueError):
                record_goal_checkpoint(paths, "goal-terminal", "Trying anyway")
            with self.assertRaises(ValueError):
                record_goal_blocker(paths, "goal-terminal", "Some blocker")
            with self.assertRaises(ValueError):
                fail_goal_ledger(paths, "goal-terminal", "Again", reason_code="refused_by_policy")

    def test_a_failed_goals_completion_gate_and_status_card_render_distinctly(self) -> None:
        # Requirement (c): reporting surfaces render the outcome distinctly
        # from an ordinary in-progress or blocked goal.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "Goal that cannot be met as specified", ["AC"], goal_id="goal-render")
            fail_goal_ledger(
                paths, "goal-render", "Criteria are infeasible as specified.",
                reason_code="infeasible_as_specified",
            )

            gate = build_goal_completion_gate(paths, "goal-render")
            self.assertFalse(gate["ready"])
            self.assertEqual(gate["next_action"], "show_status")
            self.assertIn("goal status is failed", gate["summary"])

            card = build_goal_status_card(paths, "goal-render")
            self.assertEqual(card["goal_status"], "failed")
            self.assertEqual(card["failure_reason_code"], "infeasible_as_specified")
            self.assertIn("failed conclusively", card["safe_copy"]["next_step"])
            self.assertIn("infeasible_as_specified", card["safe_copy"]["next_step"])
            self.assertEqual(card["allowed_actions"], ["show_status"])

    def test_reason_codes_are_closed_and_exhaustively_round_trip(self) -> None:
        for reason in GOAL_FAILURE_REASON_CODES:
            with self.subTest(reason=reason), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                create_goal_ledger(paths, f"Goal for {reason}", ["AC"], goal_id="goal-reason")
                failed = fail_goal_ledger(paths, "goal-reason", "because", reason_code=reason)
                self.assertEqual(failed["failure_reason_code"], reason)

    def test_validation_flags_raw_objective_and_bad_shape(self) -> None:
        validation = validate_goal_ledger(
            {
                "schema_version": GOAL_LEDGER_SCHEMA,
                "goal_id": "bad-goal",
                "status": "active",
                "objective": "raw prompt should not be stored",
                "objective_storage": "plaintext",
                "objective_hash": "not-a-sha",
                "acceptance_criteria": [],
                "checkpoints": {},
                "blockers": [],
                "quality_gates": [],
                "linked_runtime_runs": [],
            }
        )

        self.assertFalse(validation["ok"])
        self.assertIn("raw objective field is not allowed", validation["errors"])
        self.assertIn("objective_storage must be sha256", validation["errors"])


class GoalStatusCardCheckpointRenderingTests(unittest.TestCase):
    # A live Slack session once rendered goal checkpoints as a markdown
    # table (| ID | 이름 | 상태 | 증거 |), which messenger surfaces (Slack,
    # Telegram) silently drop. These tests pin the fix: the status card
    # pre-renders dash lines and tells the caller never to use a table.
    def test_checkpoint_lines_are_pre_rendered_dash_bullets(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "Finish the durable goal",
                ["Criterion one"],
                goal_id="goal-checkpoint-lines",
            )
            record_goal_checkpoint(paths, "goal-checkpoint-lines", "Wrote the ledger module", evidence_refs=["unit"])
            record_goal_checkpoint(paths, "goal-checkpoint-lines", "Drafted the design notes")

            status_card = build_goal_status_card(paths, "goal-checkpoint-lines")
            lines = status_card["checkpoint_lines"]

            self.assertEqual(len(lines), 2)
            self.assertRegex(lines[0], r"^- [0-9a-f]+: Wrote the ledger module — done, observed$")
            self.assertRegex(lines[1], r"^- [0-9a-f]+: Drafted the design notes — done, prepared$")
            self.assertIn("Never render a markdown table", status_card["render_guidance"])
            self.assertIn("messenger surfaces", status_card["render_guidance"])

    def test_checkpoint_lines_is_empty_list_not_missing_key_when_no_checkpoints(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "Finish the durable goal",
                ["Criterion one"],
                goal_id="goal-no-checkpoints",
            )

            status_card = build_goal_status_card(paths, "goal-no-checkpoints")

            self.assertIn("checkpoint_lines", status_card)
            self.assertEqual(status_card["checkpoint_lines"], [])

    def test_safe_copy_carries_checkpoint_format_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "Finish the durable goal",
                ["Criterion one"],
                goal_id="goal-format-hint",
            )

            status_card = build_goal_status_card(paths, "goal-format-hint")

            self.assertEqual(
                status_card["safe_copy"]["checkpoint_format"],
                "- cpN: summary — status, evidence",
            )


class GoalLedgerMutationIdTests(unittest.TestCase):
    def _goal(self, paths, goal_id: str = "goal-mutation-id") -> dict:
        return create_goal_ledger(
            paths,
            "Finish the durable goal",
            [{"id": "AC-guard", "summary": "Guard is verified"}],
            goal_id=goal_id,
        )

    def test_connector_style_mutation_ids_are_accepted_and_replay_once(self) -> None:
        # Goals used to be the one surface that restricted mutation_id to the
        # storage-id charset, so a connector deriving ids from upstream
        # message ids (snowflakes carrying ':' or '/') failed only here.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            mutation_id = "slack:C123/p1700000000.000100"

            first = record_goal_checkpoint(
                paths, "goal-mutation-id", "Snowflake", status="in_progress", mutation_id=mutation_id
            )
            second = record_goal_checkpoint(
                paths, "goal-mutation-id", "Snowflake", status="in_progress", mutation_id=mutation_id
            )

            stored = read_goal_ledger(paths, "goal-mutation-id")
            self.assertEqual(len(stored["checkpoints"]), 1)
            self.assertEqual(first["record_revision"], second["record_revision"])
            # The item id is derived from the mutation id, never taken from it
            # verbatim when it is not filesystem-safe.
            checkpoint_id = stored["checkpoints"][0]["checkpoint_id"]
            self.assertTrue(checkpoint_id.startswith("checkpoint-"))
            self.assertNotIn("/", checkpoint_id)
            self.assertNotIn(":", checkpoint_id)

    def test_item_id_derivation_from_a_mutation_id_is_deterministic(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths, "goal-a")
            self._goal(paths, "goal-b")

            first = record_goal_blocker(paths, "goal-a", "Needs approval", mutation_id="slack:C1/p1.2")
            second = record_goal_blocker(paths, "goal-b", "Needs approval", mutation_id="slack:C1/p1.2")

            self.assertEqual(first["blockers"][0]["blocker_id"], second["blockers"][0]["blocker_id"])

    def test_filesystem_safe_mutation_ids_stay_verbatim_in_the_item_id(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)

            goal = record_goal_checkpoint(
                paths, "goal-mutation-id", "Readable", status="in_progress", mutation_id="cp-retry-1"
            )

            self.assertEqual(goal["checkpoints"][0]["checkpoint_id"], "cp-retry-1")

    def test_mutation_outcome_reports_replay_and_what_the_record_actually_says(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            first_outcome: dict = {}
            replay_outcome: dict = {}

            cancel_goal_ledger(paths, "goal-mutation-id", mutation_id="cancel-1", outcome=first_outcome)
            cancel_goal_ledger(paths, "goal-mutation-id", mutation_id="cancel-1", outcome=replay_outcome)

            self.assertEqual(first_outcome, {"replayed": False, "applied": True, "goal_status": "cancelled"})
            self.assertEqual(replay_outcome, {"replayed": True, "applied": True, "goal_status": "cancelled"})

    def test_goal_ledger_validator_rejects_bad_revision_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            goal = self._goal(paths)

            revision_errors = validate_goal_ledger({**goal, "record_revision": -1})["errors"]
            applied_errors = validate_goal_ledger({**goal, "applied_mutations": []})["errors"]

            self.assertIn("goal_ledger record_revision must be a non-negative integer", revision_errors)
            self.assertIn("goal_ledger applied_mutations must be an object", applied_errors)


class GoalLedgerEvictedRetryTests(unittest.TestCase):
    """The retry proof left after the bounded applied_mutations map forgot an id.

    The eviction floor only refuses a retry that also carried an
    expected_revision, and every CLI accepts --mutation-id on its own. Before
    issue #828 such a retry applied a second time and appended a duplicate item
    under the same derived id. The item id is materialized from the mutation
    id, so the record itself is the proof the map can no longer give.
    """

    def _goal(self, paths, goal_id: str = "goal-evicted") -> dict:
        return create_goal_ledger(
            paths,
            "Survive applied_mutations eviction",
            [{"id": "AC-evict", "summary": "Retries survive eviction"}],
            goal_id=goal_id,
        )

    def _evict(self, paths, goal_id: str = "goal-evicted") -> dict:
        """Push the goal past the bound so the seeded id is no longer retained."""
        for index in range(APPLIED_MUTATIONS_LIMIT + 10):
            record_goal_checkpoint(
                paths,
                goal_id,
                f"filler {index}",
                status="in_progress",
                mutation_id=f"filler-{index:04d}",
            )
        stored = read_goal_ledger(paths, goal_id)
        self.assertGreaterEqual(int(stored["applied_mutations_floor_revision"]), 1)
        return stored

    def test_a_retry_carrying_only_a_mutation_id_leaves_one_blocker_after_eviction(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_blocker(paths, "goal-evicted", "the original blocker", mutation_id="turn-EVICT-ME")
            stored = self._evict(paths)
            self.assertNotIn(
                applied_mutation_key("record_goal_blocker", "turn-EVICT-ME"), stored["applied_mutations"]
            )
            outcome: dict = {}

            goal = record_goal_blocker(
                paths, "goal-evicted", "the original blocker", mutation_id="turn-EVICT-ME", outcome=outcome
            )

            self.assertEqual(outcome, {"replayed": True, "applied": True, "goal_status": "active"})
            blockers = read_goal_ledger(paths, "goal-evicted")["blockers"]
            self.assertEqual([item["blocker_id"] for item in blockers], ["turn-EVICT-ME"])
            self.assertEqual(blockers[0]["summary"], "the original blocker")
            # A replay is not a write: the revision did not move.
            self.assertEqual(goal["record_revision"], int(stored["record_revision"]))

    def test_a_retried_checkpoint_after_eviction_neither_duplicates_nor_bumps(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_checkpoint(
                paths, "goal-evicted", "the original checkpoint", status="in_progress", mutation_id="cp-EVICT-ME"
            )
            stored = self._evict(paths)
            before = len(stored["checkpoints"])
            outcome: dict = {}

            record_goal_checkpoint(
                paths,
                "goal-evicted",
                "the original checkpoint",
                status="in_progress",
                mutation_id="cp-EVICT-ME",
                outcome=outcome,
            )

            after = read_goal_ledger(paths, "goal-evicted")
            self.assertEqual(len(after["checkpoints"]), before)
            self.assertEqual(int(after["record_revision"]), int(stored["record_revision"]))
            self.assertTrue(outcome["replayed"])
            self.assertTrue(outcome["applied"])

    def test_a_retried_quality_gate_after_eviction_leaves_one_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_quality_gate(paths, "goal-evicted", "suite green", mutation_id="qg-EVICT-ME")
            self._evict(paths)
            outcome: dict = {}

            record_goal_quality_gate(
                paths, "goal-evicted", "suite green", mutation_id="qg-EVICT-ME", outcome=outcome
            )

            gates = read_goal_ledger(paths, "goal-evicted")["quality_gates"]
            self.assertEqual([item["quality_gate_id"] for item in gates], ["qg-EVICT-ME"])
            self.assertTrue(outcome["replayed"])
            self.assertTrue(outcome["applied"])

    def test_a_new_mutation_id_still_applies_after_eviction_has_happened(self) -> None:
        # The dedupe must not be a disguised widening of the floor rule: once
        # any eviction has happened, an id the record has never seen still has
        # to apply normally.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            stored = self._evict(paths)
            outcome: dict = {}

            goal = record_goal_blocker(
                paths, "goal-evicted", "brand new blocker", mutation_id="turn-BRAND-NEW", outcome=outcome
            )

            self.assertEqual(outcome, {"replayed": False, "applied": True, "goal_status": "active"})
            self.assertEqual(int(goal["record_revision"]), int(stored["record_revision"]) + 1)
            self.assertEqual(
                [item["blocker_id"] for item in read_goal_ledger(paths, "goal-evicted")["blockers"]],
                ["turn-BRAND-NEW"],
            )

    def test_a_retried_completion_after_eviction_reports_a_replay(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_checkpoint(
                paths,
                "goal-evicted",
                "Criterion satisfied",
                criteria_refs=["AC-evict"],
                evidence_refs=["observed:suite-green"],
            )
            first = complete_goal_ledger(
                paths, "goal-evicted", evidence_refs=["observed:suite-green"], mutation_id="done-EVICT-ME"
            )
            self.assertTrue(first["completed"])
            # A complete goal refuses further checkpoints, so eviction is
            # forced by clearing the map directly rather than by more writes.
            path = goal_ledger_path(paths, "goal-evicted")
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["applied_mutations"] = {}
            stored["applied_mutations_floor_revision"] = int(stored["record_revision"])
            path.write_text(json.dumps(stored, sort_keys=True), encoding="utf-8")

            second = complete_goal_ledger(
                paths, "goal-evicted", evidence_refs=["observed:suite-green"], mutation_id="done-EVICT-ME"
            )

            self.assertTrue(second["completed"])
            self.assertTrue(second["replayed"])
            gates = read_goal_ledger(paths, "goal-evicted")["quality_gates"]
            self.assertEqual([item["quality_gate_id"] for item in gates], ["done-EVICT-ME"])


class GoalLedgerDuplicateItemIdValidationTests(unittest.TestCase):
    def _goal(self, paths) -> dict:
        return create_goal_ledger(
            paths,
            "Reject duplicate item ids",
            [{"id": "AC-dup", "summary": "Duplicates are rejected"}],
            goal_id="goal-duplicate",
        )

    def test_duplicate_item_ids_in_one_list_are_a_validation_error(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            goal = self._goal(paths)
            for id_key, label, list_key, item in (
                (
                    "checkpoint_id",
                    "checkpoint",
                    "checkpoints",
                    {"status": "done", "summary": "s", "criteria_refs": [], "evidence_refs": []},
                ),
                ("blocker_id", "blocker", "blockers", {"status": "active", "summary": "s", "evidence_refs": []}),
                (
                    "quality_gate_id",
                    "quality gate",
                    "quality_gates",
                    {"status": "passed", "summary": "s", "evidence_refs": []},
                ),
            ):
                with self.subTest(list_key=list_key):
                    duplicated = {
                        **goal,
                        list_key: [{**item, id_key: "shared-id"}, {**item, id_key: "shared-id"}],
                    }

                    validation = validate_goal_ledger(duplicated)

                    self.assertFalse(validation["ok"])
                    self.assertIn(f"duplicate {label} {id_key}: shared-id", validation["errors"])

    def test_distinct_item_ids_in_one_list_stay_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_blocker(paths, "goal-duplicate", "First", mutation_id="b-1")
            record_goal_blocker(paths, "goal-duplicate", "Second", mutation_id="b-2")

            stored = read_goal_ledger(paths, "goal-duplicate")

            self.assertEqual([item["blocker_id"] for item in stored["blockers"]], ["b-1", "b-2"])
            self.assertEqual(validate_goal_ledger(stored), {"ok": True, "errors": []})

    def test_a_duplicate_planted_by_hand_is_refused_by_the_guarded_write(self) -> None:
        # The validator runs inside guarded_record_update, so a record that
        # already lost the invariant cannot be extended by a further mutation.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_blocker(paths, "goal-duplicate", "First", mutation_id="b-1")
            path = goal_ledger_path(paths, "goal-duplicate")
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["blockers"] = stored["blockers"] + [dict(stored["blockers"][0])]
            path.write_text(json.dumps(stored, sort_keys=True), encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                record_goal_blocker(paths, "goal-duplicate", "Second", mutation_id="b-2")

            self.assertIn("duplicate blocker blocker_id: b-1", str(caught.exception))

    def test_one_mutation_id_shared_across_both_quality_gate_writers_is_refused(self) -> None:
        # record_goal_quality_gate and complete_goal_ledger are different
        # operations writing into the SAME list, so one id reused across them
        # is a genuine collision. It is refused visibly - completed stays
        # false and replayed is true - rather than persisting a duplicate id.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._goal(paths)
            record_goal_checkpoint(
                paths,
                "goal-duplicate",
                "Criterion satisfied",
                criteria_refs=["AC-dup"],
                evidence_refs=["observed:suite-green"],
            )
            record_goal_quality_gate(paths, "goal-duplicate", "suite green", mutation_id="turn-1")

            collided = complete_goal_ledger(
                paths, "goal-duplicate", evidence_refs=["observed:suite-green"], mutation_id="turn-1"
            )
            distinct = complete_goal_ledger(
                paths, "goal-duplicate", evidence_refs=["observed:suite-green"], mutation_id="turn-2"
            )

            self.assertFalse(collided["completed"])
            self.assertTrue(collided["replayed"])
            self.assertTrue(distinct["completed"])
            self.assertFalse(distinct["replayed"])
            stored = read_goal_ledger(paths, "goal-duplicate")
            self.assertEqual([item["quality_gate_id"] for item in stored["quality_gates"]], ["turn-1", "turn-2"])
            self.assertEqual(validate_goal_ledger(stored), {"ok": True, "errors": []})


class MergeObligationCriterionTests(unittest.TestCase):
    def test_the_constructor_builds_a_required_merge_criterion(self) -> None:
        criterion = merge_obligation_criterion("merge", ref="#647")
        self.assertEqual(criterion["id"], MERGE_OBLIGATION_CRITERION_IDS["merge"])
        self.assertIs(criterion["required"], True)
        self.assertIn("receipt", criterion["summary"])
        self.assertIn("#647", criterion["summary"])

    def test_deploy_is_a_distinct_criterion_id(self) -> None:
        self.assertEqual(
            merge_obligation_criterion("deploy")["id"], MERGE_OBLIGATION_CRITERION_IDS["deploy"]
        )

    def test_an_unsupported_obligation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            merge_obligation_criterion("rebase")

    def test_a_fresh_merge_obligation_ledger_stays_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "coding-delegation:merge:goal-obl",
                [merge_obligation_criterion("merge")],
                goal_id="goal-obl",
                source="coding_delegation",
            )
            gate = build_goal_completion_gate(paths, "goal-obl")
            self.assertFalse(gate["ready"])
            self.assertEqual(
                [c["id"] for c in gate["missing_required_criteria"]],
                [MERGE_OBLIGATION_CRITERION_IDS["merge"]],
            )

    def test_hand_satisfying_without_a_receipt_stays_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "coding-delegation:merge:goal-hand",
                [merge_obligation_criterion("merge")],
                goal_id="goal-hand",
                source="coding_delegation",
            )
            # A placeholder evidence value trips the existing completion-integrity
            # refusal, so "merged" cannot check out without an observed receipt.
            record_goal_checkpoint(
                paths,
                "goal-hand",
                "recorded merge",
                criteria_refs=[MERGE_OBLIGATION_CRITERION_IDS["merge"]],
                evidence_refs=["pending"],
                status="done",
            )
            gate = build_goal_completion_gate(paths, "goal-hand")
            self.assertFalse(gate["ready"])
            self.assertTrue(gate["integrity_refusals"])

    def test_an_observed_receipt_ref_satisfies_the_obligation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(
                paths,
                "coding-delegation:merge:goal-recv",
                [merge_obligation_criterion("merge", ref="#647")],
                goal_id="goal-recv",
                source="coding_delegation",
            )
            record_goal_checkpoint(
                paths,
                "goal-recv",
                "merge observed via receipt",
                criteria_refs=[MERGE_OBLIGATION_CRITERION_IDS["merge"]],
                evidence_refs=["observed: merge receipt merge:run-1 external_ref pr-647"],
                status="done",
            )
            gate = build_goal_completion_gate(paths, "goal-recv")
            self.assertTrue(gate["ready"])
            self.assertEqual(gate["integrity_refusals"], [])


if __name__ == "__main__":
    unittest.main()
