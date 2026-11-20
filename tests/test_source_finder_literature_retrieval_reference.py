"""`source-finder`'s literature retrieval reference is reachable and source-finder only.

The pointer sits in `quality_bar` at index 4 or later so the capability rows
(the first four items) do not move. These tests check what ships: the Hermes
body, the portable body, and the portable reference pack.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions, omh_skill_display_name
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import (
    agent_skill_reference_templates,
    agent_skill_templates,
    workflow_skill_from_definition,
)

POINTER = "references/literature-retrieval.md"

MECHANISM_TOKENS = (
    "OpenAlex",
    "PubMed",
    "bioRxiv",
    "S4306402567",
    "Difficulty",
    "search-method.md",
    "link_observed",
    "never add a paper id from memory",
    "research_progress/v1",
)


def _reference() -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == "source-finder" and template.relative_path == POINTER
    )


def _source_finder_definition():
    return next(d for d in builtin_definitions() if d.name == "source-finder")


class SourceFinderLiteratureRetrievalProjectionTests(unittest.TestCase):
    def test_hermes_body_names_the_reference_on_one_line(self) -> None:
        body = workflow_skill_from_definition(
            _source_finder_definition(), "source-finder"
        ).content
        lines = [line for line in body.splitlines() if POINTER in line]
        self.assertEqual(len(lines), 1, f"source-finder body names {POINTER} on {len(lines)} lines")

    def test_portable_projection_ships_the_reference_and_names_it(self) -> None:
        name = omh_skill_display_name("source-finder")
        shipped = {(t.skill_name, t.relative_path) for t in agent_skill_reference_templates()}
        self.assertIn((name, POINTER), shipped, "portable pack dropped the literature reference")
        bodies = {t.name: t.content for t in agent_skill_templates()}
        naming = [n for n, content in bodies.items() if POINTER in content]
        self.assertEqual(naming, [name], f"portable bodies naming {POINTER}")
        lines = [line for line in bodies[name].splitlines() if POINTER in line]
        self.assertEqual(len(lines), 1, "the portable pointer is one line")

    def test_reference_is_produced_only_for_source_finder(self) -> None:
        owners = {
            t.skill_name
            for t in builtin_skill_reference_templates()
            if t.relative_path == POINTER
        }
        self.assertEqual(owners, {"source-finder"})

    def test_pointer_stays_out_of_the_capability_rows(self) -> None:
        quality_bar = _source_finder_definition().quality_bar
        self.assertFalse(any(POINTER in item for item in quality_bar[:4]))
        self.assertTrue(any(POINTER in item for item in quality_bar[4:]))


class SourceFinderLiteratureRetrievalMechanismTests(unittest.TestCase):
    def test_reference_carries_the_mechanism_tokens(self) -> None:
        content = _reference().lower()
        for token in MECHANISM_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token.lower(), content)


if __name__ == "__main__":
    unittest.main()
