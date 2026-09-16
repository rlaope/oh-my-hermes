"""#817: the Hermes-visible guidance projection reports one honest status.

The four axes this file pins apart -- projection freshness, local drift,
registration, and observed host use -- were previously answerable only by
reading five doctor checks and inferring which one mattered.
"""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.install.guidance_projection import (
    DRIFT_STATES,
    GUIDANCE_PROJECTION_STATUS_KEYS,
    GUIDANCE_PROJECTION_STATUS_SCHEMA_VERSION,
    HOST_OBSERVATION_STATES,
    PROJECTION_STATES,
    REGISTRATION_STATES,
    build_guidance_projection_status,
    catalog_revision,
    projected_skill_paths,
    validate_guidance_projection_status,
)
from omh.commands import setup as setup_commands
from omh.install.installer import DEFAULT_SKILL_PROFILE, SKILL_PROFILES, install_skill_pack
from omh.local_store import atomic_write_text
from omh.maintenance.doctor import run_doctor
from omh.manifest import SkillRecord, new_manifest, skill_records
from omh.paths import resolve_paths
from omh.skill_pack import builtin_skill_templates
from omh.skills.catalog import omh_skill_install_path


def _install_projection(skills_dir: Path) -> dict[str, object]:
    """Render the projection the way the installer does, then manifest it.

    `atomic_write_text`, not `Path.write_text`: the installer writes through it
    for its `newline=""`, which keeps `\\n` on disk as `\\n`. Writing in default
    text mode translates to CRLF on Windows, and the catalog comparison hashes
    template content that still has LF -- so the same install reads as `fresh`
    on Linux and `stale` on Windows.
    """
    for template in builtin_skill_templates():
        path = skills_dir / omh_skill_install_path(template.name) / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, template.content)
    return new_manifest("builtin", skills_dir, skill_records(skills_dir, "builtin"))


class CatalogRevisionTests(unittest.TestCase):
    def test_the_revision_is_a_stable_digest_of_the_packaged_catalog(self) -> None:
        first = catalog_revision()
        self.assertEqual(first, catalog_revision())
        self.assertEqual(len(first), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in first))

    def test_the_revision_covers_every_projected_skill(self) -> None:
        # If a skill were absent from the digest, renaming or rewriting it
        # would leave a stale projection reporting `fresh`.
        self.assertEqual(len(projected_skill_paths()), len(builtin_skill_templates()))
        self.assertEqual(len(set(projected_skill_paths())), len(projected_skill_paths()))

    def test_a_manifest_records_the_revision_it_was_rendered_from(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            self.assertEqual(manifest["catalog_revision"], catalog_revision())


class ProjectionStatusTests(unittest.TestCase):
    """AC1: a fresh projection matches the catalog revision and the checksums."""

    def test_a_freshly_installed_projection_is_fresh_and_clean(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)

            status = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=False
            )

            self.assertEqual(validate_guidance_projection_status(status), [])
            self.assertEqual(status["projection"], "fresh")
            self.assertEqual(status["drift"], "clean")
            self.assertEqual(status["locally_modified"], [])
            self.assertEqual(status["catalog_revision"], status["installed_revision"])

    def test_a_projection_rendered_from_an_older_catalog_is_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            # What an older release's manifest looks like from here: it names a
            # catalog revision this package does not carry.
            aged = {**manifest, "catalog_revision": "0" * 64}

            status = build_guidance_projection_status(
                skills_dir, aged, registered=True, host_observed=False
            )

            self.assertEqual(status["projection"], "stale")
            self.assertIn("omh update", str(status["next_action"]))

    def test_a_manifest_written_before_revisions_falls_back_to_checksums(self) -> None:
        # AC1 has to hold for stores that predate the revision field, and the
        # only comparison available there is per-file content.
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            legacy = {key: value for key, value in manifest.items() if key != "catalog_revision"}

            self.assertEqual(
                build_guidance_projection_status(
                    skills_dir, legacy, registered=True, host_observed=False
                )["projection"],
                "fresh",
            )

            first = skills_dir / projected_skill_paths()[0]
            first.write_text("content an older release rendered\n", encoding="utf-8")

            self.assertEqual(
                build_guidance_projection_status(
                    skills_dir, legacy, registered=True, host_observed=False
                )["projection"],
                "stale",
            )

    def test_a_missing_projection_is_missing_rather_than_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            (skills_dir / projected_skill_paths()[0]).unlink()

            status = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=False
            )

            self.assertEqual(status["projection"], "missing")

    def test_a_local_source_install_is_not_comparable_to_the_packaged_catalog(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = {**_install_projection(skills_dir), "source": "/some/local/checkout"}

            status = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=False
            )

            # Not "stale": no `omh update` resolves a difference from a catalog
            # the projection was never rendered from.
            self.assertEqual(status["projection"], "not_comparable")


class GuidanceProjectionProfileTests(unittest.TestCase):
    """#1635: the reason completeness follows the manifest, computed not asserted.

    `_projection_state` measures completeness against the manifest rather than
    the catalog, and the comment beside it used to justify that by asserting
    `omh setup` installs a core subset by default. That stopped being true once
    the default became `full`, and a load-bearing reason a reader can falsify in
    one command is worse than no reason at all. These two cases compute both
    halves: what the default actually is, and that a core install -- the state
    the rule exists for, default or not -- reads `fresh` while holding a
    fraction of the catalog.
    """

    def test_the_default_profile_is_read_from_the_installer_not_from_prose(self) -> None:
        args = argparse.Namespace(full=False, core=False)
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            resolved = setup_commands._resolved_skill_profile(args, paths)

        # Whatever the default is, it is the installer's value; nothing here
        # restates it, so a change to it cannot leave a second copy behind.
        self.assertEqual(resolved, DEFAULT_SKILL_PROFILE)
        self.assertIn(resolved, SKILL_PROFILES)

    def test_a_core_profile_install_reads_fresh_while_holding_a_subset(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            manifest = install_skill_pack(paths, profile="core")

            # The premise of the rule: a correct install that is not the whole
            # catalog. Computed, so a catalog or profile change cannot leave
            # this passing for the wrong reason.
            self.assertEqual(manifest["skill_profile"], "core")
            self.assertLess(len(manifest["skills"]), len(builtin_skill_templates()))

            status = build_guidance_projection_status(
                paths.skills_dir, manifest, registered=True, host_observed=False
            )
            self.assertEqual(status["projection"], "fresh")


class LocalModificationTests(unittest.TestCase):
    """AC2: modified files are detected and never imported into canonical data."""

    def test_an_edited_projected_file_is_reported_as_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            edited = projected_skill_paths()[0]
            (skills_dir / edited).write_text("hand edit\n", encoding="utf-8")

            status = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=False
            )

            self.assertEqual(status["drift"], "locally_modified")
            self.assertEqual(status["locally_modified"], [edited])
            self.assertIn("--force", str(status["next_action"]))

    def test_an_edited_file_never_becomes_the_catalog_revision(self) -> None:
        # The one-way boundary. Editing a projected file must not change what
        # the package says it would render, or a hand edit would silently
        # become canonical on the next install.
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            _install_projection(skills_dir)
            before = catalog_revision()

            (skills_dir / projected_skill_paths()[0]).write_text("hand edit\n", encoding="utf-8")

            self.assertEqual(catalog_revision(), before)
            # And a reinstall from the same tree restores the rendered content.
            reinstalled = _install_projection(skills_dir)
            self.assertEqual(reinstalled["catalog_revision"], before)
            self.assertEqual(
                build_guidance_projection_status(
                    skills_dir, reinstalled, registered=True, host_observed=False
                )["locally_modified"],
                [],
            )

    def test_drift_is_reported_separately_from_freshness(self) -> None:
        # A file the operator edited and a file an older release left behind
        # both differ from the catalog, and they need different repairs. One
        # axis could not say which.
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            (skills_dir / projected_skill_paths()[0]).write_text("hand edit\n", encoding="utf-8")

            status = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=False
            )

            self.assertEqual(status["projection"], "fresh")
            self.assertEqual(status["drift"], "locally_modified")


class RegistrationAndObservationTests(unittest.TestCase):
    """AC3: status is explained without file export or config edits."""

    def test_registration_and_observed_use_are_separate_axes(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)

            registered = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=False
            )
            # Registered is where Hermes would look, not proof that it did.
            self.assertEqual(registered["registration"], "registered")
            self.assertEqual(registered["host_observation"], "not_observed")

            observed = build_guidance_projection_status(
                skills_dir, manifest, registered=True, host_observed=True
            )
            self.assertEqual(observed["host_observation"], "observed")

    def test_an_unreadable_config_is_unknown_and_not_unregistered(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)

            status = build_guidance_projection_status(
                skills_dir, manifest, registered=None, host_observed=False
            )

            self.assertEqual(status["registration"], "unknown")
            self.assertIn("--hermes-home", str(status["next_action"]))

    def test_the_claim_boundary_denies_runtime_use(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)

            boundary = str(
                build_guidance_projection_status(
                    skills_dir, manifest, registered=True, host_observed=False
                )["claim_boundary"]
            )

            self.assertIn("not evidence that Hermes loaded", boundary)
            self.assertIn("Registration is where Hermes would look", boundary)

    def test_an_absent_manifest_is_missing_with_unknown_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"

            status = build_guidance_projection_status(
                skills_dir, None, registered=False, host_observed=False
            )

            self.assertEqual(validate_guidance_projection_status(status), [])
            self.assertEqual(status["projection"], "missing")
            self.assertEqual(status["drift"], "unknown")
            self.assertEqual(status["registration"], "not_registered")


class ValidatorTests(unittest.TestCase):
    def test_the_key_set_is_closed_in_both_directions(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            status = build_guidance_projection_status(
                skills_dir, _install_projection(skills_dir), registered=True, host_observed=False
            )
            self.assertEqual(tuple(sorted(status)), GUIDANCE_PROJECTION_STATUS_KEYS)
            self.assertEqual(status["schema_version"], GUIDANCE_PROJECTION_STATUS_SCHEMA_VERSION)

            extra = {**status, "surprise": 1}
            self.assertTrue(any("unsupported keys" in error for error in validate_guidance_projection_status(extra)))

            short = {key: value for key, value in status.items() if key != "drift"}
            self.assertTrue(any("missing keys" in error for error in validate_guidance_projection_status(short)))

    def test_every_vocabulary_is_refused_outside_its_own_values(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            status = build_guidance_projection_status(
                skills_dir, _install_projection(skills_dir), registered=True, host_observed=False
            )
            for key, vocabulary in (
                ("projection", PROJECTION_STATES),
                ("drift", DRIFT_STATES),
                ("registration", REGISTRATION_STATES),
                ("host_observation", HOST_OBSERVATION_STATES),
            ):
                with self.subTest(key=key):
                    self.assertIn(status[key], vocabulary)
                    broken = {**status, key: "made_up"}
                    self.assertTrue(
                        any(key in error for error in validate_guidance_projection_status(broken))
                    )

    def test_listed_modifications_cannot_be_reported_as_clean_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            status = build_guidance_projection_status(
                skills_dir, _install_projection(skills_dir), registered=True, host_observed=False
            )
            lying = {**status, "locally_modified": ["a/SKILL.md"], "drift": "clean"}
            self.assertTrue(
                any("drift must be locally_modified" in error for error in validate_guidance_projection_status(lying))
            )

    def test_a_non_object_payload_is_refused(self) -> None:
        self.assertEqual(
            validate_guidance_projection_status("not a status"),
            ["guidance_projection_status must be an object"],
        )


class ManifestRecordTests(unittest.TestCase):
    def test_skill_records_still_carry_canonical_names(self) -> None:
        # The revision field is additive; it must not disturb what the manifest
        # already recorded, which other callers compare against the catalog.
        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            manifest = _install_projection(skills_dir)
            names = {str(record["name"]) for record in manifest["skills"]}
            self.assertTrue(names)
            self.assertTrue(names.issubset({template.name for template in builtin_skill_templates()}))
            self.assertTrue(all(isinstance(SkillRecord(**record), SkillRecord) for record in manifest["skills"]))


class DoctorSurfaceTests(unittest.TestCase):
    """AC3, at the surface a user actually reaches: `omh doctor`."""

    def test_doctor_reports_the_projection_as_one_grouped_check(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            checks = run_doctor(paths)

            by_name = {check.name: check for check in checks}
            self.assertIn("guidance_projection", by_name)
            message = by_name["guidance_projection"].message
            for axis in ("projection=", "drift=", "registration=", "host_observation=", "catalog_revision="):
                self.assertIn(axis, message)

            # The check has to land in a named group, or an operator reading
            # the grouped summary never sees it.
            summary = setup_commands._doctor_operator_summary(checks)
            managed = next(group for group in summary["groups"] if group["name"] == "managed_skills")
            self.assertIn("guidance_projection", managed["failed"])

    def test_a_failing_projection_names_the_repair(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            check = next(item for item in run_doctor(paths) if item.name == "guidance_projection")
            # Nothing is installed in a bare home, so the projection is missing
            # and the check has to say what fixes it rather than only that it
            # is broken.
            self.assertFalse(check.ok)
            self.assertIn("omh update", check.next_action)


if __name__ == "__main__":
    unittest.main()
