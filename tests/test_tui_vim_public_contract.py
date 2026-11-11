"""The detailed installed Vim guide must not contradict its supported key table.

Read the prose a person reaches below the table, rather than satisfying the
contract from the table's feature names alone. Runtime behavior is exercised
by the existing dot, character/line visual and reselect acceptance suites.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest


INSTALLATION = Path(__file__).resolve().parents[1] / "docs" / "INSTALLATION.md"


class PublicVimContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        guide = INSTALLATION.read_text(encoding="utf-8")
        start = guide.index("Vim mode: with Hermes'")
        end = guide.index("\nShift+Tab cycles three input modes", start)
        cls.prose = " ".join(guide[start:end].replace("`", "").split())

    def test_entire_mode_section_rejects_retired_feature_denials(self) -> None:
        # Scan the entire prose, including the final differences/limitations
        # paragraph: a correct feature paragraph cannot excuse a later denial.
        contradictions = (
            r"i a I A o O\s+(?:and\s+0 \^ \$\s+)?take\s+(?:none|no count)",
            r"(?:a\s+)?count does not repeat an insert",
            r"there is no\b[^.;]*\bvisual mode\b",
            r"there is no\b[^.;]*\. repeat\b",
            r"linewise(?:/block)? visual and reselect are not supported",
            r"reselect (?:is|are) (?:not supported|unsupported)",
            r"not supported by this slice",
            r"text object but iw and aw",
        )
        for pattern in contradictions:
            with self.subTest(contradiction=pattern):
                self.assertNotRegex(self.prose, re.compile(pattern, re.IGNORECASE))

    def test_all_six_counted_insert_examples_are_in_detailed_prose(self) -> None:
        for command, result in (
            ("2iZ<Esc>", "ZZabc"),
            ("2aZ<Esc>", "aZZbc"),
            ("2IZ<Esc>", "ZZabc"),
            ("2AZ<Esc>", "abcZZ"),
            ("2oZ<Esc>", r"abc\nZ\nZ"),
            ("2OZ<Esc>", r"Z\nZ\nabc"),
        ):
            with self.subTest(command=command):
                self.assertIn(f"{command} produces {result}", self.prose)
        self.assertIn("repeat the completed insertion recipe on Escape", self.prose)
        self.assertIn("0 ^ $ ignore counts", self.prose)

    def test_dot_prose_explains_count_override_payload_and_transaction(self) -> None:
        for contract in (
            ". repeats the last completed local change",
            "[n]. overrides its count rather than multiplying it",
            "put repeats its captured payload even after another yank",
            "Insert/change sessions complete on Escape and undo as one transaction",
            "local to this composer, not a macro",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.prose)

    def test_dot_prose_explains_preservation_reset_and_rejection(self) -> None:
        for contract in (
            "External paste/image edits and oversized insertion sessions do not replace the saved change",
            "motion, yank and undo/redo preserve it",
            "Submit, clear, history/draft replacement, masking and Vim toggles reset it",
            "An over-budget repeat is an atomic no-op",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.prose)

    def test_line_visual_prose_covers_conversion_register_and_repeat(self) -> None:
        for contract in (
            "V enters VISUAL LINE over whole logical hard lines",
            "v/V converts modes retaining endpoint columns",
            "V again cancels line selection",
            "counts before v/V or d/c/y do not scale the selection",
            "linewise register without a terminal separator",
            "selected hard-line count forward",
            "[n]. scales that count",
            "empty or unterminated line shows a selected end cell",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.prose)

    def test_gv_prose_explains_exact_generation_and_invalidation(self) -> None:
        for contract in (
            "NORMAL-only gv restores the last completed selection",
            "exact anchor/head, type and direction",
            "9999gv",
            "Escape, toggle-out and yank save it",
            "Text or paste/image metadata generation changes",
            "undo/redo, submit, clear, history/draft replacement, masking and Vim toggles invalidate it",
            "even when text becomes identical again",
            "failed/no-op edits do not",
            "Resize and navigation preserve it",
            "absent/stale gv is a consumed no-op",
            "gv inside VISUAL is unsupported",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.prose)

    def test_limitations_keep_supported_visual_repeat_and_object_inventory(self) -> None:
        differences = self.prose.split("What differs from Hermes' Vi mode", 1)[1]
        for supported in ("character and linewise visual", ". repeat", "counted inserts",
                          "quote and bracket text objects"):
            with self.subTest(supported=supported):
                self.assertIn(supported, differences)
        self.assertIn("no REPLACE mode (R), block visual, named register", differences)
        # R5 reconciles public claims, not the separately preserved iw/aw policy.
        self.assertIn("iw aw take words between blanks on one line", differences)


if __name__ == "__main__":
    unittest.main()
