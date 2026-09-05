from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from _credential_fixtures import AWS_ACCESS_KEY_ID
from src.quality import cross_harness_adapter_io as adapter_io
from src.quality.cross_harness_adapter_sandbox import ChildContext, ProcessObservation, environment_is_safe, observe_process, preflight, sandbox_command
from src.quality.cross_harness_adapters import ExecutionSpec, _artifact_result, runner_receipt_payload
from tests.test_cross_harness_adapters import ROOT, _RunnerMixin, _output, _request, _spec

from _platform_support import requires_posix, requires_secure_dir_io


def _kill_group(process_id: int) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process_id, signal.SIGKILL)


def _capture_inventory_error(root: Path, errors: list[OSError]) -> None:
    try:
        adapter_io.inventory(root, set())
    except OSError as error:
        errors.append(error)


def _fifo_call_completes(call: Callable[[], None], fifo: Path) -> bool:
    worker = Thread(target=call, daemon=True)
    worker.start()
    worker.join(0.2)
    completed = not worker.is_alive()
    if not completed:
        writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(writer)
        worker.join(1)
    return completed


class AdapterSandboxSecurityTests(_RunnerMixin, unittest.TestCase):
    @requires_posix
    def test_keyboard_interrupt_during_real_wait_cleans_exact_process_and_streams(self) -> None:
        created: list[subprocess.Popen[bytes]] = []

        def interrupting_factory(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            created.append(process)
            self.addCleanup(_kill_group, process.pid)
            original_wait = process.wait
            interrupted = False

            def interrupt_once(timeout=None):
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt
                return original_wait(timeout=timeout)

            process.wait = interrupt_once
            return process

        with TemporaryDirectory() as temporary, self.assertRaises(KeyboardInterrupt):
            observe_process((sys.executable, "-c", "import signal; signal.pause()"), Path(temporary), os.environ, 2, interrupting_factory)
        process = created[0]
        with self.assertRaises(ProcessLookupError):
            os.kill(process.pid, 0)
        self.assertEqual((process.stdout is not None and process.stdout.closed, process.stderr is not None and process.stderr.closed), (True, True))

    @requires_posix
    def test_fifo_device_and_socket_artifacts_and_inventory_fail_without_blocking(self) -> None:
        observation = ProcessObservation("exit", 0, True, "0" * 64, 0, "0" * 64, 0, b"", b"", False)
        request = _request(("fake-adapter",))
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fifo = root / "artifact-fifo"
            os.mkfifo(fifo)
            artifact: list[tuple[object, str]] = []
            self.assertTrue(_fifo_call_completes(lambda: artifact.append(_artifact_result(fifo, request, "0" * 64, observation, 0)), fifo))
            self.assertEqual(artifact[0][1], "artifact_not_regular_file")

            socket_path = root / "artifact-socket"
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(socket_path))
                for path in (Path("/dev/null"), socket_path):
                    with self.subTest(path=path.name):
                        self.assertEqual(_artifact_result(path, request, "0" * 64, observation, 0)[1], "artifact_not_regular_file")

                inventory_root = root / "inventory"
                inventory_root.mkdir()
                inventory_fifo = inventory_root / "fifo"
                os.mkfifo(inventory_fifo)
                inventory_errors: list[OSError] = []
                self.assertTrue(_fifo_call_completes(lambda: _capture_inventory_error(inventory_root, inventory_errors), inventory_fifo))
                self.assertEqual((len(inventory_errors), type(inventory_errors[0])), (1, adapter_io.UnsafeRegularFileError))
                _capture_inventory_error(Path("/dev/null"), inventory_errors)
                self.assertTrue(all(isinstance(error, adapter_io.UnsafeRegularFileError) for error in inventory_errors))
                inventory_fifo.unlink()
                with socket.socket(socket.AF_UNIX) as inventory_listener:
                    inventory_listener.bind(str(inventory_root / "socket"))
                    with self.assertRaises(adapter_io.UnsafeRegularFileError):
                        adapter_io.inventory(inventory_root, set())

    def test_atomic_output_rejects_symlinked_ancestors_without_external_write(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked"
            linked.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(adapter_io.UnsafeRegularFileError):
                adapter_io.write_json(linked / "nested" / "receipt.json", {"status": "blocked"})
            self.assertEqual(tuple(outside.iterdir()), ())

    def test_secret_shaped_values_are_rejected_but_numeric_listener_values_are_allowed(self) -> None:
        rejected = (
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            AWS_ACCESS_KEY_ID,
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
            "Bearer opaque-credential",
            "-----BEGIN PRIVATE KEY-----",
        )
        for value in rejected:
            with self.subTest(value=value[:8]):
                self.assertFalse(environment_is_safe((("OMH_LISTENER_VALUE", value),)))
        self.assertTrue(environment_is_safe((("OMH_NETWORK_PORT", "54321"),)))

    @requires_secure_dir_io
    def test_ambient_credentials_are_stripped_and_requested_credentials_rejected(self) -> None:
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "ambient-secret"}):
            outcome = self._run("environment-clean")
        self.assertEqual(outcome.status, "observed_success")

        with TemporaryDirectory() as temporary:
            request, spec = _spec(Path(temporary), "passing", environment=(("GITHUB_TOKEN", "secret"),))
            outcome = self._run_fake_adapter(request, spec, _output(Path(temporary)))
        self.assertEqual(outcome.reason_code, "credential_environment_rejected")

    @requires_secure_dir_io
    def test_real_home_credentials_are_unreadable(self) -> None:
        with TemporaryDirectory() as temporary:
            sentinel = Path(temporary) / "credential.txt"
            sentinel.write_text("sentinel-secret", encoding="utf-8")
            outcome = self._run("credential-read-denied", sandbox=True, environment=(("OMH_READ_PROBE", str(sentinel)),))
            self.assertEqual(outcome.status, "observed_success")

    @requires_secure_dir_io
    def test_default_network_and_outside_scratch_write_are_denied(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            network = self._run("network-denied", sandbox=True, environment=(("OMH_NETWORK_PORT", str(port)),))
            allowed = self._run("network-allowed", sandbox=True, environment=(("OMH_NETWORK_PORT", str(port)),), allow_network=True)
        outside = self._run("outside-write-denied", sandbox=True)
        self.assertEqual((network.status, allowed.status, outside.status, allowed.network_allowed), ("observed_success", "observed_success", "observed_success", True))

    @unittest.skipUnless(sys.platform == "darwin", "sandbox-exec is macOS-only")
    def test_macos_default_process_exec_policy_remains_strict(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            child = ChildContext(
                root,
                root / "home",
                root / "work",
                root / "tmp",
                root / "output",
                root / "request.json",
                root / "output" / "result.json",
                "f" * 64,
            )
            policy = sandbox_command(
                ("/bin/sh", "-c", "exit 0"), "sandbox-exec", (), child, False, {}
            )[2]

        self.assertNotIn("(allow process-exec*)", policy)
        self.assertNotIn("(allow file-read*)", policy)
        self.assertIn(
            '(allow process-exec (literal "/bin/sh") (literal "/usr/bin/true") '
            '(literal "/bin/bash"))',
            policy,
        )

    @unittest.skipUnless(sys.platform == "darwin", "sandbox-exec is macOS-only")
    def test_macos_session_and_process_group_escape_syscalls_are_denied(self) -> None:
        outcome = self._run("session-escape-denied", sandbox=True)
        self.assertEqual(outcome.status, "observed_success")

    @requires_secure_dir_io
    def test_dirty_worktree_is_not_observed_or_modified(self) -> None:
        dirty = ROOT / "task2-dirty-sentinel.txt"
        dirty.write_text("owned-by-test", encoding="utf-8")
        self.addCleanup(dirty.unlink)
        outcome = self._run("dirty-worktree-denied", sandbox=True, environment=(("OMH_DIRTY_PROBE", str(dirty)),))
        self.assertEqual(outcome.status, "observed_success")
        self.assertEqual(dirty.read_text(encoding="utf-8"), "owned-by-test")

    @requires_secure_dir_io
    def test_stdout_and_stderr_are_hash_only_and_bounded(self) -> None:
        outcome = self._run("noisy")
        repetition = outcome.repetitions[0]
        self.assertEqual(outcome.status, "observed_success")
        self.assertEqual(len(repetition.stdout_hash), 64)
        self.assertGreater(repetition.stdout_bytes, 0)
        self.assertLessEqual(repetition.stdout_bytes, 1_048_576)
        self.assertFalse(hasattr(repetition, "stdout"))

        oversized = self._run("oversized-output")
        receipt = oversized.repetitions[0]
        self.assertEqual(oversized.reason_code, "output_limit_exceeded")
        self.assertGreater(receipt.stdout_bytes, 1_048_576)
        self.assertGreater(receipt.stderr_bytes, 1_048_576)
        self.assertNotEqual(receipt.stdout_hash, receipt.stderr_hash)

    @requires_secure_dir_io
    def test_scratch_write_fd_closure_and_literal_argv(self) -> None:
        written = self._run("scratch-write", sandbox=True)
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        os.set_inheritable(read_fd, True)
        closed = self._run("fd-denied", environment=(("OMH_FD_PROBE", str(read_fd)),))
        injected = self._run("passing;touch outside")
        self.assertEqual((written.status, closed.status, injected.status), ("observed_success",) * 3)
        self.assertEqual(written.repetitions[0].inventory[0].path, "work/product.bin")

    @requires_secure_dir_io
    def test_symlink_escape_is_denied_and_symlinked_sensitive_root_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "allowed"
            allowed.mkdir()
            secret = root / "secret"
            secret.write_text("sentinel-secret", encoding="utf-8")
            linked = allowed / "linked"
            linked.symlink_to(secret)
            outcome = self._run("credential-read-denied", sandbox=True, environment=(("OMH_READ_PROBE", str(linked)),), read_roots=(allowed,))
            self.assertEqual(outcome.status, "observed_success")

            request, spec = _spec(root, "passing")
            sensitive_link = root / "sensitive"
            sensitive_link.symlink_to(Path.home() / ".ssh")
            rejected = self._run_fake_adapter(request, ExecutionSpec(spec.argv, (sensitive_link,), root, spec.backend), _output(root))
            self.assertEqual(rejected.reason_code, "unsafe_read_root")

    @requires_posix
    def test_linux_command_is_strict_and_missing_backend_fails_closed(self) -> None:
        child = ChildContext(Path("/tmp/scratch"), Path("/tmp/scratch/home"), Path("/tmp/scratch/work"), Path("/tmp/scratch/tmp"), Path("/tmp/scratch/output"), Path("/tmp/scratch/request.json"), Path("/tmp/scratch/output/result.json"), "f" * 64)
        environment = {"HOME": "/tmp/scratch/home", "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"}
        with patch("src.quality.cross_harness_adapter_sandbox._trusted_bwrap", return_value="/usr/bin/bwrap"):
            command = sandbox_command(("/opt/runtime/bin/tool", "run"), "bwrap", (Path("/opt/fixtures"),), child, False, environment)
        expected = ("/usr/bin/bwrap", "--unshare-user", "--unshare-ipc", "--unshare-pid", "--unshare-net", "--unshare-uts", "--disable-userns", "--new-session", "--die-with-parent", "--clearenv", "--tmpfs", "/", "--ro-bind", "/opt/fixtures", "/opt/fixtures", "--ro-bind", "/opt/runtime/bin", "/opt/runtime/bin", "--bind", "/tmp/scratch", "/tmp/scratch", "--chdir", "/tmp/scratch/work", "--setenv", "HOME", "/tmp/scratch/home", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "PYTHONNOUSERSITE", "1", "--", "/opt/runtime/bin/tool", "run")
        self.assertEqual(command, expected)
        self.assertFalse(any("try" in part or part in {str(Path.home()), "--share-net"} for part in command))

    def test_linux_owner_state_write_root_is_writable_without_broadening_reads(self) -> None:
        child = ChildContext(Path("/tmp/scratch"), Path("/tmp/scratch/home"), Path("/tmp/scratch/work"), Path("/tmp/scratch/tmp"), Path("/tmp/scratch/output"), Path("/tmp/scratch/request.json"), Path("/tmp/scratch/output/result.json"), "f" * 64)
        environment = {"HOME": "/tmp/scratch/home", "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"}
        with patch("src.quality.cross_harness_adapter_sandbox._trusted_bwrap", return_value="/usr/bin/bwrap"):
            command = sandbox_command(
                ("/opt/runtime/bin/tool", "run"), "bwrap", (Path("/opt/fixtures"),), child, False, environment,
                write_roots=(Path("/home/operator/.claude"),),
                write_literals=(Path("/home/operator/.claude.json"),),
            )
        self.assertIn("--bind-try", command)
        state_index = command.index("--bind-try")
        state = str(Path("/home/operator/.claude").resolve())
        state_file = str(Path("/home/operator/.claude.json").resolve())
        self.assertEqual(command[state_index:state_index + 6], ("--bind-try", state, state, "--bind-try", state_file, state_file))
        self.assertNotIn("--ro-bind", command[state_index:])

    def test_ambient_path_bwrap_is_never_executed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            sentinel = root / "ambient-bwrap-ran"
            fake = fake_bin / "bwrap"
            fake.write_text(f"#!/bin/sh\ntouch {sentinel}\n", encoding="utf-8")
            fake.chmod(0o700)
            child_root = root / "child"
            child_root.mkdir()
            child = ChildContext(child_root, *(child_root / name for name in ("home", "work", "tmp", "output")), child_root / "request.json", child_root / "output/result.json", "f" * 64)
            for directory in (child.home, child.work, child.temporary, child.output):
                directory.mkdir()
            with patch.dict(os.environ, {"PATH": str(fake_bin)}), patch(
                "src.quality.cross_harness_adapter_backend._TRUSTED_BWRAP_CANDIDATES",
                (root / "missing-bwrap",),
            ):
                ready, _digest = preflight("bwrap", (), child, False, {"PATH": str(fake_bin)})
            self.assertFalse(ready)
            self.assertFalse(sentinel.exists())

    def test_writable_temp_self_swapping_bwrap_candidate_is_never_launched(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            sentinel = root / "self-swap-ran"
            fake = root / "bwrap"
            fake.write_text(f"#!/bin/sh\nprintf changed > {fake}\ntouch {sentinel}\n", encoding="utf-8")
            fake.chmod(0o700)
            child_root = root / "child"
            child_root.mkdir()
            child = ChildContext(child_root, *(child_root / name for name in ("home", "work", "tmp", "output")), child_root / "request.json", child_root / "output/result.json", "f" * 64)
            for directory in (child.home, child.work, child.temporary, child.output):
                directory.mkdir()
            with patch("src.quality.cross_harness_adapter_backend._TRUSTED_BWRAP_CANDIDATES", (fake,)):
                ready, _digest = preflight("bwrap", (), child, False, {"PATH": "/usr/bin:/bin"})
            self.assertFalse(ready)
            self.assertFalse(sentinel.exists())

    @requires_secure_dir_io
    def test_version_cleanup_verification_failure_fails_closed(self) -> None:
        with patch("src.quality.cross_harness_adapter_sandbox.terminate_process_group", return_value=False):
            outcome = self._run("passing")
        serialized = runner_receipt_payload(outcome)
        self.assertEqual((outcome.status, outcome.reason_code, outcome.cleanup_verified, serialized["cleanup_verified"]), ("unavailable", "process_cleanup_failed", False, False))

    @requires_secure_dir_io
    def test_repetition_cleanup_verification_failure_blocks_success(self) -> None:
        with patch("src.quality.cross_harness_adapter_sandbox.terminate_process_group", side_effect=(True, False)):
            outcome = self._run("passing")
        serialized = runner_receipt_payload(outcome)
        self.assertEqual((outcome.status, outcome.reason_code, outcome.cleanup_verified, serialized["cleanup_verified"]), ("observed_failed", "process_cleanup_failed", False, False))

    @requires_secure_dir_io
    def test_unsafe_read_roots_fail_before_launch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, spec = _spec(root, "passing")
            for unsafe in (Path("/"), Path.home(), Path.home() / ".ssh"):
                with self.subTest(unsafe=unsafe.name):
                    candidate = ExecutionSpec(spec.argv, (unsafe,), root, spec.backend)
                    outcome = self._run_fake_adapter(request, candidate, _output(root))
                    self.assertEqual(outcome.reason_code, "unsafe_read_root")


if __name__ == "__main__":
    unittest.main()
