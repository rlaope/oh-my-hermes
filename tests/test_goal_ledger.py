from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()
from omh.goal_ledger import (
    GOAL_COMPLETION_GATE_SCHEMA,
    GOAL_CONTINUATION_SCHEMA,
    GOAL_LEDGER_SCHEMA,
    GOAL_STATUS_CARD_SCHEMA,
    build_goal_completion_gate,
    build_goal_continuation,
    build_goal_status_card,
    complete_goal_ledger,
    create_goal_ledger,
    goal_ledger_path,
    read_goal_ledger,
    record_goal_blocker,
    record_goal_checkpoint,
    record_goal_quality_gate,
    validate_goal_ledger,
)
from omh.paths import resolve_paths


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


if __name__ == "__main__":
    unittest.main()
