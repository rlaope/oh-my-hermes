"""Real CLI coverage for the sanctioned Hermes paired-run adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package
from _paired_run_local_support import FAKE_HERMES as _FAKE_HERMES
from _paired_run_local_support import git as _git

load_local_package()

from omh.quality.paired_run_decision import build_paired_run_decision  # noqa: E402
from omh.quality.paired_run_model import (  # noqa: E402
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)

class PairedRunLocalRunnerTests(unittest.TestCase):
    def test_preflight_refuses_digest_and_executor_before_any_child(self) -> None:
        with TemporaryDirectory(prefix="omh-paired-refuse-") as raw:
            root = Path(raw)
            task_content = "paired task\n"
            task_file = root / "task.txt"
            task_file.write_bytes(task_content.encode("utf-8"))
            actual_digest = hashlib.sha256(
                task_content.encode("utf-8")
            ).hexdigest()
            hermes = root / "hermes.py"
            hermes.write_text(
                textwrap.dedent(_FAKE_HERMES).lstrip(),
                encoding="utf-8",
            )
            hermes.chmod(0o755)

            for name, executor, digest, expected in (
                ("digest", "hermes", "a" * 64, "digest does not match"),
                (
                    "executor",
                    "codex",
                    actual_digest,
                    "no sanctioned paired-run adapter",
                ),
            ):
                with self.subTest(name=name):
                    task = TaskSpec("task-a", "criteria-a", digest)
                    request = PairedRunRequest(
                        f"decision-{name}",
                        None,
                        ArmSpec("baseline", executor, "model-base", ()),
                        ArmSpec("variant", executor, "model-variant", ()),
                        (task,),
                        2,
                        30,
                        "a" * 40,
                        "2026-09-04T00:00:00Z",
                        tuple(
                            RunResultInput(
                                task.task_id,
                                arm,
                                InfrastructureStatus.NOT_OBSERVED,
                                BehaviorVerdict.NOT_OBSERVED,
                                None,
                            )
                            for arm in ArmRole
                        ),
                    )
                    decision = root / f"{name}.json"
                    decision.write_text(
                        build_paired_run_decision(request).to_json(),
                        encoding="utf-8",
                    )
                    status, stdout, stderr = run_cli(
                        [
                            "--omh-home",
                            str(root / ".omh"),
                            "coding",
                            "paired-run",
                            "dispatch",
                            "--decision",
                            str(decision),
                            "--confirm-dispatch",
                            "--task-file",
                            f"task-a={task_file}",
                            "--repo",
                            str(root / "missing-repo"),
                            "--provider",
                            "fake-provider",
                            "--hermes",
                            str(hermes),
                        ],
                        output_json=False,
                    )

                    self.assertEqual((status, stdout), (2, ""))
                    self.assertIn(expected, stderr)
                    self.assertFalse((root / "calls.jsonl").exists())

    def test_confirmed_cli_runs_hermes_cells_with_receipts_and_cleanup(self) -> None:
        with TemporaryDirectory(prefix="omh-paired-cli-") as raw:
            root = Path(raw)
            omh_home = root / ".omh"
            repo = root / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
            _git(repo, "add", "seed.txt")
            _git(
                repo,
                "-c",
                "user.name=tests",
                "-c",
                "user.email=tests@example.test",
                "commit",
                "-qm",
                "seed",
            )
            revision = _git(repo, "rev-parse", "HEAD")
            task_content = "PRIVATE_PAIRED_TASK_1295\n"
            task_file = root / "task-a.txt"
            task_file.write_bytes(task_content.encode("utf-8"))
            digest = hashlib.sha256(task_content.encode("utf-8")).hexdigest()
            task = TaskSpec("task-a", "criteria-a", digest)
            request = PairedRunRequest(
                "decision-local-cli",
                None,
                ArmSpec("baseline", "hermes", "model-base", ()),
                ArmSpec("variant", "hermes", "model-variant", ("code-review",)),
                (task,),
                2,
                30,
                revision,
                "2026-09-04T00:00:00Z",
                tuple(
                    RunResultInput(
                        task.task_id,
                        arm,
                        InfrastructureStatus.NOT_OBSERVED,
                        BehaviorVerdict.NOT_OBSERVED,
                        None,
                    )
                    for arm in ArmRole
                ),
            )
            decision = root / "decision.json"
            decision.write_text(
                build_paired_run_decision(request).to_json(),
                encoding="utf-8",
            )
            hermes = root / "hermes.py"
            hermes.write_text(
                textwrap.dedent(_FAKE_HERMES).lstrip(),
                encoding="utf-8",
            )
            hermes.chmod(0o755)

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "coding",
                    "paired-run",
                    "dispatch",
                    "--decision",
                    str(decision),
                    "--confirm-dispatch",
                    "--task-file",
                    f"task-a={task_file}",
                    "--repo",
                    str(repo),
                    "--provider",
                    "fake-provider",
                    "--hermes",
                    str(hermes),
                    "--timeout",
                    "5",
                    "--json",
                ],
                output_json=False,
            )

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            execution = payload["execution"]
            self.assertTrue(execution["fan_in_ready"])
            self.assertEqual(len(execution["cells"]), 2)
            self.assertTrue(
                all(cell["authenticated"] for cell in execution["cells"])
            )
            self.assertTrue(
                all(cell["cleanup_succeeded"] for cell in execution["cells"])
            )
            self.assertFalse(
                any(repo.parent.glob(f"{repo.name}-paired-run-*"))
            )
            health_status, health_stdout, health_stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "health-summary",
                    "--run-id",
                    "decision-local-cli",
                    "--json",
                ],
                output_json=False,
            )
            self.assertEqual(health_status, 0, health_stderr)
            health = json.loads(health_stdout)
            critical = health["critical_path_health"]
            self.assertEqual(health["owner_attribution"]["owner"], "paired-run")
            self.assertIsNotNone(critical["metrics"])
            self.assertEqual(critical["metrics"]["peak_concurrency"], 2)
            self.assertEqual(
                {row["task_id"] for row in critical["task_revisions"]},
                {
                    cell["workspace_id"]
                    for cell in execution["cells"]
                }
                | {
                    f"{cell['workspace_id']}:cleanup"
                    for cell in execution["cells"]
                },
            )
            self.assertEqual(critical["privacy"], "metadata_only")
            persisted = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in omh_home.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(task_content.strip(), stdout)
            self.assertNotIn(task_content.strip(), persisted)
            calls = [
                json.loads(line)
                for line in (root / "calls.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            cell_calls = [call for call in calls if call["prompt"] == task_content]
            self.assertEqual(len(cell_calls), 2)
            self.assertEqual(len(calls), 4, "one untimed warm-up chat per arm, then the cells")
            homes = execution["arm_homes"]
            self.assertEqual(homes["baseline"]["arm_setup"]["omh_plugin"], False)
            self.assertEqual(homes["variant"]["arm_setup"]["omh_plugin"], True)
            self.assertTrue(homes["baseline"]["stopped"] and homes["variant"]["stopped"])
            for call in calls:
                self.assertFalse(Path(call["hermes_home"]).exists(), "arm homes are removed")


if __name__ == "__main__":
    unittest.main()
