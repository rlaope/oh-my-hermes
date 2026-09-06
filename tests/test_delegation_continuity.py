"""Cross-delegation continuity is OMH-owned durable state, never product-tree markdown.

When OMH delegates coding work toward a stated merge/deploy goal, the outstanding
obligation is recorded as a goal ledger in the OMH state root -- not hand-written
into a product repo's `.omo`/`.omx`/`.document-harness` runtime-evidence dirs. A
delegated subtask completing (a review, say) is not the parent goal completing:
the goal stays OPEN until the merge/deploy is observed through an external-effect
receipt, or until explicit cancellation, and it is reconcilable from the
persisted ledger alone after a resume or compaction.

These tests cover the seam with Goal 1 (the merge directive it preserves is what
raises this block), the OMH-state-root write target, the command-layer ledger
creation and run linkage, the subtask-not-goal gate, cancellation, offline
reconciliation, and the awareness guardrail text.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.coding.coding_delegation import build_coding_delegation_payload  # noqa: E402
from omh.commands.coding import (  # noqa: E402
    _link_delegation_continuity_run,
    _record_delegation_continuity,
)
from omh.goal_ledger import (  # noqa: E402
    MERGE_OBLIGATION_CRITERION_IDS,
    build_goal_completion_gate,
    build_goal_continuation,
    cancel_goal_ledger,
    read_goal_ledger,
    record_goal_checkpoint,
)
from omh.paths import (  # noqa: E402
    CONTINUITY_FORBIDDEN_TARGETS,
    OmhPaths,
    continuity_write_target,
    resolve_paths,
)
from omh.plugin_bundle.omh.awareness import (  # noqa: E402
    awareness_primer_payload,
    workflow_context_cards,
)

_MESSAGE = "fix the broken login flow in src/auth.py and add a regression test"


def _merge_payload() -> dict[str, object]:
    return build_coding_delegation_payload(f"{_MESSAGE} then merge it", executor_target="codex")


class WriteTargetTests(unittest.TestCase):
    """The one allowed destination resolves under the OMH goals dir, never a product tree."""

    def test_user_scope_target_is_under_omh_home_goals(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            target = continuity_write_target(paths)
            goals_dir = Path(target["goals_dir"])
            self.assertEqual(goals_dir, paths.omh_home / "goals")
            self.assertEqual(goals_dir.parent, Path(target["state_root"]))

    def test_project_scope_target_is_under_the_repo_omh_home(self) -> None:
        # A `<repo>/.omh` state root -- exactly the shape `--scope project`
        # resolves to -- still puts continuity under its own goals dir.
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            paths = OmhPaths(omh_home=repo / ".omh", hermes_home=repo / ".hermes")
            target = continuity_write_target(paths)
            self.assertEqual(Path(target["goals_dir"]), repo / ".omh" / "goals")

    def test_the_target_never_names_a_product_runtime_evidence_dir(self) -> None:
        for home in ("~/.omh", "/some/repo/.omh"):
            with self.subTest(home=home):
                paths = OmhPaths(omh_home=Path(home), hermes_home=Path(home).parent / ".hermes")
                target = continuity_write_target(paths)
                for forbidden in CONTINUITY_FORBIDDEN_TARGETS:
                    self.assertNotIn(forbidden, target["goals_dir"])
                self.assertEqual(target["forbidden_targets"], list(CONTINUITY_FORBIDDEN_TARGETS))


class LedgerCreationTests(unittest.TestCase):
    def test_persisting_a_merge_delegation_creates_a_required_pending_criterion(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = _merge_payload()
            record = _record_delegation_continuity(paths, payload)
            self.assertTrue(record["recorded"])
            self.assertTrue(record["created"])
            goal = read_goal_ledger(paths, record["goal_id"])
            self.assertEqual(goal["status"], "active")
            self.assertEqual(Path(record["goal_ledger_path"]).parent.parent, paths.goals_dir)
            (criterion,) = goal["acceptance_criteria"]
            self.assertEqual(criterion["id"], MERGE_OBLIGATION_CRITERION_IDS["merge"])
            self.assertIs(criterion["required"], True)
            self.assertEqual(criterion["status"], "pending")
            self.assertEqual(criterion["evidence_refs"], [])

    def test_a_plain_delegation_records_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = build_coding_delegation_payload(_MESSAGE, executor_target="codex")
            record = _record_delegation_continuity(paths, payload)
            self.assertFalse(record["recorded"])
            self.assertFalse(paths.goals_dir.exists())

    def test_re_delegation_links_the_existing_ledger_without_overwriting(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = _merge_payload()
            first = _record_delegation_continuity(paths, payload)
            record_goal_checkpoint(paths, first["goal_id"], "made progress", status="in_progress")
            second = _record_delegation_continuity(paths, payload)
            self.assertEqual(second["goal_id"], first["goal_id"])
            self.assertFalse(second["created"])
            self.assertTrue(second["linked"])
            # The in-progress checkpoint survived: the re-delegation did not
            # recreate (and reset) the ledger.
            goal = read_goal_ledger(paths, first["goal_id"])
            self.assertTrue(any(c["summary"] == "made progress" for c in goal["checkpoints"]))

    def test_a_linked_run_is_an_in_progress_checkpoint_not_a_completion(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = _merge_payload()
            record = _record_delegation_continuity(paths, payload)
            payload["delegation_continuity_record"] = record
            _link_delegation_continuity_run(paths, payload, "run-abc")
            goal = read_goal_ledger(paths, record["goal_id"])
            self.assertIn("run-abc", goal["linked_runtime_runs"])
            (checkpoint,) = goal["checkpoints"]
            self.assertEqual(checkpoint["status"], "in_progress")
            self.assertEqual(checkpoint["criteria_refs"], [])
            # The obligation is still open: linking a subtask satisfied no criterion.
            gate = build_goal_completion_gate(paths, record["goal_id"])
            self.assertFalse(gate["ready"])


class SubtaskIsNotGoalTests(unittest.TestCase):
    def test_a_completed_review_subtask_leaves_the_merge_obligation_open(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _record_delegation_continuity(paths, _merge_payload())
            goal_id = record["goal_id"]
            # The delegated review run is observed complete, with observed-class
            # evidence -- yet it references no acceptance criterion, so it is a
            # subtask, not the goal.
            record_goal_checkpoint(
                paths,
                goal_id,
                "delegated review run completed",
                status="done",
                evidence_refs=["observed: review passed run-abc"],
            )
            gate = build_goal_completion_gate(paths, goal_id)
            self.assertFalse(gate["ready"])
            self.assertEqual(
                [c["id"] for c in gate["missing_required_criteria"]],
                [MERGE_OBLIGATION_CRITERION_IDS["merge"]],
            )


class CancellationTests(unittest.TestCase):
    def test_explicit_cancellation_is_terminal_and_refuses_later_checkpoints(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _record_delegation_continuity(paths, _merge_payload())
            goal_id = record["goal_id"]
            cancelled = cancel_goal_ledger(paths, goal_id, reason="user cancelled the merge")
            self.assertEqual(cancelled["status"], "cancelled")
            with self.assertRaises(ValueError):
                record_goal_checkpoint(paths, goal_id, "too late", status="in_progress")


class ReconciliationTests(unittest.TestCase):
    def test_the_obligation_is_reconcilable_from_the_persisted_ledger_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            goal_id = _record_delegation_continuity(paths, _merge_payload())["goal_id"]
            # Rebuild from disk with no live process in hand: this is the
            # after-resume/compaction path.
            reread = resolve_paths(paths.omh_home, paths.hermes_home)
            continuation = build_goal_continuation(reread, goal_id)
            self.assertEqual(continuation["goal_status"], "active")
            self.assertEqual(continuation["next_action"], "record_checkpoint")
            missing = continuation["status_card"]["missing_criteria"]
            self.assertEqual(
                [c["id"] for c in missing], [MERGE_OBLIGATION_CRITERION_IDS["merge"]]
            )


class AwarenessGuardrailTests(unittest.TestCase):
    def _coding_handoff_card(self) -> dict[str, object]:
        for card in workflow_context_cards():
            if card.get("id") == "coding_handoff":
                return card
        self.fail("coding_handoff card not found")

    def test_the_card_carries_both_goal_1_and_goal_2_clauses(self) -> None:
        shape = str(self._coding_handoff_card()["first_response_shape"])
        # Goal 1's preserved-merge clause.
        self.assertIn("post-verification", shape)
        self.assertIn("no merge", shape)
        # Goal 2's write-location clause.
        self.assertIn(".omh/goals", shape)
        self.assertIn(".omo", shape)
        self.assertIn(".omx", shape)
        self.assertIn("subtask completing is not the parent goal completing", shape)

    def test_a_write_location_rail_line_is_present(self) -> None:
        cues = awareness_primer_payload()["workflow_cues"]
        rails = [
            cue
            for cue in cues
            if ".omh/goals" in str(cue.get("route", "")) and ".omo" in str(cue.get("route", ""))
        ]
        self.assertTrue(rails, "no delegation-continuity write-location rail cue found")


if __name__ == "__main__":
    unittest.main()
