from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.routing.catalog_questions import is_file_or_text_lookup_question, is_skill_catalog_question


class CatalogQuestionTests(unittest.TestCase):
    def test_workflow_catalog_questions_are_detected(self) -> None:
        cases = (
            "what can OMH do?",
            "what can I do with OMH?",
            "what does OMH do?",
            "how can OMH help my team?",
            "Can OMH help with planning, research, and coding?",
            "what can OMH do for planning/research/coding?",
            "Can OMH help with planning/research/coding?",
            "what workflows can OMH do?",
            "what skills can OMH do?",
            "what commands can OMH do?",
            "show me the OMH commands",
            "show me OMH workflows",
            "show me the OMH skills",
            "OMH로 뭐 할 수 있어?",
            "OMH가 뭐 해줄 수 있어?",
            "OMH는 뭘 도와줘?",
            "OMH가 우리 팀에서 어떻게 쓰여?",
            "OMH로 계획/리서치/코딩까지 도와줄 수 있어?",
            "OMH에서 deep-interview/ralplan/loop는 뭐야?",
            "OMH로 할 수 있는 workflow가 뭐야?",
            "OMH 명령어 뭐 있어?",
            "skill들은 뭐 있어?",
            "what OMH workflows are available?",
            "¿Qué comandos de OMH están disponibles?",
            "Quelles commandes OMH sont disponibles ?",
            "Welche OMH Workflows gibt es?",
            "OMHで使えるスキルは？",
            "OMH 有哪些工作流？",
            "Quais workflows do OMH estão disponíveis?",
            "Какие команды OMH доступны?",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(is_skill_catalog_question(message))

    def test_operator_command_questions_are_not_catalog_questions(self) -> None:
        cases = (
            "show me the command to install OMH",
            "what command is available to install OMH?",
            "what commands are available to install OMH?",
            "what command should I run to verify installation?",
            "what can OMH do to install itself?",
            "¿Qué comando debería ejecutar para instalar OMH?",
            "quelle commande dois-je exécuter pour installer OMH?",
            "OMH 설치 명령어 알려줘",
            "doctor 확인 명령어 뭐야?",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertFalse(is_skill_catalog_question(message))

    def test_generic_debugging_and_file_questions_do_not_open_catalog(self) -> None:
        cases = (
            "what skills are needed to debug this Python error?",
            "which workflow should I use for this bug?",
            "what does OMH do in src/omh/routing/catalog_questions.py?",
            "explain what OMH does in this README section",
            "search docs/WORKFLOWS.md for loop",
            "show img-summary in README.md",
            "README 요약해줘",
            "how can Hermes help my team?",
            "list commands in this file",
            "show workflows mentioned in docs/WORKFLOWS.md",
            "which files mention skill routing?",
            "list files that mention command injection",
            "이 파일 요약해줘",
            "이 파일에서 command injection 언급 목록 찾아줘",
            "이 파일에서 기능 목록 찾아줘",
            "이 경로에서 workflow 언급 찾아줘",
            "command not found: omh",
            "comando no encontrado: omh",
            "commande introuvable: omh",
            "Befehl nicht gefunden: omh",
            "コマンドが見つかりません: omh",
            "找不到命令: omh",
            "프리렌이 OMH 안 쓰고 일반 도구로 이미지 만들었어",
            "이미지 생성 요청을 했는데 OMH를 안 썼어",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertFalse(is_skill_catalog_question(message))

    def test_short_file_summary_requests_are_file_lookup_questions(self) -> None:
        for message in ("README 요약해줘", "이 파일 요약해줘"):
            with self.subTest(message=message):
                self.assertTrue(is_file_or_text_lookup_question(message))

    def test_release_claim_review_is_not_file_lookup_fallback(self) -> None:
        message = "릴리즈 전에 README 주장과 실제 기능이 맞는지 검토해줘"

        self.assertFalse(is_skill_catalog_question(message))
        self.assertFalse(is_file_or_text_lookup_question(message))


if __name__ == "__main__":
    unittest.main()
