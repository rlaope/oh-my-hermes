from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.materials import (
    build_material_artifact,
    export_material_artifact_markdown,
    list_material_artifacts,
    material_qa_ladder,
    show_material_artifact,
    validate_material_artifact,
    validate_materials_store,
    write_material_artifact,
)
from omh.paths import OmhPaths


class MaterialArtifactTests(unittest.TestCase):
    def test_material_plan_separates_handoff_export_qa_and_approval(self) -> None:
        record = build_material_artifact(
            kind="spreadsheet",
            title="Sales report package",
            target_formats=["xlsx", "pdf"],
            summary="Prepare sales report for leadership.",
            audience="leadership",
            source_inputs=["revenue.csv"],
            outline_sections=["Revenue trend", "Churn drivers"],
            missing_inputs=["approved revenue numbers"],
            export_status="handoff_prepared",
            handoff_target="document generator",
        )

        self.assertEqual(record["schema_version"], "omh_material_artifact/v1")
        self.assertEqual(record["target_formats"], ["xlsx", "pdf"])
        self.assertEqual(record["export_status"], "handoff_prepared")
        self.assertIn("binary_export", record["not_evidence_until_observed"])
        self.assertIn("formula_recalculation", record["not_evidence_until_observed"])
        self.assertTrue(all(check["status"] == "planned" for check in record["qa_checks"]))
        self.assertIn("formula_recalculation", {check["check"] for check in record["qa_checks"]})
        self.assertIn("render_preview", {check["check"] for check in record["qa_checks"]})

    def test_observed_export_requires_file_and_observed_qa(self) -> None:
        missing_file = build_material_artifact(
            kind="deck",
            title="Leadership deck",
            target_formats=["pptx"],
            export_status="prepared",
        )
        missing_file["export_status"] = "observed"

        self.assertIn("observed material export requires observed_files", "; ".join(validate_material_artifact(missing_file)))

        missing_qa = build_material_artifact(
            kind="deck",
            title="Leadership deck",
            target_formats=["pptx"],
            export_status="prepared",
            observed_files=["/tmp/deck.pptx"],
        )
        missing_qa["export_status"] = "observed"

        self.assertIn("observed material export requires at least one observed QA check", "; ".join(validate_material_artifact(missing_qa)))

        observed = build_material_artifact(
            kind="deck",
            title="Leadership deck",
            target_formats=["pptx"],
            export_status="observed",
            observed_files=["/tmp/deck.pptx"],
            qa_checks=[{"format": "pptx", "check": "render_screenshot", "status": "observed", "evidence": "/tmp/deck.png"}],
        )

        self.assertEqual(validate_material_artifact(observed), [])

    def test_material_store_lists_shows_validates_and_exports_markdown(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            record = build_material_artifact(
                kind="proposal",
                title="Korean HWP proposal",
                target_formats=["hwp", "pdf"],
                summary="Prepared proposal handoff.",
                missing_inputs=["legal clause approval"],
            )

            written = write_material_artifact(paths, record)

            self.assertEqual(show_material_artifact(paths, written["material_id"])["title"], "Korean HWP proposal")
            self.assertEqual(len(list_material_artifacts(paths, kind="proposal")), 1)
            validation = validate_materials_store(paths)
            self.assertTrue(validation["ok"])
            markdown = export_material_artifact_markdown(written)
            self.assertIn("# Korean HWP proposal", markdown)
            self.assertIn("## QA Checks", markdown)
            self.assertIn("binary_export", markdown)

    def test_material_qa_ladder_is_format_specific(self) -> None:
        ladder = material_qa_ladder(["xlsx", "pdf", "hwp"])

        self.assertEqual(ladder["schema_version"], "omh_material_qa_ladder/v1")
        self.assertIn("formula_recalculation", ladder["formats"]["xlsx"]["checks"])
        self.assertIn("render_preview", ladder["formats"]["pdf"]["checks"])
        self.assertIn("locale_font_check", ladder["formats"]["hwp"]["checks"])


if __name__ == "__main__":
    unittest.main()
