"""`omh doctor`'s read-only `agent_skills_pack` check for the Codex/.agents pack."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.install import agent_skills_projection as projection
from omh.maintenance import doctor
from omh.paths import resolve_paths


class DoctorAgentSkillsPackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.target = self.home / ".agents/skills"
        self.mirror = self.home / ".claude/skills"
        # Small catalog; the real install, receipt and status paths run.
        self.files = {"omh-demo/SKILL.md": "current guidance\n",
                      "omh-demo/toolkit/helper.py": "print('helper')\n",
                      "omh-other/SKILL.md": "other guidance\n"}
        for patcher in (patch.object(projection, "agent_skill_files", return_value=self.files),
                        patch.object(Path, "home", return_value=self.home),
                        patch.dict("os.environ", {"OMH_AGENT_SKILLS_HOME": str(self.home)})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _check(self):
        return doctor._agent_skills_pack_check()

    def _manifest_path(self):
        return self.target / projection.MANIFEST_NAME

    def _snapshot(self):
        return {str(path.relative_to(self.home)): (path.read_bytes() if path.is_file() else None,
                                                   path.stat().st_mtime_ns)
                for path in self.home.rglob("*")}

    def test_absent_pack_is_ok_and_creates_nothing(self):
        check = self._check()
        self.assertEqual((check.name, check.ok, check.severity), ("agent_skills_pack", True, "ok"))
        self.assertIn("not installed", check.message)
        self.assertFalse((self.home / ".agents").exists())

    def test_fresh_single_target_pack_is_ok(self):
        projection.install_agent_skills(self.target)
        check = self._check()
        self.assertEqual((check.ok, check.severity, check.next_action), (True, "ok", ""))
        revision = projection.agent_skills_status(self.target)["catalog_revision"]
        self.assertIn(revision[:12], check.message)

    def test_fresh_mirrored_pack_is_ok(self):
        projection.install_agent_skills(self.target, mirror=self.mirror)
        check = self._check()
        self.assertEqual((check.ok, check.severity), (True, "ok"))
        self.assertIn(str(self.mirror), check.message)

    def test_stale_revision_warns_with_omh_update(self):
        projection.install_agent_skills(self.target)
        manifest = json.loads(self._manifest_path().read_text(encoding="utf-8"))
        manifest["catalog_revision"] = "old-revision"
        self._manifest_path().write_text(json.dumps(manifest), encoding="utf-8")
        check = self._check()
        self.assertEqual((check.ok, check.severity, check.next_action), (True, "warning", "omh update"))
        self.assertIn("stale", check.message)
        self.assertTrue(doctor.doctor_ok([check]))

    def test_catalog_change_counts_differing_files(self):
        projection.install_agent_skills(self.target)
        self.files["omh-demo/SKILL.md"] = "new guidance\n"
        self.files["omh-new/SKILL.md"] = "added\n"
        check = self._check()
        self.assertEqual((check.severity, check.next_action), ("warning", "omh update"))
        self.assertIn("2 file(s) differ from the current catalog", check.message)

    def test_locally_modified_file_warns_with_status_next_action(self):
        projection.install_agent_skills(self.target)
        (self.target / "omh-demo/SKILL.md").write_text("my edit\n", encoding="utf-8")
        check = self._check()
        status = projection.agent_skills_status(self.target)
        self.assertEqual((check.ok, check.severity), (True, "warning"))
        self.assertIn("1 locally-modified file(s)", check.message)
        self.assertEqual(check.next_action, status["next_action"])
        self.assertNotEqual(check.next_action, "omh update")

    def test_unreadable_manifest_warns_unobserved(self):
        self.target.mkdir(parents=True)
        self._manifest_path().write_text("{not json", encoding="utf-8")
        check = self._check()
        self.assertEqual((check.ok, check.severity, check.observed), (True, "warning", False))
        self.assertIn("could not read", check.message)

    def test_check_writes_nothing_under_home(self):
        projection.install_agent_skills(self.target, mirror=self.mirror)
        (self.target / "omh-demo/SKILL.md").write_text("my edit\n", encoding="utf-8")
        before = self._snapshot()
        for _ in range(2):
            self._check()
        self.assertEqual(self._snapshot(), before)

    def test_run_doctor_includes_the_check_after_skill_layout(self):
        projection.install_agent_skills(self.target)
        paths = resolve_paths(self.home / ".omh", self.home / ".hermes")
        names = [check.name for check in doctor.run_doctor(paths, state_write=False)]
        self.assertIn("agent_skills_pack", names)
        self.assertEqual(names.index("agent_skills_pack"), names.index("skill_layout") + 1)


if __name__ == "__main__":
    unittest.main()
