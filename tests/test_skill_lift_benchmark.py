"""Contract tests for the `benchmarks/skill-lift/v1` offline and 2-model lift gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

from _local_package import load_local_package

load_local_package()

from omh.quality.reported_rate import reported_rate_shape_errors
from omh.skills.hermes_parity import CONSOLIDATION_CANDIDATES, hermes_skill_parity_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = REPO_ROOT / "benchmarks" / "skill-lift" / "v1"
BENCH_SCRIPT = BENCH_DIR / "bench.py"
GRADER_PATH = BENCH_DIR / "grader.py"


def _load_grader():
    spec = importlib.util.spec_from_file_location("skill_lift_grader", GRADER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SkillLiftBenchmarkTests(unittest.TestCase):
    def test_corpus_validates_offline(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(BENCH_SCRIPT), "validate"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["valid"], payload["errors"])
        self.assertGreaterEqual(payload["task_count"], 12)

    def test_fake_adapter_runs_two_models_and_emits_reported_rate_v1(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(BENCH_SCRIPT),
                "run",
                "--adapter",
                "fake",
                "--models",
                "frontier-a,frontier-b",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["schema_version"], "omh_skill_lift_report/v1")
        self.assertFalse(report["live_observed"])
        self.assertTrue(report["overall_passed"])
        self.assertEqual(len(report["model_results"]), 2)
        for result in report["model_results"]:
            for key in (
                "without_skill_pass_rate",
                "with_skill_pass_rate",
                "failure_reduction_rate",
                "negative_control_regression_rate",
            ):
                self.assertEqual(reported_rate_shape_errors(result[key]), (), key)
            self.assertEqual(result["negative_control_regression_rate"]["numerator"], 0)

    def test_live_adapter_refuses_without_explicit_paid_opt_in_and_confirm(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(BENCH_SCRIPT),
                "run",
                "--adapter",
                "hermes-child",
                "--models",
                "model-a,model-b",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--allow-paid-live", proc.stderr)

    def test_empty_denominator_and_negative_regression_fail_verdict(self) -> None:
        grader = _load_grader()
        empty = grader.evaluate_model_arm_pair(model="empty", without_grades=[], with_grades=[])
        self.assertFalse(empty["passed"])
        self.assertIsNone(empty["without_skill_pass_rate"]["percent"])
        self.assertEqual(empty["without_skill_pass_rate"]["basis"], "no_observations")
        self.assertEqual(reported_rate_shape_errors(empty["without_skill_pass_rate"]), ())

        regressed = grader.evaluate_model_arm_pair(
            model="regressed",
            without_grades=[
                grader.TaskGrade("p1", "spend-gate", "positive", False, ("card",), (), 100),
                grader.TaskGrade("n1", "spend-gate", "negative_control", True, (), (), 100),
            ],
            with_grades=[
                grader.TaskGrade("p1", "spend-gate", "positive", True, (), (), 120),
                grader.TaskGrade("n1", "spend-gate", "negative_control", False, ("ans",), (), 120),
            ],
        )
        self.assertFalse(regressed["passed"])
        self.assertIn("negative_control_regression_or_missing", regressed["reasons"])

    def test_parity_payload_exposes_consolidation_candidates(self) -> None:
        payload = hermes_skill_parity_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["consolidation_candidates"]), len(CONSOLIDATION_CANDIDATES))
        self.assertEqual(payload["catalog"]["value_mechanism_counts"]["executable_toolkit"], 17)


if __name__ == "__main__":
    unittest.main()
