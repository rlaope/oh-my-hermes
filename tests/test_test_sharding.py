# allow: SIZE_OK -- the issue-#1294 write scope permits exactly one test
# module (tests/test_test_sharding.py); splitting fixtures into a second
# file would violate the declared scope.
"""Tests for tools/test_sharding (issue #1294).

The shard planner must be deterministic, assign every discovered test
exactly once, keep quarantined shared-state tests out of the parallel
shards, and fail closed on discovery failure or count mismatches.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools" / "test_sharding"
PLAN_PY = TOOLS / "plan.py"
RUN_PY = TOOLS / "run.py"
AGGREGATE_PY = TOOLS / "aggregate.py"
REAL_QUARANTINE = TOOLS / "quarantine.json"
REAL_TIMINGS = TOOLS / "timings.json"

sys.path.insert(0, str(REPO_ROOT))

from tools.test_sharding import JsonValue  # noqa: E402
from tools.test_sharding import aggregate as aggregate_mod  # noqa: E402
from tools.test_sharding import plan as plan_mod  # noqa: E402

_DISCOVER_SNIPPET = (
    "import json, unittest\n"
    "def walk(suite):\n"
    "    for test in suite:\n"
    "        if isinstance(test, unittest.TestSuite):\n"
    "            yield from walk(test)\n"
    "        else:\n"
    "            yield test\n"
    "suite = unittest.TestLoader().discover('tests', top_level_dir='tests')\n"
    "tests = list(walk(suite))\n"
    "failed = [t.id() for t in tests if type(t).__name__ == '_FailedTest']\n"
    "print(json.dumps({'ids': sorted(t.id() for t in tests), 'failed': failed}))\n"
)

_PASS_MODULE = (
    "import unittest\n"
    "class Test{name}(unittest.TestCase):\n"
    "    def test_{a}(self):\n"
    "        pass\n"
    "    def test_{b}(self):\n"
    "        pass\n"
)


def run_tool(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one sharding tool from the repo root and capture the outcome."""

    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def write_json(path: Path, payload: JsonValue) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def make_fixture(root: Path) -> list[str]:
    """Create a three-module passing fixture; return its sorted test IDs."""

    modules = {"test_alpha": ("Alpha", "one", "two"), "test_beta": ("Beta", "three", "four")}
    for filename, (name, a, b) in modules.items():
        (root / f"{filename}.py").write_text(
            _PASS_MODULE.format(name=name, a=a, b=b), encoding="utf-8"
        )
    (root / "test_gamma.py").write_text(
        "import unittest\n"
        "class TestGamma(unittest.TestCase):\n"
        "    def test_five(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    return sorted(
        [
            "test_alpha.TestAlpha.test_one",
            "test_alpha.TestAlpha.test_two",
            "test_beta.TestBeta.test_three",
            "test_beta.TestBeta.test_four",
            "test_gamma.TestGamma.test_five",
        ]
    )


def make_quarantine(path: Path, match: str = "test_gamma") -> None:
    write_json(
        path,
        {
            "version": 1,
            "entries": [
                {
                    "match": match,
                    "owner": "@rlaope",
                    "reason": "fixture shared state",
                    "added": "2026-01-01",
                }
            ],
        },
    )


def plan_fixture(root: Path, out: Path, match: str = "test_gamma", shards: int = 2) -> subprocess.CompletedProcess[str]:
    """Run plan.py against the fixture directory."""

    quarantine = root / "quarantine.json"
    timings = root / "timings.json"
    make_quarantine(quarantine, match)
    write_json(timings, {"version": 1, "durations": {}})
    return run_tool(
        PLAN_PY,
        "--shards",
        str(shards),
        "--durations",
        str(timings),
        "--quarantine",
        str(quarantine),
        "--out",
        str(out),
        "--start-dir",
        str(root),
    )


class PlanDeterminismTests(unittest.TestCase):
    """Identical inventory and timings must produce byte-identical plans."""

    def test_plan_is_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_fixture(root)
            # CI plans the Linux lanes at 2 shards and Windows at 4.
            for shards in (2, 4):
                with self.subTest(shards=shards):
                    first = root / f"plan-{shards}-a.json"
                    second = root / f"plan-{shards}-b.json"
                    for out in (first, second):
                        result = plan_fixture(root, out, shards=shards)
                        self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(first.read_bytes(), second.read_bytes())
                    self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["shard_count"], shards)

    def test_unknown_tests_get_stable_fallback_assignment(self) -> None:
        ids = tuple(f"mod{i:02d}.TestCase.test_x" for i in range(20))
        plan_a = plan_mod.build_plan(plan_mod.PlanningInputs(ids, {}, ()), 2)
        reversed_inputs = plan_mod.PlanningInputs(tuple(reversed(ids)), {}, ())
        plan_b = plan_mod.build_plan(reversed_inputs, 2)
        self.assertEqual(plan_a.shards, plan_b.shards)
        for shard in plan_a.shards:
            self.assertEqual(list(shard), sorted(shard))

    def test_shard0_offset_and_quarantine_seed_shift_load_deterministically(self) -> None:
        ids = tuple(f"mod{i:02d}.TestCase.test_x" for i in range(12))
        durations = {test_id: 10.0 for test_id in ids}
        quarantine = (plan_mod.QuarantineEntry("mod11", "@rlaope", "fixture shared state", "2026-01-01"),)
        inputs = plan_mod.PlanningInputs(ids, durations, quarantine)

        def loads(plan: plan_mod.Plan) -> list[float]:
            return [sum(durations[test_id] for test_id in shard) for shard in plan.shards]

        # No declared offset: only the 10 s quarantine is seeded, onto the
        # last shard, so that shard gets one fewer parallel test.
        self.assertEqual(loads(plan_mod.build_plan(inputs, 4)), [30.0, 30.0, 30.0, 20.0])
        # A 20 s shard-0 offset takes two tests (20 s) off shard 0; with the
        # seeds counted every shard carries 40 or 30 s.
        offset = plan_mod.build_plan(inputs, 4, shard0_offset=20.0)
        self.assertEqual(loads(offset), [20.0, 40.0, 30.0, 20.0])
        self.assertEqual(offset, plan_mod.build_plan(inputs, 4, shard0_offset=20.0))
        for bad in (-1.0, float("nan"), float("inf")):
            with self.subTest(offset=bad), self.assertRaises(plan_mod.ShardingError):
                plan_mod.build_plan(inputs, 4, shard0_offset=bad)

    def test_duplicate_inventory_fails_closed(self) -> None:
        duplicate = ("module.Case.test_one", "module.Case.test_one")
        with self.assertRaises(plan_mod.ShardingError):
            plan_mod.build_plan(plan_mod.PlanningInputs(duplicate, {}, ()), 2)

    def test_duration_aware_beats_count_balancing_on_uneven_fixture(self) -> None:
        durations = {f"t{i}": 100.0 for i in (1, 2, 3)}
        durations.update({f"t{i}": 10.0 for i in (4, 5, 6, 7, 8, 9)})
        lpt = plan_mod.lpt_partition(durations, 2)
        count = plan_mod.count_partition(sorted(durations), 2)

        def max_load(shards: list[list[str]]) -> float:
            return max(sum(durations[t] for t in shard) for shard in shards)

        self.assertLess(max_load(lpt), max_load(count))


class PlanFailureTests(unittest.TestCase):
    """Planning fails closed on broken discovery and stale quarantine."""

    def test_static_planning_never_imports_test_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_static.py").write_text(
                "raise RuntimeError('planning must not import this module')\n"
                "import unittest\n"
                "class StaticTests(unittest.TestCase):\n"
                "    def test_visible_to_static_inventory(self):\n"
                "        pass\n",
                encoding="utf-8",
            )
            quarantine = root / "quarantine.json"
            timings = root / "timings.json"
            write_json(quarantine, {"version": 1, "entries": []})
            write_json(timings, {"version": 1, "durations": {}})
            out = root / "plan.json"
            result = run_tool(
                PLAN_PY, "--shards", "2", "--durations", str(timings),
                "--quarantine", str(quarantine), "--out", str(out), "--start-dir", str(root),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                {test_id for shard in plan["shards"].values() for test_id in shard},
                {"test_static.StaticTests.test_visible_to_static_inventory"},
            )

    def test_static_discovery_failure_exits_nonzero_without_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_broken.py").write_text(
                "def broken(:\n", encoding="utf-8"
            )
            out = root / "plan.json"
            result = plan_fixture(root, out)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(out.exists())

    def test_stale_quarantine_entry_fails_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_fixture(root)
            out = root / "plan.json"
            result = plan_fixture(root, out, match="test_no_such_module")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("test_no_such_module", result.stderr)

    def test_dynamic_setattr_test_name_fails_static_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_dynamic.py").write_text(
                "import unittest\n"
                "class DynamicTests(unittest.TestCase):\n"
                "    def test_visible(self):\n"
                "        pass\n"
                "suffix = 'late'\n"
                "setattr(DynamicTests, f'test_{suffix}', lambda self: None)\n",
                encoding="utf-8",
            )
            result = plan_fixture(root, root / "plan.json", match="test_dynamic")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dynamically assigned test", result.stderr)

    def test_top_level_class_test_assignment_fails_static_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_assignment.py").write_text(
                "import unittest\n"
                "class AssignmentTests(unittest.TestCase):\n"
                "    def test_visible(self):\n"
                "        pass\n"
                "AssignmentTests.test_late = lambda self: None\n",
                encoding="utf-8",
            )
            result = plan_fixture(root, root / "plan.json", match="test_assignment")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dynamically assigned test", result.stderr)

    def test_boolean_timing_duration_fails_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_fixture(root)
            quarantine = root / "quarantine.json"
            make_quarantine(quarantine)
            write_json(root / "timings.json", {"version": 1, "durations": {"test_alpha.TestAlpha.test_one": True}})
            result = run_tool(
                PLAN_PY, "--shards", "2", "--durations", str(root / "timings.json"),
                "--quarantine", str(quarantine), "--out", str(root / "plan.json"),
                "--start-dir", str(root),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("durations", result.stderr)


class RealInventoryTests(unittest.TestCase):
    """The real suite inventory is assigned exactly once (issue #1294)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name) / "plan.json"
        result = run_tool(
            PLAN_PY,
            "--shards",
            "2",
            "--durations",
            str(REAL_TIMINGS),
            "--quarantine",
            str(REAL_QUARANTINE),
            "--out",
            str(out),
        )
        if result.returncode != 0:
            if "test discovery failed" in result.stderr:
                raise unittest.SkipTest(
                    "baseline discovery is broken by modules outside this change: "
                    + result.stderr.strip().splitlines()[0][:200]
                )
            raise AssertionError(f"plan.py failed on the real suite: {result.stderr}")
        cls.plan = json.loads(out.read_text(encoding="utf-8"))
        discovered = subprocess.run(
            [sys.executable, "-c", _DISCOVER_SNIPPET],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=True,
        )
        baseline = json.loads(discovered.stdout)
        if baseline["failed"]:
            raise unittest.SkipTest(
                "baseline discovery is broken by modules outside this change: "
                + ", ".join(baseline["failed"])
            )
        cls.inventory = set(baseline["ids"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def shard_lists(self) -> list[list[str]]:
        return [self.plan["shards"][key] for key in sorted(self.plan["shards"])]

    def test_every_discovered_test_assigned_exactly_once(self) -> None:
        sharded = [tid for shard in self.shard_lists() for tid in shard]
        quarantined = list(self.plan["quarantine"])
        assigned = sharded + quarantined
        self.assertEqual(len(assigned), len(set(assigned)), "duplicate assignment")
        self.assertEqual(set(assigned), self.inventory)
        counts = self.plan["counts"]
        self.assertEqual(counts["discovered"], len(self.inventory))
        self.assertEqual(counts["sharded"], len(sharded))
        self.assertEqual(counts["quarantined"], len(quarantined))

    def test_quarantined_tests_never_in_parallel_shards(self) -> None:
        quarantined = set(self.plan["quarantine"])
        self.assertTrue(quarantined, "quarantine must isolate the shared-state tests")
        for shard in self.shard_lists():
            self.assertFalse(quarantined.intersection(shard))

    def test_quarantine_entries_have_owner_and_reason(self) -> None:
        entries = plan_mod.load_quarantine(REAL_QUARANTINE)
        self.assertTrue(entries)
        for entry in entries:
            self.assertTrue(entry.owner.strip(), entry.match)
            self.assertTrue(entry.reason.strip(), entry.match)
            self.assertRegex(entry.added, r"^\d{4}-\d{2}-\d{2}$")


class RunShardTests(unittest.TestCase):
    """run.py executes exactly the planned IDs, fail-closed on failures."""

    def test_run_shards_and_quarantine_cover_fixture_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = make_fixture(root)
            plan_path = root / "plan.json"
            result = plan_fixture(root, plan_path)
            self.assertEqual(result.returncode, 0, result.stderr)

            executed: list[str] = []
            for extra in (("--shard", "0"), ("--shard", "1"), ("--quarantine",)):
                out = root / f"result-{'-'.join(extra)}.json"
                ran = run_tool(
                    RUN_PY,
                    "--plan",
                    str(plan_path),
                    "--lane",
                    "fixture",
                    *extra,
                    "--out",
                    str(out),
                    "--start-dir",
                    str(root),
                )
                self.assertEqual(ran.returncode, 0, ran.stderr)
                payload = json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(payload["failures"], [])
                self.assertEqual(payload["errors"], [])
                planned = payload["planned"]
                self.assertEqual(
                    sorted(payload["executed"] + payload["skipped"]), sorted(planned)
                )
                self.assertTrue(payload["durations"])
                executed.extend(payload["executed"] + payload["skipped"])
            self.assertEqual(sorted(executed), expected)

    def test_run_fails_closed_when_a_test_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_delta.py").write_text(
                "import unittest\n"
                "class TestDelta(unittest.TestCase):\n"
                "    def test_bad(self):\n"
                "        self.fail('boom')\n",
                encoding="utf-8",
            )
            plan_path = root / "plan.json"
            result = plan_fixture(root, plan_path, match="test_gamma")
            # No quarantined module in this fixture: point the quarantine at
            # nothing by using an empty entries file instead.
            write_json(root / "quarantine.json", {"version": 1, "entries": []})
            result = run_tool(
                PLAN_PY,
                "--shards",
                "1",
                "--durations",
                str(root / "timings.json"),
                "--quarantine",
                str(root / "quarantine.json"),
                "--out",
                str(plan_path),
                "--start-dir",
                str(root),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            out = root / "result.json"
            ran = run_tool(
                RUN_PY,
                "--plan",
                str(plan_path),
                "--lane",
                "fixture",
                "--shard",
                "0",
                "--out",
                str(out),
                "--start-dir",
                str(root),
            )
            self.assertNotEqual(ran.returncode, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["failures"], ["test_delta.TestDelta.test_bad"])


@dataclass(frozen=True, slots=True)
class ResultSpec:
    """One fabricated lane result used by aggregate failure tests."""

    kind: str
    shard: int | None
    planned: tuple[str, ...]
    executed: tuple[str, ...] | None = None
    failures: tuple[str, ...] = ()


class AggregateTests(unittest.TestCase):
    """aggregate.py reconciles each configured platform/version lane."""

    LANES = ("linux-3.11", "linux-3.12", "windows-3.12")

    def setUp(self) -> None:
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.plan_path = root / "plan.json"
        write_json(
            self.plan_path,
            {
                "version": 1,
                "shard_count": 2,
                "shards": {"0": ["a.A.t1"], "1": ["a.A.t2"]},
                "quarantine": ["a.A.t3"],
                "counts": {"discovered": 3, "sharded": 2, "quarantined": 1},
            },
        )
        self.quarantine_path = root / "quarantine.json"
        make_quarantine(self.quarantine_path, match="a")
        self.results = root / "results"
        self.results.mkdir()
        for lane in self.LANES:
            self._write_result(lane, "s0.json", ResultSpec("shard", 0, ("a.A.t1",)))
            self._write_result(lane, "s1.json", ResultSpec("shard", 1, ("a.A.t2",)))
            self._write_result(lane, "q.json", ResultSpec("quarantine", None, ("a.A.t3",)))

    def _write_result(self, lane: str, name: str, specification: ResultSpec) -> None:
        ran = specification.planned if specification.executed is None else specification.executed
        write_json(
            self.results / f"{lane}-{name}",
            {
                "version": 1,
                "lane": lane,
                "kind": specification.kind,
                "shard": specification.shard,
                "planned": list(specification.planned),
                "executed": list(ran),
                "skipped": [],
                "failures": list(specification.failures),
                "errors": [],
                "durations": {test_id: 0.1 for test_id in ran},
            },
        )

    def aggregate(self) -> subprocess.CompletedProcess[str]:
        return run_tool(
            AGGREGATE_PY, "--plan", str(self.plan_path), "--quarantine",
            str(self.quarantine_path), "--results-dir", str(self.results),
            "--lanes", ",".join(self.LANES),
        )

    def test_three_lane_results_pass_with_compact_report(self) -> None:
        result = self.aggregate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reconciled", result.stdout)
        self.assertIn("slowest", result.stdout)
        self.assertIn("performance", result.stdout)
        self.assertIn("linux-3.11", result.stdout)
        self.assertIn("windows-3.12", result.stdout)

    def test_merged_timings_become_next_planner_input(self) -> None:
        history = self.results.parent / "timings.json"
        result = run_tool(
            AGGREGATE_PY, "--plan", str(self.plan_path), "--quarantine",
            str(self.quarantine_path), "--results-dir", str(self.results),
            "--lanes", ",".join(self.LANES), "--timings-out", str(history),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(plan_mod.load_timings(history), {"a.A.t1": 0.1, "a.A.t2": 0.1, "a.A.t3": 0.1})

    def test_missing_plan_assignment_fails(self) -> None:
        plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        plan["counts"]["discovered"] = 4
        write_json(self.plan_path, plan)
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_missing_lane_result_fails(self) -> None:
        (self.results / "linux-3.12-s1.json").unlink()
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_duplicate_shard_within_lane_fails(self) -> None:
        self._write_result("linux-3.11", "s0-dup.json", ResultSpec("shard", 0, ("a.A.t1",)))
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_unexpected_shard_fails_aggregate(self) -> None:
        self._write_result("linux-3.11", "s2.json", ResultSpec("shard", 2, ()))
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_boolean_result_shard_and_duration_fail_at_json_boundary(self) -> None:
        result_path = self.results / "linux-3.11-s0.json"
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["shard"] = True
        write_json(result_path, payload)
        with self.assertRaises(plan_mod.ShardingError):
            aggregate_mod.load_result(result_path)
        payload["shard"] = 0
        payload["durations"]["a.A.t1"] = True
        write_json(result_path, payload)
        with self.assertRaises(plan_mod.ShardingError):
            aggregate_mod.load_result(result_path)

    def test_boolean_or_non_integer_plan_counts_fail_at_json_boundary(self) -> None:
        for value in (True, 3.0):
            with self.subTest(value=value):
                payload = json.loads(self.plan_path.read_text(encoding="utf-8"))
                payload["counts"]["discovered"] = value
                write_json(self.plan_path, payload)
                with self.assertRaises(plan_mod.ShardingError):
                    aggregate_mod.load_plan(self.plan_path)

    def test_failed_shard_fails_aggregate(self) -> None:
        self._write_result("linux-3.11", "s0.json", ResultSpec("shard", 0, ("a.A.t1",), failures=("a.A.t1",)))
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_missing_executed_test_fails_reconciliation(self) -> None:
        self._write_result("linux-3.11", "s0.json", ResultSpec("shard", 0, ("a.A.t1",), executed=()))
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_missing_quarantine_metadata_fails(self) -> None:
        write_json(
            self.quarantine_path,
            {"version": 1, "entries": [{"match": "a", "owner": "", "reason": "", "added": "x"}]},
        )
        self.assertNotEqual(self.aggregate().returncode, 0)


class LanePlanAggregateTests(unittest.TestCase):
    """A lane with its own shard count is reconciled against its own plan."""

    LINUX = ("linux-3.11", "linux-3.12")
    WINDOWS = "windows-3.12"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.plan_path = root / "plan.json"
        self.windows_plan_path = root / "plan-windows.json"
        self._write_plan(self.plan_path, {"0": ["a.A.t1", "a.A.t2"], "1": ["a.A.t3", "a.A.t4"]})
        self._write_plan(
            self.windows_plan_path,
            {"0": ["a.A.t1"], "1": ["a.A.t2"], "2": ["a.A.t3"], "3": ["a.A.t4"]},
        )
        self.quarantine_path = root / "quarantine.json"
        make_quarantine(self.quarantine_path, match="a")
        self.results = root / "results"
        self.results.mkdir()
        for lane in self.LINUX:
            self._write_result(lane, 0, ("a.A.t1", "a.A.t2"))
            self._write_result(lane, 1, ("a.A.t3", "a.A.t4"))
            self._write_result(lane, None, ("a.A.t5",))
        for shard, test_id in enumerate(("a.A.t1", "a.A.t2", "a.A.t3", "a.A.t4")):
            self._write_result(self.WINDOWS, shard, (test_id,))
        self._write_result(self.WINDOWS, None, ("a.A.t5",))

    @staticmethod
    def _write_plan(path: Path, shards: dict[str, list[str]], quarantine: tuple[str, ...] = ("a.A.t5",)) -> None:
        sharded = sum(len(tests) for tests in shards.values())
        write_json(
            path,
            {
                "version": 1,
                "shard_count": len(shards),
                "shards": shards,
                "quarantine": list(quarantine),
                "counts": {"discovered": sharded + len(quarantine), "sharded": sharded, "quarantined": len(quarantine)},
            },
        )

    def _write_result(self, lane: str, shard: int | None, tests: tuple[str, ...]) -> None:
        kind = "quarantine" if shard is None else "shard"
        write_json(
            self.results / f"{lane}-{kind}-{shard}.json",
            {
                "version": 1,
                "lane": lane,
                "kind": kind,
                "shard": shard,
                "planned": list(tests),
                "executed": list(tests),
                "skipped": [],
                "failures": [],
                "errors": [],
                "durations": {test_id: 0.1 for test_id in tests},
            },
        )

    def aggregate(self, *lane_plans: str) -> subprocess.CompletedProcess[str]:
        extra = [argument for lane_plan in lane_plans for argument in ("--lane-plan", lane_plan)]
        return run_tool(
            AGGREGATE_PY, "--plan", str(self.plan_path), "--quarantine",
            str(self.quarantine_path), "--results-dir", str(self.results),
            "--lanes", ",".join((*self.LINUX, self.WINDOWS)), *extra,
        )

    def windows_plan(self) -> str:
        return f"{self.WINDOWS}={self.windows_plan_path}"

    def test_four_shard_lane_reconciles_against_its_own_plan(self) -> None:
        result = self.aggregate(self.windows_plan())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("windows-3.12 (4 shards): 5 executed", result.stdout)
        self.assertIn("linux-3.11 (2 shards): 5 executed", result.stdout)

    def test_four_shard_results_fail_against_the_default_plan(self) -> None:
        result = self.aggregate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("windows-3.12", result.stderr)

    def test_missing_windows_shard_fails_aggregation(self) -> None:
        (self.results / f"{self.WINDOWS}-shard-3.json").unlink()
        result = self.aggregate(self.windows_plan())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing result for windows-3.12 shard 3", result.stderr)

    def test_missing_quarantine_result_fails_aggregation(self) -> None:
        # The quarantine now runs inside each lane's last shard job; losing
        # that step's result must still be red, not an empty quarantine.
        (self.results / f"{self.WINDOWS}-quarantine-None.json").unlink()
        result = self.aggregate(self.windows_plan())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing result for windows-3.12 quarantine", result.stderr)

    def test_quarantine_result_missing_a_test_fails_aggregation(self) -> None:
        self._write_result("linux-3.11", None, ())
        result = self.aggregate(self.windows_plan())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("linux-3.11 quarantine", result.stderr)

    def test_linux_lane_still_needs_every_default_shard(self) -> None:
        (self.results / "linux-3.12-shard-1.json").unlink()
        result = self.aggregate(self.windows_plan())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing result for linux-3.12 shard 1", result.stderr)

    def test_lane_plan_over_a_different_suite_fails(self) -> None:
        self._write_plan(self.windows_plan_path, {"0": ["a.A.t1"], "1": ["a.A.t2"], "2": ["a.A.t3"], "3": []})
        result = self.aggregate(self.windows_plan())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not cover the same tests", result.stderr)

    def test_lane_plan_with_a_different_quarantine_fails(self) -> None:
        self._write_plan(
            self.windows_plan_path,
            {"0": ["a.A.t1"], "1": ["a.A.t2"], "2": ["a.A.t3"], "3": ["a.A.t5"]},
            quarantine=("a.A.t4",),
        )
        result = self.aggregate(self.windows_plan())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not cover the same tests", result.stderr)

    def test_lane_plan_for_an_unrequired_lane_fails(self) -> None:
        result = self.aggregate(self.windows_plan(), f"macos-3.12={self.windows_plan_path}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("macos-3.12", result.stderr)

    def test_duplicate_or_malformed_lane_plan_fails(self) -> None:
        for lane_plans in ((self.windows_plan(), self.windows_plan()), ("windows-3.12",), (f"={self.windows_plan_path}",)):
            with self.subTest(lane_plans=lane_plans):
                self.assertNotEqual(self.aggregate(*lane_plans).returncode, 0)


if __name__ == "__main__":
    unittest.main()
