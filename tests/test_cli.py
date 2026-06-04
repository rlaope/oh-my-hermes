from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class CliTests(unittest.TestCase):
    def test_recommend_risky_refactor_includes_cleanup_workflow(self) -> None:
        status, stdout, stderr = run_cli(["recommend", "risky", "refactor"])

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["query"], "risky refactor")
        recommendations = payload["recommendations"]
        self.assertTrue(recommendations)
        self.assertIn("ai-slop-cleaner", {recommendation["skill"] for recommendation in recommendations[:3]})
        self.assertTrue(any(recommendation["why"] and recommendation["suggested_prompt"] for recommendation in recommendations))

    def test_recommend_implementation_plan_includes_planning_workflow(self) -> None:
        status, stdout, stderr = run_cli(["recommend", "implementation", "plan", "with", "review"])

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        recommendations = json.loads(stdout)["recommendations"]
        top_names = {recommendation["skill"] for recommendation in recommendations[:3]}
        self.assertTrue({"plan", "ralplan"} & top_names)

    def test_recommend_diagnose_installation_health_includes_doctor(self) -> None:
        status, stdout, stderr = run_cli(["recommend", "diagnose", "installation", "health"])

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        top_names = {recommendation["skill"] for recommendation in json.loads(stdout)["recommendations"][:3]}
        self.assertIn("doctor", top_names)

    def test_recommend_weak_query_uses_fallback(self) -> None:
        status, stdout, stderr = run_cli(["recommend", "zzzzunknownphrase"])

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        recommendations = json.loads(stdout)["recommendations"]
        self.assertIn("oh-my-hermes", {recommendation["skill"] for recommendation in recommendations})
        self.assertEqual(recommendations[0]["confidence"], "low")
        self.assertIn("No strong catalog metadata match", recommendations[0]["why"])

    def test_recommend_rejects_invalid_limit(self) -> None:
        status, _, stderr = run_cli(["recommend", "refactor", "--limit", "0"])

        self.assertEqual(status, 2)
        self.assertIn("recommend --limit must be at least 1", stderr)

    def test_install_apply_doctor_and_list(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "apply"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "list"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])[0], 0)

            manifest = json.loads((omh_home / "manifest.json").read_text(encoding="utf-8"))
            names = {skill["name"] for skill in manifest["skills"]}
            self.assertIn("oh-my-hermes", names)
            self.assertIn("ralph", names)
            self.assertIn("ultragoal", names)
            self.assertIn(str(omh_home / "skills"), (hermes_home / "config.yaml").read_text(encoding="utf-8"))
            state = json.loads((omh_home / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["installed_skills"], len(manifest["skills"]))
            self.assertEqual(state["last_applied_skills_dir"], str((omh_home / "skills").resolve()))
            self.assertEqual(state["release_channel"], "preview")

            _, doctor_stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])
            doctor = json.loads(doctor_stdout)
            checks = {check["name"]: check for check in doctor["checks"]}
            self.assertTrue(checks["runtime_context"]["ok"])
            self.assertIn("--hermes-home", checks["runtime_context"]["message"])
            self.assertTrue(checks["manifest_skills_dir"]["ok"])
            self.assertTrue(checks["local_modifications"]["ok"])
            self.assertTrue(checks["runtime_artifacts"]["ok"])
            self.assertTrue(checks["workflow_state"]["ok"])

    def test_install_is_idempotent_and_detects_local_modifications(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            skill_file = omh_home / "skills" / "ralph" / "SKILL.md"
            skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")

            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])
            self.assertEqual(status, 2)
            self.assertIn("local modifications detected", stderr)

            doctor_status, doctor_stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])
            self.assertEqual(doctor_status, 1)
            checks = {check["name"]: check for check in json.loads(doctor_stdout)["checks"]}
            self.assertFalse(checks["local_modifications"]["ok"])
            self.assertIn("ralph/SKILL.md", checks["local_modifications"]["message"])
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install", "--force"])[0], 0)

    def test_doctor_reports_wrong_runtime_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            installed_hermes_home = root / ".hermes-installed"
            other_hermes_home = root / ".hermes-other"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(installed_hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(installed_hermes_home), "apply"])[0], 0)

            status, stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(other_hermes_home), "doctor"])

            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["runtime_context"]["ok"])
            self.assertIn("matching the Hermes or bot runtime", checks["runtime_context"]["message"])

    def test_convert_from_local_skill_fixture(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "local-skills" / "ralph"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text(
                "---\nname: ralph\ndescription: Upstream Ralph\n---\n# Ralph\nUse durable goal tools.\n",
                encoding="utf-8",
            )
            omh_home = root / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "convert", "--from-skills-dir", str(root / "local-skills")])[0], 0)
            converted = (omh_home / "skills" / "ralph" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Hermes Compatibility Contract", converted)

    def test_mocked_source_install_update(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "release-archive" / "team"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text(
                "---\nname: team\ndescription: Upstream Team\n---\n# Team\n",
                encoding="utf-8",
            )
            omh_home = root / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "install", "--source", str(root / "release-archive")])[0], 0)
            first_manifest = json.loads((omh_home / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(first_manifest["source"], str((root / "release-archive").resolve()))

            source.joinpath("SKILL.md").write_text(
                "---\nname: team\ndescription: Upstream Team\n---\n# Team\nUpdated.\n",
                encoding="utf-8",
            )
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "update", "--source", str(root / "release-archive")])[0], 0)
            updated = (omh_home / "skills" / "team" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Updated.", updated)

    def test_release_channel_metadata_and_validation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "install", "--dry-run", "--channel", "stable", "--version", "0.1.0"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            dry_run = json.loads(stdout)
            self.assertEqual(dry_run["release_channel"], "stable")
            self.assertIn("/tags/v0.1.0.zip", dry_run["release_package_url"])

            status, _, stderr = run_cli(["--omh-home", str(omh_home), "install", "--dry-run", "--channel", "stable"])
            self.assertEqual(status, 2)
            self.assertIn("stable channel requires", stderr)

            status, _, stderr = run_cli(["--omh-home", str(omh_home), "update", "--channel", "local"])
            self.assertEqual(status, 2)
            self.assertIn("local channel requires", stderr)

    def test_runtime_commands_record_show_and_delegate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "runtime", "status"])[0], 0)
            status, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "runtime",
                    "record",
                    "--skill",
                    "oh-my-hermes",
                    "--harness",
                    "coding-handling",
                    "--status",
                    "started",
                    "--trigger",
                    "coding request",
                ]
            )
            self.assertEqual(status, 0)
            run = json.loads(stdout)["run"]

            status, stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "runtime", "runs"])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stdout)["runs"][0]["run_id"], run["run_id"])

            status, _, _ = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
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
            self.assertEqual(status, 0)

            status, stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "runtime", "show", run["run_id"]])
            self.assertEqual(status, 0)
            shown = json.loads(stdout)
            self.assertEqual(shown["run"]["harness"], "coding-handling")
            self.assertTrue(shown["delegation"]["requested"])
            self.assertFalse(shown["delegation"]["observed"])

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "runtime",
                    "wrapper",
                    "--run",
                    run["run_id"],
                    "--prompt-dispatched",
                    "--response-observed",
                    "--completion-status",
                    "completed",
                    "--gap",
                    "verification lane not exposed",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(stdout)["wrapper"]["prompt_dispatched"])

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "runtime", "validate"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(stdout)["ok"])

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "runtime", "export"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            exported = json.loads(stdout)
            self.assertTrue(exported["redacted"])
            self.assertEqual(exported["runs"][0]["wrapper"]["completion_status"], "completed")

    def test_docs_workflows_command_prints_writes_and_checks_generated_reference(self) -> None:
        status, stdout, stderr = run_cli(["docs", "workflows"])
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("# Workflow Reference", stdout)
        self.assertIn("### oh-my-hermes", stdout)

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "WORKFLOWS.md"
            status, stdout, stderr = run_cli(["docs", "workflows", "--output", str(output)])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(output.exists())
            self.assertIn("written", stdout)

            status, stdout, stderr = run_cli(["docs", "workflows", "--output", str(output), "--check"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertIn("checked", stdout)

            output.write_text(output.read_text(encoding="utf-8") + "\nstale\n", encoding="utf-8")
            status, _, stderr = run_cli(["docs", "workflows", "--output", str(output), "--check"])
            self.assertEqual(status, 2)
            self.assertIn("workflow docs are stale", stderr)

    def test_runtime_record_rejects_unknown_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "runtime",
                    "record",
                    "--skill",
                    "missing",
                    "--harness",
                    "coding-handling",
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("unknown skill", stderr)

    def test_runtime_delegate_rejects_contradictory_observation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            status, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "record",
                    "--skill",
                    "oh-my-hermes",
                    "--harness",
                    "coding-handling",
                ]
            )
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["run"]["run_id"]

            status, _, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "delegate",
                    "--run",
                    run_id,
                    "--observed",
                    "--result",
                    "not_observed",
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("observed delegation requires", stderr)

    def test_doctor_reports_unwritable_runtime_artifact_path_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            omh_home.mkdir()
            (omh_home / "runtime").write_text("not a directory", encoding="utf-8")

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "doctor"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["runtime_artifacts"]["ok"])

    def test_doctor_reports_malformed_runtime_state_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            state_path = omh_home / "runtime" / "state.json"
            state_path.mkdir(parents=True)

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "doctor"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["runtime_state"]["ok"])

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "install"])[0], 0)
            state_path = omh_home / "runtime" / "state.json"
            state_path.write_text('"bad"', encoding="utf-8")

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "doctor"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["runtime_state"]["ok"])

    def test_runtime_status_and_record_tolerate_malformed_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            state_path = omh_home / "runtime" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{not json", encoding="utf-8")

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "runtime", "status"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            status_payload = json.loads(stdout)
            self.assertIsNone(status_payload["state"])
            self.assertIn("state_error", status_payload)

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "record",
                    "--skill",
                    "oh-my-hermes",
                    "--harness",
                    "coding-handling",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["run"]["run_id"]
            self.assertTrue((omh_home / "runtime" / "runs" / run_id / "run.json").exists())

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            state_path = omh_home / "runtime" / "state.json"
            state_path.mkdir(parents=True)

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "runtime", "status"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertIsNone(json.loads(stdout)["state"])

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "record",
                    "--skill",
                    "oh-my-hermes",
                    "--harness",
                    "coding-handling",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["run"]["run_id"]
            self.assertTrue((omh_home / "runtime" / "runs" / run_id / "run.json").exists())

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            state_path = omh_home / "runtime" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("[]", encoding="utf-8")

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "runtime", "status"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertIsNone(json.loads(stdout)["state"])

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "record",
                    "--skill",
                    "oh-my-hermes",
                    "--harness",
                    "coding-handling",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            state_path = omh_home / "runtime" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{not json", encoding="utf-8")

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "doctor"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["runtime_state"]["ok"])


if __name__ == "__main__":
    unittest.main()
