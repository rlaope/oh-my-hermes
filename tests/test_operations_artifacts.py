from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.operations import (
    build_operation_artifact,
    export_operation_artifact_markdown,
    list_operation_artifacts,
    show_operation_artifact,
    summarize_operation_artifact,
    validate_operation_artifact,
    validate_operations_store,
    write_operation_artifact,
)
from omh.hermes_ops import (
    build_scheduled_ops_blueprint,
    list_hermes_ops_blueprints,
    show_hermes_ops_blueprint,
    validate_hermes_ops_blueprint,
    validate_hermes_ops_store,
    write_hermes_ops_blueprint,
)
from omh.paths import OmhPaths
from omh.research_department import (
    build_research_department_plan,
    list_research_department_plans,
    show_research_department_plan,
    validate_research_department_plan,
    validate_research_department_store,
    write_research_department_plan,
)


class OperationsArtifactTests(unittest.TestCase):
    def test_scheduled_ops_blueprint_is_projection_not_runtime_evidence(self) -> None:
        blueprint = build_scheduled_ops_blueprint(
            "every morning check competitor news and send a Slack digest only if something changed",
            created_at="2026-06-16T00:00:00Z",
        )

        self.assertEqual(blueprint["schema_version"], "hermes_ops_blueprint/v1")
        self.assertEqual(blueprint["kind"], "scheduled-ops-blueprint")
        self.assertEqual(blueprint["observation_status"], "prepared")
        self.assertEqual(blueprint["projection"]["authority"], "projection_only")
        self.assertEqual(blueprint["schedule_intent"]["cadence"], "daily")
        self.assertEqual(blueprint["delivery_intent"]["surfaces"], ["slack"])
        self.assertEqual(blueprint["silence_policy"]["mode"], "only_report_changes")
        self.assertIn("automation-blueprint", {item["skill"] for item in blueprint["skill_suggestions"]})
        self.assertIn("web-research", {item["skill"] for item in blueprint["skill_suggestions"]})
        self.assertIn("host_cron_created", blueprint["not_evidence_until_observed"])
        self.assertIn("gateway_delivery_sent", blueprint["not_evidence_until_observed"])
        self.assertIn("source_retrieval_observed", blueprint["not_evidence_until_observed"])
        self.assertIn("review", blueprint["not_evidence_until_observed"])
        self.assertIn("ci", blueprint["not_evidence_until_observed"])
        self.assertIn("merge", blueprint["not_evidence_until_observed"])
        self.assertEqual(blueprint["status_card"]["not_observed"], blueprint["not_evidence_until_observed"])
        self.assertIn("not host cron creation", blueprint["prepared_is_not"])
        self.assertEqual(validate_hermes_ops_blueprint(blueprint), [])

    def test_scheduled_ops_blueprint_does_not_treat_content_numbers_as_time(self) -> None:
        for request in (
            "every week summarize top 10 competitors",
            "daily check 3 services",
        ):
            with self.subTest(request=request):
                blueprint = build_scheduled_ops_blueprint(request, created_at="2026-06-16T00:00:00Z")

                self.assertEqual(blueprint["schedule_intent"]["time_hint"], "")
                self.assertTrue(blueprint["schedule_intent"]["requires_confirmation"])

        for request, expected in (
            ("daily check services at 9am", "at 9am"),
            ("daily check services at 09:30", "at 09:30"),
            ("daily check services 09:30", "09:30"),
        ):
            with self.subTest(request=request):
                blueprint = build_scheduled_ops_blueprint(request, created_at="2026-06-16T00:00:00Z")

                self.assertEqual(blueprint["schedule_intent"]["time_hint"], expected)
                self.assertFalse(blueprint["schedule_intent"]["requires_confirmation"])

    def test_scheduled_ops_blueprint_store_round_trips_and_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            blueprint = build_scheduled_ops_blueprint(
                "매일 아침 경쟁사 뉴스를 조사해서 변화 있으면 슬랙으로 보내줘",
                created_at="2026-06-16T00:00:00Z",
            )

            written = write_hermes_ops_blueprint(paths, blueprint)

            self.assertEqual(show_hermes_ops_blueprint(paths, written["blueprint_id"])["title"], written["title"])
            self.assertEqual(len(list_hermes_ops_blueprints(paths)), 1)
            self.assertTrue(paths.hermes_ops_index_path.exists())
            validation = validate_hermes_ops_store(paths)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["blueprint_count"], 1)

            with self.assertRaises(ValueError):
                write_hermes_ops_blueprint(paths, blueprint)

    def test_scheduled_ops_blueprint_rejects_observed_runtime_claims(self) -> None:
        blueprint = build_scheduled_ops_blueprint("daily status digest", created_at="2026-06-16T00:00:00Z")
        blueprint["runtime_status"] = "observed"

        errors = validate_hermes_ops_blueprint(blueprint)

        self.assertIn("must not claim observed runtime or delivery status", "; ".join(errors))

    def test_scheduled_ops_blueprint_rejects_nested_observed_claims(self) -> None:
        blueprint = build_scheduled_ops_blueprint("daily status digest", created_at="2026-06-16T00:00:00Z")
        blueprint["schedule_intent"]["status"] = "observed"
        blueprint["delivery_intent"]["delivery_status"] = "delivered"

        errors = validate_hermes_ops_blueprint(blueprint)

        rendered = "; ".join(errors)
        self.assertIn("$.schedule_intent.status must remain prepared or not_observed", rendered)
        self.assertIn("$.delivery_intent.delivery_status must not claim observed runtime", rendered)

    def test_scheduled_ops_example_fixture_matches_blueprint_schema(self) -> None:
        fixture = Path("examples/hermes-ops/scheduled-competitor-digest.json")
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        generated = build_scheduled_ops_blueprint(
            "every morning check competitor news and send a Slack digest only if something changed",
            title="Scheduled ops: competitor digest",
            schedule="every morning",
            delivery="Slack digest",
            silence="only if something changed",
            source="example fixture",
            blueprint_id="20260616T000000Z-scheduled-ops-competitor-digest-example",
            created_at="2026-06-16T00:00:00Z",
        )

        self.assertEqual(validate_hermes_ops_blueprint(payload), [])
        self.assertEqual(payload["schema_version"], "hermes_ops_blueprint/v1")
        self.assertIn("gateway_delivery_sent", payload["not_evidence_until_observed"])
        self.assertEqual(payload, generated)

    def test_research_department_plan_is_projection_not_runtime_evidence(self) -> None:
        plan = build_research_department_plan(
            "every morning watch competitor news and brief me if something changed",
            created_at="2026-06-17T00:00:00Z",
            synthesis_tool="team knowledge summarizer",
            knowledge_store="markdown folder",
        )

        self.assertEqual(plan["schema_version"], "research_department_plan/v1")
        self.assertEqual(plan["kind"], "research-department-workflow")
        self.assertEqual(plan["observation_status"], "prepared")
        self.assertEqual(plan["projection"]["authority"], "projection_only")
        self.assertEqual([role["role"] for role in plan["roles"]], ["scout", "analyst", "briefer"])
        self.assertEqual(plan["cadence_intent"]["cadence"], "daily")
        self.assertEqual(plan["delivery_intent"]["surfaces"], ["report"])
        self.assertEqual(plan["source_inbox"]["schema_version"], "source_inbox/v1")
        self.assertEqual(plan["briefing_status"]["schema_version"], "briefing_status/v1")
        self.assertIn("research-department", {item["skill"] for item in plan["skill_chain"]})
        self.assertIn("web-research", {item["skill"] for item in plan["skill_chain"]})
        self.assertIn("synthesis_tool_query_observed", plan["not_evidence_until_observed"])
        self.assertIn("knowledge_store_write_observed", plan["not_evidence_until_observed"])
        self.assertIn("gateway_delivery_sent", plan["not_evidence_until_observed"])
        self.assertIn("source_retrieval_observed", plan["not_evidence_until_observed"])
        self.assertIn("projection metadata only", plan["prepared_is_not"])
        self.assertEqual(plan["synthesis_tool"]["type"], "knowledge_summarizer")
        self.assertEqual(plan["knowledge_store"]["type"], "markdown_folder")
        self.assertFalse(plan["synthesis_tool"]["query_observed"])
        self.assertFalse(plan["knowledge_store"]["write_observed"])
        self.assertNotIn("compatibility_aliases", plan["optional_integrations"])
        self.assertEqual(validate_research_department_plan(plan), [])

    def test_research_department_request_vendor_mentions_stay_concept_first_without_adapter(self) -> None:
        plan = build_research_department_plan(
            "daily research department using NotebookLM and Obsidian if possible",
            created_at="2026-06-17T00:00:00Z",
        )

        self.assertEqual(plan["synthesis_tool"]["type"], "hermes_synthesis")
        self.assertEqual(plan["synthesis_tool"]["vendor_hint"], "")
        self.assertEqual(plan["knowledge_store"]["type"], "local_markdown_folder")
        self.assertEqual(plan["knowledge_store"]["vendor_hint"], "")
        self.assertEqual(validate_research_department_plan(plan), [])

    def test_research_department_source_boundaries_shape_lane_skills(self) -> None:
        plan = build_research_department_plan(
            "prepare a weekly research digest",
            sources=["academic papers", "customer feedback", "competitor updates", "market reports"],
            created_at="2026-06-17T00:00:00Z",
        )

        detected = set(plan["source_policy"]["detected_source_types"])
        skills = {item["skill"] for item in plan["skill_chain"]}
        self.assertTrue({"papers", "customer", "competitor", "market"}.issubset(detected))
        self.assertIn("best-practice-research", skills)
        self.assertIn("feedback-triage", skills)
        self.assertEqual(plan["source_policy"]["source_boundaries"], ["academic papers", "customer feedback", "competitor updates", "market reports"])
        self.assertEqual(validate_research_department_plan(plan), [])

    def test_research_department_plan_store_round_trips_and_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            plan = build_research_department_plan(
                "매일 경쟁사와 논문 소식을 수집하고 충돌이 있으면 표시해서 브리핑해줘",
                created_at="2026-06-17T00:00:00Z",
            )

            written = write_research_department_plan(paths, plan)

            self.assertEqual(show_research_department_plan(paths, written["plan_id"])["title"], written["title"])
            self.assertEqual(len(list_research_department_plans(paths)), 1)
            self.assertTrue(paths.research_department_index_path.exists())
            validation = validate_research_department_store(paths)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["plan_count"], 1)

            with self.assertRaises(ValueError):
                write_research_department_plan(paths, plan)

    def test_research_department_plan_rejects_observed_claims(self) -> None:
        plan = build_research_department_plan("daily competitor research", created_at="2026-06-17T00:00:00Z")
        plan["source_inbox"]["buckets"]["raw_findings"]["status"] = "observed"
        plan["briefing_status"]["lanes"]["briefer"]["status"] = "delivered"
        plan["knowledge_store"]["write_observed"] = True
        plan["synthesis_tool"]["query_observed"] = True
        plan["synthesis_tool"]["workspace_observed"] = True
        plan["optional_integrations"]["synthesis_tool"]["execution_status"] = "completed"

        errors = validate_research_department_plan(plan)

        rendered = "; ".join(errors)
        self.assertIn("$.source_inbox.buckets.raw_findings.status must remain prepared or not_observed", rendered)
        self.assertIn("briefing_status.lanes.briefer.status must remain prepared or not_observed", rendered)
        self.assertIn("$.knowledge_store.write_observed must remain false in projection-only research plans", rendered)
        self.assertIn("$.synthesis_tool.query_observed must remain false in projection-only research plans", rendered)
        self.assertIn("$.synthesis_tool.workspace_observed must remain false in projection-only research plans", rendered)
        self.assertIn("optional_integrations.synthesis_tool.execution_status must not claim observed", rendered)

    def test_research_department_plan_accepts_legacy_tooling_aliases(self) -> None:
        plan = build_research_department_plan("daily competitor research", created_at="2026-06-17T00:00:00Z")
        plan.pop("knowledge_store")
        plan.pop("synthesis_tool")
        plan["optional_integrations"] = {
            "notebooklm": {"status": "prepared", "execution_observed": False},
            "obsidian": {"status": "prepared", "execution_observed": False},
        }
        plan["not_evidence_until_observed"] = [
            "source_retrieval_observed",
            "notebooklm_query_executed",
            "notebooklm_notebook_created",
            "obsidian_vault_written",
            "host_cron_created",
            "hermes_automation_enabled",
            "gateway_delivery_sent",
            "brief_delivered",
            "human_verification_complete",
            "paywall_or_access_resolved",
            "conflict_resolution_complete",
            "connector_invoked",
        ]

        self.assertEqual(validate_research_department_plan(plan), [])

    def test_research_department_plan_rejects_legacy_observed_boolean_claims(self) -> None:
        plan = build_research_department_plan("daily competitor research", created_at="2026-06-17T00:00:00Z")
        plan.pop("knowledge_store")
        plan.pop("synthesis_tool")
        plan["optional_integrations"] = {
            "notebooklm": {"status": "prepared", "execution_observed": True},
            "obsidian": {"status": "prepared", "execution_observed": True},
        }

        errors = validate_research_department_plan(plan)

        rendered = "; ".join(errors)
        self.assertIn("$.optional_integrations.notebooklm.execution_observed must remain false", rendered)
        self.assertIn("$.optional_integrations.obsidian.execution_observed must remain false", rendered)

    def test_research_department_example_fixture_matches_plan_schema(self) -> None:
        fixture = Path("examples/research-department/competitor-digest.json")
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        generated = build_research_department_plan(
            "every morning check competitor news and send a Slack digest only if something changed",
            title="Research department: competitor digest",
            cadence="every morning",
            delivery="Slack digest",
            storage="markdown folder",
            sources=["competitor news", "market updates"],
            synthesis_tool="team knowledge summarizer",
            knowledge_store="markdown folder",
            source="example fixture",
            plan_id="20260617T000000Z-research-department-competitor-digest-example",
            created_at="2026-06-17T00:00:00Z",
        )

        self.assertEqual(validate_research_department_plan(payload), [])
        self.assertEqual(payload["schema_version"], "research_department_plan/v1")
        self.assertIn("source_retrieval_observed", payload["not_evidence_until_observed"])
        self.assertEqual(payload, generated)

    def test_prepared_operating_rhythm_artifact_round_trips(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)

            record = build_operation_artifact(
                surface="operating-rhythm",
                kind="meeting",
                title="Leadership sync",
                summary="Agenda and record shell.",
                sections=["Agenda", "Decision prompts"],
            )
            written = write_operation_artifact(paths, record)

            self.assertEqual(written["schema_version"], "omh_operation_artifact/v1")
            self.assertEqual(written["observation_status"], "prepared")
            self.assertIn("meeting_held", written["not_evidence_until_observed"])
            self.assertEqual(show_operation_artifact(paths, written["artifact_id"])["title"], "Leadership sync")
            self.assertEqual(len(list_operation_artifacts(paths, surface="operating-rhythm")), 1)
            self.assertTrue(paths.operations_index_path.exists())
            self.assertEqual(json.loads(paths.operations_index_path.read_text(encoding="utf-8"))["authority"], "cache_only")

    def test_same_second_generated_artifact_ids_do_not_overwrite(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            created_at = "2026-06-11T00:00:00Z"
            first = build_operation_artifact(
                surface="operating-rhythm",
                kind="meeting",
                title="Leadership sync A",
                created_at=created_at,
            )
            second = build_operation_artifact(
                surface="operating-rhythm",
                kind="meeting",
                title="Leadership sync B",
                created_at=created_at,
            )

            self.assertNotEqual(first["artifact_id"], second["artifact_id"])
            write_operation_artifact(paths, first)
            write_operation_artifact(paths, second)

            records = list_operation_artifacts(paths, surface="operating-rhythm")
            self.assertEqual(len(records), 2)
            self.assertEqual({record["title"] for record in records}, {"Leadership sync A", "Leadership sync B"})

    def test_duplicate_operation_artifact_ids_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            first = build_operation_artifact(
                surface="operating-rhythm",
                kind="meeting",
                title="Leadership sync",
                artifact_id="shared-artifact",
            )
            duplicate = build_operation_artifact(
                surface="report-package",
                kind="weekly-report",
                title="Weekly report",
                artifact_id="shared-artifact",
            )
            write_operation_artifact(paths, first)

            with self.assertRaises(ValueError):
                write_operation_artifact(paths, duplicate)

    def test_operation_artifact_summaries_are_bounded(self) -> None:
        record = build_operation_artifact(
            surface="report-package",
            kind="weekly-report",
            title="Weekly report",
            summary="x" * 500,
            sections=["A", "B"],
            references=["notes"],
        )

        summary = summarize_operation_artifact(record)

        self.assertLessEqual(len(summary["summary"]), 240)
        self.assertEqual(summary["counts"]["sections"], 2)
        self.assertEqual(summary["counts"]["references"], 1)

    def test_observed_operating_rhythm_requires_supplied_evidence(self) -> None:
        errors = validate_operation_artifact(
            {
                "schema_version": "omh_operation_artifact/v1",
                "artifact_id": "a",
                "surface": "operating-rhythm",
                "kind": "retro",
                "title": "Sprint retro",
                "status": "recorded",
                "observation_status": "observed",
                "created_at": "2026-06-11T00:00:00Z",
                "updated_at": "2026-06-11T00:00:00Z",
                "source": "",
                "summary": "Looks done.",
                "inputs_summary": "",
                "sections": [],
                "decisions": [],
                "action_items": [],
                "metrics": [],
                "references": [],
                "assumptions": [],
                "not_evidence_until_observed": ["meeting_held"],
            }
        )

        self.assertIn("observed or mixed artifacts require supplied source", "; ".join(errors))

        record = build_operation_artifact(
            surface="operating-rhythm",
            kind="retro",
            title="Sprint retro",
            status="recorded",
            observation_status="observed",
            source="user supplied notes",
            action_items=["Fix handoff docs"],
        )
        self.assertEqual(validate_operation_artifact(record), [])

    def test_rejects_unknown_surface_kind_and_observation_status(self) -> None:
        with self.assertRaises(ValueError):
            build_operation_artifact(surface="unknown", kind="meeting", title="Bad")

        with self.assertRaises(ValueError):
            build_operation_artifact(surface="report-package", kind="postmortem", title="Bad")

        with self.assertRaises(ValueError):
            build_operation_artifact(
                surface="report-package",
                kind="ppt-outline",
                title="Bad",
                observation_status="complete",
            )

        with self.assertRaises(ValueError):
            build_operation_artifact(
                surface="report-package",
                kind="ppt-outline",
                title="Bad",
                artifact_id="../outside",
            )

        with self.assertRaises(ValueError):
            build_operation_artifact(
                surface="report-package",
                kind="ppt-outline",
                title="Bad",
                artifact_id="/tmp/outside",
            )

    def test_report_package_does_not_require_reliability_links(self) -> None:
        record = build_operation_artifact(
            surface="report-package",
            kind="ppt-outline",
            title="Monthly leadership deck",
            summary="PPT-ready outline.",
            sections=["Slide 1: Context", "Slide 2: Operating results"],
            assumptions=["Numbers are supplied by the user."],
        )

        self.assertEqual(validate_operation_artifact(record), [])
        self.assertNotIn("slo_pass", record["not_evidence_until_observed"])
        self.assertIn("binary_pptx_export", record["not_evidence_until_observed"])
        markdown = export_operation_artifact_markdown(record)
        self.assertIn("# Monthly leadership deck", markdown)
        self.assertIn("## Not Evidence Until Observed", markdown)

    def test_report_package_rejects_reliability_evidence_gates(self) -> None:
        record = {
            "schema_version": "omh_operation_artifact/v1",
            "artifact_id": "report",
            "surface": "report-package",
            "kind": "ppt-outline",
            "title": "Monthly leadership deck",
            "status": "draft",
            "observation_status": "prepared",
            "created_at": "2026-06-11T00:00:00Z",
            "updated_at": "2026-06-11T00:00:00Z",
            "source": "",
            "summary": "",
            "inputs_summary": "",
            "sections": [],
            "decisions": [],
            "action_items": [],
            "metrics": [],
            "references": [],
            "assumptions": [],
            "not_evidence_until_observed": ["stakeholder_approval", "slo_pass"],
        }

        errors = validate_operation_artifact(record)

        self.assertIn("report packages must not require reliability evidence links", "; ".join(errors))

    def test_observed_reliability_artifact_requires_metric_source_or_reference(self) -> None:
        errors = validate_operation_artifact(
            {
                "schema_version": "omh_operation_artifact/v1",
                "artifact_id": "rel",
                "surface": "reliability-review",
                "kind": "slo-review",
                "title": "API SLO",
                "status": "recorded",
                "observation_status": "observed",
                "created_at": "2026-06-11T00:00:00Z",
                "updated_at": "2026-06-11T00:00:00Z",
                "source": "",
                "summary": "SLO passed.",
                "inputs_summary": "",
                "sections": [],
                "decisions": [],
                "action_items": [],
                "metrics": [],
                "references": [],
                "assumptions": [],
                "not_evidence_until_observed": ["slo_pass"],
            }
        )

        self.assertIn("observed reliability artifacts require source, metric, or reference evidence", "; ".join(errors))

        record = build_operation_artifact(
            surface="reliability-review",
            kind="slo-review",
            title="API SLO",
            status="recorded",
            observation_status="observed",
            metrics=["availability=99.95"],
            references=["monitoring export"],
        )
        self.assertEqual(validate_operation_artifact(record), [])

    def test_index_is_cache_not_authority(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            record = build_operation_artifact(surface="report-package", kind="weekly-report", title="Weekly report")
            write_operation_artifact(paths, record)
            paths.operations_index_path.unlink()

            shown = show_operation_artifact(paths, record["artifact_id"])
            self.assertEqual(shown["artifact_id"], record["artifact_id"])
            validation = validate_operations_store(paths)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["index_authority"], "cache_only")

    def test_validate_store_reports_malformed_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            bad_dir = paths.operations_dir / "operating-rhythm"
            bad_dir.mkdir(parents=True)
            (bad_dir / "bad.json").write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")

            validation = validate_operations_store(paths)

            self.assertFalse(validation["ok"])
            self.assertIn("schema_version must be omh_operation_artifact/v1", " ".join(validation["errors"]))

    def test_show_rejects_path_traversal_artifact_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths_from_tmp(tmp)
            secret = root / "outside.json"
            secret.write_text(json.dumps({"schema_version": "omh_operation_artifact/v1", "title": "secret"}), encoding="utf-8")

        for unsafe_id in ("../outside", str(secret.with_suffix("")), "/tmp/outside", " unsafe"):
            with self.subTest(unsafe_id=unsafe_id):
                with self.assertRaises(FileNotFoundError):
                    show_operation_artifact(paths, unsafe_id)


def _paths_from_tmp(tmp: str) -> OmhPaths:
    root = Path(tmp)
    return OmhPaths(root / ".omh", root / ".hermes")
