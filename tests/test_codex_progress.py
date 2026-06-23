from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.codex_progress import (
    build_codex_prompt_handling_contract,
    build_codex_review_summary,
    build_codex_session_observation,
    summarize_codex_jsonl_text,
)


class CodexProgressTests(unittest.TestCase):
    def test_summarizes_observable_codex_jsonl_without_raw_or_hidden_text(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "tool_call", "tool": "rg", "args": "rg risky tests"}),
                json.dumps({"type": "tool_call", "tool": "apply_patch", "message": "modified src/wrapper/executor_sessions.py"}),
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
        passed = summarize_codex_jsonl_text(json.dumps({"role": "assistant", "content": "Tests passed."}))

        self.assertNotEqual(negated["status"], "completed_or_passed_observed")
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
