"""How much a lane actually did, distinct from how long it has been running.

Elapsed time alone reports a lane at twelve minutes and two tool calls
identically to one at twelve minutes and sixty, and those are different
situations for a reader deciding whether to intervene. The count was already
observed and had no field to travel in.

The rule that matters here is that zero and unobserved are different answers.
Zero is real and renderable — an executor that made no tool calls made none —
so an unobserved count must never render as `0`, because a reader would read it
as the executor having done nothing.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding.status_board import (  # noqa: E402
    UNKNOWN,
    render_status_board_text,
    status_board_messenger_body,
    tool_count_text_for,
)


def _payload(**unit_fields: object) -> dict[str, object]:
    unit = {
        "label": "routing",
        "runtime": "codex",
        "model_label": "gpt-6-astra high",
        "status": "running",
        "elapsed_text": "12m",
        "tokens_text": "18420",
        "session_ref": "s1",
    }
    unit.update(unit_fields)
    return {
        "claim_boundary": "b",
        "running_count": 1,
        "unit_count": 1,
        "observed_at": "04:00Z",
        "units": [unit],
    }


class ZeroIsNotUnknownTests(unittest.TestCase):
    def test_zero_renders_as_zero(self) -> None:
        self.assertEqual(tool_count_text_for(0), "0")

    def test_an_unobserved_count_renders_unknown(self) -> None:
        for absent in (None, "", UNKNOWN, "12"):
            with self.subTest(value=absent):
                self.assertEqual(tool_count_text_for(absent), UNKNOWN)

    def test_a_bool_is_not_a_count(self) -> None:
        """`True` is an `int` in Python, and `1 tool call` would be a fiction."""
        self.assertEqual(tool_count_text_for(True), UNKNOWN)
        self.assertEqual(tool_count_text_for(False), UNKNOWN)

    def test_a_negative_count_is_refused(self) -> None:
        self.assertEqual(tool_count_text_for(-1), UNKNOWN)


class BoardRenderingTests(unittest.TestCase):
    def test_the_aligned_board_carries_a_tools_column(self) -> None:
        text = render_status_board_text(_payload(tool_count_text="21"))
        self.assertIn("TOOLS", text)
        self.assertIn("21", text)

    def test_the_bullet_profile_names_the_unit(self) -> None:
        body = status_board_messenger_body(_payload(tool_count_text="21"))
        self.assertIn("21 tool calls", body)

    def test_an_unobserved_count_says_so_on_both_profiles(self) -> None:
        self.assertIn(UNKNOWN, render_status_board_text(_payload()))
        self.assertIn("tools unknown", status_board_messenger_body(_payload()))

    def test_zero_tool_calls_is_reported_not_hidden(self) -> None:
        """A lane that has done nothing is exactly what a reader needs to see."""
        body = status_board_messenger_body(_payload(tool_count_text="0"))
        self.assertIn("0 tool calls", body)
        self.assertNotIn("tools unknown", body)


if __name__ == "__main__":
    unittest.main()
