from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from _distribution_helpers import (
    NPM_PACKAGE_SOURCE,
    PROJECT_ROOT,
    PROJECT_VERSION,
    RENDER_HOMEBREW,
    build_wheel,
    run,
)


class HomebrewDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)
        self.root = Path(self.stack.name)
        self.wheel = build_wheel(self.root / "wheel")

    def _render(self, *arguments: str, check: bool = True):
        if not RENDER_HOMEBREW.is_file():
            raise AssertionError(
                f"Homebrew renderer entry point is missing: {RENDER_HOMEBREW}"
            )
        return run(
            [
                sys.executable,
                str(RENDER_HOMEBREW),
                *arguments,
            ],
            check=check,
        )

    def test_local_wheel_renders_valid_formula_contract(self) -> None:
        output = self.root / "omh.rb"
        self._render(
            "--version",
            PROJECT_VERSION,
            "--wheel",
            str(self.wheel),
            "--output",
            str(output),
        )
        formula = output.read_text()
        if os.name != "nt":
            self.assertEqual(output.stat().st_mode & 0o777, 0o644)
        self.assertTrue(formula.startswith("# typed: strict\n"))
        self.assertIn("# frozen_string_literal: true", formula)
        self.assertIn(
            "# Homebrew formula for the OMH maintenance command.",
            formula,
        )
        self.assertIn("class Omh < Formula", formula)
        self.assertIn(f'version "{PROJECT_VERSION}"', formula)
        self.assertIn(
            f'sha256 "{hashlib.sha256(self.wheel.read_bytes()).hexdigest()}"',
            formula,
        )
        self.assertIn(self.wheel.resolve().as_uri(), formula)
        self.assertIn('depends_on "python@3.14"', formula)
        self.assertIn(
            'formula_opt_bin("python@3.14")/"python3.14"',
            formula,
        )
        self.assertIn(
            'wheel = buildpath/"oh_my_hermes-#{version}-py3-none-any.whl"',
            formula,
        )
        self.assertIn("cp cached_download, wheel", formula)
        self.assertIn('ENV["PIP_NO_INDEX"] = "1"', formula)
        self.assertIn('shell_output("#{bin}/omh --help")', formula)

    def test_renderer_rejects_malformed_production_identity(self) -> None:
        output = self.root / "omh.rb"
        result = self._render(
            "--version",
            "1.0",
            "--sha256",
            "bad",
            "--url",
            "http://example.test/omh.whl",
            "--output",
            str(output),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipIf(sys.platform == "win32", "symlink attack probe is POSIX-only")
    def test_renderer_refuses_symlinked_output_components(self) -> None:
        target = self.root / "formula-target"
        target.mkdir()
        victim = target / "omh.rb"
        victim.write_text("preserve\n")
        direct_link = self.root / "direct.rb"
        direct_link.symlink_to(victim)
        parent_link = self.root / "formula-parent"
        parent_link.symlink_to(target, target_is_directory=True)

        for output in (direct_link, parent_link / "new.rb"):
            with self.subTest(output=output):
                result = self._render(
                    "--version",
                    PROJECT_VERSION,
                    "--wheel",
                    str(self.wheel),
                    "--output",
                    str(output),
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symbolic link", result.stderr)
        self.assertEqual(victim.read_text(), "preserve\n")
        self.assertFalse((target / "new.rb").exists())


class DistributionReleaseContractTests(unittest.TestCase):
    def test_npm_owner_preflight_accepts_cli_text_and_json(self) -> None:
        metadata = PROJECT_ROOT / "tools" / "package_manager" / "metadata.py"
        accepted = (
            "rlaope <piyrw9754@gmail.com>\n",
            '["rlaope"]\n',
            '{"rlaope":"piyrw9754@gmail.com"}\n',
            '[{"name":"rlaope","email":"piyrw9754@gmail.com"}]\n',
        )
        for owner_output in accepted:
            with self.subTest(owner_output=owner_output):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(metadata),
                        "--require-npm-owner",
                        "rlaope",
                    ],
                    cwd=PROJECT_ROOT,
                    input=owner_output,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        rejected = subprocess.run(
            [
                sys.executable,
                str(metadata),
                "--require-npm-owner",
                "rlaope",
            ],
            cwd=PROJECT_ROOT,
            input="other-owner <owner@example.test>\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("required npm owner is missing", rejected.stderr)

    def test_version_comparison_cli_guards_tap_monotonicity(self) -> None:
        metadata = (
            PROJECT_ROOT / "tools" / "package_manager" / "metadata.py"
        )
        for existing, candidate, expected in (
            ("1.0.4", "1.0.5", "-1"),
            ("1.0.5", "1.0.5", "0"),
            ("1.0.6", "1.0.5", "1"),
        ):
            with self.subTest(existing=existing, candidate=candidate):
                result = run(
                    [
                        sys.executable,
                        str(metadata),
                        "--compare-versions",
                        existing,
                        candidate,
                    ]
                )
                self.assertEqual(result.stdout.strip(), expected)
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        self.assertIn(
            'metadata.py --compare-versions "$existing_version" "$OMH_VERSION"',
            workflow,
        )
        self.assertIn(
            "ruby -ne 'puts Regexp.last_match(1)",
            workflow,
        )
        self.assertIn("' \"$formula\"", workflow)

    def test_release_serializes_tags_and_refuses_tap_downgrades(
        self,
    ) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        self.assertIn("group: distribution-release\n", workflow)
        self.assertNotIn(
            "group: distribution-release-${{",
            workflow,
        )
        guard = workflow.index('existing_version="$(')
        publish = workflow.index('cp "$RUNNER_TEMP/omh.rb" "$formula"')
        self.assertLess(guard, publish)
        self.assertIn('test "$version_order" -le 0', workflow)
        self.assertIn(
            'cmp "$RUNNER_TEMP/omh.rb" "$tap/Formula/omh.rb"',
            workflow,
        )

    def test_release_steps_have_one_complete_ordered_artifact_chain(
        self,
    ) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        steps = (
            "Validate tag and distribution contracts",
            "Build one immutable wheel and npm tarball",
            "Preflight npm and Homebrew destinations",
            "Create or verify immutable GitHub release asset",
            "Verify immutable release wheel",
            "Publish or verify npm package",
            "Render verified Homebrew formula",
            "Publish or verify Homebrew tap formula",
        )
        positions = [workflow.index(f"- name: {step}") for step in steps]
        self.assertEqual(positions, sorted(positions))
        for step in steps:
            self.assertEqual(workflow.count(f"- name: {step}"), 1)
        self.assertEqual(workflow.count("uv build --wheel"), 1)
        self.assertEqual(
            workflow.count("tools/package_manager/stage_npm.py"),
            1,
        )
        self.assertEqual(workflow.count("npm pack --pack-destination"), 1)
        self.assertLess(
            workflow.index('echo "SOURCE_DATE_EPOCH='),
            workflow.index("- name: Build one immutable wheel and npm tarball"),
        )

    def test_ci_lints_distribution_tools(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text()
        self.assertIn("ruff check src tests tools packaging", workflow)

    def test_ci_styles_formula_before_installing_it(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text()
        render = workflow.index(
            "uv run tools/package_manager/render_homebrew.py"
        )
        style = workflow.index('brew style "$formula"')
        install = workflow.index("brew install omh/local-qa/omh")
        self.assertLess(render, style)
        self.assertLess(style, install)

    def test_release_uses_trusted_publishing_toolchain_minimums(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        self.assertIn('node-version: "22.14.0"', workflow)
        self.assertIn("npm install --global npm@11.5.1", workflow)
        self.assertIn('test "$(npm --version)" = "11.5.1"', workflow)

    def test_release_asset_is_verified_before_npm_publication(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        asset = workflow.index(
            "- name: Create or verify immutable GitHub release asset"
        )
        verify = workflow.index("- name: Verify immutable release wheel")
        npm = workflow.index("- name: Publish or verify npm package")
        formula = workflow.index("- name: Render verified Homebrew formula")
        tap = workflow.index(
            "- name: Publish or verify Homebrew tap formula"
        )
        self.assertLess(asset, verify)
        self.assertLess(verify, npm)
        self.assertLess(npm, formula)
        self.assertLess(formula, tap)
        self.assertIn('gh release upload "$RELEASE_TAG"', workflow)
        self.assertNotIn("--clobber", workflow)

    def test_builds_receive_a_deterministic_source_date_epoch(self) -> None:
        release = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        ci = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()
        documentation = (PROJECT_ROOT / "docs" / "DISTRIBUTION.md").read_text()
        self.assertIn(
            'git show -s --format=%ct "$tag_commit"',
            release,
        )
        self.assertIn(
            'echo "SOURCE_DATE_EPOCH=$source_date_epoch" >> "$GITHUB_ENV"',
            release,
        )
        self.assertIn(
            'export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"',
            ci,
        )
        self.assertIn("export SOURCE_DATE_EPOCH=", documentation)

    def test_release_destinations_are_preflighted_before_first_write(
        self,
    ) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        preflight = workflow.index(
            "- name: Preflight npm and Homebrew destinations"
        )
        first_write = workflow.index(
            "- name: Create or verify immutable GitHub release asset"
        )
        self.assertLess(preflight, first_write)
        for contract in (
            "npm view oh-my-hermes name",
            "npm owner ls oh-my-hermes",
            "--require-npm-owner rlaope",
            "ACTIONS_ID_TOKEN_REQUEST_URL",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
            "git -C \"$tap\" push --dry-run origin HEAD:refs/heads/main",
        ):
            self.assertIn(contract, workflow)
        self.assertEqual(workflow.count("repository: rlaope/homebrew-tap"), 1)

    def test_release_authority_requires_real_tag_on_main(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        for contract in (
            "refs/tags/{0}",
            '[[ "$RELEASE_TAG" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]',
            'git show-ref --verify --quiet "refs/tags/$RELEASE_TAG"',
            'test "$tag_commit" = "$(git rev-parse HEAD)"',
            'git merge-base --is-ancestor "$tag_commit" origin/main',
            'test "$tag_commit" = "$(git rev-parse origin/main)"',
        ):
            self.assertIn(contract, workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn(
            "publish:\n    permissions:\n      contents: write\n      id-token: write",
            workflow,
        )

    def test_manual_release_resume_is_limited_to_release_control_changes(
        self,
    ) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        self.assertIn('if [ "$GITHUB_EVENT_NAME" = "push" ]; then', workflow)
        self.assertIn(
            'recovery_changes="$(git diff --name-only '
            '"$tag_commit"..origin/main)"',
            workflow,
        )
        for allowed_path in (
            ".github/workflows/release.yml",
            "docs/DISTRIBUTION.md",
            "tests/test_homebrew_distribution.py",
            "tools/package_manager/metadata.py",
        ):
            self.assertIn(allowed_path, workflow)
        self.assertIn(
            'owner_verifier="$RUNNER_TEMP/npm-owner-metadata.py"',
            workflow,
        )
        self.assertIn(
            "git show origin/main:tools/package_manager/metadata.py",
            workflow,
        )

    def test_workflow_actions_are_pinned_to_full_commits(self) -> None:
        action_reference = re.compile(
            r"(?:-\s+)?uses:\s+[^@\s]+@[0-9a-f]{40}(?:\s+#.*)?$"
        )
        for relative in (
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
        ):
            with self.subTest(workflow=relative):
                content = (PROJECT_ROOT / relative).read_text()
                uses_lines = [
                    line.strip()
                    for line in content.splitlines()
                    if line.strip().startswith(("- uses:", "uses:"))
                ]
                self.assertTrue(uses_lines)
                for line in uses_lines:
                    self.assertRegex(line, action_reference)

    def test_recovery_matrix_covers_every_partial_release_boundary(self) -> None:
        documentation = (PROJECT_ROOT / "docs" / "DISTRIBUTION.md").read_text()
        for scenario in (
            "GitHub release succeeds, npm fails",
            "npm succeeds, Homebrew tap fails",
            "Release asset is missing",
            "Artifact identity mismatch",
        ):
            self.assertIn(scenario, documentation)

    def test_ci_dry_runs_exact_distribution_artifacts(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("distribution:", workflow)
        self.assertIn("oven-sh/setup-bun", workflow)
        self.assertIn("tools/package_manager/stage_npm.py", workflow)
        self.assertIn("npm publish --dry-run", workflow)
        self.assertIn("brew tap-new --no-git omh/local-qa", workflow)
        self.assertIn("brew install omh/local-qa/omh", workflow)
        self.assertIn("brew uninstall omh", workflow)

    def test_release_workflow_uses_one_staged_wheel(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        self.assertTrue(workflow.is_file(), "distribution release workflow missing")
        content = workflow.read_text()
        self.assertIn("npm publish", content)
        self.assertIn("--provenance", content)
        self.assertIn("id-token: write", content)
        self.assertIn(
            "ssh-key: ${{ secrets.HOMEBREW_TAP_SSH_KEY }}",
            content,
        )
        self.assertNotIn("HOMEBREW_TAP_TOKEN", content)
        self.assertIn("render_homebrew.py", content)
        self.assertLess(
            content.index("npm publish"),
            content.index("render_homebrew.py"),
        )

    def test_missing_npm_version_reaches_publish_instead_of_integrity_check(
        self,
    ) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        self.assertIn(
            'if published_integrity="$(\n'
            '            npm view "oh-my-hermes@$OMH_VERSION" '
            "dist.integrity --json 2>/dev/null\n"
            '          )"; then',
            workflow,
        )
        self.assertNotIn("tr -d '\"' || true", workflow)
        self.assertIn('npm publish "$OMH_TARBALL"', workflow)

    def test_channel_arrays_expand_safely_on_bash_3_2(self) -> None:
        """The stable path leaves both channel arrays empty.

        The release job runs on macos-latest, whose /bin/bash is 3.2, where
        `set -u` rejects a bare "${a[@]}" for an empty array. Only the beta
        path appends to these arrays, so the bug stayed invisible through
        v1.0.7 (beta) and broke v1.0.8, the first stable cut, before it could
        create the GitHub release.
        """

        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text()
        for array in ("extra", "tag_args"):
            with self.subTest(array=array):
                self.assertIn(
                    '${%s[@]+"${%s[@]}"}' % (array, array),
                    workflow,
                )
                self.assertNotIn(f'"${{{array}[@]}}"\n', workflow)
        if not Path("/bin/bash").is_file():
            self.skipTest("no /bin/bash to execute the expansion against")
        for channel, expected in (("stable", ""), ("beta", "--prerelease")):
            with self.subTest(channel=channel):
                script = (
                    "set -euo pipefail\n"
                    "extra=()\n"
                    f'if [ "{channel}" = "beta" ]; then extra+=(--prerelease); fi\n'
                    'printf "%s" "${extra[@]+"${extra[@]}"}"\n'
                )
                result = run(["/bin/bash", "-c", script])
                self.assertEqual(result.stdout, expected)

    def test_npm_template_has_no_published_placeholder_version(self) -> None:
        template = NPM_PACKAGE_SOURCE / "package.template.json"
        self.assertTrue(template.is_file(), "npm package template missing")
        payload = json.loads(template.read_text())
        self.assertEqual(payload["version"], "__OMH_VERSION__")
        self.assertNotIn("scripts", payload)
