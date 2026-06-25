from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.demo import build_orchestration_demo


def _step(payload: dict[str, object], step_id: str) -> dict[str, object]:
    steps = payload["steps"]
    if not isinstance(steps, list):
        raise AssertionError("demo steps must be a list")
    for item in steps:
        if isinstance(item, dict) and item.get("id") == step_id:
            return item
    raise AssertionError(f"missing demo step: {step_id}")


def _payload(step: dict[str, object]) -> dict[str, object]:
    payload = step["payload"]
    if not isinstance(payload, dict):
        raise AssertionError("demo step payload must be an object")
    return payload


class OrchestrationDemoTests(unittest.TestCase):
    def test_default_demo_requires_executor_choice_without_codex_run_id(self) -> None:
        demo = build_orchestration_demo()

        self.assertEqual(demo["schema_version"], "orchestration_demo/v1")
        self.assertEqual(demo["executor_target"], "choose")
        self.assertIn("executor choice", demo["summary"])

        handoff_step = _payload(_step(demo, "handoff"))
        handoff_response = handoff_step["chat_response"]
        self.assertIsInstance(handoff_response, dict)
        self.assertEqual(handoff_response["state"]["next_action"], "choose_executor")
        self.assertEqual(handoff_response["state"]["selected_executor_profile"], None)
        self.assertEqual(handoff_step["executor_handoff"], {})

        status_step = _payload(_step(demo, "status_card"))
        status = status_step["status"]
        self.assertIsInstance(status, dict)
        self.assertEqual(status["run_id"], "demo-prepared-executor-choice")
        self.assertEqual(status["next_action"], "choose_executor")
        self.assertEqual(status["prepared"]["executor_target"], "choose")
        self.assertTrue(status["prepared"]["choice_required"])
        self.assertFalse(status["prepared"]["handoff_available"])
        self.assertNotEqual(status["run_id"], "demo-prepared-codex-handoff")
        self.assertEqual(status_step["chat_response"]["state"]["phase"], "executor_choice_required")
        self.assertIn("Choose executor", [action["label"] for action in status_step["chat_response"]["actions"]])

    def test_codex_demo_keeps_codex_specific_alias_only_when_selected(self) -> None:
        demo = build_orchestration_demo(executor_target="codex")

        status_step = _payload(_step(demo, "status_card"))
        status = status_step["status"]
        self.assertIsInstance(status, dict)
        self.assertEqual(demo["executor_target"], "codex")
        self.assertEqual(status["run_id"], "demo-prepared-codex-handoff")
        self.assertEqual(status["next_action"], "dispatch_to_executor")
        self.assertEqual(status["prepared"]["executor_target"], "codex")
        self.assertEqual(status["prepared"]["handoff_schema_version"], "coding_executor_handoff/v1")
        self.assertTrue(status["prepared"]["handoff_available"])
        self.assertIn("Send to Codex", [action["label"] for action in status_step["chat_response"]["actions"]])

    def test_prompt_and_runtime_demo_profiles_are_not_collapsed_to_codex(self) -> None:
        cases = (
            ("claude-code", "coding_prompt_handoff/v1", "show_prompt_handoff", "prompt_handoff_prepared"),
            ("hermes", "coding_runtime_handoff/v1", "show_runtime_handoff", "runtime_handoff_prepared"),
        )

        for executor, schema_version, next_action, phase in cases:
            with self.subTest(executor=executor):
                demo = build_orchestration_demo(executor_target=executor)
                status_step = _payload(_step(demo, "status_card"))
                status = status_step["status"]
                self.assertIsInstance(status, dict)
                self.assertEqual(demo["executor_target"], executor)
                self.assertEqual(status["run_id"], f"demo-prepared-{executor}-handoff")
                self.assertEqual(status["next_action"], next_action)
                self.assertEqual(status["prepared"]["executor_target"], executor)
                self.assertEqual(status["prepared"]["selected_executor_profile"], executor)
                self.assertEqual(status["prepared"]["handoff_schema_version"], schema_version)
                self.assertTrue(status["prepared"]["handoff_available"])
                self.assertEqual(status_step["chat_response"]["state"]["phase"], phase)
                self.assertNotEqual(status["run_id"], "demo-prepared-codex-handoff")

    def test_cli_demo_orchestration_accepts_executor_choice(self) -> None:
        status, stdout, stderr = run_cli(["demo", "orchestration", "--executor", "hermes"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["executor_target"], "hermes")
        status_step = _payload(_step(payload, "status_card"))
        self.assertEqual(status_step["status"]["prepared"]["executor_target"], "hermes")
        self.assertEqual(status_step["status"]["next_action"], "show_runtime_handoff")
