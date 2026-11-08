"""Real protocol/identity regression for portable fixture launch transport."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from _local_package import load_local_package
load_local_package()
from _verification_python import SHORT_INTERPRETER_CHARS
from omh.coding.executor_readiness import negotiate_session_capability, observe_session_binary
from omh.coding.fanout_capacity import AdmissionBinding, OwnerLaunchGate
from omh.coding.fanout_dispatch import signal_safe_unit_runner
import five_issue_process_fixture as fixture
from five_issue_cases.sessions import decode, record


class FixtureTransportTests(unittest.TestCase):
    def test_fixture_environment_keeps_system_bootstrap_without_user_state(self) -> None:
        system = {'SYSTEMROOT': r'C:\Windows', 'WINDIR': r'C:\Windows',
                  'COMSPEC': r'C:\Windows\System32\cmd.exe', 'PATHEXT': '.COM;.EXE;.BAT;.CMD'}
        with patch.dict(os.environ, {**system, 'HOME': 'private-home',
                                     'APPDATA': 'private-state', 'AWS_SECRET_ACCESS_KEY': 'private'}, clear=True):
            environment = fixture.fixture_system_environment()
        self.assertEqual(environment, system)

    def test_protocol_and_identity_survive_interpreter_transport(self) -> None:
        # Given a Python implementation of the real fixture protocol adapter.
        with TemporaryDirectory(prefix='fixture-transport-') as directory:
            transports = (True,) if os.name == 'nt' else (False, True)
            for interpreter in transports:
                for owner in ('codex', 'claude-code'):
                    for supported in (True, False):
                        with self.subTest(interpreter=interpreter, owner=owner, supported=supported):
                            path = Path(directory) / 'executor'
                            body = (
                                'import sys\n'
                                f'sys.path.insert(0, {str(Path(fixture.__file__).parent)!r})\n'
                                'from five_issue_process_fixture import executor_main\n'
                                f'args = sys.argv[1:] if {supported!r} else ["--fixture-unsupported-help", *sys.argv[1:]]\n'
                                f'raise SystemExit(executor_main({owner!r}, args))\n'
                            )
                            argv = fixture.write_fixture_executable(path, body, interpreter=interpreter)
                            expected_path = path.with_suffix('.exe') if interpreter else path
                            # When the production negotiator launches real version/help probes.
                            with fixture.fixture_executable_transport([argv]):
                                capability = negotiate_session_capability(owner, argv[0], env=dict(os.environ))
                            # Then protocol support and the hash describe the script, not Python.
                            self.assertIsNotNone(capability)
                            assert capability is not None
                            expected = 'codex_exec_json' if owner == 'codex' else 'claude_stream_json'
                            self.assertEqual(capability.protocol, expected if supported else None)
                            self.assertEqual(capability.binary_identity.resolved_path, str(expected_path.resolve()))
                            self.assertEqual(capability.binary_identity.sha256, sha256(expected_path.read_bytes()).hexdigest())

    def test_status_subprocess_observes_script_mutation_without_adapter(self) -> None:
        # Given a registered script identity and the real read-only observer.
        with TemporaryDirectory(prefix='fixture-identity-') as directory:
            argv = fixture.write_fixture_executable(Path(directory) / 'executor', 'print(1)\n', interpreter=True)
            before = observe_session_binary(argv[0])
            self.assertIsNotNone(before)
            path = Path(argv[0])
            _ = path.write_text(path.read_text() + '# changed executable\n')
            command = [sys.executable, '-B', '-c',
                       'from _local_package import load_local_package; load_local_package(); ' +
                       'from omh.coding.executor_readiness import observe_session_binary; ' +
                       'import dataclasses,json,sys; ' +
                       'print(json.dumps(dataclasses.asdict(observe_session_binary(sys.argv[1]))))', argv[0]]
            # When a separate Python process hashes it with no transport patch installed.
            result = subprocess.run(command, env={**os.environ, 'PYTHONPATH': str(Path(fixture.__file__).parent)},
                                    capture_output=True, text=True, check=True, timeout=fixture.FIXTURE_DEADLINE)
            # Then the same path has a changed hash, including outside the scenario process.
            identity = record(decode(result.stdout))
            assert before is not None
            self.assertEqual(identity['resolved_path'], before.resolved_path)
            self.assertNotEqual(identity['sha256'], before.sha256)
            self.assertEqual(identity['sha256'], sha256(path.read_bytes()).hexdigest())

    def test_launch_gate_and_spawn_callback_own_the_real_interpreter(self) -> None:
        # Given a real owner launch gate and a nonzero local child.
        with TemporaryDirectory(prefix='fixture-callback-') as directory:
            argv = fixture.write_fixture_executable(Path(directory) / 'executor',
                'import json,sys; print(json.dumps(sys.argv[1:])); sys.exit(7)\n', interpreter=True)
            context = OwnerLaunchGate().context(AdmissionBinding(
                'codex', 'fanout', 'a', 'run-a', 1, 'a' * 40, directory))
            spawned: list[subprocess.Popen[bytes] | subprocess.Popen[str]] = []
            # When the unmodified real runner launches through its gate and callback.
            with fixture.fixture_executable_transport([argv]):
                result = signal_safe_unit_runner([*argv, 'exec', '--json', 'prompt'],
                    capture_output=True, text=True, timeout=fixture.FIXTURE_DEADLINE,
                    launch=context.launch, on_spawn=spawned.append)
            # Then the callback owns the actual reaped interpreter, not a shell shim.
            self.assertEqual(result.returncode, 7)
            self.assertEqual(json.loads(result.stdout), ['exec', '--json', 'prompt'])
            self.assertEqual(len(spawned), 1)
            self.assertEqual(spawned[0].args, [sys.executable, *argv, 'exec', '--json', 'prompt'])
            self.assertEqual(spawned[0].returncode, 7)

    def test_overlapping_thread_scopes_leave_unrelated_commands_untouched(self) -> None:
        # Given overlapping scopes that exit in registration order, not stack order.
        original = subprocess.Popen
        with TemporaryDirectory(prefix='fixture-scopes-') as directory:
            first = fixture.write_fixture_executable(Path(directory) / 'first', 'print(1)\n', interpreter=True)
            second = fixture.write_fixture_executable(Path(directory) / 'second', 'print(2)\n', interpreter=True)
            first_open, second_open, first_closed = (threading.Event() for _ in range(3))

            def first_scope() -> None:
                try:
                    with fixture.fixture_executable_transport([first]):
                        first_open.set()
                        self.assertTrue(second_open.wait(fixture.FIXTURE_DEADLINE))
                finally:
                    first_closed.set()

            def second_scope() -> tuple[str, str]:
                self.assertTrue(first_open.wait(fixture.FIXTURE_DEADLINE))
                with fixture.fixture_executable_transport([second]):
                    second_open.set()
                    self.assertTrue(first_closed.wait(fixture.FIXTURE_DEADLINE))
                    own = subprocess.run(second, capture_output=True, text=True, check=True,
                                         timeout=fixture.FIXTURE_DEADLINE)
                    # A registered script used as an operand must not be interpreted.
                    unrelated = subprocess.run([sys.executable, '-c',
                        'import json,sys; print(json.dumps(sys.argv[1:]))', *second],
                        capture_output=True, text=True, check=True, timeout=fixture.FIXTURE_DEADLINE)
                    return own.stdout, unrelated.stdout

            # When real commands run after the earlier scope has already closed.
            with ThreadPoolExecutor(max_workers=2) as pool:
                a, b = pool.submit(first_scope), pool.submit(second_scope)
                a.result(timeout=fixture.FIXTURE_DEADLINE)
                own, unrelated = b.result(timeout=fixture.FIXTURE_DEADLINE)
            # Then the remaining registration works and unrelated argv is unchanged.
            self.assertEqual(own.strip(), '2')
            self.assertEqual(json.loads(unrelated), second)
        self.assertIs(subprocess.Popen, original)

    def test_session_scenarios_with_interpreter_transport(self) -> None:
        # Given all public session scenarios with explicit interpreter transport.
        from five_issue_cases import sessions
        writer = partial(fixture.write_fixture_executable, interpreter=True)
        for case in ('S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'):
            with self.subTest(case=case), patch.object(sessions, 'write_fixture_executable', writer):
                # When the real dispatcher, status and copy-only surfaces run.
                result = sessions.run_case(case)
                # Then the existing substantive scenario assertions and cleanup hold.
                self.assertTrue(result['pass'])
                self.assertTrue(result['cleanup']['verified_absent'])

    def test_capacity_scenarios_with_interpreter_transport_and_crlf_text_stream(self) -> None:
        # Given real capacity scenarios and Windows text translation on this host.
        from five_issue_cases import capacity

        def writer(path: Path, body: str) -> list[str]:
            return fixture.write_fixture_executable(path,
                "import sys; sys.stdout.reconfigure(newline='\\r\\n'); sys.stderr.reconfigure(newline='\\r\\n')\n" + body,
                interpreter=True)

        for case in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7'):
            with self.subTest(case=case), patch.object(capacity, 'write_fixture_executable', writer):
                # When the real processes negotiate, emit, trip and redispatch.
                result = capacity.run_case(case)
                # Then exact admission framing and all existing scenario assertions hold.
                self.assertTrue(result['pass'])
                self.assertTrue(result['cleanup']['verified_absent'])

    def test_verification_diagnostic_bytes_survive_crlf_text_stream(self) -> None:
        from five_issue_cases import diagnostics

        result = diagnostics.run_case('D5', verification_newline='\r\n')
        self.assertTrue(result['pass'], result['observations'])
        self.assertTrue(result['cleanup']['verified_absent'])

    def test_the_verification_command_does_not_grow_with_the_checkout_path(self) -> None:
        # #1474: the command embedded `sys.executable` and an inline script, so
        # a deep worktree pushed it past MAX_UNIT_VERIFICATION_COMMAND_CHARS and
        # the fixture's verdict became a function of where the repo lives.
        from five_issue_cases import diagnostics
        from omh.coding.fanout import MAX_UNIT_VERIFICATION_COMMAND_CHARS

        captured: list[str] = []
        real_build = diagnostics.build_fanout_contract

        def capture(goal: str, units: list[dict[str, object]]) -> object:
            for unit in units:
                commands = unit.get('verification_commands')
                if isinstance(commands, list):
                    captured.extend(str(command) for command in commands)
            return real_build(goal, units)

        # The fixtures' interpreter budget (`_verification_python`): a longer base interpreter would crowd the
        # command's cap, so `sys.executable` stands in for it.
        base_python = getattr(sys, "_base_executable", sys.executable)
        if len(base_python) > SHORT_INTERPRETER_CHARS or not Path(base_python).exists():
            base_python = sys.executable

        with (
            patch.object(diagnostics, 'build_fanout_contract', capture),
            patch.object(diagnostics, 'verification_python_path', return_value=base_python),
        ):
            result = diagnostics.run_case('D5', verification_newline='\r\n')
        self.assertTrue(result['pass'], result['observations'])
        self.assertEqual(len(captured), 1)
        command = captured[0]
        checkout = str(Path(__file__).resolve().parents[1])
        argv = shlex.split(command)
        self.assertEqual(argv[0], base_python)
        self.assertNotIn(checkout, argv[1])
        # Headroom for a checkout far deeper than this one, measured rather
        # than assumed: the command may not consume the whole cap.
        self.assertLess(len(command), MAX_UNIT_VERIFICATION_COMMAND_CHARS - 40)

    def test_diagnostics_fixture_survives_isolated_home_without_codex_state(self) -> None:
        from five_issue_cases import diagnostics

        with TemporaryDirectory(prefix='isolated-home-') as home_dir:
            home = Path(home_dir)
            with patch.dict(os.environ, {'HOME': str(home)}):
                _ = os.environ.pop('CODEX_HOME', None)
                result = diagnostics.run_case('D5')
            self.assertTrue(result['pass'], result['observations'])
            self.assertTrue(result['cleanup']['verified_absent'])
            self.assertFalse((home / '.codex').exists())


if __name__ == '__main__':
    _ = unittest.main()
