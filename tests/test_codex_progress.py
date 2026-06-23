from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.codex_progress import build_codex_session_observation, summarize_codex_jsonl_text


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


if __name__ == "__main__":
    unittest.main()
