from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.capabilities.hooks import hook_manifest


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
        self.assertIn("bounded_status_context", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("executor_opened", events)
        self.assertIn("selected_executor_profile", events["executor_opened"]["payload_fields"])
        self.assertIn("not proof", hooks["pre_llm_call"]["claim_boundary"])
