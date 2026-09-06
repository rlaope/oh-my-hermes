"""Contract tests for `build_identity/v1`.

Every state the identity has to survive is built here rather than assumed from
the machine running the suite: temporary git repositories for clean, dirty, and
detached-HEAD checkouts, hand-written `.git` trees for the git-free path, a
site-packages layout with and without a stamp, and injected seams for a missing
`git` binary and for several `omh` commands on `PATH`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.maintenance.build_identity import (  # noqa: E402
    BUILD_IDENTITY_CLAIM_BOUNDARY,
    BUILD_IDENTITY_SCHEMA,
    BUILD_IDENTITY_STAMP_SCHEMA,
    IDENTITY_SOURCES,
    IDENTITY_STATUSES,
    INSTALL_KINDS,
    STAMP_FILE_NAME,
    UNAVAILABLE_REASONS,
    build_identity_summary,
    probe_build_identity,
    resolve_command_path,
)
from omh.version import __version__  # noqa: E402

GIT = shutil.which("git")
NEEDS_GIT = unittest.skipUnless(GIT, "a local git binary is required to build the fixture repositories")

_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=OMH Build Identity Test",
            "-c",
            "user.email=build-identity@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repo),
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _write_project(root: Path, *, name: str = "oh-my-hermes") -> Path:
    """Lay down a checkout whose pyproject declares ``name``."""
    package_root = root / "src" / "omh"
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    return package_root


def _init_repo(root: Path, *, name: str = "oh-my-hermes") -> Path:
    package_root = _write_project(root, name=name)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return package_root


def _head_sha(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


class _FakeDistribution:
    """The two members `_editable_direct_url_text` reads off a distribution."""

    def __init__(self, name: str, direct_url: str | None) -> None:
        self.metadata = {"Name": name}
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        return self._direct_url if filename == "direct_url.json" else None


def _editable_distributions(*roots: Path):
    payloads = [
        json.dumps({"url": root.as_uri(), "dir_info": {"editable": True}})
        for root in roots
    ]
    return lambda: [_FakeDistribution("oh-my-hermes", payload) for payload in payloads]


def _no_distributions():
    return lambda: []


def _probe(package_root: Path, **overrides):
    keywords = {
        "package_root": package_root,
        "argv0": "",
        "distributions": _no_distributions(),
        "frozen": False,
    }
    keywords.update(overrides)
    return probe_build_identity(**keywords)


class SourceCheckoutIdentityTests(unittest.TestCase):
    @NEEDS_GIT
    def test_clean_source_checkout_reports_its_commit_and_clean_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _init_repo(root)

            identity = _probe(package_root)

            self.assertEqual(identity["install_kind"], "source_checkout")
            self.assertEqual(identity["identity_status"], "verified")
            self.assertEqual(identity["identity_source"], "git_command")
            self.assertEqual(identity["commit_sha"], _head_sha(root))
            self.assertIs(identity["dirty"], False)
            self.assertEqual(identity["dirty_status"], "clean")
            self.assertEqual(identity["reason"], "")
            self.assertEqual(
                identity["summary"],
                f"omh {__version__} (source {_head_sha(root)[:8]}, clean)",
            )

    @NEEDS_GIT
    def test_dirty_checkout_reports_dirty_without_naming_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _init_repo(root)
            (root / "src" / "omh" / "__init__.py").write_text("# edited\n", encoding="utf-8")
            (root / "operator_private_note.txt").write_text(
                "an unpublished local secret\n", encoding="utf-8"
            )

            identity = _probe(package_root)
            serialized = json.dumps(identity)

            self.assertIs(identity["dirty"], True)
            self.assertEqual(identity["dirty_status"], "dirty")
            self.assertIn("dirty", identity["summary"])
            self.assertNotIn("operator_private_note", serialized)
            self.assertNotIn("unpublished local secret", serialized)
            self.assertNotIn("# edited", serialized)

    @NEEDS_GIT
    def test_two_same_version_checkouts_at_different_commits_differ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            first_package = _init_repo(first_root)
            second_package = _init_repo(second_root)
            (second_root / "extra.txt").write_text("second\n", encoding="utf-8")
            _git(second_root, "add", "-A")
            _git(second_root, "commit", "-q", "-m", "second commit")

            first = _probe(first_package)
            second = _probe(second_package)

            self.assertEqual(first["version"], second["version"])
            self.assertNotEqual(first["commit_sha"], second["commit_sha"])
            self.assertNotEqual(first["summary"], second["summary"])

    @NEEDS_GIT
    def test_detached_head_still_reports_the_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _init_repo(root)
            head = _head_sha(root)
            _git(root, "checkout", "-q", "--detach", head)

            identity = _probe(package_root)

            self.assertEqual(identity["identity_status"], "verified")
            self.assertEqual(identity["commit_sha"], head)
            self.assertNotIn("HEAD", identity["summary"])

    @NEEDS_GIT
    def test_editable_install_of_the_checkout_is_labelled_editable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _init_repo(root)

            identity = _probe(package_root, distributions=_editable_distributions(root))

            self.assertEqual(identity["install_kind"], "editable_install")
            self.assertEqual(identity["identity_status"], "verified")
            self.assertEqual(identity["commit_sha"], _head_sha(root))
            self.assertTrue(identity["summary"].startswith(f"omh {__version__} (editable "))

    @NEEDS_GIT
    def test_an_editable_install_of_another_checkout_does_not_relabel_this_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _init_repo(root)
            elsewhere = root.parent / f"{root.name}-elsewhere"

            identity = _probe(package_root, distributions=_editable_distributions(elsewhere))

            self.assertEqual(identity["install_kind"], "source_checkout")

    @NEEDS_GIT
    def test_identity_follows_the_package_source_not_the_caller_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_repo = root / "package-repo"
            caller_repo = root / "caller-repo"
            package_repo.mkdir()
            caller_repo.mkdir()
            package_root = _init_repo(package_repo)
            _init_repo(caller_repo, name="some-other-project")

            previous = Path.cwd()
            os.chdir(caller_repo)
            try:
                identity = _probe(package_root)
            finally:
                os.chdir(previous)

            self.assertEqual(identity["commit_sha"], _head_sha(package_repo))
            self.assertNotEqual(identity["commit_sha"], _head_sha(caller_repo))


class InstalledArtifactIdentityTests(unittest.TestCase):
    def _site_packages(self, root: Path) -> Path:
        package_root = root / "venv" / "lib" / "python3.11" / "site-packages" / "omh"
        package_root.mkdir(parents=True)
        return package_root

    def test_installed_package_without_a_stamp_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_root = self._site_packages(Path(tmp).resolve())

            identity = _probe(package_root)

            self.assertEqual(identity["install_kind"], "installed_package")
            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertEqual(identity["identity_source"], "none")
            self.assertIsNone(identity["commit_sha"])
            self.assertIsNone(identity["dirty"])
            self.assertEqual(identity["dirty_status"], "unknown")
            self.assertEqual(identity["reason"], "no_stamped_identity")
            self.assertEqual(
                identity["summary"],
                f"omh {__version__} (build identity unavailable: installed package, no stamped identity)",
            )

    def test_installed_package_with_a_stamp_reports_the_stamped_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_root = self._site_packages(Path(tmp).resolve())
            (package_root / STAMP_FILE_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": BUILD_IDENTITY_STAMP_SCHEMA,
                        "commit_sha": _SHA_A,
                        "dirty": False,
                    }
                ),
                encoding="utf-8",
            )

            identity = _probe(package_root)

            self.assertEqual(identity["install_kind"], "installed_package")
            self.assertEqual(identity["identity_status"], "verified")
            self.assertEqual(identity["identity_source"], "stamped_artifact")
            self.assertEqual(identity["commit_sha"], _SHA_A)
            self.assertEqual(identity["dirty_status"], "clean")
            self.assertEqual(
                identity["summary"],
                f"omh {__version__} (build {_SHA_A[:8]}, clean)",
            )

    def test_a_malformed_stamp_is_reported_rather_than_treated_as_absent(self) -> None:
        for label, content in (
            ("not json", "{"),
            ("wrong schema", json.dumps({"schema_version": "other/v1", "commit_sha": _SHA_A})),
            (
                "short sha",
                json.dumps({"schema_version": BUILD_IDENTITY_STAMP_SCHEMA, "commit_sha": "abc"}),
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                package_root = self._site_packages(Path(tmp).resolve())
                (package_root / STAMP_FILE_NAME).write_text(content, encoding="utf-8")

                identity = _probe(package_root)

                self.assertEqual(identity["identity_status"], "unavailable")
                self.assertIsNone(identity["commit_sha"])
                self.assertEqual(identity["reason"], "malformed_stamped_identity")

    def test_a_staged_wheel_beside_its_dist_info_is_an_installed_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp).resolve() / "site"
            package_root = site / "omh"
            package_root.mkdir(parents=True)
            (site / "oh_my_hermes-2.0.1.dist-info").mkdir()

            identity = _probe(package_root)

            self.assertEqual(identity["install_kind"], "installed_package")
            self.assertEqual(identity["reason"], "no_stamped_identity")

    def test_a_frozen_standalone_artifact_reports_its_own_install_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp).resolve() / "bundle" / "omh"
            package_root.mkdir(parents=True)

            identity = _probe(package_root, frozen=True)

            self.assertEqual(identity["install_kind"], "standalone_artifact")
            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertEqual(identity["reason"], "no_stamped_identity")
            self.assertIn("standalone artifact", identity["summary"])

    def test_a_source_archive_without_git_metadata_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "oh-my-hermes-2.0.1"
            package_root = _write_project(root)

            identity = _probe(package_root)

            self.assertEqual(identity["install_kind"], "unknown")
            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertIsNone(identity["commit_sha"])
            self.assertEqual(identity["reason"], "no_source_identity")
            self.assertIn("unknown install", identity["summary"])

    @NEEDS_GIT
    def test_an_install_nested_in_an_unrelated_repository_borrows_no_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host_repo = Path(tmp).resolve() / "someone-elses-project"
            host_repo.mkdir()
            _init_repo(host_repo, name="someone-elses-project")
            package_root = host_repo / ".venv" / "lib" / "python3.11" / "site-packages" / "omh"
            package_root.mkdir(parents=True)

            identity = _probe(package_root)

            self.assertEqual(identity["install_kind"], "installed_package")
            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertIsNone(identity["commit_sha"])
            self.assertNotEqual(identity["reason"], "")


class GitUnavailableIdentityTests(unittest.TestCase):
    def _hand_written_repo(self, root: Path, *, head: str) -> Path:
        package_root = _write_project(root)
        git_dir = root / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text(head, encoding="utf-8")
        return package_root

    def test_missing_git_binary_falls_back_to_refs_with_unknown_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = self._hand_written_repo(root, head="ref: refs/heads/main\n")
            (root / ".git" / "refs" / "heads" / "main").write_text(f"{_SHA_A}\n", encoding="utf-8")

            identity = _probe(package_root, which=lambda name: None)

            self.assertEqual(identity["install_kind"], "source_checkout")
            self.assertEqual(identity["identity_status"], "verified")
            self.assertEqual(identity["identity_source"], "git_refs")
            self.assertEqual(identity["commit_sha"], _SHA_A)
            self.assertIsNone(identity["dirty"])
            self.assertEqual(identity["dirty_status"], "unknown")
            self.assertEqual(
                identity["summary"],
                f"omh {__version__} (source {_SHA_A[:8]}, dirty state unknown)",
            )

    def test_missing_git_binary_reads_a_packed_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = self._hand_written_repo(root, head="ref: refs/heads/main\n")
            (root / ".git" / "packed-refs").write_text(
                "# pack-refs with: peeled fully-peeled sorted \n"
                f"{_SHA_B} refs/heads/main\n"
                f"^{_SHA_A}\n",
                encoding="utf-8",
            )

            identity = _probe(package_root, which=lambda name: None)

            self.assertEqual(identity["commit_sha"], _SHA_B)
            self.assertEqual(identity["identity_source"], "git_refs")

    def test_missing_git_binary_reads_a_detached_head_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = self._hand_written_repo(root, head=f"{_SHA_A}\n")

            identity = _probe(package_root, which=lambda name: None)

            self.assertEqual(identity["commit_sha"], _SHA_A)

    def test_missing_git_binary_and_unreadable_refs_stay_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _write_project(root)
            (root / ".git").mkdir()

            identity = _probe(package_root, which=lambda name: None)

            self.assertEqual(identity["install_kind"], "source_checkout")
            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertIsNone(identity["commit_sha"])
            self.assertEqual(identity["reason"], "git_unavailable")
            self.assertIn("git not available", identity["summary"])

    def test_a_git_timeout_never_becomes_a_revision(self) -> None:
        def timing_out_runner(command, **keywords):
            raise subprocess.TimeoutExpired(command, 15)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _write_project(root)
            (root / ".git").mkdir()

            identity = _probe(
                package_root,
                which=lambda name: "/usr/bin/git",
                runner=timing_out_runner,
            )

            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertIsNone(identity["commit_sha"])
            self.assertEqual(identity["reason"], "git_probe_failed")

    def test_a_confirmed_work_tree_with_an_unreadable_head_stays_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _write_project(root)

            def partial_runner(command, **keywords):
                if command[-1] == "--show-toplevel":
                    return subprocess.CompletedProcess(command, 0, f"{root}\n", "")
                return subprocess.CompletedProcess(command, 128, "", "fatal: bad object HEAD")

            identity = _probe(
                package_root,
                which=lambda name: "/usr/bin/git",
                runner=partial_runner,
            )

            self.assertEqual(identity["install_kind"], "source_checkout")
            self.assertEqual(identity["identity_status"], "unavailable")
            self.assertEqual(identity["reason"], "git_probe_failed")


class CommandPathIdentityTests(unittest.TestCase):
    def test_an_absolute_argv0_wins_over_the_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            first = root / "first" / "omh"
            second = root / "second" / "omh"
            for command in (first, second):
                command.parent.mkdir(parents=True)
                command.write_text("#!/bin/sh\n", encoding="utf-8")

            shadowed, status = resolve_command_path(str(second), which=lambda name: str(first))

            self.assertEqual(status, "resolved")
            self.assertEqual(shadowed, str(second))

    def test_a_bare_command_name_resolves_through_the_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command = Path(tmp).resolve() / "omh"
            command.write_text("#!/bin/sh\n", encoding="utf-8")

            resolved, status = resolve_command_path("omh", which=lambda name: str(command))

            self.assertEqual(status, "resolved")
            self.assertEqual(resolved, str(command))

    def test_a_bare_name_never_resolves_to_a_directory_in_the_working_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "omh").mkdir()
            installed = root / "bin" / "omh"
            installed.parent.mkdir()
            installed.write_text("#!/bin/sh\n", encoding="utf-8")

            previous = Path.cwd()
            os.chdir(root)
            try:
                resolved, status = resolve_command_path("omh", which=lambda name: str(installed))
            finally:
                os.chdir(previous)

            self.assertEqual(status, "resolved")
            self.assertEqual(resolved, str(installed))

    def test_an_unresolvable_command_is_reported_as_unresolved(self) -> None:
        for argv0 in ("", "   ", "omh-not-installed"):
            with self.subTest(argv0=argv0):
                resolved, status = resolve_command_path(argv0, which=lambda name: None)

                self.assertIsNone(resolved)
                self.assertEqual(status, "unresolved")

    @NEEDS_GIT
    def test_the_identity_carries_the_command_that_ran(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            package_root = _init_repo(root)
            command = root / "bin" / "omh"
            command.parent.mkdir()
            command.write_text("#!/bin/sh\n", encoding="utf-8")

            identity = _probe(package_root, argv0=str(command))

            self.assertEqual(identity["command_path"], str(command))
            self.assertEqual(identity["command_path_status"], "resolved")


class BuildIdentityShapeTests(unittest.TestCase):
    def test_every_field_stays_inside_the_declared_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp).resolve() / "site-packages" / "omh"
            package_root.mkdir(parents=True)

            identity = _probe(package_root)

            self.assertEqual(
                sorted(identity),
                [
                    "claim_boundary",
                    "command_path",
                    "command_path_status",
                    "commit_sha",
                    "dirty",
                    "dirty_status",
                    "identity_source",
                    "identity_status",
                    "install_kind",
                    "reason",
                    "schema_version",
                    "summary",
                    "version",
                ],
            )
            self.assertEqual(identity["schema_version"], BUILD_IDENTITY_SCHEMA)
            self.assertEqual(identity["version"], __version__)
            self.assertEqual(identity["claim_boundary"], BUILD_IDENTITY_CLAIM_BOUNDARY)
            self.assertIn(identity["install_kind"], INSTALL_KINDS)
            self.assertIn(identity["identity_status"], IDENTITY_STATUSES)
            self.assertIn(identity["identity_source"], IDENTITY_SOURCES)
            self.assertIn(identity["command_path_status"], ("resolved", "unresolved"))
            self.assertIn(identity["dirty_status"], ("clean", "dirty", "unknown"))
            self.assertIn(identity["reason"], ("", *UNAVAILABLE_REASONS))
            self.assertTrue(json.dumps(identity))

    def test_the_claim_boundary_refuses_the_evidence_it_is_not(self) -> None:
        for word in ("tested", "reviewed", "CI", "published"):
            with self.subTest(word=word):
                self.assertIn(word, BUILD_IDENTITY_CLAIM_BOUNDARY)

    def test_the_summary_never_leaks_a_branch_or_remote(self) -> None:
        identity = {
            "version": "9.9.9",
            "install_kind": "source_checkout",
            "identity_status": "verified",
            "commit_sha": _SHA_A,
            "dirty": True,
        }

        self.assertEqual(build_identity_summary(identity), f"omh 9.9.9 (source {_SHA_A[:8]}, dirty)")


class BuildIdentityCliTests(unittest.TestCase):
    def test_version_prints_the_semantic_version_and_the_build_identity(self) -> None:
        status, stdout, _ = run_cli(["--version"], output_json=False)

        self.assertEqual(status, 0)
        line = stdout.strip()
        self.assertTrue(line.startswith(f"omh {__version__} ("), line)
        self.assertEqual(len(line.splitlines()), 1)

    def test_doctor_json_carries_the_schema_versioned_identity_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(root / "omh"),
                    "--hermes-home",
                    str(root / "hermes"),
                    "doctor",
                    "--json",
                ]
            )

            payload = json.loads(stdout)
            identity = payload["build_identity"]

            self.assertEqual(identity["schema_version"], BUILD_IDENTITY_SCHEMA)
            self.assertIn(identity["install_kind"], INSTALL_KINDS)
            self.assertIn(identity["identity_status"], IDENTITY_STATUSES)
            self.assertIn("command_path", identity)
            self.assertIn("dirty_status", identity)
            self.assertEqual(identity["claim_boundary"], BUILD_IDENTITY_CLAIM_BOUNDARY)

    def test_doctor_human_output_carries_one_build_identity_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(root / "omh"),
                    "--hermes-home",
                    str(root / "hermes"),
                    "doctor",
                ],
                output_json=False,
            )

            lines = [line for line in stdout.splitlines() if "Build identity:" in line]

            self.assertEqual(len(lines), 1, stdout)
            self.assertIn(f"omh {__version__}", lines[0])

    def test_an_unavailable_identity_does_not_change_the_doctor_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = [
                "--omh-home",
                str(root / "omh"),
                "--hermes-home",
                str(root / "hermes"),
                "doctor",
                "--json",
            ]
            status, stdout, _ = run_cli(arguments)
            payload = json.loads(stdout)

            self.assertEqual(status, 0 if payload["ok"] else 1)
            self.assertNotIn(
                "build_identity",
                [check["name"] for check in payload["checks"]],
            )


if __name__ == "__main__":
    unittest.main()
