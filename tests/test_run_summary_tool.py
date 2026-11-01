"""Contracts for the localized end-of-run summary tool.

A finished workflow run closes with two lines — elapsed seconds and token
usage — rendered from Hermes' own session accounting in state.db, never from
numbers the model estimated. The tool aggregates the calling session plus
its direct delegate_task children and localizes the labels (en/ko/ja/zh).
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from omh.plugin_bundle.omh.tools.run_summary_tool import omh_run_summary_handler


def _build_state_db(home: Path, sessions: list[dict]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(home / "state.db")
    connection.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, parent_session_id TEXT, model TEXT,
            started_at REAL, ended_at REAL, input_tokens INTEGER,
            output_tokens INTEGER, cache_read_tokens INTEGER,
            reasoning_tokens INTEGER, api_call_count INTEGER,
            actual_cost_usd REAL, estimated_cost_usd REAL
        )
        """
    )
    connection.execute(
        "CREATE TABLE session_model_usage (session_id TEXT, model TEXT, first_seen REAL)"
    )
    for row in sessions:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("parent"),
                row.get("model", ""),
                row.get("started_at"),
                row.get("ended_at"),
                row.get("input_tokens", 0),
                row.get("output_tokens", 0),
                row.get("cache_read_tokens", 0),
                row.get("reasoning_tokens", 0),
                row.get("api_call_count", 0),
                row.get("actual_cost_usd", 0.0),
                row.get("estimated_cost_usd", 0.0),
            ),
        )
        for index, model in enumerate(row.get("usage_models", [])):
            connection.execute(
                "INSERT INTO session_model_usage VALUES (?, ?, ?)",
                (row["id"], model, (row.get("started_at") or 0.0) + index),
            )
    connection.commit()
    connection.close()


class RunSummaryToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "hermes"
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260819_100000_main01",
                    "model": "gpt-5.6-sol",
                    "started_at": 1_000_000.0,
                    "ended_at": 1_002_741.0,
                    "input_tokens": 4_000_000,
                    "output_tokens": 700_000,
                    "reasoning_tokens": 90_000,
                    "api_call_count": 40,
                    "actual_cost_usd": 1.25,
                    "usage_models": ["gpt-5.6-sol"],
                },
                {
                    "id": "20260819_100200_child1",
                    "parent": "20260819_100000_main01",
                    "model": "glm-5.2-ultrafast",
                    "started_at": 1_000_100.0,
                    "ended_at": 1_001_000.0,
                    "input_tokens": 100_000,
                    "output_tokens": 49_639,
                    "api_call_count": 6,
                    "estimated_cost_usd": 0.10,
                    "usage_models": ["glm-5.2-ultrafast"],
                },
                {
                    "id": "20260819_090000_other",
                    "started_at": 999_000.0,
                    "input_tokens": 5,
                    "output_tokens": 5,
                },
            ],
        )

    def _call(self, **args) -> dict:
        return json.loads(
            omh_run_summary_handler(
                {"hermes_home": str(self.home), **args},
                session_id="20260819_100000_main01",
            )
        )

    def test_the_korean_summary_matches_the_owner_format(self):
        result = self._call(language="ko")
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["elapsed_seconds"], 2741)
        self.assertEqual(result["tokens_used"], 4_849_639)
        self.assertEqual(result["models_used"], ["gpt-5.6-sol", "glm-5.2-ultrafast"])
        self.assertEqual(
            result["summary_text"],
            "소요 시간: 2,741초\n토큰 사용량: 4,849,639\n사용 모델: gpt-5.6-sol, glm-5.2-ultrafast",
        )

    def test_every_supported_language_renders_all_lines(self):
        models = "gpt-5.6-sol, glm-5.2-ultrafast"
        expected = {
            "en": f"Elapsed time: 2,741s\nTokens used: 4,849,639\nModels used: {models}",
            "ja": f"所要時間: 2,741秒\nトークン使用量: 4,849,639\n使用モデル: {models}",
            "zh": f"耗时: 2,741秒\nToken 使用量: 4,849,639\n使用模型: {models}",
        }
        for language, text in expected.items():
            with self.subTest(language=language):
                self.assertEqual(self._call(language=language)["summary_text"], text)

    def test_children_are_included_and_unrelated_sessions_are_not(self):
        breakdown = self._call(language="en")["breakdown"]
        self.assertEqual(breakdown["subagent_sessions"], 1)
        self.assertEqual(breakdown["input_tokens"], 4_100_000)
        self.assertEqual(breakdown["output_tokens"], 749_639)
        self.assertEqual(breakdown["api_calls"], 46)
        self.assertAlmostEqual(breakdown["cost_usd"], 1.35)

    def test_a_finished_dag_run_closes_with_its_goal_verdict_from_the_record(self):
        from omh.plugin_bundle.omh import dag_run

        omh_home = Path(self._tmp.name) / "omh"
        prompt = "TASK: t\nDELIVERABLE: d\nSCOPE: s\nVERIFY: v\nSTOP WHEN: w"
        record = dag_run.new_record("20260819_100000_main01", "export", "export", "", [
            {"id": "api", "label": "Export API", "category": "quick", "prompt": prompt, "write_scope": ["a.py"]},
            {"id": "check", "label": "Check the export", "category": "quick", "prompt": prompt,
             "depends_on": ["api"], "role": "verify"},
        ], 1_000_000.0)
        path = dag_run.record_path(omh_home, "20260819_100000_main01", "export")
        path.parent.mkdir(parents=True)

        def settle_all(outcomes: dict[str, str]) -> None:
            for item in record["nodes"]:
                item["attempts"] = [{"n": 1, "handed_out_at": 1.0, "outcome": outcomes[item["id"]]}]
            dag_run.write_run(path, record)

        settle_all({"api": "accepted", "check": ""})  # the verify node is still out: no closing line yet
        running = self._call(language="en", omh_home=str(omh_home))
        self.assertNotIn("dag_goal", running)
        self.assertNotIn("Goal check", running["summary_text"])
        settle_all({"api": "accepted", "check": "accepted"})
        verified = self._call(language="en", omh_home=str(omh_home))
        self.assertEqual(verified["summary_text"].splitlines()[-1], "Goal check (DAG export): verified")
        record["nodes"][1]["role"] = "build"  # the same run with no verify node: done, and not verified
        settle_all({"api": "accepted", "check": "accepted"})
        unverified = self._call(language="ko", omh_home=str(omh_home))
        self.assertEqual(unverified["summary_text"].splitlines()[-1], "목표 검증 (DAG export): unverified")
        self.assertEqual(unverified["dag_goal"], {"run": "export", "name": "export", "state": "done",
                                                  "verdict": "unverified", "reasons": ["no_verification_node"]})

    def test_an_unknown_language_falls_back_to_english(self):
        self.assertTrue(self._call(language="fr")["summary_text"].startswith("Elapsed time:"))

    def test_a_missing_session_row_reports_not_observed(self):
        result = json.loads(
            omh_run_summary_handler(
                {"hermes_home": str(self.home), "session_id": "nope"},
            )
        )
        self.assertEqual(result["status"], "not_observed")

    def test_no_session_id_at_all_is_an_explicit_error_not_a_guess(self):
        result = json.loads(omh_run_summary_handler({"hermes_home": str(self.home)}))
        self.assertEqual(result["status"], "no_session")
        self.assertIn("claim_boundary", result)


class RunSummaryUnmeasuredElapsedTest(unittest.TestCase):
    """A session row with no recorded start time never observed starting.

    `started_at` is the one field on the row that can genuinely be absent.
    The summary must say "unknown" for it -- never a fabricated `0s` that
    reads as a run that took no time at all.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "hermes"
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260830_100000_nostart",
                    "started_at": None,
                    "input_tokens": 1_234,
                    "output_tokens": 567,
                    "usage_models": ["gpt-5.6-sol"],
                },
            ],
        )

    def _call(self, **args) -> dict:
        return json.loads(
            omh_run_summary_handler(
                {"hermes_home": str(self.home), **args},
                session_id="20260830_100000_nostart",
            )
        )

    def test_elapsed_seconds_is_none_not_a_fabricated_zero(self):
        result = self._call(language="en")
        self.assertEqual(result["status"], "observed")
        self.assertIsNone(result["elapsed_seconds"])

    def test_summary_text_renders_the_word_unknown(self):
        result = self._call(language="en")
        self.assertEqual(
            result["summary_text"],
            "Elapsed time: unknown\nTokens used: 1,801\nModels used: gpt-5.6-sol",
        )

    def test_unknown_elapsed_is_not_localized_but_labels_still_are(self):
        result = self._call(language="ko")
        self.assertEqual(
            result["summary_text"],
            "소요 시간: unknown\n토큰 사용량: 1,801\n사용 모델: gpt-5.6-sol",
        )

    def test_measured_tokens_are_unaffected_by_unmeasured_elapsed(self):
        result = self._call(language="en")
        self.assertEqual(result["tokens_used"], 1_801)
        self.assertEqual(result["breakdown"]["input_tokens"], 1_234)
        self.assertEqual(result["breakdown"]["output_tokens"], 567)


if __name__ == "__main__":
    unittest.main()
