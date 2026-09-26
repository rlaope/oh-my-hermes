"""Tests for `tools/test_sharding/run.py --workers N`.

A shard may run its tests in N worker processes, one test module per unit.
The contract these tests hold: the merged result has the serial run's schema
with every planned test ID recorded exactly once, a worker that dies turns
every test it had not reported into an error (never a green run), and the
quarantine stays serial whatever N says.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_test_sharding import AGGREGATE_PY, PLAN_PY, RUN_PY, make_quarantine, run_tool, write_json

_PASSING = (
    "import unittest\n"
    "class Test{name}(unittest.TestCase):\n"
    "    def test_one(self):\n"
    "        pass\n"
    "    def test_two(self):\n"
    "        pass\n"
)

# A test that kills its own interpreter mid-module: test_one has already
# passed in the worker, test_three never starts. None of the three is
# reported, so all three must come back as errors.
_DYING = (
    "import os, unittest\n"
    "class TestDying(unittest.TestCase):\n"
    "    def test_one(self):\n"
    "        pass\n"
    "    def test_two(self):\n"
    "        os._exit(3)\n"
    "    def test_three(self):\n"
    "        pass\n"
)


def write_modules(root: Path, modules: dict[str, str]) -> None:
    for name, source in modules.items():
        (root / f"{name}.py").write_text(source, encoding="utf-8")


def plan(root: Path, *, shards: int = 1, quarantine_match: str | None = None) -> Path:
    """Plan the fixture directory; an unset match means an empty quarantine."""

    quarantine = root / "quarantine.json"
    if quarantine_match is None:
        write_json(quarantine, {"version": 1, "entries": []})
    else:
        make_quarantine(quarantine, quarantine_match)
    timings = root / "timings.json"
    write_json(timings, {"version": 1, "durations": {}})
    plan_path = root / "plan.json"
    planned = run_tool(
        PLAN_PY, "--shards", str(shards), "--durations", str(timings),
        "--quarantine", str(quarantine), "--out", str(plan_path), "--start-dir", str(root),
    )
    if planned.returncode != 0:
        raise AssertionError(planned.stderr)
    return plan_path


def run_shard(root: Path, plan_path: Path, out: Path, *target: str, workers: int | None = None) -> subprocess.CompletedProcess[str]:
    extra = () if workers is None else ("--workers", str(workers))
    return run_tool(
        RUN_PY, "--plan", str(plan_path), "--lane", "fixture", *target,
        "--out", str(out), "--start-dir", str(root), *extra,
    )


def without_durations(payload: dict[str, object]) -> dict[str, object]:
    durations = payload["durations"]
    assert isinstance(durations, dict)
    return {**payload, "durations": sorted(durations)}


class WorkerMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_parallel_result_matches_serial_result(self) -> None:
        write_modules(self.root, {
            "test_alpha": _PASSING.format(name="Alpha"),
            "test_beta": _PASSING.format(name="Beta"),
            "test_gamma": (
                "import unittest\n"
                "class TestGamma(unittest.TestCase):\n"
                "    @unittest.skip('fixture')\n"
                "    def test_skipped(self):\n"
                "        pass\n"
                "    def test_passes(self):\n"
                "        pass\n"
            ),
        })
        plan_path = plan(self.root)
        serial = run_shard(self.root, plan_path, self.root / "serial.json", "--shard", "0")
        parallel = run_shard(self.root, plan_path, self.root / "parallel.json", "--shard", "0", workers=3)
        self.assertEqual(serial.returncode, 0, serial.stderr)
        self.assertEqual(parallel.returncode, 0, parallel.stderr)
        self.assertIn("from 3 workers", parallel.stderr)
        serial_payload = json.loads((self.root / "serial.json").read_text(encoding="utf-8"))
        parallel_payload = json.loads((self.root / "parallel.json").read_text(encoding="utf-8"))
        self.assertEqual(without_durations(parallel_payload), without_durations(serial_payload))
        self.assertEqual(parallel_payload["skipped"], ["test_gamma.TestGamma.test_skipped"])
        self.assertEqual(len(parallel_payload["executed"]), 5)

    def test_one_worker_is_the_serial_runner(self) -> None:
        write_modules(self.root, {"test_alpha": _PASSING.format(name="Alpha")})
        plan_path = plan(self.root)
        explicit = run_shard(self.root, plan_path, self.root / "one.json", "--shard", "0", workers=1)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertNotIn("workers", explicit.stderr)
        self.assertIn("Ran 2 tests", explicit.stderr)

    def test_each_module_runs_in_one_worker_with_its_own_temp_root(self) -> None:
        # Two classes of one module share a module global. They pass only if
        # they run in the same process, and only if the temp root is the
        # worker's own rather than the parent's.
        write_modules(self.root, {
            "test_shared": (
                "import tempfile, unittest\n"
                "SEEN = []\n"
                "class TestFirst(unittest.TestCase):\n"
                "    def test_first(self):\n"
                "        SEEN.append('first')\n"
                "        self.assertIn('omh-shard-worker-', tempfile.gettempdir())\n"
                "class TestSecond(unittest.TestCase):\n"
                "    def test_second(self):\n"
                "        self.assertEqual(SEEN, ['first'])\n"
            ),
            "test_alpha": _PASSING.format(name="Alpha"),
        })
        plan_path = plan(self.root)
        ran = run_shard(self.root, plan_path, self.root / "out.json", "--shard", "0", workers=2)
        self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_test_output_on_stdout_does_not_reach_the_result_channel(self) -> None:
        # Two defenses keep this green: the worker points fd 1 at stderr, and
        # the parent parses only marked lines. Removing either alone still
        # passes on POSIX; removing both fails here. The marker exists for a
        # grandchild that inherited the original handle anyway.
        write_modules(self.root, {
            "test_noisy": (
                "import subprocess, sys, unittest\n"
                "class TestNoisy(unittest.TestCase):\n"
                "    def test_prints(self):\n"
                "        print('{\"unit\": {}}')\n"
                "        sys.stdout.flush()\n"
                "        subprocess.run([sys.executable, '-c', 'print(\"child output\")'], check=True)\n"
            ),
        })
        plan_path = plan(self.root)
        ran = run_shard(self.root, plan_path, self.root / "out.json", "--shard", "0", workers=2)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        payload = json.loads((self.root / "out.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["executed"], ["test_noisy.TestNoisy.test_prints"])

    def test_failed_subtest_in_a_worker_fails_the_run(self) -> None:
        # A failed subTest has no outcome for its test ID; the serial runner
        # still exits 1 on it, and so must the merge.
        write_modules(self.root, {
            "test_sub": (
                "import unittest\n"
                "class TestSub(unittest.TestCase):\n"
                "    def test_sub(self):\n"
                "        with self.subTest(case=1):\n"
                "            self.fail('boom')\n"
            ),
            "test_alpha": _PASSING.format(name="Alpha"),
        })
        plan_path = plan(self.root)
        serial = run_shard(self.root, plan_path, self.root / "serial.json", "--shard", "0")
        parallel = run_shard(self.root, plan_path, self.root / "parallel.json", "--shard", "0", workers=2)
        self.assertEqual(serial.returncode, 1, serial.stderr)
        self.assertEqual(parallel.returncode, 1, parallel.stderr)
        self.assertIn("1 failures", parallel.stderr)

    def test_quarantine_stays_serial_whatever_workers_says(self) -> None:
        write_modules(self.root, {
            "test_alpha": _PASSING.format(name="Alpha"),
            "test_gamma": _PASSING.format(name="Gamma"),
        })
        plan_path = plan(self.root, quarantine_match="test_gamma")
        ran = run_shard(self.root, plan_path, self.root / "q.json", "--quarantine", workers=4)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertNotIn("workers", ran.stderr)
        self.assertIn("Ran 2 tests", ran.stderr)

    def test_zero_workers_is_rejected(self) -> None:
        write_modules(self.root, {"test_alpha": _PASSING.format(name="Alpha")})
        plan_path = plan(self.root)
        ran = run_shard(self.root, plan_path, self.root / "out.json", "--shard", "0", workers=0)
        self.assertEqual(ran.returncode, 2)
        self.assertFalse((self.root / "out.json").exists())

    def test_parallel_shards_reconcile_exactly_once_in_the_aggregate(self) -> None:
        write_modules(self.root, {
            f"test_{name.lower()}": _PASSING.format(name=name)
            for name in ("Alpha", "Beta", "Delta", "Epsilon", "Gamma")
        })
        plan_path = plan(self.root, shards=2, quarantine_match="test_gamma")
        results = self.root / "results"
        for target in (("--shard", "0"), ("--shard", "1"), ("--quarantine",)):
            out = results / f"result-{'-'.join(target)}.json"
            ran = run_shard(self.root, plan_path, out, *target, workers=2)
            self.assertEqual(ran.returncode, 0, ran.stderr)
        reconciled = run_tool(
            AGGREGATE_PY, "--plan", str(plan_path), "--quarantine", str(self.root / "quarantine.json"),
            "--results-dir", str(results), "--lanes", "fixture",
        )
        self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
        self.assertIn("reconciled 10 tests", reconciled.stdout)


class WorkerDeathTests(unittest.TestCase):
    """A dead worker's unreported tests are errors, recorded exactly once."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _run(self, workers: int) -> tuple[subprocess.CompletedProcess[str], dict[str, list[str]]]:
        plan_path = plan(self.root)
        out = self.root / "out.json"
        ran = run_shard(self.root, plan_path, out, "--shard", "0", workers=workers)
        return ran, json.loads(out.read_text(encoding="utf-8"))

    def assert_exactly_once(self, payload: dict[str, list[str]]) -> None:
        accounted = payload["executed"] + payload["skipped"] + payload["failures"] + payload["errors"]
        self.assertEqual(sorted(accounted), payload["planned"])

    def test_worker_dying_mid_module_surfaces_every_unreported_test(self) -> None:
        write_modules(self.root, {
            "test_alpha": _PASSING.format(name="Alpha"),
            "test_dying": _DYING,
            "test_zeta": _PASSING.format(name="Zeta"),
        })
        ran, payload = self._run(workers=2)
        self.assertEqual(ran.returncode, 1, ran.stderr)
        self.assertEqual(
            payload["errors"],
            ["test_dying.TestDying.test_one", "test_dying.TestDying.test_three", "test_dying.TestDying.test_two"],
        )
        self.assertIn("while running test_dying.TestDying.test_two", ran.stderr)
        self.assertIn("recording its 3 unreported tests as errors", ran.stderr)
        # The surviving worker still ran everything else.
        self.assertIn("test_zeta.TestZeta.test_one", payload["executed"])
        self.assertIn("test_alpha.TestAlpha.test_two", payload["executed"])
        self.assert_exactly_once(payload)

    def test_every_worker_dying_leaves_no_test_unaccounted(self) -> None:
        write_modules(self.root, {
            "test_alpha": _PASSING.format(name="Alpha"),
            "test_dying": _DYING,
            "test_dying_too": _DYING.replace("TestDying", "TestDyingToo"),
            "test_zeta": _PASSING.format(name="Zeta"),
        })
        # Plan order is alpha, dying, dying_too, zeta; with two workers both
        # die on the dying modules and zeta is never handed out.
        ran, payload = self._run(workers=2)
        self.assertEqual(ran.returncode, 1, ran.stderr)
        self.assertIn("no live worker was left to run test_zeta", ran.stderr)
        self.assertIn("test_zeta.TestZeta.test_one", payload["errors"])
        self.assertIn("test_dying_too.TestDyingToo.test_one", payload["errors"])
        self.assert_exactly_once(payload)

    def test_the_serial_path_is_not_protected_from_a_dying_test(self) -> None:
        # Control for the two tests above: the same fixture kills a serial run
        # outright and writes no result at all, which the aggregate already
        # reads as a missing shard. The workers are what turn it into errors.
        write_modules(self.root, {"test_dying": _DYING})
        plan_path = plan(self.root)
        out = self.root / "out.json"
        ran = run_shard(self.root, plan_path, out, "--shard", "0")
        self.assertEqual(ran.returncode, 3)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    sys.exit(unittest.main())
