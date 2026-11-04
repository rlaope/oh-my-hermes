from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class WorkflowStateCliTests(unittest.TestCase):
    def test_state_start_writes_authoritative_workflow_state(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "deep-interview", "--note", "clarify"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            state = json.loads(stdout)["state"]
            self.assertTrue(state["active"])
            self.assertEqual(state["workflow"], "deep-interview")
            self.assertEqual(state["note"], "clarify")
            self.assertTrue((omh_home / "state" / "deep-interview-state.json").exists())
            self.assertFalse((omh_home / "runtime" / "runs").exists())

    def test_state_status_survives_new_cli_invocation(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "deep-interview"])[0], 0)
            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "state", "status"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["active"][0]["workflow"], "deep-interview")

    def test_allowed_transition_auto_completes_source_state(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "deep-interview"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "ralplan"])[0], 0)

            deep = json.loads((omh_home / "state" / "deep-interview-state.json").read_text(encoding="utf-8"))
            ralplan = json.loads((omh_home / "state" / "ralplan-state.json").read_text(encoding="utf-8"))
            self.assertFalse(deep["active"])
            self.assertEqual(deep["lifecycle_outcome"], "finished")
            self.assertEqual(deep["transition_target"], "ralplan")
            self.assertTrue(ralplan["active"])

    def test_accepted_plan_can_start_dag_ulw(self) -> None:
        # The planning skills offer dag-ulw after acceptance; taking the offer must not be refused.
        for planner in ("plan", "ralplan"):
            with self.subTest(planner=planner), TemporaryDirectory() as tmp:
                omh_home = Path(tmp) / ".omh"

                self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", planner])[0], 0)
                status, _, stderr = run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "dag-ulw"])

                self.assertEqual((status, stderr), (0, ""))
                source = json.loads((omh_home / "state" / f"{planner}-state.json").read_text(encoding="utf-8"))
                dag = json.loads((omh_home / "state" / "dag-ulw-state.json").read_text(encoding="utf-8"))
                self.assertFalse(source["active"])
                self.assertEqual(source["transition_target"], "dag-ulw")
                self.assertTrue(dag["active"])

    def test_conflicting_transition_is_denied_with_diagnostic(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "deep-interview"])[0], 0)
            status, _, stderr = run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "ultrawork"])

            self.assertEqual(status, 2)
            self.assertIn("active workflow deep-interview must finish or be cleared first", stderr)

    def test_terminal_outcomes_are_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "ralplan"])[0], 0)
            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "state", "finish", "--workflow", "ralplan", "--outcome", "question_pending", "--note", "waiting"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            state = json.loads(stdout)["state"]
            self.assertFalse(state["active"])
            self.assertEqual(state["lifecycle_outcome"], "question_pending")
            self.assertEqual(state["note"], "waiting")

    def test_state_clear_removes_only_target_workflow(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "deep-interview"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "state", "start", "--workflow", "ralplan"])[0], 0)
            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "state", "clear", "--workflow", "ralplan"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(stdout)["removed"])
            self.assertTrue((omh_home / "state" / "deep-interview-state.json").exists())
            self.assertFalse((omh_home / "state" / "ralplan-state.json").exists())

    def test_state_reports_malformed_state_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            state_dir = omh_home / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "ralplan-state.json").write_text("{not-json", encoding="utf-8")

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "state", "status"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("ralplan-state.json", payload["errors"][0]["path"])


if __name__ == "__main__":
    unittest.main()
