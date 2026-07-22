from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli

from omh.commands.main import build_parser
from omh.paths import expand_path, resolve_paths
from omh.coding.worktree_creator import _append_worktree_record, _observation_record


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


if __name__ == "__main__":
    unittest.main()
