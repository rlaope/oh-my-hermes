"""The phone-screen density gate and the clauses that point at it.

The gate is a reference body plus one clause in the screenshot loop and one
quality-bar line in `visual-qa`. These tests pin the mechanisms a reviewer
checks (viewport, first-data position, touch emulation, `transform`,
horizontal scroll, before/after pair, three-part report) and that both
neighbours carry the clause. Packaging of the new file is not asserted here.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.frontend_mobile_density_reference import mobile_density_gate_reference
from omh.skills.render import _screenshot_loop_reference


def _unwrapped(content: str) -> str:
    return " ".join(content.split())


def _visual_qa_quality_bar() -> tuple[str, ...]:
    for definition in builtin_definitions():
        if definition.name == "visual-qa":
            return tuple(definition.quality_bar)
    raise AssertionError("missing definition visual-qa")


class GateBodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _unwrapped(mobile_density_gate_reference())

    def test_shape(self) -> None:
        raw = mobile_density_gate_reference()
        self.assertTrue(raw.startswith("# Mobile Density Gate\n"))
        self.assertIn("## Boundary", raw)
        self.assertNotIn("## Attribution", raw)
        self.assertTrue(90 <= len(raw.splitlines()) <= 135)

    def test_two_axes_are_judged_separately(self) -> None:
        self.assertIn("Hygiene", self.body)
        self.assertIn("Density", self.body)
        self.assertIn("Passing hygiene alone is not a pass", self.body)

    def test_first_screen_is_measured_as_a_position(self) -> None:
        self.assertIn("390x844", self.body)
        self.assertIn("first data row starts", self.body)
        self.assertIn("first action control", self.body)
        self.assertIn("300 px", self.body)
        self.assertIn("agreed default a project may change", self.body)

    def test_flat_before_hidden(self) -> None:
        self.assertIn("Lay controls flat before hiding them", self.body)
        self.assertIn("two taps", self.body)

    def test_hiding_bar_uses_transform_and_reduced_motion(self) -> None:
        self.assertIn("`transform`", self.body)
        self.assertIn("`display`", self.body)
        self.assertIn("`prefers-reduced-motion`", self.body)

    def test_horizontal_scroll_is_a_failure_with_conversions(self) -> None:
        self.assertIn("Horizontal scroll is a failure", self.body)
        self.assertIn("stacked rows", self.body)
        self.assertIn("tabs", self.body)

    def test_looking_needs_touch_emulation(self) -> None:
        self.assertIn("touch and a mobile user agent", self.body)
        self.assertIn("`(hover: none)`", self.body)
        self.assertIn("`(pointer: coarse)`", self.body)
        self.assertIn("first viewport, not the full page", self.body)
        self.assertIn("Capture after scrolling", self.body)

    def test_hygiene_points_at_existing_owners(self) -> None:
        self.assertIn("design-system-contract.md", self.body)
        self.assertIn("omh-accessibility-audit", self.body)
        self.assertIn("16 px", self.body)
        self.assertIn("`dvh`", self.body)
        self.assertIn("safe-area", self.body)
        self.assertIn("hit area, not its visible size", self.body)

    def test_report_is_three_parts_with_numbers(self) -> None:
        self.assertIn("Three parts", self.body)
        for part in ("**Changed**", "**Concerns**", "**Not checked**"):
            self.assertIn(part, self.body)
        self.assertIn("514 -> 311px", self.body)
        self.assertIn("An item without a number is counted as not done", self.body)

    def test_open_limits_are_stated(self) -> None:
        self.assertIn("Open limits", self.body)
        self.assertIn("watching a person use the surface", self.body)


class NeighbourClauseTests(unittest.TestCase):
    def test_screenshot_loop_carries_the_clause(self) -> None:
        body = _unwrapped(_screenshot_loop_reference())
        self.assertIn("375 capture with touch and mobile-user-agent emulation", body)
        self.assertIn("width-only capture is named as such", body)
        self.assertIn("references/mobile-density-gate.md", body)

    def test_visual_qa_quality_bar_carries_the_line(self) -> None:
        bar = _visual_qa_quality_bar()
        matches = [i for i, line in enumerate(bar) if "width-only" in line and "mobile user-agent" in line]
        self.assertEqual(len(matches), 1)
        self.assertGreaterEqual(matches[0], 4)
        line = bar[matches[0]]
        self.assertIn("render_capture_manifest/v1", line)
        self.assertIn("`(hover: none)`", line)


if __name__ == "__main__":
    unittest.main()
