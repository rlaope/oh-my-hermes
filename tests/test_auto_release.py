from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from _distribution_helpers import PROJECT_ROOT, run
from tools.package_manager.bump_version import (
    PLUGIN_VERSION_PATTERN,
    PYPROJECT_VERSION_PATTERN,
    SITE_BADGE_PATTERN,
    SITE_I18N_BADGE_PATTERN,
    SOURCE_VERSION_PATTERN,
    bump_version_surfaces,
    next_patch_version,
)
from tools.package_manager.metadata import DistributionError, canonical_version

BUMP_VERSION = PROJECT_ROOT / "tools" / "package_manager" / "bump_version.py"
AUTO_RELEASE = PROJECT_ROOT / ".github" / "workflows" / "auto-release.yml"


def _write_project(root: Path, *, source_version: str = "1.0.7") -> None:
    (root / "src" / "omh").mkdir(parents=True)
    (root / "src" / "plugin_bundle" / "omh").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "oh-my-hermes"\nversion = "1.0.7"\n'
    )
    (root / "src" / "omh" / "version.py").write_text(
        f'__version__ = "{source_version}"\n'
    )
    (root / "src" / "plugin_bundle" / "omh" / "plugin.yaml").write_text(
        'name: omh\nversion: "1.0.5"\ndescription: "bundle"\n'
    )
    (root / ".release-channel").write_text("beta\n")
    (root / "site").mkdir()
    (root / "site" / "index.html").write_text(
        '<span data-i18n="hero.badge">For Hermes Agent · v1.0.6</span>\n',
        encoding="utf-8",
    )
    (root / "site" / "i18n.js").write_text(
        '    "hero.badge": {\n'
        '      en: "For Hermes Agent · v1.0.6",\n'
        '      ko: "Hermes Agent 전용 · v1.0.6",\n'
        '      ja: "Hermes Agent のための · v1.0.6",\n'
        '      zh: "为 Hermes Agent 打造 · v1.0.6"\n'
        '    },\n'
        '    "install.note": { en: "public as of v1.0.6" },\n',
        encoding="utf-8",
    )


class BumpVersionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)
        self.root = Path(self.stack.name)

    def test_bump_moves_every_surface_and_resets_channel(self) -> None:
        _write_project(self.root)
        new_version = bump_version_surfaces(self.root)
        self.assertEqual(new_version, "1.0.8")
        self.assertIn(
            'version = "1.0.8"', (self.root / "pyproject.toml").read_text()
        )
        self.assertIn(
            '__version__ = "1.0.8"',
            (self.root / "src" / "omh" / "version.py").read_text(),
        )
        self.assertIn(
            'version: "1.0.8"',
            (
                self.root / "src" / "plugin_bundle" / "omh" / "plugin.yaml"
            ).read_text(),
        )
        self.assertEqual(
            (self.root / ".release-channel").read_text(), "stable\n"
        )
        self.assertIn(
            'data-i18n="hero.badge">For Hermes Agent · v1.0.8</span>',
            (self.root / "site" / "index.html").read_text(encoding="utf-8"),
        )
        i18n = (self.root / "site" / "i18n.js").read_text(encoding="utf-8")
        self.assertEqual(i18n.count("· v1.0.8"), 4)
        # Historical prose ("public as of v1.0.6") is not a version surface.
        self.assertIn('en: "public as of v1.0.6"', i18n)

    def test_explicit_target_must_be_canonical_and_different(self) -> None:
        _write_project(self.root)
        self.assertEqual(
            bump_version_surfaces(self.root, target="2.0.0"), "2.0.0"
        )
        with self.assertRaises(DistributionError):
            bump_version_surfaces(self.root, target="not-a-version")
        with self.assertRaises(DistributionError):
            bump_version_surfaces(self.root, target="2.0.0")

    def test_dry_run_reports_without_writing(self) -> None:
        _write_project(self.root)
        self.assertEqual(bump_version_surfaces(self.root, dry_run=True), "1.0.8")
        self.assertIn(
            'version = "1.0.7"', (self.root / "pyproject.toml").read_text()
        )
        self.assertEqual((self.root / ".release-channel").read_text(), "beta\n")

    def test_bump_refuses_enforced_surface_parity_drift(self) -> None:
        _write_project(self.root, source_version="1.0.6")
        with self.assertRaises(DistributionError):
            bump_version_surfaces(self.root)

    def test_bump_refuses_plugin_manifest_without_version_line(self) -> None:
        _write_project(self.root)
        (self.root / "src" / "plugin_bundle" / "omh" / "plugin.yaml").write_text(
            "name: omh\n"
        )
        with self.assertRaises(DistributionError):
            bump_version_surfaces(self.root)

    def test_next_patch_version_contract(self) -> None:
        self.assertEqual(next_patch_version("1.0.7"), "1.0.8")
        self.assertEqual(next_patch_version("2.9.19"), "2.9.20")
        with self.assertRaises(DistributionError):
            next_patch_version("v1.0.7")

    def test_cli_refusal_exits_nonzero(self) -> None:
        _write_project(self.root)
        result = run(
            [
                sys.executable,
                str(BUMP_VERSION),
                "--project-root",
                str(self.root),
                "--set",
                "not-a-version",
            ],
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("bump refused", result.stderr)

    def test_cli_prints_only_the_new_version(self) -> None:
        _write_project(self.root)
        result = run(
            [
                sys.executable,
                str(BUMP_VERSION),
                "--project-root",
                str(self.root),
            ]
        )
        self.assertEqual(result.stdout.strip(), "1.0.8")

    def test_repository_surfaces_each_carry_one_version_line(self) -> None:
        surfaces = {
            PROJECT_ROOT / "pyproject.toml": PYPROJECT_VERSION_PATTERN,
            PROJECT_ROOT / "src" / "omh" / "version.py": SOURCE_VERSION_PATTERN,
            PROJECT_ROOT
            / "src"
            / "plugin_bundle"
            / "omh"
            / "plugin.yaml": PLUGIN_VERSION_PATTERN,
        }
        for path, pattern in surfaces.items():
            with self.subTest(surface=str(path.relative_to(PROJECT_ROOT))):
                self.assertEqual(len(pattern.findall(path.read_text())), 1)
        self.assertEqual(len(SITE_BADGE_PATTERN.findall((PROJECT_ROOT / "site" / "index.html").read_text(encoding="utf-8"))), 1)
        self.assertEqual(len(SITE_I18N_BADGE_PATTERN.findall((PROJECT_ROOT / "site" / "i18n.js").read_text(encoding="utf-8"))), 4)

    def test_repository_dry_run_bumps_to_the_next_patch(self) -> None:
        self.assertEqual(bump_version_surfaces(PROJECT_ROOT, dry_run=True), next_patch_version(canonical_version(PROJECT_ROOT)))


class AutoReleaseWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = AUTO_RELEASE.read_text()

    def test_release_is_cut_only_on_demand(self) -> None:
        """No trigger may cut a release without a person asking for one.

        A scheduled revision of this workflow moved the public version daily,
        which is what this guard exists to prevent: choosing that main is
        worth a version is a human decision, not a cron's.
        """

        triggers = self.workflow.split("\non:\n", 1)[1].split("\nconcurrency:", 1)[0]
        self.assertEqual(triggers.strip(), "workflow_dispatch:")
        self.assertNotIn("\n  schedule:", self.workflow)
        self.assertNotIn("cron:", self.workflow)
        self.assertNotIn("\n  push:", self.workflow)
        self.assertNotIn("pull_request", self.workflow)
        self.assertIn("group: auto-release\n", self.workflow)
        self.assertNotIn("group: auto-release-${{", self.workflow)

    def test_release_decision_guards_are_present(self) -> None:
        for contract in (
            "tools/package_manager/metadata.py --version",
            'git show-ref --verify --quiet "refs/tags/v$version"',
            'git rev-list -n 1 "v$version"',
            "not interfering",
            "proceed=false",
            'git show-ref --verify --quiet "refs/tags/v$new_version"',
        ):
            self.assertIn(contract, self.workflow)

    def test_gates_run_between_bump_and_push(self) -> None:
        bump = self.workflow.index("- name: Bump every version surface")
        gates = self.workflow.index(
            "- name: Run release gates on the bumped tree"
        )
        push = self.workflow.index("- name: Commit, tag, and push atomically")
        dispatch = self.workflow.index(
            "- name: Dispatch the distribution release"
        )
        self.assertLess(bump, gates)
        self.assertLess(gates, push)
        self.assertLess(push, dispatch)
        self.assertIn(
            "PYTHONPATH=tests uv run python -m unittest discover -s tests",
            self.workflow,
        )
        self.assertIn("uv run python -m compileall -q src tests", self.workflow)
        # The full suite includes the npm/Bun launcher tests, so the gate job
        # needs the same toolchain CI installs.
        self.assertIn("actions/setup-node@", self.workflow)
        self.assertIn("oven-sh/setup-bun@", self.workflow)
        self.assertIn('bun-version: "1.3.14"', self.workflow)

    def test_push_is_atomic_and_commit_is_signed_off(self) -> None:
        self.assertIn("git commit -s -m", self.workflow)
        self.assertIn(
            'git push --atomic origin HEAD:refs/heads/main "refs/tags/v$NEW_VERSION"',
            self.workflow,
        )
        for staged in (
            "pyproject.toml",
            "src/omh/version.py",
            "src/plugin_bundle/omh/plugin.yaml",
            ".release-channel",
            # The bump tool rewrites the site badge too; a cut that leaves
            # these unstaged ships a landing page one version behind.
            "site/index.html",
            "site/i18n.js",
        ):
            self.assertIn(staged, self.workflow)

    def test_dispatch_targets_the_distribution_workflow(self) -> None:
        self.assertIn(
            'gh workflow run release.yml --ref main --field tag="v$NEW_VERSION"',
            self.workflow,
        )
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn(
            "permissions:\n      contents: write\n      actions: write",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
