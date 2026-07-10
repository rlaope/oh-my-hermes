from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import register
from omh.capabilities.hooks import hook_manifest
from omh.plugin_bundle.omh.hooks import verify_hooks
from omh.plugin_bundle.omh.tools import capability_tool
from omh.routing.chat import route_chat_message
from test_plugin_distribution import FakeHermesContext


class RepresentativeRoutingTests(unittest.TestCase):
    def test_representative_requests_select_specific_workflows(self) -> None:
        cases = (
            ("Please write tests first and implement this with TDD", "ultraprocess"),
            ("이 기능 테스트부터 작성하고 TDD로 구현해줘", "ultraprocess"),
            ("Do a literature review of recent agent memory papers", "web-research"),
            ("이 논문들 문헌 검토하고 근거를 정리해줘", "web-research"),
            ("Analyze this screenshot for UI layout problems", "visual-qa"),
            ("이 스크린샷 UI 레이아웃 문제를 분석해줘", "visual-qa"),
            ("이 목표를 오래 실행하면서 완료조건까지 계속 진행해줘", "ultragoal"),
            ("Deploy this service to production infrastructure", "deploy-and-monitor"),
            ("이 서비스를 프로덕션 인프라에 배포해줘", "deploy-and-monitor"),
            ("Find and recover my previous Codex coding session", "harness-session-inventory"),
            ("지난 코딩 세션을 찾아서 기억을 복구해줘", "harness-session-inventory"),
            ("Edit this image to remove the background", "img-summary"),
            ("Generate a short product demo video", "external-connector-readiness"),
            ("Check whether Home Assistant can control this device", "external-connector-readiness"),
        )

        for message, expected_skill in cases:
            with self.subTest(message=message):
                route = route_chat_message(message)
                self.assertEqual(route["selected_skill"], expected_skill)
                self.assertEqual(route["action"], "dispatch")

    def test_near_neighbor_requests_keep_their_existing_workflows(self) -> None:
        cases = (
            ("Write an article about testing best practices", "best-practice-research"),
            ("Review this pull request code", "ultraprocess"),
            ("Analyze this CSV dataset", "data-analysis"),
            ("Make a quick implementation plan", "plan"),
            ("Summarize this product demo video with timestamps", "media-input-operator"),
            ("Extract text from this screenshot with OCR", "media-input-operator"),
            ("Generate an image card for these release notes", "img-summary"),
            ("Route this Slack thread silently unless action is needed", "gateway-intent-card"),
        )

        for message, expected_skill in cases:
            with self.subTest(message=message):
                route = route_chat_message(message)
                self.assertEqual(route["selected_skill"], expected_skill)

    def test_background_worker_change_is_not_treated_as_image_editing(self) -> None:
        route = route_chat_message("Please remove the background worker from this service")

        self.assertNotEqual(route["selected_skill"], "img-summary")


class PreVerifyHookTests(unittest.TestCase):
    def test_pre_verify_is_registered_and_scoped_to_served_surface_risks(self) -> None:
        context = FakeHermesContext()
        register(context)

        self.assertIn("pre_verify", context.hooks)
        hook = context.hooks["pre_verify"]
        self.assertIsNone(hook(coding=True, attempt=0, changed_paths=["src/example.py"]))
        self.assertIsNone(hook(coding=True, attempt=0, changed_paths=["docs/guide.md"]))
        self.assertIsNone(hook(coding=False, attempt=0, changed_paths=["src/app.tsx"]))
        self.assertIsNone(hook(coding=True, attempt=1, changed_paths=["src/app.tsx"]))

        telemetry_result = hook(
            coding=True,
            attempt=0,
            changed_paths=["src/app.tsx"],
            telemetry_schema_version="observer_telemetry/v1",
        )
        self.assertEqual(telemetry_result["action"], "continue")

        ui_result = hook(coding=True, attempt=0, changed_paths=["src/app.tsx", "src/app.css"])
        self.assertEqual(ui_result["action"], "continue")
        self.assertIn("rendered surface", ui_result["message"])
        self.assertNotIn("src/app.tsx", ui_result["message"])

        plugin_result = hook(
            coding=True,
            attempt=0,
            changed_paths=["/Users/private/project/src/plugin_bundle/omh/plugin.yaml"],
        )
        self.assertEqual(plugin_result["action"], "continue")
        self.assertIn("plugin load", plugin_result["message"])
        self.assertNotIn("/Users/private", plugin_result["message"])

        dependency_result = hook(coding=True, attempt=0, changed_paths=["pyproject.toml"])
        self.assertEqual(dependency_result["action"], "continue")
        self.assertIn("installation or import smoke", dependency_result["message"])

    def test_pre_verify_fails_open_for_malformed_host_values(self) -> None:
        malformed_payloads = (
            {"coding": "false", "attempt": 0, "changed_paths": ["src/app.tsx"]},
            {"coding": True, "attempt": "zero", "changed_paths": ["src/app.tsx"]},
            {"coding": True, "attempt": -1, "changed_paths": ["src/app.tsx"]},
            {"coding": True, "attempt": 0, "changed_paths": 7},
            {"coding": True, "attempt": 0, "changed_paths": [None, object()]},
        )

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(verify_hooks.pre_verify(**payload))

    def test_pre_verify_records_only_path_categories_and_manifest_matches(self) -> None:
        with patch.object(verify_hooks, "observe_plugin_hook_call") as observer:
            result = verify_hooks.pre_verify(coding=True, attempt=0, changed_paths=["src/app.tsx"])

        self.assertEqual(result["action"], "continue")
        observed_payload = observer.call_args.args[1]
        self.assertEqual(observed_payload["changed_path_categories"], ["ui"])
        self.assertNotIn("changed_paths", observed_payload)

        manifest = hook_manifest()
        hook = next(item for item in manifest["plugin_hooks"] if item["name"] == "pre_verify")
        self.assertEqual(
            hook["payload_fields"],
            ["coding", "attempt", "changed_path_count", "changed_path_categories", "action", "message", "redacted"],
        )
        self.assertIn("src/plugin_bundle/omh/hooks/verify_hooks.py", manifest["source_refs"])
        self.assertEqual(hook["payload_fields"], capability_tool._standalone_hook_payload_fields("pre_verify"))

    def test_pre_verify_registration_is_skipped_when_the_host_does_not_support_it(self) -> None:
        context = FakeHermesContext()

        with patch("omh.plugin_bundle.omh._host_supports_hook", return_value=False):
            register(context)

        self.assertNotIn("pre_verify", context.hooks)
        self.assertIn("pre_llm_call", context.hooks)

    def test_pre_verify_registration_fails_open_when_a_strict_host_rejects_the_optional_hook(self) -> None:
        class StrictHermesContext(FakeHermesContext):
            def register_hook(self, name: str, handler: object) -> None:
                if name == "pre_verify":
                    raise ValueError("unsupported hook: pre_verify")
                super().register_hook(name, handler)

        context = StrictHermesContext()
        register(context)

        self.assertEqual(set(context.hooks), {"on_session_end", "pre_llm_call", "pre_tool_call"})
        self.assertIn("omh_capabilities", context.tools)

    def test_pre_verify_persists_bounded_host_observation_without_paths_or_response(self) -> None:
        with TemporaryDirectory() as tmp:
            result = verify_hooks.pre_verify(
                host="hermes-agent",
                session_id="session-1",
                evidence_ref="host-log-1",
                omh_home=tmp,
                coding=True,
                attempt=0,
                changed_paths=["/Users/private/project/src/app.tsx"],
                final_response="private final response",
            )

            observation_path = Path(tmp) / "runtime" / "plugin_host_observations.jsonl"
            record = json.loads(observation_path.read_text(encoding="utf-8").splitlines()[-1])

        self.assertEqual(result["action"], "continue")
        self.assertEqual(record["hook"], "pre_verify")
        self.assertEqual(record["host"], "hermes-agent")
        self.assertEqual(record["session_id"], "session-1")
        serialized = json.dumps(record, sort_keys=True)
        self.assertNotIn("/Users/private", serialized)
        self.assertNotIn("private final response", serialized)


class CapabilityImpactReportTests(unittest.TestCase):
    def test_cli_report_separates_evidence_dimensions_without_an_aggregate_score(self) -> None:
        status, stdout, stderr = run_cli(["capabilities", "impact", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        dimensions = {item["id"]: item for item in payload["dimensions"]}
        self.assertEqual(payload["schema_version"], "omh_capability_impact_report/v1")
        self.assertEqual(payload["verdict"], "partially_proven")
        self.assertNotIn("aggregate_score", payload)
        self.assertIn("No aggregate score", payload["score_policy"])
        self.assertEqual(dimensions["route_selection"]["status"], "passing_local_contract")
        self.assertEqual(payload["route_selection"]["representative"]["evidence_class"], "implementation_smoke")
        self.assertEqual(dimensions["guidance_depth"]["status"], "partially_proven")
        self.assertEqual(dimensions["native_execution_availability"]["status"], "requires_host_observation")
        self.assertEqual(dimensions["provider_execution_availability"]["status"], "requires_provider_observation")
        self.assertEqual(dimensions["artifact_verification"]["status"], "partially_proven")
        self.assertEqual(dimensions["comparative_outcome_quality"]["status"], "requires_external_evaluator")
        representative = payload["route_selection"]["representative"]
        self.assertEqual(representative["passed"], representative["total"])
        self.assertGreaterEqual(representative["total"], 20)

    def test_plugin_package_and_fallback_reports_keep_the_same_contract_shape(self) -> None:
        package_payload = capability_tool._handle_capability_action("impact", None, "")
        with patch.object(capability_tool, "_load_package_registry", return_value=None):
            fallback_payload = capability_tool._handle_capability_action("impact", None, "")

        self.assertEqual(package_payload["schema_version"], "omh_capability_impact_report/v1")
        self.assertEqual(fallback_payload["schema_version"], package_payload["schema_version"])
        self.assertEqual(
            [item["id"] for item in fallback_payload["dimensions"]],
            [item["id"] for item in package_payload["dimensions"]],
        )
        for section in ("fixed_precision", "common_requests", "representative"):
            self.assertEqual(
                set(fallback_payload["route_selection"][section]),
                set(package_payload["route_selection"][section]),
            )
        self.assertTrue(fallback_payload["degraded"])
        self.assertEqual(fallback_payload["source"], "standalone_plugin_bundle_fallback")
        self.assertNotIn("aggregate_score", fallback_payload)

    def test_package_registry_falls_back_only_when_package_modules_are_missing(self) -> None:
        original_import = __import__

        for missing_name in ("omh", "omh.capabilities"):
            def missing_package(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "omh.capabilities.registry":
                    error = ModuleNotFoundError(f"No module named '{missing_name}'")
                    error.name = missing_name
                    raise error
                return original_import(name, globals, locals, fromlist, level)

            with self.subTest(missing_name=missing_name):
                with patch("builtins.__import__", side_effect=missing_package):
                    self.assertIsNone(capability_tool._load_package_registry())

        def broken_dependency(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "omh.quality.capability_impact":
                raise ImportError("package dependency failed")
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=broken_dependency):
            with self.assertRaisesRegex(ImportError, "package dependency failed"):
                capability_tool._load_package_registry()

    def test_missing_impact_backend_does_not_break_existing_capability_actions(self) -> None:
        original_import = __import__

        def missing_impact(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "omh.quality.capability_impact":
                error = ModuleNotFoundError("No module named 'omh.quality'")
                error.name = "omh.quality"
                raise error
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=missing_impact):
            registry = capability_tool._load_package_registry()

        self.assertIsNotNone(registry)
        self.assertIsNone(registry["capability_impact_report"])
        with patch.object(capability_tool, "_load_package_registry", return_value=registry):
            summary = capability_tool._handle_capability_action("summary", None, "")
            impact = capability_tool._handle_capability_action("impact", None, "")
        self.assertEqual(summary["schema_version"], "omh_capability_summary/v1")
        self.assertTrue(impact["degraded"])


if __name__ == "__main__":
    unittest.main()
