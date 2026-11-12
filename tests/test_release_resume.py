"""Release body comparison is exact, local and read-only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from functools import partial
import subprocess
import sys
import runpy
from typing import Callable
from unittest.mock import patch

exercise_workflow: Callable[[Path, str], tuple[int, list[list[str]], str]] = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / 'tools/qa/_release_workflow_fixture.py')
)['exercise_workflow']

run_cli = partial(subprocess.run, capture_output=True, text=True, timeout=300)


class ReleaseResumeTests(unittest.TestCase):
    def test_matches_when_decoded_body_equals_notes(self):
        # Given
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / 'notes.md'
            notes.write_bytes(b'- fixture\n')
            body = root / 'body.json'
            body.write_text(json.dumps({'body': '- fixture\n'}), encoding='utf-8')
            # When
            result = run_cli([sys.executable, '-P', '-m', 'omh.cli', 'release', 'notes-verify', '--notes-file', str(notes), '--body-json', str(body), '--json'])
            # Then
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['verification'], 'matching')

    def test_refuses_drift_when_existing_release_has_other_body(self):
        # Given
        with TemporaryDirectory() as tmp:
            # When
            code, calls, output = exercise_workflow(Path(tmp) / 'drift', 'drift')
            # Then
            self.assertNotEqual(code, 0, output)
            self.assertFalse(any(call[:2] in (['release', 'create'], ['release', 'upload'], ['release', 'edit']) for call in calls), calls)

    def test_creates_with_file_when_release_is_missing(self):
        # Given
        with TemporaryDirectory() as tmp:
            # When
            code, calls, output = exercise_workflow(Path(tmp) / 'missing', 'missing')
            # Then
            self.assertEqual(code, 0, output)
            create = next(call for call in calls if call[:2] == ['release', 'create'])
            self.assertIn('--notes-file', create)
            self.assertNotIn('--generate-notes', create)

    def test_refuses_create_when_auth_lookup_fails(self):
        # Given
        with TemporaryDirectory() as tmp:
            # When
            code, calls, output = exercise_workflow(Path(tmp) / 'auth', 'auth')
            # Then
            self.assertNotEqual(code, 0, output)
            self.assertFalse(any(call[:2] in (['release', 'create'], ['release', 'upload'], ['release', 'edit']) for call in calls), calls)

    def test_binds_notes_when_evidence_is_generated(self):
        # Given
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'CHANGELOG.md').write_text('## Unreleased\n\n## 2.0.4 - 2026-09-13\n\n- fixture\n')
            notes = root / 'notes.md'
            notes.write_bytes(b'- fixture\n')
            # When
            result = run_cli([sys.executable, '-P', '-m', 'omh.cli', '--omh-home', str(root / 'omh'), '--hermes-home', str(root / 'hermes'), 'release', 'evidence-bundle', '--version', '2.0.4', '--repo-root', str(root), '--notes-file', str(notes), '--write', '--json'])
            # Then
            self.assertIn(result.returncode, (0, 1), result.stderr)
            metadata = json.loads(result.stdout)['release_notes']
            self.assertEqual(metadata['path'], 'notes.md')
            self.assertEqual(metadata['byte_length'], len(notes.read_bytes()))

    def test_returns_mismatch_when_only_final_whitespace_differs(self):
        # Given
        with TemporaryDirectory() as tmp:
            notes, body = Path(tmp) / 'notes.md', Path(tmp) / 'body.json'
            notes.write_bytes(b'- fixture\n')
            body.write_text(json.dumps({'body': '- fixture\n\n'}))
            # When
            result = run_cli([sys.executable, '-P', '-m', 'omh.cli', 'release', 'notes-verify', '--notes-file', str(notes), '--body-json', str(body), '--json'])
            # Then
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['verification'], 'mismatched')
            self.assertEqual(notes.read_bytes(), b'- fixture\n')

    def test_returns_invalid_input_when_body_shape_is_invalid(self):
        # Given
        for value in ({}, {'body': None}, {'body': 5}, ['body'], {'body': '- fixture\n', 'extra': True}):
            with self.subTest(value=value), TemporaryDirectory() as tmp:
                notes, body = Path(tmp) / 'notes.md', Path(tmp) / 'body.json'
                notes.write_bytes(b'- fixture\n')
                body.write_text(json.dumps(value))
                # When
                result = run_cli([sys.executable, '-P', '-m', 'omh.cli', 'release', 'notes-verify', '--notes-file', str(notes), '--body-json', str(body), '--json'])
                # Then
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)['error'], 'invalid_body_json')

    def test_reports_shell_output_when_block_never_reaches_gh(self):
        # Given: a block that fails before its first gh call
        block = {'workflow_block': lambda: 'echo block-start-failed >&2; exit 3'}
        with TemporaryDirectory() as tmp, patch.dict(exercise_workflow.__globals__, block):
            # When / Then
            with self.assertRaisesRegex(FileNotFoundError, 'bash exited 3: block-start-failed'):
                exercise_workflow(Path(tmp) / 'never', 'matching')

    def test_checks_body_before_upload_when_release_is_resumed(self):
        # Given
        with TemporaryDirectory() as tmp:
            # When
            code, calls, output = exercise_workflow(Path(tmp) / 'matching', 'matching')
            # Then
            self.assertEqual(code, 0, output)
            self.assertEqual(calls[0], ['release', 'view', 'v2.0.4', '--json', 'body'])
            self.assertTrue(any(call[:2] == ['release', 'upload'] for call in calls), calls)
            self.assertEqual(calls[-1], ['release', 'view', 'v2.0.4', '--json', 'body'])
