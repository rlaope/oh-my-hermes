from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from src.quality import cross_harness_adapters as runner
from src.quality.cross_harness_adapter_evidence import (
    CommandEvidence,
    SourceEvidence,
    adapter_request_payload,
    parse_adapter_evidence,
)
from src.quality.cross_harness_benchmark_values import JsonValue
from src.quality.cross_harness_adapter_model import (
    AdapterRequest,
    canonical_digest,
    parse_adapter_request,
)
from src.quality.cross_harness_adapters import (
    ExecutionSpec,
    run_adapter,
)

from _platform_support import requires_secure_dir_io


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "cross_harness_adapter"
FAKE = FIXTURES / "fake_adapter.py"


def _output(root: Path) -> runner.OutputContract:
    root = root.resolve()
    source_raw: dict[str, JsonValue] = {"source_id": "fixture-source", "commit": "a" * 40, "license": "MIT", "path_metadata": "fixtures/fake"}
    command_raw: dict[str, JsonValue] = {"command_id": "fixture-command", "harness": "fake", "argv": ["fake-adapter", "run"], "cwd_class": "disposable", "source_id": "fixture-source", "source_commit": "a" * 40, "expected_exit": 0, "expected_semantic_result": "pass"}
    source = SourceEvidence("fixture-source", "a" * 40, "MIT", "fixtures/fake", canonical_digest(source_raw))
    command = CommandEvidence("fixture-command", "fake", ("fake-adapter", "run"), "disposable", "fixture-source", "a" * 40, 0, "pass", canonical_digest(command_raw), 0, "pass")
    return runner.OutputContract(root / "receipt.json", root / "evidence.json", "fixture-harness", source, command)


def _request(argv: tuple[str, ...], **changes: JsonValue) -> AdapterRequest:
    raw: dict[str, JsonValue] = {
        "schema_version": "cross_harness_adapter_request/v1",
        "protocol_version": "cross_harness_adapter_protocol/v1",
        "corpus_digest": "0" * 64,
        "fixture_binding_digest": "1" * 64,
        "fixture_id": "fixture-a",
        "adapter_id": "fake-adapter",
        "capability_id": "sandbox-probe",
        "profile": "codex",
        "executable": Path(argv[0]).name,
        "executable_version": "fake-adapter 1.0",
        "model": "fixture-model",
        "effort": "none",
        "capabilities": ["tool-events", "child-events"],
        "argv_digest": canonical_digest(list(argv)),
        "repetition": 1,
        "timeout_seconds": 2,
    }
    raw.update(changes)
    return parse_adapter_request(raw)


def _spec(
    root: Path,
    scenario: str,
    *,
    backend: str = "sandbox-exec",
    environment: tuple[tuple[str, str], ...] = (),
) -> tuple[AdapterRequest, ExecutionSpec]:
    argv = (str(Path(sys.executable).resolve()), str(FAKE.resolve()), scenario)
    request = _request(argv)
    spec = ExecutionSpec(
        argv=argv,
        read_roots=(FIXTURES,),
        scratch_parent=root,
        backend=backend,
        environment=environment,
        version_argv=(argv[0], argv[1], "--version"),
    )
    return request, spec


def _passthrough_backend(argv: tuple[str, ...], *_args: Path | str | bool | tuple[Path, ...], **_kwargs: Path | str | bool | tuple[Path, ...]) -> tuple[str, ...]:
    return argv


def _scenario_diagnostics(outcome: runner.AdapterRunReceipt, elapsed: float) -> str:
    # When a scenario is misclassified the interesting facts are how long the
    # child lived and what the host does with a dying process (issue #1321:
    # `crash` read as `process_timeout` on Linux shards); put them in the
    # assertion message so a red run explains itself.
    core_pattern = Path("/proc/sys/kernel/core_pattern")
    pattern = core_pattern.read_text(encoding="utf-8").strip() if core_pattern.exists() else "n/a"
    rep = outcome.repetitions[0] if outcome.repetitions else None
    return (
        f"elapsed={elapsed:.2f}s core_pattern={pattern!r} "
        f"status={getattr(rep, 'process_status', None)} exit={getattr(rep, 'exit_code', None)} "
        f"group_terminated={getattr(rep, 'process_group_terminated', None)} "
        f"stdout_bytes={getattr(rep, 'stdout_bytes', None)} stderr_bytes={getattr(rep, 'stderr_bytes', None)}"
    )


class _RunnerMixin(unittest.TestCase):
    def _run_fake_adapter(self, request: AdapterRequest, spec: ExecutionSpec, output: runner.OutputContract) -> runner.AdapterRunReceipt:
        with patch("src.quality.cross_harness_adapters._backend_available", return_value=True), patch("src.quality.cross_harness_adapters._sandbox_command", _passthrough_backend), patch("src.quality.cross_harness_adapters._preflight", return_value=(True, "test-backend")):
            return run_adapter(request, spec, output)

    def _run(
        self,
        scenario: str,
        *,
        repetition: int = 1,
        timeout_seconds: int = 2,
        sandbox: bool = False,
        environment: tuple[tuple[str, str], ...] = (),
        read_roots: tuple[Path, ...] = (),
        allow_network: bool = False,
    ) -> runner.AdapterRunReceipt:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        allocator = root / "allocator"
        allocator.mkdir()
        request, spec = _spec(allocator, scenario)
        spec = ExecutionSpec(spec.argv, (*spec.read_roots, *read_roots), spec.scratch_parent, spec.backend, allow_network, environment, spec.version_argv)
        if repetition != 1 or timeout_seconds != 2:
            raw = adapter_request_payload(request)
            raw["repetition"] = repetition
            raw["timeout_seconds"] = timeout_seconds
            request = parse_adapter_request(raw)
        if sandbox:
            outcome = run_adapter(request, spec, _output(root))
        else:
            outcome = self._run_fake_adapter(request, spec, _output(root))
        self.assertEqual(tuple(allocator.iterdir()), ())
        if sandbox and sys.platform != "darwin":
            self.assertEqual((outcome.status, outcome.reason_code in {"sandbox_backend_unavailable", "sandbox_preflight_failed"}), ("unavailable", True))
            self.skipTest("requested OS sandbox backend is unavailable on this host")
        return outcome


@requires_secure_dir_io
class FailClosedAdapterRunnerTests(_RunnerMixin):
    def test_atomic_json_write_does_not_follow_predictable_temp_symlink(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "receipt.json"
            victim = root / "victim"
            victim.write_text("unchanged", encoding="utf-8")
            predictable = target.with_suffix(".json.tmp")
            predictable.symlink_to(victim)
            runner._write_json(target, {"status": "ok"})
            self.assertEqual((victim.read_text(encoding="utf-8"), json.loads(target.read_text(encoding="utf-8"))), ("unchanged", {"status": "ok"}))
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertTrue(predictable.is_symlink())

    def test_artifact_and_inventory_symlinks_fail_closed_without_reading_canary(self) -> None:
        with TemporaryDirectory() as temporary:
            canary = Path(temporary) / "outside-canary"
            canary.write_text("real-outside-secret", encoding="utf-8")
            for scenario, reason in (("artifact-symlink", "artifact_not_regular_file"), ("inventory-symlink", "unsafe_inventory_entry")):
                with self.subTest(scenario=scenario):
                    outcome = self._run(scenario, environment=(("OMH_FILE_CANARY", str(canary)),))
                    persisted = json.dumps(runner.runner_receipt_payload(outcome), sort_keys=True)
                    self.assertEqual(outcome.reason_code, reason)
                    self.assertNotIn("real-outside-secret", persisted)
                    self.assertNotIn(str(canary), persisted)
                    self.assertEqual(canary.read_text(encoding="utf-8"), "real-outside-secret")

    def _assert_descendant_is_killed(self, scenario: str, timeout_seconds: int = 2) -> runner.AdapterRunReceipt:
        with TemporaryDirectory() as temporary:
            pid_path = Path(temporary) / "descendant.pid"
            started = time.monotonic()
            outcome = self._run(scenario, timeout_seconds=timeout_seconds, environment=(("OMH_DESCENDANT_PID", str(pid_path)),))
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            self.assertTrue(outcome.repetitions[0].process_group_terminated)
            # The bound is the caller's own timeout plus a cleanup allowance,
            # not a constant: a hardcoded 4.0 was below the 5s timeout one
            # caller passes, so that test was asserting cleanup finished
            # sooner than the timeout it had just granted. It survived only
            # because a crash returns fast, and failed on a loaded runner at
            # 4.36s. The property under test is that teardown is bounded, not
            # that a shared runner is fast.
            self.assertLess(time.monotonic() - started, timeout_seconds + 2.0)
            return outcome

    def test_zero_exit_descendant_with_closed_stdio_is_killed(self) -> None:
        self._assert_descendant_is_killed("descendant-exit-closed")

    def test_zero_exit_descendant_with_inherited_stdio_is_killed(self) -> None:
        self._assert_descendant_is_killed("descendant-exit-inherited")

    def test_crashed_parent_descendant_is_killed(self) -> None:
        outcome = self._assert_descendant_is_killed("crash-descendant", timeout_seconds=5)
        self.assertEqual(outcome.reason_code, "process_crash")
        self.assertEqual(outcome.repetitions[0].exit_code, -signal.SIGABRT)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux dumpability syscall")
    def test_crash_fixture_disables_dumping_before_real_sigabrt(self) -> None:
        # Given a disposable Linux process with dumping explicitly enabled.
        code = """
import ctypes, os, runpy, sys
namespace = runpy.run_path(sys.argv[1])
prctl = ctypes.CDLL(None, use_errno=True).prctl
prctl.argtypes = (ctypes.c_int, *([ctypes.c_ulong] * 4))
prctl.restype = ctypes.c_int
assert prctl(4, 1, 0, 0, 0) == 0
assert prctl(3, 0, 0, 0, 0) == 1
real_abort = os.abort
def observe_abort():
    dumpable = prctl(3, 0, 0, 0, 0)
    print(dumpable, flush=True)
    if dumpable != 0:
        os._exit(91)
    real_abort()
os.abort = observe_abort
namespace["_abort"]()
"""
        with TemporaryDirectory() as temporary:
            # When the fixture aborts, inspect kernel state at the signal boundary.
            result = subprocess.run(
                [sys.executable, "-c", code, str(FAKE.resolve())],
                cwd=temporary, capture_output=True, timeout=5, check=False,
            )
        # Then the actual fatal signal remains, without invoking a dump collector.
        self.assertEqual(result.stdout, b"0\n")
        self.assertEqual(result.returncode, -signal.SIGABRT, result.stderr)

    def test_timed_out_parent_descendant_is_killed(self) -> None:
        self.assertEqual(self._assert_descendant_is_killed("timeout").reason_code, "process_timeout")

    def test_exact_receipt_and_replayable_evidence_are_persisted(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, spec = _spec(root / "allocator", "passing")
            (root / "allocator").mkdir()
            receipt = self._run_fake_adapter(request, spec, _output(root))
            receipt_raw = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
            evidence = parse_adapter_evidence(json.loads((root / "evidence.json").read_text(encoding="utf-8")))
            persisted = (root / "receipt.json").read_text(encoding="utf-8") + (root / "evidence.json").read_text(encoding="utf-8")
            self.assertEqual((receipt.status, evidence.schema_version), ("observed_success", "cross_harness_adapter_evidence/v1"))
            self.assertEqual(set(receipt_raw), {"schema_version", "status", "reason_code", "backend", "backend_version", "preflight", "network_allowed", "request_digest", "argv_digest", "version_spawn_digest", "cleanup_verified", "repetitions"})
            self.assertEqual(receipt_raw["repetitions"][0]["spawn_digest"], receipt.repetitions[0].spawn_digest)
            self.assertNotIn(str(root), persisted)
            self.assertNotIn("stdout_sample", persisted)

    def test_unavailable_persists_receipt_without_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = ("definitely-missing-adapter",)
            receipt = self._run_fake_adapter(_request(argv, executable_version="missing"), ExecutionSpec(argv, (FIXTURES,), root, "sandbox-exec"), _output(root))
            self.assertEqual((receipt.status, (root / "receipt.json").is_file(), (root / "evidence.json").exists()), ("unavailable", True, False))

    def test_cleanup_and_spawn_identity_are_observed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            self.assertFalse(runner._roots_absent((existing,)))
            existing.rmdir()
            allocator = root / "allocator"
            allocator.mkdir()
            canary = allocator / "version-canary"
            canary.write_text("unchanged", encoding="utf-8")
            request, spec = _spec(allocator, "passing", environment=(("OMH_VERSION_CANARY", str(canary)),))
            receipt = run_adapter(request, spec, _output(root))
            if sys.platform != "darwin":
                self.assertEqual((receipt.status, receipt.reason_code in {"sandbox_backend_unavailable", "sandbox_preflight_failed"}), ("unavailable", True))
                self.skipTest("requested OS sandbox backend is unavailable on this host")
            self.assertEqual((receipt.cleanup_verified, canary.read_text(encoding="utf-8"), tuple(allocator.iterdir())), (True, "unchanged", (canary,)))
            self.assertEqual((len(receipt.version_spawn_digest), len(receipt.repetitions[0].spawn_digest)), (64, 64))
    def test_missing_executable_and_backend_never_launch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = ("definitely-missing-adapter",)
            outcome = self._run_fake_adapter(_request(argv, executable_version="missing"), ExecutionSpec(argv, (FIXTURES,), root, "sandbox-exec"), _output(root))
            self.assertEqual((outcome.status, outcome.reason_code), ("unavailable", "executable_not_found"))

            request, spec = _spec(root, "passing", backend="missing")
            outcome = run_adapter(request, spec, _output(root))
            self.assertEqual((outcome.status, outcome.reason_code), ("unavailable", "sandbox_backend_unavailable"))
            self.assertFalse((root / "launched").exists())

    def test_a_write_only_backend_is_refused_even_where_it_is_available(self) -> None:
        """The Windows fence cannot narrow reads or stop the network, which this lane's policy needs."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, spec = _spec(root, "passing", backend="restricted-token")
            with patch("src.quality.cross_harness_adapters._backend_available", return_value=True):
                outcome = run_adapter(request, spec, _output(root))
            self.assertEqual((outcome.status, outcome.reason_code), ("unavailable", "sandbox_backend_unavailable"))
            self.assertFalse((root / "launched").exists())

    def test_preflight_failure_never_launches_adapter(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            allocator = root / "allocator"
            allocator.mkdir()
            sentinel = root / "launch-sentinel"
            request, spec = _spec(allocator, "passing", environment=(("OMH_LAUNCH_PROBE", str(sentinel)),))
            with patch("src.quality.cross_harness_adapters._backend_available", return_value=True), patch("src.quality.cross_harness_adapters._preflight", return_value=(False, "test-backend")):
                outcome = run_adapter(request, spec, _output(root))
            self.assertEqual(outcome.reason_code, "sandbox_preflight_failed")
            self.assertFalse(sentinel.exists())
            self.assertEqual(tuple(allocator.iterdir()), ())

    def test_timeout_crash_wrong_stale_and_misleading_zero_fail(self) -> None:
        expected = {
            "timeout": "process_timeout", "crash": "process_crash",
            "wrong-artifact": "wrong_artifact_type",
            "stale-artifact": "request_digest_mismatch",
            "preseed-stale": "stale_artifact",
            "misleading-zero": "artifact_missing",
        }
        for scenario, reason in expected.items():
            with self.subTest(scenario=scenario):
                # Only `timeout` has to finish inside the 2-second default; it
                # is the one scenario the deadline is the point of. The others
                # exit on their own, and `crash` in particular was read as
                # `process_timeout` on Linux CI shards under that budget on
                # five of seven runs (issue #1321), the same tightness the
                # crash-descendant test had already hit. They get the 5s
                # budget that test uses.
                started = time.monotonic()
                outcome = self._run(scenario, timeout_seconds=2 if scenario == "timeout" else 5)
                self.assertEqual(outcome.reason_code, reason, msg=_scenario_diagnostics(outcome, time.monotonic() - started))
                self.assertNotEqual(outcome.status, "observed_success")
                if scenario == "crash":
                    self.assertEqual(outcome.repetitions[0].exit_code, -signal.SIGABRT)
                if scenario == "timeout":
                    self.assertEqual((outcome.repetitions[0].process_group_terminated, outcome.repetitions[0].inventory[0].path), (True, "work/descendant-heartbeat"))

    def test_partial_child_or_flaky_repetition_blocks_success(self) -> None:
        partial = self._run("partial-child")
        flaky = self._run("flaky", repetition=2)
        self.assertEqual(partial.reason_code, "partial_child_failure")
        self.assertEqual((flaky.status, flaky.reason_code, len(flaky.repetitions)), ("observed_failed", "failed_child_event", 2))

    def test_interrupt_always_cleans_scratch_and_propagates(self) -> None:
        for _attempt in range(3):
            with TemporaryDirectory() as temporary:
                root = Path(temporary)
                request, spec = _spec(root, "passing")
                with patch("src.quality.cross_harness_adapters._sandbox_command", _passthrough_backend), patch(
                    "src.quality.cross_harness_adapters._preflight", return_value=(True, "test-backend")
                ), patch("src.quality.cross_harness_adapters._backend_available", return_value=True), patch("src.quality.cross_harness_adapters._observe_process", side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        run_adapter(request, spec, _output(root))
                self.assertEqual(tuple(root.iterdir()), ())

if __name__ == "__main__":
    unittest.main()
