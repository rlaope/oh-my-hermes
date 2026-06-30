import unittest

from omh.wrapper.localized_copy import (
    chat_copy,
    prefers_korean_copy,
    skill_picker_body,
    skill_picker_headline,
)


class WrapperLocalizedCopyTests(unittest.TestCase):
    def test_korean_detection_is_hangul_based_and_local_only(self) -> None:
        self.assertTrue(prefers_korean_copy("OMH가 어떤 스킬 있는지 알려줘"))
        self.assertFalse(prefers_korean_copy("what OMH workflows are available?"))
        self.assertFalse(prefers_korean_copy("OMH 有哪些工作流？"))

    def test_core_cards_keep_english_and_korean_copy_in_catalog(self) -> None:
        cases = (
            ("img_summary", "shareable image-card brief", "이미지 안 문구"),
            ("paper_learning", "paper-learning card", "섹션별 커버리지"),
            ("source_finder", "source-finder plan", "데이터셋"),
            ("web_research", "source boundaries", "조사 범위"),
            ("workflow_learning_missed_route", "missed-route feedback", "missed-route 피드백"),
            ("file_lookup", "file or text lookup", "파일/텍스트 확인"),
        )

        for copy_id, english_text, korean_text in cases:
            with self.subTest(copy_id=copy_id):
                self.assertIn(english_text, chat_copy(copy_id, korean=False).body)
                self.assertIn(korean_text, chat_copy(copy_id, korean=True).body)

    def test_skill_picker_copy_keeps_machine_contract_terms_visible(self) -> None:
        family_lines = ["- Plan and decide: deep-interview, ralplan."]

        english_body = skill_picker_body(catalog_question=True, korean=False, family_lines=family_lines)
        korean_body = skill_picker_body(catalog_question=True, korean=True, family_lines=family_lines)

        self.assertEqual(skill_picker_headline(catalog_question=True, korean=False), "Here are the OMH workflows.")
        self.assertEqual(skill_picker_headline(catalog_question=True, korean=True), "OMH workflow 목록입니다.")
        self.assertIn("shell command", english_body)
        self.assertIn("shell 명령 승인을 받지 않아도", korean_body)
        self.assertIn("Route for me:", english_body)
        self.assertIn("Route for me:", korean_body)
        self.assertIn(family_lines[0], english_body)
        self.assertIn(family_lines[0], korean_body)


if __name__ == "__main__":
    unittest.main()

