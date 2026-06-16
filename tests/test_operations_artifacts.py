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
        self.assertIn("not host cron creation", blueprint["prepared_is_not"])
        self.assertEqual(validate_hermes_ops_blueprint(blueprint), [])

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

        self.assertEqual(validate_hermes_ops_blueprint(payload), [])
        self.assertEqual(payload["schema_version"], "hermes_ops_blueprint/v1")
        self.assertIn("gateway_delivery_sent", payload["not_evidence_until_observed"])

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
