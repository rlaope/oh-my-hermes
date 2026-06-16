from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.capabilities.schema import CAPABILITY_SECTIONS
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS
from test_plugin_distribution import FakeHermesContext, load_installed_plugin


LEGACY_ROLE_ALIASES = {
    "coding-handoff": "handoff-guide",
    "planning-lead": "planner",
    "research-lead": "researcher",
    "review-gate": "reviewer",
}


class PluginCapabilitiesTests(unittest.TestCase):
    def test_installed_plugin_registers_capabilities_tool_and_returns_bounded_json(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])
            self.assertEqual(status, 0, stderr)

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            ctx = FakeHermesContext()
            module.register(ctx)

            self.assertIn("omh_capabilities", ctx.tools)
            handler = ctx.tools["omh_capabilities"]["args"][2]
            payload = json.loads(handler({"action": "export", "section": "keywords"}))
            self.assertEqual(payload["schema_version"], "omh_capability_manifest/v1")
            self.assertEqual(payload["section"], "keywords")
            self.assertIn("explicit_invocation_prefixes", payload["keywords"])

            inspected = json.loads(handler({"action": "inspect", "id": "handoff-guide"}))
            legacy_inspected = json.loads(handler({"action": "inspect", "id": "coding-handoff"}))
            self.assertEqual(inspected["section"], "agent_roles")
            self.assertEqual(inspected["capability"]["runtime_claim"], "descriptor_not_runtime_agent")
            self.assertEqual(legacy_inspected["section"], "agent_roles")
            self.assertEqual(legacy_inspected["requested_id"], "coding-handoff")
            self.assertEqual(legacy_inspected["resolved_id"], "handoff-guide")
            self.assertEqual(legacy_inspected["capability"]["id"], "handoff-guide")
            for alias, expected_role in LEGACY_ROLE_ALIASES.items():
                with self.subTest(alias=alias):
                    legacy = json.loads(handler({"action": "inspect", "id": alias, "section": "agent_roles"}))
                    self.assertEqual(legacy["section"], "agent_roles")
                    self.assertEqual(legacy["requested_id"], alias)
                    self.assertEqual(legacy["resolved_id"], expected_role)
                    self.assertEqual(legacy["capability"]["id"], expected_role)

            retained = json.loads(handler({"action": "inspect", "id": "retained-cognition", "section": "agent_roles"}))
            self.assertIn("capability not found: retained-cognition", retained["error"])

    def test_installed_plugin_capabilities_tool_loads_without_installed_omh_package(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])
            self.assertEqual(status, 0, stderr)
            plugin_dir = hermes_home / "plugins" / "omh"
            script = textwrap.dedent(
                f"""
                import importlib.util
                import json
                import sys

                class FakeCtx:
                    def __init__(self):
                        self.tools = {{}}
                        self.hooks = {{}}

                    def register_tool(self, name, *args, **kwargs):
                        self.tools[name] = {{"args": args, "kwargs": kwargs}}

                    def register_hook(self, name, handler):
                        self.hooks[name] = handler

                spec = importlib.util.spec_from_file_location(
                    "_standalone_omh_plugin",
                    {str(plugin_dir / "__init__.py")!r},
                    submodule_search_locations=[{str(plugin_dir)!r}],
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules["_standalone_omh_plugin"] = module
                spec.loader.exec_module(module)
                ctx = FakeCtx()
                module.register(ctx)
                handler = ctx.tools["omh_capabilities"]["args"][2]
                keywords = json.loads(handler({{"action": "export", "section": "keywords"}}))
                exported = json.loads(handler({{"action": "export"}}))
                listed_tools = json.loads(handler({{"action": "list", "section": "tool_requirements"}}))
                evidence = json.loads(handler({{"action": "export", "section": "evidence_boundaries"}}))
                inspected = json.loads(handler({{"action": "inspect", "id": "handoff-guide"}}))
                alias_results = {{}}
                for alias in {LEGACY_ROLE_ALIASES!r}:
                    alias_results[alias] = json.loads(
                        handler({{"action": "inspect", "id": alias, "section": "agent_roles"}})
                    )
                retained = json.loads(
                    handler({{"action": "inspect", "id": "retained-cognition", "section": "agent_roles"}})
                )
                inspected_loop = json.loads(handler({{"action": "inspect", "section": "skills", "id": "loop"}}))
                inspected_boundary = json.loads(
                    handler({{"action": "inspect", "section": "evidence_boundaries", "id": "prepared_is_not"}})
                )
                invalid_section = json.loads(handler({{"action": "inspect", "section": "missing", "id": "loop"}}))
                print(json.dumps({{
                    "tool_registered": "omh_capabilities" in ctx.tools,
                    "sections": sorted(key for key in exported if key in {set(CAPABILITY_SECTIONS)!r}),
                    "plugin_tools": sorted(item["name"] for item in exported["hooks"]["plugin_tools"]),
                    "plugin_hooks": sorted(item["name"] for item in exported["hooks"]["plugin_hooks"]),
                    "source": exported["source"],
                    "keyword_schema": keywords["keywords"]["schema_version"],
                    "tool_requirement_schema": exported["tool_requirements"]["schema_version"],
                    "tool_requirement_ids": listed_tools["ids"],
                    "evidence_section": evidence["section"],
                    "prepared_boundary": inspected_boundary["capability"],
                    "inspect_section": inspected["section"],
                    "alias_results": {{
                        alias: result["resolved_id"]
                        for alias, result in alias_results.items()
                    }},
                    "retained_error": retained["error"],
                    "loop_section": inspected_loop["section"],
                    "loop_runtime_claim": inspected_loop["capability"]["runtime_claim"],
                    "runtime_claim": inspected["capability"]["runtime_claim"],
                    "invalid_section_error": invalid_section["error"],
                    "degraded": inspected["degraded"],
                }}, sort_keys=True))
                """
            )

            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                cwd=str(root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["tool_registered"])
            self.assertEqual(payload["sections"], sorted(CAPABILITY_SECTIONS))
            self.assertEqual(payload["plugin_tools"], sorted(PROVIDED_TOOLS))
            self.assertEqual(payload["plugin_hooks"], sorted(PROVIDED_HOOKS))
            self.assertEqual(payload["source"], "standalone_plugin_bundle_fallback")
            self.assertEqual(payload["keyword_schema"], "keyword_detector_manifest/v1")
            self.assertEqual(payload["tool_requirement_schema"], "tool_requirement_manifest/v1")
            self.assertIn("loop", payload["tool_requirement_ids"])
            self.assertEqual(payload["evidence_section"], "evidence_boundaries")
            self.assertIn("Prepared OMH capability", payload["prepared_boundary"])
            self.assertEqual(payload["inspect_section"], "agent_roles")
            self.assertEqual(payload["alias_results"], LEGACY_ROLE_ALIASES)
            self.assertIn("unknown capability id: retained-cognition", payload["retained_error"])
            self.assertEqual(payload["loop_section"], "skills")
            self.assertEqual(payload["loop_runtime_claim"], "skill_guidance_not_execution")
            self.assertEqual(payload["runtime_claim"], "descriptor_not_runtime_agent")
            self.assertIn("unknown capability section", payload["invalid_section_error"])
            self.assertTrue(payload["degraded"])
