"""Career resource distribution and explicit installed-consumer regressions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from _platform_support import requires_posix, requires_secure_dir_io, requires_symlinks
from _local_package import load_local_package
load_local_package()

from omh.converter import convert_support_from_dir
from omh.core.errors import OmhError
from omh.hashutil import sha256_text
from omh.install.agent_skills_projection import install_agent_skills
from omh.install.installer import install_skill_pack
from omh.install.support_materialization import preflight_support, write_support
from omh.paths import OmhPaths
from omh.skills.ai_job_search_skill import TOOLKIT_RESOURCES, ai_job_search_provenance_manifest
from omh.skills.catalog import omh_skill_install_path
from omh.skills.skill_record import project, skill_record

ROOT = Path(__file__).resolve().parents[1]
OWNER = 'ai-job-search'
LABEL = 'omh-ai-job-search'


class AiJobSearchDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        for key in ('HOME', 'TMPDIR', 'OMH_HOME', 'HERMES_HOME'):
            target = self.root / key.lower()
            target.mkdir()
            (target / '.git').write_text('invalid git barrier\n', encoding='utf-8')
            self.env[key] = str(target)
        result = self.run_command(['git', 'rev-parse', '--show-toplevel'], cwd=Path(self.env['HOME']))
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.expected = {t.relative_path: t.content.encode() for t in skill_record(OWNER).support()}

    def run_command(self, command, *, cwd=None, timeout=180):
        return subprocess.run(command, cwd=cwd or self.root, env=self.env, capture_output=True, text=True, timeout=timeout)

    def write_tap(self):
        tap = self.root / 'tap'
        for relative, text in project(skill_record(OWNER), 'hermes').items():
            path = tap / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        return tap

    def test_closed_inventory_parity(self):
        self.assertEqual(set(self.expected), {'toolkit/' + name for name in TOOLKIT_RESOURCES})
        manifest = ai_job_search_provenance_manifest()
        self.assertEqual(set(manifest['files']), set(TOOLKIT_RESOURCES) - {'upstream-manifest.json'})
        with patch.dict(os.environ, self.env, clear=True), patch('subprocess.Popen', side_effect=AssertionError('hidden process')), patch('socket.socket', side_effect=AssertionError('hidden network')):
            tap = self.write_tap()
            imported = convert_support_from_dir(tap)
            self.assertEqual({t.relative_path: t.content.encode() for t in imported}, self.expected)
            native = OmhPaths(self.root / 'native', self.root / 'native-hermes')
            local = OmhPaths(self.root / 'local', self.root / 'local-hermes')
            install_skill_pack(native, profile='full')
            install_skill_pack(local, source='explicit-local', source_dir=tap)
            install_agent_skills(self.root / 'portable')
        for relative, data in self.expected.items():
            for base in (native.skills_dir / omh_skill_install_path(OWNER), local.skills_dir / omh_skill_install_path(OWNER), tap / LABEL, self.root / 'portable' / LABEL, ROOT / 'skills' / LABEL, ROOT / 'agent-skills' / LABEL):
                self.assertEqual((base / relative).read_bytes(), data, str(base / relative))
        execution = native.skills_dir / omh_skill_install_path(OWNER) / 'references/execution-and-qa.md'
        text = execution.read_text(encoding='utf-8')
        for consumer in ('validate --input', 'merge --workspace', 'summary --workspace', 'transition --workspace', 'actual file', 'review'):
            self.assertIn(consumer, text)

    def test_install_update_preservation(self):
        paths = OmhPaths(self.root / 'native', self.root / 'hermes')
        with patch.dict(os.environ, self.env, clear=True):
            install_skill_pack(paths, profile='full')
            install_skill_pack(paths, profile='full')
            base = paths.skills_dir / omh_skill_install_path(OWNER)
            sample = base / 'toolkit/README.md'
            original = sample.read_bytes()
            sample.write_bytes(b'user edited career instructions\n')
            with self.assertRaises(OmhError):
                install_skill_pack(paths, profile='full')
            self.assertEqual(sample.read_bytes(), b'user edited career instructions\n')
            install_skill_pack(paths, force=True, profile='full')
            self.assertEqual(sample.read_bytes(), original)
        templates = list(skill_record(OWNER).support())
        root = self.root / 'support'
        manifest = {'support_files': {}}
        current = preflight_support(root, templates, manifest)
        manifest['support_files'] = write_support(root, current, manifest, rendered_names={OWNER})
        # Force can restore edited owned bytes, never overwrite unowned collisions.
        rel = omh_skill_install_path(OWNER) + '/toolkit/README.md'
        target = root / rel
        target.write_bytes(b'foreign')
        unowned = {'support_files': {k: v for k, v in manifest['support_files'].items() if k != rel}}
        with self.assertRaisesRegex(OmhError, 'unowned support'):
            preflight_support(root, templates, unowned, overwrite=True)
        self.assertEqual(target.read_bytes(), b'foreign')
        target.write_bytes(original)
        for name in ('retired.py', 'edited-retired.py', 'unowned.py'):
            stale = target.parent / name
            stale.write_bytes(b'old')
            if name != 'unowned.py':
                manifest['support_files'][stale.relative_to(root).as_posix()] = sha256_text('old')
        (target.parent / 'edited-retired.py').write_bytes(b'edited')
        current = preflight_support(root, templates, manifest)
        write_support(root, current, manifest, rendered_names={OWNER})
        self.assertFalse((target.parent / 'retired.py').exists())
        self.assertEqual((target.parent / 'edited-retired.py').read_bytes(), b'edited')
        self.assertEqual((target.parent / 'unowned.py').read_bytes(), b'old')

    @requires_symlinks
    def test_local_source_closed_and_linked_protection(self):
        """Explicit local sources must match the one closed owner inventory."""
        tap = self.write_tap()
        sample = tap / LABEL / 'toolkit/README.md'
        original = sample.read_bytes()
        extra = sample.parent / 'unowned.py'
        extra.write_text('unreviewed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            convert_support_from_dir(tap)
        extra.unlink()
        for content in (None, b'edited'):
            sample.unlink()
            if content is not None:
                sample.write_bytes(content)
            with self.assertRaises(ValueError):
                convert_support_from_dir(tap)
            if not sample.exists():
                sample.write_bytes(original)
        sample.unlink()
        foreign = self.root / 'foreign.md'
        foreign.write_bytes(original)
        sample.symlink_to(foreign)
        with self.assertRaises(ValueError):
            convert_support_from_dir(tap)
        self.assertEqual(foreign.read_bytes(), original)

    def test_recorded_host_edit_keep_and_force(self):
        paths = OmhPaths(self.root / 'native', self.root / 'hermes')
        with patch.dict(os.environ, self.env, clear=True):
            install_skill_pack(paths, profile='full')
            body = paths.skills_dir / omh_skill_install_path(OWNER) / 'SKILL.md'
            original = body.read_bytes()
            before = hashlib.sha256(original).hexdigest()
            edited = original + b'\nSynthetic host-owned edit for update preservation.\n'
            body.write_bytes(edited)
            ledger = paths.hermes_home / 'skills/.curator_ledger.jsonl'
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps({'id': 'synthetic-career-edit', 'ts': '2026-10-23T03:00:00+00:00', 'actor': 'curator', 'action': 'patch', 'skill': LABEL, 'evidence': {}, 'before': [{'path': str(body.resolve()), 'sha256': before}], 'after': [{'path': str(body.resolve()), 'sha256': hashlib.sha256(edited).hexdigest()}]}) + '\n', encoding='utf-8')
            kept = install_skill_pack(paths, profile='full')
            self.assertEqual([(row['name'], row['disposition']) for row in kept['hermes_edited_skills']], [(OWNER, 'kept')])
            self.assertEqual(body.read_bytes(), edited)
            forced = install_skill_pack(paths, profile='full', force=True)
            self.assertEqual([(row['name'], row['disposition']) for row in forced['hermes_edited_skills']], [(OWNER, 'replaced')])
            self.assertEqual(body.read_bytes(), original)

    @requires_posix
    def test_portable_host_adapters(self):
        for host in ('cursor', 'claude', 'codex', 'opencode', 'openclaw', 'pi', 'antigravity'):
            with self.subTest(host=host):
                root = self.root / host
                root.mkdir()
                (root / '.git').write_text('invalid git barrier\n', encoding='utf-8')
                command = ['sh', str(ROOT / f'.{host}/install.sh')]
                target = root / ('.claude/skills' if host == 'claude' else '.agents/skills')
                sample = target / LABEL / 'toolkit/README.md'
                sample.parent.mkdir(parents=True)
                sample.write_bytes(b'foreign collision')
                result = self.run_command(command, cwd=root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sample.read_bytes(), b'foreign collision')
                sample.unlink()
                for _ in range(2):
                    result = self.run_command(command, cwd=root)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for relative, data in self.expected.items():
                    self.assertEqual((target / LABEL / relative).read_bytes(), data)
                manifest = target / '.omh-agent-skills-manifest.json'
                receipt = manifest.read_bytes()
                sample.write_bytes(b'edited owned')
                result = self.run_command(command, cwd=root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sample.read_bytes(), b'edited owned')
                self.assertEqual(manifest.read_bytes(), receipt)

    def test_companion_never_imported_or_executed(self):
        # A fresh process detects exec/import events, including runpy, during
        # catalog, router, materialization, repeat update and doctor inspection.
        code = r'''
import os,sys
from pathlib import Path
from unittest.mock import patch
root=Path(sys.argv[1])
def audit(event,args):
    if event=='exec' and args and 'ai_job_search_toolkit' in args[0].co_filename:
        raise AssertionError('inert companion executed')
    if event=='import' and args and 'job_state' in args[0]:
        raise AssertionError('inert companion imported')
sys.addaudithook(audit)
from omh.skills.skill_record import project,skill_record
from omh.skills.catalog import installable_skill_names
from omh.routing.chat import route_chat_message
from omh.install.installer import install_skill_pack
from omh.paths import OmhPaths
from omh.maintenance.doctor import run_doctor
with patch('subprocess.Popen',side_effect=AssertionError('hidden process')),patch('socket.socket',side_effect=AssertionError('hidden network')):
    assert 'ai-job-search' in installable_skill_names()
    assert project(skill_record('ai-job-search'),'agent-skills')
    route_chat_message('Tailor my resume to this supplied posting.')
    paths=OmhPaths(root/'native',root/'hermes')
    install_skill_pack(paths, profile='full');install_skill_pack(paths, profile='full')
    run_doctor(paths)
assert not any('job_state' in name for name in sys.modules)
print('inert discovery, routing, install/update and doctor observed')
'''
        result = self.run_command([sys.executable, '-P', '-c', code, str(self.root)], cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)

    @requires_secure_dir_io
    def test_package_only_helper(self):
        result = self.run_command(['uv', 'build', '--out-dir', str(self.root / 'dist')], cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        wheels = list((self.root / 'dist').glob('*.whl'))
        sdists = list((self.root / 'dist').glob('*.tar.gz'))
        self.assertEqual((len(wheels), len(sdists)), (1, 1))
        with zipfile.ZipFile(wheels[0]) as wheel, tarfile.open(sdists[0]) as sdist:
            for relative, data in self.expected.items():
                name = relative.removeprefix('toolkit/')
                self.assertEqual(wheel.read('omh/skills/ai_job_search_toolkit/' + name), data)
                entries = [m for m in sdist.getmembers() if m.name.endswith('/src/skills/ai_job_search_toolkit/' + name)]
                self.assertEqual(len(entries), 1)
                self.assertEqual(sdist.extractfile(entries[0]).read(), data)
        python = self.root / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        for command in (['uv', 'venv', '--offline', '--python', sys.executable, str(self.root / 'venv')], ['uv', 'pip', 'install', '--offline', '--python', str(python), '--no-deps', str(wheels[0])]):
            result = self.run_command(command)
            self.assertEqual(result.returncode, 0, result.stderr)
        code = r'''
import hashlib,json,os,sys
from pathlib import Path
from unittest.mock import patch
forbidden,root=map(Path,sys.argv[1:])
def audit(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)) and Path(os.fsdecode(args[0])).absolute().is_relative_to(forbidden):
        raise AssertionError('source checkout read denied')
    if event=='exec' and args and 'ai_job_search_toolkit' in args[0].co_filename:
        raise AssertionError('inert companion executed')
sys.addaudithook(audit)
import omh
assert not Path(omh.__file__).is_relative_to(forbidden)
from omh.skills.skill_record import skill_record,project
from omh.install.installer import install_skill_pack
from omh.install.agent_skills_projection import install_agent_skills
from omh.skills.catalog import omh_skill_install_path
from omh.paths import OmhPaths
expected={t.relative_path:t.content.encode() for t in skill_record('ai-job-search').support()}
with patch('subprocess.Popen',side_effect=AssertionError('hidden process')),patch('socket.socket',side_effect=AssertionError('hidden network')):
    native=OmhPaths(root/'native',root/'hermes');install_skill_pack(native, profile='full');install_skill_pack(native, profile='full')
    install_agent_skills(root/'portable')
    for rel,text in project(skill_record('ai-job-search'),'hermes').items():
        target=root/'tap'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(text.encode())
    local=OmhPaths(root/'local',root/'local-hermes');install_skill_pack(local,source='explicit-local',source_dir=root/'tap')
bases=[native.skills_dir/omh_skill_install_path('ai-job-search'),local.skills_dir/omh_skill_install_path('ai-job-search'),root/'tap/omh-ai-job-search',root/'portable/omh-ai-job-search']
for base in bases:
    for rel,data in expected.items(): assert (base/rel).read_bytes()==data
print(json.dumps({'source_reads':'denied','bases':[str(p) for p in bases],'hashes':{p:hashlib.sha256(v).hexdigest() for p,v in expected.items()}}))
'''
        result = self.run_command([str(python), '-I', '-c', code, str(ROOT), str(self.root / 'installed')])
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['source_reads'], 'denied')
        self.assertEqual(receipt['hashes'], {p: hashlib.sha256(v).hexdigest() for p, v in self.expected.items()})
        # Execute all four commands from every installed projection. No package
        # imports or checkout reads are available to the helper; no sockets or
        # process launch is permitted inside its interpreter.
        launcher = r'''
import os,runpy,sys
from pathlib import Path
forbidden=Path(sys.argv.pop(1));script=sys.argv[1]
sys.argv=sys.argv[1:]
def audit(event,args):
    if event.startswith(('socket.','subprocess.')) or event in ('os.system','os.posix_spawn','os.exec'):
        raise AssertionError('offline helper attempted external action')
    if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)) and Path(os.fsdecode(args[0])).absolute().is_relative_to(forbidden):
        raise AssertionError('source checkout read denied')
sys.addaudithook(audit)
runpy.run_path(script,run_name='__main__')
'''
        summaries = []
        for index, base in enumerate(map(Path, receipt['bases'])):
            helper = base / 'toolkit/scripts/job_state.py'
            fixture = base / 'toolkit/examples/synthetic-captures.json'
            workspace = self.root / f'tracker-{index}'
            def invoke(args):
                result = self.run_command([str(python), '-I', '-S', '-c', launcher, str(ROOT), str(helper), *args])
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            validated = invoke(['validate', '--input', str(fixture)])
            self.assertEqual((validated['job_count'], validated['verified_job_count'], validated['source_outcome']), (1, 0, 'partial'))
            merged = invoke(['merge', '--workspace', str(workspace), '--input', str(fixture)])
            job_id, = merged['inserted_job_ids']
            event = invoke(['transition', '--workspace', str(workspace), '--job-id', job_id, '--state', 'draft', '--evidence-type', 'draft_artifact', '--evidence-ref', 'applications/synthetic/v1/resume.md', '--occurred-at', '2026-10-23T03:00:00Z'])
            self.assertEqual(event['application_state'], 'draft')
            summary = invoke(['summary', '--workspace', str(workspace)])
            state = json.loads((workspace / 'state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['jobs'][job_id]['application_state'], 'draft')
            self.assertEqual(summary['application_counts']['submitted'], 0)
            self.assertEqual(summary['application_counts']['draft'], 1)
            summaries.append(summary)
        self.assertTrue(all(summary == summaries[0] for summary in summaries))
        print(json.dumps({'installed_career_resources': receipt['hashes'], 'source_reads': 'denied', 'projection_count': len(summaries), 'summary': summaries[0]}, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
