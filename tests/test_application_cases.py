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
        self.assertIn("omh cases artifact --all --write", cases)
        self.assertIn(".omh/use-cases/artifacts/", cases)
        self.assertIn("omh cases replay --json", cases)
        self.assertIn("Chat Wrapper Backend Flow", install)
        self.assertIn("Codex lifecycle calls", install)
        self.assertIn("What Gets Recorded", install)
        self.assertNotIn("What Gets Recorded", readme)

    def test_g1_to_g10_demo_fixture_is_wrapper_renderable(self) -> None:
        code, stdout, stderr = run_cli(["cases", "demo", "--all", "--json"], output_json=False)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")
        generated = json.loads(stdout)
        fixture = json.loads(Path("examples/use-cases/g1-g10-demo-cards.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture, generated)
        self.assertEqual(fixture["schema_version"], "omh_use_case_demo_collection/v1")
        self.assertEqual(fixture["count"], 10)
        for card in fixture["cards"]:
            with self.subTest(card=card["goal"]):
                self.assertEqual(card["schema_version"], "omh_use_case_demo_card/v1")
                self.assertEqual(card["wrapper_card"]["component"], "omh_use_case_card")
                self.assertEqual(card["wrapper_card"]["status"], "prepared_not_observed")
                self.assertEqual(card["evidence"]["state"], "prepared_not_observed")
                self.assertEqual(card["actions"][0]["id"], card["route"]["next_action"])
                self.assertIn("not", card["evidence"]["claim_boundary"].lower())
                self.assertIn("executor_dispatch", card["evidence"]["not_evidence_until_observed"])

    def test_g1_to_g10_use_case_artifacts_are_local_runbooks(self) -> None:
        code, stdout, stderr = run_cli(["cases", "artifact", "--all", "--json"], output_json=False)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")
        collection = json.loads(stdout)
        self.assertEqual(collection["schema_version"], "omh_use_case_artifact_collection/v1")
        self.assertEqual(collection["count"], 10)
        self.assertEqual([artifact["goal"] for artifact in collection["artifacts"]], [f"G{index}" for index in range(1, 11)])
        for artifact in collection["artifacts"]:
            with self.subTest(artifact=artifact["goal"]):
                self.assertEqual(artifact["schema_version"], "omh_use_case_artifact/v1")
                self.assertEqual(artifact["status"], "prepared")
                self.assertEqual(artifact["observation_status"], "prepared_not_observed")
                self.assertEqual(artifact["wrapper_card"]["status"], "prepared_not_observed")
                self.assertEqual(artifact["evidence"]["state"], "prepared_not_observed")
                self.assertFalse(artifact["release_quality"]["contains_raw_user_prompt"])
                self.assertIn("omh cases validate --json", artifact["proof_surfaces"])
                self.assertTrue(any(step["kind"] == "hermes_prompt" for step in artifact["operator_steps"]))

    def test_use_case_artifacts_can_be_written_and_validated(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            code, stdout, stderr = run_cli(["--omh-home", str(omh_home), "cases", "artifact", "--all", "--write", "--json"], output_json=False)

            self.assertEqual(code, 0, stderr)
            self.assertEqual(stderr, "")
            write_payload = json.loads(stdout)
            self.assertEqual(write_payload["schema_version"], "omh_use_case_artifact_write/v1")
            self.assertEqual(write_payload["count"], 10)
            self.assertTrue((omh_home / "use-cases" / "index.json").exists())
            self.assertEqual(len(list((omh_home / "use-cases" / "artifacts").glob("*.json"))), 10)

            code, stdout, stderr = run_cli(["--omh-home", str(omh_home), "cases", "artifact-validate", "--json"], output_json=False)

            self.assertEqual(code, 0, stderr)
            self.assertEqual(stderr, "")
            validation = json.loads(stdout)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["artifact_count"], 10)
            self.assertEqual(validation["missing_goals"], [])

    def test_g1_to_g10_use_case_replay_covers_operator_fixtures(self) -> None:
        code, stdout, stderr = run_cli(["cases", "replay", "--json"], output_json=False)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")
        replay = json.loads(stdout)
        self.assertEqual(replay["schema_version"], "omh_use_case_replay/v1")
        self.assertEqual(replay["status"], "passed")
        self.assertEqual(replay["total"], 20)
        self.assertEqual(replay["passed"], 20)
        self.assertEqual(replay["failed"], 0)
        self.assertEqual(replay["covered_goals"], [f"G{index}" for index in range(1, 11)])
        self.assertIn("synthetic operator fixtures", replay["boundary"])
        for result in replay["results"]:
            with self.subTest(fixture=result["fixture_id"]):
                self.assertEqual(result["status"], "passed")
                self.assertEqual(result["expected"]["goal"], result["observed"]["goal"])
                self.assertEqual(result["expected"]["primary_skill"], result["observed"]["primary_skill"])


if __name__ == "__main__":
    unittest.main()
