from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli

from omh.commands.main import build_parser
from omh.paths import expand_path, resolve_paths
from omh.coding.worktree_creator import (
    _append_worktree_record,
    _observation_record,
    ensure_fanout_unit_worktree,
)
from omh.system.paths import OmhPaths
from omh.workflows.observation_journal import CANONICAL_OBSERVATION_EVENTS


def _seed_observed_worktree(home: Path, target: Path, *, branch: str = "omh/seeded") -> None:
    """Record an observed worktree in the local ledger without OMH creating it.

    Worktree creation is deferred to native Hermes/Git tooling; tests seed the
    observation ledger directly through the retained observation helpers so the
    binding and listing surfaces have observed evidence to read.
    """

    target.mkdir(parents=True, exist_ok=True)
    resolved = str(expand_path(target))
    record = _observation_record(
        {
            "status": "created",
            "observed": True,
            "created": True,
            "repo_root": str(expand_path(home)),
            "branch": branch,
            "worktree_path": resolved,
            "from_ref": "HEAD",
            "evidence_refs": [f"git-worktree:{resolved}", f"git-branch:{branch}"],
        }
    )
    _append_worktree_record(resolve_paths(str(home)), record)


class WorktreeParserTests(unittest.TestCase):
    def test_worktree_prepare_subcommand_is_absent(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["worktree", "prepare", "--repo", "."])

    def test_worktree_list_and_bind_subcommands_remain(self) -> None:
        parser = build_parser()
        list_args = parser.parse_args(["worktree", "list"])
        self.assertEqual(list_args.worktree_command, "list")
        bind_args = parser.parse_args(
            ["worktree", "bind", "--path", ".worktrees/x", "--executor", "codex"]
        )
        self.assertEqual(bind_args.worktree_command, "bind")

    def test_feature_and_verify_subcommands_are_available(self) -> None:
        parser = build_parser()
        feature = parser.parse_args(["worktree", "feature", "--seed", "ubuntu-ab12", "--feature", "memory-router"])
        verify = parser.parse_args(["worktree", "verify", "--seed", "ubuntu-ab12"])
        self.assertEqual(feature.worktree_command, "feature")
        self.assertEqual(verify.worktree_command, "verify")

    def test_prepare_git_worktree_is_not_importable(self) -> None:
        import omh.worktree_creator as worktree_creator

        self.assertFalse(hasattr(worktree_creator, "prepare_git_worktree"))

    def test_no_source_module_imports_prepare_git_worktree(self) -> None:
        src_root = Path(__file__).resolve().parents[1] / "src"
        offenders = [
            str(path.relative_to(src_root))
            for path in src_root.rglob("*.py")
            if "prepare_git_worktree" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


class WorktreeObservationTests(unittest.TestCase):
    def test_worktree_list_returns_observed_records(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / ".omh"
            target = root / "worktrees" / "listed"
            _seed_observed_worktree(home, target)

            status, stdout, stderr = run_cli(["--omh-home", str(home), "worktree", "list", "--limit", "1"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_worktree_observations/v1")
            records = payload["records"]
            self.assertEqual(records[0]["schema_version"], "omh_worktree_observation/v1")
            self.assertTrue(records[0]["created"])
            self.assertEqual(records[0]["worktree_path"], str(target.resolve()))

    def test_worktree_bind_builds_codex_launch_recipe_for_observed_worktree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / ".omh"
            target = root / "worktrees" / "codex-bind"
            _seed_observed_worktree(home, target, branch="omh/codex-binding-test")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(home),
                    "worktree",
                    "bind",
                    "--path",
                    str(target),
                    "--executor",
                    "codex",
                    "--session",
                    "session-1",
                    "--prompt-ref",
                    "handoff:abc",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)["binding"]
            self.assertEqual(payload["schema_version"], "worktree_executor_binding/v1")
            self.assertEqual(payload["status"], "ready_observed_worktree")
            self.assertEqual(payload["executor"]["profile"], "codex")
            self.assertTrue(payload["worktree"]["observed_in_omh_ledger"])
            self.assertEqual(payload["launch"]["resolved_workspace_path"], str(target.resolve()))
            self.assertEqual(payload["launch"]["preferred_command_template_id"], "codex_interactive_workspace")
            isolation_plan = payload["launch"]["workspace_isolation"]["plan"]
            self.assertEqual(isolation_plan["schema_version"], "worktree_session_isolation/v1")
            self.assertIn("workspace_policy", isolation_plan)
            commands = payload["launch"]["resolved_command_templates"]
            self.assertTrue(any(command.get("argv_template", [None, None])[1] == "--cd" for command in commands))
            # Check the raw argv/shell strings directly rather than str(command): stringifying
            # the dict repr-escapes embedded backslashes (doubling them on Windows paths), which
            # would never match the unescaped str(target.resolve()) on that platform.
            command_values = [
                str(value)
                for command in commands
                for value in [*command.get("argv_template", []), command.get("shell_command_template", "")]
            ]
            self.assertTrue(any(str(target.resolve()) in value for value in command_values))
            actions = {action["id"]: action for action in payload["wrapper_actions"]}
            self.assertTrue(actions["open_executor_session"]["enabled"])
            self.assertEqual(actions["open_executor_session"]["launch_command_template_id"], "codex_interactive_workspace")
            self.assertTrue(actions["attach_executor_session"]["enabled"])
            self.assertIn("omh chat session open-executor session-1 --observed", actions["record_executor_opened"]["backend_command"])
            self.assertEqual(actions["open_executor_session"]["prompt_ref"], "handoff:abc")
            self.assertIn("executor_dispatch", payload["not_evidence_until_observed"])

    def test_worktree_bind_blocks_missing_path_without_claiming_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "missing" / "worktree"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "worktree",
                    "bind",
                    "--path",
                    str(target),
                    "--executor",
                    "claude-code",
                    "--session",
                    "session-2",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            payload = json.loads(stdout)["binding"]
            self.assertEqual(payload["status"], "blocked_missing_worktree")
            self.assertFalse(payload["worktree"]["exists"])
            self.assertFalse(payload["wrapper_actions"][0]["enabled"])
            self.assertEqual(payload["next_action"], "prepare_worktree_before_opening_executor")
            self.assertIn("git worktree add", payload["wrapper_actions"][0]["disabled_reason"])
            self.assertIn("not proof of execution", payload["launch"]["claim_boundary"])

    def test_worktree_bind_runtime_profile_adds_runtime_observation_recipe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / ".omh"
            target = root / "worktrees" / "runtime-bind"
            _seed_observed_worktree(home, target, branch="omh/runtime-binding-test")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(home),
                    "worktree",
                    "bind",
                    "--path",
                    str(target),
                    "--executor",
                    "omx-runtime",
                    "--session",
                    "session-3",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)["binding"]
            self.assertEqual(payload["executor"]["profile"], "omx-runtime")
            self.assertFalse(payload["executor"]["terminal_launch_available"])
            self.assertEqual(payload["session_binding"]["runtime_profile"], "omx-runtime")
            actions = {action["id"]: action for action in payload["wrapper_actions"]}
            self.assertIn("record_worktree_runtime_observation", actions)
            self.assertIn("omh runtime observe --session session-3", actions["record_worktree_runtime_observation"]["backend_command"])
            self.assertIn("--event worktree_creation", actions["record_worktree_runtime_observation"]["backend_command"])
            self.assertIn("prompt_only", str(payload["launch"]["resolved_command_templates"]))


def _git(repo: Path, *argv: str) -> str:
    completed = subprocess.run(
        ["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD")


def _journal_events(paths: OmhPaths) -> list[dict]:
    path = paths.runtime_journal_events_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class FanoutUnitWorktreeInvariantTests(unittest.TestCase):
    """The opt-in fanout worktree path must fail closed on drifted or colliding state.

    A unit worktree is the isolation guarantee the fanout contract sells. Adding
    one from a base the caller no longer describes, or onto a branch some other
    worktree already holds, silently breaks that guarantee, so every refusal
    here is checked BEFORE `git worktree add` runs and is recorded as an
    observation rather than raised past the dispatcher.
    """

    def _paths(self, root: Path) -> OmhPaths:
        return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")

    def test_happy_add_creates_worktree_and_records_observation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            paths = self._paths(root)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="main",
                run_ref="run-core",
            )

            self.assertEqual(result["status"], "created")
            self.assertTrue(result["created"])
            self.assertTrue(Path(result["worktree_path"]).is_dir())
            self.assertEqual(_git(repo, "rev-parse", "agent/core"), sha)
            cleanup = [event for event in _journal_events(paths) if event["event"] == "worktree_cleanup"]
            self.assertEqual(cleanup, [])

    def test_happy_add_leaves_an_uncommitted_source_file_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            dirty = repo / "uncommitted.txt"
            dirty.write_text("work in progress\n", encoding="utf-8")
            paths = self._paths(root)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="main",
            )

            self.assertTrue(result["created"])
            self.assertEqual(dirty.read_text(encoding="utf-8"), "work in progress\n")
            self.assertIn("uncommitted.txt", _git(repo, "status", "--porcelain"))

    def test_base_sha_that_no_longer_matches_the_source_ref_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            (repo / "seed.txt").write_text("moved on\n", encoding="utf-8")
            _git(repo, "add", "seed.txt")
            _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "drift")
            paths = self._paths(root)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="main",
                run_ref="run-core",
            )

            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["created"])
            self.assertEqual(result["refusal"], "base_sha_drifted_from_source_ref")
            self.assertIn("main", result["reason"])
            self.assertFalse((repo.parent / "repo-fanout-core").exists())
            cleanup = [event for event in _journal_events(paths) if event["event"] == "worktree_cleanup"]
            self.assertEqual(len(cleanup), 1)
            self.assertIn("base_sha_drifted_from_source_ref", cleanup[0]["summary"])

    def test_unresolvable_source_ref_is_refused_before_worktree_add(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            paths = self._paths(root)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="no-such-branch",
            )

            self.assertEqual(result["refusal"], "source_ref_unresolvable")
            self.assertFalse((repo.parent / "repo-fanout-core").exists())

    def test_existing_branch_is_refused_before_worktree_add(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            _git(repo, "branch", "agent/core")
            paths = self._paths(root)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="main",
            )

            self.assertEqual(result["refusal"], "branch_already_exists")
            self.assertIn("agent/core", result["reason"])
            self.assertFalse((repo.parent / "repo-fanout-core").exists())

    def test_branch_checked_out_in_another_registered_worktree_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            paths = self._paths(root)
            # `main` is checked out in the primary worktree, so a unit that asks
            # for it collides with a worktree git already registers.
            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="main",
                base_sha=sha,
                source_ref="main",
            )

            self.assertEqual(result["refusal"], "branch_checked_out_in_worktree")
            self.assertIn("main", result["reason"])
            self.assertFalse((repo.parent / "repo-fanout-core").exists())

    def test_malformed_branch_name_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            paths = self._paths(root)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent//bad branch~1",
                base_sha=sha,
                source_ref="main",
            )

            self.assertEqual(result["refusal"], "branch_name_malformed")
            self.assertFalse((repo.parent / "repo-fanout-core").exists())

    def test_partial_failure_appends_a_cleanup_receipt_naming_what_was_left(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            paths = self._paths(root)

            def runner(argv, **kwargs):
                if argv[:3] == ["git", "worktree", "add"]:
                    completed = subprocess.CompletedProcess(argv, 128, "", "fatal: could not create leading directories")
                    return completed
                return subprocess.run(argv, **kwargs)

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="main",
                run_ref="run-core",
                runner=runner,
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["refusal"], "worktree_add_failed")
            cleanup = [event for event in _journal_events(paths) if event["event"] == "worktree_cleanup"]
            self.assertEqual(len(cleanup), 1)
            self.assertIn("worktree_add_failed", cleanup[0]["summary"])
            self.assertIn(str(repo.parent / "repo-fanout-core"), cleanup[0]["summary"])

    def test_existing_worktree_path_is_never_auto_deleted(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, sha = _make_repo(root)
            paths = self._paths(root)
            squatter = repo.parent / "repo-fanout-core"
            squatter.mkdir()
            (squatter / "salvage.txt").write_text("unmerged work\n", encoding="utf-8")

            result = ensure_fanout_unit_worktree(
                paths,
                repo_root=repo,
                unit_id="core",
                branch="agent/core",
                base_sha=sha,
                source_ref="main",
            )

            self.assertEqual(result["refusal"], "worktree_path_already_exists")
            self.assertIn("already exists", result["reason"])
            self.assertEqual((squatter / "salvage.txt").read_text(encoding="utf-8"), "unmerged work\n")

    def test_worktree_cleanup_is_a_canonical_observation_event(self) -> None:
        self.assertIn("worktree_cleanup", CANONICAL_OBSERVATION_EVENTS)


if __name__ == "__main__":
    unittest.main()
