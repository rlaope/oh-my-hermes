#!/usr/bin/env python3
# ─── How to run ───
# python tools/test_sharding/run.py --plan plan.json --lane linux-3.12 --shard 0 --out result.json
# python tools/test_sharding/run.py --plan plan.json --lane linux-3.12 --shard 0 --workers 4 --out result.json
# python tools/test_sharding/run.py --plan plan.json --lane linux-3.12 --quarantine --out result.json
"""Run exactly one planned shard or quarantine and record its lane-local result.

With `--workers N` (N > 1) a shard's tests run in N worker processes, one test
module at a time per worker, and the parent merges their outcomes into the same
result JSON the serial run writes. The quarantine always runs serially: it
holds the tests that are unsafe beside any other test.
"""

from __future__ import annotations

import argparse
import collections
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from typing import IO, Final
import unittest
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.test_sharding import JsonValue, ShardingError
from tools.test_sharding.aggregate import QUARANTINE_KEY, load_plan

_ExcInfo = tuple[type[BaseException], BaseException, types.TracebackType]

# Worker mode is internal: the parent spawns `run.py --worker` and talks to it
# over the worker's original stdin/stdout. Every protocol line carries this
# marker so anything else that reaches that pipe (a grandchild process that
# inherited the handle) is echoed as log output instead of parsed.
WORKER_FLAG: Final = "--worker"
PROTOCOL_MARKER: Final = b"@@omh-test-shard-worker@@ "


@dataclass(frozen=True, slots=True)
class ShardTarget:
    """The lane and plan entry this process owns."""

    lane: str
    kind: str
    shard: int | None


def flatten_suite(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    """Flatten a unittest suite to its leaf cases without changing ordering."""

    tests: list[unittest.TestCase] = []
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            tests.extend(flatten_suite(test))
        else:
            tests.append(test)
    return tests


class RecordingResult(unittest.TextTestResult):
    """Record outcomes and monotonic durations while unittest runs one suite."""

    def __init__(self, stream: unittest.runner._WritelnDecorator, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.outcomes: dict[str, str] = {}
        self.durations: dict[str, float] = {}
        self._started = 0.0

    def startTest(self, test: unittest.TestCase) -> None:
        self._started = time.monotonic()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        self.durations[test.id()] = time.monotonic() - self._started
        super().stopTest(test)

    def addSuccess(self, test: unittest.TestCase) -> None:
        self.outcomes[test.id()] = "passed"
        super().addSuccess(test)

    def addFailure(self, test: unittest.TestCase, err: _ExcInfo) -> None:
        self.outcomes[test.id()] = "failure"
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: _ExcInfo) -> None:
        self.outcomes[test.id()] = "error"
        super().addError(test, err)

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        self.outcomes[test.id()] = "skipped"
        super().addSkip(test, reason)

    def addExpectedFailure(self, test: unittest.TestCase, err: _ExcInfo) -> None:
        self.outcomes[test.id()] = "passed"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        self.outcomes[test.id()] = "failure"
        super().addUnexpectedSuccess(test)


def load_plan_ids(plan_path: Path, shard: int | None) -> tuple[str, list[str]]:
    """Select one fully validated shard list or serial quarantine list."""

    assignments = load_plan(plan_path)
    if shard is None:
        return "quarantine", list(assignments[QUARANTINE_KEY])
    planned = assignments.get(shard)
    if planned is None:
        raise ShardingError(f"plan has no shard {shard}")
    return "shard", list(planned)


def load_suite(test_ids: list[str], start_dir: Path) -> unittest.TestSuite:
    """Import and load only planned IDs, rejecting any mismatch before running."""

    resolved = str(start_dir.resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
    try:
        suite = unittest.TestLoader().loadTestsFromNames(test_ids)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ShardingError(f"could not load planned tests: {exc}") from exc
    loaded = sorted(test.id() for test in flatten_suite(suite))
    if loaded != sorted(test_ids):
        raise ShardingError(f"planned tests failed to load: {sorted(set(test_ids) - set(loaded))}")
    return suite


def result_payload(target: ShardTarget, planned: list[str], recorded: dict[str, str], timed: dict[str, float]) -> dict[str, JsonValue]:
    """Build the lane-identified JSON contract consumed by the aggregate."""

    outcomes: dict[str, list[str]] = {name: [] for name in ("passed", "skipped", "failure", "error")}
    for test_id, outcome in recorded.items():
        outcomes[outcome].append(test_id)
    durations = {
        test_id: round(seconds, 6)
        for test_id, seconds in timed.items()
        if recorded.get(test_id) != "skipped"
    }
    return {
        "version": 1,
        "lane": target.lane,
        "kind": target.kind,
        "shard": target.shard,
        "planned": sorted(planned),
        "executed": sorted(outcomes["passed"]),
        "skipped": sorted(outcomes["skipped"]),
        "failures": sorted(outcomes["failure"]),
        "errors": sorted(outcomes["error"]),
        "durations": dict(sorted(durations.items())),
    }


def plan_units(suite: unittest.TestSuite) -> list[tuple[str, ...]]:
    """Group loaded tests into worker units: one unit per test module, in plan order.

    A module is the smallest unit that keeps every class fixture, module
    fixture, and module-level global inside one process; splitting finer
    would run a module's fixtures in several processes at once.
    """

    units: dict[str, list[str]] = {}
    for test in flatten_suite(suite):
        units.setdefault(type(test).__module__, []).append(test.id())
    return [tuple(ids) for ids in units.values()]


def send_message(channel: IO[bytes], message: dict[str, JsonValue]) -> None:
    channel.write(PROTOCOL_MARKER + json.dumps(message, sort_keys=True).encode("utf-8") + b"\n")
    channel.flush()


class WorkerResult(RecordingResult):
    """A RecordingResult that tells the parent which test is running."""

    channel: IO[bytes]

    def startTest(self, test: unittest.TestCase) -> None:
        send_message(self.channel, {"started": test.id()})
        super().startTest(test)


def run_unit(test_ids: list[str], channel: IO[bytes]) -> dict[str, JsonValue]:
    """Run one unit inside a worker the way TextTestRunner runs a suite."""

    stream = unittest.runner._WritelnDecorator(sys.stderr)
    result = WorkerResult(stream, True, 1)
    result.channel = channel
    try:
        suite = unittest.TestLoader().loadTestsFromNames(test_ids)
    except Exception as exc:  # noqa: BLE001 - every test of the unit is reported as an error
        print(f"test sharding worker: could not load {test_ids[0]}: {exc!r}", file=sys.stderr)
        return {"outcomes": {test_id: "error" for test_id in test_ids}, "durations": {}, "failures": 0, "errors": len(test_ids)}
    with warnings.catch_warnings():
        if not sys.warnoptions:
            warnings.simplefilter("default")
        result.startTestRun()
        try:
            suite(result)
        finally:
            result.stopTestRun()
    if result.errors or result.failures or result.unexpectedSuccesses:
        result.printErrors()
    stream.flush()
    # The counts are what the serial runner's exit code reads: a failed
    # subTest or a class fixture error is counted there without an outcome
    # for a planned ID, so the outcomes alone would under-report.
    return {
        "outcomes": dict(result.outcomes),
        "durations": dict(result.durations),
        "failures": len(result.failures),
        "errors": len(result.errors),
    }


def worker_main(start_dir: Path) -> int:
    """Serve units from the parent until it closes the worker's stdin."""

    # Keep private, non-inheritable copies of the protocol pipes, then point
    # fds 0 and 1 away from them, so neither a test nor a process it spawns
    # can read a unit assignment or write into the result channel.
    inbox = os.fdopen(os.dup(0), "rb")
    channel = os.fdopen(os.dup(1), "wb")
    sys.stdout.flush()
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    os.dup2(2, 1)
    resolved = str(start_dir.resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
    for raw in inbox:
        send_message(channel, {"unit": run_unit(json.loads(raw), channel)})
    return 0


def worker_command(start_dir: Path) -> list[str]:
    """The interpreter command for one worker; `-P` keeps the cwd off sys.path."""

    return [sys.executable, "-P", str(Path(__file__).resolve()), WORKER_FLAG, "--start-dir", str(start_dir.resolve())]


@dataclass(slots=True)
class MergedRun:
    """Every worker's outcomes, merged so each test ID is recorded once."""

    outcomes: dict[str, str] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    failures: int = 0
    errors: int = 0


class WorkerPool:
    """Hand units to worker processes one at a time and merge what they report."""

    def __init__(self, units: list[tuple[str, ...]], command: list[str]) -> None:
        self.pending = collections.deque(units)
        self.command = command
        self.lock = threading.Lock()
        self.merged = MergedRun()

    def next_unit(self) -> tuple[str, ...] | None:
        with self.lock:
            return self.pending.popleft() if self.pending else None

    def record(self, report: dict[str, JsonValue]) -> None:
        with self.lock:
            for test_id, outcome in report["outcomes"].items():
                if test_id in self.merged.outcomes:
                    self.merged.outcomes[test_id] = "error"
                    self.merged.errors += 1
                    self.merged.problems.append(f"{test_id} was reported by more than one worker")
                else:
                    self.merged.outcomes[test_id] = outcome
            self.merged.durations.update(report["durations"])
            self.merged.failures += report["failures"]
            self.merged.errors += report["errors"]

    def lost(self, unit: tuple[str, ...], reason: str) -> None:
        """Record every test of a unit that no worker reported as an error."""

        with self.lock:
            self.merged.problems.append(f"{reason}; recording its {len(unit)} unreported tests as errors")
            for test_id in unit:
                self.merged.outcomes.setdefault(test_id, "error")
            self.merged.errors += len(unit)

    def drive(self, index: int) -> None:
        """Own one worker process for its lifetime, in its own temp root."""

        temp_root = tempfile.mkdtemp(prefix=f"omh-shard-worker-{index}-")
        env = dict(os.environ, TMPDIR=temp_root, TEMP=temp_root, TMP=temp_root)
        proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        try:
            while (unit := self.next_unit()) is not None:
                reply, running = exchange(proc, unit)
                if reply is None:
                    code = proc.wait()
                    where = f" while running {running}" if running else ""
                    self.lost(unit, f"worker {index} exited with code {code}{where} before reporting {unit[0].rsplit('.', 2)[0]}")
                    return
                self.record(reply)
            assert proc.stdin is not None
            proc.stdin.close()
            code = proc.wait()
            if code != 0:
                with self.lock:
                    self.merged.problems.append(f"worker {index} exited with code {code} after its last unit")
                    self.merged.outcomes[f"run.py worker {index} (exit code {code})"] = "error"
                    self.merged.errors += 1
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            shutil.rmtree(temp_root, ignore_errors=True)


def exchange(proc: subprocess.Popen[bytes], unit: tuple[str, ...]) -> tuple[dict[str, JsonValue] | None, str | None]:
    """Send one unit and read until its report (None when the worker dies first)."""

    assert proc.stdin is not None and proc.stdout is not None
    running: str | None = None
    try:
        proc.stdin.write(json.dumps(list(unit)).encode("utf-8") + b"\n")
        proc.stdin.flush()
    except OSError:
        return None, running
    for raw in iter(proc.stdout.readline, b""):
        if not raw.startswith(PROTOCOL_MARKER):
            sys.stderr.buffer.write(raw)
            sys.stderr.buffer.flush()
            continue
        message = json.loads(raw[len(PROTOCOL_MARKER):])
        if "started" in message:
            running = message["started"]
        elif "unit" in message:
            return message["unit"], running
    return None, running


def run_parallel(units: list[tuple[str, ...]], workers: int, command: list[str]) -> MergedRun:
    """Run units across `workers` processes; every test left unreported is an error."""

    pool = WorkerPool(units, command)
    threads = [threading.Thread(target=pool.drive, args=(index,), daemon=True) for index in range(min(workers, len(units)))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Every worker died before the queue drained: nothing will report these.
    while (unit := pool.next_unit()) is not None:
        pool.lost(unit, f"no live worker was left to run {unit[0].rsplit('.', 2)[0]}")
    return pool.merged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--lane", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--shard", type=int)
    target.add_argument("--quarantine", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start-dir", type=Path, default=Path("tests"))
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=1,
        help="worker processes for a shard (default 1: serial, in this process); the quarantine always runs serially",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute the selected lane-local test list and fail on test failures."""

    raw = sys.argv[1:] if argv is None else argv
    if raw[:1] == [WORKER_FLAG]:
        worker = argparse.ArgumentParser(prog="run.py --worker")
        worker.add_argument("--start-dir", type=Path, required=True)
        return worker_main(worker.parse_args(raw[1:]).start_dir)
    args = _parser().parse_args(raw)
    if not args.lane.strip():
        print("test sharding: lane must be non-empty", file=sys.stderr)
        return 2
    if args.workers < 1:
        print("test sharding: --workers must be at least 1", file=sys.stderr)
        return 2
    shard = None if args.quarantine else args.shard
    try:
        kind, planned = load_plan_ids(args.plan, shard)
        suite = load_suite(planned, args.start_dir)
    except ShardingError as exc:
        print(f"test sharding: {exc}", file=sys.stderr)
        return 2
    target = ShardTarget(args.lane, kind, shard)
    if args.workers == 1 or kind == "quarantine":
        result = unittest.TextTestRunner(resultclass=RecordingResult, verbosity=1).run(suite)
        payload = result_payload(target, planned, result.outcomes, result.durations)
        failures, errors = len(result.failures), len(result.errors)
    else:
        started = time.monotonic()
        merged = run_parallel(plan_units(suite), args.workers, worker_command(args.start_dir))
        payload = result_payload(target, planned, merged.outcomes, merged.durations)
        for problem in merged.problems:
            print(f"test sharding: {problem}", file=sys.stderr)
        failures, errors = merged.failures, merged.errors
        print(f"test sharding: {len(merged.outcomes)} results from {args.workers} workers in {time.monotonic() - started:.1f}s", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures or errors:
        print(f"test sharding: {failures} failures, {errors} errors", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
