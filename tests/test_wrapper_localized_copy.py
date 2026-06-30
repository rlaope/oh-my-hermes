import unittest

from omh.wrapper.localized_copy import (
    chat_copy,
    detect_copy_locale,
    is_localized_locale,
    prefers_korean_copy,
    skill_picker_body,
    skill_picker_headline,
)


class WrapperLocalizedCopyTests(unittest.TestCase):
    def test_locale_detection_is_local_and_deterministic(self) -> None:
        cases = {
            "OMH가 어떤 스킬 있는지 알려줘": "ko",
            "OMHで使えるスキルは？": "ja",
            "OMH 有哪些工作流？": "zh",
            "¿Qué comandos de OMH están disponibles?": "es",
            "Quelles commandes OMH sont disponibles ?": "fr",
            "Welche OMH Workflows gibt es?": "de",
            "what OMH workflows are available?": "en",
        }

        for message, locale in cases.items():
            with self.subTest(message=message):
                self.assertEqual(detect_copy_locale(message), locale)
                self.assertEqual(is_localized_locale(locale), locale != "en")

        self.assertTrue(prefers_korean_copy("OMH가 어떤 스킬 있는지 알려줘"))
        self.assertFalse(prefers_korean_copy("OMH 有哪些工作流？"))

    def test_core_cards_keep_multilingual_copy_in_catalog(self) -> None:
        cases = (
            ("img_summary", "en", "shareable image-card brief"),
            ("img_summary", "ja", "画像カード"),
            ("paper_learning", "fr", "paper-learning card"),
            ("source_finder", "zh", "source-finder plan"),
            ("web_research", "es", "research"),
            ("agent_ops_review", "ko", "관리자 관점"),
            ("workflow_learning_missed_route", "de", "missed-route feedback"),
            ("file_lookup", "ko", "파일/텍스트 확인"),
        )

        for copy_id, locale, expected_text in cases:
            with self.subTest(copy_id=copy_id, locale=locale):
                self.assertIn(expected_text, chat_copy(copy_id, locale=locale).body)

        self.assertIn("shareable image-card brief", chat_copy("img_summary", locale="unsupported").body)
        self.assertIn("이미지 안 문구", chat_copy("img_summary", korean=True).body)

    def test_skill_picker_copy_keeps_machine_contract_terms_visible(self) -> None:
        family_lines = ["- Plan and decide: deep-interview, ralplan."]

        english_body = skill_picker_body(catalog_question=True, locale="en", family_lines=family_lines)
        korean_body = skill_picker_body(catalog_question=True, locale="ko", family_lines=family_lines)
        japanese_body = skill_picker_body(catalog_question=True, locale="ja", family_lines=family_lines)
        chinese_body = skill_picker_body(catalog_question=True, locale="zh", family_lines=family_lines)

        self.assertEqual(skill_picker_headline(catalog_question=True, locale="en"), "Here are the OMH workflows.")
        self.assertEqual(skill_picker_headline(catalog_question=True, locale="ko"), "OMH workflow 목록입니다.")
        self.assertEqual(skill_picker_headline(catalog_question=True, locale="ja"), "OMH workflow 一覧です。")
        self.assertEqual(skill_picker_headline(catalog_question=True, locale="zh"), "这是 OMH workflow 列表。")
        self.assertIn("shell command", english_body)
        self.assertIn("shell 명령 승인을 받지 않아도", korean_body)
        self.assertIn("shell command", japanese_body)
        self.assertIn("shell command", chinese_body)
        self.assertIn("Route for me:", english_body)
        self.assertIn("Route for me:", korean_body)
        self.assertIn("Route for me:", japanese_body)
        self.assertIn("Route for me:", chinese_body)
        self.assertIn(family_lines[0], english_body)
        self.assertIn(family_lines[0], korean_body)
        self.assertIn(family_lines[0], japanese_body)
        self.assertIn(family_lines[0], chinese_body)


if __name__ == "__main__":
    unittest.main()
