from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli
from omh.installer import install_skill_pack
from omh.maintenance.doctor import run_doctor
from omh.paths import resolve_paths
from omh.skill_pack import CORE_PROFILE_SKILLS, CORE_SKILLS, builtin_skill_templates


class InstallerSkillProfileTests(unittest.TestCase):
    def test_core_profile_is_a_strict_subset_of_full_and_covers_doctor_core_skills(self) -> None:
        full_names = {template.name for template in builtin_skill_templates()}

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            result = install_skill_pack(paths, dry_run=True)

        self.assertEqual(result["skill_profile"], "core")
        installed_names = set(result["skills"])
        self.assertLess(len(installed_names), len(full_names))
        self.assertTrue(installed_names.issubset(full_names))
        self.assertTrue(set(CORE_SKILLS).issubset(installed_names))
        self.assertEqual(installed_names, set(CORE_PROFILE_SKILLS))
        self.assertNotIn("context_cost_warning", result)

    def test_full_profile_installs_everything_and_emits_context_cost_warning(self) -> None:
        full_names = {template.name for template in builtin_skill_templates()}

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            result = install_skill_pack(paths, profile="full", dry_run=True)

        self.assertEqual(result["skill_profile"], "full")
        self.assertEqual(set(result["skills"]), full_names)
        warning = result["context_cost_warning"]
        self.assertEqual(warning["schema_version"], "omh_skill_profile_context_cost_warning/v1")
        self.assertEqual(warning["profile"], "full")
        self.assertEqual(warning["installed_skill_count"], len(full_names))
        self.assertEqual(warning["core_profile_skill_count"], len(CORE_PROFILE_SKILLS))
        self.assertEqual(warning["extra_skill_count"], len(full_names) - len(CORE_PROFILE_SKILLS))
        self.assertIn("context weight", warning["message"])

    def test_manifest_records_the_installed_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            core_manifest = install_skill_pack(paths)
            self.assertEqual(core_manifest["skill_profile"], "core")
            on_disk = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["skill_profile"], "core")
            self.assertNotIn("context_cost_warning", on_disk)

            full_manifest = install_skill_pack(paths, profile="full", force=True)
            self.assertEqual(full_manifest["skill_profile"], "full")
            self.assertIn("context_cost_warning", full_manifest)
            on_disk = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["skill_profile"], "full")
            self.assertIn("context_cost_warning", on_disk)

    def test_unknown_profile_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            with self.assertRaises(Exception):
                install_skill_pack(paths, profile="everything", dry_run=True)

    def test_core_install_passes_doctors_skill_checks(self) -> None:
        # Mirrors the CLI setup/doctor harness pattern used in test_cli.py: run a
        # real `omh setup` (now defaulting to the core profile) and confirm
        # `omh doctor` still reports every managed skill check as healthy.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]

            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, _stdout, stderr = run_cli(base + ["setup", "--no-interactive"], output_json=False)
            self.assertEqual(status, 0, stderr)

            checks = run_doctor(paths)
            skill_checks = [check for check in checks if check.name.startswith("skill:")]
            # Doctor only requires the small health-floor set (CORE_SKILLS); the
            # core install profile installs a superset of it for messenger flows.
            self.assertEqual(len(skill_checks), len(CORE_SKILLS))
            self.assertTrue(all(check.ok for check in skill_checks), skill_checks)

            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, stdout, stderr = run_cli(base + ["doctor", "--json"], output_json=False)
            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
