from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import corpus  # noqa: E402
from common import artifact_is_safe  # noqa: E402
from omh_live import prompt_digest, prompt_for_condition  # noqa: E402
from omp_live import omp_argv, run_omp_trial, summarize_omp_events  # noqa: E402
from runner import _live_task, execute_one  # noqa: E402

FAKE_OMP = str(BASE / "adapters" / "fake_omp.py")
MODEL = {"id": "claude-haiku-4-5-20251001", "provider": "cpa", "effort": "medium", "family": "claude", "live": True}


def _manifest() -> dict:
    manifest = json.loads((BASE / "manifest.json").read_text())
    manifest["timeouts_seconds"] = dict(manifest["timeouts_seconds"], edit=5)
    return manifest


def _run(output: Path, mode: str = "ok", condition: str = "baseline", **extra) -> dict:
    with mock.patch.dict(os.environ, {"FAKE_OMP_MODE": mode}):
        return execute_one(BASE, _manifest(), corpus.CONSISTENCY_AB_SPLIT, "C-SCOPE-TRAP", "edit",
                           corpus.EVALUATION_SEEDS[0], condition, output, "omp", model=MODEL,
                           omp_executable=FAKE_OMP, **extra)


class OmpEventSummaryTests(unittest.TestCase):
    def test_sums_usage_over_assistant_messages_and_counts_tools(self) -> None:
        usage = {"input": 3, "output": 4, "cacheRead": 50, "cacheWrite": 7, "totalTokens": 64, "cost": {"total": 0}}
        lines = [
            json.dumps({"type": "session", "id": "s-1"}),
            json.dumps({"type": "message_end", "message": {"role": "user", "content": [], "usage": usage}}),
            json.dumps({"type": "message_end", "message": {"role": "assistant", "usage": usage, "stopReason": "toolUse",
                                                             "content": [{"type": "toolCall", "name": "edit"},
                                                                         {"type": "toolCall", "name": "bash"}]}}),
            "not json",
            json.dumps({"type": "message_end", "message": {"role": "assistant", "usage": usage, "stopReason": "stop",
                                                             "content": [{"type": "text", "text": '{"changed_paths": []}'}]}}),
            json.dumps({"type": "agent_end"}),
        ]
        summary = summarize_omp_events(lines)
        self.assertEqual(summary["session_id"], "s-1")
        self.assertEqual(summary["assistant_calls"], 2)
        self.assertEqual(summary["tokens"], {"input": 6, "output": 8, "cache_read": 100, "cache_write": 14, "total": 128})
        self.assertEqual(summary["tool_counts"], {"bash": 1, "edit": 1})
        self.assertEqual(summary["tool_calls"], 2)
        self.assertTrue(summary["final_text_has_answer_key"])
        self.assertEqual(summary["non_json_lines"], 1)
        self.assertTrue(summary["agent_end"])

    def test_final_text_is_the_last_assistant_text(self) -> None:
        lines = [json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "text", "text": text}], "usage": {}}}) for text in ('{"changed_paths": []}', "All done.")]
        self.assertFalse(summarize_omp_events(lines)["final_text_has_answer_key"])


class OmpArgvTests(unittest.TestCase):
    def test_print_mode_json_with_bounds_and_prompt_last(self) -> None:
        argv = omp_argv("omp", model="m", provider="cpa", effort="medium", workspace=Path("/w"), prompt="task",
                        max_time=600)
        self.assertEqual(argv[:5], ["omp", "-p", "--mode", "json", "--no-title"])
        self.assertEqual(argv[argv.index("--model") + 1], "cpa/m")
        self.assertEqual(argv[argv.index("--thinking") + 1], "medium")
        self.assertEqual(argv[argv.index("--max-time") + 1], "600")
        self.assertEqual(argv[-1], "task")

    def test_rejects_unknown_effort_and_file_reference_prompt(self) -> None:
        with self.assertRaises(ValueError):
            omp_argv("omp", model="m", provider="p", effort="extreme", workspace=Path("/w"), prompt="t", max_time=1)
        with self.assertRaises(ValueError):
            omp_argv("omp", model="m", provider="p", effort="low", workspace=Path("/w"), prompt="@file", max_time=1)

    def test_only_the_baseline_condition_is_sent(self) -> None:
        for condition in ("optimized", "family", "unit", "unit_lean"):
            with self.assertRaisesRegex(ValueError, "baseline"):
                run_omp_trial(omp_executable=FAKE_OMP, workspace=Path("."), task="t", model="m", provider="p",
                              effort="low", condition=condition, timeout=5, confirmed=True)
        with self.assertRaisesRegex(ValueError, "confirmation"):
            run_omp_trial(omp_executable=FAKE_OMP, workspace=Path("."), task="t", model="m", provider="p",
                          effort="low", condition="baseline", timeout=5)


class OmpHarnessRecordTests(unittest.TestCase):
    def test_completed_run_is_graded_and_metadata_only(self) -> None:
        with TemporaryDirectory() as root:
            record = _run(Path(root) / "runs.jsonl")
        self.assertEqual(record["harness"], "omp")
        self.assertEqual(record["observation"]["status"], "completed")
        self.assertEqual(record["observation"]["tokens"], 405)
        self.assertEqual(record["observation"]["tools"], 2)
        self.assertTrue(record["grade"]["pass"], record["grade"]["failure_codes"])
        self.assertEqual(record["harness_metrics"]["tool_counts"], {"edit": 1, "read": 1})
        self.assertTrue(record["harness_metrics"]["final_text_has_answer_key"])
        self.assertIsInstance(record["wall_seconds"], float)
        self.assertEqual(record["session_id"], "fake-omp-session")
        self.assertTrue(artifact_is_safe(record))

    def test_prompt_is_the_baseline_condition_of_the_shared_task(self) -> None:
        with TemporaryDirectory() as root:
            digest_file = Path(root) / "digest"
            with mock.patch.dict(os.environ, {"FAKE_OMP_PROMPT_DIGEST": str(digest_file)}):
                record = _run(Path(root) / "runs.jsonl")
            received = digest_file.read_text(encoding="utf-8")
            with TemporaryDirectory() as other:
                instance, _ = corpus.materialize(corpus.CONSISTENCY_AB_SPLIT, "C-SCOPE-TRAP", "edit",
                                                 corpus.EVALUATION_SEEDS[0], Path(other) / "w", Path(other) / "p")
        expected = prompt_digest(prompt_for_condition(_live_task(instance.prompt), {}, "baseline"))
        self.assertEqual(received, expected)
        self.assertEqual(record["prompt_digest"], expected)

    def test_failed_exit_is_recorded_as_a_failed_run(self) -> None:
        with TemporaryDirectory() as root:
            record = _run(Path(root) / "runs.jsonl", mode="exit")
        self.assertEqual(record["observation"]["status"], "failed")
        self.assertEqual(record["failure_receipt"]["kind"], "process_exit")
        self.assertEqual(record["failure_receipt"]["exit_code"], 1)
        self.assertFalse(record["grade"]["pass"])
        self.assertEqual(record["observation"]["tokens"], 135)

    def test_silent_run_has_no_usage(self) -> None:
        with TemporaryDirectory() as root:
            record = _run(Path(root) / "runs.jsonl", mode="silent")
        self.assertEqual(record["failure_receipt"]["classification"], "usage_unavailable")
        self.assertIsNone(record["observation"]["tokens"])

    def test_timeout_kills_the_child_and_records_a_timeout(self) -> None:
        with TemporaryDirectory() as root:
            manifest = _manifest()
            manifest["timeouts_seconds"]["edit"] = 1
            with mock.patch.dict(os.environ, {"FAKE_OMP_MODE": "hang"}), \
                    mock.patch("omp_live._GRACE_SECONDS", 1):
                record = execute_one(BASE, manifest, corpus.CONSISTENCY_AB_SPLIT, "C-SCOPE-TRAP", "edit",
                                     corpus.EVALUATION_SEEDS[0], "baseline", Path(root) / "runs.jsonl", "omp",
                                     model=MODEL, omp_executable=FAKE_OMP)
        self.assertEqual(record["failure_receipt"], {"classification": "timeout", "kind": "timeout"})
        self.assertLess(record["wall_seconds"], 20)

    def test_edit_directive_is_refused(self) -> None:
        with TemporaryDirectory() as root, self.assertRaisesRegex(ValueError, "directive"):
            _run(Path(root) / "runs.jsonl", edit_directive=True)


class OmpCliTests(unittest.TestCase):
    def _bench(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(BASE / "bench.py"), "run", "--harness", "omp", *args],
                              capture_output=True, text=True, check=False)

    def test_cli_refuses_calibrated_conditions_directives_and_unconfirmed_runs(self) -> None:
        refused = self._bench("--condition", "optimized", "--allow-paid-live", "--max-paid-calls", "1")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("baseline", refused.stderr)
        refused = self._bench("--edit-directive", "--allow-paid-live", "--max-paid-calls", "1")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("--edit-directive", refused.stderr)
        refused = self._bench()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("--allow-paid-live", refused.stderr)


if __name__ == "__main__":
    unittest.main()
