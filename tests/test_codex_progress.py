from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.codex_progress import (
    build_codex_prompt_handling_contract,
    build_codex_review_summary,
    build_codex_session_observation,
    summarize_codex_jsonl_text,
)
from omh.executor_progress import (
    build_progress_binding,
    build_safe_progress_signal,
    infer_progress_event_type,
    observe_executor_progress,
    write_progress_binding,
)
from omh.paths import resolve_paths


class CodexProgressTests(unittest.TestCase):
    def test_summarizes_observable_codex_jsonl_without_raw_or_hidden_text(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "tool_call", "tool": "rg", "args": "rg risky tests"}),
                json.dumps({"type": "tool_call", "tool": "apply_patch", "message": "modified src/omh/wrapper/executor_sessions.py"}),
                json.dumps({"type": "tool_call", "command": "python -m unittest tests/test_cli.py"}),
                json.dumps({"type": "reasoning", "analysis": "hidden private reasoning should never render"}),
                json.dumps({"type": "reasoning", "content": "hidden private content should never influence summaries"}),
                json.dumps({"role": "assistant", "content": "I will wait on review after tests pass."}),
            ]
        )

        summary = summarize_codex_jsonl_text(raw, evidence_refs=["codex-jsonl"], source="codex-run.jsonl")

        self.assertEqual(summary["schema_version"], "codex_progress_summary/v1")
        self.assertEqual(summary["event_count"], 6)
        self.assertEqual(summary["malformed_event_count"], 0)
        self.assertGreater(summary["activity_counts"]["inspecting"], 0)
        self.assertGreater(summary["activity_counts"]["editing"], 0)
        self.assertGreater(summary["activity_counts"]["testing"], 0)
        self.assertIn("Codex changed files.", summary["observable_activity"])
        self.assertIn("Codex decided via assistant-visible message", summary["chat_summary"])
        rendered = json.dumps(summary)
        self.assertNotIn("hidden private reasoning", rendered)
        self.assertNotIn("hidden private content", rendered)
        self.assertIn("not raw JSONL", summary["claim_boundary"])
        self.assertEqual(summary["privacy"], "summary_only")

    def test_oversized_codex_progress_returns_artifact_ref_and_bounded_context(self) -> None:
        huge_visible = "Codex tool output: " + ("A" * 5000) + " final decision"
        huge_ref = "codex-jsonl:" + ("B" * 5000)
        raw = "\n".join(
            [
                json.dumps({"role": "assistant", "content": huge_visible}),
                json.dumps({"type": "tool_call", "tool": "rg", "args": "rg bounded context"}),
            ]
        )

        summary = summarize_codex_jsonl_text(
            raw,
            evidence_refs=[huge_ref, *[f"ref-{index}" for index in range(20)]],
            source="codex-session.jsonl",
        )

        rendered = json.dumps(summary)
        self.assertEqual(summary["raw_output_artifact"]["schema_version"], "omh_context_artifact_ref/v1")
        self.assertEqual(summary["raw_output_artifact"]["source"], "codex-session.jsonl")
        self.assertEqual(summary["raw_output_artifact"]["sha256"], hashlib.sha256(raw.encode("utf-8")).hexdigest())
        self.assertEqual(summary["raw_output_artifact"]["byte_count"], len(raw.encode("utf-8")))
        self.assertFalse(summary["raw_output_artifact"]["raw_content_included"])
        self.assertEqual(summary["raw_output_artifact"]["storage_policy"], "store_raw_output_as_artifact")
        self.assertEqual(summary["raw_output_artifact"]["in_context_policy"], "refs_and_summary_only")
        self.assertEqual(summary["context_budget"]["max_visible_message_chars"], 180)
        self.assertEqual(summary["context_budget"]["max_evidence_refs"], 8)
        self.assertLessEqual(len(summary["latest_assistant_visible_message"]), 180)
        self.assertLessEqual(len(summary["evidence_refs"]), 8)
        self.assertLessEqual(max(len(ref) for ref in summary["evidence_refs"]), 160)
        self.assertGreater(summary["omitted"]["evidence_ref_count"], 0)
        self.assertNotIn("A" * 1000, rendered)
        self.assertNotIn("B" * 1000, rendered)
        self.assertIn("raw output should stay in artifacts", summary["claim_boundary"])

    def test_codex_progress_emits_event_triggered_updates_without_raw_logs(self) -> None:
        raw_noise = "full tool log " + ("N" * 5000)
        raw = "\n".join(
            [
                json.dumps({"role": "assistant", "content": f"Bug discovered: delegate mode ignored the setup default. {raw_noise}"}),
                json.dumps(
                    {
                        "role": "assistant",
                        "content": "Root cause identified in src/omh/wrapper/contract.py: default executor was not propagated.",
                    }
                ),
                json.dumps(
                    {
                        "role": "assistant",
                        "content": "Fix strategy selected: carry setup_profile.default_executor into the delegate handoff.",
                    }
                ),
                json.dumps({"role": "assistant", "content": "Targeted tests passed: tests/test_wrapper_contract.py."}),
            ]
        )

        summary = summarize_codex_jsonl_text(raw, evidence_refs=["codex-jsonl"], source="codex-events.jsonl")

        rendered = json.dumps(summary)
        event_types = [event["event_type"] for event in summary["progress_events"]]
        self.assertEqual(summary["progress_reporting"]["mode"], "event_triggered")
        self.assertFalse(summary["progress_reporting"]["timed_polling_required"])
        self.assertIn("bug_discovered", event_types)
        self.assertIn("root_cause_identified", event_types)
        self.assertIn("fix_strategy_selected", event_types)
        self.assertIn("targeted_tests_passed", event_types)
        self.assertLessEqual(len(summary["progress_events"]), summary["context_budget"]["max_progress_events"])
        self.assertEqual(summary["latest_progress_event"]["event_type"], "targeted_tests_passed")
        self.assertEqual(summary["latest_progress_event"]["severity"], "success")
        self.assertIn("tests/test_wrapper_contract.py", summary["latest_progress_event"]["file_refs"])
        self.assertEqual(summary["latest_progress_event"]["artifact_refs"][0]["schema_version"], "omh_context_artifact_ref/v1")
        self.assertNotIn("N" * 1000, rendered)
        self.assertNotIn("```", rendered)
        self.assertIn("not execution", summary["latest_progress_event"]["claim_boundary"])

    def test_codex_progress_summary_can_drive_executor_progress_signal(self) -> None:
        summary = summarize_codex_jsonl_text(
            "\n".join(
                [
                    json.dumps({"type": "tool_call", "tool": "rg", "args": "rg progress"}),
                    json.dumps({"type": "tool_call", "tool": "apply_patch", "message": "modified src/omh/coding/executor_progress.py"}),
                    json.dumps({"type": "reasoning", "analysis": "hidden private reasoning"}),
                ]
            ),
            evidence_refs=["codex-jsonl"],
        )

        signal = build_safe_progress_signal(executor_profile="codex", codex_progress_summary=summary)

        self.assertEqual(signal["executor_profile"], "codex")
        self.assertEqual(infer_progress_event_type(signal), "diff_started")
        rendered = json.dumps(signal)
        self.assertNotIn("hidden private reasoning", rendered)
        self.assertNotIn("raw", rendered)

    def test_codex_live_progress_snapshots_emit_stateful_intermediate_reports(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-live-1",
                    executor_profile="codex",
                    process_session_id="codex-proc-1",
                    evidence_refs=["codex-live-jsonl"],
                    now="2026-06-25T00:00:00Z",
                ),
            )

            inspect_summary = summarize_codex_jsonl_text(
                "\n".join(
                    [
                        json.dumps({"type": "tool_call", "tool": "rg", "args": "rg runtime progress src tests"}),
                        json.dumps({"type": "reasoning", "analysis": "hidden private reasoning must not leak"}),
                    ]
                ),
                evidence_refs=["codex-live-jsonl"],
                source="codex-live.jsonl",
            )
            inspect_signal = build_safe_progress_signal(
                executor_profile="codex",
                process_status="running",
                codex_progress_summary=inspect_summary,
                evidence_refs=["codex-live-jsonl"],
            )

            first = observe_executor_progress(paths, binding, inspect_signal, observed_at="2026-06-25T00:00:10Z")
            repeated = observe_executor_progress(paths, first["binding"], inspect_signal, observed_at="2026-06-25T00:00:20Z")

            self.assertTrue(first["reported"])
            self.assertEqual(first["reporting_action"], "send_report")
            self.assertEqual(first["event"]["event_type"], "repo_exploration")
            self.assertIn("inspecting", first["chat_report"])
            self.assertFalse(repeated["reported"])
            self.assertEqual(repeated["reporting_action"], "suppress")
            self.assertEqual(repeated["suppressed_reason"], "duplicate_transition")

            diff_summary = summarize_codex_jsonl_text(
                "\n".join(
                    [
                        json.dumps({"type": "tool_call", "tool": "rg", "args": "rg runtime progress src tests"}),
                        json.dumps({"type": "tool_call", "tool": "apply_patch", "message": "modified src/omh/coding/executor_progress.py"}),
                    ]
                ),
                evidence_refs=["codex-live-jsonl"],
                source="codex-live.jsonl",
            )
            diff = observe_executor_progress(
                paths,
                repeated["binding"],
                build_safe_progress_signal(
                    executor_profile="codex",
                    process_status="running",
                    codex_progress_summary=diff_summary,
                    evidence_refs=["codex-live-jsonl"],
                ),
                observed_at="2026-06-25T00:00:30Z",
            )

            self.assertTrue(diff["reported"])
            self.assertEqual(diff["event"]["event_type"], "diff_started")

            test_summary = summarize_codex_jsonl_text(
                "\n".join(
                    [
                        json.dumps({"type": "tool_call", "tool": "apply_patch", "message": "modified tests/test_codex_progress.py"}),
                        json.dumps({"type": "tool_call", "command": "PYTHONPATH=tests uv run python -m unittest tests/test_codex_progress.py -v"}),
                        json.dumps({"role": "assistant", "content": "Tests passed: tests/test_codex_progress.py."}),
                    ]
                ),
                evidence_refs=["codex-live-jsonl"],
                source="codex-live.jsonl",
            )
            tests = observe_executor_progress(
                paths,
                diff["binding"],
                build_safe_progress_signal(
                    executor_profile="codex",
                    process_status="running",
                    codex_progress_summary=test_summary,
                    evidence_refs=["codex-live-jsonl"],
                ),
                observed_at="2026-06-25T00:00:40Z",
            )

            self.assertTrue(tests["reported"])
            self.assertIn(tests["event"]["event_type"], {"tests_started", "tests_passed"})
            rendered = json.dumps(tests)
            self.assertNotIn("hidden private reasoning", rendered)
            self.assertNotIn("analysis", rendered)
            self.assertNotIn("raw_log", rendered)

    def test_nested_reasoning_does_not_influence_observable_summary(self) -> None:
        raw = json.dumps(
            {
                "type": "response_item",
                "item": {
                    "type": "reasoning",
                    "summary": [{"text": "hidden tests passed and apply_patch changed files"}],
                },
            }
        )

        summary = summarize_codex_jsonl_text(raw, source="codex-run.jsonl")

        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["status"], "no_observable_events")
        self.assertEqual(summary["activity_counts"]["testing"], 0)
        self.assertEqual(summary["activity_counts"]["editing"], 0)
        rendered = json.dumps(summary)
        self.assertNotIn("hidden tests passed", rendered)
        self.assertNotIn("completed_or_passed_observed", rendered)

    def test_terminal_status_avoids_negated_or_partial_success_words(self) -> None:
        negated = summarize_codex_jsonl_text(
            json.dumps({"role": "assistant", "content": "Tests are not completed; this is an incomplete run."})
        )
        future = summarize_codex_jsonl_text(
            "\n".join(
                [
                    json.dumps({"role": "assistant", "content": "I will complete the implementation after tests run."}),
                    json.dumps({"role": "assistant", "content": "I am going to mark this success after CI."}),
                    json.dumps({"role": "assistant", "content": "I will run tests, then report success."}),
                ]
            )
        )
        passed = summarize_codex_jsonl_text(json.dumps({"role": "assistant", "content": "Tests passed."}))

        self.assertNotEqual(negated["status"], "completed_or_passed_observed")
        self.assertNotEqual(future["status"], "completed_or_passed_observed")
        self.assertEqual(passed["status"], "completed_or_passed_observed")

    def test_codex_session_observation_exposes_resume_contract_without_execution_claim(self) -> None:
        progress = summarize_codex_jsonl_text(
            json.dumps({"role": "assistant", "content": "Done with the patch."}),
            evidence_refs=["codex-summary"],
        )

        observation = build_codex_session_observation(
            selected_executor_profile="codex",
            external_session_ref="thread-1",
            codex_session_ref="session-1",
            codex_thread_ref="thread-1",
            evidence_refs=["button-open"],
            progress_summary=progress,
        )

        self.assertTrue(observation["observed"])
        self.assertEqual(observation["session_ref"], "session-1")
        self.assertEqual(observation["thread_ref"], "thread-1")
        self.assertEqual(observation["event_count"], 1)
        self.assertEqual(observation["resume"]["argv_template"], ["codex", "exec", "resume", "session-1"])
        self.assertTrue(observation["resume"]["not_omh_backend_execution"])
        self.assertIn("do not prove", observation["claim_boundary"])

    def test_codex_session_resume_requires_explicit_codex_session_ref(self) -> None:
        observation = build_codex_session_observation(
            selected_executor_profile="codex",
            external_session_ref="codex-thread-only",
        )

        self.assertTrue(observation["observed"])
        self.assertEqual(observation["session_ref"], "")
        self.assertEqual(observation["thread_ref"], "codex-thread-only")
        self.assertFalse(observation["resume"]["available"])
        self.assertEqual(observation["resume"]["argv_template"], [])

    def test_followup_contract_recommends_append_only_for_same_observed_session(self) -> None:
        progress = summarize_codex_jsonl_text(
            json.dumps({"type": "tool_call", "tool": "rg", "args": "rg codex"}),
            evidence_refs=["codex-jsonl"],
        )

        append = build_codex_prompt_handling_contract(
            new_prompt="continue the same PR",
            progress_summary=progress,
            codex_session_ref="session-1",
            codex_thread_ref="thread-1",
            wrapper_session_id="ws-1",
        )

        self.assertEqual(append["recommendation"]["action"], "append_followup_to_observed_codex_session")
        self.assertEqual(append["resume"]["argv_template"], ["codex", "exec", "resume", "session-1"])
        self.assertEqual(append["new_prompt"]["raw_prompt_stored"], False)
        self.assertNotIn("continue the same PR", json.dumps(append))
        self.assertFalse(append["adapter_contract"]["raw_logs_exposed"])
        self.assertFalse(append["adapter_contract"]["hidden_reasoning_exposed"])

        clarify = build_codex_prompt_handling_contract(
            new_prompt="maybe a separate task",
            progress_summary=progress,
            codex_session_ref="session-1",
        )

        self.assertEqual(clarify["recommendation"]["action"], "clarify_before_append_or_route_new")
        self.assertIn("resume", clarify)

        new_route = build_codex_prompt_handling_contract(new_prompt="new task", progress_summary=progress)
        self.assertEqual(new_route["recommendation"]["action"], "route_new_or_clarify")
        self.assertNotIn("resume", new_route)

    def test_review_summary_is_human_readable_and_resume_bound_to_session_ref(self) -> None:
        progress = summarize_codex_jsonl_text(
            "\n".join(
                [
                    json.dumps({"type": "tool_call", "tool": "rg", "args": "rg review"}),
                    json.dumps({"type": "response_item", "item": {"type": "reasoning", "summary": "hidden review thought"}}),
                ]
            ),
            evidence_refs=["codex-jsonl"],
        )

        review = build_codex_review_summary(
            review_status="changes_requested",
            summary="Codex review found two bounded issues to fix.",
            finding_count=2,
            progress_summary=progress,
            codex_session_ref="codex-session-1",
            codex_thread_ref="codex-thread-1",
            evidence_refs=["codex-review-summary"],
        )

        self.assertEqual(review["schema_version"], "codex_review_summary/v1")
        self.assertTrue(review["observed"])
        self.assertEqual(review["status"], "changes_requested")
        self.assertTrue(review["requires_fixes"])
        self.assertEqual(review["finding_count"], 2)
        self.assertEqual(review["handback"]["recommended_action"], "resume_codex_for_review_fixes")
        self.assertEqual(review["handback"]["resume"]["argv_template"], ["codex", "exec", "resume", "codex-session-1"])
        self.assertFalse(review["adapter_contract"]["raw_logs_exposed"])
        self.assertFalse(review["adapter_contract"]["hidden_reasoning_exposed"])
        rendered = json.dumps(review)
        self.assertIn("Codex review found two bounded issues", rendered)
        self.assertNotIn("hidden review thought", rendered)

        thread_only = build_codex_review_summary(
            review_status="changes_requested",
            summary="Review needs fixes.",
            external_session_ref="codex-thread-only",
        )
        self.assertFalse(thread_only["handback"]["can_resume_for_fixes"])
        self.assertEqual(thread_only["handback"]["resume"], {})


if __name__ == "__main__":
    unittest.main()
