"""Contract tests for the business-operations skill audit (PR for the `business-ops` lane)."""

from __future__ import annotations

import datetime
import re
import unittest

from _local_package import load_local_package

load_local_package()

from omh.skills import render
from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates


def _reference(skill: str, path: str) -> str:
    return next(t.content for t in builtin_skill_reference_templates() if t.skill_name == skill and t.relative_path == path)


def _valid_date(six: str) -> bool:
    year, month, day = int(six[:2]), int(six[2:4]), int(six[4:6])
    for century in (1900, 2000):
        try:
            datetime.date(century + year, month, day)
            return True
        except ValueError:
            continue
    return False


class ScanPatternTests(unittest.TestCase):
    RRN = re.compile(render.KR_RRN_PATTERN)
    RRN_MASKED = re.compile(render.KR_RRN_MASKED_PATTERN)
    SSN = re.compile(render.US_SSN_PATTERN)
    MOBILE = re.compile(render.KR_MOBILE_PATTERN)

    def test_resident_numbers_are_found_whatever_the_separator_or_check_digit(self) -> None:
        for sample in ("900101-1123454", "900101 1123454", "900101–1123454", "9001011123454", "900101-1123450"):
            with self.subTest(sample=sample):
                match = self.RRN.search(sample)
                self.assertIsNotNone(match)
                self.assertTrue(_valid_date(match.group(0)[:6]))
        self.assertIsNotNone(self.RRN_MASKED.search("900101-1******"))

    def test_other_digit_strings_are_not_resident_numbers(self) -> None:
        self.assertIsNone(self.RRN.search("1731000000000"))
        self.assertIsNone(self.RRN.search("12900101-1123454"))
        self.assertIsNone(self.RRN.search("900101-11234545"))

    def test_mobile_numbers_in_common_forms_and_anchored(self) -> None:
        for sample in ("010-1234-5678", "01012345678", "+82 10-1234-5678", "010 1234 5678", "010.1234.5678", "+8210-1234-5678"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(self.MOBILE.search(sample))
        self.assertIsNone(self.MOBILE.search("20101234567"))

    def test_ssn_excludes_the_unissued_areas(self) -> None:
        self.assertIsNotNone(self.SSN.search("123-45-6789"))
        for sample in ("000-12-3456", "666-12-3456", "912-12-3456", "123-00-6789", "123-45-0000"):
            with self.subTest(sample=sample):
                self.assertIsNone(self.SSN.search(sample))

    def test_the_reference_states_the_patterns_and_never_filters_on_the_check_digit(self) -> None:
        text = _reference("data-share-review", "references/data-share-method.md")
        for pattern in (render.KR_RRN_PATTERN, render.KR_RRN_MASKED_PATTERN, render.US_SSN_PATTERN, render.KR_MOBILE_PATTERN):
            self.assertIn(pattern, text)
        self.assertIn("never the check digit as a filter", text)
        self.assertIn("`data_state`", text)


class WordingTests(unittest.TestCase):
    def test_deviation_rule_uses_the_upper_limit_and_does_not_excuse_an_explained_deviation(self) -> None:
        text = _reference("internal-audit", "references/control-audit-method.md")
        self.assertIn("any deviation, explained or not", text)
        self.assertIn("upper deviation limit", text)
        self.assertNotIn("one unexplained deviation", text)

    def test_morning_brief_never_calls_a_send_capable_credential_draft_only(self) -> None:
        morning = next(d for d in builtin_definitions() if d.name == "morning-brief")
        rules = " ".join(morning.safety_rules)
        self.assertIn("never enable Send permission", rules)
        self.assertIn("mcp_servers.<name>.tools.include", rules)
        self.assertIn("credential can send", rules)
        self.assertIn("not `hermes mcp test`", rules)
        self.assertIn("Mail.Send.Shared", rules)
        checklist = " ".join(morning.final_checklist)
        self.assertIn("whether the credential itself can send", checklist)

    def test_document_pointers_name_the_release_that_folded_the_skills(self) -> None:
        from omh.skills.catalog_types import DOCUMENT_PRODUCER_RUNGS_RULE

        self.assertIn("`microsoft-office` from v0.22.6", DOCUMENT_PRODUCER_RUNGS_RULE)
        self.assertNotIn("v0.23", DOCUMENT_PRODUCER_RUNGS_RULE)


if __name__ == "__main__":
    unittest.main()
