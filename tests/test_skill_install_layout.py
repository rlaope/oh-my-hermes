"""Managed skills install under a Hermes dashboard category directory.

Hermes derives a skill's category from DIRECTORY STRUCTURE, not from
frontmatter. `tools/skills_tool.py::_get_category_from_path` takes the SKILL.md
path relative to each configured skills dir (including `skills.external_dirs`
entries) and returns `parts[0]` only when that relative path has three or more
parts. OMH installed flat -- `<skills_dir>/<label>/SKILL.md`, two parts -- so
every OMH skill resolved to no category and the startup banner filed the whole
pack under one line:

    general: omh-agent-ops-review, omh-buzz, omh-cancel, +7 more

These tests hold the layout that makes the banner say something: the category
directory exists, it is the one the catalog chose, and nothing is left at the
flat depth where it would register a second time.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.installer import (
    install_skill_pack,
    installed_skill_directories,
    uninstall_skill_pack,
    skill_directory_name,
    skill_install_relative_dir,
)
from omh.maintenance.doctor import run_doctor
from omh.paths import resolve_paths
from omh.skill_pack import builtin_skill_reference_templates, builtin_skill_templates, installable_skill_names
from omh.skills.catalog import (
    ULTRAWORK_HERMES_CATEGORY,
    ULW_ENGINE_SKILL_NAMES,
    hermes_skill_categories,
    hermes_skill_category,
    omh_skill_display_name,
    omh_skill_install_path,
)

# The banner prints one line per category, so the count is the contract: nine
# groups is a dashboard, forty-one (the catalog's fine-grained `category` field)
# is a wall of text. Update this deliberately when a role is added or retired.
EXPECTED_CATEGORIES = (
    "guide",
    "handoff-guide",
    "memory-keeper",
    "operator",
    "planner",
    "researcher",
    "reviewer",
    "tracker",
    "ultrawork",
)


class HermesSkillCategoryTests(unittest.TestCase):
    def test_the_category_set_is_small_and_named(self) -> None:
        self.assertEqual(hermes_skill_categories(), EXPECTED_CATEGORIES)

    def test_every_installable_skill_has_a_category(self) -> None:
        for name in installable_skill_names():
            self.assertIn(hermes_skill_category(name), EXPECTED_CATEGORIES, name)

    def test_categories_are_short_lowercase_path_segments(self) -> None:
        for category in hermes_skill_categories():
            self.assertEqual(category, category.lower(), category)
            self.assertNotIn("/", category)
            self.assertNotIn(" ", category)
            self.assertLessEqual(len(category), 16, category)

    def test_the_ulw_family_is_one_group_the_banner_can_name(self) -> None:
        """The user-visible ask: ULW content must be nameable in the dashboard."""
        ulw = {
            name
            for name in installable_skill_names()
            if hermes_skill_category(name) == ULTRAWORK_HERMES_CATEGORY
        }
        self.assertEqual(ulw, set(installable_skill_names()) & set(ULW_ENGINE_SKILL_NAMES))
        self.assertTrue(ulw)
        for name in ulw:
            self.assertTrue(omh_skill_display_name(name).startswith("ulw-"), name)

    def test_a_category_name_never_shadows_a_skill_label(self) -> None:
        """A category dir and a skill leaf dir must not want the same path.

        `ultrawork` is the documented exception: it was the pre-relabel CANONICAL
        directory of the ULW engine and is now the category, so a stale flat
        `skills/ultrawork/SKILL.md` can sit beside `skills/ultrawork/ulw-work/`.
        The installer prunes that case file-by-file rather than as a tree. Any
        NEW collision would have no such handling, so it fails here.
        """
        labels = {omh_skill_display_name(name) for name in installable_skill_names()}
        self.assertEqual(set(hermes_skill_categories()) & labels, set())
        canonical = set(installable_skill_names())
        self.assertEqual(
            set(hermes_skill_categories()) & canonical,
            {ULTRAWORK_HERMES_CATEGORY},
        )

    def test_the_install_path_is_the_category_and_the_label(self) -> None:
        for name in installable_skill_names():
            self.assertEqual(
                omh_skill_install_path(name),
                f"{hermes_skill_category(name)}/{omh_skill_display_name(name)}",
            )


class InstalledLayoutTests(unittest.TestCase):
    def test_a_full_install_nests_every_skill_under_its_category(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")

            for template in builtin_skill_templates():
                installed = paths.skills_dir / omh_skill_install_path(template.name) / "SKILL.md"
                self.assertTrue(installed.is_file(), template.name)
                relative = installed.relative_to(paths.skills_dir)
                # Three parts is exactly what Hermes requires before it reads a
                # category off the path; two is what produced "general".
                self.assertEqual(len(relative.parts), 3, relative)
                self.assertEqual(relative.parts[0], hermes_skill_category(template.name))

    def test_a_full_install_leaves_nothing_at_the_flat_depth(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")

            self.assertEqual(sorted(paths.skills_dir.glob("*/SKILL.md")), [])
            self.assertEqual(
                sorted(entry.name for entry in paths.skills_dir.iterdir() if entry.is_dir()),
                list(EXPECTED_CATEGORIES),
            )

    def test_skill_references_follow_their_skill_into_the_category(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")

            references = sorted(paths.skills_dir.glob("*/*/references/*.md"))
            self.assertTrue(references, "the catalog ships skill reference files")
            self.assertEqual(sorted(paths.skills_dir.glob("*/references/*.md")), [])

    def test_local_source_install_refreshes_and_removes_apple_references(self) -> None:
        expected = {
            template.relative_path: template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == "apple-design"
        }
        self.assertEqual(len(expected), 5)

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, source="local", source_dir=Path.cwd(), profile="full")
            apple_dir = paths.skills_dir / omh_skill_install_path("apple-design")
            for relative_path, content in expected.items():
                self.assertEqual((apple_dir / relative_path).read_text(encoding="utf-8"), content)

            missing_reference = apple_dir / "references/web-production-libraries.md"
            missing_reference.unlink()
            install_skill_pack(paths, source="local", source_dir=Path.cwd(), profile="full")
            self.assertEqual(missing_reference.read_text(encoding="utf-8"), expected["references/web-production-libraries.md"])

            uninstall_skill_pack(paths, remove_files=True)
            self.assertFalse(apple_dir.exists())

    def test_the_manifest_records_the_categorized_path(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            manifest = install_skill_pack(paths, profile="full")

            by_name = {str(record["name"]): str(record["path"]) for record in manifest["skills"]}
            for template in builtin_skill_templates():
                self.assertEqual(
                    by_name[template.name],
                    f"{omh_skill_install_path(template.name)}/SKILL.md",
                )

    def test_the_directory_walk_sees_both_layouts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="core")
            categorized = len(installed_skill_directories(paths.skills_dir))

            legacy = paths.skills_dir / "omh-left-behind"
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text("---\nname: omh-left-behind\n---\n", encoding="utf-8")

            found = installed_skill_directories(paths.skills_dir)
            self.assertEqual(len(found), categorized + 1)
            self.assertIn(legacy, found)


class DoctorSkillLayoutCheckTests(unittest.TestCase):
    def _layout_check(self, paths):
        return next(check for check in run_doctor(paths) if check.name == "skill_layout")

    def test_a_categorized_install_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="core")

            check = self._layout_check(paths)
            self.assertTrue(check.ok, check.message)

    def test_a_flat_leftover_is_named_with_its_repair(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="core")
            label = skill_directory_name("oh-my-hermes")
            leftover = paths.skills_dir / label
            leftover.mkdir(parents=True)
            (leftover / "SKILL.md").write_text(
                (paths.skills_dir / skill_install_relative_dir("oh-my-hermes") / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )

            check = self._layout_check(paths)
            self.assertFalse(check.ok)
            self.assertIn(label, check.message)
            self.assertIn("omh update", check.next_action)


if __name__ == "__main__":
    unittest.main()
