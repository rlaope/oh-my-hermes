from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.dynamic_workflow import (
    DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION,
    DYNAMIC_WORKFLOW_SCHEMA_VERSION,
    build_dynamic_coding_workflow,
    render_dynamic_workflow_svg,
    write_dynamic_coding_workflow,
)
from omh.paths import resolve_paths


class DynamicWorkflowTests(unittest.TestCase):
    def test_default_workflow_prepares_dynamic_target_plan_without_claiming_execution(self) -> None:
        workflow = build_dynamic_coding_workflow("Build the dynamic coding orchestration feature")

        self.assertEqual(workflow["schema_version"], DYNAMIC_WORKFLOW_SCHEMA_VERSION)
        self.assertEqual(workflow["status"], "prepared_not_observed")
        targets = {stage["target"] for stage in workflow["stages"]}
        target_types = {stage["target_type"] for stage in workflow["stages"]}

        for concrete_target in {"gpt", "claude-code", "glm", "codex", "pi", "omp-runtime", "omx-runtime"}:
            self.assertNotIn(concrete_target, targets)
        for expected in {"planning-model-pool", "implementation-model-pool", "executor-runtime-pool", "hermes"}:
            self.assertIn(expected, targets)
        for expected_type in {"model", "runtime", "wrapper"}:
            self.assertIn(expected_type, target_types)

        gates = {stage["gate"] for stage in workflow["stages"]}
        self.assertIn("critic_approval_required", gates)
        self.assertIn("independent_review_required", gates)
        self.assertIn("model invocation", " ".join(workflow["prepared_is_not"]))
        self.assertIn("model selection", " ".join(workflow["prepared_is_not"]))
        self.assertIn("target_selection_observed", workflow["observed_evidence_required"])
        self.assertIn("runtime_dispatch_observed", workflow["observed_evidence_required"])
        self.assertEqual(workflow["goal"]["summary_kind"], "digest_reference")
        self.assertFalse(workflow["goal"]["raw_prompt_stored"])
        self.assertEqual(workflow["target_selection"]["selection_unit"], "typed_orchestration_target")

    def test_workflow_goal_payload_stores_digest_not_prompt_text(self) -> None:
        workflow = build_dynamic_coding_workflow(
            "Deploy with token sk-test-secret-123, password hunter2, and private email user@example.com"
        )
        serialized = json.dumps(workflow, sort_keys=True)

        self.assertNotIn("sk-test-secret-123", serialized)
        self.assertNotIn("hunter2", serialized)
        self.assertNotIn("user@example.com", serialized)
        self.assertIn("sha256:", workflow["goal"]["summary"])
        self.assertEqual(workflow["goal"]["summary_kind"], "digest_reference")
        self.assertFalse(workflow["goal"]["raw_prompt_stored"])
        self.assertFalse(workflow["goal"]["content_preview_stored"])
        self.assertEqual(
            workflow["goal"]["input_chars"],
            len("Deploy with token sk-test-secret-123, password hunter2, and private email user@example.com"),
        )
        self.assertRegex(workflow["goal"]["sha256"], r"^[0-9a-f]{64}$")

    def test_explicit_glm_and_pi_specs_keep_model_and_runtime_targets_distinct(self) -> None:
        workflow = build_dynamic_coding_workflow(
            "Ship a reviewed multi-agent implementation",
            implementers=("glm:auto:GLM model target", "pi:auto:Pi runtime target"),
        )
        stages = {stage["target"]: stage for stage in workflow["stages"]}

        self.assertEqual(stages["glm"]["target_type"], "model")
        self.assertEqual(stages["pi"]["target_type"], "runtime")
        self.assertEqual(stages["glm"]["runtime"], "")
        self.assertEqual(stages["pi"]["runtime"], "pi")

        svg = render_dynamic_workflow_svg(workflow)

        self.assertTrue(svg.startswith("<svg "))
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        self.assertIn(DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION, svg)
        self.assertIn("GLM model target", svg)
        self.assertIn("target: glm (model)", svg)
        self.assertIn("target: pi (runtime)", svg)
        self.assertIn("model: auto", svg)
        self.assertIn("role: implementation_owner", svg)
        self.assertIn("cost: medium", svg)
        self.assertIn("gate: handoff_prepared_after_critique", svg)
        self.assertIn("Pi runtime target", svg)
        self.assertIn("prepared_not_observed", svg)

    def test_svg_chart_viewbox_contains_rightmost_stage(self) -> None:
        workflow = build_dynamic_coding_workflow("Render a complete chart without clipping")
        svg = render_dynamic_workflow_svg(workflow)

        width_match = re.search(r'viewBox="0 0 ([0-9]+) ([0-9]+)"', svg)
        rect_matches = [
            (int(x), int(width))
            for x, width in re.findall(r'<rect x="([0-9]+)" y="[0-9]+" width="([0-9]+)" height="112"', svg)
        ]

        self.assertIsNotNone(width_match)
        self.assertTrue(rect_matches)
        self.assertLessEqual(max(x + width for x, width in rect_matches), int(width_match.group(1)))

    def test_glm_like_targets_infer_model_without_exact_id_match(self) -> None:
        workflow = build_dynamic_coding_workflow(
            "Route model-family targets without collapsing them to runtimes",
            implementers=("glm-4.5:auto:GLM 4.5", "glm-pro:auto:GLM Pro", "gpt-5.5:auto:GPT 5.5"),
        )
        stages = {stage["target"]: stage for stage in workflow["stages"]}

        self.assertEqual(stages["glm-4.5"]["target_type"], "model")
        self.assertEqual(stages["glm-pro"]["target_type"], "model")
        self.assertEqual(stages["gpt-5.5"]["target_type"], "model")
        self.assertEqual(stages["glm-4.5"]["runtime"], "")
        self.assertEqual(stages["glm-4.5"]["cost_tier"], "medium")

    def test_pi_like_targets_remain_runtime_or_agent_surfaces(self) -> None:
        workflow = build_dynamic_coding_workflow(
            "Route Pi-like surfaces without treating them as model families",
            implementers=("pi:auto:Pi runtime", "pi-runtime:auto:Pi runtime profile", "pi-agent:auto:Pi agent"),
        )
        stages = {stage["target"]: stage for stage in workflow["stages"]}

        self.assertEqual(stages["pi"]["target_type"], "runtime")
        self.assertEqual(stages["pi-runtime"]["target_type"], "runtime")
        self.assertEqual(stages["pi-agent"]["target_type"], "agent")
        self.assertEqual(stages["pi-agent"]["runtime"], "")

    def test_svg_chart_tolerates_malformed_stage_dicts(self) -> None:
        svg = render_dynamic_workflow_svg({"stages": [{"id": "missing-lane"}, {"lane": "planning"}], "edges": []})

        self.assertTrue(svg.startswith("<svg "))
        self.assertIn("Dynamic coding workflow", svg)

    def test_svg_chart_rejects_xml_control_characters(self) -> None:
        workflow = build_dynamic_coding_workflow(
            "Prepare a dynamic workflow safely",
            implementers=("glm:auto:Bad\x01Label",),
        )

        with self.assertRaisesRegex(ValueError, "XML 1.0"):
            render_dynamic_workflow_svg(workflow)

    def test_cli_writes_workflow_json_and_svg_image_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "coding",
                    "dynamic-workflow",
                    "--write",
                    "--planner",
                    "planning-model-pool:auto:Planning model pool:adaptive:model",
                    "--critic",
                    "critique-model-pool:auto:Critique model pool:adaptive:model",
                    "--implementer",
                    "implementation-model-pool:auto:Implementation model pool:adaptive:model",
                    "--implementer",
                    "executor-runtime-pool:auto:Executor runtime pool:runtime-variable:runtime",
                    "--reviewer",
                    "review-model-pool:auto:Review model pool:adaptive:model",
                    "Build this feature with adversarial review",
                ]
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            workflow_path = Path(payload["artifacts"]["workflow_path"])
            chart_path = Path(payload["artifacts"]["chart_path"])

            self.assertTrue(workflow_path.exists())
            self.assertTrue(chart_path.exists())
            self.assertEqual(payload["status"], "prepared_not_observed")
            self.assertEqual(payload["chart"]["format"], "svg")
            self.assertEqual(payload["message_projection"]["attachments"][0]["kind"], "image")
            self.assertEqual(payload["target_selection"]["selection_unit"], "typed_orchestration_target")
            self.assertIn("target_type", payload["stages"][0])
            self.assertFalse((omh_home / "runtime" / "runs").exists())
            self.assertIn("not execution", " ".join(payload["prepared_is_not"]))
            self.assertIn("<svg ", chart_path.read_text(encoding="utf-8"))

    def test_cli_source_metadata_partitions_persisted_workflow_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            base_args = [
                "--omh-home",
                str(omh_home),
                "coding",
                "dynamic-workflow",
                "--write",
                "--source",
                "discord",
                "--channel-ref",
                "channel-a",
                "Build the dynamic workflow feature",
            ]

            first_status, first_stdout, first_stderr = run_cli(base_args + ["--source-event-id", "event-1"])
            second_status, second_stdout, second_stderr = run_cli(base_args + ["--source-event-id", "event-2"])

            self.assertEqual(first_status, 0, first_stderr)
            self.assertEqual(second_status, 0, second_stderr)
            first_payload = json.loads(first_stdout)
            second_payload = json.loads(second_stdout)

            self.assertNotEqual(first_payload["workflow_id"], second_payload["workflow_id"])
            self.assertNotEqual(first_payload["artifacts"]["workflow_path"], second_payload["artifacts"]["workflow_path"])
            self.assertEqual(first_payload["source_metadata"]["source_event_id"], "event-1")
            self.assertEqual(second_payload["source_metadata"]["source_event_id"], "event-2")
            self.assertTrue(Path(first_payload["artifacts"]["workflow_path"]).exists())
            self.assertTrue(Path(second_payload["artifacts"]["workflow_path"]).exists())

    def test_source_metadata_allowlist_drops_raw_or_secret_like_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            workflow = build_dynamic_coding_workflow(
                "Prepare a dynamic workflow safely",
                source_metadata={
                    "source_event_id": "event-safe",
                    "channel_ref": "channel-safe",
                    "raw_message": "token sk-live-secret",
                    "password": "hunter2",
                },
            )

            payload = write_dynamic_coding_workflow(paths, workflow)
            workflow_path = Path(payload["artifacts"]["workflow_path"])
            serialized = json.dumps(payload, sort_keys=True) + workflow_path.read_text(encoding="utf-8")

            self.assertEqual(payload["source_metadata"], {"source_event_id": "event-safe", "channel_ref": "channel-safe"})
            self.assertNotIn("raw_message", serialized)
            self.assertNotIn("sk-live-secret", serialized)
            self.assertNotIn("hunter2", serialized)

    def test_cli_stdout_and_persisted_artifacts_redact_secret_like_goal(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            secret_goal = "Deploy with token sk-test-secret-123, password hunter2, and private email user@example.com"

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "coding", "dynamic-workflow", "--write", secret_goal]
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            workflow_path = Path(payload["artifacts"]["workflow_path"])
            serialized = stdout + workflow_path.read_text(encoding="utf-8")

            self.assertNotIn("sk-test-secret-123", serialized)
            self.assertNotIn("hunter2", serialized)
            self.assertNotIn("user@example.com", serialized)
            self.assertIn("sha256:", payload["goal"]["summary"])
            self.assertFalse(payload["goal"]["content_preview_stored"])

    def test_writer_rejects_workflow_id_path_traversal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            workflow = build_dynamic_coding_workflow("Prepare a dynamic workflow safely")
            workflow["workflow_id"] = "../../../../outside-omh-audit"

            with self.assertRaisesRegex(ValueError, "workflow_id"):
                write_dynamic_coding_workflow(paths, workflow)

            self.assertFalse((root / "outside-omh-audit").exists())

    def test_writer_rejects_symlinked_dynamic_workflow_storage(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            storage = paths.dynamic_coding_workflows_dir
            outside = root / "outside-workflows"
            storage.parent.mkdir(parents=True)
            outside.mkdir()
            try:
                storage.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            workflow = build_dynamic_coding_workflow("Prepare a dynamic workflow safely")

            with self.assertRaisesRegex(ValueError, "storage must not be a symlink"):
                write_dynamic_coding_workflow(paths, workflow)

            self.assertFalse((outside / workflow["workflow_id"] / "workflow.json").exists())

    def test_writer_rejects_symlinked_dynamic_workflow_parent_escape(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            coding_dir = paths.dynamic_coding_workflows_dir.parent
            outside = root / "outside-coding"
            coding_dir.parent.mkdir(parents=True)
            outside.mkdir()
            try:
                coding_dir.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            workflow = build_dynamic_coding_workflow("Prepare a dynamic workflow safely")

            with self.assertRaisesRegex(ValueError, "storage must resolve under OMH home"):
                write_dynamic_coding_workflow(paths, workflow)

            self.assertFalse((outside / "dynamic-workflows" / workflow["workflow_id"] / "workflow.json").exists())

    def test_writer_stores_private_workflow_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            workflow = build_dynamic_coding_workflow("Prepare a dynamic workflow privately")

            payload = write_dynamic_coding_workflow(paths, workflow)
            workflow_path = Path(payload["artifacts"]["workflow_path"])
            chart_path = Path(payload["artifacts"]["chart_path"])

            self.assertEqual(workflow_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(chart_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(workflow_path.parent.stat().st_mode & 0o777, 0o700)

    def test_writer_does_not_leave_chart_when_workflow_json_write_is_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            workflow = build_dynamic_coding_workflow("Prepare a dynamic workflow atomically")
            workflow_dir = paths.dynamic_coding_workflows_dir / str(workflow["workflow_id"])
            workflow_dir.mkdir(parents=True)
            (workflow_dir / ".workflow.json.tmp").write_text("blocked", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "atomic write temp path already exists"):
                write_dynamic_coding_workflow(paths, workflow)

            self.assertFalse((workflow_dir / "workflow-chart.svg").exists())
            self.assertFalse((workflow_dir / "workflow.json").exists())

    def test_writer_rejects_preexisting_temp_symlink_escape(self) -> None:
        for filename, outside_name in (
            (".workflow-chart.svg.tmp", "outside-chart.svg"),
            (".workflow.json.tmp", "outside-workflow.json"),
        ):
            with self.subTest(filename=filename), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = resolve_paths(root / ".omh", root / ".hermes")
                workflow = build_dynamic_coding_workflow("Prepare a dynamic workflow safely")
                workflow_dir = paths.dynamic_coding_workflows_dir / str(workflow["workflow_id"])
                outside = root / outside_name
                workflow_dir.mkdir(parents=True)
                try:
                    (workflow_dir / filename).symlink_to(outside)
                except (NotImplementedError, OSError) as exc:
                    self.skipTest(f"symlink creation unavailable: {exc}")

                with self.assertRaisesRegex(FileExistsError, "atomic write temp path already exists"):
                    write_dynamic_coding_workflow(paths, workflow)

                self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
