from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.capabilities.hooks import hook_manifest
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call


class HookManifestTests(unittest.TestCase):
    def test_hook_manifest_projects_plugin_yaml_and_wrapper_events(self) -> None:
        manifest = hook_manifest()

        self.assertEqual(manifest["schema_version"], "omh_hook_manifest/v1")
        tools = {item["name"]: item for item in manifest["plugin_tools"]}
        hooks = {item["name"]: item for item in manifest["plugin_hooks"]}
        events = {item["name"]: item for item in manifest["wrapper_events"]}

        self.assertIn("omh_capabilities", tools)
        self.assertTrue(tools["omh_capabilities"]["supported_by_plugin_bundle"])
        self.assertTrue(tools["omh_capabilities"]["supported_by_cli_backend"])
        self.assertFalse(tools["omh_capabilities"]["observed_in_this_environment"])
        self.assertIn("pre_llm_call", hooks)
        self.assertIn("omh_awareness_primer", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("omh_route_hint", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("bounded_status_context", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("executor_opened", events)
        self.assertIn("selected_executor_profile", events["executor_opened"]["payload_fields"])
        self.assertIn("native_command_registered", events)
        self.assertIn("registration_schema", events["native_command_registered"]["payload_fields"])
        self.assertIn("native_command_rendered", events)
        self.assertIn("render_kind", events["native_command_rendered"]["payload_fields"])
        self.assertIn("not proof", hooks["pre_llm_call"]["claim_boundary"])

    def test_awareness_route_hint_is_metadata_only_and_message_specific(self) -> None:
        message = "make an image explaining the cron feature with secret-token-123"

        payload = awareness_route_hint(message)
        suppressed = awareness_route_hint(message, max_hints=0)
        serialized = str(payload)

        self.assertEqual(payload["schema_version"], "omh_route_hint/v1")
        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "img-summary")
        self.assertTrue(payload["message_sha256"])
        self.assertEqual(payload["message_length"], len(message))
        self.assertFalse(payload["privacy"]["raw_prompt_stored"])
        self.assertIn("image", payload["hints"][0]["matched_cues"])
        self.assertIn("not workflow execution", payload["claim_boundary"])
        self.assertNotIn(message, serialized)
        self.assertNotIn("secret-token-123", serialized)
        self.assertEqual(suppressed["status"], "no_hint")
        self.assertEqual(suppressed["hints"], [])

    def test_pre_llm_call_includes_bounded_route_hint_without_raw_message(self) -> None:
        message = "make an image explaining the cron feature with secret-token-123"

        result = pre_llm_call(user_message=message, is_first_turn=False)
        context = result["context"] if result else ""

        self.assertIn("[OMH Awareness]", context)
        self.assertIn("[OMH Route Hint]", context)
        self.assertIn("workflow=img-summary", context)
        self.assertIn("workflow=automation-blueprint", context)
        self.assertIn("not_evidence_yet=file export, image generation", context)
        self.assertNotIn(message, context)
        self.assertNotIn("secret-token-123", context)

    def test_pre_llm_call_can_disable_awareness_route_hint(self) -> None:
        result = pre_llm_call(
            user_message="make an image explaining the cron feature",
            is_first_turn=False,
            include_omh_awareness=False,
        )
        context = result["context"] if result else ""

        self.assertNotIn("[OMH Awareness]", context)
        self.assertNotIn("[OMH Route Hint]", context)
        self.assertNotIn("workflow=img-summary", context)
