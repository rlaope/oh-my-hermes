"""`loop`'s design review is reachable on both projections (issue #2049).

`tests/test_skill_reference_mechanisms.py` checks the pointer against the
catalog-rendered body. These tests check what actually ships: the Hermes body
`loop_skill()` produces after its sections are spliced in, and the portable
body built from `portable_overrides`, which carries its own quality bar. A
pointer added to one quality bar and not the other would pass the mechanism
test and leave the portable pack with a reference nothing names, or a name
with no file behind it.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import omh_skill_display_name
from omh.skills.render import (
    agent_skill_reference_templates,
    agent_skill_templates,
    loop_skill,
)

POINTER = "references/loop-design-review.md"


class LoopDesignReviewProjectionTests(unittest.TestCase):
    def test_shipped_hermes_body_names_the_reference_on_one_line(self) -> None:
        lines = [line for line in loop_skill().content.splitlines() if POINTER in line]
        self.assertEqual(len(lines), 1, f"loop body names {POINTER} on {len(lines)} lines")

    def test_portable_projection_ships_the_reference_and_names_it(self) -> None:
        shipped = {
            (template.skill_name, template.relative_path)
            for template in agent_skill_reference_templates()
        }
        self.assertIn((omh_skill_display_name("loop"), POINTER), shipped, "portable pack dropped the loop design review")
        bodies = {template.name: template.content for template in agent_skill_templates()}
        portable_loop = [name for name, content in bodies.items() if POINTER in content]
        self.assertEqual(portable_loop, [omh_skill_display_name("loop")], f"portable bodies naming {POINTER}")
        naming = [line for line in bodies[portable_loop[0]].splitlines() if POINTER in line]
        self.assertEqual(len(naming), 1, "the portable pointer is one line")


if __name__ == "__main__":
    unittest.main()
