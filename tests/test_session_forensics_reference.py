"""`agent-debug`'s session forensics rules (issue #2049).

`references/session-forensics.md` governs reading a past agent session as
evidence: the question is written before the first read, every store and file
is opened read-only, every read is length-bounded, software-written rows are
not the user's words, and a figure the report never derived from the
session stays out. `tests/test_skill_reference_mechanisms.py` holds the
pointer and the mechanism tokens; this file pins each rule by the sentence
that carries it, so deleting one rule fails here by name even while the
other tokens survive.

The reference names Hermes' `state.db`, so it is Hermes-only: the portable
body keeps its own quality bar without the pointer, and the portable pack
does not carry the file. Content is read from the producers, never from the
generated `skills/` tree.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import omh_skill_display_name
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import agent_skill_reference_templates, agent_skill_templates
from test_skill_reference_mechanisms import _bodies_by_name

SKILL = "agent-debug"
REFERENCE_PATH = "references/session-forensics.md"


def _reference() -> str:
    for template in builtin_skill_reference_templates():
        if (template.skill_name, template.relative_path) == (SKILL, REFERENCE_PATH):
            return template.content
    raise AssertionError(f"{SKILL} lost {REFERENCE_PATH} from builtin_skill_reference_templates()")


class SessionForensicsRuleTests(unittest.TestCase):
    def test_sources_are_opened_read_only(self) -> None:
        content = _reference()
        self.assertIn("sqlite3 'file:<hermes_home>/state.db?mode=ro'", content)
        self.assertIn("is opened for reading only. Never edit, rename, move, truncate, or remove one", content)

    def test_every_read_is_length_bounded(self) -> None:
        content = _reference()
        self.assertIn("select `length(content)` first, then the text through `substr(content, 1, <cap>)`", content)
        self.assertIn("read through a per-line byte cap", content)
        self.assertIn("A row over the cap is reported as unread", content)

    def test_software_written_rows_are_not_the_users_words(self) -> None:
        content = _reference()
        self.assertIn("Only text the human typed is the user's words.", content)
        for speaker in ("hook output and injected system reminders", "`_compressed_summary`", "tool results"):
            with self.subTest(speaker=speaker):
                self.assertIn(speaker, content)

    def test_a_delegated_childs_user_turns_are_the_parent_agent(self) -> None:
        self.assertIn("every user-role turn is the parent agent's brief", _reference())

    def test_intake_is_written_before_the_first_read(self) -> None:
        content = _reference()
        intake = content.index("## 1. Intake before any query")
        self.assertLess(intake, content.index("## 2. Read-only, every source"))
        self.assertIn("A question you filled in on the user's behalf does not count as their answer", content)

    def test_only_computed_numbers_are_reported(self) -> None:
        content = _reference()
        self.assertIn("the report shows that query or command beside the figure", content)
        self.assertIn('is written as "not computed" instead', content)
        self.assertIn("Count tool calls by distinct `tool_call_id`", content)

    def test_sharing_waits_for_the_users_approval(self) -> None:
        content = _reference()
        self.assertIn("written only after the user has reviewed that package", content)
        self.assertIn("sent only after they approve that exact text", content)


class SessionForensicsProjectionTests(unittest.TestCase):
    def test_hermes_body_names_the_reference_on_one_line_in_the_quality_bar(self) -> None:
        body = _bodies_by_name()[SKILL]
        naming = [line for line in body.splitlines() if REFERENCE_PATH in line]
        self.assertEqual(len(naming), 1, f"{SKILL} body names {REFERENCE_PATH} on {len(naming)} lines")
        quality_bar = body[body.index("Quality bar:"):body.index("Handoff policy:")]
        self.assertIn(naming[0], quality_bar)

    def test_portable_projection_neither_names_nor_ships_the_reference(self) -> None:
        display = omh_skill_display_name(SKILL)
        bodies = {template.name: template.content for template in agent_skill_templates()}
        self.assertNotIn(REFERENCE_PATH, bodies[display])
        shipped = {(template.skill_name, template.relative_path) for template in agent_skill_reference_templates()}
        self.assertNotIn((display, REFERENCE_PATH), shipped)


if __name__ == "__main__":
    unittest.main()
