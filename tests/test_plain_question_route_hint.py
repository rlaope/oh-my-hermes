"""The route hint skips token-only rule matches for a plain knowledge question.

"Explain what a JWT is" shares words with the skill catalog but asks for no
work, so no hint. A phrase match, a guard, or a direct invocation keeps its hint.
"""

from __future__ import annotations

import unittest

from omh.plugin_bundle.omh.awareness import awareness_route_hint


def _workflows(message: str) -> list[str]:
    payload = awareness_route_hint(message) or {}
    return [str(hint.get("workflow")) for hint in payload.get("hints", []) if isinstance(hint, dict)]


class PlainQuestionRouteHintTest(unittest.TestCase):
    def test_plain_questions_get_no_hint(self) -> None:
        for message in ("Explain what a JWT is", "What's the difference between git merge and rebase?"):
            with self.subTest(message=message):
                self.assertEqual(_workflows(message), [])

    def test_phrase_match_keeps_paper_learning(self) -> None:
        self.assertIn("paper-learning", _workflows("Explain this paper at beginner level"))

    def test_work_request_keeps_ulw_work(self) -> None:
        self.assertIn("ulw-work", _workflows("merge this PR after review"))

    def test_work_questions_keep_their_hint(self) -> None:
        cases = (
            ("Can you do market sizing for dental clinics in Korea?", "ulw-research"),
            ("CI 통과했어?", "ulw-work"),
            ("should we use rlvr or dpo for the math model", "model-finetuning"),
            ("\nExplain TCP vs UDP briefly", "paper-learning"),
            ("Explain TCP https://example.com", "paper-learning"),
        )
        for message, workflow in cases:
            with self.subTest(message=message):
                self.assertIn(workflow, _workflows(message))

    def test_direct_invocation_keeps_its_hint(self) -> None:
        self.assertIn("ulw-plan", _workflows("/ulw-plan add a retry to the uploader"))


if __name__ == "__main__":
    unittest.main()
