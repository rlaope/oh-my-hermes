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
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import (
    agent_skill_reference_templates,
    agent_skill_templates,
    loop_skill,
)

POINTER = "references/loop-design-review.md"

# The pre-launch check's five rows, by the names the table gives them.
FAILURE_CHECK_ITEMS = (
    "| Undecidable finish |",
    "| Self-grading |",
    "| Unfenced check |",
    "| Questions left for mid-run |",
    "| Stale working context |",
)


def _reference() -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == "loop" and template.relative_path == POINTER
    )


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


class LoopDesignReviewFenceCommandTests(unittest.TestCase):
    """The fence check is only as good as the exact command it names.

    `git diff --name-only <start>..HEAD` passed review once and missed two
    ways around the fence: a rename reports only the new path, so moving a
    fenced test out of the way hid it, and a commit range never sees staged,
    unstaged, or untracked edits. A later review found that ignored files and
    fence entries untracked at the start reach neither listing. These pins
    hold the command forms and the direct checks that close all of those, so
    a reword back to a weaker form fails here.
    """

    def test_the_diff_sees_renames_as_a_deletion(self) -> None:
        self.assertIn(
            "`git -c core.quotePath=false diff --no-renames --name-status <start-sha>`", _reference()
        )

    def test_the_diff_covers_the_working_tree_and_untracked_files(self) -> None:
        content = _reference()
        self.assertIn("`git -c core.quotePath=false ls-files --others --exclude-standard`", content)
        self.assertIn("staged and unstaged edits included", content)
        self.assertNotIn("..HEAD", content, "a commit range misses uncommitted edits")

    def test_entries_the_listings_cannot_see_are_checked_directly(self) -> None:
        """Ignored files never reach either listing, and a file untracked at
        the start is never compared by them, so both need their own step."""
        content = _reference()
        self.assertIn("run `test -e <path>`", content)
        self.assertIn("gitignored or not", content)
        self.assertIn("`git ls-files --error-unmatch <path>` reports as untracked", content)
        self.assertIn("the entry's sha256", content)
        self.assertIn("`git -C <sub> status --porcelain`", content)

    def test_a_rebase_keeps_the_approved_anchor(self) -> None:
        self.assertIn(
            "the rebased copy of the most recent approved re-anchor commit, or the new base when there is none",
            _reference(),
        )

    def test_the_start_is_a_recorded_sha_not_a_branch(self) -> None:
        content = _reference()
        self.assertIn("by its full SHA, never by a branch name", content)
        self.assertIn("record that commit's SHA as the new start", content)

    def test_all_five_failure_check_items_are_rows(self) -> None:
        content = _reference()
        for item in FAILURE_CHECK_ITEMS:
            with self.subTest(item=item):
                self.assertIn(item, content)


if __name__ == "__main__":
    unittest.main()
