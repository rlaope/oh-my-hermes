from __future__ import annotations

import hashlib
import importlib.resources as resources
import importlib.util
import json
import sys
import tomllib
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.paths import resolve_paths
from omh.plugin_pack import inspect_plugin_bundle
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS, TOOL_FILE_STEMS


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}
        self.hooks: dict[str, object] = {}

    def register_tool(self, name: str, *args: object, **kwargs: object) -> None:
        self.tools[name] = {"args": args, "kwargs": kwargs}

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks[name] = handler


def load_installed_plugin(plugin_dir: Path):
    module_name = "_test_omh_installed_plugin"
    for name in list(sys.modules):
        if name == module_name or name.startswith(f"{module_name}."):
            sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load installed plugin")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class PluginDistributionTests(unittest.TestCase):
    def test_bundled_plugin_resource_is_packaged(self) -> None:
        root = resources.files("omh.plugin_bundle.omh")
        self.assertTrue(root.joinpath("plugin.yaml").is_file())
        self.assertTrue(root.joinpath("config.yaml").is_file())
        self.assertTrue(root.joinpath("references", "role-planner.md").is_file())
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        packages = set(pyproject["tool"]["setuptools"]["packages"])
        self.assertIn("omh.plugin_bundle.omh", packages)
        self.assertIn("omh.plugin_bundle.omh.references", packages)
        self.assertIn("omh.plugin_bundle.omh", pyproject["tool"]["setuptools"]["package-data"])
        self.assertIn(
            "*.md",
            pyproject["tool"]["setuptools"]["package-data"]["omh.plugin_bundle.omh.references"],
        )

    def test_plugin_yaml_advertises_metadata_tools_and_hooks(self) -> None:
        root = resources.files("omh.plugin_bundle.omh")
        text = root.joinpath("plugin.yaml").read_text(encoding="utf-8")

        for tool in PROVIDED_TOOLS:
            self.assertIn(f"  - {tool}", text)
            self.assertTrue(
                root.joinpath("tools", f"{TOOL_FILE_STEMS[tool]}.py").is_file(),
                f"{tool} must have a bundled tool file declared by metadata.py",
            )
        for hook in PROVIDED_HOOKS:
            self.assertIn(f"  - {hook}", text)

    def test_probe_tool_falls_back_only_when_package_is_absent(self) -> None:
        from omh.plugin_bundle.omh.tools import probe_tool

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            args = {"omh_home": str(omh_home), "hermes_home": str(hermes_home)}
            package_missing = ModuleNotFoundError("No module named 'omh'", name="omh")
            backend_broken = ModuleNotFoundError("No module named 'omh.probe'", name="omh.probe")

            with mock.patch.object(probe_tool, "_package_probe", side_effect=package_missing):
                fallback_payload = json.loads(probe_tool.omh_probe_handler(args))

            self.assertEqual(fallback_payload["source"], "standalone_plugin_bundle_fallback")
            self.assertTrue(fallback_payload["degraded"])

            with mock.patch.object(probe_tool, "_package_probe", side_effect=backend_broken):
                with self.assertRaises(ModuleNotFoundError):
                    probe_tool.omh_probe_handler(args)

    def test_setup_default_installs_plugin(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertIn("plugin", payload["steps"])
            self.assertEqual(payload["operator_summary"]["plugin_mode"], "installed")
            self.assertTrue((hermes_home / "plugins" / "omh").exists())
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])[0], 0)

    def test_setup_with_plugin_installs_and_registers_smoke(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            plugin = payload["plugin_distribution"]
            plugin_dir = hermes_home / "plugins" / "omh"
            self.assertEqual(plugin["schema_version"], "plugin_distribution/v1")
            self.assertTrue(plugin["observed"])
            self.assertTrue(plugin["requires_hermes_plugin_enable"])
            self.assertTrue((plugin_dir / "plugin.yaml").exists())
            self.assertTrue((plugin_dir / ".omh-plugin-manifest.json").exists())
            self.assertEqual(
                plugin["registered_tools"],
                [
                    "omh_capabilities",
                    "omh_context",
                    "omh_gather_evidence",
                    "omh_hud",
                    "omh_interact",
                    "omh_probe",
                    "omh_recommend",
                    "omh_role",
                    "omh_status",
                ],
            )
            self.assertEqual(plugin["registered_hooks"], ["on_session_end", "pre_llm_call", "pre_tool_call"])

            inspection = inspect_plugin_bundle(resolve_paths(omh_home, hermes_home))
            self.assertTrue(inspection["plugin_distribution_ready"])

            doctor_status, doctor_stdout, doctor_stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])
            self.assertEqual(doctor_stderr, "")
            self.assertEqual(doctor_status, 0)
            checks = {check["name"]: check for check in json.loads(doctor_stdout)["checks"]}
            self.assertTrue(checks["plugin_import_smoke"]["ok"])
            self.assertTrue(checks["plugin_register_smoke"]["ok"])

    def test_setup_with_plugin_dry_run_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin", "--dry-run"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertTrue(payload["plugin_distribution"]["dry_run"])
            self.assertFalse(payload["plugin_distribution"]["observed"])
            self.assertFalse((hermes_home / "plugins" / "omh").exists())

    def test_setup_with_plugin_refuses_dirty_managed_files_without_force(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])[0], 0)
            plugin_yaml = hermes_home / "plugins" / "omh" / "plugin.yaml"
            plugin_yaml.write_text(plugin_yaml.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")

            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])

            self.assertEqual(status, 2)
            self.assertIn("OMH status helper files were changed outside OMH", stderr)
            self.assertIn("omh setup --force", stderr)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin", "--force"])[0], 0)

    def test_doctor_reports_stale_plugin_bundle_as_plain_setup_refresh(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            base = ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home)]
            self.assertEqual(run_cli(base + ["setup", "--with-plugin"])[0], 0)

            plugin_dir = hermes_home / "plugins" / "omh"
            init_py = plugin_dir / "__init__.py"
            text = init_py.read_text(encoding="utf-8")
            stale_text = text.replace(
                '    ctx.register_tool(\n'
                '        "omh_probe",\n'
                "        _TOOLSET,\n"
                "        OMH_PROBE_SCHEMA,\n"
                "        omh_probe_handler,\n"
                '        description=OMH_PROBE_SCHEMA["description"],\n'
                "    )\n",
                "",
            ).replace(
                '    ctx.register_tool(\n'
                '        "omh_recommend",\n'
                "        _TOOLSET,\n"
                "        OMH_RECOMMEND_SCHEMA,\n"
                "        omh_recommend_handler,\n"
                '        description=OMH_RECOMMEND_SCHEMA["description"],\n'
                "    )\n",
                "",
            )
            init_py.write_text(stale_text, encoding="utf-8")
            manifest_path = plugin_dir / ".omh-plugin-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest["files"]:
                if record["path"] == "__init__.py":
                    record["sha256"] = hashlib.sha256(stale_text.encode("utf-8")).hexdigest()
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            inspection = inspect_plugin_bundle(resolve_paths(omh_home, hermes_home))
            self.assertTrue(inspection["plugin_manifest_valid"])
            self.assertFalse(inspection["plugin_manifest_current"])
            self.assertTrue(inspection["plugin_bundle_stale"])
            self.assertFalse(inspection["plugin_register_smoke"])
            self.assertEqual(inspection["missing_registered_tools"], ["omh_probe", "omh_recommend"])
            self.assertIn("stale relative to the installed OMH package", "; ".join(inspection["errors"]))

            status, stdout, stderr = run_cli(base + ["doctor"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["plugin_bundle_current"]["ok"])
            self.assertFalse(checks["plugin_register_smoke"]["ok"])
            self.assertIn("omh setup", checks["plugin_register_smoke"]["next_action"])
            self.assertNotIn("--force", checks["plugin_register_smoke"]["next_action"])
            self.assertIn("omh_probe", checks["plugin_register_smoke"]["message"])

            self.assertEqual(run_cli(base + ["setup"])[0], 0)
            self.assertEqual(run_cli(base + ["doctor"])[0], 0)

    def test_doctor_fails_for_malformed_installed_plugin(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])[0], 0)
            (hermes_home / "plugins" / "omh" / "__init__.py").unlink()

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["plugin_manifest"]["ok"])
            self.assertFalse(checks["plugin_import_smoke"]["ok"])

    def test_installed_plugin_status_tool_and_hook_keep_evidence_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])[0], 0)
            status, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "coding",
                    "delegate",
                    "--record",
                    "--executor",
                    "codex",
                    "implement safe status feature in src/runtime/status.py without overclaiming",
                ]
            )
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["runtime"]["run"]["run_id"]

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            ctx = FakeHermesContext()
            module.register(ctx)
            self.assertIn("omh_capabilities", ctx.tools)
            self.assertIn("omh_context", ctx.tools)
            self.assertIn("omh_gather_evidence", ctx.tools)
            self.assertIn("omh_hud", ctx.tools)
            self.assertIn("omh_probe", ctx.tools)
            self.assertIn("omh_role", ctx.tools)
            self.assertIn("omh_status", ctx.tools)
            self.assertIn("on_session_end", ctx.hooks)
            self.assertIn("pre_llm_call", ctx.hooks)
            self.assertIn("pre_tool_call", ctx.hooks)

            hud_handler = ctx.tools["omh_hud"]["args"][2]
            hud_payload = json.loads(hud_handler({"omh_home": str(omh_home), "hermes_home": str(hermes_home), "limit": 1}))
            self.assertEqual(hud_payload["schema_version"], "omh_hud/v1")
            self.assertIn("[omh]", hud_payload["display"]["line"])
            self.assertEqual(hud_payload["runtime"]["evidence_state"], "prepared_not_observed")
            self.assertEqual(hud_payload["tokens"]["status"], "unobserved")

            probe_handler = ctx.tools["omh_probe"]["args"][2]
            probe_payload = json.loads(
                probe_handler(
                    {
                        "omh_home": str(omh_home),
                        "hermes_home": str(hermes_home),
                        "include_roadmap": True,
                    }
                )
            )
            self.assertEqual(probe_payload["source"], "package_probe_backend")
            self.assertFalse(probe_payload["degraded"])
            self.assertEqual(probe_payload["plugin_tool"], "omh_probe")
            self.assertIn("capability_gap_roadmap", probe_payload)
            self.assertEqual(probe_payload["capability_gap_roadmap"]["schema_version"], "omh_capability_gap_roadmap/v1")
            self.assertIn("plugin_runtime_observed", {item["name"] for item in probe_payload["capabilities"]})

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "runtime",
                    "observe",
                    "--run",
                    run_id,
                    "--runtime-profile",
                    "hermes",
                    "--event",
                    "worker_result",
                    "--summary",
                    "executor completed the prepared handoff",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stdout)["journal_event"]["event"], "executor_result_observed")

            handler = ctx.tools["omh_status"]["args"][2]
            payload = json.loads(handler({"omh_home": str(omh_home), "limit": 1}))
            self.assertEqual(payload["schema_version"], "omh_status/v1")
            self.assertEqual(payload["runs"][0]["run_id"], run_id)
            self.assertTrue(payload["runs"][0]["prepared_handoff"])
            self.assertTrue(payload["runs"][0]["execution_observed"])
            self.assertEqual(payload["runs"][0]["observation_status"], "execution_observed")
            self.assertEqual(payload["runs"][0]["latest_event"]["event"], "executor_result_observed")
            self.assertTrue(payload["runs"][0]["lifecycle"]["execution_observed"])
            self.assertGreaterEqual(payload["runs"][0]["journal_event_count"], 2)
            self.assertIn("not execution evidence", payload["evidence_boundary"]["prepared_handoff"])

            recommend_handler = ctx.tools["omh_recommend"]["args"][2]
            recommendation = json.loads(
                recommend_handler({"message": "make an image card for this PR with secret-token-123", "limit": 2})
            )
            self.assertEqual(recommendation["schema_version"], "omh_recommend_result/v1")
            self.assertEqual(recommendation["status"], "recommended")
            self.assertEqual(recommendation["source"], "package_recommend")
            self.assertEqual(recommendation["message"]["raw_prompt_echoed"], False)
            self.assertFalse(recommendation["message"]["raw_prompt_stored"])
            self.assertTrue(recommendation["recommendations"])
            self.assertEqual(recommendation["recommendations"][0]["skill"], "img-summary")
            self.assertNotIn("secret-token-123", json.dumps(recommendation, sort_keys=True))
            self.assertIn("<current user request>", recommendation["recommendations"][0]["suggested_prompt"])

            context_handler = ctx.tools["omh_context"]["args"][2]
            context_brief = json.loads(
                context_handler(
                    {
                        "message": "make an image card for this PR with secret-token-123",
                        "source": "discord",
                        "limit": 2,
                        "include_prompt_context": True,
                    }
                )
            )
            self.assertEqual(context_brief["schema_version"], "omh_context_brief/v1")
            self.assertEqual(context_brief["plugin_tool"], "omh_context")
            self.assertEqual(context_brief["source_backend"], "package_context")
            self.assertEqual(context_brief["route_hint"]["primary_workflow"], "img-summary")
            self.assertIn("generic tool can render", context_brief["normal_response_contract"]["when_generic_tool_is_available"])
            self.assertIn("selected=img-summary", context_brief["prompt_context"])
            self.assertFalse(context_brief["message"]["raw_prompt_echoed"])
            self.assertNotIn("secret-token-123", json.dumps(context_brief, sort_keys=True))

            evidence_handler = ctx.tools["omh_gather_evidence"]["args"][2]
            evidence = json.loads(
                evidence_handler(
                    {
                        "commands": ["python3 -m compileall -q ."],
                        "project_root": str(root),
                        "workdir": str(root),
                        "timeout": 30,
                        "truncate": 1000,
                    }
                )
            )
            self.assertEqual(evidence["schema_version"], "omh_evidence_probe/v1")
            self.assertTrue(evidence["all_pass"])
            self.assertEqual(evidence["results"][0]["evidence_type"], "observed_local_command")
            self.assertIn("not executor dispatch", evidence["claim_boundary"])

            rejected = json.loads(
                evidence_handler(
                    {
                        "commands": ["python3 -m compileall -q .; echo bad"],
                        "project_root": str(root),
                        "workdir": str(root),
                    }
                )
            )
            self.assertFalse(rejected["all_pass"])
            self.assertEqual(rejected["results"][0]["evidence_type"], "rejected")
            self.assertIn("shell metacharacters", rejected["results"][0]["output_tail"])

            bounded_root = root / "inside"
            bounded_root.mkdir()
            outside_workdir = json.loads(
                evidence_handler(
                    {
                        "commands": ["python3 -m compileall -q ."],
                        "project_root": str(bounded_root),
                        "workdir": str(root),
                    }
                )
            )
            self.assertIn("workdir must stay within project_root", outside_workdir["error"])

            role_handler = ctx.tools["omh_role"]["args"][2]
            roles = json.loads(role_handler({"action": "list"}))
            self.assertEqual(roles["schema_version"], "omh_role_catalog/v1")
            self.assertIn("planner", roles["roles"])
            self.assertEqual(roles["aliases"]["planning-lead"], "planner")
            self.assertEqual(roles["aliases"]["retained-router"], "guide")
            self.assertNotIn("retained-cognition", roles["aliases"])
            role_payload = json.loads(role_handler({"action": "read", "role": "planner"}))
            self.assertEqual(role_payload["schema_version"], "omh_role_context/v1")
            self.assertEqual(role_payload["status"], "available")
            self.assertEqual(role_payload["role"], "planner")
            self.assertEqual(role_payload["resolved_role"], "planner")
            self.assertIn("Planner", role_payload["context"])
            self.assertIn("OMH Role Context", role_payload["context"])
            self.assertIn("OMH workflow-layer responsibility context", role_payload["context"])
            self.assertIn("not runtime delegation", role_payload["claim_boundary"])
            legacy_role_payload = json.loads(role_handler({"action": "read", "role": "planning-lead"}))
            self.assertEqual(legacy_role_payload["status"], "available")
            self.assertEqual(legacy_role_payload["role"], "planner")
            self.assertEqual(legacy_role_payload["requested_role"], "planning-lead")
            self.assertEqual(legacy_role_payload["resolved_role"], "planner")
            guide_role_payload = json.loads(role_handler({"action": "read", "role": "retained-router"}))
            self.assertEqual(guide_role_payload["status"], "available")
            self.assertEqual(guide_role_payload["resolved_role"], "guide")
            category_seed_payload = json.loads(role_handler({"action": "read", "role": "retained-cognition"}))
            self.assertEqual(category_seed_payload["status"], "unknown_role")

            role_hook_payload = ctx.hooks["pre_llm_call"](
                omh_home=str(omh_home),
                user_message="[omh-role:planning-lead] do not leak this exact sentence",
                is_first_turn=True,
            )
            self.assertIsNotNone(role_hook_payload)
            role_context = role_hook_payload["context"]
            self.assertIn("[OMH Role: planner]", role_context)
            self.assertIn("Planner", role_context)
            self.assertNotIn("do not leak this exact sentence", role_context)

            self.assertIsNone(
                ctx.hooks["pre_tool_call"](
                    tool_name="delegate_task",
                    tool_input={"goal": "[omh-role:planning-lead] prepare a plan"},
                )
            )
            tool_warning = ctx.hooks["pre_tool_call"](
                tool_name="delegate_task",
                tool_input={"goal": "[omh-role:nope] prepare a plan"},
            )
            self.assertIsNotNone(tool_warning)
            self.assertIn("Unknown role 'nope'", tool_warning["context"])
            self.assertIn("planner", tool_warning["context"])

            tool_checkpoint = ctx.hooks["pre_tool_call"](
                tool_name="image_generate",
                tool_input={"prompt": "secret-token-123 should not leak"},
            )
            self.assertIsNotNone(tool_checkpoint)
            self.assertIn("[OMH Tool Checkpoint]", tool_checkpoint["context"])
            self.assertIn("schema=omh_generic_tool_checkpoint/v1", tool_checkpoint["context"])
            self.assertIn("workflow=img-summary", tool_checkpoint["context"])
            self.assertIn("next_action=prepare_visual_prompt_card", tool_checkpoint["context"])
            checkpoint_payload = tool_checkpoint["omh_generic_tool_checkpoint"]
            self.assertEqual(checkpoint_payload["schema_version"], "omh_generic_tool_checkpoint/v1")
            self.assertEqual(checkpoint_payload["source"], "pre_tool_call")
            self.assertEqual(checkpoint_payload["tool_name"], "image_generate")
            self.assertEqual(checkpoint_payload["tool_family"], "image_tools")
            self.assertEqual(checkpoint_payload["primary_workflow"], "img-summary")
            self.assertEqual(checkpoint_payload["primary_next_action"], "prepare_visual_prompt_card")
            self.assertFalse(checkpoint_payload["privacy"]["raw_tool_input_stored"])
            self.assertFalse(checkpoint_payload["privacy"]["raw_tool_input_echoed"])
            self.assertNotIn("secret-token-123", tool_checkpoint["context"])
            self.assertNotIn("should not leak", tool_checkpoint["context"])
            self.assertNotIn("secret-token-123", json.dumps(checkpoint_payload, sort_keys=True))
            self.assertNotIn("should not leak", json.dumps(checkpoint_payload, sort_keys=True))

            session_checkpoint = ctx.hooks["on_session_end"](omh_home=str(omh_home))
            self.assertEqual(session_checkpoint["status"], "checkpoint_written")
            checkpoint = json.loads((omh_home / "runtime" / "plugin-session-end.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["schema_version"], "omh_plugin_session_end/v1")
            self.assertEqual(checkpoint["privacy"], "metadata_only")
            payload_after_checkpoint = json.loads(handler({"omh_home": str(omh_home), "limit": 1}))
            self.assertEqual(
                payload_after_checkpoint["plugin_session_end"]["schema_version"],
                "omh_plugin_session_end/v1",
            )

            hook_payload = ctx.hooks["pre_llm_call"](
                omh_home=str(omh_home),
                user_message="this raw prompt should not leak",
                is_first_turn=True,
            )
            self.assertIsNotNone(hook_payload)
            context = hook_payload["context"]
            context_brief = hook_payload["omh_context_brief"]
            self.assertIn("[OMH Awareness]", context)
            self.assertIn("Hermes-native workflow guidance", context)
            self.assertIn("consider OMH before generic tools", context)
            self.assertIn("Use message-specific route hints", context)
            self.assertIn("not observed execution", context)
            self.assertIn("omh_capabilities", context)
            self.assertIn("omh_context", context)
            self.assertIn("omh_status/omh_hud", context)
            self.assertIn("[omh]", context)
            self.assertIn("prepared handoffs are not execution", context)
            self.assertNotIn("Pattern cards:", context)
            self.assertNotIn("Common cues:", context)
            self.assertNotIn("Tools:", context)
            self.assertEqual(context_brief["schema_version"], "omh_context_brief/v1")
            self.assertEqual(context_brief["source"], "pre_llm_call")
            self.assertEqual(context_brief["message"]["raw_prompt_stored"], False)
            self.assertEqual(context_brief["message"]["raw_prompt_echoed"], False)
            self.assertNotIn("this raw prompt should not leak", context)
            self.assertNotIn("this raw prompt should not leak", json.dumps(context_brief, sort_keys=True))

            empty_first_turn_context = ctx.hooks["pre_llm_call"](
                omh_home=str(root / ".empty-omh"),
                user_message="make an image summary card for this PR",
                is_first_turn=True,
            )
            self.assertIsNotNone(empty_first_turn_context)
            self.assertIn("[OMH Awareness]", empty_first_turn_context["context"])
            self.assertIn("[OMH Route Hint]", empty_first_turn_context["context"])
            self.assertIn("selected=img-summary", empty_first_turn_context["context"])
            self.assertNotIn("Pattern cards:", empty_first_turn_context["context"])
            self.assertNotIn("make an image summary card for this PR", empty_first_turn_context["context"])

            mid_session_visual_context = ctx.hooks["pre_llm_call"](
                omh_home=str(root / ".empty-omh"),
                user_message="회의록을 세로 요약 이미지 카드로 만들어줘",
                is_first_turn=False,
            )
            self.assertIsNotNone(mid_session_visual_context)
            self.assertIn("[OMH Awareness]", mid_session_visual_context["context"])
            self.assertEqual(
                mid_session_visual_context["omh_context_brief"]["route_hint"]["primary_workflow"],
                "img-summary",
            )
            self.assertIn("selected=img-summary", mid_session_visual_context["context"])
            self.assertIn("not_evidence_yet=file export", mid_session_visual_context["context"])
            self.assertNotIn("Pattern cards:", mid_session_visual_context["context"])
            self.assertNotIn("회의록을 세로 요약 이미지 카드로 만들어줘", mid_session_visual_context["context"])
            self.assertNotIn(
                "회의록을 세로 요약 이미지 카드로 만들어줘",
                json.dumps(mid_session_visual_context["omh_context_brief"], sort_keys=True),
            )

            mid_session_generic_context = ctx.hooks["pre_llm_call"](
                omh_home=str(root / ".empty-omh"),
                user_message="tell me a short joke",
                is_first_turn=False,
            )
            self.assertIsNone(mid_session_generic_context)

            suppressed_awareness_context = ctx.hooks["pre_llm_call"](
                omh_home=str(root / ".empty-omh"),
                user_message="make a PR summary image card",
                is_first_turn=False,
                include_omh_awareness=False,
            )
            self.assertIsNone(suppressed_awareness_context)

            mid_session_role_context = ctx.hooks["pre_llm_call"](
                omh_home=str(root / ".empty-omh"),
                user_message="[omh-role:planner] do not leak this mid-session prompt",
                is_first_turn=False,
                include_omh_awareness=False,
            )
            self.assertIsNotNone(mid_session_role_context)
            self.assertIn("[OMH Role: planner]", mid_session_role_context["context"])
            self.assertNotIn("do not leak this mid-session prompt", mid_session_role_context["context"])


if __name__ == "__main__":
    unittest.main()
