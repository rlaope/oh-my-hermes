"""Real built distributions and native/portable/local-source support parity."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from _local_package import load_local_package
load_local_package()

ROOT = Path(__file__).resolve().parents[1]


class WheelSupportTests(unittest.TestCase):
    def test_built_wheel_contains_actual_companion_resources(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            result = subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            wheels = list(out.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as wheel:
                self.assertIn("omh/skills/show_reel_toolkit/scripts/render.mjs", wheel.namelist(), "built distribution drops actual executable support data")
                self.assertIn("omh/skills/show_reel_toolkit/upstream-manifest.json", wheel.namelist())
                site = out / "site"
                wheel.extractall(site)
            script = r'''
import sys,os,json,hashlib
from pathlib import Path
site,forbidden,workspace=map(Path,sys.argv[1:])
sys.path=[str(site),*[p for p in sys.path if p and not str(Path(p).absolute()).startswith(str(forbidden))]]
def deny_source(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)) and str(Path(os.fsdecode(args[0])).absolute()).startswith(str(forbidden)+os.sep):
        raise AssertionError('source checkout hidden: '+str(args[0]))
sys.addaudithook(deny_source)
import omh
assert Path(omh.__file__).is_relative_to(site),omh.__file__
from unittest.mock import patch
from omh.skills.support_files import builtin_skill_support_templates
from omh.install.installer import install_skill_pack
from omh.install.agent_skills_projection import install_agent_skills,agent_skill_files
from omh.skills.skill_record import skill_record,project
from omh.paths import OmhPaths
expected={t.relative_path:hashlib.sha256(t.content.encode()).hexdigest() for t in builtin_skill_support_templates() if t.skill_name=='show-reel'}
with patch('subprocess.Popen',side_effect=AssertionError('hidden companion execution')),patch('socket.socket',side_effect=AssertionError('hidden companion network')):
    native=OmhPaths(workspace/'native',workspace/'hermes')
    native_result=install_skill_pack(native)
    portable=workspace/'portable'
    install_agent_skills(portable)
    tap=workspace/'tap'
    for rel,content in project(skill_record('show-reel'),'hermes').items():
        path=tap/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content.encode())
    local=OmhPaths(workspace/'local',workspace/'local-hermes')
    install_skill_pack(local,source='explicit-local',source_dir=tap)
roots=[native.skills_dir/'operator/omh-show-reel',portable/'omh-show-reel',tap/'omh-show-reel',local.skills_dir/'operator/omh-show-reel']
for root in roots:
    actual={rel:hashlib.sha256((root/rel).read_bytes()).hexdigest() for rel in expected}
    assert actual==expected,(root,actual)
assert not any('show_reel_toolkit' in name for name in sys.modules),'core imported executable companion'
print(json.dumps({'module':omh.__file__,'support_files':len(expected),'maps_equal':True,'source_access':'denied_by_audit_hook_and_removed_from_import_path','no_companion_imported':True,'consumers':['builtin-native','portable','tap-producer','explicit-local-source'],'sha256':expected}))
'''
            workspace = out / "hidden-source-run"
            workspace.mkdir()
            result = subprocess.run([sys.executable, "-I", "-c", script, str(site), str(ROOT), str(workspace)], cwd=workspace, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertTrue(receipt["maps_equal"])
            self.assertTrue(receipt["no_companion_imported"])
            self.assertGreater(receipt["support_files"], 0)


class DistributionParityTests(unittest.TestCase):
    def test_record_native_and_portable_return_same_support_without_execution(self):
        from omh.skills.skill_record import skill_record, project
        from omh.skills.support_files import builtin_skill_support_templates
        from omh.install.agent_skills_projection import agent_skill_files
        record = skill_record("show-reel")
        expected = {"omh-show-reel/"+t.relative_path: t.content for t in builtin_skill_support_templates() if t.skill_name == "show-reel"}
        with patch("subprocess.Popen", side_effect=AssertionError("hidden execution")), patch("socket.socket", side_effect=AssertionError("hidden socket")):
            for target in ("hermes", "agent-skills"):
                files = project(record, target)
                self.assertEqual({p: files.get(p) for p in expected}, expected)
            portable = agent_skill_files()
            self.assertEqual({p: portable.get(p) for p in expected}, expected)

    def test_local_source_carries_only_exact_reviewed_declared_bytes(self):
        from omh.skills.support_files import builtin_skill_support_templates
        from omh.converter import convert_support_from_dir
        from omh.install.installer import install_skill_pack
        from omh.paths import OmhPaths
        from omh.skills.skill_record import project, skill_record
        expected = {t.relative_path: t.content for t in builtin_skill_support_templates() if t.skill_name == "show-reel"}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            for rel, content in project(skill_record("show-reel"), "hermes").items():
                file = source / rel
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(content.encode("utf-8"))
            converted = convert_support_from_dir(source)
            self.assertEqual({t.relative_path: t.content for t in converted}, expected)
            paths = OmhPaths(base / "omh", base / "hermes")
            result = install_skill_pack(paths, source="local", source_dir=source)
            self.assertEqual(len(result["support_files"]), len(expected))
            for rel, content in expected.items():
                self.assertEqual((paths.skills_dir / "operator/omh-show-reel" / rel).read_bytes(), content.encode("utf-8"))
                self.assertEqual((source / "omh-show-reel" / rel).read_bytes(), content.encode("utf-8"))
            bad = source / "omh-show-reel/toolkit/scripts/timeline.py"
            bad.write_text("unreviewed changed script", encoding="utf-8", newline="\n")
            with self.assertRaises(ValueError):
                convert_support_from_dir(source)
            bad.unlink()
            bad.symlink_to(base / "foreign.py")
            with self.assertRaises(ValueError):
                convert_support_from_dir(source)

    def test_clone_adapters_preserve_edited_and_foreign_support(self):
        for host in ("cursor", "claude", "codex", "opencode", "openclaw", "pi", "antigravity"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                target = base / (".claude/skills" if host == "claude" else ".agents/skills")
                support = target / "omh-show-reel/toolkit/scripts/timeline.py"
                support.parent.mkdir(parents=True)
                support.write_text("foreign support", encoding="utf-8", newline="\n")
                command = ["sh", str(ROOT / f".{host}/install.sh")]
                result = subprocess.run(command, cwd=base, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, "foreign support overwritten")
                self.assertEqual(support.read_text(encoding="utf-8"), "foreign support")
                self.assertFalse((target / "omh-show-reel/SKILL.md").exists())
                support.unlink()
                result = subprocess.run(command, cwd=base, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                support.write_text("edited support", encoding="utf-8", newline="\n")
                body = target / "omh-show-reel/SKILL.md"
                body.write_text("edited body", encoding="utf-8", newline="\n")
                result = subprocess.run(command, cwd=base, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, "edited support overwritten")
                self.assertEqual(support.read_text(encoding="utf-8"), "edited support")
                self.assertEqual(body.read_text(encoding="utf-8"), "edited body")

    def test_support_symlink_scope_and_dangling_local_toolkit_refuse(self):
        from omh.install.agent_skills_projection import install_agent_skills
        from omh.converter import convert_support_from_dir
        from omh.skills.support_files import checked_support_path
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            real = base / "real"
            real.mkdir()
            alias = base / "alias"
            alias.symlink_to(real, target_is_directory=True)
            # A project under a linked directory (`~/code -> /Volumes/x/code`)
            # is the user's layout: only the install root's own parent and
            # what is below the root are checked, as on main.
            install_agent_skills(alias / "proj/.claude/skills")
            self.assertTrue((real / "proj/.claude/skills/omh-show-reel/toolkit/README.md").is_file())
            self.assertEqual(checked_support_path(alias / "skills/omh-show-reel", "toolkit/README.md"), alias / "skills/omh-show-reel/toolkit/README.md")
            # The root's own parent, the root and the components below it still refuse a link.
            (real / "outer").mkdir()
            (base / "outer-link").symlink_to(real / "outer", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                install_agent_skills(base / "outer-link/skills")
            with self.assertRaisesRegex(ValueError, "symlink"):
                checked_support_path(base / "outer-link/omh-show-reel", "toolkit/README.md")
            (real / "pack/omh-show-reel").mkdir(parents=True)
            (real / "pack/omh-show-reel/toolkit").symlink_to(real / "outer", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                checked_support_path(real / "pack/omh-show-reel", "toolkit/README.md")
            source = base / "source/omh-show-reel"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: show-reel\ndescription: test\n---\n", encoding="utf-8", newline="\n")
            (source / "toolkit").symlink_to(base / "missing", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                convert_support_from_dir(source.parent)

    def test_portable_edited_support_refuses_before_any_write(self):
        from omh.install.agent_skills_projection import install_agent_skills, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "portable"
            install_agent_skills(root)
            support = root / "omh-show-reel/toolkit/scripts/timeline.py"
            support.write_text("user edit", encoding="utf-8", newline="\n")
            body = root / "omh-show-reel/SKILL.md"
            body.write_text("body edit must also survive refused update", encoding="utf-8", newline="\n")
            before = {p: p.read_bytes() for p in (support, body, root / MANIFEST_NAME)}
            with self.assertRaisesRegex(ValueError, "edited support"):
                install_agent_skills(root)
            self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_portable_retired_support_preserves_edits_and_manifest_guards_preflight(self):
        from omh.install.agent_skills_projection import install_agent_skills, MANIFEST_NAME
        from omh.hashutil import sha256_text
        from omh.local_store import atomic_write_json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "portable"
            install_agent_skills(root)
            manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
            unchanged = "omh-show-reel/toolkit/scripts/retired.py"
            edited = "omh-show-reel/toolkit/scripts/retired-edited.py"
            for rel in (unchanged, edited):
                (root / rel).write_text("old", encoding="utf-8", newline="\n")
                manifest["files"][rel] = sha256_text("old")
            (root / edited).write_text("user edit", encoding="utf-8", newline="\n")
            atomic_write_json(root / MANIFEST_NAME, manifest)
            install_agent_skills(root)
            self.assertFalse((root / unchanged).exists())
            self.assertEqual((root / edited).read_text(encoding="utf-8"), "user edit")
            manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
            manifest["files"]["omh-show-reel/toolkit/CON.py"] = "a"*64
            atomic_write_json(root / MANIFEST_NAME, manifest)
            body = root / "omh-show-reel/SKILL.md"
            original = body.read_bytes()
            with self.assertRaises(ValueError):
                install_agent_skills(root)
            self.assertEqual(body.read_bytes(), original)

    def test_profile_reconcile_counts_support_and_preserves_foreign_toolkit(self):
        from omh.install.installer import install_skill_pack, reconcile_skill_profile
        from omh.paths import OmhPaths
        from omh.manifest import read_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = OmhPaths(root / "omh", root / "hermes")
            manifest = install_skill_pack(paths)
            plan = reconcile_skill_profile(paths, dry_run=True)
            self.assertIn("show-reel", plan["would_remove_skills"])
            foreign = paths.skills_dir / "operator/omh-show-reel/toolkit/foreign.py"
            foreign.write_text("foreign", encoding="utf-8", newline="\n")
            reconcile_skill_profile(paths)
            self.assertEqual(foreign.read_text(encoding="utf-8"), "foreign")
            # Retain ownership for preserved files, not other removed owners.
            self.assertEqual(read_manifest(paths.manifest_path)["support_files"],
                             {rel: digest for rel, digest in manifest["support_files"].items() if (paths.skills_dir / rel).is_file()})

    def test_curator_keeps_support_and_carries_ownership_into_new_generation(self):
        from omh.install.installer import install_skill_pack
        from omh.paths import OmhPaths
        from omh.hashutil import sha256_file
        from test_managed_skill_ownership import _append_ledger, _ledger_row
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = OmhPaths(root / "omh", root / "hermes")
            manifest = install_skill_pack(paths)
            relative = "operator/omh-show-reel/toolkit/scripts/timeline.py"
            target = paths.skills_dir / relative
            old_hash = sha256_file(target)
            target.write_text(target.read_text(encoding="utf-8")+"\n# curator edit\n", encoding="utf-8", newline="\n")
            _append_ledger(paths.hermes_home, _ledger_row(target, before=old_hash))
            result = install_skill_pack(paths)
            self.assertIn("# curator edit", target.read_text(encoding="utf-8"))
            self.assertEqual(result["support_files"][relative], manifest["support_files"][relative])
            next_paths = OmhPaths(paths.omh_home, paths.hermes_home, managed_skills_dir=root / "new-generation/skills")
            result = install_skill_pack(next_paths)
            self.assertIn("# curator edit", (next_paths.skills_dir / relative).read_text(encoding="utf-8"))
            self.assertEqual(result["support_files"][relative], old_hash)
            self.assertIn("# curator edit", target.read_text(encoding="utf-8"), "old generation is rollback target")

    def test_native_support_is_owned_profile_scoped_preserved_and_freshness_checked(self):
        from omh.install.installer import install_skill_pack
        from omh.install.guidance_projection import build_guidance_projection_status
        from omh.paths import OmhPaths
        from omh.skills.support_files import builtin_skill_support_templates
        from omh.core.errors import OmhError
        from omh.local_store import atomic_write_json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = OmhPaths(root / "omh", root / "hermes")
            with patch("subprocess.Popen", side_effect=AssertionError("hidden execution")), patch("socket.socket", side_effect=AssertionError("hidden socket")):
                manifest = install_skill_pack(paths)
            from omh.skills.catalog import omh_skill_install_path
            expected = {omh_skill_install_path(t.skill_name)+"/"+t.relative_path: hashlib.sha256(t.content.encode()).hexdigest() for t in builtin_skill_support_templates()}
            self.assertEqual(manifest.get("support_files"), expected)
            sample = paths.skills_dir / "operator/omh-show-reel/toolkit/scripts/timeline.py"
            baseline = sample.read_text(encoding="utf-8")
            sample.unlink()
            status = build_guidance_projection_status(paths.skills_dir, manifest, registered=True, host_observed=False)
            self.assertNotEqual(status["projection"], "fresh")
            manifest = install_skill_pack(paths)
            sample.write_text("user edit", encoding="utf-8", newline="\n")
            before_body = (sample.parents[2] / "SKILL.md").read_bytes()
            with self.assertRaises(OmhError):
                install_skill_pack(paths)
            self.assertEqual(sample.read_text(encoding="utf-8"), "user edit")
            self.assertEqual((sample.parents[2] / "SKILL.md").read_bytes(), before_body)
            with patch.dict(os.environ, {"OMH_SECURITY": "strict"}), self.assertRaises(OmhError):
                install_skill_pack(paths, force=True)
            manifest = install_skill_pack(paths, force=True)
            self.assertEqual(sample.read_text(encoding="utf-8"), baseline)
            foreign = sample.parent / "foreign.py"
            foreign.write_text("foreign", encoding="utf-8", newline="\n")
            retired = sample.parent / "retired.py"
            retired.write_text("previously owned", encoding="utf-8", newline="\n")
            manifest["support_files"][retired.relative_to(paths.skills_dir).as_posix()] = hashlib.sha256(retired.read_bytes()).hexdigest()
            atomic_write_json(paths.manifest_path, manifest)
            manifest = install_skill_pack(paths)
            self.assertFalse(retired.exists())
            self.assertEqual(foreign.read_text(encoding="utf-8"), "foreign")
            legacy = {key: value for key, value in manifest.items() if key != "support_files"}
            self.assertNotEqual(build_guidance_projection_status(paths.skills_dir, legacy, registered=True, host_observed=False)["projection"], "fresh")
            core = OmhPaths(root / "core", root / "core-hermes")
            manifest = install_skill_pack(core, profile="core")
            self.assertFalse(manifest.get("support_files"))
            self.assertEqual(build_guidance_projection_status(core.skills_dir, manifest, registered=True, host_observed=False)["projection"], "fresh")


if __name__ == "__main__":
    unittest.main()
