"""Reviewed-build default wiring through real fixture processes, never native refusal."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import TypedDict, Unpack
import unittest
from unittest.mock import patch

from _local_package import load_local_package
load_local_package()

from five_issue_process_fixture import fixture_executable_transport, fixture_system_environment, write_fixture_executable
from five_issue_cases.capacity import RunnerOptions, no_stagger, ready
from five_issue_cases.sessions import decode, record, rows_of, text
from _cli_harness import run_cli
from omh.coding import fanout_capacity as capacity
from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_artifacts import write_fanout_contract
from omh.coding.fanout_dispatch import build_dispatch_argv, dispatch_fanout, signal_safe_unit_runner
from omh.coding.fanout_executor_sessions import BinaryIdentity, SessionCapability
from omh.coding.fanout_output import FanoutOutput
from omh.system.paths import OmhPaths

RELEASE_REVISION = '6b9826e3aa83b1a5947db50f4332cb9c65f1b340'
DARWIN_DIGEST = '4f85982624b3898c8991cb80c0981b2aa71070e3537046c9a95950318a95afcc'
LINUX_DIGEST = '9b7c1c7abdc26fc3c4f47c77656a8e9121def5483dbae830ef1ee561758448a9'


class SourceOptions(TypedDict, total=False):
    capacity_sources: Sequence[capacity.CodexAdmissionSource] | None


class CapacityDefaultBuildTests(unittest.TestCase):
    def dispatch_fixture(self, *, recognized: bool = True, version: str = '0.154.0',
                         help_flags: str = '--json resume', stderr: str = capacity.CODEX_ADMISSION_ERROR,
                         explicit_fixture: bool = False, mutate_binary: bool = False,
                         retarget_before_spawn: bool = False,
                         **options: Unpack[SourceOptions]) -> tuple[list[str], str, list[str | None]]:
        with TemporaryDirectory(prefix='g3-default-build-') as directory:
            root = Path(directory).resolve()
            repo = root / 'repo'
            repo.mkdir()
            _ = (repo / 'seed').write_text('fixture\n')
            # Only this disposable fixture repository receives a baseline commit.
            for command in (['init', '-q'], ['add', 'seed'],
                            ['-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                             'commit', '-qm', 'fixture']):
                _ = subprocess.run(['git', *command], cwd=repo, capture_output=True, check=True)
            base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                  capture_output=True, text=True, check=True).stdout.strip()
            home = root / 'home'
            home.mkdir()
            env = {**fixture_system_environment(), 'PATH': os.environ.get('PATH', ''), 'HOME': str(home),
                   'CODEX_HOME': str(home / 'codex'), 'RUST_LIB_BACKTRACE': '1'}
            paths = OmhPaths(omh_home=root / 'omh', hermes_home=root / 'hermes')
            executable = write_fixture_executable(root / 'codex-fixture', '\n'.join((
                'import sys',
                f"if '--version' in sys.argv: print('codex-fixture {version}'); raise SystemExit(0)",
                f"if '--help' in sys.argv: print({help_flags!r}); raise SystemExit(0)",
                'sys.stdout.buffer.write(b\'{"type":"thread.started","thread_id":"11111111-1111-4111-8111-111111111111"}\\n\')',
                'sys.stderr.buffer.write(' + repr(stderr.encode()) + ')',
                'raise SystemExit(1)', '')))
            digest = sha256(Path(executable[0]).read_bytes()).hexdigest()
            registry = {digest if recognized else '0' * 64: ('0.154.0', RELEASE_REVISION, 'fixture')}
            if explicit_fixture:
                options['capacity_sources'] = (capacity.CodexAdmissionSource(
                    executable[0], digest, version, capacity.CODEX_ADMISSION_REVISION, 'fixture'),)
            starts: list[list[str]] = []
            backtraces: list[str | None] = []

            def argv_for(owner: str, prompt: str, route: Mapping[str, object] | None = None) -> list[str]:
                command = build_dispatch_argv(owner, prompt, route)
                assert command is not None
                return [executable[0], *command[1:]]

            def runner(argv: Sequence[str], **kwargs: Unpack[RunnerOptions]) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
                if retarget_before_spawn and argv[0] == executable[0]:
                    Path(executable[0]).write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
                result = signal_safe_unit_runner(argv, **kwargs)
                if argv[0] == executable[0]:
                    starts.append(list(argv))
                    backtraces.append((kwargs.get('env') or {}).get('RUST_LIB_BACKTRACE'))
                    if mutate_binary:
                        with Path(executable[0]).open('a') as stream:
                            _ = stream.write('\n# replaced fixture identity\n')
                return result

            setattr(runner, 'accepts_on_spawn', True)
            setattr(runner, 'accepts_output_capture', True)
            setattr(runner, 'accepts_launch', True)
            setattr(runner, 'accepts_binary_identity', True)
            goal = 'Exercise the default reviewed-build resolver with a labeled fixture.'
            contract = write_fanout_contract(paths, build_fanout_contract(goal, [
                {'unit_id': name, 'title': name, 'owner': 'codex', 'file_scope': [name + '/']}
                for name in ('a', 'b')], spawn_plan={
                    'why_parallel': 'Independent fixture scopes.',
                    'why_not_single_unit': 'Observe the next queued admission.',
                    'independence': 'No shared output files.',
                    'expected_evidence_shape': 'Bound process-local fixture rejection.'}))
            with (fixture_executable_transport([executable]),
                  patch.object(capacity, 'CODEX_ADMISSION_BUILDS', registry),
                  patch('omh.coding.fanout_dispatch.build_dispatch_argv', argv_for),
                  patch('omh.coding.fanout_dispatch._SpawnStagger.reserve', no_stagger)):
                # The default case deliberately supplies no capacity_sources argument.
                summary = dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                    base_sha=base, concurrency=1, runner=runner, readiness=ready,
                    max_retries=0, env=env,
                    environment_policy={'project_variables': ['RUST_LIB_BACKTRACE']}, **options)
            rows = rows_of(summary)
            statuses = [text(row['status']) for row in rows]
            summary_capacity = record(record(summary)['capacity'])
            support = text(summary_capacity['native_support'])
            self.assertFalse(summary_capacity['quota_observed'])
            if not retarget_before_spawn:
                self.assertEqual(len(starts), 1 if statuses[0] == 'executor_capacity_rejected' else 2)
            if statuses[0] == 'executor_capacity_rejected':
                admission = record(rows[0]['capacity'])
                self.assertEqual(admission['evidence_kind'], 'fixture')
                self.assertEqual(admission['scope'], 'process_local')
                self.assertEqual(admission['definition_revision'], capacity.CODEX_ADMISSION_REVISION)
                self.assertEqual(admission['source_revision'],
                                 capacity.CODEX_ADMISSION_REVISION if explicit_fixture else RELEASE_REVISION)
                code, output, error = run_cli(['--omh-home', str(paths.omh_home),
                    '--hermes-home', str(paths.hermes_home), 'coding', 'fanout', 'status',
                    '--fanout-id', str(contract['fanout_id']), '--unit', 'a', '--json'])
                self.assertEqual(code, 0, error)
                self.assertEqual(rows_of(decode(output))[0]['capacity'], admission)
            else:
                self.assertTrue(all('capacity' not in row for row in rows))
            if retarget_before_spawn:
                self.assertNotIn('executor_session', rows[0])
                self.assertLess(len(starts), len(rows))
        self.assertFalse(root.exists())
        return statuses, support, backtraces

    def test_default_dispatch_resolves_reviewed_fixture_without_source_argument(self) -> None:
        self.assertEqual(self.dispatch_fixture(), (
            ['executor_capacity_rejected', 'not_started_capacity_blocked'], 'fixture_only', ['0']))

    def test_explicit_empty_disables_default_and_none_enables_it(self) -> None:
        self.assertEqual(self.dispatch_fixture(capacity_sources=()), (
            ['failed', 'failed'], 'unsupported_without_source_qualified_build', ['1', '1']))
        self.assertEqual(self.dispatch_fixture(capacity_sources=None), (
            ['executor_capacity_rejected', 'not_started_capacity_blocked'], 'fixture_only', ['0']))

    def test_explicit_fixture_sequence_remains_a_path_bound_seam(self) -> None:
        self.assertEqual(self.dispatch_fixture(recognized=False, explicit_fixture=True), (
            ['executor_capacity_rejected', 'not_started_capacity_blocked'], 'fixture_only', ['0']))

    def test_unknown_build_version_and_protocol_are_ordinary_failures(self) -> None:
        for label, result in (
                ('hash', self.dispatch_fixture(recognized=False)),
                ('version', self.dispatch_fixture(version='0.154.1')),
                ('protocol', self.dispatch_fixture(help_flags='resume'))):
            with self.subTest(field=label):
                statuses, support, _ = result
                self.assertEqual(statuses, ['failed', 'failed'])
                self.assertEqual(support, 'unsupported_without_source_qualified_build')

    def test_recognized_build_support_does_not_require_a_rejection(self) -> None:
        self.assertEqual(self.dispatch_fixture(stderr='compiler failed\n'), (
            ['failed', 'failed'], 'fixture_only', ['0', '0']))

    def test_postflight_changed_binary_is_not_recognized_or_classified(self) -> None:
        statuses, support, _ = self.dispatch_fixture(mutate_binary=True)
        self.assertEqual(statuses, ['failed', 'failed'])
        self.assertEqual(support, 'unsupported_without_source_qualified_build')

    def test_spawn_boundary_refuses_changed_identity_without_session_evidence(self) -> None:
        statuses, support, _ = self.dispatch_fixture(
            retarget_before_spawn=True,
            capacity_sources=(),
        )
        self.assertEqual(statuses, ['failed', 'completed'])
        self.assertEqual(support, 'unsupported_without_source_qualified_build')


class ReviewedBuildRegistryTests(unittest.TestCase):
    """Pure metadata checks, not claims that a fabricated capability was executed."""
    def test_only_reviewed_hashes_and_exact_version_match_at_any_resolved_path(self) -> None:
        self.assertEqual(set(capacity.CODEX_ADMISSION_BUILDS), {DARWIN_DIGEST, LINUX_DIGEST})
        for digest in (DARWIN_DIGEST, LINUX_DIGEST):
            capability = SessionCapability('codex', 'codex_exec_json',
                BinaryIdentity('/relocated/codex', digest), '0.154.0')
            source = capacity.codex_admission_source(capability)
            assert source is not None
            self.assertEqual((source.resolved_path, source.source_revision, source.evidence_kind),
                             ('/relocated/codex', RELEASE_REVISION, 'source_verified'))
            for variant in (replace(capability, executor='claude-code'),
                            replace(capability, protocol=None), replace(capability, version=None),
                            replace(capability, version='0.154.1'),
                            replace(capability, binary_identity=BinaryIdentity('/relocated/codex', 'f' * 64))):
                self.assertIsNone(capacity.codex_admission_source(variant))
            self.assertIsNone(capacity.codex_admission_source(capability, ()))
            self.assertIsNone(capacity.codex_admission_source(capability,
                (replace(source, resolved_path='/foreign/codex'),)))
            self.assertIsNone(capacity.codex_admission_source(capability,
                (replace(source, source_revision='a' * 40),)))

    def test_summary_support_uses_only_this_invocations_recognized_identities(self) -> None:
        gate = capacity.OwnerLaunchGate()
        def summary() -> dict[str, object]:
            return capacity.capacity_summary([], requested=2, effective=2,
                                             recognized_sources=gate.recognized_sources())
        self.assertEqual(summary()['native_support'], 'unsupported_without_source_qualified_build')
        capability = SessionCapability('codex', 'codex_exec_json',
            BinaryIdentity('/relocated/codex', DARWIN_DIGEST), '0.154.0')
        source = capacity.codex_admission_source(capability)
        assert source is not None
        gate.observe_source(source)
        self.assertEqual(summary()['native_support'], 'source_qualified_build')
        self.assertEqual(summary()['affected_units'], [])
        self.assertEqual(capacity.OwnerLaunchGate().recognized_sources(), ())

    def test_definition_and_build_source_are_distinct_and_legacy_records_stay_readable(self) -> None:
        for revision in (capacity.CODEX_ADMISSION_REVISION, RELEASE_REVISION):
            source = capacity.CodexAdmissionSource('/fixture', 'a' * 64, '0.154.0', revision, 'fixture')
            observer = capacity.CodexAdmissionObserver()
            capture = FanoutOutput(protocol='codex', observer=observer.observe)
            capture.feed('stdout', b'{"type":"thread.started","thread_id":"11111111-1111-4111-8111-111111111111"}\n')
            capture.feed('stderr', capacity.CODEX_ADMISSION_ERROR.encode())
            capture.finish('stdout')
            capture.finish('stderr')
            binding = capacity.AdmissionBinding('codex', 'fanout-a', 'a', 'run-a', 1,
                'a' * 40, '/fixture-worktree', 'invocation', 'attempt')
            receipt = observer.receipt(capture, binding=binding, source=source, returncode=1,
                process_started=True, fresh_exec=True, artifact_observed=False)
            assert receipt is not None
            self.assertEqual(receipt.definition_revision, capacity.CODEX_ADMISSION_REVISION)
            self.assertEqual(receipt.source_revision, revision)
            fields = capacity.capacity_fields(binding, capacity.CapacityTrip(receipt, 2),
                status='executor_capacity_rejected', process_started=True)
            self.assertEqual(capacity.read_capacity_fields({'capacity': fields}), {'capacity': fields})
            variants: tuple[Mapping[str, object], ...] = (
                {'source_revision': 'a' * 40}, {'source_revision': None},
                {'source_revision': []}, {'definition_revision': RELEASE_REVISION},
                {'definition_revision': None}, {'adapter': 'foreign'},
                {'evidence_kind': 'native_saturation'})
            for changes in variants:
                with self.subTest(revision=revision, changes=changes):
                    self.assertEqual(capacity.read_capacity_fields({'capacity': {**fields, **changes}}), {})
            legacy = {key: value for key, value in fields.items() if key != 'source_revision'}
            self.assertEqual(capacity.read_capacity_fields({'capacity': legacy}), {'capacity': legacy})


if __name__ == '__main__':
    _ = unittest.main()
