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
from omh.install.guidance_projection import catalog_revision
from omh.installer import (
    install_skill_pack,
    installed_skill_names,
    reconcile_skill_profile,
    skill_directory_name,
    skill_install_relative_dir,
    skill_profile_report,
)
from omh.maintenance.doctor import run_doctor
from omh.manifest import new_manifest, read_manifest, skill_records, write_manifest
from omh.paths import resolve_paths
from omh.skill_pack import (
    CORE_PROFILE_SKILLS,
    CORE_SKILLS,
    builtin_skill_templates,
    installable_skill_names,
)
from omh.version import __version__


def _installed_names(paths) -> set[str]:
    """Canonical names of the skills on disk, under either install layout."""
    return set(installed_skill_names(paths.skills_dir))


class InstallerSkillProfileTests(unittest.TestCase):
    def test_installing_over_a_flat_pack_removes_the_old_directories(self) -> None:
        """A layout move must not leave both layouts installed.

        Skills moved from `skills/<canonical>/` to `skills/<label>/`, and then to
        `skills/<category>/<label>/` so Hermes can read a dashboard category off
        the path. Installs are non-destructive, so each move wrote the new
        directories and left the old ones beside them: an observed machine went
        from 92 skills to 184 after the relabel, doubling the pack's per-turn
        context weight, and the manifest then reported every vanished old path as
        a local modification. A leftover flat copy after the category move also
        keeps a "general" group in the Hermes banner, which is what the
        categorized layout exists to remove.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            categorized = _installed_names(paths)

            # Recreate the pre-category layout: every skill also present flat
            # under its label, recorded in the manifest.
            flat_names = sorted(installable_skill_names())
            for name in flat_names:
                legacy = paths.skills_dir / skill_directory_name(name)
                legacy.mkdir(parents=True, exist_ok=True)
                (legacy / "SKILL.md").write_text(
                    (paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            manifest = new_manifest("builtin", paths.skills_dir, skill_records(paths.skills_dir, "builtin"))
            write_manifest(paths.manifest_path, manifest)
            self.assertEqual(
                len(list(paths.skills_dir.glob("*/SKILL.md"))),
                len(flat_names),
                "fixture did not recreate the flat layout",
            )

            result = install_skill_pack(paths, profile="full", force=True)

            self.assertEqual(_installed_names(paths), categorized)
            self.assertEqual(list(paths.skills_dir.glob("*/SKILL.md")), [])
            self.assertEqual(sorted(result["flat_layout_skills_removed"]), flat_names)
            self.assertEqual(result["flat_layout_skills_retained"], [])

    def test_the_ultrawork_category_survives_pruning_its_own_flat_namesake(self) -> None:
        """`ultrawork` is both a pre-relabel skill directory and a category name.

        The pre-relabel install put the ULW engine at `skills/ultrawork/SKILL.md`;
        the ULW family now installs under the `ultrawork/` CATEGORY. Removing the
        stale flat copy as a tree would delete the eight skills just written into
        the category beside it.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            category = paths.skills_dir / skill_install_relative_dir("ultrawork").parts[0]
            members = sorted(child.name for child in category.iterdir())
            self.assertIn(skill_directory_name("ultrawork"), members)

            (category / "SKILL.md").write_text(
                "---\nname: ultrawork\n---\nstale pre-relabel render\n", encoding="utf-8"
            )
            write_manifest(
                paths.manifest_path,
                new_manifest("builtin", paths.skills_dir, skill_records(paths.skills_dir, "builtin")),
            )

            result = install_skill_pack(paths, profile="full", force=True)

            self.assertFalse((category / "SKILL.md").exists(), "stale flat copy survived")
            self.assertEqual(sorted(child.name for child in category.iterdir()), members)
            self.assertIn("ultrawork", result["flat_layout_skills_removed"])

    def test_a_core_refresh_migrates_a_pre_relabel_only_directory(self) -> None:
        """The refresh gate must accept the pre-relabel directory name.

        A pre-relabel install has only `skills/<canonical>/` on disk. Matching the
        refresh gate on the labelled name alone dropped such a skill from refresh
        entirely: the replacement was never written, the pruner then kept the old
        directory ("no replacement yet"), and the host kept serving the stale
        pre-label SKILL.md forever - the observed `Reading skill ultragoal` long
        after the catalog moved to `ulw-goal`.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="core")
            victim = next(
                name
                for name in sorted(installable_skill_names())
                if skill_directory_name(name) != name and name not in CORE_PROFILE_SKILLS
            )
            legacy = paths.skills_dir / victim
            legacy.mkdir(parents=True, exist_ok=True)
            (legacy / "SKILL.md").write_text(f"---\nname: {victim}\n---\nstale pre-relabel render\n", encoding="utf-8")
            write_manifest(
                paths.manifest_path,
                new_manifest("builtin", paths.skills_dir, skill_records(paths.skills_dir, "builtin")),
            )

            result = install_skill_pack(paths, profile="core", force=True)

            categorized = paths.skills_dir / skill_install_relative_dir(victim)
            self.assertTrue((categorized / "SKILL.md").is_file(), "categorized replacement was not written")
            self.assertFalse(legacy.exists(), "pre-relabel directory survived the refresh")
            self.assertIn(victim, result["flat_layout_skills_removed"])
            self.assertIn(
                f'name: "{skill_directory_name(victim)}"',
                (categorized / "SKILL.md").read_text(encoding="utf-8"),
            )

    def test_a_locally_edited_flat_directory_blocks_the_install(self) -> None:
        """The migration never gets to delete an edit; the existing guard stops first.

        `install_skill_pack` refuses outright when a managed file differs from the
        manifest, so an edited flat directory makes the install ask the user to
        resolve it rather than being quietly cleaned up. `--force` is the explicit
        way through, and it does remove the directory.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            victim = next(
                name for name in sorted(installable_skill_names()) if skill_directory_name(name) != name
            )
            legacy = paths.skills_dir / victim
            legacy.mkdir(parents=True, exist_ok=True)
            (legacy / "SKILL.md").write_text("recorded content\n", encoding="utf-8")
            write_manifest(
                paths.manifest_path,
                new_manifest("builtin", paths.skills_dir, skill_records(paths.skills_dir, "builtin")),
            )
            (legacy / "SKILL.md").write_text("edited after the manifest\n", encoding="utf-8")

            with self.assertRaises(OmhError) as refused:
                install_skill_pack(paths, profile="full")
            self.assertIn(f"{victim}/SKILL.md", str(refused.exception))
            self.assertTrue((legacy / "SKILL.md").is_file())

            result = install_skill_pack(paths, profile="full", force=True)

            self.assertFalse(legacy.exists())
            self.assertIn(victim, result["flat_layout_skills_removed"])

    def test_a_core_refresh_updates_full_only_skills_already_on_disk(self) -> None:
        """`omh update` must leave nothing stale, whatever profile is recorded.

        A core-profile refresh used to write only the core skills, so a machine
        that had once installed `--full` kept 73 skills frozen at whatever render
        they were installed with. That is how an install kept serving
        `name: ultrawork` long after the catalog had moved to `ulw-ultrawork`,
        while `omh update` still reported success.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            full_only = sorted(set(name for name in _installed_names(paths)) - set(CORE_PROFILE_SKILLS))
            self.assertTrue(full_only, "fixture needs at least one full-only skill")

            victim = paths.skills_dir / skill_install_relative_dir(full_only[0]) / "SKILL.md"
            fresh = victim.read_text(encoding="utf-8")
            victim.write_text("---\nname: stale-on-purpose\n" + fresh.split("---\n", 2)[2], encoding="utf-8")

            before = _installed_names(paths)

            install_skill_pack(paths, profile="core", force=True)

            self.assertEqual(victim.read_text(encoding="utf-8"), fresh)
            # Refreshing must not shed skills either; that stays an explicit
            # `omh skill-profile reconcile --to core`.
            self.assertEqual(_installed_names(paths), before)

    def test_core_profile_is_a_strict_subset_of_full_and_covers_doctor_core_skills(self) -> None:
        full_names = {template.name for template in builtin_skill_templates()}

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            # profile passed explicitly: the API default is now "full", and this
            # test exercises the core profile mechanics, not the default.
            result = install_skill_pack(paths, dry_run=True, profile="core")

        self.assertEqual(result["skill_profile"], "core")
        installed_names = set(result["skills"])
        self.assertLess(len(installed_names), len(full_names))
        self.assertTrue(installed_names.issubset(full_names))
        self.assertTrue(set(CORE_SKILLS).issubset(installed_names))
        self.assertEqual(installed_names, set(CORE_PROFILE_SKILLS))
        self.assertIn("buzz", installed_names)
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

            core_manifest = install_skill_pack(paths, profile="core")
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

    def test_installer_full_to_core_reinstall_stays_non_destructive_and_reports_the_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            full_names = {template.name for template in builtin_skill_templates()}
            install_skill_pack(paths, profile="full")

            full_only_names = full_names - set(CORE_PROFILE_SKILLS)
            self.assertTrue(full_only_names)
            for name in full_only_names:
                self.assertTrue((paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").exists(), name)

            result = install_skill_pack(paths, profile="core", force=True)

            # An ordinary reinstall must never delete skills: the catalog-basis prune
            # still keeps every sha-unmodified full-only skill on a full->core reinstall.
            self.assertEqual(result["pruned_skills"], [])
            for name in full_only_names:
                self.assertTrue((paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").exists(), name)

            # ...but the recorded profile must no longer imply the core footprint.
            state = result["skill_profile_state"]
            self.assertEqual(state["requested_profile"], "core")
            self.assertEqual(state["effective_profile"], "full")
            self.assertFalse(state["matches_requested_profile"])
            self.assertTrue(state["retained_exception"])
            self.assertEqual(set(state["full_only_installed_skills"]), full_only_names)
            self.assertEqual(state["next_action"], "omh skill-profile reconcile --to core")
            self.assertIn("context weight", state["context_cost_note"])
            self.assertIn("never delete installed skills", state["non_destructive_default"])


class SkillFreshnessCheckTests(unittest.TestCase):
    """`skill_freshness` must catch installs an older OMH release wrote.

    `local_modifications` compares installed files against the manifest
    recorded at install time, so an operator who upgrades the omh package but
    never reruns `omh update` keeps serving Hermes skill guidance from the old
    release with a fully green doctor. An observed session ran a cached
    old-version loop skill for a whole task because nothing surfaced the gap.
    """

    def _check(self, paths, name: str):
        return next((check for check in run_doctor(paths) if check.name == name), None)

    def _age_one_skill(self, paths, *, version: str | None = None) -> str:
        """Rewrite one installed skill as an older release would have left it.

        The file content and the manifest sha agree (so it is not a local
        modification), but both differ from what the current package renders.
        `version` rewrites the manifest's recorded package version; leaving it
        `None` keeps whatever the install recorded, which is the case where the
        content moved and the version did not. Returns the canonical skill name.
        """
        manifest = read_manifest(paths.manifest_path)
        record = manifest["skills"][0]
        path = paths.skills_dir / record["path"]
        path.write_text("# Old release content\n", encoding="utf-8")
        record["sha256"] = sha256_file(path)
        if version is not None:
            manifest["version"] = version
        write_manifest(paths.manifest_path, manifest)
        return record["name"]

    def test_fresh_install_passes_skill_freshness(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)
            check = self._check(paths, "skill_freshness")
            self.assertIsNotNone(check)
            self.assertTrue(check.ok, check)

    def test_outdated_install_fails_skill_freshness_and_points_at_update(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)
            aged = self._age_one_skill(paths, version="0.0.1")

            freshness = self._check(paths, "skill_freshness")
            self.assertIsNotNone(freshness)
            self.assertFalse(freshness.ok)
            self.assertIn(aged, freshness.message)
            self.assertIn("omh update", freshness.next_action)

            # Negative control for the equal-version case below: a genuinely
            # differing package version changes nothing about how the finding
            # reads, because the finding was never derived from the version.
            self._assert_carries_no_version_pair(freshness.message)

            # Ownership boundary: the aged file matches its manifest record,
            # so it is stale, not a local modification.
            local = self._check(paths, "local_modifications")
            self.assertTrue(local.ok, local)

    def _assert_carries_no_version_pair(self, message: str) -> None:
        """No package version anywhere in a finding derived from content hashes."""
        self.assertNotIn("but this omh is", message)
        self.assertNotIn(__version__, message)

    def test_content_that_moved_without_a_version_bump_still_reads(self) -> None:
        """#1635: the equal-version case, which is the normal preview-channel one.

        The check is a content comparison, and reporting it as a package
        version pair produced `installed by omh 2.0.3, but this omh is 2.0.3`
        -- a sentence that contradicts itself while asserting a real problem,
        leaving the reader nothing to act on. Same version on both sides,
        content differing, and the message must still say what differs.

        The manifest here also still records the current catalog revision, so
        this doubles as the guard against reprinting the version pair's shape
        in revision clothing: one digest quoted against itself reads exactly as
        badly. The digest is counted, not matched.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)
            aged = self._age_one_skill(paths)
            manifest = read_manifest(paths.manifest_path)

            # The premise, computed: neither the version nor the recorded
            # revision moved, so either printed as a pair would be two
            # identical strings.
            self.assertEqual(manifest["version"], __version__)
            self.assertEqual(manifest["catalog_revision"], catalog_revision())

            freshness = self._check(paths, "skill_freshness")
            self.assertFalse(freshness.ok)
            self.assertIn(aged, freshness.message)
            self._assert_carries_no_version_pair(freshness.message)
            self.assertIn("omh update", freshness.next_action)

            current = catalog_revision()[:12]
            self.assertEqual(
                freshness.message.count(current),
                1,
                f"one revision quoted against itself: {freshness.message}",
            )
            self.assertIn("do not match it", freshness.message)

    def test_an_install_from_an_older_catalog_names_both_revisions(self) -> None:
        """The other half: two real revisions, and both are named.

        Without this case the message could name no revision at all and the
        equal-revision guard above would still pass.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)
            aged = self._age_one_skill(paths)
            manifest = read_manifest(paths.manifest_path)
            # What an older release's manifest looks like from here: it names a
            # catalog generation this package does not carry.
            manifest["catalog_revision"] = "0" * 64
            write_manifest(paths.manifest_path, manifest)

            freshness = self._check(paths, "skill_freshness")
            self.assertFalse(freshness.ok)
            self.assertIn(aged, freshness.message)
            self.assertIn("installed_revision=" + "0" * 12, freshness.message)
            self.assertIn(f"catalog_revision={catalog_revision()[:12]}", freshness.message)
            self._assert_carries_no_version_pair(freshness.message)

    def test_a_current_install_reports_the_revision_it_matches(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)

            check = self._check(paths, "skill_freshness")
            self.assertTrue(check.ok, check)
            # The passing message states the same identifier as the failing one
            # and as `guidance_projection`, so one condition is not described
            # in two vocabularies.
            self.assertIn(f"catalog_revision={catalog_revision()[:12]}", check.message)

    def test_locally_edited_skill_is_not_reported_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)
            manifest = read_manifest(paths.manifest_path)
            path = paths.skills_dir / manifest["skills"][0]["path"]
            path.write_text("# Local operator edit\n", encoding="utf-8")

            self.assertTrue(self._check(paths, "skill_freshness").ok)
            self.assertFalse(self._check(paths, "local_modifications").ok)

    def test_local_source_install_is_not_compared(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths)
            manifest = read_manifest(paths.manifest_path)
            manifest["source"] = str(Path(tmp) / "custom-skills")
            write_manifest(paths.manifest_path, manifest)

            check = self._check(paths, "skill_freshness")
            self.assertTrue(check.ok)
            self.assertIn("not comparable", check.message)


class SkillProfileReconcileTests(unittest.TestCase):
    def _full_only_names(self) -> set[str]:
        return {template.name for template in builtin_skill_templates()} - set(CORE_PROFILE_SKILLS)

    def test_fresh_core_install_records_a_matching_core_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            manifest = install_skill_pack(paths, profile="core")

            state = manifest["skill_profile_state"]
            self.assertEqual(state["schema_version"], "omh_skill_profile_state/v1")
            self.assertEqual(state["requested_profile"], "core")
            self.assertEqual(state["effective_profile"], "core")
            self.assertTrue(state["matches_requested_profile"])
            self.assertFalse(state["retained_exception"])
            self.assertEqual(state["full_only_installed_skills"], [])
            self.assertEqual(state["installed_catalog_skill_count"], len(CORE_PROFILE_SKILLS))
            self.assertEqual(state["unmanaged_skill_count"], 0)
            self.assertEqual(state["next_action"], "")

            report = skill_profile_report(paths)
            self.assertTrue(report["installed"])
            self.assertEqual(report["reconcilable_skills"], [])
            self.assertEqual(report["retained_skills"], [])

    def test_fresh_full_install_records_a_matching_full_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            manifest = install_skill_pack(paths, profile="full")

            state = manifest["skill_profile_state"]
            self.assertEqual(state["requested_profile"], "full")
            self.assertEqual(state["effective_profile"], "full")
            self.assertTrue(state["matches_requested_profile"])
            self.assertFalse(state["retained_exception"])
            self.assertEqual(state["installed_catalog_skill_count"], len(builtin_skill_templates()))

            # Inspecting a full install is read-only and never removes anything.
            report = skill_profile_report(paths)
            self.assertEqual(set(report["reconcilable_skills"]), self._full_only_names())
            for name in self._full_only_names():
                self.assertTrue((paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").exists(), name)

    def test_reconcile_full_to_core_removes_only_unmodified_managed_full_only_skills(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            full_only_names = self._full_only_names()

            result = reconcile_skill_profile(paths)

            self.assertEqual(result["schema_version"], "omh_skill_profile_reconcile/v1")
            self.assertFalse(result["dry_run"])
            self.assertEqual(set(result["removed_skills"]), full_only_names)
            self.assertEqual(result["retained_skills"], [])
            self.assertEqual(result["profile_state_before"]["effective_profile"], "full")
            self.assertEqual(result["profile_state_after"]["effective_profile"], "core")
            self.assertTrue(result["profile_state_after"]["matches_requested_profile"])

            for name in full_only_names:
                self.assertFalse((paths.skills_dir / skill_install_relative_dir(name)).exists(), name)
            for name in CORE_PROFILE_SKILLS:
                self.assertTrue((paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").exists(), name)

            on_disk = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["skill_profile"], "core")
            self.assertEqual(set(on_disk["reconciled_skills"]), full_only_names)
            self.assertEqual(on_disk["skill_profile_state"]["effective_profile"], "core")
            self.assertEqual(
                {str(record["name"]) for record in on_disk["skills"]},
                set(CORE_PROFILE_SKILLS),
            )

            checks = run_doctor(paths)
            skill_checks = [check for check in checks if check.name.startswith("skill:")]
            self.assertTrue(all(check.ok for check in skill_checks), skill_checks)

    def test_reconcile_dry_run_reports_the_plan_without_deleting_anything(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            full_only_names = self._full_only_names()
            before = paths.manifest_path.read_text(encoding="utf-8")

            result = reconcile_skill_profile(paths, dry_run=True)

            self.assertTrue(result["dry_run"])
            self.assertEqual(set(result["would_remove_skills"]), full_only_names)
            self.assertEqual(result["removed_skills"], [])
            self.assertNotIn("profile_state_after", result)
            self.assertEqual(result["profile_state_before"]["effective_profile"], "full")
            for name in full_only_names:
                self.assertTrue((paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").exists(), name)
            self.assertEqual(paths.manifest_path.read_text(encoding="utf-8"), before)

    def test_reconcile_retains_modified_and_unmanaged_skill_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            modified_name = sorted(self._full_only_names())[0]
            modified_file = paths.skills_dir / skill_install_relative_dir(modified_name) / "SKILL.md"
            modified_file.write_text(
                modified_file.read_text(encoding="utf-8") + "\nlocal operator note\n",
                encoding="utf-8",
            )
            unmanaged_dir = paths.skills_dir / "team-local-skill"
            unmanaged_dir.mkdir(parents=True, exist_ok=True)
            (unmanaged_dir / "SKILL.md").write_text("# team local skill\n", encoding="utf-8")

            result = reconcile_skill_profile(paths)

            self.assertNotIn(modified_name, result["removed_skills"])
            self.assertNotIn("team-local-skill", result["removed_skills"])
            reasons = {str(item["name"]): str(item["reason"]) for item in result["retained_skills"]}
            self.assertEqual(reasons[modified_name], "locally modified vs. the rendered catalog templates")
            self.assertEqual(reasons["team-local-skill"], "not an OMH catalog skill")
            self.assertTrue(modified_file.exists())
            self.assertTrue((unmanaged_dir / "SKILL.md").exists())
            self.assertEqual(result["profile_state_after"]["effective_profile"], "mixed")
            self.assertTrue(result["profile_state_after"]["retained_exception"])

    def test_reconcile_retains_a_managed_skill_that_carries_an_extra_local_file(self) -> None:
        # The unmodified check compares the whole skill directory against the rendered
        # catalog templates, so an added local file protects the directory even when
        # SKILL.md itself is untouched and matches the install manifest sha.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            skill_name = sorted(self._full_only_names())[0]
            extra = paths.skills_dir / skill_install_relative_dir(skill_name) / "references" / "team-note.md"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text("# team note\n", encoding="utf-8")

            result = reconcile_skill_profile(paths, dry_run=True)

            self.assertNotIn(skill_name, result["would_remove_skills"])
            reasons = {str(item["name"]): str(item["reason"]) for item in result["retained_skills"]}
            self.assertEqual(reasons[skill_name], "locally modified vs. the rendered catalog templates")
            self.assertTrue(extra.exists())

    def test_reconcile_requires_an_existing_manifest_and_only_targets_core(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            with self.assertRaises(OmhError):
                reconcile_skill_profile(paths)

            install_skill_pack(paths, profile="full")
            with self.assertRaises(OmhError):
                reconcile_skill_profile(paths, target_profile="full")

    def test_reconcile_cli_supports_dry_run_then_apply(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            install_skill_pack(paths, profile="full")
            full_only_names = self._full_only_names()

            status, stdout, stderr = run_cli(base + ["skill-profile", "status", "--json"], output_json=False)
            self.assertEqual(status, 0, stderr)
            report = json.loads(stdout)
            self.assertEqual(report["profile_state"]["effective_profile"], "full")
            self.assertEqual(set(report["reconcilable_skills"]), full_only_names)
            prompt_cost = report["profile_state"]["prompt_cost"]
            self.assertEqual(prompt_cost["schema_version"], "omh_skill_prompt_cost_estimate/v1")
            self.assertEqual(prompt_cost["evidence_status"], "prepared_estimate_not_host_observed")
            self.assertGreater(prompt_cost["estimated_index_line_bytes"], 0)
            self.assertGreater(prompt_cost["full_only_fixed_index_bytes"], 0)
            self.assertGreater(
                prompt_cost["estimated_index_line_bytes"],
                prompt_cost["core_fixed_index_bytes"],
            )
            self.assertGreater(prompt_cost["installed_skill_body_bytes"], 0)
            self.assertIn("hermes prompt-size --json", prompt_cost["observation_command"])
            self.assertNotIn("visibility", prompt_cost)
            self.assertNotIn("progressive_skill_body_bytes", prompt_cost)

            status, stdout, stderr = run_cli(
                base + ["skill-profile", "reconcile", "--to", "core", "--dry-run", "--json"],
                output_json=False,
            )
            self.assertEqual(status, 0, stderr)
            preview = json.loads(stdout)
            self.assertTrue(preview["dry_run"])
            self.assertEqual(set(preview["would_remove_skills"]), full_only_names)
            for name in full_only_names:
                self.assertTrue((paths.skills_dir / skill_install_relative_dir(name) / "SKILL.md").exists(), name)

            status, stdout, stderr = run_cli(
                base + ["skill-profile", "reconcile", "--to", "core", "--json"],
                output_json=False,
            )
            self.assertEqual(status, 0, stderr)
            applied = json.loads(stdout)
            self.assertEqual(set(applied["removed_skills"]), full_only_names)
            self.assertEqual(applied["profile_state_after"]["effective_profile"], "core")
            for name in full_only_names:
                self.assertFalse((paths.skills_dir / skill_install_relative_dir(name)).exists(), name)

            # The reconcile command also refreshes the runtime state manifest hash, so
            # doctor's manifest/skill checks stay healthy after the removal.
            checks = run_doctor(paths)
            tracked = [check for check in checks if check.name.startswith("skill:") or check.name == "runtime_state"]
            self.assertTrue(tracked)
            self.assertTrue(all(check.ok for check in tracked), [check for check in tracked if not check.ok])

    def test_skill_profile_status_reports_not_installed_without_a_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            report = skill_profile_report(paths)

            self.assertFalse(report["installed"])
            self.assertEqual(report["profile_state"]["effective_profile"], "none")
            self.assertEqual(report["profile_state"]["requested_profile"], "")


if __name__ == "__main__":
    unittest.main()
