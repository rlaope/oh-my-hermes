from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli
from omh.core.errors import OmhError
from omh.hashutil import sha256_file
from omh.installer import install_skill_pack
from omh.maintenance.doctor import run_doctor
from omh.manifest import read_manifest, write_manifest
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

    def test_installer_prunes_orphaned_managed_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)

            # Simulate a managed skill that the catalog no longer ships: write a
            # dir + record it in the manifest with a matching (unmodified) sha.
            orphan_dir = paths.skills_dir / "legacy-orphan-skill"
            orphan_file = orphan_dir / "SKILL.md"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            orphan_file.write_text("# legacy orphan skill\n", encoding="utf-8")

            manifest = read_manifest(paths.manifest_path)
            assert manifest is not None
            manifest["skills"].append(
                {
                    "name": "legacy-orphan-skill",
                    "path": "legacy-orphan-skill/SKILL.md",
                    "sha256": sha256_file(orphan_file),
                    "source": "builtin",
                }
            )
            write_manifest(paths.manifest_path, manifest)

            result = install_skill_pack(paths)
            self.assertIn("legacy-orphan-skill", result["pruned_skills"])
            self.assertFalse(orphan_dir.exists())

    def test_installer_preserves_modified_orphan_without_force(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)

            orphan_dir = paths.skills_dir / "legacy-orphan-skill"
            orphan_file = orphan_dir / "SKILL.md"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            orphan_file.write_text("# user-edited legacy orphan\n", encoding="utf-8")

            manifest = read_manifest(paths.manifest_path)
            assert manifest is not None
            # Record a sha that does NOT match the on-disk file, marking it as a
            # user-modified orphan. Without --force the installer refuses to touch it.
            manifest["skills"].append(
                {
                    "name": "legacy-orphan-skill",
                    "path": "legacy-orphan-skill/SKILL.md",
                    "sha256": "0" * 64,
                    "source": "builtin",
                }
            )
            write_manifest(paths.manifest_path, manifest)

            with self.assertRaises(OmhError):
                install_skill_pack(paths)
            self.assertTrue(orphan_dir.exists())

    def test_installer_full_to_core_preserves_catalog_skills(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            full_names = {template.name for template in builtin_skill_templates()}
            install_skill_pack(paths, profile="full")

            full_only_names = full_names - set(CORE_PROFILE_SKILLS)
            self.assertTrue(full_only_names)
            for name in full_only_names:
                self.assertTrue((paths.skills_dir / name / "SKILL.md").exists(), name)

            result = install_skill_pack(paths, profile="core", force=True)

            # The catalog-basis prune must never shed sha-unmodified full-only skills
            # on a full->core downgrade reinstall.
            self.assertEqual(result["pruned_skills"], [])
            for name in full_only_names:
                self.assertTrue((paths.skills_dir / name / "SKILL.md").exists(), name)


if __name__ == "__main__":
    unittest.main()
