from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import dispatch_fanout, verify_goal_matches_contract  # noqa: E402
from omh.runtime.artifacts import show_run  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "split the sample feature across agents"
_UNITS = [
    {"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]},
    {"unit_id": "docs", "title": "Docs work", "owner": "claude-code", "file_scope": ["docs/"]},
    {"unit_id": "tests", "title": "Test work", "owner": "codex", "file_scope": ["tests/"], "depends_on": ["core"]},
]


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True)


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-q", "-m", "init")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _agent_runner(*, fail_units: set[str] | None = None, timeout_units: set[str] | None = None):
    """Route git commands to the real subprocess; fake agent CLI spawns."""

    spawned: list[list[str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        spawned.append(list(argv))
        prompt = " ".join(argv)
        for unit_id in timeout_units or set():
            if f"Work unit:" in prompt and unit_id in prompt:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        for unit_id in fail_units or set():
            if unit_id in prompt:
                return _FakeCompleted(1, f"unit {unit_id} failed")
        return _FakeCompleted(0, "done")

    runner.spawned = spawned
    return runner


def _ready(paths, profile, **kwargs):
    return {"status": "ready", "profile": profile}


class FanoutDispatchEngineTests(unittest.TestCase):
    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
        return paths, repo, sha, contract

    def test_happy_path_dispatches_units_and_records_observed_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "completed")
            self.assertEqual(by_unit["docs"]["status"], "completed")
            self.assertEqual(by_unit["tests"]["status"], "completed")
            self.assertEqual(summary["merge_ready_units"], ["core", "docs", "tests"])
            self.assertFalse(summary["auto_merge"])
            self.assertIn("exited 0", summary["dependency_bar"])
            # observed evidence per unit run
            shown = show_run(paths, by_unit["core"]["run_ref"])
            events = [e["event"] for e in shown["journal_events"]]
            self.assertIn("executor_dispatch_observed", events)
            self.assertIn("executor_result_observed", events)
            # worktrees created per unit, never merged
            self.assertTrue((repo.parent / "repo-fanout-core").exists())
            self.assertNotIn(["git", "merge"], runner.spawned)

    def test_dependent_unit_waits_and_failure_blocks_only_dependents(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(fail_units={"Core"}),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "failed")
            self.assertEqual(by_unit["tests"]["status"], "blocked_by_dependency")
            self.assertEqual(by_unit["docs"]["status"], "completed")
            self.assertEqual(summary["merge_ready_units"], ["docs"])

    def test_timeout_records_failed_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                timeout=5,
                runner=_agent_runner(timeout_units={"Docs"}),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["status"], "failed")
            self.assertEqual(by_unit["docs"]["exit_code"], 124)

    def test_readiness_refusal_skips_unit_without_fabricating_a_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            def not_ready(paths_, profile, **kwargs):
                return {"status": "missing", "profile": profile}

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=not_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "executor_not_ready")
            self.assertFalse((paths.runtime_runs_dir / by_unit["core"]["run_ref"]).exists())

    def test_dry_run_plans_without_spawning_or_creating_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                dry_run=True,
                runner=runner,
                readiness=_ready,
            )

            self.assertTrue(all(entry["status"] == "dry_run_planned" for entry in summary["units"]))
            self.assertEqual(runner.spawned, [])
            self.assertFalse(paths.runtime_runs_dir.exists())
            self.assertFalse((repo.parent / "repo-fanout-core").exists())

    def test_resume_skips_completed_units(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            first = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )
            self.assertEqual(len({e["unit_id"] for e in first["units"] if e["status"] == "completed"}), 3)

            rerun_runner = _agent_runner()
            second = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=rerun_runner,
                readiness=_ready,
            )

            self.assertTrue(all(entry["status"] == "already_completed" for entry in second["units"]))
            self.assertEqual(rerun_runner.spawned, [])

    def test_argv_templates_for_both_spawnable_profiles(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
            )

            heads = {tuple(argv[:2]) for argv in runner.spawned}
            self.assertIn(("codex", "exec"), heads)
            claude_argv = next(argv for argv in runner.spawned if argv[0] == "claude")
            self.assertEqual(claude_argv[1], "-p")
            self.assertEqual(claude_argv[3:], ["--permission-mode", "acceptEdits"])
            self.assertIn("Work unit:", claude_argv[2])

    def test_missing_cli_maps_to_exit_127(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                raise FileNotFoundError(argv[0])

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "failed")
            self.assertEqual(by_unit["core"]["exit_code"], 127)

    def test_unsupported_profile_falls_back_and_blocks_dependents_with_pointer(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            units = [
                {"unit_id": "manual", "owner": "hermes", "file_scope": ["notes/"]},
                {"unit_id": "auto", "owner": "codex", "file_scope": ["src/"], "depends_on": ["manual"]},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["manual"]["status"], "unsupported_for_local_dispatch")
            self.assertIn("prepared prompt", by_unit["manual"]["fallback"])
            self.assertEqual(by_unit["auto"]["status"], "blocked_by_dependency")
            self.assertEqual(by_unit["auto"]["blocked_on"], ["manual"])

    def test_partial_redispatch_consumes_previously_completed_dependency(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            (repo.parent / "repo-fanout-tests").exists()
            second = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["tests"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(by_unit["core"]["status"], "already_completed")
            self.assertEqual(by_unit["tests"]["status"], "completed")
            self.assertEqual(by_unit["docs"]["status"], "not_selected")

    def test_goal_divergence_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            with self.assertRaises(ValueError):
                verify_goal_matches_contract(contract, "a different goal entirely")
            with self.assertRaises(ValueError):
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text="a different goal entirely",
                    repo_root=repo,
                    base_sha=sha,
                    runner=_agent_runner(),
                    readiness=_ready,
                )

    def test_existing_worktree_path_errors_instead_of_reuse(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            (repo.parent / "repo-fanout-core").mkdir()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "worktree_failed")
            self.assertIn("already exists", by_unit["core"]["reason"])


class FanoutDispatchCliTests(unittest.TestCase):
    def test_cli_dry_run_and_show_join(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            units_path = root / "units.json"
            units_path.write_text(json.dumps(_UNITS), encoding="utf-8")
            goal_path = root / "goal.txt"
            goal_path.write_text(_GOAL, encoding="utf-8")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "prepare", "--goal", *_GOAL.split(), "--units", str(units_path), "--record"]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(goal_path),
                    "--repo-root",
                    str(repo),
                    "--dry-run",
                ]
            )
            self.assertEqual(status, 0, stderr)
            summary = json.loads(stdout)
            self.assertEqual(summary["schema_version"], "fanout_dispatch_summary/v1")
            self.assertTrue(summary["dry_run"])
            self.assertFalse(summary["auto_merge"])
            for entry in summary["units"]:
                self.assertIn(entry["status"], {"dry_run_planned", "executor_not_ready", "unsupported_for_local_dispatch"})

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "show", fanout_id])
            self.assertEqual(status, 0, stderr)
            board = json.loads(stdout)
            for unit in board["units"].values():
                self.assertEqual(unit["observed_run_status"], "not_observed")

    def test_cli_refuses_diverged_goal_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            units_path = root / "units.json"
            units_path.write_text(json.dumps(_UNITS), encoding="utf-8")
            wrong_goal = root / "wrong.txt"
            wrong_goal.write_text("not the frozen goal", encoding="utf-8")

            status, stdout, _ = run_cli(
                base + ["coding", "fanout", "prepare", "--goal", *_GOAL.split(), "--units", str(units_path), "--record"]
            )
            fanout_id = json.loads(stdout)["fanout_id"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(wrong_goal),
                    "--repo-root",
                    str(repo),
                    "--dry-run",
                ]
            )
            self.assertNotEqual(status, 0)
            self.assertIn("does not match the digest", stderr)


if __name__ == "__main__":
    unittest.main()
