"""Read-only diagnostics measure the managed pack in use (#2358, #2378).

A managed install serves skills from a generation's own pack behind the
shared `current` pointer, and a host migrated from the pre-pointer layout
keeps `<omh_home>/skills` as a frozen copy that the `bootstrap-legacy`
generation links to. Three readers got that wrong:

- the doctor advisory `workflow_engine_reach` rebuilt its paths from
  `omh_home` and measured `<omh_home>/skills`: the frozen copy, which lacks
  every engine released after the migration, or nothing at all;
- the plugin bundle's standalone probe looked for `<omh_home>/skills` as a
  substring of the Hermes config, which registers the pointer;
- `omh doctor` read support files through the bootstrap generation's
  `skills` link, which the support reader refuses, and aborted the report.

Each case below builds both install shapes: a home with a resolved managed
pack and a retained pre-pointer copy, and one without that copy.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.install.installer import install_skill_pack
from omh.maintenance import advisory
from omh.maintenance.advisory import check_workflow_engine_reach
from omh.maintenance.doctor import doctor_ok, run_doctor, run_doctor_advisories
from omh.paths import OmhPaths, resolve_paths
from omh.plugin_bundle.omh.tools import probe_tool
from omh.skills.catalog import omh_skill_install_path, ulw_inventory_payload
from omh.system import paths as system_paths

_DAG_ULW = omh_skill_install_path("dag-ulw")
# Every fixture links a generation behind the `current` pointer, as the
# installer does; a Windows runner without symlink rights cannot build one.
_LINKS = unittest.skipIf(os.name == "nt", "the managed layout under test is built from directory symlinks")


def _engine_entry(paths: OmhPaths):
    return {entry.check_id: entry for entry in run_doctor_advisories(paths).entries}["workflow_engine_reach"]


def _probe_rows(home: Path, hermes: Path) -> dict[str, dict[str, str]]:
    rows = probe_tool._standalone_capabilities(home, hermes, {}, {}, plugin_observation=None)
    return {row["name"]: row for row in rows}


class _ManagedHome:
    """A managed install: `<root>/share/omh/{generations/g2,current}`, a Hermes home and an OMH home."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.hermes = root / ".hermes"
        self.hermes.mkdir()
        self.omh_home = root / ".omh"
        self.managed_root = root / "share" / "omh"
        self.generation = self.managed_root / "generations" / "g2"
        self.pack = self.generation / "skills"
        self.pointer = self.managed_root / "current" / "skills"
        self.paths = OmhPaths(self.omh_home, self.hermes, managed_skills_dir=self.pack)
        install_skill_pack(self.paths, profile="full")
        os.symlink(self.generation, self.managed_root / "current", target_is_directory=True)

    def register(self, entry: Path | str) -> None:
        (self.hermes / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n  - /elsewhere/team-skills\n  - {entry}\n", encoding="utf-8"
        )

    def freeze_pre_pointer_copy(self) -> None:
        """The copy a migrated host keeps: every skill but the engine released after it."""
        shutil.copytree(self.pack, self.omh_home / "skills")
        shutil.rmtree(self.omh_home / "skills" / _DAG_ULW)

    def env(self) -> dict[str, str]:
        return {"OMH_VENV_DIR": str(self.managed_root / "venv")}


@_LINKS
class WorkflowEngineReachMeasuresThePackInUseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.home = _ManagedHome(self.root)
        self.home.register(self.home.pointer)
        self.engines = len(ulw_inventory_payload()["canonical_engines"])

    def test_a_migrated_home_is_not_told_an_engine_the_pack_holds_is_missing(self) -> None:
        self.home.freeze_pre_pointer_copy()
        entry = _engine_entry(self.home.paths)
        self.assertEqual(entry.status, "ok", entry.observed)
        self.assertEqual(entry.observed, f"all {self.engines} ULW workflow engine(s) installed; profile=full")
        self.assertNotIn("dag-ulw", entry.observed)

    def test_a_home_without_a_pre_pointer_copy_is_measured_not_reported_uninstalled(self) -> None:
        self.assertFalse((self.home.omh_home / "skills").exists())
        entry = _engine_entry(self.home.paths)
        self.assertEqual(entry.status, "ok", entry.observed)

    def test_called_without_a_directory_it_resolves_the_running_generation_like_resolve_paths(self) -> None:
        self.home.freeze_pre_pointer_copy()
        with mock.patch.object(advisory, "managed_workflow_pack_dir", return_value=self.home.pack):
            entry = check_workflow_engine_reach(self.home.hermes, omh_home=self.home.omh_home)
        self.assertEqual(entry.status, "ok", entry.observed)

    def test_an_unmanaged_home_still_measures_its_own_skills_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp).resolve() / ".omh", Path(tmp).resolve() / ".hermes")
            plain = dataclasses.replace(paths, managed_skills_dir=None)
            install_skill_pack(plain, profile="core")
            entry = _engine_entry(plain)
            self.assertEqual(entry.status, "advice")
            self.assertIn("dag-ulw", entry.observed)

    def test_an_unobserved_report_names_what_was_missing(self) -> None:
        empty = OmhPaths(self.root / "empty-omh", self.home.hermes, managed_skills_dir=self.root / "no-pack")
        entry = _engine_entry(empty)
        self.assertEqual(entry.status, "unobserved")
        self.assertIn(str(empty.manifest_path), entry.observed)
        self.assertNotIn("no OMH skill install found", entry.observed)

        (self.root / "empty-omh").mkdir()
        shutil.copy(self.home.paths.manifest_path, empty.manifest_path)
        entry = _engine_entry(empty)
        self.assertEqual(entry.status, "unobserved")
        self.assertIn(f"no OMH skills in {self.root / 'no-pack'}", entry.observed)

    def test_the_advisory_still_never_moves_the_doctor_status(self) -> None:
        self.home.freeze_pre_pointer_copy()
        checks = run_doctor(self.home.paths)
        self.assertNotIn("workflow_engine_reach", {check.name for check in checks})
        self.assertEqual(doctor_ok(checks), doctor_ok(run_doctor(self.home.paths)))


@_LINKS
class StandaloneProbeReadsThePackInUseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.home = _ManagedHome(self.root)
        self.enterContext(mock.patch.dict(os.environ, self.home.env()))

    def _rows(self) -> dict[str, dict[str, str]]:
        return _probe_rows(self.home.omh_home, self.home.hermes)

    def test_every_accepted_spelling_of_the_managed_pack_reads_registered(self) -> None:
        self.home.freeze_pre_pointer_copy()
        spellings = {
            "pointer": self.home.pointer,
            "pointer with trailing slash": f"{self.home.pointer}/",
            "generation": self.home.pack,
            "another generation": self.home.managed_root / "generations" / "g1" / "skills",
            "pre-pointer": self.home.omh_home / "skills",
        }
        for label, entry in spellings.items():
            with self.subTest(spelling=label):
                self.home.register(entry)
                row = self._rows()["external_skill_dirs"]
                self.assertEqual(row["status"], "available", row["message"])

    def test_a_config_naming_no_managed_pack_still_reads_missing(self) -> None:
        self.home.register(self.root / "someone-elses" / "skills")
        row = self._rows()["external_skill_dirs"]
        self.assertEqual(row["status"], "missing")

    def test_an_inline_list_naming_the_pointer_reads_registered(self) -> None:
        (self.home.hermes / "config.yaml").write_text(
            f"skills:\n  external_dirs: [/elsewhere/team-skills, '{self.home.pointer}']  # managed\n", encoding="utf-8"
        )
        self.assertEqual(self._rows()["external_skill_dirs"]["status"], "available")

    def test_managed_skills_reflects_the_pack_in_use_in_both_shapes(self) -> None:
        self.home.register(self.home.pointer)
        row = self._rows()["managed_skills"]
        self.assertEqual(row["status"], "available", row)
        self.assertTrue(row["evidence"].startswith(str(self.home.pack)), row["evidence"])

        self.home.freeze_pre_pointer_copy()
        row = self._rows()["managed_skills"]
        self.assertEqual(row["status"], "available")
        self.assertTrue(row["evidence"].startswith(str(self.home.pack)), row["evidence"])

    def test_a_home_with_no_install_still_reads_missing(self) -> None:
        bare = self.root / "bare-omh"
        row = _probe_rows(bare, self.home.hermes)["managed_skills"]
        self.assertEqual(row["status"], "missing")

    def test_the_bundle_root_matches_the_package_reading(self) -> None:
        cases = {
            "explicit venv": {"OMH_VENV_DIR": str(self.root / "venvs" / "omh" / "venv")},
            "xdg": {"OMH_VENV_DIR": "", "XDG_DATA_HOME": str(self.root / "xdg")},
            "home": {"OMH_VENV_DIR": "", "XDG_DATA_HOME": "", "HOME": str(self.root), "USERPROFILE": str(self.root)},
        }
        for label, env in cases.items():
            with self.subTest(case=label), mock.patch.dict(os.environ, env):
                for key, value in env.items():
                    if not value:
                        os.environ.pop(key, None)
                expected = system_paths.managed_command_root()
                actual = probe_tool._managed_command_root()
                self.assertIsNotNone(actual)
                self.assertEqual(actual.resolve(), expected.resolve())


@_LINKS
class DoctorReadsThroughTheBootstrapLegacyLinkTests(unittest.TestCase):
    """#2378: a migrated host's doctor ran into the support reader's link refusal."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.omh_home = self.root / ".omh"
        legacy = OmhPaths(self.omh_home, self.hermes)
        install_skill_pack(legacy, profile="full")
        self.managed_root = self.root / "share" / "omh"
        self.alias = self.managed_root / "generations" / "bootstrap-legacy" / "skills"
        self.alias.parent.mkdir(parents=True)
        self.alias.symlink_to(legacy.skills_dir, target_is_directory=True)
        os.symlink(self.alias.parent, self.managed_root / "current", target_is_directory=True)
        (self.hermes / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n  - {self.managed_root / 'current' / 'skills'}\n", encoding="utf-8"
        )
        self.paths = OmhPaths(self.omh_home, self.hermes, managed_skills_dir=self.alias)

    def test_doctor_reports_every_check_on_a_migrated_home(self) -> None:
        checks = {check.name: check for check in run_doctor(self.paths)}
        for name in ("manifest_skills_dir", "local_modifications", "guidance_projection", "external_dir"):
            with self.subTest(check=name):
                self.assertTrue(checks[name].ok, checks[name].message)
        self.assertNotIn("skills_dir_link", checks)

    def test_an_edited_support_file_is_still_reported_through_the_link(self) -> None:
        manifest = json.loads(self.paths.manifest_path.read_text(encoding="utf-8"))
        relative = sorted(manifest["support_files"])[0]
        (self.omh_home / "skills" / relative).write_text("edited by hand\n", encoding="utf-8")
        check = {check.name: check for check in run_doctor(self.paths)}["local_modifications"]
        self.assertFalse(check.ok)
        self.assertIn(relative, check.message)

    def test_the_command_prints_its_report_instead_of_aborting(self) -> None:
        with mock.patch.object(system_paths, "managed_workflow_pack_dir", return_value=self.alias):
            status, stdout, stderr = run_cli(
                ["--omh-home", str(self.omh_home), "--hermes-home", str(self.hermes), "doctor", "--json"],
                output_json=False,
            )
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(status, 0 if payload["ok"] else 1)
        names = {check["name"] for check in payload["checks"]}
        self.assertIn("local_modifications", names)
        self.assertNotIn("skills_dir_link", names)

    def test_a_link_the_installer_refuses_is_a_finding_not_an_abort(self) -> None:
        foreign = self.root / "foreign"
        foreign.mkdir()
        self.alias.unlink()
        self.alias.symlink_to(foreign, target_is_directory=True)
        checks = {check.name: check for check in run_doctor(self.paths)}
        link = checks["skills_dir_link"]
        self.assertFalse(link.ok)
        self.assertEqual(link.severity, "blocking")
        self.assertIn(str(self.alias), link.message)
        self.assertIn("manifest", checks)
        self.assertFalse(doctor_ok(list(checks.values())))

    def test_any_other_skills_link_is_reported_by_the_checks_that_read_through_it(self) -> None:
        other = self.root / "other" / "skills"
        other.parent.mkdir()
        other.symlink_to(self.omh_home / "skills", target_is_directory=True)
        paths = OmhPaths(self.omh_home, self.hermes, managed_skills_dir=other)
        checks = {check.name: check for check in run_doctor(paths)}
        self.assertFalse(checks["local_modifications"].ok)
        self.assertIn("symlink", checks["local_modifications"].message)
        self.assertFalse(checks["guidance_projection"].ok)
        self.assertNotIn("skills_dir_link", checks)


@_LINKS
class StatusProbeKeepsTheResolvedPackTests(unittest.TestCase):
    def test_the_chat_status_probe_reads_the_pack_this_command_resolved(self) -> None:
        from omh.wrapper import contract

        with TemporaryDirectory() as tmp:
            home = _ManagedHome(Path(tmp).resolve())
            home.register(home.pointer)
            contract._omh_status_probe_cached.cache_clear()
            probe = contract._omh_status_probe(home.paths)
            gaps = {item["capability"] for item in probe["capability_gap_roadmap"]["product_gaps"]}
            self.assertNotIn("managed_skills", gaps)
            self.assertNotIn("external_skill_dirs", gaps)


if __name__ == "__main__":
    unittest.main()
