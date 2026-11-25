"""Owner-keyed actual-resource parity and conservative companion updates."""
from __future__ import annotations

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

from _local_package import load_local_package
load_local_package()

from omh.core.errors import OmhError
from omh.converter import convert_support_from_dir
from omh.hashutil import sha256_text
from omh.install.agent_skills_projection import install_agent_skills
from omh.install.installer import install_skill_pack
from omh.install.support_materialization import preflight_support, support_records, write_support
from omh.paths import OmhPaths
from omh.skills.catalog import omh_skill_display_name, omh_skill_install_path
from omh.skills.skill_record import project, skill_record
from omh.skills.support_files import builtin_skill_support_templates

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("geospatial-analysis", "biomedical-evidence", "molecular-docking")


def expected_support():
    return {(t.skill_name, t.relative_path): t.content for t in builtin_skill_support_templates() if t.skill_name in DOMAINS}


def write_tap(root):
    for owner in DOMAINS:
        for relative, content in project(skill_record(owner), "hermes").items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode())


class DomainDistributionTests(unittest.TestCase):
    def test_closed_owner_maps_across_records_tap_portable_and_local_source(self):
        expected = expected_support()
        self.assertEqual({owner: sum(o == owner for o, _ in expected) for owner in DOMAINS},
                         {"geospatial-analysis": 6, "biomedical-evidence": 3, "molecular-docking": 5})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("subprocess.Popen", side_effect=AssertionError("hidden process")), patch("socket.socket", side_effect=AssertionError("hidden network")):
                write_tap(root / "tap")
                for owner in DOMAINS:
                    record = skill_record(owner)
                    self.assertEqual({(t.skill_name, t.relative_path): t.content for t in record.support()},
                                     {key: value for key, value in expected.items() if key[0] == owner})
                    for target in ("hermes", "agent-skills"):
                        files = project(record, target)
                        for (o, relative), content in expected.items():
                            if o == owner:
                                self.assertEqual(files[f"{record.display_name}/{relative}"], content)
                imported = convert_support_from_dir(root / "tap")
                self.assertEqual({(t.skill_name, t.relative_path): t.content for t in imported}, expected)
                native = OmhPaths(root / "native", root / "hermes")
                install_skill_pack(native)
                local = OmhPaths(root / "local", root / "local-hermes")
                install_skill_pack(local, source="explicit-local", source_dir=root / "tap")
                install_agent_skills(root / "portable")
            for (owner, relative), text in expected.items():
                for base in (native.skills_dir / omh_skill_install_path(owner), local.skills_dir / omh_skill_install_path(owner),
                             root / "portable" / omh_skill_display_name(owner), root / "tap" / omh_skill_display_name(owner),
                             ROOT / "skills" / omh_skill_display_name(owner), ROOT / "agent-skills" / omh_skill_display_name(owner)):
                    self.assertEqual((base / relative).read_bytes(), text.encode(), str(base / relative))

    def test_local_source_missing_extra_changed_symlink_and_owner_isolation(self):
        for owner in DOMAINS:
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                for relative, content in project(skill_record(owner), "hermes").items():
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content.encode())
                self.assertEqual({t.skill_name for t in convert_support_from_dir(root)}, {owner})
                extra = root / omh_skill_display_name(owner) / "toolkit/undeclared.py"
                extra.write_text("unreviewed")
                with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                    convert_support_from_dir(root)
                extra.unlink()
                sample = extra.parent / "README.md"
                original = sample.read_bytes()
                sample.unlink()
                with self.assertRaises(ValueError):
                    convert_support_from_dir(root)
                sample.write_bytes(b"edited")
                with self.assertRaises(ValueError):
                    convert_support_from_dir(root)
                sample.unlink()
                foreign = root / "foreign.md"
                foreign.write_bytes(original)
                sample.symlink_to(foreign)
                with self.assertRaises(ValueError):
                    convert_support_from_dir(root)
                self.assertEqual(foreign.read_bytes(), original)
                sample.unlink()
                sample.write_bytes(original)
                sample.parent.rename(root / "hidden-toolkit")
                with self.assertRaisesRegex(ValueError, "toolkit missing"):
                    convert_support_from_dir(root)

    def test_native_fresh_upgrade_edited_force_unowned_and_stale_selective_owner(self):
        templates = [t for t in builtin_skill_support_templates() if t.skill_name in DOMAINS]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = {"support_files": {}}
            current = preflight_support(root, templates, manifest)
            manifest["support_files"] = write_support(root, current, manifest, rendered_names=set(DOMAINS))
            first = dict(manifest["support_files"])
            current = preflight_support(root, templates, manifest)
            self.assertEqual(write_support(root, current, manifest, rendered_names=set(DOMAINS)), first)
            for owner in DOMAINS:
                rel = omh_skill_install_path(owner) + "/toolkit/README.md"
                target = root / rel
                original = target.read_bytes()
                target.write_text("user edit")
                before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                with self.assertRaisesRegex(OmhError, "edited support"):
                    preflight_support(root, templates, manifest)
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                forced = preflight_support(root, templates, manifest, overwrite=True)
                write_support(root, forced, manifest, rendered_names=set(DOMAINS))
                self.assertEqual(target.read_bytes(), original)
                unowned = {"support_files": {k: v for k, v in first.items() if k != rel}}
                target.write_text("foreign collision")
                with self.assertRaisesRegex(OmhError, "unowned support"):
                    preflight_support(root, templates, unowned, overwrite=True)
                self.assertEqual(target.read_text(), "foreign collision")
                target.write_bytes(original)
            for owner in DOMAINS:
                target = root / omh_skill_install_path(owner) / "toolkit/README.md"
                for name in ("retired.py", "retired-edited.py", "foreign.py"):
                    path = target.parent / name
                    path.write_text("old")
                    if name != "foreign.py":
                        manifest["support_files"][path.relative_to(root).as_posix()] = sha256_text("old")
                (target.parent / "retired-edited.py").write_text("edited stale")
            selected = DOMAINS[0]
            current = preflight_support(root, [t for t in templates if t.skill_name == selected], manifest)
            records = write_support(root, current, manifest, rendered_names={selected})
            for owner in DOMAINS:
                base = root / omh_skill_install_path(owner) / "toolkit"
                self.assertEqual((base / "retired.py").exists(), owner != selected)
                self.assertEqual((base / "retired-edited.py").read_text(), "edited stale")
                self.assertEqual((base / "foreign.py").read_text(), "old")
                self.assertIn(omh_skill_install_path(owner) + "/toolkit/README.md", records)

    def test_native_manifest_and_destination_guards_for_each_owner(self):
        for owner in DOMAINS:
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                prefix = omh_skill_install_path(owner) + "/"
                for suffix in ("toolkit/../x.py", "toolkit/CON.py", "toolkit/x.py:ads", "toolkit/x.bin"):
                    with self.assertRaises(OmhError):
                        support_records({"support_files": {prefix + suffix: "a" * 64}})
                with self.assertRaises(OmhError):
                    support_records({"support_files": {prefix + "toolkit/a.py": "a" * 64, prefix + "toolkit/A.py": "b" * 64}})
                with self.assertRaises(OmhError):
                    support_records({"support_files": {"operator/unknown/toolkit/a.py": "a" * 64}})
                dest = root / omh_skill_install_path(owner)
                dest.mkdir(parents=True)
                (dest / "toolkit").symlink_to(root / "foreign", target_is_directory=True)
                with self.assertRaisesRegex(OmhError, "symlink"):
                    preflight_support(root, list(skill_record(owner).support()), None)
                self.assertFalse((root / "foreign").exists())

    def test_host_adapters_fresh_unchanged_edited_unowned_and_stale(self):
        expected = expected_support()
        for host in ("cursor", "claude", "codex", "opencode", "openclaw", "pi", "antigravity"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                target = root / (".claude/skills" if host == "claude" else ".agents/skills")
                command = ["sh", str(ROOT / f".{host}/install.sh")]
                sample = target / "omh-geospatial-analysis/toolkit/README.md"
                sample.parent.mkdir(parents=True)
                sample.write_text("foreign")
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sample.read_text(), "foreign")
                self.assertFalse((target / "omh-biomedical-evidence/SKILL.md").exists())
                sample.unlink()
                for _ in range(2):
                    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for (owner, relative), content in expected.items():
                    self.assertEqual((target / omh_skill_display_name(owner) / relative).read_bytes(), content.encode())
                for owner in DOMAINS:
                    sample = target / omh_skill_display_name(owner) / "toolkit/README.md"
                    original = sample.read_bytes()
                    sample.write_text("edited owned")
                    manifest = target / ".omh-agent-skills-manifest.json"
                    before = manifest.read_bytes()
                    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(sample.read_text(), "edited owned")
                    self.assertEqual(manifest.read_bytes(), before)
                    sample.write_bytes(original)
                document = json.loads(manifest.read_text())
                for owner in DOMAINS:
                    prefix = omh_skill_display_name(owner) + "/toolkit/"
                    for name in ("retired.py", "retired-edited.py"):
                        rel = prefix + name
                        (target / rel).write_text("old")
                        document["files"][rel] = sha256_text("old")
                    (target / prefix / "retired-edited.py").write_text("user edit")
                manifest.write_text(json.dumps(document))
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                for owner in DOMAINS:
                    base = target / omh_skill_display_name(owner) / "toolkit"
                    # Clone adapters conservatively preserve retired files;
                    # Python portable installation separately owns cleanup.
                    self.assertEqual((base / "retired.py").read_text(), "old")
                    self.assertEqual((base / "retired-edited.py").read_text(), "user edit")

    def test_tap_gate_detects_missing_and_undeclared_actual_domain_resources(self):
        from omh.commands.docs import tap_skills_check_payload
        for owner in DOMAINS:
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                write_tap(root)
                rel = omh_skill_display_name(owner) + "/toolkit/README.md"
                (root / rel).unlink()
                self.assertIn(rel, tap_skills_check_payload(root)["missing"])
                extra = omh_skill_display_name(owner) + "/toolkit/undeclared.py"
                (root / extra).write_text("foreign")
                self.assertIn(extra, tap_skills_check_payload(root)["extra"])

    def test_domain_resource_line_endings_are_explicit_lf(self):
        paths = []
        for owner, relative in expected_support():
            stem = owner.replace("-", "_") + "_toolkit"
            paths.extend([f"src/skills/{stem}/{relative.removeprefix('toolkit/')}",
                          f"skills/{omh_skill_display_name(owner)}/{relative}",
                          f"agent-skills/{omh_skill_display_name(owner)}/{relative}"])
        result = subprocess.run(["git", "check-attr", "eol", "--", *paths], cwd=ROOT, capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(len(result.stdout.splitlines()), len(paths))
        self.assertTrue(all(line.endswith(": eol: lf") for line in result.stdout.splitlines()), result.stdout)


class BuiltDomainDistributionTests(unittest.TestCase):
    def test_real_wheel_sdist_fresh_install_source_hidden_materializers_and_helpers(self):
        expected = expected_support()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = subprocess.run(["uv", "build", "--out-dir", str(root / "dist")], cwd=ROOT, capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            wheels = list((root / "dist").glob("*.whl"))
            sdists = list((root / "dist").glob("*.tar.gz"))
            self.assertEqual((len(wheels), len(sdists)), (1, 1))
            with zipfile.ZipFile(wheels[0]) as wheel, tarfile.open(sdists[0]) as sdist:
                for (owner, relative), content in expected.items():
                    stem = owner.replace("-", "_") + "_toolkit"
                    package_path = f"omh/skills/{stem}/{relative.removeprefix('toolkit/')}"
                    self.assertEqual(wheel.read(package_path), content.encode())
                    suffix = f"src/skills/{stem}/{relative.removeprefix('toolkit/')}"
                    members = [m for m in sdist.getmembers() if m.name.endswith('/' + suffix)]
                    self.assertEqual(len(members), 1, suffix)
                    self.assertEqual(sdist.extractfile(members[0]).read(), content.encode())
            python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            for command in (["uv", "venv", "--python", sys.executable, str(root / "venv")],
                            ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])]):
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr)
            script = r'''
import hashlib,json,os,sys
from pathlib import Path
from unittest.mock import patch
forbidden,workspace=map(Path,sys.argv[1:])
def audit(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0])).absolute()
        if path.is_relative_to(forbidden): raise AssertionError('checkout read denied: '+str(path))
    if event=='exec' and args and any(p.endswith('_toolkit') for p in Path(args[0].co_filename).parts):
        raise AssertionError('companion executed during materialization')
sys.addaudithook(audit)
import omh
assert not Path(omh.__file__).is_relative_to(forbidden),omh.__file__
from importlib.util import find_spec
assert all(find_spec(name) is None for name in ('vina','shapely','pyproj','biomcp'))
from omh.skills.support_files import builtin_skill_support_templates
from omh.skills.skill_record import skill_record,project
from omh.skills.catalog import omh_skill_display_name,omh_skill_install_path
from omh.install.installer import install_skill_pack
from omh.install.agent_skills_projection import install_agent_skills
from omh.paths import OmhPaths
owners=('geospatial-analysis','biomedical-evidence','molecular-docking')
expected={(t.skill_name,t.relative_path):t.content for t in builtin_skill_support_templates() if t.skill_name in owners}
with patch('subprocess.Popen',side_effect=AssertionError('hidden process')),patch('socket.socket',side_effect=AssertionError('hidden socket')):
    native=OmhPaths(workspace/'native',workspace/'hermes');install_skill_pack(native);install_skill_pack(native)
    install_agent_skills(workspace/'portable')
    for owner in owners:
        for rel,content in project(skill_record(owner),'hermes').items():
            path=workspace/'tap'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content.encode())
    local=OmhPaths(workspace/'local',workspace/'local-hermes');install_skill_pack(local,source='explicit-local',source_dir=workspace/'tap')
for (owner,relative),content in expected.items():
    for base in (native.skills_dir/omh_skill_install_path(owner),local.skills_dir/omh_skill_install_path(owner),workspace/'tap'/omh_skill_display_name(owner),workspace/'portable'/omh_skill_display_name(owner)):
        assert (base/relative).read_bytes()==content.encode(),str(base/relative)
assert not any('_toolkit' in name for name in sys.modules)
print(json.dumps({'module':omh.__file__,'files':len(expected),'source_reads':'denied','maps_equal':True,'no_companion_execution':True,'sha256':{o+'/'+p:hashlib.sha256(t.encode()).hexdigest() for (o,p),t in expected.items()}}))
'''
            workspace = root / "outside"
            workspace.mkdir()

            result = subprocess.run([str(python), "-I", "-c", script, str(ROOT), str(workspace)], cwd=workspace, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertTrue(receipt["maps_equal"])
            self.assertEqual(receipt["files"], len(expected))
            for owner, helper in zip(DOMAINS, ("analyze.py", "reconcile.py", "dock.py")):
                command = [str(python), "-I", "-S", str(workspace / "tap" / omh_skill_display_name(owner) / "toolkit/scripts" / helper), "--help"]
                result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.lower())



if __name__ == "__main__":
    unittest.main()
