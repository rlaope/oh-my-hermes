"""The research-lane skills say what their findings required, in the text a model reads."""

from __future__ import annotations

import unittest

from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import builtin_skill_templates


class ResearchLaneSkillTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bodies = {t.name: t.content for t in builtin_skill_templates()}
        self.refs = {(r.skill_name, r.relative_path): r.content for r in builtin_skill_reference_templates()}

    def test_long_document_reading_uses_hermes_environment_rule_and_a_durable_ledger(self) -> None:
        body = self.bodies["long-document-reading"]
        self.assertNotIn("with `pip install` once", body)
        self.assertNotIn("install the one it names once with `pip install`", body)
        self.assertIn("Never `pip install` into the interpreter that runs Hermes", body)
        # Stated by presence: the floor pdf skill has no documents-environment block.
        self.assertIn("When the skill has no such block (Hermes before it, including the floor v2026.9.7)", body)
        self.assertIn("task-local virtual environment", body)
        self.assertIn("`<PY_MUPDF> <scripts dir>/extract_pymupdf.py", body)
        self.assertIn("the range's start page minus one", body)
        self.assertIn("with no `--pages`", body)
        self.assertIn("`command -v <name>`", body)
        self.assertNotIn("re-plan the remaining", body)
        self.assertNotIn("`python pdf_read.py", body)
        self.assertNotIn('"$PY"', body)
        self.assertIn("`extract_pymupdf.py` has no `--password`", body)
        self.assertIn("PDF page index", body)
        self.assertIn("ignore its `read_window` and `brief`", body)
        self.assertIn("planning again with the same numbers returns the same plan", body)
        limits = self.refs[("long-document-reading", "references/hermes-pdf-limits.md")]
        self.assertIn("`pdfplumber`; `--meta` also `pypdf`", limits)

    def test_the_ledger_text_names_only_fields_the_plan_tool_has(self) -> None:
        from pathlib import Path

        from omh.plugin_bundle.omh.tools.document_plan_tool import OMH_DOCUMENT_PLAN_SCHEMA

        properties = OMH_DOCUMENT_PLAN_SCHEMA["parameters"]["properties"]
        self.assertEqual(properties["action"]["enum"], ["plan", "show", "mark"])
        body = self.bodies["long-document-reading"]
        for field in ("source", "pages", "outline", "plan_id", "budget_chars", "chunk", "state"):
            with self.subTest(field=field):
                self.assertIn(field, properties)
                self.assertIn(field, body)
        self.assertEqual(properties["outline"]["items"]["required"], ["title", "page"])
        planner = Path(__import__("omh.plugin_bundle.omh.document_chunk_plan", fromlist=["x"]).__file__).read_text()
        self.assertIn("read_window", planner)

    def test_data_analysis_computes_with_code_and_guards_statistics(self) -> None:
        body = self.bodies["data-analysis"]
        self.assertIn("loaded with code", body)
        self.assertIn("n per group", body)
        self.assertIn("report association as association", body)
        self.assertIn("flagging that five per group makes the result fragile", body)

    def test_geospatial_refuses_web_mercator_in_the_text_and_names_the_input_format(self) -> None:
        body = self.bodies["geospatial-analysis"]
        self.assertIn("refuses them for real layers", body)
        self.assertIn("Never add or edit `data_class` or `fixture_id`", body)
        self.assertIn("reads GeoJSON only", body)

    def test_systematic_review_states_the_same_model_limit_and_deduplication(self) -> None:
        body = self.bodies["systematic-review"]
        self.assertIn("`delegate_task` takes no per-child model", body)
        self.assertIn("deduplicated across databases", body)

    def test_wiki_hands_to_llm_wiki_only_when_installed(self) -> None:
        text = self.bodies["wiki"] + "".join(c for (s, _), c in self.refs.items() if s == "wiki")
        self.assertIn("when it is installed", text)
        self.assertNotIn("Hermes' bundled `llm-wiki`", text)

    def test_live_info_runs_the_lookup_and_names_loadable_recovery_skills(self) -> None:
        body = self.bodies["live-info-operator"]
        self.assertIn("The lookup was run with an available tool", body)
        self.assertIn("`omh-toolbelt-readiness`", body)
        self.assertIn("`omh-apps`", body)

    def test_docs_do_not_pre_write_the_product_identity(self) -> None:
        text = "".join(c for (s, _), c in self.refs.items() if s == "product-docs")
        self.assertNotIn("engineering-intelligence", text)


if __name__ == "__main__":
    unittest.main()
