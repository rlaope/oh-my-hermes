from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.executor_progress import (
    ExecutorProgressError,
    build_progress_binding,
    build_safe_progress_signal,
    latest_progress_event,
    latest_progress_report,
    normalize_executor_profile,
    observe_executor_progress,
    project_active_executor_status,
    read_progress_binding,
    validate_progress_binding,
    validate_progress_event,
    validate_progress_report,
    write_progress_binding,
)
from omh.paths import resolve_paths


class ExecutorProgressBindingTests(unittest.TestCase):
    def test_profile_boundaries_normalize_coding_executors_without_promoting_hermes(self) -> None:
        self.assertEqual(normalize_executor_profile("codex"), "codex")
        self.assertEqual(normalize_executor_profile("claude-code"), "claude_code")
        self.assertEqual(normalize_executor_profile("claude_code"), "claude_code")

        with self.assertRaisesRegex(ExecutorProgressError, "Hermes orchestration is not an active executor"):
            normalize_executor_profile("hermes")
        with self.assertRaisesRegex(ExecutorProgressError, "hermes_local requires explicit observed local execution"):
            normalize_executor_profile("hermes-local")

        self.assertEqual(normalize_executor_profile("hermes", observed_hermes_execution=True), "hermes_local")
        self.assertEqual(normalize_executor_profile("hermes-local", observed_hermes_execution=True), "hermes_local")

    def test_binding_records_metadata_only_correlation_and_rejects_gate_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            binding = build_progress_binding(
                target_type="run",
                target_id="run-1",
                executor_profile="claude-code",
                claude_session_ref="claude-session-1",
                branch="feature/live-progress",
                evidence_refs=["dispatch-card", "claude-session-card"],
                now="2026-06-24T00:00:00Z",
            )
            write_progress_binding(paths, binding)

            loaded = read_progress_binding(paths, "run", "run-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["binding_id"], "run:run-1:claude_code")
            self.assertEqual(loaded["executor_profile"], "claude_code")
            self.assertEqual(loaded["correlation_root"], "claude_session:claude-session-1")
            self.assertIn({"kind": "claude_session_ref", "value": "claude-session-1"}, loaded["correlation_aliases"])
            self.assertEqual(validate_progress_binding(loaded), [])
            self.assertIn("not result", loaded["claim_boundary"])

            invalid = dict(loaded)
            invalid["result"] = "completed"
            self.assertIn(
                "progress binding must not store result, verification, review, CI, or merge evidence",
                validate_progress_binding(invalid),
            )

    def test_observe_progress_reports_once_for_duplicate_transition(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-1",
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    evidence_refs=["codex-jsonl"],
                    now="2026-06-24T00:00:00Z",
                ),
            )
            signal = build_safe_progress_signal(
                executor_profile="codex",
                explicit_event_type="diff_started",
                explicit_summary="Codex changed files in the executor progress tests.",
                evidence_refs=["codex-jsonl"],
            )

            first = observe_executor_progress(paths, binding, signal, observed_at="2026-06-24T00:01:00Z")
            second = observe_executor_progress(paths, first["binding"], signal, observed_at="2026-06-24T00:01:30Z")

            self.assertTrue(first["reported"])
            self.assertFalse(second["reported"])
            self.assertEqual(second["suppressed_reason"], "duplicate_transition")
            self.assertEqual(second["binding"]["report_count"], 1)
            self.assertEqual(second["binding"]["suppressed_duplicate_count"], 1)
            self.assertEqual(latest_progress_event(paths, first["binding"])["event_type"], "diff_started")
            self.assertEqual(latest_progress_report(paths, first["binding"])["event_type"], "diff_started")
            self.assertEqual(validate_progress_event(first["event"]), [])
            self.assertEqual(validate_progress_report(first["report"]), [])

    def test_projection_groups_run_and_wrapper_bindings_by_correlation_root(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-1",
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    now="2026-06-24T00:00:00Z",
                ),
            )
            wrapper_binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="wrapper_session",
                    target_id="session-1",
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    now="2026-06-24T00:00:10Z",
                ),
            )

            signal = build_safe_progress_signal(
                executor_profile="codex",
                explicit_event_type="tests_started",
                explicit_summary="Codex started targeted tests.",
            )
            observe_executor_progress(paths, run_binding, signal, observed_at="2026-06-24T00:02:00Z")
            observe_executor_progress(paths, wrapper_binding, signal, observed_at="2026-06-24T00:02:05Z")

            projection = project_active_executor_status(paths, now="2026-06-24T00:03:00Z")

            self.assertEqual(projection["schema_version"], "omh_executor_progress_projection/v1")
            self.assertEqual(len(projection["active_executors"]), 1)
            row = projection["active_executors"][0]
            self.assertEqual(row["primary_binding_id"], "wrapper_session:session-1:codex")
            self.assertEqual(row["latest_event"]["event_type"], "tests_started")
            self.assertEqual(row["linked_bindings"][0]["binding_id"], "run:run-1:codex")
            self.assertEqual(len(projection["latest_progress_events"]), 1)
            self.assertNotIn("raw", json.dumps(projection))

    def test_rebinding_target_filters_old_executor_events_by_binding_id(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            codex = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-1",
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    now="2026-06-24T00:00:00Z",
                ),
            )
            observe_executor_progress(
                paths,
                codex,
                build_safe_progress_signal(
                    executor_profile="codex",
                    explicit_event_type="diff_started",
                    explicit_summary="Codex changed files.",
                ),
                observed_at="2026-06-24T00:01:00Z",
            )
            claude = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-1",
                    executor_profile="claude-code",
                    claude_session_ref="claude-session-1",
                    now="2026-06-24T00:02:00Z",
                ),
            )

            self.assertEqual(latest_progress_event(paths, claude), {})
            self.assertEqual(latest_progress_report(paths, claude), {})

            observe_executor_progress(
                paths,
                claude,
                build_safe_progress_signal(
                    executor_profile="claude-code",
                    explicit_event_type="repo_exploration",
                    explicit_summary="Claude Code inspected files.",
                ),
                observed_at="2026-06-24T00:03:00Z",
            )
            self.assertEqual(latest_progress_event(paths, claude)["binding_id"], "run:run-1:claude_code")
