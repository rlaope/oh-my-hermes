from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.codex_progress import summarize_codex_jsonl_text
from omh.paths import resolve_paths
from omh.wrapper.executor_sessions import open_executor_session, record_executor_session_result
from omh.wrapper_sessions import (
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)


class ChatProgressReportingTests(unittest.TestCase):
    def test_codex_session_progress_surfaces_in_status_without_satisfying_result_or_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "codex")
            prepared = prepare_wrapper_session_handoff(paths, session_id, message)

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="codex-thread-1",
                codex_session_ref="codex-session-1",
                codex_progress_summary=summarize_codex_jsonl_text(
                    "\n".join(
                        [
                            json.dumps({"type": "tool_call", "tool": "rg", "args": "rg executor progress"}),
                            json.dumps({"role": "assistant", "content": "I found the status projection path and am editing the adapter."}),
                        ]
                    ),
                    evidence_refs=["codex-jsonl"],
                ),
                evidence_refs=["discord-button"],
            )

            status = opened["status"]
            self.assertEqual(prepared["status"]["executor_session_status"]["result"], "not_observed")
            self.assertEqual(status["result"], "not_observed")
            self.assertEqual(status["verification"], "not_requested")
            self.assertEqual(status["executor_progress"]["latest_event"]["event_type"], "diff_started")
            self.assertIn("executor-progress:", "\n".join(status["status_lines"]))
            self.assertIn("not result", status["executor_progress"]["claim_boundary"])

    def test_terminal_executor_progress_closes_progress_but_still_requires_verification_evidence(self) -> None:
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
                codex_session_ref="codex-session-1",
                evidence_refs=["discord-button"],
            )

            completed = record_executor_session_result(
                paths,
                session_id,
                result="completed",
                evidence_refs=["codex-summary"],
                codex_progress_summary=summarize_codex_jsonl_text(
                    "\n".join(
                        [
                            json.dumps({"type": "tool_call", "command": "python -m unittest tests/test_chat_progress_reporting.py"}),
                            json.dumps({"role": "assistant", "content": "Tests passed."}),
                        ]
                    ),
                    evidence_refs=["codex-final-jsonl"],
                ),
            )
            self.assertEqual(completed["status"]["result"], "completed")
            self.assertEqual(completed["status"]["executor_progress"]["state"], "closed")
            self.assertEqual(completed["status"]["executor_progress"]["latest_event"]["event_type"], "executor_completed")
            self.assertEqual(completed["status"]["verification"], "not_requested")
            self.assertIn("not result", completed["status"]["executor_progress"]["claim_boundary"])

    def test_unsupported_progress_profile_records_non_gate_warning_event(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor"
            started = create_or_resume_wrapper_session(paths, message, source="discord")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "generic")
            prepare_wrapper_session_handoff(paths, session_id, message)

            opened = open_executor_session(
                paths,
                session_id,
                observed=True,
                external_session_ref="generic-session-1",
                evidence_refs=["wrapper-button"],
            )

            events_path = paths.runtime_wrapper_sessions_dir / session_id / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            progress_errors = [event for event in events if event.get("event") == "executor_progress_error"]

            self.assertEqual(opened["status"]["result"], "not_observed")
            self.assertNotIn("executor_progress", opened["status"])
            self.assertEqual(len(progress_errors), 1)
            self.assertEqual(progress_errors[0]["level"], "warning")
            self.assertEqual(progress_errors[0]["data"]["progress_error"], "unsupported executor profile for progress")
            self.assertIn("not_observed", json.dumps(progress_errors[0]))
