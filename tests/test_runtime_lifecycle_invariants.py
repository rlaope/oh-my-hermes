from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding_lifecycle import record_codex_dispatch, record_codex_result, record_codex_verification
from omh.paths import resolve_paths
from omh.runtime_artifacts import summarize_delegated_coding_status, validate_runtime
from omh.wrapper_sessions import (
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)


class RuntimeLifecycleInvariantTests(unittest.TestCase):
    def test_codex_session_link_preserves_prepared_not_observed_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")

            prepared = prepare_wrapper_session_handoff(paths, session_id, message)

            run_id = str(prepared["session"]["current_run_id"])
            status = summarize_delegated_coding_status(paths, run_id)
            self.assertTrue(status["prepared"]["available"])
            self.assertEqual(status["prepared"]["status"], "prepared_not_observed")
            self.assertFalse(status["wrapper"]["prompt_dispatched"])
            self.assertFalse(status["execution"]["observed"])
            self.assertFalse(status["verification"]["observed"])
            self.assertEqual(status["next_action"], "dispatch_to_executor")
            self.assertTrue(validate_runtime(paths, run_id)["ok"])
            self.assertNotIn(message, json.dumps(prepared))

            run_path = paths.runtime_runs_dir / run_id / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["observation_status"] = "observed"
            run_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")

            validation = validate_runtime(paths, run_id)
            self.assertFalse(validation["ok"])
            self.assertIn("linked run must preserve prepared_not_observed boundary", json.dumps(validation))

    def test_prompt_only_and_runtime_handoff_paths_do_not_create_lifecycle_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            prompt_only = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            prompt_only_id = str(prompt_only["session"]["session_id"])
            record_plan_decision(paths, prompt_only_id, "accept")
            select_wrapper_session_executor(paths, prompt_only_id, "claude-code")
            prompt_handoff = prepare_wrapper_session_handoff(paths, prompt_only_id, "risky refactor")

            self.assertEqual(prompt_handoff["session"]["status"], "prompt_handoff_prepared")
            self.assertEqual(prompt_handoff["session"]["current_run_id"], "")
            self.assertEqual(prompt_handoff["handoff"]["runtime"]["run_created"], False)
            self.assertEqual(validate_runtime(paths)["runs"], [])

            runtime = create_or_resume_wrapper_session(paths, "safe feature implementation plan", source="slack")
            runtime_id = str(runtime["session"]["session_id"])
            record_plan_decision(paths, runtime_id, "accept")
            select_wrapper_session_executor(paths, runtime_id, "hermes")
            runtime_handoff = prepare_wrapper_session_handoff(paths, runtime_id, "safe feature implementation plan")

            self.assertEqual(runtime_handoff["session"]["status"], "runtime_handoff_prepared")
            self.assertEqual(runtime_handoff["session"]["current_run_id"], "")
            self.assertEqual(runtime_handoff["handoff"]["runtime"]["run_created"], False)
            self.assertEqual(runtime_handoff["handoff"]["runtime_handoff"]["runtime_profile"]["runtime_family"], "omh")
            self.assertIn("worktree_creation", runtime_handoff["handoff"]["runtime_handoff"]["evidence_contract"]["prepared_is_not"])
            self.assertEqual(validate_runtime(paths)["runs"], [])

    def test_runtime_completion_claim_waits_for_dispatch_result_and_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "safely add a feature to this repo"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(prepared["session"]["current_run_id"])

            self.assertEqual(summarize_delegated_coding_status(paths, run_id)["next_action"], "dispatch_to_executor")

            record_codex_dispatch(paths, run_id)
            self.assertEqual(summarize_delegated_coding_status(paths, run_id)["next_action"], "wait_for_executor_evidence")

            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-log"])
            self.assertEqual(summarize_delegated_coding_status(paths, run_id)["next_action"], "record_verification_evidence")

            record_codex_verification(paths, run_id)
            status = summarize_delegated_coding_status(paths, run_id)
            self.assertEqual(status["next_action"], "report_completion_with_evidence")
            self.assertTrue(status["execution"]["observed"])
            self.assertTrue(status["verification"]["observed"])
            self.assertTrue(validate_runtime(paths, run_id)["ok"])


if __name__ == "__main__":
    unittest.main()
