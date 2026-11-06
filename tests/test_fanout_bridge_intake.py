"""Regression boundaries for executor runtime state and fanout intake."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout_dispatch import (  # noqa: E402
    _observed_clean_producer_head,
    _verification_worktree_revision,
    dispatch_fanout,
)
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402
from _fanout_interrupt_flag import InterruptFlagIsolatedTestCase  # noqa: E402
from test_fanout_dispatch import (  # noqa: E402
    _agent_runner, _git, _make_repo, _prompted_sidecar, _ready,
)


class ProducerRuntimeStateTests(unittest.TestCase):
    def test_untracked_executor_runtime_state_does_not_hide_committed_head(self):
        with TemporaryDirectory() as tmp:
            repo, sha = _make_repo(Path(tmp))
            for root in (".omx", ".omc"):
                (repo / root / "state").mkdir(parents=True)
                (repo / root / "state" / "run.json").write_text("{}", encoding="utf-8")
                # Git quotes non-ASCII paths; the closed root still applies.
                (repo / root / "state" / "café.json").write_text("{}", encoding="utf-8")
            self.assertEqual(_observed_clean_producer_head(subprocess.run, repo), sha)
            # A check may read runtime state: it must not reuse a HEAD-only key.
            self.assertIsNone(_verification_worktree_revision(subprocess.run, repo))

    def test_untracked_product_files_and_root_prefixes_still_refuse_intake(self):
        for filename in ("output.txt", ".omxfoo/state.json", ".omc-other/state.json", ".omx", ".omc"):
            with self.subTest(filename=filename), TemporaryDirectory() as tmp:
                repo, _ = _make_repo(Path(tmp))
                target = repo / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("uncommitted", encoding="utf-8")
                self.assertIsNone(_observed_clean_producer_head(subprocess.run, repo))

    def test_tracked_runtime_state_changes_still_refuse_intake(self):
        for root in (".omx", ".omc"):
            for change in ("modified", "staged", "deleted", "renamed"):
                with self.subTest(root=root, change=change), TemporaryDirectory() as tmp:
                    repo, _ = _make_repo(Path(tmp))
                    target = repo / root / "tracked.json"
                    target.parent.mkdir()
                    target.write_text("base", encoding="utf-8")
                    _git(repo, "add", root)
                    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "track state")
                    if change == "deleted":
                        target.unlink()
                    elif change == "renamed":
                        _git(repo, "mv", str(target.relative_to(repo)), f"{root}/renamed.json")
                    else:
                        target.write_text("changed", encoding="utf-8")
                        if change == "staged":
                            _git(repo, "add", root)
                    self.assertIsNone(_observed_clean_producer_head(subprocess.run, repo))


class BridgeDispatchTests(InterruptFlagIsolatedTestCase):
    def _setup(self, tmp, owner="claude-code"):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        goal = "Exercise the executor intake bridge"
        contract = write_fanout_contract(paths, build_fanout_contract(goal, [
            {"unit_id": "bridge", "owner": owner, "file_scope": ["result.txt"]},
        ]))
        return paths, repo, sha, goal, contract

    def test_claude_template_gets_only_its_own_intake_directory(self):
        for owner in ("claude-code", "codex"):
            with self.subTest(owner=owner), TemporaryDirectory() as tmp:
                paths, repo, sha, goal, contract = self._setup(tmp, owner)
                runner = _agent_runner()
                dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                                base_sha=sha, readiness=_ready, runner=runner)
                argv = runner.spawned[0]
                if owner == "claude-code":
                    self.assertIn("--add-dir", argv)
                    self.assertEqual(argv[argv.index("--add-dir") + 1], str(_prompted_sidecar(argv).parent))
                else:
                    self.assertNotIn("--add-dir", argv)

    def test_workspace_only_stale_readiness_is_reobserved_once(self):
        for owner in ("codex", "claude-code"):
            for dry_run in (False, True):
                with self.subTest(owner=owner, dry_run=dry_run), TemporaryDirectory() as tmp:
                    paths, repo, sha, goal, contract = self._setup(tmp, owner)
                    calls = []
                    def readiness(paths_, owner_, **kwargs):
                        calls.append((owner_, kwargs))
                        if kwargs.get("force"):
                            return {"status": "ready"}
                        return {"status": "stale", "pre_handoff_readiness": {"changed_axes": ["workspace"]}}
                    runner = _agent_runner()
                    result = dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                        base_sha=sha, readiness=readiness, runner=runner, dry_run=dry_run)["units"][0]
                    self.assertEqual(result["status"], "dry_run_planned" if dry_run else "completed")
                    self.assertEqual(calls, [(owner, {}), (owner, {"force": True})])
                    self.assertEqual(result["readiness_reobserved"], "workspace")

    def test_workspace_reobservation_that_is_not_ready_keeps_repair_card(self):
        with TemporaryDirectory() as tmp:
            paths, repo, sha, goal, contract = self._setup(tmp)
            card = {"changed_axes": ["permission"], "status": "prepared_not_observed"}
            readiness = mock.Mock(side_effect=[
                {"status": "stale", "pre_handoff_readiness": {"changed_axes": ["workspace"]}},
                {"status": "stale", "repair_card": card},
            ])
            runner = _agent_runner()
            result = dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                base_sha=sha, readiness=readiness, runner=runner)["units"][0]
            self.assertEqual(result["status"], "executor_not_ready")
            self.assertEqual(result["repair_card"], card)
            self.assertEqual(result["readiness_reobserved"], "workspace")
            self.assertEqual(readiness.call_count, 2)
            self.assertEqual(runner.spawned, [])

    def test_other_stale_axes_expired_and_unbound_readiness_are_not_reobserved(self):
        for status, axes in (
            ("stale", ["tool"]), ("stale", ["permission"]), ("stale", ["profile"]),
            ("stale", ["workspace", "tool"]), ("stale", []),
            ("expired", ["workspace"]), ("unbound", ["workspace"]),
            ("stale", None),
        ):
            with self.subTest(status=status, axes=axes), TemporaryDirectory() as tmp:
                paths, repo, sha, goal, contract = self._setup(tmp)
                card = {"changed_axes": axes, "status": "prepared_not_observed"}
                probe = {"status": status, "repair_card": card}
                if axes is not None:
                    probe["pre_handoff_readiness"] = {"changed_axes": axes}
                readiness = mock.Mock(return_value=probe)
                runner = _agent_runner()
                result = dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                    base_sha=sha, readiness=readiness, runner=runner)["units"][0]
                self.assertEqual(result["status"], "executor_not_ready")
                self.assertEqual(result["repair_card"], card)
                self.assertNotIn("readiness_reobserved", result)
                self.assertEqual(readiness.call_count, 1)
                self.assertEqual(runner.spawned, [])

    def test_patched_fixture_argv_is_not_given_claude_flags(self):
        with TemporaryDirectory() as tmp:
            paths, repo, sha, goal, contract = self._setup(tmp)
            runner = _agent_runner()
            fixture = ["python", "fixture.py", "keep-exact-arguments"]
            with mock.patch("omh.coding.fanout_dispatch.build_dispatch_argv", return_value=fixture):
                dispatch_fanout(paths, contract, goal_text=goal, repo_root=repo,
                                base_sha=sha, readiness=_ready, runner=runner)
            self.assertEqual(runner.spawned, [fixture])


if __name__ == "__main__":
    unittest.main()
