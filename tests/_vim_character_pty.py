"""Character-VISUAL edits and rollback through the shared real OS PTY runner.

Only literal input/result cases are replaced. Gateway replay, production input
and rendering, VT overflow checks, caret marker submission and process cleanup
all remain those of _vim_operator_pty; no fake terminal or production hooks.
"""
from unittest import mock

import _vim_operator_pty as operator_pty


# The shared runner starts at second hard line, column zero. Each tuple carries
# literal post-command text and insertion-caret offset, not a composer resolver.
TEXT = "FIRST\nSECOND\nTAIL"
CASES = (
    ("vld", "FIRST\nCOND\nTAIL", 6),
    ("vldu", "FIRST\nSECOND\nTAIL", 7),
    ("v2ldu", "FIRST\nSECOND\nTAIL", 8),
    ("vlv", "FIRST\nSECOND\nTAIL", 7),
)


def assert_character_visual_pty(testcase):
    """Run delete, exact undo rollback and cancel at 20x8 and 100x30."""
    with mock.patch.multiple(operator_pty, TEXT=TEXT, CASES=CASES):
        operator_pty.assert_operator_pty(testcase)
