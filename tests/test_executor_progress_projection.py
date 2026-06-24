from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.codex_progress import summarize_codex_jsonl_text
from omh.executor_progress import (
    build_progress_binding,
    build_safe_progress_signal,
    observe_executor_progress,
    project_active_executor_status,
    write_progress_binding,
)
from omh.paths import resolve_paths
from omh.plugin_bundle.omh.runtime_reader import read_omh_status
from omh.runtime_artifacts import create_run, show_run, write_delegation


class ExecutorProgressProjectionTests(unittest.TestCase):
    def test_codex_summary_projects_testing_progress_without_raw_jsonl(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-1",
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    now="2026-06-24T00:00:00Z",
                ),
            )
            summary = summarize_codex_jsonl_text(
                "\n".join(
                    [
                        json.dumps({"type": "tool_call", "tool": "rg", "args": "rg live progress"}),
                        json.dumps({"type": "tool_call", "tool": "apply_patch", "message": "modified src/omh/executor_progress.py"}),
                        json.dumps({"type": "tool_call", "command": "python -m unittest tests/test_executor_progress_binding.py"}),
                        json.dumps({"type": "reasoning", "analysis": "private reasoning should not leak"}),
                    ]
                ),
                evidence_refs=["codex-jsonl"],
                source="codex-session.jsonl",
            )
            signal = build_safe_progress_signal(executor_profile="codex", codex_progress_summary=summary)

            observed = observe_executor_progress(paths, binding, signal, observed_at="2026-06-24T00:03:00Z")
            projection = project_active_executor_status(paths, now="2026-06-24T00:04:00Z")

            self.assertTrue(observed["reported"])
            self.assertEqual(observed["event"]["event_type"], "tests_started")
            rendered = json.dumps(projection)
            self.assertIn("tests_started", rendered)
            self.assertNotIn("private reasoning", rendered)
            self.assertNotIn("codex-session.jsonl", rendered)

    def test_stale_projection_is_separate_from_active_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-1",
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    freshness_seconds=60,
                    expiry_seconds=3600,
                    now="2026-06-24T00:00:00Z",
                ),
            )
            signal = build_safe_progress_signal(
                executor_profile="codex",
                explicit_event_type="repo_exploration",
                explicit_summary="Codex is inspecting the repository.",
            )
            observe_executor_progress(paths, binding, signal, observed_at="2026-06-24T00:00:10Z")

            projection = project_active_executor_status(paths, now="2026-06-24T00:02:00Z")

            self.assertEqual(projection["active_executors"], [])
            self.assertEqual(len(projection["stale_executors"]), 1)
            self.assertEqual(projection["stale_executors"][0]["state"], "stale")

    def test_plugin_runtime_reader_projects_persisted_progress_without_live_polling(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id=run["run_id"],
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                ),
            )
            signal = build_safe_progress_signal(
                executor_profile="codex",
                explicit_event_type="diff_started",
                explicit_summary="Codex changed files in the plugin reader test.",
            )
            observe_executor_progress(paths, binding, signal)

            status = read_omh_status(paths.omh_home)

            self.assertEqual(len(status["active_executors"]), 1)
            self.assertEqual(status["active_executors"][0]["executor_profile"], "codex")
            self.assertEqual(status["active_executors"][0]["latest_event"]["event_type"], "diff_started")
            self.assertEqual(status["latest_progress_events"][0]["event_type"], "diff_started")

            write_delegation(
                paths.runtime_runs_dir / run["run_id"],
                {"requested": True, "observed": True, "result": "completed", "evidence_refs": ["codex-summary"]},
            )
            closed = read_omh_status(paths.omh_home)

            self.assertEqual(closed["active_executors"], [])
            self.assertEqual(closed["stale_executors"], [])

    def test_binding_without_progress_event_does_not_project_as_active_executor(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id=run["run_id"],
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                    now="2026-06-24T00:00:00Z",
                ),
            )

            cli_projection = project_active_executor_status(paths, now="2026-06-24T00:01:00Z")
            plugin_status = read_omh_status(paths.omh_home)

            self.assertEqual(cli_projection["active_executors"], [])
            self.assertEqual(cli_projection["stale_executors"], [])
            self.assertEqual(cli_projection["latest_progress_events"], [])
            self.assertEqual(plugin_status["active_executors"], [])
            self.assertEqual(plugin_status["stale_executors"], [])
            self.assertEqual(plugin_status["latest_progress_events"], [])

    def test_worktree_branch_only_bindings_project_as_separate_instances(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_one = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            run_two = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            shared = {"worktree": "/tmp/omh-worktree", "branch": "feature/live-progress"}
            for index, run in enumerate((run_one, run_two), start=1):
                binding = write_progress_binding(
                    paths,
                    build_progress_binding(
                        target_type="run",
                        target_id=run["run_id"],
                        executor_profile="codex",
                        now=f"2026-06-24T00:0{index}:00Z",
                        freshness_seconds=86400,
                        **shared,
                    ),
                )
                observe_executor_progress(
                    paths,
                    binding,
                    build_safe_progress_signal(
                        executor_profile="codex",
                        explicit_event_type="diff_started",
                        explicit_summary=f"Codex changed files for run {index}.",
                    ),
                    observed_at=f"2026-06-24T00:0{index}:30Z",
                )

            projection = project_active_executor_status(paths, now="2026-06-24T00:03:00Z")
            plugin_status = read_omh_status(paths.omh_home)

            self.assertEqual(len(projection["active_executors"]), 2)
            self.assertEqual(len(plugin_status["active_executors"]), 2)
            for row in projection["active_executors"]:
                self.assertTrue(row["correlation_root"].startswith("binding_instance:"))
                self.assertEqual(row["linked_bindings"], [])
            for row in plugin_status["active_executors"]:
                self.assertTrue(row["correlation_root"].startswith("binding_instance:"))
                self.assertEqual(row["linked_bindings"], [])

    def test_plugin_reader_drops_invalid_progress_event_payloads(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id=run["run_id"],
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                ),
            )
            progress_dir = paths.runtime_runs_dir / run["run_id"] / "executor_progress"
            (progress_dir / "events.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": "omh_progress_event/v1",
                        "binding_id": binding["binding_id"],
                        "executor_profile": "codex",
                        "event_type": "diff_started",
                        "status": "running",
                        "summary": "unsafe progress summary",
                        "observed_at": "2026-06-24T00:01:00Z",
                        "transition_fingerprint": "abc",
                        "raw_log": "secret raw executor output",
                        "claim_boundary": "Executor progress is not result evidence.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            status = read_omh_status(paths.omh_home)
            rendered = json.dumps(status)

            self.assertEqual(status["active_executors"], [])
            self.assertEqual(status["latest_progress_events"], [])
            self.assertNotIn("secret raw executor output", rendered)
            self.assertNotIn("unsafe progress summary", rendered)

    def test_plugin_reader_drops_invalid_progress_binding_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id=run["run_id"],
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                ),
            )
            observe_executor_progress(
                paths,
                binding,
                build_safe_progress_signal(
                    executor_profile="codex",
                    explicit_event_type="diff_started",
                    explicit_summary="Codex changed files.",
                ),
            )
            binding_path = paths.runtime_runs_dir / run["run_id"] / "executor_progress" / "binding.json"
            corrupted = dict(binding)
            corrupted["correlation_root"] = "secret correlation root"
            corrupted["raw_log"] = "secret raw binding output"
            binding_path.write_text(json.dumps(corrupted), encoding="utf-8")

            status = read_omh_status(paths.omh_home)
            rendered = json.dumps(status)

            self.assertEqual(status["active_executors"], [])
            self.assertEqual(status["latest_progress_events"], [])
            self.assertNotIn("secret raw binding output", rendered)
            self.assertNotIn("secret correlation root", rendered)

    def test_cross_surface_projection_agrees_for_active_and_terminal_run_progress(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id=run["run_id"],
                    executor_profile="codex",
                    codex_session_ref="codex-session-1",
                ),
            )
            observe_executor_progress(
                paths,
                binding,
                build_safe_progress_signal(
                    executor_profile="codex",
                    explicit_event_type="diff_started",
                    explicit_summary="Codex changed files.",
                ),
            )

            cli_projection = project_active_executor_status(paths)
            shown = show_run(paths, run["run_id"])
            plugin_status = read_omh_status(paths.omh_home)

            self.assertEqual(cli_projection["active_executors"][0]["state"], "active")
            self.assertEqual(shown["executor_progress"]["state"], "active")
            self.assertEqual(plugin_status["active_executors"][0]["state"], "active")
            self.assertEqual(shown["executor_progress"]["latest_event"]["event_type"], "diff_started")

            write_delegation(
                paths.runtime_runs_dir / run["run_id"],
                {"requested": True, "observed": True, "result": "completed", "evidence_refs": ["codex-summary"]},
            )
            cli_closed = project_active_executor_status(paths)
            shown_closed = show_run(paths, run["run_id"])
            plugin_closed = read_omh_status(paths.omh_home)

            self.assertEqual(cli_closed["active_executors"], [])
            self.assertEqual(cli_closed["stale_executors"], [])
            self.assertEqual(shown_closed["executor_progress"]["state"], "closed")
            self.assertEqual(plugin_closed["active_executors"], [])
            self.assertEqual(plugin_closed["stale_executors"], [])
