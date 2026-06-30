from __future__ import annotations

from contextlib import ExitStack
import json
import sys
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import omh.maintenance.release as release_module
from omh.paths import OmhPaths
from omh.release import (
    hermes_release_smoke_plan,
    product_readiness_report,
    release_evidence_bundle,
    release_readiness_checklist,
    run_hermes_release_smoke,
    skill_content_smoke,
)
from omh.release_install_smoke import install_script_smoke_plan, run_install_script_smoke
from omh.release_smoke_core import CommandResult, subprocess_runner, subprocess_runner_exact_env


class ReleaseSmokeTests(unittest.TestCase):
    def test_release_readiness_checklist_is_plan_only_and_names_required_gates(self) -> None:
        payload = release_readiness_checklist(version="v1.0.0", omh_command="/tmp/omh")

        self.assertEqual(payload["schema_version"], "release_readiness_checklist/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["version"], "1.0.0")
        self.assertEqual(payload["tag"], "v1.0.0")
        self.assertIn("does not run commands", payload["proof_boundary"])
        items = {item["id"]: item for item in payload["items"]}
        self.assertIn("unit_tests", items)
        self.assertIn("skill_content_smoke", items)
        self.assertIn("installed_command_smoke", items)
        self.assertIn("installed_command_path", items)
        self.assertIn("use_case_demo_cards", items)
        self.assertIn("use_case_artifact_bundle", items)
        self.assertIn("use_case_replay", items)
        self.assertIn("use_case_readiness", items)
        self.assertIn("grounded_score", items)
        self.assertIn("chat_card_coverage", items)
        self.assertIn("route_hint_alignment", items)
        self.assertIn("context_brief_coverage", items)
        self.assertIn("routing_precision", items)
        self.assertIn("product_readiness", items)
        self.assertIn("release_evidence_bundle", items)
        self.assertIn("live_tap_smoke", items)
        self.assertIn("tag_and_publish", items)
        self.assertEqual(items["installed_command_path"]["command"], "command -v /tmp/omh")
        self.assertEqual(items["installed_command_help"]["command"], "/tmp/omh --help")
        self.assertEqual(items["skill_content_smoke"]["command"], "/tmp/omh release skill-content-smoke --json")
        self.assertIn("generated workflow context rails", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("bundled role context", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("all-skill awareness lane coverage", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("full capability manifest context", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("playbook capability context", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("standalone plugin capability fallback coverage", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("G1-G10 use-case demo cards", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("G1-G10 use-case artifact bundles", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("G1-G10 natural-language use-case replay", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("bounded prompt context budgets", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("bounded capability payload budgets", items["skill_content_smoke"]["evidence_required"])
        self.assertIn("--include-command-smoke", items["installed_command_smoke"]["command"])
        self.assertIn("dist/oh_my_hermes-1.0.0-py3-none-any.whl", items["wheel_install"]["command"])
        self.assertIn("wheel_setup_dry_run", items)
        self.assertIn("setup --dry-run --channel stable --version 1.0.0", items["wheel_setup_dry_run"]["command"])
        self.assertIn("release install-smoke --live", items["installer_smoke"]["command"])
        self.assertEqual(
            items["source_checkout_command_smoke"]["command"],
            'uv run --no-editable omh recommend "risky refactor" --limit 1 --json',
        )
        self.assertIn("console script", items["source_checkout_command_smoke"]["evidence_required"])
        self.assertIn("console-script importability", items["source_checkout_command_smoke"]["proof_boundary"])
        self.assertIn("does not prove Hermes chat visibility", items["source_checkout_command_smoke"]["proof_boundary"])
        self.assertEqual(items["use_case_demo_cards"]["command"], "uv run python -m omh.cli cases demo --all --json")
        self.assertIn("G1-G10", items["use_case_demo_cards"]["evidence_required"])
        self.assertIn("wrapper-renderable projections", items["use_case_demo_cards"]["proof_boundary"])
        self.assertIn("not prove", items["use_case_demo_cards"]["proof_boundary"])
        self.assertEqual(items["use_case_artifact_bundle"]["command"], "uv run python -m omh.cli cases artifact --all --json")
        self.assertIn("prepared artifacts", items["use_case_artifact_bundle"]["evidence_required"])
        self.assertIn("prepared runbook projection", items["use_case_artifact_bundle"]["proof_boundary"])
        self.assertIn("not prove", items["use_case_artifact_bundle"]["proof_boundary"])
        self.assertEqual(items["use_case_replay"]["command"], "uv run python -m omh.cli cases replay --json")
        self.assertIn("English and Korean operator fixtures", items["use_case_replay"]["evidence_required"])
        self.assertIn("synthetic fixtures", items["use_case_replay"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat behavior", items["use_case_replay"]["proof_boundary"])
        self.assertEqual(items["use_case_readiness"]["command"], "uv run python -m omh.cli cases readiness --json")
        self.assertIn("readiness", items["use_case_readiness"]["evidence_required"])
        self.assertIn("deterministic local use-case contracts", items["use_case_readiness"]["proof_boundary"])
        self.assertEqual(items["grounded_score"]["command"], "uv run python -m omh.cli demo grounded-score --json")
        self.assertIn("10/10", items["grounded_score"]["evidence_required"])
        self.assertIn("deterministic local route", items["grounded_score"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat rendering", items["grounded_score"]["proof_boundary"])
        self.assertEqual(items["chat_card_coverage"]["command"], "uv run python -m omh.cli demo chat-card-coverage --json")
        self.assertIn("generic ack count 0", items["chat_card_coverage"]["evidence_required"])
        self.assertIn("deterministic local wrapper-card contracts", items["chat_card_coverage"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat rendering", items["chat_card_coverage"]["proof_boundary"])
        self.assertEqual(items["route_hint_alignment"]["command"], "uv run python -m omh.cli demo route-hint-alignment --json")
        self.assertIn("primary plugin awareness hint", items["route_hint_alignment"]["evidence_required"])
        self.assertIn("deterministic local router/hint agreement", items["route_hint_alignment"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat rendering", items["route_hint_alignment"]["proof_boundary"])
        self.assertEqual(items["context_brief_coverage"]["command"], "uv run python -m omh.cli demo context-brief-coverage --json")
        self.assertIn("route hint or picker hint", items["context_brief_coverage"]["evidence_required"])
        self.assertIn("deterministic local Hermes-facing context", items["context_brief_coverage"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat rendering", items["context_brief_coverage"]["proof_boundary"])
        self.assertEqual(items["routing_precision"]["command"], "uv run python -m omh.cli demo routing-precision --json")
        self.assertIn("overroute count 0", items["routing_precision"]["evidence_required"])
        self.assertIn("missed intervention count 0", items["routing_precision"]["evidence_required"])
        self.assertIn("deterministic local over-intervention and missed-intervention", items["routing_precision"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat rendering", items["routing_precision"]["proof_boundary"])
        self.assertEqual(items["hermes_ux_quality"]["command"], "uv run python -m omh.cli demo hermes-ux-quality --json")
        self.assertIn("routing score", items["hermes_ux_quality"]["evidence_required"])
        self.assertIn("deterministic local routing, card, hint, and context contracts", items["hermes_ux_quality"]["proof_boundary"])
        self.assertIn("does not prove live Hermes chat rendering", items["hermes_ux_quality"]["proof_boundary"])
        self.assertEqual(items["product_readiness"]["command"], "/tmp/omh release product-readiness --version 1.0.0 --json")
        self.assertIn("skill-content", items["product_readiness"]["evidence_required"])
        self.assertIn("grounded score", items["product_readiness"]["evidence_required"])
        self.assertIn("wrapper chat card coverage", items["product_readiness"]["evidence_required"])
        self.assertIn("product contracts", items["product_readiness"]["proof_boundary"])
        self.assertEqual(items["release_evidence_bundle"]["command"], "/tmp/omh release evidence-bundle --version 1.0.0 --write --json")
        self.assertIn("omh_release_evidence_bundle/v1", items["release_evidence_bundle"]["evidence_required"])
        self.assertIn("local deterministic evidence", items["release_evidence_bundle"]["proof_boundary"])
        self.assertTrue(items["live_tap_smoke"]["mutates_profile"])
        self.assertTrue(items["live_tap_smoke"]["requires_release_authority"])
        self.assertFalse(items["tag_and_publish"]["required"])
        self.assertIn('git tag -a v1.0.0 -m "Release v1.0.0"', items["tag_and_publish"]["command"])
        self.assertTrue(items["tag_and_publish"]["requires_release_authority"])
        self.assertGreaterEqual(payload["required_item_count"], 18)

    def test_release_readiness_checklist_rejects_unsafe_versions_and_quotes_command_paths(self) -> None:
        with self.assertRaises(ValueError):
            release_readiness_checklist(version="1.0.0; echo injected")

        payload = release_readiness_checklist(version="1.0.0", omh_command="/tmp/omh command")

        items = {item["id"]: item for item in payload["items"]}
        self.assertEqual(items["installed_command_help"]["command"], "'/tmp/omh command' --help")
        self.assertEqual(items["installed_command_path"]["command"], "command -v '/tmp/omh command'")
        self.assertEqual(items["skill_content_smoke"]["command"], "'/tmp/omh command' release skill-content-smoke --json")
        self.assertEqual(
            items["product_readiness"]["command"],
            "'/tmp/omh command' release product-readiness --version 1.0.0 --json",
        )
        self.assertEqual(
            items["release_evidence_bundle"]["command"],
            "'/tmp/omh command' release evidence-bundle --version 1.0.0 --write --json",
        )
        self.assertIn("--omh-command '/tmp/omh command'", items["installed_command_smoke"]["command"])
        self.assertIn("'/tmp/omh command' release hermes-smoke --live", items["live_tap_smoke"]["command"])

    def test_skill_content_smoke_checks_router_and_workflow_context(self) -> None:
        payload = skill_content_smoke()

        self.assertEqual(payload["schema_version"], "skill_content_smoke/v1")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["observed"])
        self.assertEqual(payload["router_skill"], "oh-my-hermes")
        self.assertIn("img-summary", payload["representative_skills"])
        self.assertEqual(payload["missing_representative_skills"], [])
        self.assertEqual(payload["missing_awareness_lane_skills"], [])
        self.assertEqual(payload["unexpected_awareness_surfaces"], [])
        self.assertIn("request-to-handoff", payload["allowed_conceptual_awareness_surfaces"])
        self.assertGreaterEqual(payload["awareness_lane_skill_count"], payload["workflow_skill_count"])
        self.assertGreaterEqual(payload["full_capability_skill_count"], payload["workflow_skill_count"])
        self.assertEqual(payload["missing_full_capability_skills"], [])
        self.assertEqual(payload["missing_full_capability_context_skills"], [])
        self.assertGreaterEqual(payload["playbook_capability_count"], 20)
        self.assertGreaterEqual(payload["standalone_playbook_capability_count"], 8)
        self.assertIn("request-to-handoff", payload["required_playbook_capability_ids"])
        self.assertEqual(payload["missing_required_playbook_capabilities"], [])
        self.assertEqual(payload["missing_required_standalone_playbook_capabilities"], [])
        self.assertEqual(payload["missing_playbook_context_playbooks"], [])
        self.assertEqual(payload["missing_standalone_playbook_context_playbooks"], [])
        self.assertEqual(payload["missing_standalone_capability_skills"], [])
        self.assertEqual(payload["unexpected_standalone_capability_skills"], [])
        self.assertEqual(payload["missing_standalone_capability_context_skills"], [])
        self.assertGreaterEqual(payload["role_context_count"], 8)
        self.assertEqual(payload["missing_role_context_roles"], [])
        self.assertEqual(payload["bundled_role_context_count"], payload["role_context_count"])
        self.assertEqual(payload["missing_bundled_role_context_roles"], [])
        self.assertEqual(payload["missing_bundled_role_files"], [])
        self.assertEqual(payload["unexpected_bundled_role_files"], [])
        self.assertEqual(payload["stale_bundled_role_context_roles"], [])
        self.assertIn("OMH Role Context", payload["required_role_context_markers"])
        self.assertIn("workflow_routing_hint", payload["required_capability_context_fields"])
        self.assertIn("evidence_boundary", payload["required_capability_context_fields"])
        self.assertIn("pipeline", payload["required_playbook_context_fields"])
        self.assertIn("prepared_is_not", payload["required_playbook_context_fields"])
        self.assertIn("primary_owner_role", payload["required_playbook_context_fields"])
        self.assertIn("available_wrapper_actions", payload["required_playbook_context_fields"])
        self.assertIn("first_stage", payload["required_playbook_context_fields"])
        self.assertIn("workflow_routing_hint", payload["required_standalone_capability_context_fields"])
        self.assertIn("evidence_boundary", payload["required_standalone_capability_context_fields"])
        self.assertGreaterEqual(payload["catalog_skill_count"], payload["skill_count"])
        self.assertGreaterEqual(payload["standalone_capability_skill_count"], payload["workflow_skill_count"])
        self.assertLessEqual(
            payload["full_capability_skill_section_chars"],
            payload["capability_context_char_limits"]["full_skill_section"],
        )
        self.assertLessEqual(
            payload["standalone_capability_skill_section_chars"],
            payload["capability_context_char_limits"]["standalone_skill_section"],
        )
        self.assertLessEqual(
            payload["max_full_capability_skill_chars"],
            payload["capability_context_char_limits"]["full_skill_item"],
        )
        self.assertLessEqual(
            payload["max_standalone_capability_skill_chars"],
            payload["capability_context_char_limits"]["standalone_skill_item"],
        )
        self.assertEqual(payload["capability_budget_failures"], [])
        self.assertEqual(payload["use_case_demo_collection_schema"], "omh_use_case_demo_collection/v1")
        self.assertEqual(payload["use_case_demo_card_count"], 10)
        self.assertEqual(payload["expected_use_case_demo_card_count"], 10)
        self.assertEqual(payload["use_case_demo_failures"], [])
        self.assertEqual(payload["use_case_artifact_collection_schema"], "omh_use_case_artifact_collection/v1")
        self.assertEqual(payload["use_case_artifact_count"], 10)
        self.assertEqual(payload["expected_use_case_artifact_count"], 10)
        self.assertEqual(payload["use_case_artifact_failures"], [])
        self.assertEqual(payload["use_case_replay_schema"], "omh_use_case_replay/v1")
        self.assertEqual(payload["use_case_replay_status"], "passed")
        self.assertEqual(payload["use_case_replay_total"], 20)
        self.assertEqual(payload["use_case_replay_passed"], 20)
        self.assertEqual(payload["expected_use_case_replay_total"], 20)
        self.assertEqual(payload["use_case_replay_failures"], [])
        self.assertEqual(payload["use_case_readiness_schema"], "omh_use_case_readiness/v1")
        self.assertEqual(payload["use_case_readiness_status"], "ready")
        self.assertEqual(payload["use_case_readiness_score"], 100)
        self.assertEqual(payload["use_case_readiness_blocking_failures"], 0)
        self.assertGreaterEqual(payload["use_case_readiness_warning_count"], 0)
        self.assertEqual(payload["use_case_readiness_failures"], [])
        self.assertLessEqual(
            payload["awareness_primer_context_chars"],
            payload["awareness_context_char_limits"]["primer_context"],
        )
        self.assertLessEqual(
            payload["awareness_primer_markdown_chars"],
            payload["awareness_context_char_limits"]["primer_markdown"],
        )
        self.assertLessEqual(
            payload["max_workflow_context_chars"],
            payload["awareness_context_char_limits"]["workflow_context"],
        )
        self.assertEqual(payload["oversized_awareness_contexts"], [])
        self.assertEqual(payload["awareness_budget_failures"], [])
        self.assertLessEqual(
            payload["max_role_context_chars"],
            payload["awareness_context_char_limits"]["role_context"],
        )
        self.assertEqual(payload["oversized_role_contexts"], [])
        self.assertEqual(payload["role_context_budget_failures"], [])
        self.assertEqual(payload["failed_checks"], [])
        self.assertGreaterEqual(payload["skill_count"], 40)
        self.assertGreaterEqual(payload["checked_marker_count"], 100)
        self.assertIn("does not prove the target Hermes profile", payload["proof_boundary"])

    def test_product_readiness_report_rolls_up_public_release_story(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            payload = product_readiness_report(version="v1.0.1", omh_command="/tmp/omh command", paths=paths)

            self.assertEqual(payload["schema_version"], "omh_product_readiness/v1")
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["score"], 100)
            self.assertTrue(payload["observed"])
            self.assertEqual(payload["version"], "1.0.1")
            self.assertEqual(payload["blocking_failures"], 0)
            self.assertEqual(payload["local_artifact_store"], "not_written")
            self.assertIn("local_artifact_store: not_written", payload["warnings"])
            self.assertIn("cases artifact --all --write", " ".join(payload["next_actions"]))
            gates = {gate["id"]: gate for gate in payload["gates"]}
            self.assertEqual(
                set(gates),
                {
                    "skill_content",
                    "use_cases",
                    "grounded_score",
                    "chat_card_coverage",
                    "route_hint_alignment",
                    "context_brief_coverage",
                    "routing_precision",
                    "hermes_ux_quality",
                    "parity_contracts",
                    "release_checklist",
                },
            )
            self.assertEqual(gates["skill_content"]["status"], "passed")
            self.assertEqual(gates["use_cases"]["status"], "passed")
            self.assertIn("local artifact store not_written", gates["use_cases"]["summary"])
            self.assertEqual(gates["use_cases"]["warnings"], ["local_artifact_store: not_written"])
            self.assertEqual(gates["grounded_score"]["status"], "passed")
            self.assertIn("47/47 scenarios at 10/10", gates["grounded_score"]["summary"])
            self.assertIn("avg 10.0", gates["grounded_score"]["summary"])
            self.assertEqual(gates["grounded_score"]["command"], "omh demo grounded-score --json")
            self.assertIn("deterministic local contract-compliance", gates["grounded_score"]["proof_boundary"])
            self.assertEqual(gates["chat_card_coverage"]["status"], "passed")
            self.assertIn("25/25 dedicated workflow cards", gates["chat_card_coverage"]["summary"])
            self.assertIn("generic ack 0", gates["chat_card_coverage"]["summary"])
            self.assertEqual(gates["chat_card_coverage"]["command"], "omh demo chat-card-coverage --json")
            self.assertIn("deterministic local wrapper-card coverage", gates["chat_card_coverage"]["proof_boundary"])
            self.assertEqual(gates["route_hint_alignment"]["status"], "passed")
            self.assertIn("72/72 route hints aligned", gates["route_hint_alignment"]["summary"])
            self.assertIn("missing 0", gates["route_hint_alignment"]["summary"])
            self.assertIn("mismatches 0", gates["route_hint_alignment"]["summary"])
            self.assertEqual(gates["route_hint_alignment"]["command"], "omh demo route-hint-alignment --json")
            self.assertIn("deterministic local agreement", gates["route_hint_alignment"]["proof_boundary"])
            self.assertEqual(gates["context_brief_coverage"]["status"], "passed")
            self.assertIn("8/8 context brief cases passing", gates["context_brief_coverage"]["summary"])
            self.assertIn("route hints 7", gates["context_brief_coverage"]["summary"])
            self.assertIn("catalog picker hints 1", gates["context_brief_coverage"]["summary"])
            self.assertEqual(gates["context_brief_coverage"]["command"], "omh demo context-brief-coverage --json")
            self.assertIn("deterministic local OMH mental-model", gates["context_brief_coverage"]["proof_boundary"])
            self.assertEqual(gates["routing_precision"]["status"], "passed")
            self.assertIn("39/39 negative-control cases", gates["routing_precision"]["summary"])
            self.assertIn("19/19 interventions", gates["routing_precision"]["summary"])
            self.assertIn("overroutes 0", gates["routing_precision"]["summary"])
            self.assertIn("catalog pickers 0", gates["routing_precision"]["summary"])
            self.assertIn("missed interventions 0", gates["routing_precision"]["summary"])
            self.assertEqual(gates["routing_precision"]["command"], "omh demo routing-precision --json")
            self.assertIn("deterministic local over-intervention", gates["routing_precision"]["proof_boundary"])
            self.assertEqual(gates["hermes_ux_quality"]["status"], "passed")
            self.assertIn("5/5 UX gates passing", gates["hermes_ux_quality"]["summary"])
            self.assertIn("routing avg 10.0", gates["hermes_ux_quality"]["summary"])
            self.assertIn("generic ack 0", gates["hermes_ux_quality"]["summary"])
            self.assertIn("context 8/8", gates["hermes_ux_quality"]["summary"])
            self.assertEqual(gates["hermes_ux_quality"]["command"], "omh demo hermes-ux-quality --json")
            self.assertIn("deterministic local routing", gates["hermes_ux_quality"]["proof_boundary"])
            self.assertEqual(gates["parity_contracts"]["status"], "passed")
            self.assertEqual(gates["release_checklist"]["status"], "passed")
            self.assertIn(
                "'/tmp/omh command' release checklist --version 1.0.1 --json",
                gates["release_checklist"]["command"],
            )
            self.assertIn("deterministic local OMH package", payload["boundary"])
            self.assertIn("Attach observed evidence", " ".join(payload["next_actions"]))
            self.assertIn("evidence-bundle", " ".join(payload["next_actions"]))

    def test_release_evidence_bundle_packages_and_writes_local_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")

            payload = release_evidence_bundle(version="v1.0.1", omh_command="/tmp/omh command", paths=paths)

            self.assertEqual(payload["schema_version"], "omh_release_evidence_bundle/v1")
            self.assertEqual(payload["status"], "ready")
            self.assertFalse(payload["written"])
            self.assertFalse(paths.release_evidence_index_path.exists())
            self.assertIn("local_artifact_store: not_written", payload["warnings"])
            self.assertEqual(payload["summary"]["product_readiness_status"], "ready")
            self.assertEqual(payload["summary"]["grounded_score_perfect"], 47)
            self.assertEqual(payload["summary"]["grounded_score_total"], 47)
            self.assertEqual(payload["summary"]["grounded_score_average"], 10.0)
            self.assertEqual(payload["summary"]["chat_card_coverage_passing"], 25)
            self.assertEqual(payload["summary"]["chat_card_coverage_total"], 25)
            self.assertEqual(payload["summary"]["chat_card_generic_ack_count"], 0)
            self.assertEqual(payload["summary"]["route_hint_alignment_aligned"], 72)
            self.assertEqual(payload["summary"]["route_hint_alignment_total"], 72)
            self.assertEqual(payload["summary"]["route_hint_missing_count"], 0)
            self.assertEqual(payload["summary"]["route_hint_mismatch_count"], 0)
            self.assertEqual(payload["summary"]["context_brief_coverage_passing"], 8)
            self.assertEqual(payload["summary"]["context_brief_coverage_total"], 8)
            self.assertEqual(payload["summary"]["context_brief_route_hint_count"], 7)
            self.assertEqual(payload["summary"]["context_brief_catalog_question_count"], 1)
            self.assertEqual(payload["summary"]["routing_precision_passing"], 39)
            self.assertEqual(payload["summary"]["routing_precision_total"], 39)
            self.assertEqual(payload["summary"]["routing_precision_overroute_count"], 0)
            self.assertEqual(payload["summary"]["routing_precision_catalog_picker_count"], 0)
            self.assertEqual(payload["summary"]["routing_precision_generic_ack_count"], 0)
            self.assertEqual(payload["summary"]["routing_precision_intervention_passing"], 19)
            self.assertEqual(payload["summary"]["routing_precision_intervention_total"], 19)
            self.assertEqual(payload["summary"]["routing_precision_missed_intervention_count"], 0)
            self.assertEqual(payload["summary"]["hermes_ux_quality_score"], 100)
            self.assertEqual(payload["summary"]["hermes_ux_quality_passing_gates"], 5)
            self.assertEqual(payload["summary"]["hermes_ux_quality_total_gates"], 5)
            self.assertEqual(payload["evidence"]["product_readiness"]["schema_version"], "omh_product_readiness/v1")
            self.assertEqual(payload["evidence"]["release_checklist"]["schema_version"], "release_readiness_checklist/v1")
            self.assertEqual(payload["evidence"]["grounded_score"]["schema_version"], "grounded_score_evaluation/v1")
            self.assertEqual(payload["evidence"]["chat_card_coverage"]["schema_version"], "chat_card_coverage/v1")
            self.assertEqual(payload["evidence"]["route_hint_alignment"]["schema_version"], "route_hint_alignment/v1")
            self.assertEqual(payload["evidence"]["context_brief_coverage"]["schema_version"], "context_brief_coverage/v1")
            self.assertEqual(payload["evidence"]["routing_precision"]["schema_version"], "routing_precision/v1")
            self.assertEqual(payload["evidence"]["hermes_ux_quality"]["schema_version"], "hermes_ux_quality/v1")
            self.assertIn("grounded_score_ready", payload["claims"])
            self.assertIn("chat_card_coverage_ready", payload["claims"])
            self.assertIn("route_hint_alignment_ready", payload["claims"])
            self.assertIn("context_brief_coverage_ready", payload["claims"])
            self.assertIn("routing_precision_ready", payload["claims"])
            self.assertIn("hermes_ux_quality_ready", payload["claims"])
            self.assertIn("executor_dispatch", payload["not_evidence_for"])

            written = release_evidence_bundle(version="v1.0.1", omh_command="/tmp/omh command", paths=paths, write=True)

            self.assertTrue(written["written"])
            artifact_path = Path(str(written["artifact_path"]))
            self.assertTrue(artifact_path.exists())
            self.assertTrue(paths.release_evidence_index_path.exists())
            stored = json.loads(artifact_path.read_text(encoding="utf-8"))
            index = json.loads(paths.release_evidence_index_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["schema_version"], "omh_release_evidence_bundle/v1")
            self.assertEqual(index["schema_version"], "omh_release_evidence_index/v1")
            self.assertEqual(index["latest_version"], "1.0.1")
            self.assertEqual(index["latest_artifact_path"], str(artifact_path))

    def test_release_evidence_bundle_reuses_product_readiness_quality_evidence(self) -> None:
        counted_names = (
            "skill_content_smoke",
            "build_parity_matrix",
            "build_grounded_score_demo",
            "build_chat_card_coverage_demo",
            "build_route_hint_alignment_demo",
            "build_context_brief_coverage_demo",
            "build_routing_precision_demo",
            "build_hermes_ux_quality_demo",
            "release_readiness_checklist",
        )
        counts = {name: 0 for name in counted_names}

        def counted(name: str):
            original = getattr(release_module, name)

            def wrapper(*args, **kwargs):
                counts[name] += 1
                return original(*args, **kwargs)

            return wrapper

        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            with ExitStack() as stack:
                for name in counted_names:
                    stack.enter_context(patch.object(release_module, name, side_effect=counted(name)))
                payload = release_evidence_bundle(version="v1.0.1", omh_command="/tmp/omh command", paths=paths)

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["evidence"]["product_readiness"]["status"], "ready")
        for name in counted_names:
            self.assertEqual(counts[name], 1, name)

    def test_release_readiness_checklist_rejects_empty_version(self) -> None:
        with self.assertRaises(ValueError):
            release_readiness_checklist(version=" ")

    def test_hermes_smoke_plan_is_non_mutating_until_live(self) -> None:
        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        payload = hermes_release_smoke_plan(omh_home="/tmp/omh-smoke", hermes_home="/tmp/hermes-smoke")

        self.assertEqual(payload["schema_version"], "hermes_release_smoke/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertFalse(payload["observed"])
        self.assertIn("--live", payload["live_command"])
        commands = [step["command"] for step in payload["steps"]]
        self.assertEqual(commands[0], ["hermes", "skills", "tap", "add", "rlaope/oh-my-hermes"])
        self.assertEqual(
            commands[1],
            ["hermes", "skills", "install", "rlaope/oh-my-hermes/skills/oh-my-hermes", "--yes"],
        )
        self.assertIn(["hermes", "skills", "list", "--enabled-only"], commands)
        self.assertIn(["hermes", "skills", "check", "oh-my-hermes"], commands)
        self.assertIn(["hermes", "skills", "inspect", "rlaope/oh-my-hermes/skills/oh-my-hermes"], commands)
        self.assertIn("does not touch", payload["proof_boundary"])
        self.assertEqual(payload["target_binding"]["hermes_home"], hermes_home)
        self.assertIn("--hermes-home", payload["live_command"])
        self.assertEqual(payload["installed_command_smoke"]["schema_version"], "installed_omh_command_smoke/v1")
        self.assertEqual(payload["installed_command_smoke"]["path_check"]["schema_version"], "installed_omh_path_check/v1")
        self.assertFalse(payload["installed_command_smoke"]["path_check"]["observed"])
        installed_commands = [step["command"] for step in payload["installed_command_smoke"]["steps"]]
        self.assertEqual(installed_commands[0], ["omh", "--help"])
        self.assertIn(["omh", "release", "skill-content-smoke", "--json"], installed_commands)
        self.assertIn(
            ["omh", "--omh-home", omh_home, "--hermes-home", hermes_home, "release", "hermes-smoke", "--install-path", "setup", "--omh-command", "omh"],
            installed_commands,
        )
        self.assertEqual(payload["first_use_status_smoke"]["schema_version"], "first_use_status_smoke/v1")
        self.assertFalse(payload["first_use_status_smoke"]["observed"])
        first_use_commands = [step["command"] for step in payload["first_use_status_smoke"]["steps"]]
        self.assertIn("chat", first_use_commands[0])
        self.assertIn("session", first_use_commands[0])
        self.assertIn("accept-plan", first_use_commands[1])
        self.assertIn("select-executor", first_use_commands[2])
        self.assertIn("prepare-handoff", first_use_commands[3])
        self.assertIn("status", first_use_commands[4])
        self.assertEqual(
            payload["first_use_status_smoke"]["expected_status_boundary"]["before_handoff"]["executor_actions_visible"],
            False,
        )

    def test_setup_install_path_uses_omh_setup_before_hermes_checks(self) -> None:
        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        payload = hermes_release_smoke_plan(
            install_path="setup",
            omh_command="omh-dev",
            omh_home="/tmp/omh-smoke",
            hermes_home="/tmp/hermes-smoke",
        )

        commands = [step["command"] for step in payload["steps"]]
        self.assertEqual(commands[0], ["omh-dev", "--omh-home", omh_home, "--hermes-home", hermes_home, "setup"])
        self.assertIn(["hermes", "skills", "check", "oh-my-hermes"], commands)
        self.assertIn(["omh-dev", "--omh-home", omh_home, "--hermes-home", hermes_home, "doctor"], commands)
        self.assertNotIn(["hermes", "skills", "inspect", "oh-my-hermes"], commands)
        installed_commands = [step["command"] for step in payload["installed_command_smoke"]["steps"]]
        self.assertEqual(installed_commands[0], ["omh-dev", "--help"])
        self.assertIn(["omh-dev", "release", "skill-content-smoke", "--json"], installed_commands)
        self.assertIn(
            [
                "omh-dev",
                "--omh-home",
                omh_home,
                "--hermes-home",
                hermes_home,
                "release",
                "hermes-smoke",
                "--install-path",
                "setup",
                "--omh-command",
                "omh-dev",
            ],
            installed_commands,
        )

    def test_install_script_smoke_plan_is_isolated_and_non_observed(self) -> None:
        payload = install_script_smoke_plan(repo_root="/tmp/omh-repo", install_script="/tmp/omh-repo/install.sh")

        self.assertEqual(payload["schema_version"], "install_script_smoke/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["repo_root"], str(Path("/tmp/omh-repo").resolve()))
        self.assertEqual(payload["package_url"], str(Path("/tmp/omh-repo").resolve()))
        self.assertIn("OMH_VENV_DIR", payload["environment"])
        self.assertIn("OMH_BIN_DIR", payload["environment"])
        self.assertEqual(payload["environment"]["OMH_HOME"], "<tempdir>/home/.omh")
        self.assertEqual(payload["environment"]["HERMES_HOME"], "<tempdir>/home/.hermes")
        first_use = payload["first_use_status_smoke"]
        self.assertEqual(first_use["target_binding"]["omh_home"], "<tempdir>/home/.omh")
        self.assertEqual(first_use["target_binding"]["hermes_home"], "<tempdir>/home/.hermes")
        self.assertEqual(payload["environment"]["OMH_RUN_SETUP"], "0")
        self.assertEqual(payload["environment"]["OMH_RUN_DOCTOR"], "1")
        self.assertEqual(payload["environment"]["OMH_SETUP_ARGS"], "")
        self.assertIn("<tempdir>", payload["work_dir"])
        self.assertEqual(payload["steps"][0]["command"], ["sh", str(Path("/tmp/omh-repo/install.sh").resolve())])
        self.assertEqual(payload["steps"][1]["name"], "installed_command_smoke")
        self.assertIn("release", payload["steps"][1]["command"])
        self.assertIn("first_use_status_smoke", payload)
        self.assertIn("does not download over curl", payload["proof_boundary"])

    def test_install_script_smoke_live_installs_command_without_setup_and_runs_command_smoke(self) -> None:
        seen: list[list[str]] = []
        seen_env: list[dict[str, str]] = []

        def runner(command, _timeout, env):
            seen.append(list(command))
            seen_env.append(dict(env or {}))
            if list(command)[0] == "sh":
                bin_dir = Path(env["OMH_BIN_DIR"])
                bin_dir.mkdir(parents=True, exist_ok=True)
                installed = bin_dir / "omh"
                installed.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                installed.chmod(0o755)
                return CommandResult(command, 0, "installer ok", "")
            return CommandResult(command, 0, "ok", "")

        with self.subTest("live"):
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                install_script = root / "install.sh"
                install_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                with patch.dict(
                    "os.environ",
                    {"OMH_HOME": "/real/operator/omh", "HERMES_HOME": "/real/operator/hermes"},
                ):
                    payload = run_install_script_smoke(
                        repo_root=root,
                        install_script=install_script,
                        work_dir=root / "work",
                        runner=runner,
                        timeout_seconds=5,
                    )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["observed"])
        self.assertEqual(payload["failed_step"], "")
        self.assertTrue(payload["retained_work_dir"])
        self.assertEqual(seen[0], ["sh", str(install_script.resolve())])
        self.assertNotIn([str((root / "work" / "bin" / "omh").resolve()), "doctor", "--json"], seen)
        self.assertIn([str((root / "work" / "bin" / "omh").resolve()), "--help"], seen)
        expected_omh_home = str((root / "work" / "home" / ".omh").resolve())
        expected_hermes_home = str((root / "work" / "home" / ".hermes").resolve())
        self.assertTrue(seen_env)
        self.assertTrue(all(env["OMH_HOME"] == expected_omh_home for env in seen_env))
        self.assertTrue(all(env["HERMES_HOME"] == expected_hermes_home for env in seen_env))
        self.assertTrue(all(env["OMH_HOME"] != "/real/operator/omh" for env in seen_env))
        self.assertTrue(all(env["HERMES_HOME"] != "/real/operator/hermes" for env in seen_env))
        self.assertEqual(payload["environment"]["OMH_HOME"], expected_omh_home)
        self.assertEqual(payload["environment"]["HERMES_HOME"], expected_hermes_home)
        self.assertTrue(payload["installed_command_smoke"]["ok"])
        self.assertTrue(payload["installed_command_smoke"]["observed"])
        self.assertEqual(payload["environment"]["OMH_RUN_SETUP"], "0")
        self.assertIn("isolated", payload["proof_boundary"])

    def test_install_script_smoke_default_runner_does_not_inherit_operator_controls(self) -> None:
        seen_env: list[dict[str, str]] = []

        def fake_run(command, *, stdout, stderr, text, timeout, check, env):
            del stdout, stderr, text, timeout, check
            run_env = dict(env or {})
            seen_env.append(run_env)
            if list(command)[0] == "sh":
                bin_dir = Path(run_env["OMH_BIN_DIR"])
                bin_dir.mkdir(parents=True, exist_ok=True)
                installed = bin_dir / "omh"
                installed.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                installed.chmod(0o755)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        with self.subTest("live"):
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                install_script = root / "install.sh"
                install_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                with patch.dict(
                    "os.environ",
                    {
                        "OMH_HOME": "/real/operator/omh",
                        "HERMES_HOME": "/real/operator/hermes",
                        "OMH_SCOPE": "project",
                        "OMH_PROFILE_PACKS": "cto-loop",
                        "OMH_SETUP_PROFILES": "1,3",
                        "OMH_DEFAULT_EXECUTOR": "claude-code",
                        "OMH_WITH_MCP": "1",
                        "OMH_WITH_PLUGIN": "1",
                        "OMH_PIP_ARGS": "--break-system-packages",
                    },
                    clear=False,
                ):
                    with patch("omh.release_smoke_core.subprocess.run", side_effect=fake_run):
                        payload = run_install_script_smoke(
                            repo_root=root,
                            install_script=install_script,
                            work_dir=root / "work",
                            timeout_seconds=5,
                        )

        self.assertTrue(payload["ok"])
        self.assertTrue(seen_env)
        blocked_keys = {
            "OMH_SCOPE",
            "OMH_PROFILE_PACKS",
            "OMH_SETUP_PROFILES",
            "OMH_DEFAULT_EXECUTOR",
            "OMH_WITH_MCP",
            "OMH_WITH_PLUGIN",
            "OMH_PIP_ARGS",
        }
        for run_env in seen_env:
            self.assertTrue(blocked_keys.isdisjoint(run_env))
            self.assertEqual(run_env["OMH_HOME"], str((root / "work" / "home" / ".omh").resolve()))
            self.assertEqual(run_env["HERMES_HOME"], str((root / "work" / "home" / ".hermes").resolve()))
            self.assertEqual(run_env["OMH_RUN_SETUP"], "0")
            self.assertEqual(run_env["OMH_SETUP_ARGS"], "")

    def test_exact_subprocess_runner_uses_only_explicit_env(self) -> None:
        with patch.dict("os.environ", {"OMH_SCOPE": "project", "OMH_PROFILE_PACKS": "cto-loop"}, clear=False):
            result = subprocess_runner_exact_env(
                [
                    sys.executable,
                    "-c",
                    "import os; print('OMH_SCOPE' in os.environ, 'OMH_PROFILE_PACKS' in os.environ, os.environ['HOME'])",
                ],
                5,
                {"HOME": "/tmp/omh-smoke-home"},
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "False False /tmp/omh-smoke-home")

    def test_install_script_smoke_fails_before_running_when_script_missing(self) -> None:
        def runner(command, _timeout, _env):  # pragma: no cover - missing script should stop first
            raise AssertionError(f"unexpected command: {command}")

        payload = run_install_script_smoke(repo_root="/tmp/no-such-omh-repo", runner=runner)

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["failed_step"], "install_script_missing")
        self.assertIn("--install-script", payload["recommended_next_action"])

    def test_live_smoke_records_successful_command_results(self) -> None:
        seen: list[list[str]] = []
        seen_env: list[dict[str, str]] = []

        def runner(command, _timeout, env):
            seen.append(list(command))
            seen_env.append(dict(env or {}))
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner, timeout_seconds=5, hermes_home="/tmp/hermes-smoke")

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["observed"])
        self.assertEqual(payload["hermes_cli"]["path"], "/usr/local/bin/hermes")
        self.assertEqual(seen[0], ["hermes", "skills", "tap", "add", "rlaope/oh-my-hermes"])
        self.assertEqual(seen[-1], ["hermes", "skills", "inspect", "rlaope/oh-my-hermes/skills/oh-my-hermes"])
        self.assertTrue(all(env["HERMES_HOME"] == str(Path("/tmp/hermes-smoke").resolve()) for env in seen_env))
        self.assertTrue(all(result["environment"]["HERMES_HOME"] == str(Path("/tmp/hermes-smoke").resolve()) for result in payload["results"]))
        self.assertTrue(all(result["ok"] for result in payload["results"]))
        self.assertIn("does not prove a later chat session", payload["proof_boundary"])
        self.assertFalse(payload["installed_command_smoke"]["observed"])

    def test_live_smoke_can_include_installed_command_smoke(self) -> None:
        seen: list[list[str]] = []

        def runner(command, _timeout, _env):
            seen.append(list(command))
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(
                runner=runner,
                timeout_seconds=5,
                hermes_home="/tmp/hermes-smoke",
                omh_home="/tmp/omh-smoke",
                omh_command="omh-dev",
                include_command_smoke=True,
            )

        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["installed_command_smoke"]["observed"])
        self.assertTrue(payload["installed_command_smoke"]["path_check"]["ok"])
        self.assertEqual(payload["installed_command_smoke"]["path_check"]["mode"], "live")
        self.assertIn(["omh-dev", "--help"], seen)
        self.assertIn(["omh-dev", "release", "skill-content-smoke", "--json"], seen)
        self.assertIn(
            [
                "omh-dev",
                "--omh-home",
                omh_home,
                "--hermes-home",
                hermes_home,
                "release",
                "hermes-smoke",
                "--install-path",
                "setup",
                "--omh-command",
                "omh-dev",
            ],
            seen,
        )

    def test_installed_command_smoke_failure_marks_release_smoke_failed(self) -> None:
        def runner(command, _timeout, _env):
            if list(command) == ["omh-dev", "--help"]:
                return CommandResult(command, 127, "", "missing omh")
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "installed_command_smoke")
        self.assertEqual(payload["installed_command_smoke"]["failed_step"], "installed_omh_help")
        self.assertIn("console script", payload["recommended_next_action"])

    def test_installed_command_smoke_failure_from_skill_content_marks_release_smoke_failed(self) -> None:
        def runner(command, _timeout, _env):
            if list(command) == ["omh-dev", "release", "skill-content-smoke", "--json"]:
                return CommandResult(command, 1, '{"ok": false}', "missing context rail")
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "installed_command_smoke")
        self.assertEqual(payload["installed_command_smoke"]["failed_step"], "installed_omh_skill_content")
        self.assertIn("skill-content-smoke", payload["installed_command_smoke"]["recommended_next_action"])

    def test_installed_command_smoke_fails_before_help_when_omh_is_not_on_path(self) -> None:
        def runner(command, _timeout, _env):  # pragma: no cover - path check should stop first
            raise AssertionError(f"unexpected command: {command}")

        with patch("omh.release.shutil.which", side_effect=lambda command: "/usr/local/bin/hermes" if command == "hermes" else None):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "installed_command_smoke")
        self.assertEqual(payload["installed_command_smoke"]["failed_step"], "installed_omh_path")
        self.assertFalse(payload["installed_command_smoke"]["observed"])
        self.assertTrue(payload["installed_command_smoke"]["path_check"]["observed"])
        self.assertFalse(payload["installed_command_smoke"]["path_check"]["ok"])
        self.assertEqual(payload["installed_command_smoke"]["results"], [])
        self.assertIn("command -v omh-dev", payload["installed_command_smoke"]["recommended_next_action"])

    def test_live_smoke_stops_on_required_failure(self) -> None:
        def runner(command, _timeout, _env):
            if list(command)[:3] == ["hermes", "skills", "install"]:
                return CommandResult(command, 1, "", "scan failed")
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "skill_install")
        self.assertEqual(len(payload["results"]), 2)
        self.assertIn("Hermes skill scan", payload["recommended_next_action"])

    def test_live_smoke_reports_missing_hermes_cli_without_running_steps(self) -> None:
        def runner(command, _timeout, _env):  # pragma: no cover - should not be called
            raise AssertionError(f"unexpected command: {command}")

        with patch("omh.release.shutil.which", return_value=None):
            payload = run_hermes_release_smoke(runner=runner)

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["failed_step"], "hermes_cli")
        self.assertEqual(payload["results"], [])

    def test_missing_hermes_cli_can_still_observe_installed_command_smoke(self) -> None:
        seen: list[list[str]] = []

        def runner(command, _timeout, _env):
            seen.append(list(command))
            return CommandResult(command, 0, "ok", "")

        def which(command: str) -> str | None:
            if command == "omh-dev":
                return "/usr/local/bin/omh-dev"
            return None

        with patch("omh.release.shutil.which", side_effect=which):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["failed_step"], "hermes_cli")
        self.assertTrue(payload["installed_command_smoke"]["observed"])
        self.assertIn(["omh-dev", "--help"], seen)
        self.assertEqual(payload["results"], [])

    def test_subprocess_runner_reports_missing_executable_as_command_failure(self) -> None:
        result = subprocess_runner(["/definitely/not/a/real/omh-command"], 1)

        self.assertEqual(result.returncode, 127)
        self.assertIn("No such file", result.stderr)

    def test_subprocess_runner_normalizes_timeout_bytes_output(self) -> None:
        result = subprocess_runner(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stdout.write('hello'); sys.stdout.flush(); sys.stderr.write('warn'); sys.stderr.flush(); time.sleep(5)",
            ],
            1,
        )

        self.assertEqual(result.returncode, 124)
        self.assertIn("hello", result.stdout)
        self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
