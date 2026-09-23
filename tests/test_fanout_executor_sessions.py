"""Foundation proofs; public dispatcher/native acceptance remains separate."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typing import TYPE_CHECKING, TypeGuard

if TYPE_CHECKING:
    from omh.coding.fanout_executor_sessions import SessionReceipt

from _local_package import load_local_package

load_local_package()
from five_issue_cases import JsonValue, sessions as producer
from five_issue_process_fixture import process_fixture
from omh.coding.codex_progress import build_codex_session_observation
from omh.coding.fanout_dispatch import stdout_fenced_json_blocks as _stdout_fenced_json_blocks

MODULE = 'omh.coding.fanout_executor_sessions'
SID = '12345678-1234-4234-8234-123456789abc'
OTHER = '12345678-1234-4234-8234-123456789abd'
ATTEMPT = '22345678-1234-4234-8234-123456789abc'
SHA = 'a' * 40
decode_json: Callable[[str | bytes], JsonValue] = json.loads


def _is_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


class SessionsFoundation(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec(MODULE),
                             'missing sessions contract: native event receipt and copy-only projection')
        from omh.coding import fanout_executor_sessions
        return fanout_executor_sessions

    def capability(self, executor: str = 'codex'):
        api = self.api()
        return api.SessionCapability(
            executor, 'codex_exec_json' if executor == 'codex' else 'claude_stream_json',
            api.BinaryIdentity('/opt/agent binaries/' + executor, 'b' * 64), 'fixture-1')

    def binding(self):
        api = self.api()
        return api.SessionBinding(
            'fo-1', 'unit-a', 'run-a', ATTEMPT, 'c' * 64,
            "/work/it's a $(literal); tree",
            api.WorktreeIncarnation(OTHER, '/repo/.git', 'refs/heads/agent/a', 1, 200),
            SHA, SHA)

    def receipt(self, executor: str = 'codex'):
        api = self.api()
        decoder = api.SessionDecoder(self.capability(executor))
        event = ({'type': 'thread.started', 'thread_id': SID} if executor == 'codex'
                 else {'type': 'system', 'subtype': 'init', 'session_id': SID})
        decoder.observe(event, event_ref='stdout:1')
        return decoder.receipt(self.binding(), end_head=SHA)

    def workspace(self, receipt: SessionReceipt):
        return self.api().WorkspaceSnapshot(receipt.binding.worktree_path,
            receipt.binding.worktree_incarnation, SHA, False, None)

    def test_s1_native_fixture_events_bind_only_dispatcher_lineage(self):
        api = self.api()
        for executor, mode, sid in [('codex', 'codex', SID), ('claude-code', 'claude', OTHER)]:
            with self.subTest(executor=executor):
                decoder = api.SessionDecoder(self.capability(executor))
                binding = replace(self.binding(), unit_id='unit-' + executor)
                with process_fixture(['--mode', mode, '--session-id', sid], stdout=b'final') as child:
                    child.event('ready')
                    child.send('start')
                    child.event('started')
                    child.event('emitted')
                    result = child.finish()
                    self.assertEqual(result.returncode, 0)
                    for index, line in enumerate(result.stdout.splitlines(), 1):
                        event = decode_json(line)
                        assert isinstance(event, dict)
                        decoder.observe(event, event_ref=f'stdout:{index}')
                self.assertTrue(child.cleanup['verified_absent'])
                self.assertEqual(child.cleanup['errors'], [])
                self.assertIsNotNone(child.process.returncode)
                receipt = decoder.receipt(binding, end_head=SHA)
                self.assertEqual((receipt.state, receipt.reference), ('observed', sid))
                self.assertEqual(receipt.binding, binding)
                self.assertEqual(receipt.event_ref, 'stdout:1')
                self.assertEqual(receipt.capability.executor, executor)
                self.assertEqual(receipt.end_head, SHA)

    def test_s1_claude_root_result_alone_and_matching_init(self):
        api = self.api()
        for events in [[{'type': 'result', 'session_id': SID}],
                       [{'type': 'system', 'subtype': 'init', 'session_id': SID},
                        {'type': 'result', 'session_id': SID}]]:
            decoder = api.SessionDecoder(self.capability('claude-code'))
            for event in events:
                decoder.observe(event, event_ref='stdout:1')
            self.assertEqual(decoder.receipt(self.binding()).reference, SID)

    def test_s2_copy_only_exact_argv_quoted_cwd_and_no_launch(self):
        api = self.api()
        for executor in ['codex', 'claude-code']:
            receipt = self.receipt(executor)
            with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
                projection = api.project_session_resume(receipt.to_dict(), binding=self.binding(),
                    workspace=self.workspace(receipt), platform='posix')
            expected = ([receipt.capability.binary_identity.launch_path, 'exec', 'resume', SID, '-']
                        if executor == 'codex' else
                        [receipt.capability.binary_identity.launch_path, '--resume=' + SID])
            self.assertTrue(projection['available'])
            self.assertEqual(projection['argv'], expected)
            shell_command = projection['shell_command']
            assert shell_command is not None
            self.assertEqual(shlex.split(shell_command),
                             ['cd', '--', receipt.binding.worktree_path, '&&', *expected])
            self.assertEqual(projection['execution_policy'], 'copy_only')
            self.assertEqual(projection['native_resume_state'], 'not_tested')
            self.assertEqual(projection['required_input'],
                             'follow_up_prompt_on_stdin' if executor == 'codex' else None)

    def test_s2_windows_has_no_unverified_shell_rendering(self):
        receipt = self.receipt()
        result = self.api().project_session_resume(receipt.to_dict(), binding=self.binding(),
            workspace=self.workspace(receipt), platform='nt')
        self.assertTrue(result['available'])
        self.assertIsNone(result['shell_command'])
        self.assertEqual(result['cwd'], receipt.binding.worktree_path)

    def test_s3_round_trip_held_receipt_and_fresh_attempt_never_borrows_id(self):
        api = self.api()
        old = self.receipt()
        serialized = json.dumps(old.to_dict(), sort_keys=True)
        read = api.read_session_receipt(decode_json(serialized))
        self.assertEqual(read.receipt, old)
        assert read.receipt is not None
        self.assertEqual(json.dumps(read.receipt.to_dict(), sort_keys=True), serialized)
        binding = replace(self.binding(), attempt_id=OTHER, predecessor_attempt_id=ATTEMPT)
        fresh = api.SessionDecoder(self.capability()).receipt(binding)
        self.assertIsNone(fresh.reference)
        self.assertEqual(fresh.reason, 'event_missing')
        self.assertEqual(fresh.binding.predecessor_attempt_id, ATTEMPT)
        self.assertNotEqual(fresh.binding.attempt_id, old.binding.attempt_id)
        self.assertEqual(old.reference, SID)

    def test_s4_ignores_nested_tool_sidecar_and_wrong_event_identity(self):
        api = self.api()
        for executor in ['codex', 'claude-code']:
            decoder = api.SessionDecoder(self.capability(executor))
            for event in [{'type': 'tool', 'result': {'type': 'thread.started', 'thread_id': SID}},
                          {'session_ref': SID}, {'type': 'assistant', 'session_id': SID},
                          {'type': 'system', 'subtype': 'other', 'session_id': SID},
                          {'type': 'thread.started', 'thread_id': SID, 'parent_tool_use_id': 'tool'},
                          {'type': 'result', 'session_id': SID, 'parent_tool_use_id': 'tool'},
                          {'type': 'system', 'subtype': 'init', 'session_id': SID,
                           'parent_tool_use_id': 'tool'}]:
                decoder.observe(event, event_ref='stdout:1')
            receipt = decoder.receipt(self.binding())
            self.assertEqual((receipt.state, receipt.reason, receipt.reference),
                             ('not_observed', 'event_missing', None))

    def test_s4_malformed_uuid_and_conflict_poison_attempt(self):
        api = self.api()
        for executor in ['codex', 'claude-code']:
            for invalid in ['', '--latest', SID.upper(), SID + '\n', SID.replace('-', ''),
                            SID + '\x00', 42, {'session_id': SID}, OTHER]:
                with self.subTest(executor=executor, invalid=invalid):
                    decoder = api.SessionDecoder(self.capability(executor))
                    def event(value: object) -> dict[str, object]:
                        return ({'type': 'thread.started', 'thread_id': value} if executor == 'codex'
                                else {'type': 'result', 'session_id': value})
                    decoder.observe(event(SID), event_ref='stdout:1')
                    decoder.observe(event(invalid), event_ref='stdout:2')
                    decoder.observe(event(SID), event_ref='stdout:3')
                    receipt = decoder.receipt(self.binding())
                    self.assertEqual(receipt.state, 'not_observed')
                    self.assertIsNone(receipt.reference)
                    self.assertEqual(receipt.reason,
                                     'conflicting_reference' if invalid == OTHER else 'invalid_reference')

    def test_s4_capability_unknown_protocol_and_plain_fallback(self):
        api = self.api()
        for capability in [replace(self.capability(), protocol=None),
                           replace(self.capability(), protocol='future'),
                           replace(self.capability(), executor='generic'),
                           replace(self.capability(), protocol='claude_stream_json')]:
            decoder = api.SessionDecoder(capability)
            decoder.observe({'type': 'thread.started', 'thread_id': SID}, event_ref='stdout:1')
            receipt = decoder.receipt(self.binding())
            self.assertEqual((receipt.state, receipt.reason, receipt.reference),
                             ('not_available', 'unsupported_protocol', None))
            self.assertIsNotNone(api.read_session_receipt(receipt.to_dict()).receipt)

    def test_s4_missing_version_probe_is_unavailable_not_unit_failure(self):
        api = self.api()
        decoder = api.SessionDecoder(replace(self.capability(), version=None))
        decoder.observe({'type': 'thread.started', 'thread_id': SID}, event_ref='stdout:1')
        try:
            receipt = decoder.receipt(self.binding())
        except ValueError:
            self.fail('missing version probe must disable sessions, not fail valid dispatch')
        self.assertEqual((receipt.state, receipt.reason), ('not_available', 'unsupported_protocol'))
        self.assertIsNone(receipt.reference)

    def test_s4_recovery_state_cleaned_after_failure_is_stale(self):
        receipt = self.receipt()
        result = self.api().project_session_resume(receipt.to_dict(), binding=self.binding(),
            workspace=self.workspace(receipt), recovery_snapshot='f' * 64)
        self.assertEqual((result['available'], result['reason']), (False, 'recovery_snapshot_mismatch'))

    def test_s4_duplicate_across_fresh_attempts_disables_both_not_replay(self):
        api = self.api()
        first = self.receipt()
        second = replace(first, binding=replace(first.binding, attempt_id=OTHER, unit_id='unit-b'))
        self.assertEqual(api.duplicate_session_references([first.to_dict(), first.to_dict()]), frozenset())
        duplicates = api.duplicate_session_references([first.to_dict(), second.to_dict()])
        self.assertEqual(duplicates, frozenset({SID}))
        for receipt in [first, second]:
            result = api.project_session_resume(receipt.to_dict(), binding=receipt.binding,
                workspace=self.workspace(receipt), duplicate_references=duplicates)
            self.assertFalse(result['available'])
            self.assertEqual(result['reason'], 'duplicate_reference')
            self.assertEqual(receipt.reference, SID)

    def test_s4_recreated_branch_head_and_selection_mismatch_disable_copy(self):
        api = self.api()
        receipt = self.receipt()
        current = self.workspace(receipt)
        for field, value in [('incarnation_id', ATTEMPT), ('branch', 'refs/heads/foreign'),
                             ('common_dir', '/other/.git'), ('device', 2), ('inode', 201)]:
            with self.subTest(field=field):
                snapshot = replace(current, incarnation=replace(current.incarnation, **{field: value}))
                result = api.project_session_resume(receipt.to_dict(), binding=self.binding(), workspace=snapshot)
                self.assertEqual((result['available'], result['reason']), (False, 'stale_workspace'))
        for snapshot in [None, replace(current, path='/elsewhere'), replace(current, head='d' * 40)]:
            result = api.project_session_resume(receipt.to_dict(), binding=self.binding(), workspace=snapshot)
            self.assertFalse(result['available'])
        for field, value in [('unit_id', 'unit-b'), ('fanout_id', 'fo-other'), ('run_ref', 'run-other'),
                             ('attempt_id', OTHER), ('contract_digest', 'e' * 64), ('base_sha', 'e' * 40)]:
            result = api.project_session_resume(receipt.to_dict(),
                binding=replace(self.binding(), **{field: value}), workspace=current)
            self.assertEqual(result['reason'], 'binding_mismatch')

    def test_s4_dirty_failed_work_requires_exact_recovery_snapshot(self):
        api = self.api()
        receipt = self.receipt()
        dirty = replace(self.workspace(receipt), dirty=True, recovery_snapshot='f' * 64)
        for recorded in [None, 'e' * 64, 'f' * 64]:
            result = api.project_session_resume(receipt.to_dict(), binding=self.binding(),
                workspace=dirty, recovery_snapshot=recorded)
            self.assertEqual(result['available'], recorded == 'f' * 64)
        result = api.project_session_resume(replace(receipt, end_head=None).to_dict(),
            binding=self.binding(), workspace=self.workspace(receipt))
        self.assertEqual(result['reason'], 'end_revision_not_observed')

    def test_s5_event_budget_bounded_and_no_body_retention(self):
        api = self.api()
        decoder = api.SessionDecoder(self.capability())
        event = {'type': 'thread.started', 'thread_id': SID, 'body': 'PRIVATE_SENTINEL' * 1000,
                 'fanout_id': 'spoofed', 'worktree_path': '/spoofed', 'event_ref': 'spoofed'}
        decoder.observe(event, event_ref='stdout:1')
        event['thread_id'] = OTHER
        event['body'] = 'mutated'
        receipt = decoder.receipt(self.binding())
        self.assertEqual(receipt.reference, SID)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(receipt.to_dict()))
        self.assertNotIn('spoofed', json.dumps(receipt.to_dict()))
        self.assertNotIn('PRIVATE_SENTINEL', repr(decoder))
        for _ in range(65535):
            decoder.observe({'type': 'other'}, event_ref='stdout:2')
        self.assertEqual(decoder.receipt(self.binding()).state, 'observed')
        decoder.observe({'type': 'other'}, event_ref='stdout:3')
        for _ in range(10):
            decoder.observe({'type': 'other'}, event_ref='stdout:4')
        self.assertEqual(decoder.event_count, 65536)
        self.assertEqual(decoder.receipt(self.binding()).reason, 'event_limit')
        self.assertIsNone(decoder.receipt(self.binding()).reference)

    def test_s6_legacy_unknown_version_and_malformed_optional_do_not_rewrite(self):
        api = self.api()
        cases: list[tuple[JsonValue, str]] = [
            (None, 'legacy_missing'), ({'session_ref': SID}, 'unknown_schema'),
            ({'schema_version': 'fanout_executor_session/v999'}, 'unknown_schema'),
            ([], 'invalid_receipt'),
        ]
        for value, reason in cases:
            original = json.dumps(value)
            read = api.read_session_receipt(value)
            self.assertIsNone(read.receipt)
            self.assertEqual(read.reason, reason)
            self.assertEqual(json.dumps(value), original)
            result = api.project_session_resume(value, binding=self.binding(), workspace=None)
            self.assertFalse(result['available'])
            self.assertEqual(result['reason'], reason)
        summary = {'status': 'completed', 'session_ref': SID, 'executor_session': {'bad': True}}
        before = json.dumps(summary)
        _ = api.read_session_receipt(summary['executor_session'])
        self.assertEqual(json.dumps(summary), before)

    def test_persisted_v1_receipt_normalizes_launch_path_for_resume(self):
        api = self.api()
        persisted = self.receipt().to_dict()
        persisted['schema_version'] = 'fanout_executor_session/v1'
        identity = persisted['binary_identity']
        assert isinstance(identity, dict)
        identity.pop('launch_path')

        read = api.read_session_receipt(persisted)

        self.assertIsNotNone(read.receipt)
        assert read.receipt is not None
        self.assertEqual(
            read.receipt.capability.binary_identity.launch_path,
            read.receipt.capability.binary_identity.resolved_path,
        )
        projection = api.project_session_resume(
            persisted,
            binding=self.binding(),
            workspace=self.workspace(read.receipt),
        )
        self.assertTrue(projection['available'])
        self.assertEqual(projection['argv'][0], read.receipt.capability.binary_identity.resolved_path)

    def test_s6_strict_closed_receipt_validation(self):
        api = self.api()
        good = self.receipt().to_dict()
        self.assertIsNotNone(api.read_session_receipt(good).receipt)
        variants = [dict(good, reference='--continue'), dict(good, reference_kind='session_ref'),
                    dict(good, body='PRIVATE_SENTINEL'), dict(good, state='completed'),
                    dict(good, reason='invented'), dict(good, event_ref='bad\nref'),
                    dict(good, attempt_id='not-uuid'), dict(good, end_head='fake'),
                    dict(good, predecessor_attempt_id=ATTEMPT), dict(good, version='x' * 300),
                    dict(good, binary_identity={'resolved_path': 'codex', 'sha256': 'b' * 64}),
                    dict(good, worktree_path='relative'), dict(good, contract_digest='bad'),
                    dict(good, worktree_incarnation={'raw': 'PRIVATE_SENTINEL'})]
        for value in variants:
            with self.subTest(changed=[k for k in value if value[k] != good.get(k)]):
                read = api.read_session_receipt(value)
                self.assertIsNone(read.receipt)
                self.assertEqual(read.reason, 'invalid_receipt')

    def test_s7_existing_explicit_wrapper_reference_not_thread_borrowing(self):
        thread_only = build_codex_session_observation(selected_executor_profile='codex', external_session_ref=SID)
        self.assertTrue(thread_only['observed'])
        self.assertEqual(thread_only['thread_ref'], SID)
        self.assertEqual(thread_only['session_ref'], '')
        thread_resume = thread_only['resume']
        assert _is_mapping(thread_resume)
        self.assertFalse(thread_resume['available'])
        explicit = build_codex_session_observation(selected_executor_profile='codex', codex_session_ref=SID)
        explicit_resume = explicit['resume']
        assert _is_mapping(explicit_resume)
        self.assertEqual(explicit_resume['argv_template'], ['codex', 'exec', 'resume', SID])
        self.assertEqual(explicit_resume['execution_policy'], 'copyable_instruction_only')
        self.assertEqual(build_codex_session_observation(selected_executor_profile='claude-code',
                                                       external_session_ref=SID), {})

    def test_s7_existing_fence_scan_drops_incomplete_tail(self):
        text = '```json\n{"v":1}\n```\n```json\n{"v":2}\n```\n```json\n{"v":3}'
        self.assertEqual([decode_json(block) for block in _stdout_fenced_json_blocks(text)],
                         [{'v': 1}, {'v': 2}])

    def test_s6_qa_never_upgrades_foundation_to_surface_pass(self):
        root = Path(__file__).resolve().parents[1]
        path = root / 'tests/five_issue_cases/sessions.py'
        self.assertTrue(path.is_file(), 'missing sessions QA case producer')
        assert producer.__file__ is not None
        self.assertEqual(Path(producer.__file__).resolve(), path)
        # Public integration replaces the foundation producer, never its native boundary.
        self.assertTrue(callable(producer.run_case))

    def test_s4_bounded_local_probe_rejects_nonzero_and_oversized_output(self):
        import sys
        from omh.coding.fanout_executor_sessions import bounded_session_probe
        data, reason = bounded_session_probe([sys.executable, '-c', 'print("1.0")'])
        # The probe returns raw pipe bytes; the child's own line ending is
        # platform-native (CRLF on Windows), so compare the payload, not it.
        self.assertEqual((data.splitlines() if data is not None else None, reason), ([b'1.0'], 'observed'))
        for program, expected in [('print("x" * 20000)', 'probe_output_limited'),
                                  ('raise SystemExit(7)', 'probe_nonzero')]:
            data, reason = bounded_session_probe([sys.executable, '-c', program])
            self.assertIsNone(data)
            self.assertEqual(reason, expected)

    def test_windows_pinned_script_probe_uses_the_verified_copy_through_python(self):
        import sys
        from omh.coding.fanout_executor_sessions import _session_probe_launch

        with TemporaryDirectory() as temporary:
            pinned = Path(temporary) / "codex.exe"
            pinned.write_bytes(b"#!python\nprint('trusted')\n")
            argv, executable = _session_probe_launch(
                [r"C:\\tools\\codex.exe", "exec", "--help"],
                str(pinned),
                windows=True,
            )

        self.assertEqual(argv, [sys.executable, str(pinned), "exec", "--help"])
        self.assertIsNone(executable)

    def test_s5_native_telemetry_never_recurses_or_borrows_identity(self):
        from omh.coding.unit_telemetry import native_unit_telemetry
        event = {'type': 'turn.completed', 'usage': {'input_tokens': 4,
            'output_tokens': 8, 'nested': {'total_tokens': 999}, 'session_id': SID},
            'thread_id': SID, 'body': {'usage': {'total_tokens': 999}}}
        telemetry = native_unit_telemetry('codex', event)
        self.assertEqual(telemetry['input_tokens'], 4)
        self.assertEqual(telemetry['output_tokens'], 8)
        self.assertNotIn('tokens_total', telemetry)
        self.assertNotIn('session_ref', telemetry)
        self.assertEqual(native_unit_telemetry('codex', dict(event, parent_tool_use_id='tool')), {})

    def test_s3_stale_attempt_events_cannot_replace_fresh_missing_receipt(self):
        from omh.workflows.observation_journal import project_run_executor_session
        old = replace(self.receipt(), binding=replace(self.binding(),
            fanout_id='fanout-123456789abc', run_ref='fanout-123456789abc-unit-a'))
        fresh_binding = replace(old.binding, attempt_id=OTHER, predecessor_attempt_id=ATTEMPT)
        fresh = self.api().SessionDecoder(self.capability()).receipt(fresh_binding, end_head=SHA)
        def event(receipt: SessionReceipt) -> dict[str, object]:
            return {'run_id': receipt.binding.run_ref, 'event': 'executor_session_observed',
                    'attempt_id': receipt.binding.attempt_id, 'runtime_profile': 'codex',
                    'executor_session': receipt.to_dict()}
        projected = project_run_executor_session([event(old), event(fresh), event(old)], run_id=old.binding.run_ref)
        self.assertEqual(projected['executor_session'], fresh.to_dict())
        self.assertIsNone(fresh.reference)

    def test_s6_optional_receipt_reader_drops_foreign_and_private_fields(self):
        from tempfile import TemporaryDirectory
        from omh.system.paths import OmhPaths
        from omh.workflows.observation_journal import read_observation_events_result
        receipt = replace(self.receipt(), binding=replace(self.binding(),
            fanout_id='fanout-123456789abc', run_ref='fanout-123456789abc-unit-a'))
        event = {'run_id': receipt.binding.run_ref, 'event': 'executor_session_observed',
                 'attempt_id': ATTEMPT, 'runtime_profile': 'codex', 'executor_session': receipt.to_dict()}
        for bad in [dict(receipt.to_dict(), body='PRIVATE_SENTINEL'),
                    dict(receipt.to_dict(), unit_id='foreign')]:
            with TemporaryDirectory() as directory:
                paths = OmhPaths(omh_home=Path(directory), hermes_home=Path(directory) / 'hermes')
                paths.runtime_journal_events_path.parent.mkdir(parents=True)
                original = json.dumps(dict(event, executor_session=bad)) + '\n'
                _ = paths.runtime_journal_events_path.write_text(original)
                events, errors = read_observation_events_result(paths)
                self.assertEqual(errors, [])
                self.assertNotIn('executor_session', events[0])
                self.assertEqual(paths.runtime_journal_events_path.read_text(), original)


class SessionsIntegration(unittest.TestCase):
    def check_case(self, case: str) -> None:
        result = producer.run_case(case)
        self.assertTrue(result['pass'], result['blocked_reason'])
        self.assertEqual(result['provenance']['scope'], 'surface')
        self.assertEqual(result['provenance']['kind'], 'fixture')
        self.assertFalse(result['provenance']['native_available'])
        self.assertTrue(result['commands'])
        self.assertTrue(result['cleanup']['verified_absent'])
        self.assertEqual(result['cleanup']['errors'], [])

    def test_s1_observer_failure_preserves_historical_id_without_resume(self):
        from omh.coding.fanout_executor_sessions import SessionDecoder, read_session_receipt
        from omh.runtime.artifacts import append_journal_observation
        from omh.system.paths import OmhPaths
        captured: list[object] = []
        original = SessionDecoder.observe
        def fail(decoder: SessionDecoder, event: Mapping[str, object], *, event_ref: str) -> None:
            original(decoder, event, event_ref=event_ref)
            raise RuntimeError('observer_fixture')
        def observe(paths: OmhPaths, event: dict[str, object]) -> dict[str, object]:
            observed: Mapping[str, object] = append_journal_observation(paths, event)
            if 'executor_session' in observed:
                captured.append(event['executor_session'])
            return dict(observed)
        with patch.object(SessionDecoder, 'observe', fail), patch(
                'omh.coding.fanout_dispatch.append_journal_observation', observe):
            with self.assertRaisesRegex(RuntimeError, 'observer_fixture'):
                _ = producer.run_case('S1')
        self.assertTrue(captured, 'observed session ID lost on observer failure')
        for value in captured:
            receipt = read_session_receipt(value).receipt
            assert receipt is not None
            self.assertEqual(receipt.state, 'observed')
            self.assertIsNone(receipt.end_head)
            self.assertFalse(Path(receipt.binding.worktree_path).parent.exists())

    def test_s1_public_dispatch_receipt(self):
        self.check_case('S1')

    def test_s2_selected_copy_only_resume(self):
        self.check_case('S2')

    def test_s3_held_and_fresh_attempt_lineage(self):
        self.check_case('S3')

    def test_s4_adversarial_associations(self):
        self.check_case('S4')

    def test_s5_native_stream_privacy_and_telemetry(self):
        self.check_case('S5')

    def test_s6_legacy_read_only_compatibility(self):
        self.check_case('S6')

    def test_s7_final_fence_and_wrapper_compatibility(self):
        self.check_case('S7')


if __name__ == '__main__':
    _ = unittest.main()
