"""Editorial layout reference and the screen-copy review in taste foundations.

The layout reference holds seven named axes, a rule to differ from the last
page, static-before-motion and image rules. The taste foundations gain a review
of the text a page says about itself. These tests pin those mechanisms from the
producers, and check that the new text states no frequencies.
"""

from __future__ import annotations

import re
import unittest

from omh.skills.frontend_editorial_layout_reference import editorial_layout_reference
from omh.skills.render import _taste_foundations_reference


def _unwrapped(content: str) -> str:
    return " ".join(content.split())


def _screen_copy_section() -> str:
    body = _taste_foundations_reference()
    start = body.index("## Screen copy")
    end = body.index("## Boundary", start)
    return _unwrapped(body[start:end])


class EditorialLayoutReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = editorial_layout_reference()
        self.body = _unwrapped(self.raw)

    def test_shape(self) -> None:
        self.assertTrue(self.raw.startswith("# Editorial Layout"))
        self.assertIn("## Boundary", self.raw)
        self.assertTrue(self.raw.rstrip().endswith("from a capture."))
        self.assertLessEqual(len(self.raw.splitlines()), 140)

    def test_seven_axes_are_named(self) -> None:
        for axis in (
            "Skeleton / grid",
            "First screen",
            "Section boundary",
            "Image placement",
            "Signature moment",
            "Density",
            "Screen corners and navigation",
        ):
            self.assertIn(f"**{axis}**", self.body)
        self.assertIn("one line of reason", self.body)
        self.assertIn("not a closed list", self.body)
        # The corner axis is about what sits at the screen edges, never radius:
        # radius belongs to the contract's Shapes section.
        self.assertIn("Corner radius is not this axis", self.body)

    def test_box_restriction_follows_the_chosen_direction(self) -> None:
        self.assertIn("Where the chosen direction does not make the box its own language", self.body)
        self.assertIn("a direction that boxes everything on purpose", self.body)
        self.assertIn("hierarchy comes from size, weight and position", self.body)
        self.assertNotIn("bordered box only when", self.body)

    def test_differ_from_previous_output(self) -> None:
        self.assertIn("change at least three of the seven axes", self.body)
        self.assertIn('"like last time"', self.body)
        self.assertIn("date, project, and the seven axis values", self.body)
        self.assertIn("leaves the path to the project's own conventions", self.body)

    def test_less_familiar_values_rule_has_no_numbers(self) -> None:
        self.assertIn("pick at least two axes from the less familiar candidates", self.body)

    def test_frame_shared_interior_varied(self) -> None:
        self.assertIn("pages share the frame", self.body)
        self.assertIn("consecutive sections of the same kind change composition", self.body)

    def test_static_before_motion_and_one_mode(self) -> None:
        self.assertIn("no motion, hover effect, scroll effect, or shader", self.body)
        self.assertIn("Add motion only after the still layout holds", self.body)
        self.assertIn("A light page stays light", self.body)

    def test_image_rules(self) -> None:
        self.assertIn("Use what exists first", self.body)
        self.assertIn("Never bake text into the image file", self.body)
        self.assertIn("text area left empty", self.body)
        self.assertIn("aspect ratio of the slot", self.body)
        self.assertIn("dark variant an edit of the approved light image", self.body)
        self.assertIn("Open each image and look at it before placing it", self.body)

    def test_phone_fold_points_at_density_gate(self) -> None:
        self.assertIn("references/mobile-density-gate.md", self.body)
        self.assertIn("returns to the flow", self.body)

    def test_stylesheet_record(self) -> None:
        self.assertIn("top of the page's stylesheet", self.body)

    def test_no_frequencies(self) -> None:
        for text in (self.raw, _screen_copy_section()):
            self.assertIsNone(re.search(r"%\s*\d|\d\s*%", text))
            self.assertIsNone(re.search(r"\b\d+\s+(?:in|out of)\s+\d+\b", text))


class ScreenCopyReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.section = _screen_copy_section()

    def test_review_prompts(self) -> None:
        for phrase in (
            "A hero sentence that introduces the product",
            "A one-line description under every section title",
            'A contrast headline of the "not X but Y" shape',
            "A paragraph narrating how a decision was reached",
        ):
            self.assertIn(phrase, self.section)
        self.assertIn("a stated reason keeps each one", self.section)

    def test_reject_on_sight(self) -> None:
        self.assertIn("01 / 02 / 03 numbering on content that has no order", self.section)
        # The button-label rule is owned by the Interface copy section, not repeated here.
        self.assertNotIn("A button label that does not say what happens", self.section)
        self.assertIn("An outcome number with no source", self.section)

    def test_number_test(self) -> None:
        self.assertIn('"what is this number trying to prove?"', self.section)
        self.assertIn("measured on the same basis stays", self.section)
        self.assertIn("configuration or limit value", self.section)
        self.assertIn("A boast about improvement goes", self.section)

    def test_no_invented_content_and_read_every_string(self) -> None:
        self.assertIn("do not invent sentences, roles, or experience", self.section)
        self.assertIn("ask what goes there", self.section)
        self.assertIn("read every string on the captured screen", self.section)

    def test_points_at_existing_prompt_instead_of_repeating(self) -> None:
        self.assertIn("eyebrow, title, and description prompt above", self.section)


if __name__ == "__main__":
    unittest.main()
