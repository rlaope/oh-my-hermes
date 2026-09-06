"""`cancelled` as a first-class observed terminal state (issue #1360).

The four terminal states have to stay apart everywhere they are recorded and
everywhere they are read. These tests hold that line from both ends: a
cancellation can be RECORDED without being relabelled, and once recorded it
never reads as active, stale, blocked, failed, or completed, and never satisfies
an evidence gate.
"""

from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding.executor_progress import (  # noqa: E402
    CLOSING_EVENT_TYPES,
    PROGRESS_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    build_progress_binding,
    build_safe_progress_signal,
    infer_progress_event_type,
    observe_executor_progress,
    read_progress_binding,
    wait_outcome_for_progress_event,
    write_progress_binding,
)
from omh.coding.wait_strategy import (  # noqa: E402
    WAIT_TERMINAL_STATES,
    arm_wait_binding,
    build_execution_wait_strategy,
    consume_wait_completion,
)
from omh.coding_lifecycle import (  # noqa: E402
    CodingLifecycleError,
    record_codex_dispatch,
    record_codex_result,
    record_codex_verification,
    report_codex_delegation_lifecycle,
    start_codex_delegation_lifecycle,
)
from omh.executors import EXECUTOR_PROFILES  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.plugin_bundle.omh.runtime_reader import _hud_subagent_summary  # noqa: E402
from omh.runtime.artifacts import (  # noqa: E402
    export_runtime,
    show_run,
    summarize_delegated_coding_status,
)
from omh.runtime.claims import Claim, allowed_runtime_claims  # noqa: E402
from omh.runtime.records import (  # noqa: E402
    DELEGATION_RESULTS,
    OBSERVED_RESULTS,
    RUN_STATUSES,
    UNOBSERVED_RESULTS,
    WRAPPER_COMPLETION_STATUSES,
    build_delegation_record,
    build_run_record,
    build_wrapper_record,
    validate_delegation_record,
    validate_delegation_result,
    validate_run_record,
    validate_wrapper_record,
)
from omh.wrapper.continuity_state import journey_state, resume_status_from_evidence  # noqa: E402
from omh.wrapper.contract import STATUS_CARD_STEP_STATES  # noqa: E402
from omh.wrapper.executor_sessions import build_executor_session_status_card  # noqa: E402
from omh.wrapper.executor_sessions import (  # noqa: E402
    EXECUTOR_SESSION_OBSERVED_RESULTS,
    EXECUTOR_SESSION_RESULTS,
    EXECUTOR_SESSION_STATUSES,
    ExecutorSessionError,
    open_executor_session,
    record_executor_session_result,
)
from omh.wrapper_sessions import (  # noqa: E402
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)

from omh.commands.main import build_parser  # noqa: E402


def _paths(tmp: str):
    return resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")


class CancelledVocabularyTests(unittest.TestCase):
    def test_cancelled_is_a_member_of_every_terminal_vocabulary(self) -> None:
        self.assertIn("cancelled", RUN_STATUSES)
        self.assertIn("cancelled", DELEGATION_RESULTS)
        self.assertIn("cancelled", OBSERVED_RESULTS)
        self.assertIn("cancelled", WRAPPER_COMPLETION_STATUSES)
        self.assertIn("cancelled", EXECUTOR_SESSION_STATUSES)
        self.assertIn("cancelled", EXECUTOR_SESSION_RESULTS)
        self.assertIn("cancelled", EXECUTOR_SESSION_OBSERVED_RESULTS)

    def test_cancellation_is_observed_never_merely_requested(self) -> None:
        """It sits with the observed results, so recording it needs the same evidence."""
        self.assertNotIn("cancelled", UNOBSERVED_RESULTS)
        with self.assertRaises(ValueError):
            validate_delegation_result(False, "cancelled")
        validate_delegation_result(True, "cancelled")

    def test_a_cancelled_run_and_wrapper_record_build_and_validate(self) -> None:
        run = build_run_record({"status": "cancelled", "skill": "x", "harness": "y"}, "run-1")
        self.assertEqual(validate_run_record(run), [])
        wrapper = build_wrapper_record({"completion_status": "cancelled"})
        self.assertEqual(validate_wrapper_record(wrapper), [])
        delegation = build_delegation_record(
            {"requested": True, "observed": True, "result": "cancelled", "evidence_refs": ["host:sigterm"]}
        )
        self.assertEqual(validate_delegation_record(delegation), [])

    def test_records_written_before_cancelled_existed_still_validate(self) -> None:
        """The change is additive: no stored record's meaning or shape moved."""
        for result in ("completed", "blocked", "failed"):
            with self.subTest(result=result):
                legacy = build_delegation_record({"requested": True, "observed": True, "result": result})
                self.assertEqual(validate_delegation_record(legacy), [])
        for status in ("started", "completed", "blocked", "failed", "unknown"):
            with self.subTest(status=status):
                self.assertEqual(validate_wrapper_record(build_wrapper_record({"completion_status": status})), [])

    def test_a_forged_cancellation_is_refused_the_way_every_unobserved_claim_is(self) -> None:
        with self.assertRaises(ValueError):
            build_delegation_record({"requested": True, "observed": False, "result": "cancelled"})


class CancelledLifecycleTests(unittest.TestCase):
    def _cancelled_run(self, paths) -> str:
        started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
        run_id = started["run"]["run_id"]
        record_codex_dispatch(paths, run_id)
        record_codex_result(paths, run_id, result="cancelled", evidence_refs=["host:sigterm"])
        return run_id

    def test_a_cancelled_result_records_without_being_relabelled(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            run_id = self._cancelled_run(paths)

            delegation = json.loads((paths.runtime_runs_dir / run_id / "delegation.json").read_text())
            self.assertEqual(delegation["result"], "cancelled")
            self.assertTrue(delegation["observed"])

    def test_the_status_surfaces_cancellation_apart_from_a_blocker(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            run_id = self._cancelled_run(paths)

            status = summarize_delegated_coding_status(paths, run_id)
            self.assertEqual(status["next_action"], "surface_executor_cancellation")
            self.assertEqual(status["execution"]["status"], "cancelled")
            self.assertIn("was cancelled", status["safe_summary"])
            self.assertNotIn("blocked", status["safe_summary"])

            reported = report_codex_delegation_lifecycle(paths, run_id)
            self.assertEqual(reported["lifecycle_status"], "cancelled")
            self.assertFalse(reported["can_report_completion"])
            self.assertIn("re-dispatched or resumed", reported["blocking_reason"])

    def test_a_cancelled_run_cannot_record_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            run_id = self._cancelled_run(paths)

            with self.assertRaises(CodingLifecycleError):
                record_codex_verification(paths, run_id)

    def test_the_lifecycle_projection_says_cancelled_and_nothing_else(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            run_id = self._cancelled_run(paths)

            lifecycle = show_run(paths, run_id)["lifecycle"]
            self.assertTrue(lifecycle["cancelled"])
            self.assertFalse(lifecycle["blocked"])
            self.assertFalse(lifecycle["failed"])
            self.assertFalse(lifecycle["verification_observed"])
            self.assertFalse(lifecycle["merge_observed"])

    def test_cancellation_satisfies_no_evidence_gate_above_dispatch(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            run_id = self._cancelled_run(paths)

            allowed = allowed_runtime_claims(summarize_delegated_coding_status(paths, run_id), validation_failed=False)
            self.assertIn(Claim.EXECUTOR_DISPATCHED, allowed)
            for claim in (
                Claim.EXECUTION_OBSERVED,
                Claim.VERIFICATION_OBSERVED,
                Claim.REVIEW_OBSERVED,
                Claim.CI_OBSERVED,
                Claim.MERGE_READY,
                Claim.MERGED,
            ):
                with self.subTest(claim=claim.value):
                    self.assertNotIn(claim, allowed)

    def test_a_blocked_result_still_reaches_the_execution_rung(self) -> None:
        """The negative above is about cancellation, not a new rule for every non-success."""
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="blocked", evidence_refs=["codex-log"])

            allowed = allowed_runtime_claims(summarize_delegated_coding_status(paths, run_id), validation_failed=False)
            self.assertIn(Claim.EXECUTION_OBSERVED, allowed)


class CancelledProgressEventTests(unittest.TestCase):
    def _binding(self, paths) -> dict:
        binding = build_progress_binding(
            target_type="run",
            target_id="20260101T000000-run",
            executor_profile="codex",
        )
        return write_progress_binding(paths, binding)

    def test_executor_cancelled_is_terminal_and_closing(self) -> None:
        self.assertIn("executor_cancelled", PROGRESS_EVENT_TYPES)
        self.assertIn("executor_cancelled", TERMINAL_EVENT_TYPES)
        self.assertIn("executor_cancelled", CLOSING_EVENT_TYPES)

    def test_the_wait_contract_and_the_progress_contract_agree(self) -> None:
        outcome = wait_outcome_for_progress_event("executor_cancelled")
        self.assertEqual(outcome, "cancelled")
        self.assertIn(outcome, WAIT_TERMINAL_STATES)
        strategy = build_execution_wait_strategy(
            work_kind="executor_dispatch",
            expected_duration_class="long",
            handle_kind="process",
            handle_ref="job-1",
            condition="the dispatched unit reports a terminal result",
            host_capabilities=("background_completion_notification",),
            deadline_seconds=60,
            cancellation_path="terminate the dispatched unit process group",
        )
        closed = consume_wait_completion(arm_wait_binding(strategy), outcome=outcome)
        self.assertEqual(closed["binding_state"], "cancelled")
        self.assertNotIn("unmapped_source_outcome", closed)

    def test_a_host_observed_termination_infers_cancellation_not_failure(self) -> None:
        for process_status in ("cancelled", "terminated", "interrupted", "signal_terminated", "killed"):
            with self.subTest(process_status=process_status):
                signal = build_safe_progress_signal(executor_profile="codex", process_status=process_status)
                self.assertEqual(infer_progress_event_type(signal), "executor_cancelled")

    def test_an_executor_narrating_its_own_cancellation_is_not_believed(self) -> None:
        """A cancellation the host did not observe is narration, and narration ends nothing."""
        signal = build_safe_progress_signal(
            executor_profile="codex",
            profile_progress_summary={"status": "", "latest_progress_event_type": "executor_cancelled"},
        )
        self.assertNotEqual(infer_progress_event_type(signal), "executor_cancelled")

    def test_the_event_closes_the_binding_so_it_is_never_stale_afterwards(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            binding = self._binding(paths)
            signal = build_safe_progress_signal(executor_profile="codex", process_status="cancelled")

            observation = observe_executor_progress(paths, binding, signal)

            self.assertEqual(observation["event"]["event_type"], "executor_cancelled")
            self.assertEqual(observation["binding"]["state"], "closed")
            stored = read_progress_binding(paths, "run", "20260101T000000-run")
            self.assertEqual(stored["state"], "closed")


class CancelledWrapperSessionTests(unittest.TestCase):
    """Recording a cancellation through the wrapper session, for every executor profile."""

    def _session(self, paths, profile: str) -> str:
        started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
        session_id = str(started["session"]["session_id"])
        record_plan_decision(paths, session_id, "accept")
        select_wrapper_session_executor(paths, session_id, profile)
        prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
        open_executor_session(
            paths,
            session_id,
            observed=True,
            external_session_ref="thread-1",
            evidence_refs=["discord-button"],
        )
        return session_id

    def test_every_supported_executor_profile_can_record_a_cancellation(self) -> None:
        for profile in EXECUTOR_PROFILES:
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                paths = _paths(tmp)
                session_id = self._session(paths, profile)

                recorded = record_executor_session_result(
                    paths, session_id, result="cancelled", evidence_refs=["host:sigterm"]
                )

                status = recorded["status"]
                self.assertEqual(status["result"], "cancelled")
                self.assertEqual(status["coding_agent"], f"cancelled({profile})")
                self.assertEqual(status["verification"], "not_requested")
                self.assertEqual(recorded["executor_session"]["status"], "cancelled")

    def test_the_cancellation_closes_the_progress_binding_and_names_its_own_event(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            session_id = self._session(paths, "codex")

            recorded = record_executor_session_result(
                paths, session_id, result="cancelled", evidence_refs=["host:sigterm"]
            )

            progress = recorded["status"]["executor_progress"]
            self.assertEqual(progress["state"], "closed")
            self.assertEqual(progress["latest_event"]["event_type"], "executor_cancelled")

    def test_the_status_card_shows_cancelled_apart_from_blocked_and_failed(self) -> None:
        card = build_executor_session_status_card({"result": "cancelled", "verification": "not_requested"})
        result_step = next(step for step in card["steps"] if step["id"] == "result")

        self.assertEqual(result_step["state"], "cancelled")
        self.assertIn(result_step["state"], STATUS_CARD_STEP_STATES)
        self.assertEqual(card["severity"], "cancelled")

        blocked = build_executor_session_status_card({"result": "blocked", "verification": "not_requested"})
        self.assertEqual(
            next(step for step in blocked["steps"] if step["id"] == "result")["state"], "blocked"
        )

    def test_an_unsupported_result_word_is_still_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            session_id = self._session(paths, "codex")

            with self.assertRaises(ExecutorSessionError):
                record_executor_session_result(paths, session_id, result="cancel_requested")


class CancelledCliSurfaceTests(unittest.TestCase):
    """The recorded vocabulary and the offered vocabulary are the same vocabulary.

    An integration that can only submit `failed` or `blocked` for a cancelled
    run has to relabel it, which is the coercion this whole change removes.
    """

    def _choices(self, path: tuple[str, ...], option: str) -> tuple[str, ...]:
        parser = build_parser()
        for name in path:
            actions = [
                action
                for action in parser._actions  # noqa: SLF001 - argparse has no public subparser lookup
                if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
            ]
            parser = next(sub for action in actions for key, sub in action.choices.items() if key == name)
        target = next(action for action in parser._actions if option in action.option_strings)  # noqa: SLF001
        return tuple(target.choices or ())

    def test_the_result_recording_commands_offer_cancelled(self) -> None:
        for path, option in (
            (("coding", "lifecycle", "result"), "--result"),
            (("coding", "lifecycle", "verify"), "--completion-status"),
            (("chat", "session", "record-executor"), "--result"),
            (("runtime", "wrapper"), "--completion-status"),
            (("runtime", "delegate"), "--result"),
            (("runtime", "record"), "--status"),
        ):
            with self.subTest(command=" ".join(path)):
                self.assertIn("cancelled", self._choices(path, option))


class CancelledHudProjectionTests(unittest.TestCase):
    def test_a_cancelled_executor_row_is_neither_running_nor_blocked(self) -> None:
        summary = _hud_subagent_summary(
            {
                "active_executors": [
                    {
                        "target_id": "run-a",
                        "target_type": "run",
                        "executor_profile": "codex",
                        "latest_event": {"event_type": "executor_cancelled", "status": "cancelled", "summary": "s"},
                    },
                    {
                        "target_id": "run-b",
                        "target_type": "run",
                        "executor_profile": "codex",
                        "latest_event": {"event_type": "executor_blocked", "status": "blocked", "summary": "s"},
                    },
                ],
                "stale_executors": [],
                "latest_progress_events": [],
            }
        )

        self.assertEqual(summary["cancelled"], 1)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["running"], 0)
        states = {row["task_id"]: row["state"] for row in summary["rows"]}
        self.assertEqual(sorted(states.values()), ["blocked", "cancelled"])


class CancelledExportTests(unittest.TestCase):
    def test_a_redacted_export_carries_the_cancellation_as_allowlisted_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="cancelled", evidence_refs=["host:sigterm"])

            payload = export_runtime(paths, redacted=True, run_id=run_id)
            text = json.dumps(payload)

            self.assertIn("cancelled", text)
            delegation = payload["runs"][0]["delegation"]
            self.assertEqual(delegation["result"], "cancelled")
            self.assertEqual(
                sorted(delegation),
                [
                    "evidence_refs",
                    "message",
                    "observed",
                    "participants",
                    "requested",
                    "result",
                    "schema_version",
                    "updated_at",
                ],
            )
            for forbidden in ("stdout", "stderr", "transcript", "raw_logs", "prompt_body"):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(f'"{forbidden}"', text)


class CancelledContinuityTests(unittest.TestCase):
    def test_the_journey_state_names_cancellation_instead_of_invalid_evidence(self) -> None:
        state = journey_state({"execution": {"observed": True, "status": "cancelled"}}, {}, {})
        self.assertEqual(state, "executor_cancelled")

    def test_a_cancelled_session_is_not_resumable_as_a_conversation(self) -> None:
        status = resume_status_from_evidence(
            {
                "runtime_status": {"execution": {"observed": True, "status": "cancelled"}},
                "runtime_observation": {},
                "executor_status": {"result": "cancelled"},
                "session_status": "handoff_prepared",
            }
        )
        self.assertEqual(status, "blocked")


if __name__ == "__main__":
    unittest.main()
