"""Smoke gate for tools/benchmarks/tui_perf.py: every case runs at the tiny size and keeps its output schema.

Deliberately no wall-clock ceilings. The only absolute claims are counts.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/benchmarks/tui_perf.py"


def bench():
    spec = importlib.util.spec_from_file_location("tui_perf_bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TuiPerfBenchSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "tests")])}
        done = subprocess.run([sys.executable, "-P", str(SCRIPT), "--json", "--size", "tiny"], env=env,
                              cwd=str(ROOT), capture_output=True, text=True, check=False, timeout=300)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-2000:])
        cls.payload = json.loads(done.stdout)

    def test_schema_and_every_case_present(self):
        b = bench()
        self.assertEqual(self.payload["schema"], b.SCHEMA)
        self.assertEqual(self.payload["size"], "tiny")
        self.assertEqual({r["case"] for r in self.payload["results"]}, set(b.CASES))
        for result in self.payload["results"]:
            self.assertEqual(set(result), {"case", "label", "metrics"})
            self.assertTrue(result["metrics"], result)
            for name, value in result["metrics"].items():
                self.assertTrue(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0,
                                (result["case"], name, value))

    def test_steady_frame_with_nothing_changed_writes_nothing(self):
        frames = [r for r in self.payload["results"] if r["case"] == "frame"]
        self.assertTrue(frames)
        for result in frames:
            self.assertEqual(result["metrics"]["steady_frame_bytes"], 0, result["label"])

    def test_compare_verdicts(self):
        b = bench()
        self.assertEqual(b.verdict("steady_frame_p50_ms", 1.0, 1.1, 15.0)[1], "~")
        self.assertEqual(b.verdict("steady_frame_p50_ms", 1.0, 2.0, 15.0)[1], "worse")
        self.assertEqual(b.verdict("steady_frame_p50_ms", 2.0, 1.0, 15.0)[1], "better")
        self.assertEqual(b.verdict("steady_frame_p50_ms", 0.001, 0.005, 15.0)[1], "~")
        self.assertEqual(b.verdict("full_redraw_bytes", 1000, 1100, 15.0)[1], "worse")
        self.assertEqual(b.verdict("full_redraw_bytes", 1000, 1000, 15.0)[1], "~")


if __name__ == "__main__":
    unittest.main()
