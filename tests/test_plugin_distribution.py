from __future__ import annotations

import hashlib
import importlib.resources as resources
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
import unittest
from types import ModuleType
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands import setup as setup_module
from omh.paths import resolve_paths
from omh.install.plugin_loader_observation import observe_real_loader_registration
from omh.plugin_pack import inspect_plugin_bundle
from omh.plugin_bundle.omh.tools import evidence_tool
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS, TOOL_FILE_STEMS
from omh.release_smoke_core import CommandResult


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
    def test_plugin_manifest_conformance_catches_missing_kind(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--with-plugin",
                    ]
                )[0],
                0,
            )
            plugin_yaml = hermes_home / "plugins" / "omh" / "plugin.yaml"
            plugin_yaml.write_text(
                "\n".join(
                    line
                    for line in plugin_yaml.read_text(encoding="utf-8").splitlines()
                    if not line.startswith("kind:")
                )
                + "\n",
                encoding="utf-8",
            )

            inspection = inspect_plugin_bundle(resolve_paths(omh_home, hermes_home))

            conformance = inspection["plugin_manifest_conformance"]
            self.assertFalse(conformance["ok"])
            self.assertEqual(conformance["kind"], "")
            self.assertIn("kind", conformance["invalid_fields"])
            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "doctor",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            check = next(
                item
                for item in json.loads(stdout)["checks"]
                if item["name"] == "plugin_manifest_conformance"
            )
            self.assertFalse(check["ok"])

    def test_plugin_manifest_conformance_matches_registered_surface(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--with-plugin",
                    ]
                )[0],
                0,
            )

            inspection = inspect_plugin_bundle(resolve_paths(omh_home, hermes_home))

            conformance = inspection["plugin_manifest_conformance"]
            self.assertTrue(conformance["ok"])
            self.assertEqual(conformance["kind"], "standalone")
            self.assertEqual(conformance["declared_tools"], list(PROVIDED_TOOLS))
            self.assertEqual(conformance["declared_hooks"], list(PROVIDED_HOOKS))
            self.assertEqual(conformance["invalid_fields"], [])

    def test_real_loader_observation_names_absent_hermes(self) -> None:
        with TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "plugins" / "omh"
            plugin_dir.mkdir(parents=True)

            observation = observe_real_loader_registration(
                plugin_dir,
                python_executable=Path(tmp) / "missing-python",
            )

            self.assertFalse(observation["observed"])
            self.assertEqual(observation["reason"], "hermes_not_installed")

    def test_real_loader_observation_uses_isolated_home(self) -> None:
        with TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "source" / "omh"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.yaml").write_text("name: omh\nkind: standalone\n", encoding="utf-8")
            (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
            seen: dict[str, object] = {}

            def runner(command, timeout_seconds, env):
                seen["command"] = list(command)
                seen["timeout_seconds"] = timeout_seconds
                seen["env"] = dict(env or {})
                isolated_home = Path(str((env or {})["HERMES_HOME"]))
                self.assertNotEqual(isolated_home, plugin_dir.parent.parent)
                self.assertTrue((isolated_home / "plugins" / "omh" / "plugin.yaml").is_file())
                return CommandResult(
                    command=command,
                    returncode=0,
                    stdout=(
                        'OMH_PLUGIN_LOADER_OBSERVATION={"enabled":true,"error":null,'
                        f'"tools":{json.dumps(list(PROVIDED_TOOLS))},'
                        f'"hooks":{json.dumps(list(PROVIDED_HOOKS))}'
                        "}\n"
                    ),
                )

            observation = observe_real_loader_registration(
                plugin_dir,
                python_executable=Path(sys.executable),
                runner=runner,
            )

            self.assertTrue(observation["observed"])
            self.assertTrue(observation["ok"])
            self.assertEqual(observation["registered_tools"], list(PROVIDED_TOOLS))
            self.assertEqual(observation["registered_hooks"], list(PROVIDED_HOOKS))
            self.assertEqual(seen["timeout_seconds"], 120)

    def test_real_loader_observation_detects_zero_registered_tools(self) -> None:
        with TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "omh"
            plugin_dir.mkdir()
            (plugin_dir / "plugin.yaml").write_text("name: omh\n", encoding="utf-8")
            (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

            def runner(command, timeout_seconds, env):
                return CommandResult(
                    command=command,
                    returncode=0,
                    stdout=(
                        "OMH_PLUGIN_LOADER_OBSERVATION="
                        '{"enabled":false,"error":"exclusive plugin","tools":[],"hooks":[]}\n'
                    ),
                )

            observation = observe_real_loader_registration(
                plugin_dir,
                python_executable=Path(sys.executable),
                runner=runner,
            )

            self.assertTrue(observation["observed"])
            self.assertFalse(observation["ok"])
            self.assertEqual(observation["registered_tools"], [])
            self.assertEqual(observation["registered_hooks"], [])
            self.assertEqual(observation["error"], "exclusive plugin")

    def test_doctor_names_fake_context_and_unobserved_real_loader(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--with-plugin",
                    ]
                )[0],
                0,
            )

            with mock.patch(
                "omh.maintenance.doctor.observe_real_loader_registration",
                return_value={
                    "observed": False,
                    "ok": False,
                    "reason": "hermes_not_installed",
                    "registered_tools": [],
                    "registered_hooks": [],
                },
            ):
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "doctor",
                    ]
                )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            checks = {item["name"]: item for item in json.loads(stdout)["checks"]}
            self.assertTrue(checks["plugin_register_smoke"]["ok"])
            loader = checks["plugin_loader_observed"]
            self.assertTrue(loader["ok"])
            self.assertFalse(loader["observed"])
            self.assertEqual(loader["severity"], "warning")

    def test_doctor_human_summary_distinguishes_loader_observation(self) -> None:
        checks = [
            {"name": "plugin_register_smoke", "ok": True},
            {
                "name": "plugin_loader_observed",
                "ok": True,
                "observed": True,
                "severity": "ok",
            },
        ]
        with mock.patch.object(
            setup_module,
            "tr",
            side_effect=lambda language, key: key,
        ):
            lines = setup_module._doctor_observation_boundary_lines(checks, language="en")

        self.assertEqual(
            lines,
            [
                "doctor_plugin_bridge_ready",
                "doctor_plugin_loader_observed",
            ],
        )

    def test_doctor_fails_when_real_loader_registers_zero_tools(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--with-plugin",
                    ]
                )[0],
                0,
            )

            with mock.patch(
                "omh.maintenance.doctor.observe_real_loader_registration",
                return_value={
                    "observed": True,
                    "ok": False,
                    "reason": "registration_mismatch",
                    "error": "exclusive plugin",
                    "registered_tools": [],
                    "registered_hooks": [],
                },
            ):
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "doctor",
                    ]
                )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            checks = {item["name"]: item for item in json.loads(stdout)["checks"]}
            loader = checks["plugin_loader_observed"]
            self.assertFalse(loader["ok"])
            self.assertTrue(loader["observed"])
            self.assertEqual(loader["severity"], "blocking")

    def test_bundled_plugin_resource_is_packaged(self) -> None:
        root = resources.files("omh.plugin_bundle.omh")
        self.assertTrue(root.joinpath("plugin.yaml").is_file())
        self.assertTrue(root.joinpath("config.yaml").is_file())
        self.assertTrue(root.joinpath("references", "role-planner.md").is_file())
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        packages = pyproject["tool"]["setuptools"]["packages"]
        package_dir = pyproject["tool"]["setuptools"]["package-dir"]
        self.assertIn("omh.plugin_bundle.omh", packages)
        self.assertEqual(package_dir["omh.plugin_bundle"], "src/plugin_bundle")
        self.assertTrue((Path("src") / "plugin_bundle" / "omh" / "__init__.py").is_file())
        self.assertTrue((Path("src") / "plugin_bundle" / "omh" / "references" / "__init__.py").is_file())
        self.assertIn("omh.plugin_bundle.omh", pyproject["tool"]["setuptools"]["package-data"])
        self.assertIn(
            "*.md",
            pyproject["tool"]["setuptools"]["package-data"]["omh.plugin_bundle.omh.references"],
        )
        self.assertTrue(root.joinpath("tools", "capability_families.json").is_file())
        self.assertIn(
            "capability_families.json",
            pyproject["tool"]["setuptools"]["package-data"]["omh.plugin_bundle.omh.tools"],
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

    def test_source_layout_plugin_awareness_uses_package_loopability_helpers(self) -> None:
        script = r"""
import json
from omh.plugin_bundle.omh.awareness import awareness_route_hint

cases = [
    ("run a loop to improve first-run experience", "choose_permission_profile", "choosing the loop permission profile"),
    ("Make this a 100k-star OSS", "reframe_north_star", "reframing the north-star goal"),
    ("./loop change the button color", "route_direct_task", "routing the direct task"),
]
observed = []
for message, expected_action, expected_label in cases:
    payload = awareness_route_hint(message)
    observed.append(
        {
            "message": message,
            "workflow": payload.get("primary_workflow"),
            "action": payload.get("primary_next_action"),
            "label": payload.get("primary_next_action_label"),
        }
    )
    assert payload.get("primary_workflow") == "loop", observed[-1]
    assert payload.get("primary_next_action") == expected_action, observed[-1]
    assert payload.get("primary_next_action_label") == expected_label, observed[-1]
print(json.dumps(observed, ensure_ascii=False))
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path.cwd(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        observed = json.loads(result.stdout)
        self.assertEqual(
            [item["action"] for item in observed],
            ["choose_permission_profile", "reframe_north_star", "route_direct_task"],
        )

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

    def test_context_tool_distinguishes_missing_package_from_package_call_failure(self) -> None:
        from omh.plugin_bundle.omh.tools import context_tool

        args = {"message": "plan a risky refactor with secret-token-123", "limit": 2}

        # Case (a): the package genuinely cannot be imported. This is the true
        # standalone fallback and must keep working.
        with mock.patch.dict(sys.modules, {"omh.context": None}):
            fallback_payload = json.loads(context_tool.omh_context_handler(dict(args)))
        self.assertEqual(fallback_payload["source_backend"], "standalone_plugin_bundle_fallback")
        self.assertEqual(fallback_payload["schema_version"], "omh_context_brief/v1")
        self.assertFalse(fallback_payload["message"]["raw_prompt_echoed"])

        # Case (b): the package imports fine but the delegated call raises. This must
        # not be mislabeled as the same normal standalone fallback.
        with mock.patch("omh.context.build_context_brief", side_effect=RuntimeError("package-context-boom")):
            error_payload = json.loads(context_tool.omh_context_handler(dict(args)))
        self.assertEqual(error_payload["source_backend"], "package_context_error")
        self.assertNotEqual(error_payload["source_backend"], "standalone_plugin_bundle_fallback")
        self.assertEqual(error_payload["status"], "error")
        self.assertEqual(error_payload["error"], "package_backend_error")
        self.assertEqual(error_payload["error_type"], "RuntimeError")
        self.assertTrue(error_payload["degraded"])
        self.assertFalse(error_payload["message"]["raw_prompt_echoed"])
        serialized = json.dumps(error_payload, sort_keys=True)
        self.assertNotIn("package-context-boom", serialized)
        self.assertNotIn("secret-token-123", serialized)

    def test_memory_tool_needs_no_package_and_still_answers(self) -> None:
        from omh.plugin_bundle.omh.tools import memory_tool

        # The Hermes process cannot import the `omh` package, so a tool that
        # delegated there answered "package_absent" on the only host it exists
        # for. Blocking the package must now change nothing: the reader is in
        # the bundle, which is what makes the tool work at all.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            memories = root / ".hermes" / "memories"
            memories.mkdir(parents=True)
            (memories / "MEMORY.md").write_text("a remembered fact", encoding="utf-8")
            env = {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}

            with mock.patch.dict(sys.modules, {"omh.memory": None, "omh.paths": None}):
                with mock.patch.dict(os.environ, env):
                    payload = json.loads(memory_tool.omh_memory_handler({}))

        self.assertEqual(payload["source_backend"], "bundle_memory")
        self.assertEqual(payload["schema_version"], "hermes_memory_bridge/v1")
        self.assertNotIn("status", payload)  # not the unavailable shape
        self.assertEqual([f["label"] for f in payload["files"]], ["MEMORY.md", "USER.md"])
        self.assertEqual(payload["files"][0]["chars"], len("a remembered fact"))

    def test_memory_tool_keeps_a_read_failure_apart_from_an_empty_comparison(self) -> None:
        from omh.plugin_bundle.omh.tools import memory_tool

        with mock.patch.object(
            memory_tool, "build_hermes_memory_bridge", side_effect=RuntimeError("bundle-memory-boom")
        ):
            error_payload = json.loads(memory_tool.omh_memory_handler({}))
        # Returning an empty comparison here would read as "Hermes remembers
        # nothing" when OMH simply could not read the file.
        self.assertEqual(error_payload["source_backend"], "bundle_memory_error")
        self.assertEqual(error_payload["status"], "unavailable")
        self.assertEqual(error_payload["reason"], "RuntimeError")
        self.assertNotIn("bundle-memory-boom", json.dumps(error_payload, sort_keys=True))
        for absent in ("files", "already_in_hermes", "promotable", "approved_records"):
            self.assertNotIn(absent, error_payload)

    def test_recommend_tool_distinguishes_missing_package_from_package_call_failure(self) -> None:
        from omh.plugin_bundle.omh.tools import recommend_tool

        args = {"message": "plan a risky refactor with secret-token-123", "limit": 2}

        # Case (a): the package genuinely cannot be imported. This is the true
        # standalone fallback and must keep working.
        with mock.patch.dict(sys.modules, {"omh.routing.recommend": None}):
            fallback_payload = json.loads(recommend_tool.omh_recommend_handler(dict(args)))
        self.assertEqual(fallback_payload["source"], "standalone_plugin_bundle_fallback")
        self.assertIn(fallback_payload["status"], {"recommended", "no_match"})
        self.assertNotIn("error", fallback_payload)

        # Case (b): the package imports fine but the delegated call raises. This must
        # not be mislabeled as the same normal standalone fallback.
        with mock.patch("omh.routing.recommend.recommend_skills", side_effect=RuntimeError("package-recommend-boom")):
            error_payload = json.loads(recommend_tool.omh_recommend_handler(dict(args)))
        self.assertEqual(error_payload["source"], "package_recommend_error")
        self.assertNotEqual(error_payload["source"], "standalone_plugin_bundle_fallback")
        self.assertEqual(error_payload["status"], "error")
        self.assertEqual(error_payload["error"], "package_backend_error")
        self.assertEqual(error_payload["error_type"], "RuntimeError")
        self.assertTrue(error_payload["degraded"])
        self.assertEqual(error_payload["recommendations"], [])
        serialized = json.dumps(error_payload, sort_keys=True)
        self.assertNotIn("package-recommend-boom", serialized)
        self.assertNotIn("secret-token-123", serialized)

    def test_pre_llm_call_distinguishes_an_idle_host_from_a_failed_status_read(self) -> None:
        # This is the bundle surface that ships to third-party hosts, so the
        # degraded path is exercised here as an installed host would hit it.
        from omh.plugin_bundle.omh import awareness as awareness_module
        from omh.plugin_bundle.omh.hooks import llm_hooks

        awareness_module._awareness_context_matches_message_cached.cache_clear()
        awareness_module._awareness_route_hint_cached.cache_clear()

        message = "tell me a short joke about secret-token-123"

        # Case (a): a genuinely idle host with an empty runtime home. Nothing
        # to report, so the hook keeps returning None exactly as today.
        with TemporaryDirectory() as tmp:
            idle_payload = llm_hooks.pre_llm_call(
                omh_home=tmp, hermes_home=tmp, user_message=message, is_first_turn=False
            )
        self.assertIsNone(idle_payload)

        # Case (b): the status read raises. This must not be mislabeled as the
        # same idle host.
        awareness_module._awareness_context_matches_message_cached.cache_clear()
        awareness_module._awareness_route_hint_cached.cache_clear()
        with TemporaryDirectory() as tmp:
            with mock.patch.object(llm_hooks, "read_omh_activity", side_effect=RuntimeError("status-boom")):
                error_payload = llm_hooks.pre_llm_call(
                    omh_home=tmp, hermes_home=tmp, user_message=message, is_first_turn=False
                )

        self.assertIsNotNone(error_payload)
        assert error_payload is not None
        degradation = error_payload["omh_degradation"]
        self.assertEqual(degradation["schema_version"], "omh_degradation/v1")
        self.assertTrue(degradation["degraded"])
        self.assertEqual([row["component"] for row in degradation["components"]], ["runtime_status_read"])
        self.assertEqual(degradation["components"][0]["error_type"], "RuntimeError")
        self.assertFalse(degradation["privacy"]["error_message_stored"])
        self.assertIn("[OMH Degraded]", error_payload["context"])
        # PM-1: no status panel is implied, because the status fields are still absent.
        self.assertNotIn("runs", error_payload)
        self.assertNotIn("[OMH] Native bridge status context.", error_payload["context"])
        serialized = json.dumps(error_payload, sort_keys=True)
        self.assertNotIn("status-boom", serialized)
        self.assertNotIn("secret-token-123", serialized)

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
                    "omh_delegate_route",
                    "omh_gather_evidence",
                    "omh_hud",
                    "omh_interact",
                    "omh_memory",
                    "omh_probe",
                    "omh_recommend",
                    "omh_role",
                    "omh_source_trust",
                    "omh_status",
                    "omh_todo",
                ],
            )
            self.assertEqual(
                plugin["registered_hooks"],
                ["on_session_end", "pre_llm_call", "pre_tool_call", "pre_verify"],
            )

            inspection = inspect_plugin_bundle(resolve_paths(omh_home, hermes_home))
            self.assertTrue(inspection["plugin_distribution_ready"])

            doctor_status, doctor_stdout, doctor_stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])
            self.assertEqual(doctor_stderr, "")
            self.assertEqual(doctor_status, 0)
            checks = {check["name"]: check for check in json.loads(doctor_stdout)["checks"]}
            self.assertTrue(checks["plugin_import_smoke"]["ok"])
            self.assertTrue(checks["plugin_register_smoke"]["ok"])

    def test_setup_smoke_accepts_host_without_optional_pre_verify_hook(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            hermes_cli = ModuleType("hermes_cli")
            hermes_plugins = ModuleType("hermes_cli.plugins")
            setattr(hermes_cli, "plugins", hermes_plugins)
            setattr(
                hermes_plugins,
                "VALID_HOOKS",
                {"on_session_end", "pre_llm_call", "pre_tool_call"},
            )

            with mock.patch.dict(
                sys.modules,
                {"hermes_cli": hermes_cli, "hermes_cli.plugins": hermes_plugins},
            ):
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--with-plugin",
                    ]
                )
                inspection = inspect_plugin_bundle(resolve_paths(omh_home, hermes_home))

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            plugin = json.loads(stdout)["plugin_distribution"]
            self.assertEqual(
                plugin["registered_hooks"],
                ["on_session_end", "pre_llm_call", "pre_tool_call"],
            )
            self.assertTrue(plugin["register_smoke"])
            self.assertEqual(plugin.get("missing_registered_hooks", []), [])

            self.assertTrue(inspection["plugin_distribution_ready"])

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
            init_py.write_text(stale_text, encoding="utf-8", newline="")
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
                    "implement safe status feature in src/omh/runtime/status.py without overclaiming",
                ]
            )
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["runtime"]["run"]["run_id"]

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            installed_awareness = __import__(
                f"{module.__name__}.awareness",
                fromlist=["awareness_route_hint"],
            )
            specialist_cases = (
                ("Compare Q2 actuals against budget and flag cash risks.", "finance-analysis"),
                ("Create an interview scorecard and debrief plan.", "people-ops"),
                ("Review this vendor DPA for data-processing risks.", "legal-compliance-review"),
                ("Draft a reply for this customer and assess engineering escalation.", "support-operations"),
                ("Design a curriculum with learning objectives.", "curriculum-design"),
                ("Review terminology consistency and cultural fit.", "localization-review"),
                ("Build a discovery plan and qualification questions.", "sales-development"),
                ("Create a PRD with prioritization options.", "product-brief"),
            )
            for message, expected_workflow in specialist_cases:
                with self.subTest(installed_specialist=expected_workflow):
                    self.assertEqual(
                        installed_awareness.awareness_route_hint(message)["primary_workflow"],
                        expected_workflow,
                    )

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
                    "worker_dispatch",
                    "--summary",
                    "executor session opened for the prepared handoff",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stdout)["journal_event"]["event"], "executor_dispatch_observed")

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

            with mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "model-secret-do-not-print",
                    "AWS_SECRET_ACCESS_KEY": "cloud-secret-do-not-print",
                    "BUZZ_PRIVATE_KEY": "buzz-secret-do-not-print",
                    "PYTHONPATH": "/tmp/inject",
                    "DYLD_INSERT_LIBRARIES": "/tmp/inject.dylib",
                },
                clear=False,
            ), mock.patch.object(evidence_tool.subprocess, "run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                safe = json.loads(
                    evidence_handler(
                        {
                            "commands": ["python3 -m compileall -q ."],
                            "project_root": str(root),
                            "workdir": str(root),
                        }
                    )
                )
            self.assertTrue(safe["all_pass"])
            child_env = run.call_args.kwargs["env"]
            self.assertEqual(
                set(child_env),
                {
                    "HOME",
                    "LANG",
                    "LC_ALL",
                    "PATH",
                    "PYTHONNOUSERSITE",
                    "PYTHONPYCACHEPREFIX",
                    "TMPDIR",
                },
            )
            self.assertNotIn("OPENAI_API_KEY", child_env)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", child_env)
            self.assertNotIn("BUZZ_PRIVATE_KEY", child_env)
            self.assertNotIn("PYTHONPATH", child_env)
            self.assertNotIn("DYLD_INSERT_LIBRARIES", child_env)

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
            self.assertIsNone(tool_checkpoint)

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
                user_message="review this PR; this raw prompt should not leak",
                is_first_turn=True,
            )
            self.assertIsNotNone(hook_payload)
            context = hook_payload["context"]
            context_brief = hook_payload["omh_context_brief"]
            self.assertIn("[OMH Awareness]", context)
            self.assertIn("Hermes-native workflow guidance", context)
            self.assertIn("durable, evidence-bounded artifact or handoff", context)
            self.assertIn("tracks prepared against observed", context)
            self.assertNotIn("consider OMH before generic tools", context)
            self.assertIn("Use message-specific route hints", context)
            self.assertIn("not observed execution", context)
            self.assertIn("omh_capabilities", context)
            self.assertIn("omh_context", context)
            self.assertIn("omh_status/omh_hud", context)
            self.assertNotIn("Native bridge status context", context)
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

            loop_route_context = ctx.hooks["pre_llm_call"](
                omh_home=str(root / ".empty-omh"),
                user_message="Make this a 100k-star OSS",
                is_first_turn=False,
            )
            self.assertIsNotNone(loop_route_context)
            loop_route_hint = loop_route_context["omh_context_brief"]["route_hint"]
            self.assertEqual(loop_route_hint["primary_workflow"], "loop")
            self.assertEqual(loop_route_hint["primary_next_action"], "reframe_north_star")
            self.assertIn("selected=loop", loop_route_context["context"])
            self.assertIn("next_action=reframe_north_star", loop_route_context["context"])
            self.assertNotIn("next_action=assess_loopability", loop_route_context["context"])
            self.assertNotIn("Make this a 100k-star OSS", loop_route_context["context"])

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


class UpdateRefreshesTheBundleTests(unittest.TestCase):
    """`omh update` used to leave the installed bundle at its old version.

    `install_plugin_bundle` was reachable only from `cmd_setup`, so an operator
    who ran `omh update` got new workflows against old plugin code -- the tools,
    hooks, and now the memory provider under `$HERMES_HOME/plugins/omh/` stayed
    where the last `omh setup` left them. AGENTS.md tells ordinary users they
    need setup, update, and doctor; update was the one not doing its name.
    """

    def _bundle_dir(self, hermes_home: Path) -> Path:
        return hermes_home / "plugins" / "omh"

    def test_update_reinstalls_the_bundle_tree(self) -> None:
        # The bundle is replaced wholesale by an atomic rename of a freshly
        # copied tree, so a file the source does not contain cannot survive a
        # real reinstall. That makes a stray file the honest observable: editing
        # a managed file instead would trip the drift guard, which is a
        # different behaviour and correctly refuses.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, _, stderr = run_cli(base + ["setup"])
            self.assertEqual(status, 0, stderr)

            stray = self._bundle_dir(root / ".hermes") / "stray_from_an_older_version.py"
            stray.write_text("# left behind by an older bundle\n", encoding="utf-8")

            status, _, stderr = run_cli(base + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertFalse(stray.exists())
            self.assertTrue((self._bundle_dir(root / ".hermes") / "memory_provider.py").is_file())

    def test_update_does_not_install_a_bundle_setup_never_installed(self) -> None:
        # Installing it here would write plugin files without the Hermes
        # enablement setup also does, and half that pair is worse than neither.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, _, stderr = run_cli(base + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertFalse(self._bundle_dir(root / ".hermes").exists())

    def test_a_dry_run_update_leaves_the_installed_bundle_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            run_cli(base + ["setup"])
            stray = self._bundle_dir(root / ".hermes") / "stray_from_an_older_version.py"
            stray.write_text("# left behind by an older bundle\n", encoding="utf-8")

            status, _, stderr = run_cli(base + ["update", "--dry-run"])
            self.assertEqual(status, 0, stderr)
            self.assertTrue(stray.exists())

    def test_a_drifted_bundle_does_not_fail_the_update(self) -> None:
        # A managed file edited outside OMH makes the reinstall refuse. Update
        # must still succeed for everything else; `omh doctor` reports the drift
        # with the `omh setup --force` instruction that repairs it.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            run_cli(base + ["setup"])
            marker = self._bundle_dir(root / ".hermes") / "__init__.py"
            marker.write_text("# edited outside OMH\n", encoding="utf-8")

            status, _, stderr = run_cli(base + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "# edited outside OMH\n")


class UpdateCarriesRegistrationTests(unittest.TestCase):
    """`omh setup` is meant to be run once, and it stopped being.

    Every release that added something to Hermes' config which only setup wrote
    made setup a recurring chore: update refreshed skills and the bundle, the
    new key never landed, and the instruction became "run setup again". The
    memory-provider slot was the latest instance and will not be the last.
    """

    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def _config(self, root: Path) -> Path:
        return root / ".hermes" / "config.yaml"

    def _downgrade(self, root: Path) -> None:
        """Make a registered install look like one from before the slot existed."""
        config = self._config(root)
        config.write_text(config.read_text(encoding="utf-8").replace("  provider: omh", "  provider: ''"), encoding="utf-8")

    def test_update_alone_brings_a_registered_install_up_to_date(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            self._downgrade(root)
            self.assertIn("provider: ''", self._config(root).read_text(encoding="utf-8"))

            status, _, stderr = run_cli(self._base(root) + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertIn("provider: omh", self._config(root).read_text(encoding="utf-8"))

    def test_update_does_not_register_an_install_setup_never_registered(self) -> None:
        # Someone who unregistered OMH deliberately must not have update put it
        # back, and a first registration stays setup's to make.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(self._base(root) + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertFalse(self._config(root).exists())

    def test_update_never_takes_a_slot_another_product_holds(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            config = self._config(root)
            config.write_text(config.read_text(encoding="utf-8").replace("  provider: omh", "  provider: honcho"), encoding="utf-8")

            status, _, stderr = run_cli(self._base(root) + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertIn("provider: honcho", config.read_text(encoding="utf-8"))

    def test_a_dry_run_update_rewrites_no_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            self._downgrade(root)
            before = self._config(root).read_text(encoding="utf-8")

            status, _, stderr = run_cli(self._base(root) + ["update", "--dry-run"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(self._config(root).read_text(encoding="utf-8"), before)

    def test_update_is_idempotent_once_registration_is_current(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            run_cli(self._base(root) + ["update"])
            before = self._config(root).read_text(encoding="utf-8")
            run_cli(self._base(root) + ["update"])
            self.assertEqual(self._config(root).read_text(encoding="utf-8"), before)

    def test_setup_is_not_needed_a_second_time_for_a_new_registration(self) -> None:
        # The whole point: one setup, then update forever.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            self._downgrade(root)
            (self._bundle_stray(root)).write_text("# older bundle\n", encoding="utf-8")

            run_cli(self._base(root) + ["update"])

            config = self._config(root).read_text(encoding="utf-8")
            self.assertIn("provider: omh", config)
            self.assertIn((root / ".omh" / "skills").resolve().as_posix(), config)
            self.assertFalse(self._bundle_stray(root).exists())

    def _bundle_stray(self, root: Path) -> Path:
        return root / ".hermes" / "plugins" / "omh" / "stray_from_an_older_version.py"


if __name__ == "__main__":
    unittest.main()


class UltraperfInstalledAwarenessTests(unittest.TestCase):
    """The copied plugin bundle routes ultraperf discovery prompts on its own."""

    def test_ultraperf_route_hint_parity_in_installed_bundle(self) -> None:
        from omh.plugin_bundle.omh.awareness import awareness_route_hint

        for message in (
            "find the performance bottleneck in the checkout path",
            "\uc131\ub2a5 \ubcd1\ubaa9\uc774 \uc5b4\ub514\uc778\uc9c0 \ucc3e\uc544\uc918",
        ):
            with self.subTest(message=message):
                hint = awareness_route_hint(message)
                self.assertEqual(hint["primary_workflow"], "ultraperf")

    def test_ultraperf_display_pair_resolves_in_installed_bundle(self) -> None:
        from omh.plugin_bundle.omh.awareness import awareness_route_hint

        hint = awareness_route_hint("run ulw-perf on the api and worker")
        self.assertEqual(hint["primary_workflow"], "ultraperf")
