"""Update refreshes only an installed user Agent Skills pack, without taking ownership."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from omh.commands import setup
from omh.install import agent_skills_projection as projection


class UpdateAgentSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.target = self.home / ".agents/skills"
        self.mirror = self.home / ".claude/skills"
        # Small catalog; the real install, receipt, preflight and status paths run.
        self.files = {"omh-demo/SKILL.md": "current guidance\n",
                      "omh-demo/toolkit/helper.py": "print('helper')\n"}
        self.catalog = patch.object(projection, "agent_skill_files", return_value=self.files)
        self.catalog.start()
        self.addCleanup(self.catalog.stop)

    def _old_pack(self, *, mirrored=False):
        projection.install_agent_skills(self.target, mirror=self.mirror if mirrored else None)
        path = self.target / projection.MANIFEST_NAME
        manifest = json.loads(path.read_text())
        manifest["catalog_revision"] = "old-revision"
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def _snapshot(self):
        return {path.relative_to(self.home): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.home.rglob("*") if path.is_file()}

    def _update(self, *options, output_json=True):
        # Exercise cmd_update through the CLI, isolating the other update phases.
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, "home", return_value=self.home))
            stack.enter_context(patch.object(setup, "_command_package_self_update_plan", return_value={}))
            stack.enter_context(patch.object(setup, "cmd_install", return_value=0))
            stack.enter_context(patch.object(setup, "_paths", return_value=SimpleNamespace(
                hermes_plugin_dir=self.home / "absent-plugin", hermes_home=self.home / ".hermes")))
            stack.enter_context(patch.object(setup, "_bootstrap_tui_surface", return_value={}))
            stack.enter_context(patch.object(setup, "_refresh_installed_menubar_app", return_value=None))
            profiles = stack.enter_context(patch.object(setup, "_sync_hermes_profiles", return_value=[]))
            stack.enter_context(patch.object(setup, "refresh_skill_dir_caches", return_value=[]))
            stack.enter_context(patch.object(setup, "managed_current_workflow_pack_dir", return_value=None))
            stack.enter_context(patch.object(setup, "gateway_restart_hints", return_value=[]))
            stack.enter_context(patch.object(setup, "_registration_ambiguity_lines", return_value=[]))
            result = run_cli(["update", *options], output_json=output_json)
            profiles.assert_called_once()
            return result

    def test_refreshes_old_single_target_and_preserves_unrelated_files(self):
        self._old_pack()
        personal = self.target / "personal/SKILL.md"
        personal.parent.mkdir()
        personal.write_text("personal guidance", encoding="utf-8")
        repo = self.home / "repo/.agents/skills/foreign.md"
        repo.parent.mkdir(parents=True)
        repo.write_text("repo pack", encoding="utf-8")
        before = {path: path.read_bytes() for path in (personal, repo)}
        result = projection.refresh_installed_agent_skills(self.home, dry_run=False)
        self.assertEqual(result["projection_before"], "stale")
        self.assertEqual(result["projection_after"], "fresh")
        self.assertEqual(result["target_dirs"], [str(self.target)])
        self.assertEqual(json.loads((self.target / projection.MANIFEST_NAME).read_text())["target_dirs"], ["."])
        self.assertFalse(self.mirror.exists())
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_refreshes_mirrored_receipt_as_two_roots(self):
        self._old_pack(mirrored=True)
        result = projection.refresh_installed_agent_skills(self.home, dry_run=False)
        self.assertEqual(result["target_dirs"], [str(self.target), str(self.mirror)])
        self.assertEqual(result["projection_after"], "fresh")
        self.assertEqual((self.target / projection.MANIFEST_NAME).read_bytes(),
                         (self.mirror / projection.MANIFEST_NAME).read_bytes())

    def test_dry_run_reports_roots_and_writes_nothing(self):
        self._old_pack()
        before = self._snapshot()
        result = projection.refresh_installed_agent_skills(self.home, dry_run=True)
        self.assertEqual(result, {"would_refresh": [str(self.target)]})
        status, stdout, stderr = self._update("--dry-run")
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["agent_skills"], result)
        self.assertEqual(self._snapshot(), before)

    def test_absent_pack_is_not_created(self):
        for dry_run in (True, False):
            self.assertIsNone(projection.refresh_installed_agent_skills(self.home, dry_run=dry_run))
        status, stdout, stderr = self._update()
        self.assertEqual(status, 0, stderr)
        self.assertIsNone(json.loads(stdout)["agent_skills"])
        status, stdout, stderr = self._update(output_json=False)
        self.assertEqual(status, 0, stderr)
        self.assertNotIn("Agent Skills (Codex/.agents)", stdout)
        self.assertFalse((self.home / ".agents").exists())

    def test_cmd_update_refreshes_and_prints_file_count(self):
        self._old_pack()
        status, stdout, stderr = self._update()
        self.assertEqual(status, 0, stderr)
        result = json.loads(stdout)["agent_skills"]
        self.assertEqual((result["projection_before"], result["projection_after"]), ("stale", "fresh"))
        status, stdout, stderr = self._update(output_json=False)
        self.assertEqual(status, 0, stderr)
        self.assertIn("Agent Skills (Codex/.agents): refreshed 2 files", stdout)

    def test_edited_toolkit_is_reported_without_aborting_other_phases(self):
        self._old_pack()
        (self.target / "omh-demo/toolkit/helper.py").write_text("local edit", encoding="utf-8")
        before = self._snapshot()
        status, stdout, _ = self._update()
        self.assertEqual(status, 1)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["failures"][0]["phase"], "agent_skills")
        self.assertIn("refuses edited support", payload["failures"][0]["error"])
        self.assertEqual(self._snapshot(), before)

    def test_unowned_collision_is_reported_without_writes(self):
        self._old_pack()
        self.files["omh-new/SKILL.md"] = "new skill\n"
        collision = self.target / "omh-new/SKILL.md"
        collision.parent.mkdir()
        collision.write_text("personal skill", encoding="utf-8")
        before = self._snapshot()
        status, stdout, _ = self._update()
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stdout)["failures"][0]["phase"], "agent_skills")
        self.assertIn("unowned file collision", json.loads(stdout)["failures"][0]["error"])
        self.assertEqual(self._snapshot(), before)

    def test_io_error_is_a_failure_row(self):
        with patch.object(projection, "refresh_installed_agent_skills", side_effect=OSError("read failed")):
            status, stdout, _ = self._update()
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stdout)["failures"], [{"phase": "agent_skills", "error": "OSError: read failed"}])


if __name__ == "__main__":
    unittest.main()
