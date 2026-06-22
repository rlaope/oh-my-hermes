from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.paper_learning import (
    PAPER_LEARNING_CARD_SCHEMA_VERSION,
    PAPER_LEARNING_NOT_OBSERVED,
    build_coverage_ledger,
    build_paper_learning_card,
    normalize_paper_learning_level,
    normalize_paper_source_state,
    validate_paper_learning_card,
)


class PaperLearningContractTests(unittest.TestCase):
    def test_level_aliases_keep_contract_ids(self) -> None:
        self.assertEqual(normalize_paper_learning_level("very easy"), "very_easy")
        self.assertEqual(normalize_paper_learning_level("전문가급"), "expert")
        self.assertEqual(normalize_paper_learning_level("moderate"), "moderate")
        self.assertEqual(normalize_paper_learning_level(None), "choose")
        self.assertEqual(normalize_paper_learning_level("surprise me"), "choose")

    def test_source_state_distinguishes_metadata_excerpt_extraction_and_full_text(self) -> None:
        metadata = normalize_paper_source_state("metadata_only")
        self.assertEqual(metadata["state"], "metadata_only")

        excerpt = normalize_paper_source_state("metadata_only", observed_sections=["Abstract"])
        self.assertEqual(excerpt["state"], "excerpt_text_observed")
        self.assertEqual(excerpt["observed_sections"], ["Abstract"])

        partial = normalize_paper_source_state(
            "full_text_observed",
            observed_sections=["Abstract", "Method"],
            missing_sections=["Results"],
            evidence_ref="extract:1",
        )
        self.assertEqual(partial["state"], "file_text_extraction_observed")
        self.assertEqual(partial["evidence_ref"], "extract:1")

    def test_coverage_ledger_marks_observed_and_missing_sections(self) -> None:
        ledger = build_coverage_ledger(
            observed_sections=["Abstract"],
            missing_sections=["Figures, tables, and equations"],
            sections=["Abstract", "Method", "Figures, tables, and equations"],
        )

        self.assertEqual(ledger[0]["status"], "observed")
        self.assertEqual(ledger[1]["status"], "prepared")
        self.assertEqual(ledger[2]["status"], "missing")
        self.assertTrue(all(item["explanation_status"] == "pending" for item in ledger))

    def test_paper_learning_card_preserves_boundaries(self) -> None:
        card = build_paper_learning_card(
            title="Attention Is All You Need",
            authors=["Vaswani et al."],
            source_ref="arxiv:1706.03762",
            level="expert",
            source_state="file_text_extraction_observed",
            observed_sections=["Abstract", "Introduction"],
            missing_sections=["Figures, tables, and equations"],
            evidence_ref="wrapper-extract-001",
        )

        self.assertEqual(card["schema_version"], PAPER_LEARNING_CARD_SCHEMA_VERSION)
        self.assertEqual(card["level"], "expert")
        self.assertEqual(card["paper_identity"]["authors"], ["Vaswani et al."])
        self.assertEqual(card["source_state"]["state"], "file_text_extraction_observed")
        self.assertIn("coverage_preserving_not_lossy_summary", card["coverage_policy"])
        self.assertIn("continue_next_section", card["available_actions"])
        for boundary in PAPER_LEARNING_NOT_OBSERVED:
            self.assertIn(boundary, card["not_observed"])
        self.assertEqual(validate_paper_learning_card(card), [])


if __name__ == "__main__":
    unittest.main()
