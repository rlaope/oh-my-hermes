from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package
from _platform_support import requires_domain_intelligence_store

load_local_package()
from omh.coding_lifecycle import record_codex_dispatch, record_codex_result, record_codex_verification, start_codex_delegation_lifecycle
from omh.codex_progress import summarize_codex_jsonl_text
from omh.coding.executor_local_workflow import build_executor_local_workflow
from omh.coding.executor_capability_snapshots import (
    build_executor_capability_snapshot,
    executor_capability_snapshot_path,
    write_executor_capability_snapshot,
)
from omh.coding_delegation import build_coding_delegation_payload
from project_identity_fixture import memory_paths as resolve_paths
from omh.memory import capture_project_memory_candidate
from omh.profiles.setup import write_setup_profile
from omh.runtime_artifacts import (
    create_run,
    export_runtime,
    validate_runtime,
    write_ci_record,
    write_merge_record,
    write_review_record,
    write_runtime_observation,
)
from omh.record_revision import StaleRecordMutation
from omh.runtime_records import validate_wrapper_session_record
from omh.wrapper.executor_sessions import (
    ExecutorSessionError,
    attach_executor_session,
    build_executor_session_actions,
    build_executor_session_status,
    open_executor_session,
    record_executor_session_result,
    request_executor_session_verification,
    validate_executor_session_record,
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
from omh.wrapper_contract import build_chat_interaction_payload


class DomainContextSessionBindingTests(unittest.TestCase):
    @requires_domain_intelligence_store
    def test_each_turn_uses_a_fresh_host_binding_without_cross_project_reuse(self) -> None:
        from omh.workflows.domain_project_context import bind_plugin_project
        from domain_project_context_helpers import domain_store as _domain_store
        from test_domain_routing_context import _approve_profile, _repository

        with TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            first_root = _repository(base / "first" / "same-name")
            second_root = _repository(base / "second" / "same-name")
            _approve_profile(first_root, domain_id="sales", phrase="feels off")
            _domain_store(second_root)
            first_paths = resolve_paths(first_root / ".omh", first_root / ".hermes")
            second_paths = resolve_paths(second_root / ".omh", second_root / ".hermes")

            first = create_or_resume_wrapper_session(
                first_paths,
                "something feels off",
                source="discord",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1"},
                _host_project_binding_factory=lambda: bind_plugin_project(
                    {"project_root": str(first_root)}
                ),
            )
            second = create_or_resume_wrapper_session(
                second_paths,
                "something feels off",
                source="discord",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1"},
                _host_project_binding_factory=lambda: bind_plugin_project(
                    {"project_root": str(second_root)}
                ),
            )

            self.assertIn("domain_routing_context", first["interaction"])
            self.assertNotIn("domain_routing_context", second["interaction"])
            self.assertEqual(
                set(first["interaction"]["domain_routing_context"]),
                {
                    "schema_version",
                    "workflow_hint",
                    "required_input",
                    "question",
                    "digest",
                    "claim_boundary",
                },
            )
            self.assertEqual(
                json.dumps(first["interaction"]["route"], sort_keys=True, separators=(",", ":")),
                json.dumps(second["interaction"]["route"], sort_keys=True, separators=(",", ":")),
            )
            self.assertEqual(
                json.dumps(
                    first["interaction"]["route"].get("candidate_handoff"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    second["interaction"]["route"].get("candidate_handoff"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )


class WrapperSessionTests(unittest.TestCase):
    def test_session_delegate_mode_uses_setup_default_codex_executor_when_available(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="codex")

            started = create_or_resume_wrapper_session(
                paths,
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="hermes",
                mode="delegate",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1"},
            )

        interaction = started["interaction"]
        self.assertEqual(interaction["next_action"], "send_to_executor")
        self.assertEqual(interaction["executor_resolution"]["source"], "setup_profile")
        self.assertEqual(interaction["delegation"]["selected_executor_profile"], "codex")
        self.assertIn("executor_handoff", interaction["delegation"])

    def test_session_start_is_metadata_only_and_resumable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"

            first = create_or_resume_wrapper_session(
                paths,
                message,
                source="hermes",
                source_metadata={
                    "source_event_id": "m1",
                    "channel_ref": "c1",
                    "render_profile": "limited_markdown",
                    "raw": "drop-me",
                },
            )
            second = create_or_resume_wrapper_session(
                paths,
                message,
                source="hermes",
                source_metadata={"source_event_id": "m1", "channel_ref": "c1"},
            )

            session = first["session"]
            self.assertFalse(first["resumed"])
            self.assertTrue(second["resumed"])
            self.assertEqual(session["session_id"], second["session"]["session_id"])
            self.assertEqual(session["session_id"], session_id_for_thread_key("hermes:c1:m1"))
            self.assertEqual(session["status"], "plan_presented")
            self.assertEqual(session["decision"], "none")
            self.assertEqual(session["current_run_id"], "")
            self.assertEqual(session["record_provenance"]["producer"], "wrapper_backend")
            self.assertFalse(session["record_provenance"]["observed_by_host"])
            self.assertEqual(first["status"]["chat_response"]["messenger_rendering"]["render_profile"], "limited_markdown")
            self.assertEqual(
                session["source_metadata"],
                {"source_event_id": "m1", "channel_ref": "c1", "render_profile": "limited_markdown"},
            )
            self.assertNotIn(message, json.dumps(first))
            self.assertEqual(validate_wrapper_session_record(session), [])

    def test_session_status_projects_workspace_and_resume_continuity(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "parallel team refactor with private-token-123"
            source_metadata = {"source_event_id": "continuity-1", "channel_ref": "qa"}

            started = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata=source_metadata,
            )
            session_id = str(started["session"]["session_id"])
            started_revision = started["session"]["record_revision"]
            self.assertIn("continuity_briefing", started["status"]["chat_response"])
            started_continuity = started["status"]["chat_response"]["continuity_briefing"]
            resumed = create_or_resume_wrapper_session(
                paths,
                message,
                source="discord",
                source_metadata=source_metadata,
            )

            self.assertFalse(started["resumed"])
            self.assertTrue(resumed["resumed"])
            self.assertEqual(resumed["session"]["session_id"], session_id)
            self.assertEqual(resumed["session"]["record_revision"], started_revision)
            self.assertEqual(started_continuity["resume"]["status"], "not_started")
            self.assertEqual(
                resumed["status"]["chat_response"]["continuity_briefing"]["resume"]["status"],
                "not_started",
            )

            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            prepared_continuity = prepared["status"]["chat_response"]["continuity_briefing"]
            run_id = str(prepared["session"]["current_run_id"])

            self.assertEqual(
                prepared_continuity["workspace"],
                {"reuse": "blocked", "required": "worktree_required", "current": "unobserved"},
            )
            self.assertEqual(prepared_continuity["resume"]["status"], "not_started")

            record_codex_dispatch(paths, run_id)
            running = build_wrapper_session_status(paths, session_id)
            self.assertEqual(
                running["chat_response"]["continuity_briefing"]["resume"]["status"],
                "reattach",
            )

            record_codex_result(paths, run_id, result="completed", evidence_refs=["local:result"])
            completed = build_wrapper_session_status(paths, session_id)
            completed_continuity = completed["chat_response"]["continuity_briefing"]
            self.assertEqual(completed_continuity["resume"]["status"], "conversation_safe")
            self.assertNotIn(message, json.dumps(completed_continuity))
            self.assertNotIn(session_id, json.dumps(completed_continuity))
            self.assertNotIn("safe", completed_continuity["resume"])

            blocked_message = "risky refactor of src/parser.py with focused regression tests"
            blocked_started = create_or_resume_wrapper_session(
                paths,
                blocked_message,
                source="discord",
                source_metadata={"source_event_id": "continuity-blocked", "channel_ref": "qa"},
            )
            blocked_id = str(blocked_started["session"]["session_id"])
            record_plan_decision(paths, blocked_id, "accept")
            select_wrapper_session_executor(paths, blocked_id, "codex")
            blocked_prepared = prepare_wrapper_session_handoff(paths, blocked_id, blocked_message)
            blocked_run_id = str(blocked_prepared["session"]["current_run_id"])
            record_codex_dispatch(paths, blocked_run_id)
            record_codex_result(paths, blocked_run_id, result="blocked", evidence_refs=["local:blocked"])
            blocked = build_wrapper_session_status(paths, blocked_id)
            self.assertEqual(
                blocked["chat_response"]["continuity_briefing"]["resume"]["status"],
                "blocked",
            )

    def test_session_status_treats_empty_memory_pack_as_not_included(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
            run_id = str(prepared["session"]["current_run_id"])
            coding_path = paths.runtime_runs_dir / run_id / "coding_delegation.json"
            coding = json.loads(coding_path.read_text(encoding="utf-8"))
            coding["executor_handoff"]["memory_recall_pack"] = {}
            coding_path.write_text(json.dumps(coding, sort_keys=True), encoding="utf-8")

            status = build_wrapper_session_status(paths, session_id)
            memory = status["chat_response"]["continuity_briefing"]["memory"]

            self.assertEqual(memory["availability"], "not_included")
            self.assertEqual(memory["included_count"], 0)
            self.assertEqual(memory["excluded_count"], 0)
            self.assertIsNone(memory["truncated"])
            self.assertEqual(memory["freshness"], "not_available")
            self.assertEqual(memory["freshness_warning_count"], 0)
            self.assertNotIn("private-token-123", memory["claim_boundary"])
            self.assertEqual(
                [line["domain"] for line in status["chat_response"]["continuity_briefing"]["lines"]],
                ["workspace", "resume", "memory"],
            )

            coding["executor_handoff"]["memory_recall_pack"] = {
                "schema_version": "bad",
                "claim_boundary": "private-token-123",
            }
            coding_path.write_text(json.dumps(coding, sort_keys=True), encoding="utf-8")
            malformed_status = build_wrapper_session_status(paths, session_id)
            malformed = malformed_status["chat_response"]["continuity_briefing"]["memory"]

            self.assertEqual(malformed["availability"], "unknown")
            self.assertIsNone(malformed["included_count"])
            self.assertIsNone(malformed["excluded_count"])
            self.assertIsNone(malformed["truncated"])
            self.assertEqual(malformed["freshness"], "unknown")
            self.assertIsNone(malformed["freshness_warning_count"])
            self.assertNotIn("private-token-123", json.dumps(malformed))

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
            self.assertTrue(accepted["status"]["chat_response"]["headline"].startswith("[omh] handoff - "))
            self.assertEqual(accepted["status"]["chat_response"]["usage_trace"]["visible_prefix"], "[omh] handoff")
            self.assertEqual(accepted["status"]["chat_response"]["messenger_rendering"]["prefix_policy"]["default"], "once_per_response_first_line")

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

    def test_coding_briefing_is_metadata_only_and_keeps_cards_compact(self) -> None:
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
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            context_pack = {
                "schema_version": "handoff_context_pack/v1",
                "executor_target": "codex",
                "session_id": session_id,
                "scope": {"kind": "project", "ref": "default"},
                "source_refs": [{"source": "omh_memory", "truth_level": "approved_context", "precedence": 60, "item_count": 1}],
                "included_context": [
                    {
                        "item_id": "ctx-1",
                        "key": "default_executor",
                        "summary": "Use Codex by default for coding work.",
                        "source": "omh_memory",
                        "truth_level": "approved_context",
                        "scope": {"kind": "project", "ref": "default"},
                    }
                ],
                "excluded_context": [],
                "blocked_by_conflicts": [],
                "redaction_policy": "metadata_only",
                "claim_boundary": "Context pack is metadata only.",
            }

            prepared = prepare_wrapper_session_handoff(paths, session_id, message, context_pack=context_pack)
            status = prepared["status"]
            briefing = status["coding_briefing"]

            self.assertEqual(briefing["schema_version"], "coding_briefing/v1")
            self.assertEqual(
                set(briefing),
                {
                    "schema_version",
                    "session_id",
                    "run_id",
                    "thread_key",
                    "headline",
                    "narrative",
                    "current_state",
                    "original_context",
                    "work_summary",
                    "progress",
                    "runtime_milestones",
                    "runtime_milestone_gaps",
                    "evidence_summary",
                    "pending_gaps",
                    "blockers",
                    "signal",
                    "next_action",
                    "user_facing_lines",
                    "claim_boundary",
                },
            )
            self.assertEqual(briefing["original_context"]["message"]["sha256"], hashlib.sha256(message.encode("utf-8")).hexdigest())
            self.assertEqual(briefing["original_context"]["message"]["length"], len(message))
            self.assertFalse(briefing["original_context"]["message"]["raw_text_persisted"])
            self.assertFalse(briefing["original_context"]["deep_interview"]["persisted"])
            self.assertIn("execution_brief", briefing["work_summary"]["handoff_contract"])
            self.assertIn("task_prompt_contract", briefing["work_summary"]["handoff_contract"])
            self.assertIn("session_observation_contract", briefing["work_summary"]["handoff_contract"])
            self.assertIn("local_capability_report_contract", briefing["work_summary"]["handoff_contract"])
            self.assertIn("evidence_contract", briefing["work_summary"]["handoff_contract"])
            task_contract = briefing["work_summary"]["handoff_contract"]["task_prompt_contract"]
            self.assertEqual(task_contract["schema_version"], "executor_task_prompt_contract/v1")
            self.assertEqual(task_contract["required_sections"], ["Goal", "Do", "Don't", "Expected result", "Test"])
            self.assertEqual(task_contract["status"], "prepared_not_observed")
            session_contract = briefing["work_summary"]["handoff_contract"]["session_observation_contract"]
            self.assertEqual(session_contract["schema_version"], "codex_session_observation_contract/v1")
            self.assertIn("waitingOnApproval", session_contract["blocker_statuses"])
            self.assertIn("waitingOnUserInput", session_contract["blocker_statuses"])
            self.assertIn("not live telemetry", session_contract["claim_boundary"])
            capability_report = briefing["work_summary"]["handoff_contract"]["local_capability_report_contract"]
            self.assertEqual(capability_report["schema_version"], "executor_local_capability_report_contract/v1")
            self.assertEqual(capability_report["profile"], "codex")
            self.assertIn("local_capabilities_used", capability_report["required_fields"])
            snapshot = prepared["handoff"]["coding_delegation"]["executor_handoff"]["executor_capability_snapshot"]
            self.assertEqual(snapshot["schema_version"], "executor_capability_snapshot/v3")
            self.assertEqual(snapshot["executor"], "codex")
            self.assertEqual(snapshot["capabilities"]["worktree_isolation"]["status"], "prepared")
            self.assertFalse(any(capability["status"] == "host_observed" for capability in snapshot["capabilities"].values()))
            self.assertEqual(prepared["status"]["executor_session_status"]["executor_capability_snapshot"], snapshot)
            self.assertEqual(briefing["work_summary"]["handoff_contract"]["context_pack"]["included_context_count"], 1)
            self.assertNotIn("included_context", briefing["work_summary"]["handoff_contract"]["context_pack"])
            self.assertNotIn(message, json.dumps(briefing))
            self.assertNotIn("private-token-123", json.dumps(briefing))
            self.assertIn("coding_briefing", status["chat_response"])
            self.assertEqual(status["chat_response"]["coding_briefing"]["schema_version"], "coding_briefing/v1")
            self.assertEqual(
                set(status["chat_response"]["coding_briefing"]),
                {"schema_version", "headline", "lines", "next_action", "pending_gaps", "blockers", "signal", "claim_boundary"},
            )
            self.assertNotIn("progress", status["chat_response"]["coding_briefing"])
            self.assertNotIn("coding_briefing", status["status_card"])

    def test_prompt_only_coding_briefing_reports_prepared_not_dispatched(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")

            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            briefing = prepared["status"]["coding_briefing"]
            states = {step["id"]: step["state"] for step in briefing["progress"]}

            self.assertEqual(briefing["run_id"], "")
            self.assertEqual(briefing["current_state"]["selected_executor_profile"], "claude-code")
            self.assertEqual(briefing["work_summary"]["handoff_schema_version"], "coding_prompt_handoff/v1")
            self.assertNotIn("executor_local_workflow", briefing["work_summary"]["handoff_contract"])
            self.assertEqual(
                briefing["work_summary"]["handoff_contract"]["task_prompt_contract"]["schema_version"],
                "executor_task_prompt_contract/v1",
            )
            session_contract = briefing["work_summary"]["handoff_contract"]["session_observation_contract"]
            self.assertEqual(session_contract["schema_version"], "claude_code_session_observation_contract/v1")
            self.assertEqual(session_contract["profile"], "claude-code")
            self.assertIn("tool_use_status", session_contract["status_fields"])
            capability_report = briefing["work_summary"]["handoff_contract"]["local_capability_report_contract"]
            self.assertEqual(capability_report["schema_version"], "executor_local_capability_report_contract/v1")
            self.assertEqual(capability_report["profile"], "claude-code")
            self.assertIn("local_capability_fallback_reason", capability_report["required_fields"])
            snapshot = prepared["handoff"]["prompt_handoff"]["executor_capability_snapshot"]
            self.assertEqual(snapshot["executor"], "claude-code")
            self.assertEqual(snapshot["capabilities"]["worktree_isolation"]["status"], "prepared")
            self.assertEqual(prepared["status"]["executor_session_status"]["executor_capability_snapshot"], snapshot)
            self.assertEqual(states["handoff"], "complete")
            self.assertEqual(states["dispatch"], "pending")
            self.assertIn("dispatch", briefing["pending_gaps"])
            self.assertIn("prompt-only handoff", json.dumps(briefing["user_facing_lines"]))

    def test_executor_local_workflow_projects_to_briefing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "$ultrawork fix the focused parser regression with tests"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")

            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            binding = prepared["handoff"]["coding_delegation"]["executor_handoff"]["executor_local_workflow"]
            briefing = prepared["status"]["coding_briefing"]
            work_summary = briefing["work_summary"]

            self.assertEqual(work_summary["handoff_contract"]["executor_local_workflow"], binding)
            self.assertEqual(binding["profile"], "codex")
            self.assertEqual(binding["candidate"]["skill_id"], binding["routed_workflow"])
            self.assertEqual(binding["status"], "unknown")
            self.assertEqual(binding["dispatchability"]["reason"], "availability_not_observed")
            self.assertEqual({step["id"]: step["state"] for step in briefing["progress"]}["dispatch"], "pending")

    def test_local_workflow_direct_route_wrapper_replay_parity(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            snapshot = build_executor_capability_snapshot(
                executor="codex",
                recorded_at="2026-08-02T00:00:01Z",
                capabilities={
                    "local_workflow": {
                        "status": "host_observed",
                        "scope": {
                            "profile": "codex",
                            "skill_id": "ai-slop-cleaner",
                            "environment": "test_host",
                        },
                        "evidence_ref": "operator:wrapper-parity",
                        "observed_at": "2026-08-02T00:00:00Z",
                    }
                },
            )
            snapshot_path = executor_capability_snapshot_path(
                paths.omh_home / "coding" / "executor-capability-snapshots",
                "codex",
            )
            write_executor_capability_snapshot(snapshot_path, snapshot)
            message = "$ai-slop-cleaner clean delegation code"

            direct = build_coding_delegation_payload(
                message,
                executor_target="codex",
                capability_snapshot_directory=snapshot_path.parent,
            )["executor_handoff"]["executor_local_workflow"]
            routed_payload = build_chat_interaction_payload(
                message,
                source="discord",
                mode="delegate",
                executor_target="codex",
                paths=paths,
            )
            routed = routed_payload["delegation"]["executor_handoff"]["executor_local_workflow"]

            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            wrapper = prepared["handoff"]["coding_delegation"]["executor_handoff"]["executor_local_workflow"]
            replay = build_wrapper_session_status(paths, session_id)["coding_briefing"]["work_summary"]["handoff_contract"][
                "executor_local_workflow"
            ]

            self.assertEqual(routed_payload["route"]["selected_skill"], "ai-slop-cleaner")
            self.assertEqual(direct, routed)
            self.assertEqual(routed, wrapper)
            self.assertEqual(wrapper, replay)
            self.assertEqual(direct["status"], "observed_available")
            self.assertTrue(direct["dispatchability"]["candidate_invocation_dispatchable"])
            self.assertEqual(direct["availability"]["evidence_ref"], "operator:wrapper-parity")

    def test_local_workflow_projection_excludes_raw_metadata(self) -> None:
        binding = build_executor_local_workflow(
            profile="codex",
            routed_workflow="ultrawork",
            parent_handoff_dispatchable=True,
        )
        assert binding is not None
        sensitive_binding = deepcopy(binding)
        sensitive_binding["raw_prompt"] = "private-token-123"
        sensitive_binding["local_path"] = "/private/secret/repository"
        sensitive_binding["evidence_contents"] = "transcript-content"
        sensitive_binding["skill_body"] = "hidden-skill-body"

        from omh.wrapper.briefing import build_coding_briefing

        briefing = build_coding_briefing(
            {
                "session_id": "ws-sensitive",
                "thread_key": "discord:sensitive",
                "status": "prompt_handoff_prepared",
                "selected_executor_profile": "codex",
                "prompt_handoff": {
                    "schema_version": "coding_prompt_handoff/v1",
                    "selected_executor_profile": "codex",
                    "executor_local_workflow": sensitive_binding,
                },
            }
        )
        serialized = json.dumps(briefing, sort_keys=True)

        self.assertNotIn("executor_local_workflow", briefing["work_summary"]["handoff_contract"])
        for secret in ("private-token-123", "/private/secret/repository", "transcript-content", "hidden-skill-body"):
            self.assertNotIn(secret, serialized)
        self.assertEqual({step["id"]: step["state"] for step in briefing["progress"]}["dispatch"], "pending")

    def test_wrapper_status_excludes_forged_local_workflow_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "$ultrawork complete the goal"
            started = create_or_resume_wrapper_session(paths, message, source="slack")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "hermes")
            prepare_wrapper_session_handoff(paths, session_id, message)
            session_path = paths.runtime_wrapper_sessions_dir / session_id / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            session["runtime_handoff"]["executor_local_workflow"]["raw_prompt"] = "private-token-123"
            session_path.write_text(json.dumps(session, sort_keys=True), encoding="utf-8")

            replay = build_wrapper_session_status(paths, session_id)
            serialized = json.dumps(replay, sort_keys=True)

            self.assertEqual(replay["runtime_handoff"], {})
            self.assertNotIn("private-token-123", serialized)
            self.assertNotIn(
                "executor_local_workflow",
                replay["coding_briefing"]["work_summary"]["handoff_contract"],
            )

    def test_prompt_briefing_keeps_bounded_replay_evidence_prepared_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths,
                "Run regression tests before risky refactors",
                record_type="procedure",
                tags=["risky", "refactor"],
            )
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")

            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            replay_evidence = prepared["status"]["coding_briefing"]["work_summary"]["handoff_contract"]["memory_recall_pack"]["replay_evidence"]

            self.assertTrue(replay_evidence["prepared_not_observed"])
            self.assertEqual(replay_evidence["included"][0]["reason_code"], "eligible")
            self.assertIn("not evidence an executor or model used memory", replay_evidence["claim_boundary"])

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
            self.assertEqual(prepared["handoff"]["prompt_handoff"]["local_capability_report_contract"]["profile"], "claude-code")
            self.assertEqual(prepared["handoff"]["prompt_handoff"]["session_observation_contract"]["profile"], "claude-code")
            self.assertEqual(prepared["status"]["next_action"], "show_prompt_handoff")
            self.assertEqual(validate_runtime(paths)["runs"], [])
            self.assertTrue(validate_runtime(paths)["ok"])
            session_path = paths.runtime_wrapper_sessions_dir / session_id / "session.json"
            self.assertNotIn(message, session_path.read_text(encoding="utf-8"))

    @staticmethod
    def _session_events(paths, session_id: str) -> list[dict]:
        events_path = paths.runtime_wrapper_sessions_dir / session_id / "events.jsonl"
        if not events_path.exists():
            return []
        return [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _prompt_only_prepared_session(self, paths, message: str) -> str:
        started = create_or_resume_wrapper_session(paths, message, source="discord")
        session_id = str(started["session"]["session_id"])
        record_plan_decision(paths, session_id, "accept")
        select_wrapper_session_executor(paths, session_id, "claude-code")
        prepare_wrapper_session_handoff(paths, session_id, message)
        return session_id

    def test_same_message_retry_and_empty_message_reserve_without_new_events(self) -> None:
        """Characterization: retries and shows stay idempotent re-serves."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor of the observer summary"
            session_id = self._prompt_only_prepared_session(paths, message)
            events_before = len(self._session_events(paths, session_id))

            retried = prepare_wrapper_session_handoff(paths, session_id, message)
            shown = prepare_wrapper_session_handoff(paths, session_id, "")

            self.assertEqual(retried["session"]["status"], "prompt_handoff_prepared")
            self.assertEqual(shown["session"]["status"], "prompt_handoff_prepared")
            self.assertEqual(
                shown["handoff"]["prompt_handoff"]["schema_version"], "coding_prompt_handoff/v1"
            )
            self.assertEqual(len(self._session_events(paths, session_id)), events_before)

    def test_session_restore_prompt_handoff_header_uses_the_executor_label(self) -> None:
        # Parity with the contract path: the same prepared handoff must render
        # "Prepared prompt for Claude Code:" (executor_label form) on the
        # session-restore path too, never the raw profile id "claude-code".
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor of the observer summary"
            session_id = self._prompt_only_prepared_session(paths, message)

            status = build_wrapper_session_status(paths, session_id)

            body = str(status["chat_response"]["body"])
            self.assertIn("Prepared prompt for Claude Code:", body)
            self.assertNotIn("Prepared prompt for claude-code:", body)

    def test_follow_up_message_reprepares_prompt_only_handoff(self) -> None:
        """Issue #754: a new message on a prepared session must not be dropped."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths, "Regression tests run before merge", record_type="procedure", tags=["tests"]
            )
            first_message = "risky refactor of the observer summary"
            session_id = self._prompt_only_prepared_session(paths, first_message)

            follow_up = "follow-up: add regression tests too"
            prepared = prepare_wrapper_session_handoff(paths, session_id, follow_up)

            self.assertEqual(prepared["session"]["status"], "prompt_handoff_prepared")
            follow_up_sha = hashlib.sha256(follow_up.encode("utf-8")).hexdigest()
            pack = prepared["handoff"]["prompt_handoff"]["memory_recall_pack"]
            self.assertEqual(pack["task_ref"]["sha256"], follow_up_sha)
            prepared_events = [
                event for event in self._session_events(paths, session_id) if event.get("event") == "prompt_handoff_prepared"
            ]
            self.assertEqual(len(prepared_events), 2)
            self.assertEqual(prepared_events[-1]["data"]["message_sha256"], follow_up_sha)

    def test_follow_up_message_links_new_codex_run_and_keeps_previous_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            first_message = "risky refactor of the observer summary"
            started = create_or_resume_wrapper_session(paths, first_message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            first = prepare_wrapper_session_handoff(paths, session_id, first_message)
            first_run_id = str(first["session"]["current_run_id"])
            self.assertTrue(first_run_id)

            follow_up = "follow-up: add regression tests too"
            second = prepare_wrapper_session_handoff(paths, session_id, follow_up)

            second_run_id = str(second["session"]["current_run_id"])
            self.assertTrue(second_run_id)
            self.assertNotEqual(second_run_id, first_run_id)
            follow_up_sha = hashlib.sha256(follow_up.encode("utf-8")).hexdigest()
            new_coding = json.loads(
                (paths.runtime_runs_dir / second_run_id / "coding_delegation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(new_coding["message_sha256"], follow_up_sha)
            self.assertTrue((paths.runtime_runs_dir / first_run_id / "coding_delegation.json").exists())

            retried = prepare_wrapper_session_handoff(paths, session_id, follow_up)
            self.assertEqual(str(retried["session"]["current_run_id"]), second_run_id)

    def test_follow_up_message_reprepares_runtime_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            first_message = "risky refactor of the observer summary"
            started = create_or_resume_wrapper_session(paths, first_message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "omx-runtime")
            prepare_wrapper_session_handoff(paths, session_id, first_message)

            follow_up = "follow-up: add regression tests too"
            prepared = prepare_wrapper_session_handoff(paths, session_id, follow_up)

            self.assertEqual(prepared["session"]["status"], "runtime_handoff_prepared")
            follow_up_sha = hashlib.sha256(follow_up.encode("utf-8")).hexdigest()
            prepared_events = [
                event for event in self._session_events(paths, session_id) if event.get("event") == "runtime_handoff_prepared"
            ]
            self.assertEqual(len(prepared_events), 2)
            self.assertEqual(prepared_events[-1]["data"]["message_sha256"], follow_up_sha)

    def test_write_wrapper_session_preserves_legacy_prompt_handoff_without_local_capability_strategy(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            legacy_session = deepcopy(prepared["session"])
            del legacy_session["prompt_handoff"]["executor_local_capability_strategy"]

            rewritten = write_wrapper_session(paths, legacy_session)

            self.assertNotIn("executor_local_capability_strategy", rewritten["prompt_handoff"])
            self.assertEqual(validate_wrapper_session_record(rewritten), [])
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_write_wrapper_session_preserves_legacy_prompt_handoff_without_local_capability_report_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "claude-code")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            legacy_session = deepcopy(prepared["session"])
            del legacy_session["prompt_handoff"]["local_capability_report_contract"]

            rewritten = write_wrapper_session(paths, legacy_session)

            self.assertNotIn("local_capability_report_contract", rewritten["prompt_handoff"])
            self.assertEqual(validate_wrapper_session_record(rewritten), [])
            self.assertTrue(validate_runtime(paths)["ok"])

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
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["local_capability_report_contract"]["profile"], "hermes")
            snapshot = prepared["handoff"]["runtime_handoff"]["executor_capability_snapshot"]
            self.assertEqual(snapshot["executor"], "hermes")
            self.assertEqual(snapshot["capabilities"]["worktree_isolation"]["status"], "prepared")
            self.assertEqual(prepared["status"]["executor_session_status"]["executor_capability_snapshot"], snapshot)
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["runtime_family"], "omh")
            self.assertTrue(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["supports_team_swarm"])
            self.assertTrue(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["supports_tmux_workers"])
            self.assertTrue(prepared["handoff"]["runtime_handoff"]["runtime_profile"]["supports_worktree_guidance"])
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["hermes_coding_team_path"]["schema_version"], "hermes_coding_team_path/v1")
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["hermes_coding_harness"]["schema_version"], "hermes_coding_harness/v1")
            self.assertEqual(prepared["handoff"]["runtime_handoff"]["hermes_coding_harness"]["status"], "prepared_not_observed")
            self.assertEqual(prepared["status"]["hermes_coding_harness"]["selected_owner"], "hermes")
            self.assertEqual(prepared["status"]["hermes_coding_harness"]["pr_preparation"]["status"], "pending")
            self.assertIn("GitHub PR creation", prepared["status"]["hermes_coding_harness"]["pr_preparation"]["not_observed"])
            self.assertEqual(
                prepared["status"]["coding_briefing"]["work_summary"]["handoff_contract"]["coding_team_path"]["status"],
                "prepared_not_observed",
            )
            self.assertEqual(
                prepared["status"]["coding_briefing"]["work_summary"]["handoff_contract"]["local_capability_report_contract"]["profile"],
                "hermes",
            )
            self.assertEqual(prepared["status"]["coding_briefing"]["runtime_milestones"][0]["id"], "runtime_start")
            self.assertEqual(prepared["status"]["coding_briefing"]["runtime_milestones"][0]["state"], "pending")
            prepared_actions = {action["id"] for action in prepared["status"]["chat_response"]["actions"]}
            self.assertIn("show_coding_team_path", prepared_actions)
            self.assertIn("start_hermes_coding", prepared_actions)
            self.assertIn("record_runtime_observation", prepared_actions)
            self.assertEqual(prepared["status"]["next_action"], "show_runtime_handoff")
            self.assertEqual(validate_runtime(paths)["runs"], [])

    def test_write_wrapper_session_preserves_legacy_runtime_handoff_without_local_capability_strategy(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "hermes")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            legacy_session = deepcopy(prepared["session"])
            del legacy_session["runtime_handoff"]["executor_local_capability_strategy"]

            rewritten = write_wrapper_session(paths, legacy_session)

            self.assertNotIn("executor_local_capability_strategy", rewritten["runtime_handoff"])
            self.assertEqual(validate_wrapper_session_record(rewritten), [])
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_write_wrapper_session_preserves_legacy_runtime_handoff_without_local_capability_report_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "hermes")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)
            legacy_session = deepcopy(prepared["session"])
            del legacy_session["runtime_handoff"]["local_capability_report_contract"]

            rewritten = write_wrapper_session(paths, legacy_session)

            self.assertNotIn("local_capability_report_contract", rewritten["runtime_handoff"])
            self.assertEqual(validate_wrapper_session_record(rewritten), [])
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_hermes_coding_team_path_status_uses_runtime_observations(self) -> None:
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
                    "summary": "Hermes coding skill path started",
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
                    "summary": "Hermes assigned worker lane 1",
                    "worker_ref": "hermes-lane-1",
                },
            )

            status = build_wrapper_session_status(paths, session_id)
            milestones = {item["id"]: item["state"] for item in status["coding_briefing"]["runtime_milestones"]}
            harness = status["hermes_coding_harness"]
            harness_stages = {item["id"]: item["state"] for item in harness["workflow_graph"]}

            self.assertEqual(status["coding_briefing"]["current_state"]["coding_agent"], "running(hermes)")
            self.assertEqual(harness["status"], "in_progress")
            self.assertEqual(harness["start_mode"], "team")
            self.assertEqual(harness_stages["build"], "pending")
            self.assertEqual(harness_stages["review"], "pending")
            self.assertIn("runtime_observation:verification", harness["verification_matrix"]["missing_evidence"])
            lines = "\n".join(status["coding_briefing"]["user_facing_lines"])
            # The rendered words, not the event ids: the ids stay in
            # `runtime_milestones[]` below, which is what a parser reads.
            self.assertIn("runtime start", lines)
            self.assertIn("worker dispatch", lines)
            self.assertIn("Hermes team path", lines)
            self.assertIn("remaining:", lines)
            self.assertNotIn("runtime_start", lines)
            self.assertEqual(milestones["runtime_start"], "complete")
            self.assertEqual(milestones["worker_dispatch"], "complete")
            for pending_event in (
                "worktree_creation",
                "worker_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ):
                self.assertEqual(milestones[pending_event], "pending")
                self.assertIn(pending_event, status["coding_briefing"]["runtime_milestone_gaps"])
            self.assertIn("executor_result", status["coding_briefing"]["pending_gaps"])
            self.assertIn("Hermes team path — observed:", lines)

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

    def test_pre_handoff_status_does_not_surface_executor_buttons(self) -> None:
        forbidden_action_ids = {
            "open_executor_session",
            "attach_executor_session",
            "record_executor_completed",
            "record_executor_blocked",
            "record_executor_failed",
            "ask_hermes_verify",
        }
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])

            started_status = build_wrapper_session_status(paths, session_id)
            accepted = record_plan_decision(paths, session_id, "accept")
            accepted_status = accepted["status"]

            for status in (started_status, accepted_status):
                card = status["status_card"]
                chat_response = status["chat_response"]
                self.assertEqual(card["executor_next_action"], "show_status")
                self.assertEqual(card["executor_next_action_label"], "Show status")
                self.assertEqual(card["executor_actions"], [])
                self.assertTrue(forbidden_action_ids.isdisjoint({action["id"] for action in chat_response["actions"]}))
                self.assertTrue(forbidden_action_ids.isdisjoint({action["id"] for action in status["executor_session_status"]["actions"]}))
                self.assertNotIn("Open Unselected executor", json.dumps(status))

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
            self.assertEqual(prepared_status["workspace_isolation"]["strategy"], "worktree_recommended")
            self.assertEqual(prepared_status["workspace_isolation"]["status"], "prepared_not_observed")
            self.assertEqual(prepared_status["dispatch"], "not_observed")
            self.assertEqual(prepared_status["result"], "not_observed")
            self.assertTrue(prepared_actions["prepare_worktree"]["enabled"])
            self.assertEqual(prepared_actions["prepare_worktree"]["label"], "Prepare worktree")
            self.assertEqual(prepared_actions["prepare_worktree"]["style"], "primary")
            self.assertTrue(prepared_actions["open_executor_session"]["enabled"])
            self.assertEqual(prepared_actions["open_executor_session"]["label"], "Start Codex session")
            self.assertEqual(prepared_actions["open_executor_session"]["style"], "secondary")
            codex_launch = prepared_actions["open_executor_session"]["payload"]["launch"]
            self.assertEqual(codex_launch["schema_version"], "executor_launch/v1")
            self.assertEqual(codex_launch["session_start_owner"], "hermes_or_wrapper")
            self.assertEqual(codex_launch["decision_owner"], "hermes_agent")
            self.assertEqual(codex_launch["backend_action_owner"], "wrapper")
            self.assertEqual(codex_launch["configured_executor_profile"], "codex")
            self.assertTrue(codex_launch["ui_only"])
            self.assertTrue(codex_launch["terminal_launch_available"])
            self.assertEqual(codex_launch["execution_policy"], "copyable_instruction_only")
            self.assertEqual(codex_launch["session_start_capability"], "terminal_command_available")
            self.assertTrue(codex_launch["not_backend_execution"])
            self.assertTrue(codex_launch["not_omh_backend_execution"])
            self.assertEqual(codex_launch["workspace_isolation"]["strategy"], "worktree_recommended")
            self.assertIn("Prefer an isolated worktree", codex_launch["workspace_hint"])
            self.assertEqual(codex_launch["command_templates"][0]["argv_template"], ["codex", "{executor_prompt}"])
            self.assertEqual(codex_launch["command_templates"][0]["shell_command_template"], "codex {executor_prompt_shell_quoted}")
            self.assertEqual(codex_launch["command_templates"][1]["argv_template"], ["codex", "--cd", "{workspace_path}", "{executor_prompt}"])
            self.assertEqual(codex_launch["command_templates"][1]["shell_command_template"], "codex --cd {workspace_path_shell_quoted} {executor_prompt_shell_quoted}")
            self.assertEqual(codex_launch["command_templates"][2]["argv_template"], ["codex", "exec", "resume", "{codex_session_ref}"])
            self.assertEqual(codex_launch["resume_capability"]["argv_template"], ["codex", "exec", "resume", "{codex_session_ref}"])
            self.assertTrue(codex_launch["resume_capability"]["not_omh_backend_execution"])
            self.assertEqual(codex_launch["after_launch_backend_action"], "open-executor")
            self.assertIn("not proof of execution", codex_launch["claim_boundary"])
            self.assertEqual(prepared_actions["attach_executor_session"]["label"], "Attach coding session")
            self.assertEqual(prepared_actions["attach_executor_session"]["payload"]["input_schema"]["required"], ["external_session_ref"])
            self.assertIn("open_executor_session", {action["id"] for action in prepared["status"]["chat_response"]["actions"]})
            self.assertEqual(prepared["status"]["status_card"]["executor_session_status"]["coding_agent"], "prepared(codex)")
            self.assertEqual(prepared["status"]["status_card"]["executor_next_action_label"], "Prepare worktree")
            self.assertIn("Coding agent is prepared in Codex.", prepared_status["display_status_lines"])
            self.assertIn("Workspace isolation is recommended before starting the coding session.", prepared_status["display_status_lines"])
            self.assertIn("open_executor_session", {action["id"] for action in prepared["status"]["status_card"]["executor_actions"]})
            self.assertIn("prepare_worktree", {action["id"] for action in prepared["status"]["status_card"]["executor_actions"]})
            with self.assertRaisesRegex(ExecutorSessionError, "requires --observed"):
                open_executor_session(paths, session_id, external_session_ref="codex-thread-1")

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-1",
                codex_session_ref="codex-session-1",
                codex_thread_ref="codex-thread-1",
                evidence_refs=["discord-button"],
                codex_progress_summary=summarize_codex_jsonl_text(
                    "\n".join(
                        [
                            json.dumps({"type": "tool_call", "tool": "rg", "args": "rg executor_session tests"}),
                            json.dumps({"role": "assistant", "content": "I am inspecting files before editing."}),
                        ]
                    ),
                    evidence_refs=["codex-jsonl"],
                ),
            )

            opened_status = opened["status"]
            self.assertEqual(opened_status["coding_agent"], "running(codex)")
            self.assertEqual(opened_status["executor_session"], "attached")
            self.assertEqual(opened_status["dispatch"], "observed")
            self.assertEqual(opened_status["codex_session"]["session_ref"], "codex-session-1")
            self.assertEqual(opened_status["codex_session"]["thread_ref"], "codex-thread-1")
            self.assertEqual(opened_status["codex_session"]["resume"]["argv_template"], ["codex", "exec", "resume", "codex-session-1"])
            self.assertEqual(opened_status["codex_progress"]["event_count"], 2)
            self.assertIn("Codex is inspecting files/tests.", opened_status["codex_progress"]["observable_activity"])
            self.assertEqual(opened_status["executor_progress"]["binding_id"], f"wrapper_session:{session_id}:codex")
            self.assertEqual(opened_status["executor_progress"]["latest_event"]["event_type"], "repo_exploration")
            self.assertIn("not result", opened_status["executor_progress"]["claim_boundary"])
            self.assertIn("codex-session: observed(codex-session-1)", opened_status["status_lines"])
            self.assertIn("Observed Codex metadata: session codex-session-1, thread codex-thread-1", "\n".join(opened_status["display_status_lines"]))
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
                codex_progress_summary=summarize_codex_jsonl_text(
                    "\n".join(
                        [
                            json.dumps({"type": "tool_call", "command": "python -m unittest tests/test_wrapper_sessions.py"}),
                            json.dumps({"role": "assistant", "content": "Tests passed; waiting on review."}),
                        ]
                    ),
                    evidence_refs=["codex-final-jsonl"],
                ),
            )

            self.assertEqual(completed["status"]["coding_agent"], "completed(codex)")
            self.assertEqual(completed["status"]["result"], "completed")
            self.assertEqual(completed["status"]["codex_progress"]["event_count"], 2)
            self.assertIn("Codex is running tests.", completed["status"]["codex_progress"]["observable_activity"])
            self.assertEqual(completed["status"]["executor_progress"]["state"], "closed")
            self.assertEqual(completed["status"]["executor_progress"]["latest_event"]["event_type"], "executor_completed")
            self.assertEqual(completed["status"]["latest_progress_event"]["event_type"], "targeted_tests_passed")
            self.assertEqual(completed["status"]["latest_progress_event"]["severity"], "success")
            self.assertIn("summary_only", completed["executor_session"]["codex_progress"]["privacy"])
            self.assertEqual(completed["status"]["linked_lifecycle_status"]["next_action"], "record_verification_evidence")
            with self.assertRaisesRegex(ExecutorSessionError, "after executor result is recorded"):
                attach_executor_session(paths, session_id, external_session_ref="codex-thread-2")

            verify_request = request_executor_session_verification(paths, session_id)

            self.assertEqual(verify_request["status"]["verification"], "requested")
            status_after_verify_request = build_wrapper_session_status(paths, session_id)
            briefing = status_after_verify_request["coding_briefing"]
            self.assertEqual(status_after_verify_request["status_card"]["latest_progress_event"]["event_type"], "targeted_tests_passed")
            states = {step["id"]: step["state"] for step in briefing["progress"]}
            self.assertEqual(states["executor_result"], "complete")
            self.assertEqual(states["verification"], "in_progress")
            self.assertIn("verification", briefing["pending_gaps"])
            self.assertIn("verification evidence is still needed", briefing["headline"])
            self.assertEqual(validate_runtime(paths)["ok"], True)

    def test_executor_session_status_bounds_oversized_wrapper_summaries(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            raw_tool_output = "raw codex output " + ("X" * 5000)
            huge_ref = "codex-jsonl:" + ("Y" * 5000)
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepare_wrapper_session_handoff(paths, session_id, message)

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-oversized",
                evidence_refs=[huge_ref, *[f"ref-{index}" for index in range(20)]],
                summary=raw_tool_output,
                codex_session_ref="codex-session-oversized",
                codex_progress_summary=summarize_codex_jsonl_text(
                    json.dumps({"role": "assistant", "content": raw_tool_output}),
                    evidence_refs=[huge_ref],
                    source="codex-oversized.jsonl",
                ),
            )

            status = build_wrapper_session_status(paths, session_id)
            rendered = json.dumps(status)
            session_record = opened["executor_session"]
            status_record = status["executor_session_status"]["record"]

            self.assertLessEqual(len(session_record["summary"]), 240)
            self.assertLessEqual(len(status_record["summary"]), 240)
            self.assertLessEqual(len(session_record["evidence_refs"]), 8)
            self.assertLessEqual(max(len(ref) for ref in session_record["evidence_refs"]), 160)
            self.assertEqual(
                status["executor_session_status"]["codex_progress"]["raw_output_artifact"]["storage_policy"],
                "store_raw_output_as_artifact",
            )
            self.assertNotIn("X" * 1000, rendered)
            self.assertNotIn("Y" * 1000, rendered)
            self.assertIn("raw output should stay in artifacts", status["executor_session_status"]["codex_progress"]["claim_boundary"])

    def test_required_worktree_isolation_disables_open_button_until_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "parallel team refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)

            prepared_status = prepared["status"]["executor_session_status"]
            prepared_actions = {action["id"]: action for action in prepared_status["actions"]}

            self.assertEqual(prepared_status["workspace_isolation"]["strategy"], "worktree_required")
            self.assertEqual(prepared_status["workspace_isolation"]["next_action"], "prepare_worktree")
            self.assertTrue(prepared_actions["prepare_worktree"]["enabled"])
            self.assertEqual(prepared_actions["prepare_worktree"]["style"], "primary")
            self.assertFalse(prepared_actions["open_executor_session"]["enabled"])
            self.assertIn(
                "Workspace isolation is required",
                prepared_actions["open_executor_session"]["payload"]["disabled_reason"],
            )
            self.assertEqual(prepared["status"]["status_card"]["executor_next_action"], "prepare_worktree")
            self.assertIn("Workspace isolation is required before starting the coding session.", prepared_status["display_status_lines"])

    def test_coding_briefing_omits_optional_merge_gaps_when_merge_not_required(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "diagnose installation health"
            lifecycle = start_codex_delegation_lifecycle(paths, message, source="discord")
            coding = lifecycle["coding_delegation"]
            run_id = str(lifecycle["run"]["run_id"])
            thread_key = "discord:c1:m1"
            session_id = session_id_for_thread_key(thread_key)
            write_wrapper_session(
                paths,
                {
                    "session_id": session_id,
                    "thread_key": thread_key,
                    "source": "discord",
                    "source_metadata": {"source_event_id": "m1", "channel_ref": "c1"},
                    "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                    "message_length": len(message),
                    "created_at": "2026-06-15T00:00:00Z",
                    "updated_at": "2026-06-15T00:00:00Z",
                    "status": "handoff_prepared",
                    "decision": "plan_accepted",
                    "route": {
                        "action": "route",
                        "selected_skill": str(coding["recommended_workflow"]),
                        "selected_harness": str(coding["recommended_harness"]),
                        "confidence": "high",
                        "score": 10,
                    },
                    "plan": {
                        "status": "ready",
                        "recommended_workflow": str(coding["recommended_workflow"]),
                        "recommended_harness": str(coding["recommended_harness"]),
                        "coding_delegate_available": "true",
                    },
                    "work_owner_mode": "external_executor",
                    "selected_executor_profile": "codex",
                    "dispatch_policy": "ask_before_dispatch",
                    "prompt_handoff": {},
                    "runtime_handoff": {},
                    "current_run_id": run_id,
                },
            )

            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-summary"])
            record_codex_verification(paths, run_id)

            status = build_wrapper_session_status(paths, session_id)
            briefing = status["coding_briefing"]
            states = {step["id"]: step["state"] for step in briefing["progress"]}

            self.assertEqual(status["runtime_status"]["next_action"], "report_completion_with_evidence")
            self.assertEqual(states["review"], "not_required")
            self.assertEqual(states["ci"], "not_required")
            self.assertEqual(states["merge_ready"], "not_required")
            self.assertEqual(states["merged"], "not_required")
            self.assertNotIn("merge_ready", briefing["pending_gaps"])
            self.assertNotIn("merged", briefing["pending_gaps"])

    def test_coding_briefing_separates_merge_ready_from_merged(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            handoff = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(handoff["session"]["current_run_id"])
            run_dir = paths.runtime_runs_dir / run_id

            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-summary"])
            record_codex_verification(paths, run_id)
            write_review_record(run_dir, {"status": "passed", "reviewer": "code-review", "evidence_refs": ["review"]})
            write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["unit:passed"]})
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["ci"], "summary": "ready"})

            ready_status = build_wrapper_session_status(paths, session_id)
            ready_states = {step["id"]: step["state"] for step in ready_status["coding_briefing"]["progress"]}

            self.assertEqual(ready_status["runtime_status"]["next_action"], "report_merge_ready")
            self.assertEqual(ready_states["merge_ready"], "complete")
            self.assertEqual(ready_states["merged"], "pending")
            self.assertIn("merged", ready_status["coding_briefing"]["pending_gaps"])

            write_merge_record(
                run_dir,
                {
                    "status": "merged",
                    "target_branch": "main",
                    "merge_commit": "abc123",
                    "evidence_refs": ["https://github.example/repo/pull/1"],
                    "summary": "merged",
                },
            )
            merged_status = build_wrapper_session_status(paths, session_id)
            merged_states = {step["id"]: step["state"] for step in merged_status["coding_briefing"]["progress"]}

            self.assertEqual(merged_status["runtime_status"]["next_action"], "report_merged")
            self.assertEqual(merged_states["merge_ready"], "complete")
            self.assertEqual(merged_states["merged"], "complete")
            self.assertNotIn("merged", merged_status["coding_briefing"]["pending_gaps"])

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

    def test_codex_lifecycle_progress_error_does_not_block_dispatch_or_result(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            handoff = prepare_wrapper_session_handoff(paths, session_id, message)
            run_id = str(handoff["session"]["current_run_id"])
            run_dir = paths.runtime_runs_dir / run_id
            progress_dir = run_dir / "executor_progress"
            progress_dir.mkdir(parents=True)
            (progress_dir / "binding.json").write_text(
                json.dumps({"schema_version": "broken", "binding_id": "not-valid"}),
                encoding="utf-8",
            )

            dispatched = record_codex_dispatch(paths, run_id)
            completed = record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-summary"])
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            progress_errors = [event for event in events if event.get("event") == "executor_progress_error"]

            self.assertEqual(dispatched["status"]["execution"]["status"], "not_observed")
            self.assertEqual(completed["status"]["execution"]["status"], "completed")
            self.assertEqual(completed["status"]["executor_progress"]["state"], "diagnostic_error")
            self.assertEqual(completed["status"]["executor_progress"]["progress_error"], "invalid progress binding")
            self.assertGreaterEqual(len(progress_errors), 2)
            self.assertEqual(progress_errors[-1]["level"], "warning")
            self.assertTrue(progress_errors[-1]["data"]["diagnostic_only"])
            self.assertIn("not result", progress_errors[-1]["data"]["claim_boundary"])

    def test_wrapper_session_progress_error_does_not_block_status_rendering(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepare_wrapper_session_handoff(paths, session_id, message)
            open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-1",
                evidence_refs=["discord-button"],
            )
            progress_dir = paths.runtime_wrapper_sessions_dir / session_id / "executor_progress"
            (progress_dir / "binding.json").write_text(
                json.dumps({"schema_version": "broken", "binding_id": "not-valid"}),
                encoding="utf-8",
            )

            status = build_wrapper_session_status(paths, session_id)
            progress_status = status["executor_session_status"]["executor_progress"]

            self.assertEqual(progress_status["state"], "diagnostic_error")
            self.assertTrue(progress_status["diagnostic_only"])
            self.assertEqual(progress_status["progress_error"], "invalid progress binding")
            self.assertIn("not result", progress_status["claim_boundary"])

    def test_wrapper_session_malformed_progress_binding_does_not_block_actions(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepare_wrapper_session_handoff(paths, session_id, message)
            progress_dir = paths.runtime_wrapper_sessions_dir / session_id / "executor_progress"
            progress_dir.mkdir(parents=True)
            (progress_dir / "binding.json").write_text("{not json", encoding="utf-8")

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-1",
                evidence_refs=["discord-button"],
            )
            completed = record_executor_session_result(paths, session_id, result="completed", evidence_refs=["codex-summary"])
            events = [
                json.loads(line)
                for line in (paths.runtime_wrapper_sessions_dir / session_id / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            progress_errors = [event for event in events if event.get("event") == "executor_progress_error"]

            self.assertEqual(opened["status"]["executor_progress"]["state"], "diagnostic_error")
            self.assertEqual(completed["status"]["result"], "completed")
            self.assertEqual(completed["status"]["executor_progress"]["state"], "diagnostic_error")
            self.assertTrue(completed["status"]["executor_progress"]["diagnostic_only"])
            self.assertIn("not result", completed["status"]["executor_progress"]["claim_boundary"])
            self.assertGreaterEqual(len(progress_errors), 2)
            self.assertEqual(progress_errors[-1]["level"], "warning")

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

            wrapper_status = build_wrapper_session_status(paths, session_id)
            status = wrapper_status["executor_session_status"]
            actions = {action["id"]: action for action in status["actions"]}

            self.assertEqual(status["result"], "not_observed")
            self.assertIn("executor_session_error", status)
            self.assertEqual(
                wrapper_status["chat_response"]["continuity_briefing"]["resume"]["status"],
                "blocked",
            )
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
            actions = {action["id"]: action for action in prepared["status"]["executor_session_status"]["actions"]}
            claude_launch = actions["open_executor_session"]["payload"]["launch"]
            self.assertEqual(actions["open_executor_session"]["label"], "Start Claude Code session")
            self.assertEqual(claude_launch["schema_version"], "executor_launch/v1")
            self.assertEqual(claude_launch["session_start_owner"], "hermes_or_wrapper")
            self.assertEqual(claude_launch["backend_action_owner"], "wrapper")
            self.assertEqual(claude_launch["configured_executor_profile"], "claude-code")
            self.assertTrue(claude_launch["ui_only"])
            self.assertTrue(claude_launch["terminal_launch_available"])
            self.assertEqual(claude_launch["execution_policy"], "copyable_instruction_only")
            self.assertEqual(claude_launch["session_start_capability"], "terminal_command_available")
            self.assertTrue(claude_launch["not_backend_execution"])
            self.assertEqual(claude_launch["command_templates"][0]["argv_template"], ["claude", "{executor_prompt}"])
            self.assertEqual(claude_launch["command_templates"][0]["shell_command_template"], "claude {executor_prompt_shell_quoted}")
            self.assertEqual(claude_launch["command_templates"][1]["argv_template"], ["claude", "--add-dir", "{workspace_path}", "{executor_prompt}"])
            self.assertEqual(claude_launch["command_templates"][1]["shell_command_template"], "claude --add-dir {workspace_path_shell_quoted} {executor_prompt_shell_quoted}")

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
            self.assertEqual(opened["status"]["executor_progress"]["binding_id"], f"wrapper_session:{session_id}:claude_code")
            self.assertEqual(opened["status"]["executor_progress"]["latest_event"]["event_type"], "executor_dispatched")
            self.assertEqual(completed["status"]["coding_agent"], "completed(claude-code)")
            self.assertEqual(completed["status"]["result"], "completed")
            self.assertEqual(completed["status"]["executor_progress"]["state"], "closed")
            self.assertEqual(completed["status"]["executor_progress"]["latest_event"]["event_type"], "executor_completed")
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

    def test_non_terminal_executor_launches_are_prompt_only(self) -> None:
        for executor in ("generic", "hermes", "omx-runtime", "omo-runtime", "omc-runtime"):
            with self.subTest(executor=executor):
                actions = {
                    action["id"]: action
                    for action in build_executor_session_actions(
                        {
                            "session_id": "ws-test",
                            "status": "runtime_handoff_prepared",
                            "selected_executor_profile": executor,
                        }
                    )
                }
                launch = actions["open_executor_session"]["payload"]["launch"]

                self.assertTrue(launch["ui_only"])
                self.assertTrue(launch["not_backend_execution"])
                self.assertFalse(launch["terminal_launch_available"])
                self.assertEqual(launch["execution_policy"], "copyable_instruction_only")
                self.assertEqual(launch["session_start_capability"], "prompt_or_runtime_contract_only")
                self.assertEqual(launch["session_start_owner"], "hermes_or_wrapper")
                self.assertEqual(launch["backend_action_owner"], "wrapper")
                self.assertTrue(launch["not_omh_backend_execution"])
                expected_copy_blocks = [
                    {
                        "id": "copy_prompt",
                        "label": f"Copy prompt for {launch['executor_label']}",
                        "text_template": "{executor_prompt}",
                    }
                ]
                self.assertEqual(launch["copy_blocks"], expected_copy_blocks)
                self.assertEqual(launch["command_templates"][0]["launch_mode"], "prompt_only")
                self.assertNotIn("copy_terminal_command", {block["id"] for block in launch["copy_blocks"]})
                self.assertNotIn("shell_command_template", launch["command_templates"][0])
                self.assertNotEqual(launch["command_templates"][0].get("shell_command_template"), "{executor_prompt}")

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

    def test_runtime_handoff_coding_briefing_uses_observed_ladder_events(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "omx-runtime")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
            session_dir = paths.runtime_wrapper_sessions_dir / session_id

            for event_type in (
                "runtime_start",
                "worktree_creation",
                "worker_dispatch",
                "worker_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ):
                payload = {
                    "target_type": "wrapper_session",
                    "target_id": session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": event_type,
                    "status": "observed",
                    "summary": f"{event_type} observed",
                }
                if event_type == "worktree_creation":
                    payload["worktree_ref"] = "worktree-1"
                if event_type in {"worker_dispatch", "worker_result"}:
                    payload["worker_ref"] = "worker-1"
                write_runtime_observation(session_dir, payload)

            status = build_wrapper_session_status(paths, session_id)
            briefing = status["coding_briefing"]
            states = {step["id"]: step["state"] for step in briefing["progress"]}

            continuity = status["chat_response"]["continuity_briefing"]
            self.assertEqual(status["runtime_observation"]["next_action"], "report_runtime_observed")
            self.assertEqual(
                continuity["workspace"],
                {"reuse": "allowed", "required": "none", "current": "isolated_worktree"},
            )
            self.assertEqual(continuity["resume"]["status"], "conversation_safe")
            self.assertNotIn("worktree-1", json.dumps(continuity))
            self.assertNotIn("created", json.dumps(continuity).lower())
            self.assertEqual(states["dispatch"], "complete")
            self.assertEqual(states["executor_result"], "complete")
            self.assertEqual(states["verification"], "complete")
            self.assertEqual(states["review"], "complete")
            self.assertEqual(states["ci"], "complete")
            self.assertEqual(states["merge_ready"], "complete")
            self.assertEqual(states["merged"], "complete")
            self.assertEqual(briefing["current_state"]["coding_agent"], "completed(omx-runtime)")
            self.assertEqual(briefing["headline"], "OMX runtime work is recorded as merged.")
            self.assertEqual(briefing["pending_gaps"], [])

    def test_malformed_runtime_observation_blocks_continuity_without_mutating_session(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "omx-runtime")
            prepare_wrapper_session_handoff(paths, session_id, message)
            session_dir = paths.runtime_wrapper_sessions_dir / session_id
            session_path = session_dir / "session.json"
            session_before = session_path.read_bytes()
            (session_dir / "runtime_observations.jsonl").write_text(
                '{"private":"private-token-123"\n',
                encoding="utf-8",
            )

            status = build_wrapper_session_status(paths, session_id)
            continuity = status["chat_response"]["continuity_briefing"]

            self.assertTrue(status["runtime_observation_errors"])
            self.assertEqual(continuity["resume"]["status"], "blocked")
            self.assertEqual(session_path.read_bytes(), session_before)
            self.assertNotIn("private-token-123", json.dumps(continuity))

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

    def test_export_runtime_run_scope_includes_only_linked_wrapper_sessions(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            first = create_or_resume_wrapper_session(
                paths,
                "risky refactor first scoped runtime fix in src/omh/runtime/artifacts.py",
                source="discord",
                source_metadata={"channel_ref": "c1", "source_event_id": "thread-one"},
            )
            first_id = str(first["session"]["session_id"])
            record_plan_decision(paths, first_id, "accept")
            select_wrapper_session_executor(paths, first_id, "codex")
            first_handoff = prepare_wrapper_session_handoff(
                paths,
                first_id,
                "risky refactor first scoped runtime fix in src/omh/runtime/artifacts.py",
            )
            first_run_id = str(first_handoff["session"]["current_run_id"])

            second = create_or_resume_wrapper_session(
                paths,
                "risky refactor second unrelated runtime fix in src/omh/runtime/artifacts.py",
                source="discord",
                source_metadata={"channel_ref": "c2", "source_event_id": "thread-two"},
            )
            second_id = str(second["session"]["session_id"])
            record_plan_decision(paths, second_id, "accept")
            select_wrapper_session_executor(paths, second_id, "codex")
            second_handoff = prepare_wrapper_session_handoff(
                paths,
                second_id,
                "risky refactor second unrelated runtime fix in src/omh/runtime/artifacts.py",
            )
            second_run_id = str(second_handoff["session"]["current_run_id"])

            exported = export_runtime(paths, redacted=False, run_id=first_run_id)

            self.assertNotEqual(first_run_id, second_run_id)
            self.assertEqual(exported["export"]["run_id"], first_run_id)
            self.assertEqual(exported["export"]["wrapper_session_count"], 1)
            self.assertEqual(exported["wrapper_sessions"][0]["session"]["session_id"], first_id)
            self.assertNotIn(second_id, json.dumps(exported))

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

    def test_prepare_handoff_threads_expected_revision_into_the_writes_it_authorizes(self) -> None:
        # Two prepares rendered at the same revision both used to commit,
        # leaving two run directories: the pre-flight compare never reached
        # the write that actually linked the run.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            selected = select_wrapper_session_executor(paths, session_id, "codex")
            rendered_revision = int(selected["session"]["record_revision"])

            first = prepare_wrapper_session_handoff(
                paths, session_id, "risky refactor one", expected_revision=rendered_revision
            )

            with self.assertRaises(StaleRecordMutation) as caught:
                prepare_wrapper_session_handoff(
                    paths, session_id, "risky refactor two", expected_revision=rendered_revision
                )

            self.assertEqual(caught.exception.expected_revision, rendered_revision)
            runs = sorted(path for path in paths.runtime_runs_dir.glob("*") if path.is_dir())
            self.assertEqual(len(runs), 1)
            self.assertEqual(str(first["session"]["current_run_id"]), runs[0].name)

    def test_prepare_handoff_threads_the_revision_through_the_executor_selection_it_makes(self) -> None:
        # prepare --executor writes twice: the selection and the handoff. The
        # second write must compare against the revision the first produced,
        # not against the one the wrapper rendered, or the guard is dropped
        # exactly where the multi-write path needs it.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            accepted = record_plan_decision(paths, session_id, "accept")
            rendered_revision = int(accepted["session"]["record_revision"])

            prepared = prepare_wrapper_session_handoff(
                paths,
                session_id,
                "risky refactor",
                executor_target="codex",
                expected_revision=rendered_revision,
            )

            self.assertEqual(prepared["session"]["status"], "handoff_prepared")
            self.assertEqual(int(prepared["session"]["record_revision"]), rendered_revision + 2)

    @staticmethod
    def _file_digests(root: Path) -> dict[str, str]:
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_prepare_refused_by_a_concurrent_cancel_writes_nothing_at_all(self) -> None:
        # AC1: a rejected prepare used to leave two new session events and a
        # runtime run directory behind, because the artifacts were created
        # before the guard that refuses ran. Every prepare path is covered:
        # the codex lifecycle path, the runtime-handoff path, and the
        # prompt-only path each create their own side effects.
        for executor_target in ("codex", "hermes", "claude-code"):
            with self.subTest(executor_target=executor_target), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = resolve_paths(root / ".omh", root / ".hermes")
                started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
                session_id = str(started["session"]["session_id"])
                record_plan_decision(paths, session_id, "accept")
                selected = select_wrapper_session_executor(paths, session_id, executor_target)
                stale_revision = int(selected["session"]["record_revision"])
                record_plan_decision(paths, session_id, "cancel")
                before = self._file_digests(root)

                with self.assertRaises(WrapperSessionError):
                    prepare_wrapper_session_handoff(
                        paths, session_id, "risky refactor", expected_revision=stale_revision
                    )

                self.assertEqual(self._file_digests(root), before)

    def test_prepare_refused_by_the_in_lock_revision_compare_writes_nothing_at_all(self) -> None:
        # The same guarantee when the guard that refuses is the revision
        # compare rather than the terminal-status pre-check.
        for executor_target in ("codex", "hermes", "claude-code"):
            with self.subTest(executor_target=executor_target), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = resolve_paths(root / ".omh", root / ".hermes")
                started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
                session_id = str(started["session"]["session_id"])
                record_plan_decision(paths, session_id, "accept")
                selected = select_wrapper_session_executor(paths, session_id, executor_target)
                stale_revision = int(selected["session"]["record_revision"])
                select_wrapper_session_executor(paths, session_id, executor_target)
                before = self._file_digests(root)

                with self.assertRaises(StaleRecordMutation):
                    prepare_wrapper_session_handoff(
                        paths, session_id, "risky refactor", expected_revision=stale_revision
                    )

                self.assertEqual(self._file_digests(root), before)

    def test_retry_with_the_original_revision_and_mutation_id_replays_instead_of_going_stale(self) -> None:
        # The canonical retry: the client timed out, never saw the result, and
        # resends the request it built - original expected_revision, same
        # mutation_id. Checking staleness before replay turned that into a
        # StaleRecordMutation the client could never recover from.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            selected = select_wrapper_session_executor(paths, session_id, "codex")
            rendered_revision = int(selected["session"]["record_revision"])

            first = prepare_wrapper_session_handoff(
                paths,
                session_id,
                "risky refactor",
                expected_revision=rendered_revision,
                mutation_id="prepare-turn-1",
            )
            retry = prepare_wrapper_session_handoff(
                paths,
                session_id,
                "risky refactor",
                expected_revision=rendered_revision,
                mutation_id="prepare-turn-1",
            )

            self.assertFalse(first["replayed"])
            self.assertEqual(
                int(first["session"]["record_revision"]), int(retry["session"]["record_revision"])
            )
            runs = sorted(path for path in paths.runtime_runs_dir.glob("*") if path.is_dir())
            self.assertEqual(len(runs), 1)

    def test_wrapper_session_mutation_ids_accept_connector_style_ids(self) -> None:
        # Same charset rule as goal ledgers and loop cycles: an id derived from
        # an upstream message id must work on every surface, not just this one.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])

            first = record_plan_decision(paths, session_id, "accept", mutation_id="slack:C123/p1700000000.000100")
            second = record_plan_decision(paths, session_id, "accept", mutation_id="slack:C123/p1700000000.000100")

            self.assertFalse(first["replayed"])
            self.assertTrue(second["replayed"])
            self.assertEqual(first["session"]["record_revision"], second["session"]["record_revision"])

    def test_wrapper_session_validator_rejects_bad_revision_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")

            errors = validate_wrapper_session_record({**started["session"], "record_revision": -1})
            applied_errors = validate_wrapper_session_record({**started["session"], "applied_mutations": []})

            self.assertIn("wrapper_session record_revision must be a non-negative integer", errors)
            self.assertIn("wrapper_session applied_mutations must be an object", applied_errors)

    def test_executor_session_validator_rejects_bad_revision_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "risky refactor", source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            prepare_wrapper_session_handoff(paths, session_id, "risky refactor", executor_target="codex")
            record = open_executor_session(paths, session_id)["executor_session"]

            errors = validate_executor_session_record({**record, "record_revision": -1})
            applied_errors = validate_executor_session_record({**record, "applied_mutations": []})

            self.assertIn("executor_session record_revision must be a non-negative integer", errors)
            self.assertIn("executor_session applied_mutations must be an object", applied_errors)

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
