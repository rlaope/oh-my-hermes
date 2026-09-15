"""Which of the three shapes a table takes, and why each limit exists.

A markdown table is dropped by Slack and Telegram, so a limited profile has to
turn it into something else. Bullets always work and always lose the columns; a
fenced block keeps the columns and only fits while it is narrow. The policy
picks per table, and these pin every boundary it decides on -- including the
one that is easy to get wrong, which is that a column's width is measured in
display cells rather than in characters.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.system.display_width import display_width, pad_to_width  # noqa: E402
from omh.wrapper.contract import messenger_rendering_contract  # noqa: E402

_ALIGNED = "markdown_table_to_aligned_block"
_BULLETS = "markdown_table_to_bullets"


def _render(body: str, *, source: str = "slack", profile: str = "limited_markdown") -> dict[str, object]:
    return messenger_rendering_contract(
        visible_prefix="[omh]",
        first_line="x",
        body=body,
        claim_boundary="b",
        render_profile=profile,
        source=source,
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


class ThreeWaySplitTests(unittest.TestCase):
    def test_a_narrow_list_shaped_table_keeps_its_columns(self) -> None:
        rendering = _render(_table(["PR", "Owner", "State"], [["#1", "claude", "review"], ["#2", "gpt", "waiting"]]))
        self.assertIn(_ALIGNED, rendering["transforms_applied"])
        self.assertIn("```", str(rendering["body_text"]))
        self.assertIn("#1  claude  review", str(rendering["body_text"]))

    def test_a_four_column_table_becomes_bullets(self) -> None:
        """Four aligned columns no longer fit a phone, and a wrapped monospace
        row is worse than a bullet: it stops lining up with the row above it."""
        rendering = _render(
            _table(["A", "B", "C", "D"], [["1", "2", "3", "4"], ["5", "6", "7", "8"]])
        )
        self.assertIn(_BULLETS, rendering["transforms_applied"])
        self.assertNotIn(_ALIGNED, rendering["transforms_applied"])

    def test_a_wide_table_becomes_bullets_even_with_two_columns(self) -> None:
        """Width is measured on the rendered block, not guessed from the column
        count: two long columns overflow where three short ones fit."""
        long_cell = "a sentence long enough that the row cannot fit a phone screen"
        rendering = _render(_table(["Issue", "Detail"], [["#1", long_cell], ["#2", long_cell]]))
        self.assertIn(_BULLETS, rendering["transforms_applied"])

    def test_a_single_row_table_becomes_bullets(self) -> None:
        """One data row has nothing to align with, and a fence around it costs
        more vertical space than the columns save."""
        rendering = _render(_table(["Issue", "State"], [["#1", "blocked"]]))
        self.assertIn(_BULLETS, rendering["transforms_applied"])

    def test_a_rich_profile_keeps_the_markdown_table(self) -> None:
        body = _table(["PR", "Owner", "State"], [["#1", "claude", "review"], ["#2", "gpt", "waiting"]])
        rendering = _render(body, source="mattermost", profile="rich_markdown")
        self.assertEqual(rendering["transforms_applied"], [])
        self.assertIn("| PR | Owner | State |", str(rendering["body_text"]))
        self.assertEqual(rendering["table_policy"], "preserve_markdown_tables_when_supported")

    def test_the_limited_policy_names_both_outcomes(self) -> None:
        self.assertEqual(
            _render(_table(["A", "B"], [["1", "2"], ["3", "4"]]))["table_policy"],
            "narrow_tables_to_aligned_block_else_bullets",
        )


class WidthTests(unittest.TestCase):
    def test_a_korean_table_aligns_on_display_cells(self) -> None:
        """`len("이슈")` is 2 while the string occupies four columns.

        Padding by length is how a table comes out ragged inside the fence that
        exists to keep it straight, so every rendered row must be equally wide.
        """
        rendering = _render(_table(["이슈", "상태"], [["#1609", "리뷰 대기"], ["#2", "대기"]]))
        self.assertIn(_ALIGNED, rendering["transforms_applied"])
        rows = [line for line in str(rendering["body_text"]).splitlines() if line and not line.startswith("```")]
        self.assertEqual(len(rows), 3)
        # Where the SECOND column starts, in display cells. Comparing the first
        # column's own width would compare the cell contents, which of course
        # differ; what has to match is the offset the padding puts them at.
        offsets = []
        for row in rows:
            first, rest = row.split("  ", 1)
            offsets.append(display_width(first) + 2 + len(rest) - len(rest.lstrip(" ")))
        self.assertEqual(len(set(offsets)), 1, f"ragged second column at {offsets} in {rows}")

    def test_width_counts_wide_characters_as_two(self) -> None:
        self.assertEqual(display_width("이슈"), 4)
        self.assertEqual(display_width("#1612"), 5)
        self.assertEqual(display_width(""), 0)

    def test_width_ignores_combining_marks_and_ansi(self) -> None:
        self.assertEqual(display_width("é"), 1)
        self.assertEqual(display_width("\x1b[31mred\x1b[0m"), 3)

    def test_padding_fills_to_display_width(self) -> None:
        self.assertEqual(display_width(pad_to_width("이슈", 8)), 8)
        self.assertEqual(display_width(pad_to_width("ab", 8)), 8)

    def test_padding_never_truncates(self) -> None:
        """Dropping content to keep a column straight trades a cosmetic problem
        for a correctness one."""
        self.assertEqual(pad_to_width("a long cell", 3), "a long cell")


class PassThroughTests(unittest.TestCase):
    def test_a_table_inside_a_fence_is_untouched(self) -> None:
        body = "```\n| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n```"
        rendering = _render(body)
        # No table transform ran; the fence with no language tag needs no strip
        # either, so the list is empty rather than carrying one entry.
        self.assertEqual(rendering["transforms_applied"], [])
        self.assertIn("| A | B |", str(rendering["body_text"]))

    def test_a_malformed_table_is_left_alone(self) -> None:
        body = "| A | B |\n| 1 | 2 |"
        rendering = _render(body)
        self.assertNotIn(_ALIGNED, rendering["transforms_applied"])
        self.assertNotIn(_BULLETS, rendering["transforms_applied"])


if __name__ == "__main__":
    unittest.main()
