from __future__ import annotations

import unittest

from omh.routing.localization import normalized_phrase, routing_tokens
from omh.routing.policy import EVERYDAY_SENSE_PHRASES, everyday_sense_phrase_unanchored
from omh.skills.catalog import routable_definitions


class EverydaySensePhraseTableTests(unittest.TestCase):
    def test_every_phrase_is_one_of_the_skills_own_triggers_or_its_name(self) -> None:
        # The table withdraws a skill on a phrase the skill itself claims. A
        # phrase that is not the skill's own would withdraw it on a sentence
        # it was never matched by, which is a silent reach loss.
        definitions = {definition.name: definition for definition in routable_definitions()}
        for skill, (phrases, _anchors) in EVERYDAY_SENSE_PHRASES.items():
            self.assertIn(skill, definitions, skill)
            own = {normalized_phrase(trigger) for trigger in definitions[skill].triggers}
            own.add(normalized_phrase(skill))
            for phrase in phrases:
                self.assertIn(normalized_phrase(phrase), own, f"{skill}: {phrase}")

    def test_every_anchor_word_survives_tokenization(self) -> None:
        # An anchor the tokenizer drops (a stopword, or too short) can never
        # match, so it reads as coverage the rule does not have.
        for skill, (_phrases, anchors) in EVERYDAY_SENSE_PHRASES.items():
            dead = sorted(anchor for anchor in anchors if anchor not in routing_tokens(anchor))
            self.assertEqual([], dead, skill)

    def test_everyday_sense_withdraws_and_lane_sense_keeps_the_skill(self) -> None:
        cases = (
            ("failure-signal-audit", "my phone had a silent failure of the alarm this morning", True),
            ("failure-signal-audit", "hunt for silent failures in the sync service", False),
            ("harness-session-inventory", "how many harness sessions does a sled dog need before a race", True),
            ("harness-session-inventory", "list my harness sessions", False),
            ("ops-review", "what is a weekly status review in a school parent meeting", True),
            ("ops-review", "prepare the weekly status review for the team", False),
            ("physical-device-readiness", "is a camera gate at the driveway worth installing", True),
            ("physical-device-readiness", "set up the camera gate before the print starts", False),
            ("skill-health", "what are some habits that keep your skill health up as a pianist", True),
            ("skill-health", "check skill health", False),
            ("adversarial-consensus", "summarize the independent perspectives in this essay about city parks", True),
            ("adversarial-consensus", "get independent perspectives on this migration plan", False),
            ("media-input-operator", "what is media input on an old vcr", True),
            ("media-input-operator", "take this media input and extract text", False),
            ("cancel", "how do i cancel my gym membership", True),
            ("cancel", "cancel the running loop", False),
            ("doctor", "how long does it take to become a doctor", True),
            ("doctor", "run doctor", False),
            ("frontend", "export this figma frame as png", True),
            ("frontend", "view this figma frame", True),
            ("frontend", "take screenshots of these screens from the figma frame", True),
            ("frontend", "open the admin interface of this figma frame", True),
            ("frontend", "turn this figma frame into a react component", False),
            ("frontend", "build the settings screen from this figma frame", False),
        )
        for skill, message, withdrawn in cases:
            with self.subTest(message=message):
                self.assertIs(withdrawn, everyday_sense_phrase_unanchored(skill, normalized_phrase(message)))

    def test_the_phrase_alone_keeps_the_skill(self) -> None:
        for skill, (phrases, _anchors) in EVERYDAY_SENSE_PHRASES.items():
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    self.assertFalse(everyday_sense_phrase_unanchored(skill, normalized_phrase(f"please {phrase}")))

    def test_a_skill_outside_the_table_is_never_withdrawn(self) -> None:
        self.assertFalse(everyday_sense_phrase_unanchored("code-review", "what is a weekly status review"))


if __name__ == "__main__":
    unittest.main()
