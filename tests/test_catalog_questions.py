from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.routing.catalog_questions import is_skill_catalog_question


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
            "what does OMH do in src/routing/catalog_questions.py?",
            "explain what OMH does in this README section",
            "search docs/WORKFLOWS.md for loop",
            "show img-summary in README.md",
            "how can Hermes help my team?",
            "list commands in this file",
            "show workflows mentioned in docs/WORKFLOWS.md",
            "which files mention skill routing?",
            "list files that mention command injection",
            "이 파일에서 command injection 언급 목록 찾아줘",
            "이 파일에서 기능 목록 찾아줘",
            "이 경로에서 workflow 언급 찾아줘",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertFalse(is_skill_catalog_question(message))


if __name__ == "__main__":
    unittest.main()
