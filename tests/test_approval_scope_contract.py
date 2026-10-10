"""Contract for what an approval covers in ralplan and deep-interview (issue #2049).

`ralplan` takes plan acceptance from the answer the user gave -- the status and
value the question tool returns, or the user's own reply -- and never from the
wording of the question. An acceptance question that times out, is dismissed,
or returns with no answer leaves the plan unaccepted: no acceptance is
recorded, no handoff is prepared, nothing starts. A missing answer is not a
refusal either, the same split the typed runtime approval receipts keep
between an unanswered confirmation and a `denied` one.

`deep-interview` gains one sentence: a yes to an idea approves only the idea,
and a later plan, handoff, or change is accepted at its own gate.

Every assertion re-derives from the producers, never from the generated
`skills/` or `agent-skills/` trees. `ralplan`'s `portable_overrides` quality
bar replaces the Hermes one wholesale, so the portable body is checked on its
own. The portable `deep-interview` body has no interview protocol section, so
the sentence is a Hermes-only rule and only the Hermes body is checked.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_templates
from omh.skills.render import agent_skill_templates, workflow_skill_from_definition
from omh.skills.validation import STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING

RALPLAN_NO_ANSWER_TOKENS = (
    "times out",  # the three ways a question ends without an answer
    "is dismissed",
    "returns with no answer",
    "the plan stays unaccepted",  # the gate stays closed
    "record no acceptance",
    "prepare no handoff",
    "start nothing",
    "not a refusal either",  # an unanswered question is not a `denied` answer
)

RALPLAN_ANSWER_RECORD_TOKENS = (
    "Take plan acceptance only from the answer the user gave",
    "the response status and value the question tool returns",  # the record that decides
    "never from the wording of the question you asked",
)

DEEP_INTERVIEW_TOKENS = (
    "A yes to an idea approves only the idea",
    "a later plan, handoff, or change is accepted at its own gate",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _ralplan_hermes_body() -> str:
    definition = next(item for item in builtin_definitions() if item.name == "ralplan")
    return _flat(workflow_skill_from_definition(definition, definition.name).content)


def _ralplan_portable_body() -> str:
    return _flat(next(item.content for item in agent_skill_templates() if item.name == "ulw-plan"))


def _deep_interview_hermes_body() -> str:
    return _flat(next(item.content for item in builtin_skill_templates() if item.name == "deep-interview"))


class ApprovalScopeContractTests(unittest.TestCase):
    def test_ralplan_hermes_body_carries_the_timeout_dismiss_no_answer_tokens(self) -> None:
        body = _ralplan_hermes_body()
        for token in RALPLAN_NO_ANSWER_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_ralplan_hermes_body_carries_the_answer_record_not_wording_tokens(self) -> None:
        body = _ralplan_hermes_body()
        for token in RALPLAN_ANSWER_RECORD_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_ralplan_portable_body_carries_the_same_tokens(self) -> None:
        body = _ralplan_portable_body()
        for token in RALPLAN_NO_ANSWER_TOKENS + RALPLAN_ANSWER_RECORD_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_deep_interview_hermes_body_carries_the_idea_approval_sentence_tokens(self) -> None:
        body = _deep_interview_hermes_body()
        for token in DEEP_INTERVIEW_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_shipped_ralplan_and_deep_interview_bodies_stay_under_the_byte_ceiling(self) -> None:
        # Measure the bodies that ship: `deep-interview` is the bespoke
        # `deep_interview_skill()` render, not the generic workflow render.
        shipped = {item.name: item.content for item in builtin_skill_templates()}
        bodies = {name: shipped[name] for name in ("ralplan", "deep-interview")}
        for name, body in bodies.items():
            with self.subTest(skill=name):
                self.assertLessEqual(len(body.encode("utf-8")), STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING)


if __name__ == "__main__":
    unittest.main()
