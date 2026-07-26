"""Repository-specific OMH artifacts resolve to the repository they describe.

Plans used to be written into `~/.hermes/plans`: Hermes' own home, one flat
directory for every project, with `scope.ref` hardcoded to "default" so nothing
in the artifact said which repository it came from. These tests pin the four
decisions that replaced it -- how a root is found, which store wins, whether the
store is ignored, and what identity the artifact carries.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.paths import (
    OmhPaths,
    ensure_project_store_ignored,
    find_project_root,
    project_artifact_dir,
    project_identity,
    resolve_paths,
)
from omh.workflows.hermes_planning import (
    build_hermes_plan_payload,
    build_plan_handoff_context_pack,
    write_hermes_plan,
)


def _repo(root: Path, *, git_as_file: bool = False) -> Path:
    """A directory that looks like a git checkout to the resolver."""
    marker = root / ".git"
    if git_as_file:
        # What a linked worktree actually leaves behind.
        marker.write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    else:
        marker.mkdir()
    return root


class FindProjectRootTests(unittest.TestCase):
    def test_nested_directory_resolves_to_the_repository_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            nested = root / "src" / "deep" / "nested"
            nested.mkdir(parents=True)
            self.assertEqual(find_project_root(nested), root)

    def test_git_as_a_file_resolves_like_git_as_a_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            # A linked worktree writes `.git` as a file. Testing only for a
            # directory would send every worktree to the user-scope fallback.
            root = _repo(Path(tmp).resolve(), git_as_file=True)
            self.assertEqual(find_project_root(root), root)

    def test_the_nearest_repository_root_wins(self) -> None:
        with TemporaryDirectory() as tmp:
            outer = _repo(Path(tmp).resolve())
            inner = outer / "vendor" / "lib"
            inner.mkdir(parents=True)
            _repo(inner)
            (inner / "src").mkdir()
            # Returning the outermost root would put a vendored library's plans
            # in its host repository.
            self.assertEqual(find_project_root(inner / "src"), inner)

    def test_resolution_runs_no_subprocess(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            # PATH emptied: a `git rev-parse` implementation would fail here.
            previous = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                self.assertEqual(find_project_root(root), root)
            finally:
                os.environ["PATH"] = previous


class ArtifactDirTests(unittest.TestCase):
    def test_inside_a_repository_artifacts_sit_beside_the_code(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            paths = resolve_paths()  # default home, so the repository decides
            self.assertEqual(
                project_artifact_dir(paths, "plans", cwd=root),
                root / ".omh" / "plans",
            )

    def test_an_explicit_omh_home_wins_over_the_repository(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            named = root / "explicit-home"
            paths = resolve_paths(named, root / ".hermes")
            # `--omh-home` says where the store is; inferring past it would make
            # the flag a lie and would scatter test output into the source tree.
            self.assertEqual(project_artifact_dir(paths, "plans", cwd=root), named / "plans")

    def test_an_explicit_home_equal_to_the_default_still_wins(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            named = Path(os.environ["OMH_HOME"]).resolve()  # what resolve_paths would default to
            paths = resolve_paths(named, root / ".hermes")
            # Detecting "explicit" by comparing the resolved home against the
            # default cannot see this case: a caller that passes the same value
            # the default resolves to is still a caller that named it. Any
            # script passing --omh-home for reproducibility hits this.
            self.assertTrue(paths.omh_home_named)
            self.assertEqual(project_artifact_dir(paths, "plans", cwd=root), named / "plans")

    def test_an_unnamed_home_lets_the_repository_decide(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            paths = resolve_paths()
            self.assertFalse(paths.omh_home_named)
            self.assertEqual(project_artifact_dir(paths, "plans", cwd=root), root / ".omh" / "plans")

    def test_scope_project_still_resolves_to_the_repository_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            nested = root / "nested" / "deep"
            nested.mkdir(parents=True)
            paths = resolve_paths(scope="project")
            # `--scope project` sets omh_home from the literal cwd, so without
            # the walk a plan recorded from a subdirectory would land in
            # nested/deep/.omh instead of the repository's own store.
            self.assertEqual(
                project_artifact_dir(paths, "plans", cwd=nested), root / ".omh" / "plans"
            )

    def test_constructing_paths_directly_counts_as_naming_the_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            # Call sites that build OmhPaths by hand always pass a home, so the
            # default must not silently divert them into a repository.
            paths = OmhPaths(omh_home=root / "direct", hermes_home=root / ".hermes")
            self.assertEqual(project_artifact_dir(paths, "plans", cwd=root), root / "direct" / "plans")

    def test_outside_a_repository_artifacts_fall_back_to_the_user_store(self) -> None:
        # Patched rather than inferred: whether a temp dir sits under a
        # repository is machine-dependent, and recomputing the expected value
        # from find_project_root would just restate the implementation.
        paths = resolve_paths()
        with patch("omh.system.paths.find_project_root", return_value=None):
            self.assertEqual(project_artifact_dir(paths, "plans"), paths.omh_home / "plans")


class ProjectIdentityTests(unittest.TestCase):
    def test_identity_falls_back_to_default_outside_a_repository(self) -> None:
        with patch("omh.system.paths.find_project_root", return_value=None):
            self.assertEqual(project_identity(), "default")

    def test_identity_is_the_repository_directory_name(self) -> None:
        with TemporaryDirectory() as tmp:
            named = Path(tmp).resolve() / "acme-service"
            named.mkdir()
            self.assertEqual(project_identity(_repo(named)), "acme-service")

    def test_identity_is_stable_across_calls_in_one_repository(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            nested = root / "src"
            nested.mkdir()
            self.assertEqual(project_identity(root), project_identity(nested))


class StoreIgnoreTests(unittest.TestCase):
    """A repo-local store must not turn up in the user's `git status`."""

    def test_the_store_ignores_itself(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            ensure_project_store_ignored(root / ".omh" / "plans")
            self.assertEqual((root / ".omh" / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_an_existing_ignore_file_is_left_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            marker = root / ".omh" / ".gitignore"
            marker.parent.mkdir(parents=True)
            marker.write_text("!keep-me\n", encoding="utf-8")
            ensure_project_store_ignored(marker.parent / "plans")
            self.assertEqual(marker.read_text(encoding="utf-8"), "!keep-me\n")

    def test_a_store_outside_a_repository_is_left_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            # The user-scope ~/.omh is not version controlled, so an ignore file
            # there would be litter rather than protection.
            store = Path(tmp).resolve() / ".omh" / "plans"
            with patch("omh.system.paths.find_project_root", return_value=None):
                ensure_project_store_ignored(store)
            self.assertEqual(list(Path(tmp).rglob(".gitignore")), [])

    def test_a_directory_outside_a_store_is_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            ensure_project_store_ignored(root / "somewhere" / "plans")
            self.assertEqual(list(root.rglob(".gitignore")), [])

    def test_no_temp_file_survives_the_write(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            ensure_project_store_ignored(root / ".omh" / "plans")
            self.assertEqual(list((root / ".omh").glob("*.tmp")), [])

    def test_recording_a_plan_writes_the_ignore_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp).resolve())
            paths = resolve_paths(root / ".omh", root / ".hermes")
            write_hermes_plan(paths, build_hermes_plan_payload("build a coding delegation flow"))
            self.assertEqual((paths.omh_home / ".gitignore").read_text(encoding="utf-8"), "*\n")


class HandoffScopeTests(unittest.TestCase):
    """`scope.ref` shipped as the literal "default" in every pack ever built."""

    def _pack(self) -> dict:
        return build_plan_handoff_context_pack(
            {"path": "/tmp/plan.md", "status": "accepted", "schema_version": "hermes_plan/v1", "sha256": "abc"}
        )

    def test_scope_names_the_repository_rather_than_default(self) -> None:
        pack = self._pack()
        # The suite runs inside this repository, so a resolved identity is
        # available and "default" would mean the resolver never fired.
        self.assertEqual(pack["scope"]["kind"], "project")
        self.assertNotEqual(pack["scope"]["ref"], "default")
        self.assertEqual(pack["scope"]["ref"], project_identity())

    def test_included_context_carries_the_same_scope(self) -> None:
        pack = self._pack()
        self.assertEqual(pack["included_context"][0]["scope"], pack["scope"])

    def test_each_pack_owns_its_scope_dict(self) -> None:
        pack = self._pack()
        pack["scope"]["ref"] = "mutated"
        # Sharing one dict between the pack and its rows would let a caller
        # editing the top-level scope silently rewrite every included row.
        self.assertNotEqual(pack["included_context"][0]["scope"]["ref"], "mutated")


class PlanWriteTests(unittest.TestCase):
    def test_a_recorded_plan_never_touches_the_hermes_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            paths = resolve_paths(root / ".omh", root / ".hermes")
            payload = build_hermes_plan_payload("build a coding delegation flow")

            artifact = write_hermes_plan(paths, payload)

            plan_path = Path(str(artifact["path"]))
            self.assertEqual(plan_path.parent, paths.omh_home / "plans")
            self.assertTrue(plan_path.exists())
            self.assertFalse((paths.hermes_home / "plans").exists())
            self.assertFalse((paths.hermes_home / "context").exists())

    def test_a_blocked_plan_puts_its_context_in_the_same_store(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            paths = resolve_paths(root / ".omh", root / ".hermes")
            payload = build_hermes_plan_payload("help")

            artifact = write_hermes_plan(paths, payload)

            self.assertEqual(payload["plan"]["status"], "blocked")
            context_path = Path(str(artifact["context_path"]))
            self.assertEqual(context_path.parent, paths.omh_home / "plan-context")
            self.assertTrue(context_path.exists())
            self.assertFalse((paths.hermes_home / "context").exists())


if __name__ == "__main__":
    unittest.main()
