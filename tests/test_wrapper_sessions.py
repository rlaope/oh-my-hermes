from __future__ import annotations

import json
import hashlib
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding_lifecycle import record_codex_dispatch, record_codex_result, start_codex_delegation_lifecycle
from omh.paths import resolve_paths
from omh.runtime_artifacts import create_run, export_runtime, validate_runtime, write_runtime_observation
from omh.runtime_records import validate_wrapper_session_record
from omh.wrapper.executor_sessions import (
    ExecutorSessionError,
    attach_executor_session,
    build_executor_session_status,
    open_executor_session,
    record_executor_session_result,
    request_executor_session_verification,
)
from omh.wrapper_sessions import (
    WrapperSessionError,
    append_wrapper_session_event,
    build_wrapper_session_status,
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
    session_id_for_thread_key,
    write_wrapper_session,
)


class WrapperSessionTests(unittest.TestCase):
    def test_session_start_is_metadata_only_and_resumable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"

            first = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1", "raw": "drop-me"},
            )
            second = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1"},
            )

            session = first["session"]
            self.assertFalse(first["resumed"])
            self.assertTrue(second["resumed"])
            self.assertEqual(session["session_id"], second["session"]["session_id"])
            self.assertEqual(session["session_id"], session_id_for_thread_key("discord:c1:m1"))
            self.assertEqual(session["status"], "plan_presented")
            self.assertEqual(session["decision"], "none")
            self.assertEqual(session["current_run_id"], "")
            self.assertEqual(session["source_metadata"], {"source_event_id": "m1", "channel_ref": "c1"})
            self.assertNotIn(message, json.dumps(first))
            self.assertEqual(validate_wrapper_session_record(session), [])

    def test_session_start_is_scoped_by_hermes_target_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")
            message = "risky refactor"
            shared_event = {"source_event_id": "m1", "channel_ref": "c1"}

            first = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={
                    **shared_event,
                    "agent_ref": "agent-a",
                    "hermes_home": str(root / ".hermes-a"),
                },
            )
            second = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={
                    **shared_event,
                    "agent_ref": "agent-b",
                    "hermes_home": str(root / ".hermes-b"),
                },
            )
            third = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={
                    **shared_event,
                    "agent_ref": "agent-b",
                    "hermes_home": str(root / ".hermes-b"),
                },
            )

            self.assertFalse(first["resumed"])
            self.assertFalse(second["resumed"])
            self.assertTrue(third["resumed"])
            self.assertNotEqual(first["session"]["session_id"], second["session"]["session_id"])
            self.assertEqual(second["session"]["session_id"], third["session"]["session_id"])
            self.assertIn("target-", first["session"]["thread_key"])
            self.assertEqual(first["session"]["source_metadata"]["agent_ref"], "agent-a")
            self.assertEqual(second["session"]["source_metadata"]["agent_ref"], "agent-b")
            self.assertEqual(validate_wrapper_session_record(first["session"]), [])
            self.assertEqual(validate_wrapper_session_record(second["session"]), [])

    def test_session_start_treats_policy_route_actions_as_routed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "prepare weekly ops review from customer feedback and release risks"

            started = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={"source_event_id": "m1", "channel_ref": "ops"},
            )

            session = started["session"]
            self.assertEqual(session["status"], "routed")
            self.assertEqual(session["route"]["selected_skill"], "ops-review")
            self.assertEqual(started["interaction"]["next_action"], "prepare_ops_review")
            self.assertEqual(validate_wrapper_session_record(session), [])

    def test_plan_acceptance_gates_handoff_and_links_run_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"
            started = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1"},
            )
            session_id = str(started["session"]["session_id"])

            with self.assertRaises(WrapperSessionError):
                prepare_wrapper_session_handoff(paths, session_id, message)

            accepted = record_plan_decision(paths, session_id, "accept")
            self.assertEqual(accepted["session"]["status"], "executor_choice_required")
            self.assertEqual(accepted["status"]["chat_response"]["state"]["next_action"], "choose_executor")

            with self.assertRaises(WrapperSessionError):
                prepare_wrapper_session_handoff(paths, session_id, message)

            selected = select_wrapper_session_executor(paths, session_id, "codex")
            self.assertEqual(selected["session"]["status"], "executor_selected")
            self.assertEqual(selected["status"]["chat_response"]["state"]["next_action"], "prepare_handoff")

            handoff = prepare_wrapper_session_handoff(paths, session_id, message)

            session = handoff["session"]
            self.assertEqual(session["status"], "handoff_prepared")
            self.assertTrue(session["current_run_id"])
            self.assertEqual(handoff["status"]["runtime_status"]["next_action"], "dispatch_to_executor")
            self.assertEqual(handoff["status"]["chat_response"]["state"]["next_action"], "dispatch_to_executor")
            self.assertFalse(handoff["status"]["runtime_status"]["execution"]["observed"])
            self.assertTrue(validate_runtime(paths)["ok"])
            session_path = paths.runtime_wrapper_sessions_dir / session_id / "session.json"
            self.assertNotIn(message, session_path.read_text(encoding="utf-8"))

    def test_revision_and_cancel_do_not_create_run_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="slack")
            session_id = str(started["session"]["session_id"])

            revised = record_plan_decision(paths, session_id, "revise")
            cancelled = record_plan_decision(paths, session_id, "cancel")

            self.assertEqual(revised["session"]["current_run_id"], "")
            self.assertEqual(cancelled["session"]["status"], "cancelled")
            self.assertEqual(cancelled["status"]["claim_boundary"], "Wrapper session state is not execution evidence.")
            self.assertEqual(validate_runtime(paths)["runs"], [])

    def test_prompt_only_executor_selection_prepares_no_runtime_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])

            record_plan_decision(paths, session_id, "accept")
            selected = select_wrapper_session_executor(paths, session_id, "claude-code")
            self.assertEqual(selected["session"]["status"], "executor_selected")
            self.assertEqual(selected["session"]["work_owner_mode"], "prompt_only_handoff")

            prepared = prepare_wrapper_session_handoff(paths, session_id, message)

            self.assertEqual(prepared["session"]["status"], "prompt_handoff_prepared")
            self.assertEqual(prepared["session"]["current_run_id"], "")
            self.assertEqual(prepared["session"]["selected_executor_profile"], "claude-code")
            self.assertEqual(prepared["handoff"]["runtime"]["run_created"], False)
            self.assertEqual(prepared["handoff"]["prompt_handoff"]["schema_version"], "coding_prompt_handoff/v1")
            self.assertEqual(prepared["status"]["next_action"], "show_prompt_handoff")
            self.assertEqual(validate_runtime(paths)["runs"], [])
            self.assertTrue(validate_runtime(paths)["ok"])
            session_path = paths.runtime_wrapper_sessions_dir / session_id / "session.json"
            self.assertNotIn(message, session_path.read_text(encoding="utf-8"))

    def test_hermes_selection_prepares_runtime_handoff_without_executor_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])

            record_plan_decision(paths, session_id, "accept")
            selected = select_wrapper_session_executor(paths, session_id, "hermes")

            self.assertEqual(selected["session"]["work_owner_mode"], "runtime_handoff")
            self.assertEqual(selected["session"]["selected_executor_profile"], "hermes")
            self.assertEqual(selected["status"]["chat_response"]["state"]["next_action"], "prepare_handoff")

            prepared = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            self.assertEqual(prepared["session"]["status"], "runtime_handoff_prepared")
            self.assertEqual(prepared["session"]["current_run_id"], "")
            self.assertEqual(prepared["session"]["selected_executor_profile"], "hermes")
            self.assertEqual(prepared["handoff"]["runtime"]["run_created"], False)
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["schema_version"], "coding_runtime_handoff/v1")
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["runtime_family"], "omh")
            self.assertTrue(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["supports_team_swarm"])
            self.assertTrue(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["supports_tmux_workers"])
            self.assertTrue(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["supports_worktree_guidance"])
            self.assertEqual(prepared["status"]["next_action"], "show_runtime_handoff")
            self.assertEqual(validate_runtime(paths)["runs"], [])

    def test_runtime_handoff_preparation_is_idempotent_and_preserves_envelope(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "omx-runtime")

            first = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
            second = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            self.assertEqual(second["session"]["status"], "runtime_handoff_prepared")
            self.assertEqual(second["handoff"]["schema_version"], "runtime_session_handoff/v1")
            self.assertEqual(second["handoff"]["runtime"]["run_created"], False)
            self.assertEqual(second["handoff"]["runtime"]["reason"], "runtime_handoff_is_not_lifecycle_backed")
            self.assertEqual(
                second["handoff"]["runtime_handoff"]["schema_version"],
                first["handoff"]["runtime_handoff"]["schema_version"],
            )
            self.assertEqual(second["handoff"]["runtime_handoff"]["runtime_profile"]["runtime_family"], "omx")
            self.assertEqual(validate_runtime(paths)["runs"], [])

    def test_invalid_plan_decision_transitions_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])

            record_plan_decision(paths, session_id, "revise")

            with self.assertRaises(WrapperSessionError):
                record_plan_decision(paths, session_id, "accept")
            with self.assertRaises(WrapperSessionError):
                prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            cancelled = record_plan_decision(paths, session_id, "cancel")
            self.assertEqual(cancelled["session"]["status"], "cancelled")
            with self.assertRaises(WrapperSessionError):
                record_plan_decision(paths, session_id, "accept")

    def test_clarifying_session_cannot_be_accepted_without_a_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "zzzzunknownphrase", source="discord")
            session_id = str(started["session"]["session_id"])

            self.assertEqual(started["session"]["status"], "clarifying")
            with self.assertRaises(WrapperSessionError):
                record_plan_decision(paths, session_id, "accept")

    def test_handoff_preparation_is_idempotent_and_cannot_be_cancelled(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            first = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
            second = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            self.assertEqual(first["session"]["current_run_id"], second["session"]["current_run_id"])
            with self.assertRaises(WrapperSessionError):
                record_plan_decision(paths, session_id, "cancel")
            status = build_wrapper_session_status(paths, session_id)
            self.assertEqual(status["session_status"], "handoff_prepared")
            self.assertEqual(status["runtime_status"]["next_action"], "dispatch_to_executor")

    def test_handoff_retry_recovers_orphan_prepared_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            source_metadata = {"source_event_id": "m1", "channel_ref": "c1"}
            started = create_or_resume_wrapper_session(paths, message, source="discord", source_metadata=source_metadata)
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            append_wrapper_session_event(
                paths.runtime_wrapper_sessions_dir / session_id,
                {
                    "event": "handoff_prepare_started",
                    "message": "wrapper session started preparing coding handoff",
                    "data": {"message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(), "message_length": len(message)},
                },
            )
            orphan = start_codex_delegation_lifecycle(paths, message, source="discord", source_metadata=source_metadata)

            recovered = prepare_wrapper_session_handoff(paths, session_id, message)

            self.assertEqual(recovered["session"]["current_run_id"], orphan["run"]["run_id"])
            self.assertEqual(len(validate_runtime(paths)["runs"]), 1)
            events = recovered["status"]["runtime_status"]["runtime_validation"]["wrapper_sessions"]
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["ok"])

    def test_handoff_retry_does_not_recover_run_owned_by_another_session(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            source_metadata = {"source_event_id": "m1", "channel_ref": "c1"}
            started = create_or_resume_wrapper_session(paths, message, source="discord", source_metadata=source_metadata)
            first_session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, first_session_id, "accept")
            select_wrapper_session_executor(paths, first_session_id, "codex")
            first_handoff = prepare_wrapper_session_handoff(paths, first_session_id, message)
            first_run_id = str(first_handoff["session"]["current_run_id"])
            second_session_id = "ws-duplicate-recovery-attempt"
            second_session = dict(started["session"])
            second_session.update(
                {
                    "session_id": second_session_id,
                    "thread_key": "discord:c1:m2",
                    "status": "plan_accepted",
                    "decision": "plan_accepted",
                    "work_owner_mode": "external_executor",
                    "selected_executor_profile": "codex",
                    "dispatch_policy": "ask_before_dispatch",
                    "current_run_id": "",
                }
            )
            write_wrapper_session(paths, second_session)
            append_wrapper_session_event(
                paths.runtime_wrapper_sessions_dir / second_session_id,
                {
                    "event": "handoff_prepare_started",
                    "message": "wrapper session started preparing coding handoff",
                    "data": {"message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(), "message_length": len(message)},
                },
            )

            second_handoff = prepare_wrapper_session_handoff(paths, second_session_id, message, source_metadata=source_metadata)

            self.assertNotEqual(second_handoff["session"]["current_run_id"], first_run_id)
            self.assertEqual(len(validate_runtime(paths)["runs"]), 2)
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_handoff_retry_repairs_missing_link_event(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            accepted = record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            lifecycle = start_codex_delegation_lifecycle(paths, message, source="discord")
            session = dict(accepted["session"])
            session.update(
                {
                    "status": "handoff_prepared",
                    "work_owner_mode": "external_executor",
                    "selected_executor_profile": "codex",
                    "dispatch_policy": "ask_before_dispatch",
                    "current_run_id": lifecycle["run"]["run_id"],
                }
            )
            write_wrapper_session(paths, session)

            self.assertFalse(validate_runtime(paths)["ok"])
            healed = prepare_wrapper_session_handoff(paths, session_id, message)

            self.assertEqual(healed["session"]["current_run_id"], lifecycle["run"]["run_id"])
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_runtime_validation_rejects_duplicate_wrapper_run_ownership(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            handoff = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(handoff["session"]["current_run_id"])
            duplicate_session_id = "ws-duplicate-run-owner"
            duplicate = dict(handoff["session"])
            duplicate.update({"session_id": duplicate_session_id, "thread_key": "discord:duplicate-thread"})
            write_wrapper_session(paths, duplicate)
            append_wrapper_session_event(
                paths.runtime_wrapper_sessions_dir / duplicate_session_id,
                {
                    "event": "handoff_prepared",
                    "message": "wrapper session linked prepared coding handoff",
                    "data": {"run_id": run_id, "status": "handoff_prepared", "recovered": True},
                },
            )

            validation = validate_runtime(paths)
            scoped_validation = validate_runtime(paths, run_id)

            self.assertFalse(validation["ok"])
            self.assertFalse(scoped_validation["ok"])
            errors = "\n".join(error for session in validation["wrapper_sessions"] for error in session["errors"])
            self.assertIn("linked by multiple wrapper sessions", errors)

    def test_status_uses_linked_run_instead_of_session_execution_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            status = build_wrapper_session_status(paths, session_id)

            self.assertIn("runtime_status", status)
            self.assertNotIn("execution", status)
            self.assertEqual(status["claim_boundary"], "Execution claims come from the linked runtime run ledger, not the wrapper session.")
            self.assertEqual(len(status["runtime_status"]["runtime_validation"]["wrapper_sessions"]), 1)
            self.assertTrue(status["runtime_status"]["runtime_validation"]["wrapper_sessions"][0]["ok"])

    def test_codex_wrapper_session_exposes_open_attach_record_actions(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            prepared_status = prepared["status"]["executor_session_status"]
            prepared_actions = {action["id"]: action for action in prepared_status["actions"]}
            self.assertEqual(prepared_status["coding_agent"], "prepared(codex)")
            self.assertEqual(prepared_status["dispatch"], "not_observed")
            self.assertEqual(prepared_status["result"], "not_observed")
            self.assertTrue(prepared_actions["open_executor_session"]["enabled"])
            self.assertEqual(prepared_actions["open_executor_session"]["label"], "Open in Codex")
            self.assertEqual(prepared_actions["attach_executor_session"]["label"], "Attach existing session")
            self.assertEqual(prepared_actions["attach_executor_session"]["payload"]["input_schema"]["required"], ["external_session_ref"])
            self.assertIn("open_executor_session", {action["id"] for action in prepared["status"]["chat_response"]["actions"]})
            self.assertEqual(prepared["status"]["status_card"]["executor_session_status"]["coding_agent"], "prepared(codex)")
            self.assertEqual(prepared["status"]["status_card"]["executor_next_action_label"], "Open in Codex")
            self.assertIn("Coding agent is prepared in Codex.", prepared_status["display_status_lines"])
            self.assertIn("open_executor_session", {action["id"] for action in prepared["status"]["status_card"]["executor_actions"]})
            with self.assertRaisesRegex(ExecutorSessionError, "requires --observed"):
                open_executor_session(paths, session_id, external_session_ref="codex-thread-1")

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-1",
                evidence_refs=["discord-button"],
            )

            opened_status = opened["status"]
            self.assertEqual(opened_status["coding_agent"], "running(codex)")
            self.assertEqual(opened_status["executor_session"], "attached")
            self.assertEqual(opened_status["dispatch"], "observed")
            self.assertEqual(opened_status["linked_lifecycle_status"]["next_action"], "wait_for_executor_evidence")
            opened_actions = {action["id"]: action for action in opened_status["actions"]}
            self.assertFalse(opened_actions["open_executor_session"]["enabled"])
            self.assertTrue(opened_actions["record_executor_completed"]["enabled"])
            status_after_open = build_wrapper_session_status(paths, session_id)
            self.assertEqual(status_after_open["runtime_status"]["next_action"], "wait_for_executor_evidence")
            self.assertEqual(status_after_open["status_card"]["executor_session_status"]["coding_agent"], "running(codex)")

            completed = record_executor_session_result(
                paths,
                session_id,
                result="completed",
                evidence_refs=["codex-summary"],
            )

            self.assertEqual(completed["status"]["coding_agent"], "completed(codex)")
            self.assertEqual(completed["status"]["result"], "completed")
            self.assertEqual(completed["status"]["linked_lifecycle_status"]["next_action"], "record_verification_evidence")
            with self.assertRaisesRegex(ExecutorSessionError, "after executor result is recorded"):
                attach_executor_session(paths, session_id, external_session_ref="codex-thread-2")

            verify_request = request_executor_session_verification(paths, session_id)

            self.assertEqual(verify_request["status"]["verification"], "requested")
            self.assertEqual(validate_runtime(paths)["ok"], True)

    def test_codex_lifecycle_result_allows_executor_session_verification_request(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            handoff = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(handoff["session"]["current_run_id"])

            open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-1",
                evidence_refs=["discord-button"],
            )
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-summary"])
            status = build_wrapper_session_status(paths, session_id)
            actions = {action["id"]: action for action in status["executor_session_status"]["actions"]}

            self.assertEqual(status["executor_session_status"]["result"], "completed")
            self.assertTrue(actions["ask_hermes_verify"]["enabled"])
            verify_request = request_executor_session_verification(paths, session_id)

            self.assertEqual(verify_request["status"]["verification"], "requested")

    def test_codex_lifecycle_dispatch_allows_executor_session_result_recording(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            handoff = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(handoff["session"]["current_run_id"])

            record_codex_dispatch(paths, run_id)
            status = build_wrapper_session_status(paths, session_id)
            actions = {action["id"]: action for action in status["executor_session_status"]["actions"]}

            self.assertEqual(status["executor_session_status"]["dispatch"], "observed")
            self.assertTrue(actions["record_executor_completed"]["enabled"])

            completed = record_executor_session_result(paths, session_id, result="completed", evidence_refs=["codex-summary"])

            self.assertEqual(completed["status"]["coding_agent"], "completed(codex)")
            self.assertEqual(completed["status"]["result"], "completed")
            with self.assertRaisesRegex(ExecutorSessionError, "after executor result is recorded"):
                open_executor_session(paths, session_id, observed=True, external_session_ref="codex-thread-2")

    def test_invalid_executor_session_record_is_ignored_for_status_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
            session_dir = paths.runtime_wrapper_sessions_dir / session_id
            (session_dir / "executor_session.json").write_text(
                json.dumps(
                    {
                        "schema_version": "executor_session/v1",
                        "record_type": "executor_session",
                        "session_id": session_id,
                        "updated_at": "2026-06-13T00:00:00Z",
                        "selected_executor_profile": "claude-code",
                        "session_kind": "prompt_only",
                        "status": "completed",
                        "open_action": "observed",
                        "attached": True,
                        "external_session_ref": "claude-secret-session",
                        "dispatch_observed": True,
                        "result": "completed",
                        "result_observed": False,
                        "verification": "not_requested",
                        "verification_requested": False,
                        "evidence_refs": ["private-ref"],
                        "summary": "looks complete but is invalid",
                        "claim_boundary": "Executor session records are metadata-only wrapper/operator observations.",
                    }
                ),
                encoding="utf-8",
            )

            status = build_wrapper_session_status(paths, session_id)["executor_session_status"]
            actions = {action["id"]: action for action in status["actions"]}

            self.assertEqual(status["result"], "not_observed")
            self.assertIn("executor_session_error", status)
            self.assertFalse(actions["ask_hermes_verify"]["enabled"])
            self.assertIn("Action is blocked", status["display_status_lines"][-1])

    def test_missing_linked_codex_run_blocks_local_executor_completion_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            handoff = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(handoff["session"]["current_run_id"])
            open_executor_session(paths, session_id, observed=True, external_session_ref="codex-thread-1")
            record_executor_session_result(paths, session_id, result="completed", evidence_refs=["codex-summary"])
            shutil.rmtree(paths.runtime_runs_dir / run_id)

            session = json.loads((paths.runtime_wrapper_sessions_dir / session_id / "session.json").read_text(encoding="utf-8"))
            status = build_executor_session_status(paths, session)
            actions = {action["id"]: action for action in status["actions"]}

            self.assertEqual(status["result"], "not_observed")
            self.assertEqual(status["dispatch"], "not_observed")
            self.assertIn(f"linked runtime run not found: {run_id}", status["linked_lifecycle_error"])
            self.assertFalse(actions["ask_hermes_verify"]["enabled"])
            with self.assertRaisesRegex(ExecutorSessionError, "linked runtime run not found"):
                request_executor_session_verification(paths, session_id)

    def test_prompt_only_executor_session_tracks_attached_result_without_runtime_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)

            self.assertEqual(prepared["status"]["executor_session_status"]["coding_agent"], "prepared(claude-code)")
            self.assertNotIn("runtime_status", prepared["status"])

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="claude-session-1",
                evidence_refs=["wrapper-open"],
            )
            completed = record_executor_session_result(
                paths,
                session_id,
                result="completed",
                evidence_refs=["claude-summary"],
            )

            self.assertEqual(opened["status"]["coding_agent"], "running(claude-code)")
            self.assertEqual(completed["status"]["coding_agent"], "completed(claude-code)")
            self.assertEqual(completed["status"]["result"], "completed")
            exported = export_runtime(paths, redacted=True)
            self.assertEqual(exported["wrapper_sessions"][0]["executor_session"]["schema_version"], "executor_session/v1")
            self.assertEqual(exported["wrapper_sessions"][0]["executor_session"]["external_session_ref"], "[redacted]")
            self.assertEqual(exported["wrapper_sessions"][0]["executor_session"]["evidence_refs"], ["[redacted]"])
            self.assertEqual(exported["wrapper_sessions"][0]["executor_session"]["summary"], "[redacted]")
            self.assertNotIn(message, json.dumps(exported))
            self.assertNotIn("claude-session-1", json.dumps(exported))
            self.assertNotIn("claude-summary", json.dumps(exported))
            self.assertEqual(validate_runtime(paths)["runs"], [])
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_runtime_executor_session_attachment_records_runtime_start_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "omx-runtime")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            attached = attach_executor_session(
                paths,
                session_id,
                external_session_ref="omx-pane-1",
                evidence_refs=["wrapper-open"],
            )
            status = build_wrapper_session_status(paths, session_id)

            self.assertEqual(attached["status"]["coding_agent"], "running(omx-runtime)")
            self.assertEqual(status["executor_session_status"]["dispatch"], "observed")
            self.assertEqual(status["runtime_observation"]["observed_events"], ["runtime_start"])
            self.assertEqual(status["runtime_observation"]["next_action"], "record_runtime_observation:worktree_creation")
            self.assertEqual(status["executor_session_status"]["result"], "not_observed")
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_non_runtime_session_reports_runtime_observation_not_applicable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            status = build_wrapper_session_status(paths, session_id)

            self.assertEqual(status["runtime_observation"]["applicable"], False)
            self.assertEqual(status["runtime_observation"]["next_action"], "not_applicable")

            write_runtime_observation(
                paths.runtime_wrapper_sessions_dir / session_id,
                {
                    "target_type": "wrapper_session",
                    "target_id": session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "runtime_start",
                    "status": "observed",
                    "summary": "incorrectly attached runtime observation",
                },
            )

            validation = validate_runtime(paths)
            self.assertFalse(validation["ok"])
            errors = "\n".join(error for session in validation["wrapper_sessions"] for error in session["errors"])
            self.assertIn("runtime observations require a runtime_handoff_prepared wrapper session", errors)

    def test_runtime_session_rejects_and_ignores_misattached_observations(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "omx-runtime")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor")

            write_runtime_observation(
                paths.runtime_wrapper_sessions_dir / session_id,
                {
                    "target_type": "run",
                    "target_id": "not-this-session",
                    "runtime_profile": "omx-runtime",
                    "event_type": "runtime_start",
                    "status": "observed",
                    "summary": "misattached runtime observation",
                },
            )

            status = build_wrapper_session_status(paths, session_id)
            self.assertEqual(status["runtime_observation"]["observed_events"], [])
            self.assertEqual(status["runtime_observation"]["next_action"], "record_runtime_observation:runtime_start")

            validation = validate_runtime(paths)
            self.assertFalse(validation["ok"])
            errors = "\n".join(error for session in validation["wrapper_sessions"] for error in session["errors"])
            self.assertIn("target_type must match containing target 'wrapper_session'", errors)
            self.assertIn(f"target_id must match containing target '{session_id}'", errors)

    def test_export_runtime_includes_wrapper_sessions_without_raw_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")

            exported = export_runtime(paths, redacted=True)

            self.assertTrue(exported["redacted"])
            self.assertEqual(len(exported["wrapper_sessions"]), 1)
            self.assertNotIn(message, json.dumps(exported))

    def test_runtime_validation_rejects_wrong_linked_run_type(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session = dict(started["session"])
            run = create_run(paths, {"skill": "plan", "harness": "planning", "trigger": "test"})
            session.update(
                {
                    "status": "handoff_prepared",
                    "decision": "plan_accepted",
                    "work_owner_mode": "external_executor",
                    "selected_executor_profile": "codex",
                    "dispatch_policy": "ask_before_dispatch",
                    "current_run_id": run["run_id"],
                }
            )
            write_wrapper_session(paths, session)

            validation = validate_runtime(paths)

            self.assertFalse(validation["ok"])
            errors = "\n".join(validation["wrapper_sessions"][0]["errors"])
            self.assertIn("prepared coding delegation run", errors)

    def test_wrapper_session_validator_rejects_authority_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session = dict(started["session"])
            session["authority"] = {**session["authority"], "session_owns": ["chat_continuity", "plan_decision"]}

            errors = validate_wrapper_session_record(session)

            self.assertIn("wrapper_session authority.session_owns must match the wrapper session authority contract", errors)

    def test_src_does_not_add_network_or_platform_sdk_imports(self) -> None:
        banned = (
            "import requests",
            "import httpx",
            "import openai",
            "import discord",
            "import slack_sdk",
            "from requests",
            "from httpx",
            "from openai",
            "from discord",
            "from slack_sdk",
        )
        source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path("src").rglob("*.py")))

        for needle in banned:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, source)


if __name__ == "__main__":
    unittest.main()
