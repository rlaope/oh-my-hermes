"""Real local-process dispatcher scenarios; never native-provider evidence."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_artifacts import write_fanout_contract
from omh.coding.fanout_dispatch import dispatch_fanout
from omh.coding.fanout_failure_diagnostics import is_object_list, is_string_map
from omh.runtime.artifacts import show_run
from omh.system.paths import OmhPaths
from _fanout_host_fence import host_cannot_fence_fanout
from _verification_python import verification_python_path

from . import CaseResult, JsonValue


def exercise_dispatch(*, stdout: bytes = b'', stderr: bytes = b'', exit_code: int = 3,
                      sidecar: str = 'missing', verification: bool = False,
                      verification_newline: str = '') -> CaseResult:
    """Exercise dispatch_fanout with its real runner and an explicit fixture argv.

    No injected process result or confinement bypass. The only adapter replaces
    the selected CLI argv with the local fixture; Git and checks really execute.
    """
    commands: list[list[str]] = []
    observations: dict[str, JsonValue] = {}
    with TemporaryDirectory(prefix='five-issue-dispatch-') as directory:
        root = Path(directory)
        repo = root / 'repo'
        repo.mkdir()
        def git(*args: str) -> str:
            command = ['git', *args]
            commands.append(command)
            return subprocess.run(command, cwd=repo, capture_output=True,
                                  text=True, check=True).stdout.strip()
        _ = git('init', '-q')
        _ = (repo / 'seed').write_text('seed\n')
        _ = git('add', 'seed')
        _ = git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'fixture')
        base = git('rev-parse', 'HEAD')
        paths = OmhPaths(omh_home=root / 'omh', hermes_home=root / 'hermes')
        goal = 'bounded diagnostic fixture'
        unit: dict[str, object] = {'unit_id': 'core', 'title': 'Core', 'owner': 'codex',
                                  'file_scope': ['src/']}
        fixture = str(Path(__file__).resolve().parents[1] / 'five_issue_process_fixture.py')
        out, err, result_file = root / 'stdout.input', root / 'stderr.input', root / 'result.input'
        _ = out.write_bytes(stdout)
        _ = err.write_bytes(stderr)
        if verification:
            import shlex
            # The script is a file in the temp root, not an inline `-c` payload:
            # both halves of the command then stay clear of the contract's
            # per-command character cap however deep the checkout sits (#1474).
            reconfigure = (f'sys.stderr.reconfigure(newline={verification_newline!r})\n'
                           if verification_newline else '')
            failing_script = root / 'fail.py'
            _ = failing_script.write_text(
                'import sys\n'
                + reconfigure
                + 'sys.stderr.buffer.write(b"compiler failed\\n")\n'
                  'sys.exit(7)\n',
                encoding='utf-8',
            )
            unit['verification_commands'] = [
                shlex.join([verification_python_path(), str(failing_script)])
            ]
        contract = write_fanout_contract(paths, build_fanout_contract(goal, [unit]))
        fanout_id = str(contract['fanout_id'])
        run_ref = fanout_id + '-core'
        payload = {'schema_version': 'fanout_unit_result/v1', 'unit_id': 'core',
                   'run_id': run_ref, 'fanout_id': fanout_id, 'base_sha': base,
                   'head_sha': base, 'process_status': 'process_succeeded',
                   'changed_paths': ['SOURCE_PRIVATE_SENTINEL.py'],
                   'checks': [{'command': 'PROMPT_PRIVATE_SENTINEL', 'status': 'passed',
                               'evidence_ref': 'EVENT_PRIVATE_SENTINEL', 'reported_by': 'executor',
                               'observed_by': None, 'observation_source': None}],
                   'findings': ['FINDING_PRIVATE_SENTINEL'],
                   'transcript': 'SIDECAR_PRIVATE_SENTINEL'}
        _ = result_file.write_text('{invalid' if sidecar == 'invalid' else json.dumps(payload))
        intake_paths: list[str] = []
        def argv_for_fixture(_owner: str, prompt: str,
                             _route: Mapping[str, object] | None = None) -> list[str]:
            match = re.search(r'JSON sidecar to exactly (.+)\.', prompt)
            if match is None:
                raise AssertionError('fixture_sidecar_contract_missing')
            intake_paths.append(match[1])
            argv = [sys.executable, fixture, '--stdout-file', str(out),
                    '--stderr-file', str(err), '--exit-code', str(exit_code)]
            if sidecar != 'missing':
                argv += ['--result-file', str(result_file)]
                argv += ['--fenced-result'] if sidecar == 'fenced' else ['--result-path', match[1]]
            commands.append(argv)
            return argv
        codex_state = root / 'codex-state'
        codex_state.mkdir()
        def ready(_paths: OmhPaths, _owner: str) -> dict[str, object]:
            return {'status': 'ready'}
        with (
            patch('omh.coding.fanout_dispatch.build_dispatch_argv', argv_for_fixture),
            patch.dict(os.environ, {'CODEX_HOME': str(codex_state)}),
        ):
            summary = dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                                      base_sha=base, concurrency=1, readiness=ready,
                                      max_retries=0, run_verification=verification,
                                      allow_unconfined=host_cannot_fence_fanout())
        # JSON round-trip gives the same machine-visible public payload a CLI reads.
        decode: Callable[[str], JsonValue] = json.loads
        observations['summary'] = decode(json.dumps(summary))
        observations['run'] = decode(json.dumps(show_run(paths, run_ref)))
        persisted = b'\n'.join(path.read_bytes() for path in paths.omh_home.rglob('*') if path.is_file())
        observations['private_absent'] = all(marker not in persisted for marker in (
            b'PROMPT_PRIVATE_SENTINEL', b'SOURCE_PRIVATE_SENTINEL', b'EVENT_PRIVATE_SENTINEL',
            b'SIDECAR_PRIVATE_SENTINEL', b'FINDING_PRIVATE_SENTINEL', b'Bearer abcdef123456'))
        observations['no_spills'] = not paths.runtime_output_spills_dir.exists()
        observations['ephemeral_intake'] = bool(intake_paths) and all(
            not Path(path).is_relative_to(paths.omh_home) and not Path(path).exists()
            for path in intake_paths)
    return {'case': '', 'commands': commands, 'inputs_metadata': {
                'stdout_bytes': len(stdout), 'stderr_bytes': len(stderr), 'exit_code': exit_code},
            'observations': observations, 'pass': False, 'blocked_reason': None,
            'provenance': {'kind': 'fixture', 'scope': 'surface',
                           'native_required': False, 'native_available': False},
            'cleanup': {'owned_resources': [directory], 'terminated_processes': [],
                        'removed_paths': [directory], 'verified_absent': not root.exists(), 'errors': []}}


def run_case(case_id: str, *, verification_newline: str = '') -> CaseResult:
    if case_id not in {'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'S5'}:
        raise ValueError('unknown_diagnostics_case')
    stdout, stderr, code, sidecar, verification = b'', b'compiler failed\n', 3, 'missing', False
    if case_id == 'D2':
        stdout, stderr, code = b'phase A failed\n', b'phase B failed\n', 4
    elif case_id == 'D3':
        stdout = ('\uac00\U0001f642\n' * 1001).encode()
    elif case_id in ('D4', 'S5'):
        stdout = b'PROMPT_PRIVATE_SENTINEL\ndef SOURCE_PRIVATE_SENTINEL(): pass\n'
        stderr = b'Authorization: Bearer abcdef123456\n\x1b[2JEVENT_PRIVATE_SENTINEL\n'
        sidecar = 'valid'
        code = 0 if case_id == 'S5' else 3
    elif case_id == 'D5':
        code, sidecar, verification = 0, 'valid', True
    elif case_id == 'D6':
        stdout = b'\xff\xfe\x80err\n'
    elif case_id == 'D7':
        code, sidecar = 0, 'fenced'
    result = exercise_dispatch(stdout=stdout, stderr=stderr, exit_code=code,
                               sidecar=sidecar, verification=verification,
                               verification_newline=verification_newline)
    result['case'] = case_id
    observations = result['observations']
    summary = observations['summary']
    passed = False
    if is_string_map(summary):
        units = summary.get('units')
        if is_object_list(units) and units and is_string_map(units[0]):
            unit = units[0]
            diagnostic = unit.get('failure_diagnostic')
            if case_id in ('D7', 'S5'):
                passed = (unit.get('process_succeeded') is True and unit.get('result_schema_valid') is True
                          and 'failure_diagnostic' not in unit)
            elif is_string_map(diagnostic):
                streams = diagnostic.get('streams')
                passed = (diagnostic.get('unit_id') == 'core'
                          and diagnostic.get('attempt_id') == unit.get('attempt_id')
                          and diagnostic.get('phase') == ('verification' if verification else 'worker')
                          and diagnostic.get('returncode') == (7 if verification else code))
                if is_object_list(streams) and len(streams) == 2:
                    for name, stream, raw in zip(('stdout', 'stderr'), streams,
                                                 (b'' if verification else stdout, stderr)):
                        if not is_string_map(stream):
                            passed = False
                            continue
                        text = stream.get('text')
                        passed = (passed and isinstance(text, str)
                                  and stream.get('stream') == name
                                  and stream.get('original_bytes') == len(raw)
                                  and stream.get('original_lines') == raw.count(b'\n') + int(bool(raw) and not raw.endswith(b'\n'))
                                  and stream.get('truncated') == (len(raw) > 2000 or raw.count(b'\n') > 20))
                        if raw:
                            passed = passed and bool(text)
                        if case_id == 'D6' and name == 'stdout':
                            passed = passed and stream.get('reason') == 'invalid_utf8'
                        if isinstance(text, str):
                            passed = passed and stream.get('digest') == hashlib.sha256(text.encode()).hexdigest()
                            passed = passed and len(text.encode()) <= 2000 and len(text.splitlines()) <= 20
                else:
                    passed = False
    result['pass'] = bool(passed and observations['private_absent'] and observations['no_spills']
                          and observations['ephemeral_intake'] and result['cleanup']['verified_absent'])
    result['blocked_reason'] = None if result['pass'] else 'diagnostic_observable_failed'
    return result
