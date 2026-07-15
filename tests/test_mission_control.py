from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding_lifecycle import record_codex_dispatch, record_codex_result, record_codex_verification
from omh.mission_control import build_mission_control
from omh.adapter_quality import link_adapter_quality_session
from omh.paths import resolve_paths
from omh.runtime_artifacts import write_ci_record, write_merge_record, write_review_record, write_runtime_observation
from omh.wrapper_sessions import (
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)


class MissionControlTests(unittest.TestCase):
    def test_quality_controls_are_additive_and_do_not_promote_coding_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "inspect checkout layout", source="discord")
            session_id = str(started["session"]["session_id"])
            link_adapter_quality_session(paths, session_id=session_id, subject_id="checkout", surface_kind="web", source_revision="build-42")
            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["adapter_quality"]["status"], "linked_no_observation")
        self.assertEqual(mission_control["quality_evidence"]["claim_state"], "handoff_prepared")

    def test_prepared_handoff_reports_next_safe_action_without_execution_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "safely add a feature to this repo", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepare_wrapper_session_handoff(paths, session_id, "safely add a feature to this repo")

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["schema_version"], "mission_control/v1")
        self.assertEqual(mission_control["owner"]["executor"], "codex")
        self.assertEqual(mission_control["journey"]["state"], "handoff_prepared")
        self.assertEqual(mission_control["recovery"]["status"], "not_started")
        self.assertEqual(mission_control["next_action"], "dispatch_to_executor")
        self.assertFalse(mission_control["execution"]["observed"])
        self.assertEqual(mission_control["capability_observation"]["status"], "prepared")
        self.assertEqual(mission_control["quality_evidence"]["source_binding"]["status"], "not_recorded")
        self.assertEqual(mission_control["merge_decision"]["status"], "not_ready")

    def test_observed_running_reports_wait_instead_of_resume(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id, run_id = _prepared_codex_session(paths)
            record_codex_dispatch(paths, run_id)

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["journey"]["state"], "executor_dispatched")
        self.assertEqual(mission_control["recovery"]["status"], "running_observed")
        self.assertFalse(mission_control["recovery"]["resume_safe"])
        self.assertEqual(mission_control["next_action"], "wait_for_executor_evidence")

    def test_blocked_executor_result_fails_closed_for_recovery(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id, run_id = _prepared_codex_session(paths)
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="blocked", evidence_refs=["local:blocked"])

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["journey"]["state"], "executor_blocked")
        self.assertEqual(mission_control["recovery"]["status"], "recovery_blocked")
        self.assertFalse(mission_control["recovery"]["resume_safe"])
        self.assertNotEqual(mission_control["next_action"], "resume_executor")

    def test_merge_readiness_without_source_binding_is_not_a_merge_decision(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id, run_id = _prepared_codex_session(paths)
            run_dir = paths.runtime_runs_dir / run_id
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["local:result"])
            record_codex_verification(paths, run_id)
            write_review_record(run_dir, {"status": "passed", "reviewer": "local", "evidence_refs": ["local:review"]})
            write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["tests:passed"]})
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["local:merge"]})

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["quality_evidence"]["claim_state"], "merge_ready")
        self.assertEqual(mission_control["quality_evidence"]["source_binding"]["status"], "not_recorded")
        self.assertEqual(mission_control["merge_decision"]["status"], "not_ready")
        self.assertEqual(mission_control["merge_decision"]["next_action"], "record_source_bound_quality_evidence")

    def test_runtime_handoff_uses_observed_session_ladder_without_run_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "coordinate a safe coding team for a risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "hermes")
            prepare_wrapper_session_handoff(paths, session_id, "coordinate a safe coding team for a risky refactor")
            session_dir = paths.runtime_wrapper_sessions_dir / session_id
            write_runtime_observation(
                session_dir,
                {
                    "target_type": "wrapper_session",
                    "target_id": session_id,
                    "runtime_profile": "hermes",
                    "event_type": "runtime_start",
                    "status": "observed",
                    "summary": "Hermes coding path started",
                },
            )
            write_runtime_observation(
                session_dir,
                {
                    "target_type": "wrapper_session",
                    "target_id": session_id,
                    "runtime_profile": "hermes",
                    "event_type": "worker_dispatch",
                    "status": "observed",
                    "summary": "Hermes assigned a worker lane",
                    "worker_ref": "hermes-lane-1",
                },
            )

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["journey"]["state"], "runtime_running_observed")
        self.assertEqual(mission_control["recovery"]["status"], "running_observed")
        self.assertFalse(mission_control["execution"]["observed"])
        self.assertEqual(mission_control["quality_evidence"]["claim_state"], "handoff_prepared")

    def test_invalid_unobserved_result_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id, run_id = _prepared_codex_session(paths)
            delegation_path = paths.runtime_runs_dir / run_id / "delegation.json"
            delegation_path.write_text(
                json.dumps({"requested": True, "observed": False, "result": "fabricated"}),
                encoding="utf-8",
            )

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["journey"]["state"], "invalid_runtime_evidence")
        self.assertFalse(mission_control["execution"]["observed"])
        self.assertEqual(mission_control["recovery"]["status"], "recovery_blocked")

    def test_runtime_worker_result_is_observed_without_merge_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "coordinate a safe coding team for a risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "hermes")
            prepare_wrapper_session_handoff(paths, session_id, "coordinate a safe coding team for a risky refactor")
            session_dir = paths.runtime_wrapper_sessions_dir / session_id
            for event_type in ("runtime_start", "worker_dispatch", "worker_result"):
                write_runtime_observation(
                    session_dir,
                    {
                        "target_type": "wrapper_session",
                        "target_id": session_id,
                        "runtime_profile": "hermes",
                        "event_type": event_type,
                        "status": "observed",
                        "summary": f"Observed {event_type}",
                        "worker_ref": "hermes-lane-1" if event_type != "runtime_start" else "",
                    },
                )

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["journey"]["state"], "runtime_execution_observed")
        self.assertTrue(mission_control["execution"]["observed"])
        self.assertEqual(mission_control["quality_evidence"]["claim_state"], "handoff_prepared")
        self.assertEqual(mission_control["merge_decision"]["status"], "not_ready")

    def test_dangling_run_link_returns_conservative_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id, run_id = _prepared_codex_session(paths)
            (paths.runtime_runs_dir / run_id / "run.json").unlink()

            mission_control = build_mission_control(paths, session_id)

        self.assertEqual(mission_control["journey"]["state"], "invalid_linkage")
        self.assertEqual(mission_control["recovery"]["status"], "recovery_blocked")
        self.assertEqual(mission_control["next_action"], "repair_linked_runtime_record")


def _prepared_codex_session(paths) -> tuple[str, str]:
    started = create_or_resume_wrapper_session(paths, "safely add a feature to this repo", source="discord")
    session_id = str(started["session"]["session_id"])
    record_plan_decision(paths, session_id, "accept")
    select_wrapper_session_executor(paths, session_id, "codex")
    prepared = prepare_wrapper_session_handoff(paths, session_id, "safely add a feature to this repo")
    return session_id, str(prepared["session"]["current_run_id"])


if __name__ == "__main__":
    unittest.main()
