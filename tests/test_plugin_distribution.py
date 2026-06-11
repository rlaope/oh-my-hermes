from __future__ import annotations

import importlib.resources as resources
import importlib.util
import json
import sys
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.paths import resolve_paths
from omh.plugin_pack import inspect_plugin_bundle


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
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        packages = set(pyproject["tool"]["setuptools"]["packages"])
        self.assertIn("omh.plugin_bundle.omh", packages)
        self.assertIn("omh.plugin_bundle.omh", pyproject["tool"]["setuptools"]["package-data"])

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
            self.assertEqual(plugin["registered_tools"], ["omh_hud", "omh_status"])
            self.assertEqual(plugin["registered_hooks"], ["pre_llm_call"])

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
            self.assertIn("managed plugin files changed", stderr)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin", "--force"])[0], 0)

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
                    "Safely add feature without overclaiming.",
                ]
            )
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["runtime"]["run"]["run_id"]

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            ctx = FakeHermesContext()
            module.register(ctx)
            self.assertIn("omh_hud", ctx.tools)
            self.assertIn("omh_status", ctx.tools)
            self.assertIn("pre_llm_call", ctx.hooks)

            hud_handler = ctx.tools["omh_hud"]["args"][2]
            hud_payload = json.loads(hud_handler({"omh_home": str(omh_home), "hermes_home": str(hermes_home), "limit": 1}))
            self.assertEqual(hud_payload["schema_version"], "omh_hud/v1")
            self.assertIn("[omh]", hud_payload["display"]["line"])
            self.assertEqual(hud_payload["runtime"]["evidence_state"], "prepared_not_observed")
            self.assertEqual(hud_payload["tokens"]["status"], "unobserved")

            handler = ctx.tools["omh_status"]["args"][2]
            payload = json.loads(handler({"omh_home": str(omh_home), "limit": 1}))
            self.assertEqual(payload["schema_version"], "omh_status/v1")
            self.assertEqual(payload["runs"][0]["run_id"], run_id)
            self.assertTrue(payload["runs"][0]["prepared_handoff"])
            self.assertFalse(payload["runs"][0]["execution_observed"])
            self.assertIn("not execution evidence", payload["evidence_boundary"]["prepared_handoff"])

            hook_payload = ctx.hooks["pre_llm_call"](
                omh_home=str(omh_home),
                user_message="this raw prompt should not leak",
                is_first_turn=True,
            )
            self.assertIsNotNone(hook_payload)
            context = hook_payload["context"]
            self.assertIn("[omh]", context)
            self.assertIn("prepared handoffs are not execution", context)
            self.assertNotIn("this raw prompt should not leak", context)


if __name__ == "__main__":
    unittest.main()
