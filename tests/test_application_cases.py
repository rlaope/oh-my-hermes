from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class ApplicationCaseArtifactTests(unittest.TestCase):
    def _record_case(self, omh_home: Path, skill: str, harness: str, status: str) -> dict:
        code, stdout, _ = run_cli(["--omh-home", str(omh_home), "runtime", "record", "--skill", skill, "--harness", harness, "--status", status])
        self.assertEqual(code, 0)
        run = json.loads(stdout)["run"]
        code, _, _ = run_cli(
            [
                "--omh-home",
                str(omh_home),
                "runtime",
                "delegate",
                "--run",
                run["run_id"],
                "--requested",
                "--not-observed",
                "--result",
                "not_observed",
                "--evidence-ref",
                "run.json",
            ]
        )
        self.assertEqual(code, 0)
        code, stdout, _ = run_cli(["--omh-home", str(omh_home), "runtime", "show", run["run_id"]])
        self.assertEqual(code, 0)
        return json.loads(stdout)

    def test_three_application_cases_create_runtime_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            cases = [
                self._record_case(omh_home, "oh-my-hermes", "coding-handling", "started"),
                self._record_case(omh_home, "ultragoal", "goal-execution", "started"),
                self._record_case(omh_home, "code-review", "critic", "completed"),
            ]

            for case in cases:
                self.assertEqual(case["delegation"]["result"], "not_observed")
                self.assertTrue(case["delegation"]["requested"])
                self.assertFalse(case["delegation"]["observed"])
                self.assertIn("run_recorded", {event["event"] for event in case["events"]})
                self.assertTrue((omh_home / "runtime" / "runs" / case["run"]["run_id"] / "run.json").exists())

    def test_docs_describe_artifact_backed_cases(self) -> None:
        cases = Path("docs/APPLICATION_CASES.md").read_text(encoding="utf-8")
        install = Path("docs/INSTALLATION.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("Artifact-backed verification", cases)
        self.assertIn("omh runtime show", cases)
        self.assertIn("Chat Wrapper Flow", install)
        self.assertIn("Codex lifecycle calls", install)
        self.assertIn("What Gets Recorded", readme)


if __name__ == "__main__":
    unittest.main()
