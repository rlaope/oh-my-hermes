from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class WorktreeCreatorTests(unittest.TestCase):
    def test_worktree_prepare_dry_run_does_not_create_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            target = root / "worktrees" / "dry"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "risky refactor",
                    "--path",
                    str(target),
                    "--dry-run",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)["worktree"]
            self.assertEqual(payload["schema_version"], "omh_worktree_prepare/v1")
            self.assertEqual(payload["status"], "dry_run")
            self.assertFalse(payload["observed"])
            self.assertFalse(target.exists())
            self.assertIn("git", payload["command"][0])
            self.assertEqual(payload["runtime_observation_followup"]["event_type"], "worktree_creation")

    def test_worktree_prepare_creates_git_worktree_and_records_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            target = root / "worktrees" / "risky"
            home = root / ".omh"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(home),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "risky refactor",
                    "--branch",
                    "omh/risky-refactor-test",
                    "--path",
                    str(target),
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0, stdout)
            payload = json.loads(stdout)["worktree"]
            self.assertEqual(payload["status"], "created")
            self.assertTrue(payload["observed"])
            self.assertTrue(payload["created"])
            self.assertTrue((target / ".git").exists() or (target / ".git").is_file())
            self.assertIn(f"git-worktree:{target.resolve()}", payload["evidence_refs"])
            self.assertIn("not executor dispatch", payload["claim_boundary"])
            self.assertIn("omh runtime observe", payload["runtime_observation_followup"]["record_with"])
            worktree_list = _git(repo, "worktree", "list", "--porcelain")
            self.assertIn(str(target), worktree_list.stdout)

            status, stdout, stderr = run_cli(["--omh-home", str(home), "worktree", "list", "--limit", "1"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            records = json.loads(stdout)["records"]
            self.assertEqual(records[0]["schema_version"], "omh_worktree_observation/v1")
            self.assertTrue(records[0]["created"])

    def test_worktree_prepare_blocks_dirty_source_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "risky refactor",
                    "--path",
                    str(root / "worktrees" / "blocked"),
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            payload = json.loads(stdout)["worktree"]
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "source_dirty")
            self.assertFalse(payload["created"])

    def test_worktree_bind_builds_codex_launch_recipe_for_observed_worktree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            target = root / "worktrees" / "codex-bind"
            home = root / ".omh"

            prepare_status, _, prepare_stderr = run_cli(
                [
                    "--omh-home",
                    str(home),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "codex binding",
                    "--branch",
                    "omh/codex-binding-test",
                    "--path",
                    str(target),
                ]
            )
            self.assertEqual(prepare_stderr, "")
            self.assertEqual(prepare_status, 0)

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
            self.assertTrue(any(str(target.resolve()) in str(command) for command in commands))
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
            self.assertIn("not proof of execution", payload["launch"]["claim_boundary"])

    def test_worktree_bind_runtime_profile_adds_runtime_observation_recipe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            target = root / "worktrees" / "runtime-bind"
            home = root / ".omh"

            prepare_status, _, prepare_stderr = run_cli(
                [
                    "--omh-home",
                    str(home),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "runtime binding",
                    "--branch",
                    "omh/runtime-binding-test",
                    "--path",
                    str(target),
                ]
            )
            self.assertEqual(prepare_stderr, "")
            self.assertEqual(prepare_status, 0)

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


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    (path / "README.md").write_text("# temp\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "-c", "user.name=OMH Test", "-c", "user.email=omh@example.com", "commit", "-m", "init")
    return path


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed


if __name__ == "__main__":
    unittest.main()
