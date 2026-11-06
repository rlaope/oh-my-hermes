"""Contract tests for the business-operations skill audit (PR for the `business-ops` lane)."""

from __future__ import annotations

import datetime
import re
import unicodedata
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


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


class ScanPatternTests(unittest.TestCase):
    RRN = re.compile(render.KR_RRN_PATTERN)
    RRN_MASKED = re.compile(render.KR_RRN_MASKED_PATTERN)
    SSN = re.compile(render.US_SSN_PATTERN)
    ITIN = re.compile(render.US_ITIN_PATTERN)
    SSN_MASKED = re.compile(render.US_SSN_MASKED_PATTERN)
    MOBILE = re.compile(render.KR_MOBILE_PATTERN)
    MOBILE_STRIPPED = re.compile(render.KR_MOBILE_STRIPPED_PATTERN)
    SHAPE13 = re.compile(render.SHAPE13_PATTERN)
    SHAPE9 = re.compile(render.SHAPE9_PATTERN)

    def test_resident_numbers_are_found_whatever_the_separator_or_check_digit(self) -> None:
        for sample in (
            "900101-1123454", "900101 1123454", "900101\u20131123454", "9001011123454", "900101-1123450",
            "900101\uff0d1123454", "900101\u22121123454", "900101 - 1123454", "900101.1123454", "\uff19\uff10\uff10\uff11\uff10\uff11-1123454",
        ):
            with self.subTest(sample=sample):
                match = self.RRN.search(_norm(sample))
                self.assertIsNotNone(match)
                self.assertTrue(_valid_date(re.sub(r"\D", "", match.group(0))[:6]))

    def test_masked_resident_numbers_count(self) -> None:
        for sample in ("900101-1******", "900101-1\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf", "900101-*******", "900101 1xxxxxx"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(self.RRN_MASKED.search(_norm(sample)))

    def test_other_digit_strings_are_not_resident_numbers(self) -> None:
        self.assertIsNone(self.RRN.search("1731000000000"))
        self.assertIsNone(self.RRN.search("12900101-1123454"))
        self.assertIsNone(self.RRN.search("900101-11234545"))

    def test_shape_only_counts_catch_what_the_full_pattern_cannot(self) -> None:
        self.assertIsNotNone(self.SHAPE13.search("1731000000000"))
        self.assertIsNotNone(self.SHAPE9.search("123456789"))
        self.assertIsNone(self.SHAPE9.search("1234567890"))
        self.assertIsNotNone(self.RRN.search("8801043014830"))

    def test_mobile_numbers_in_common_forms_and_anchored(self) -> None:
        for sample in (
            "010-1234-5678", "01012345678", "+82 10-1234-5678", "010 1234 5678", "010.1234.5678", "+8210-1234-5678",
            "010\u20131234\u20135678", "(010) 1234-5678", "+82 (0)10-1234-5678", "0082-10-1234-5678",
        ):
            with self.subTest(sample=sample):
                self.assertIsNotNone(self.MOBILE.search(_norm(sample)))
        for sample in ("20101234567", "0.01012345678"):
            with self.subTest(sample=sample):
                self.assertIsNone(self.MOBILE.search(sample))
        for sample in ("1012345678", "10-1234-5678"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(self.MOBILE_STRIPPED.search(sample))

    def test_ssn_forms_itin_and_masked_last_four(self) -> None:
        for sample in ("123-45-6789", "123 45 6789", "123\u201345\u20136789", "123456789"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(self.SSN.search(_norm(sample)))
        for sample in ("000-12-3456", "666-12-3456", "123-00-6789", "123-45-0000"):
            with self.subTest(sample=sample):
                self.assertIsNone(self.SSN.search(sample))
        self.assertIsNone(self.SSN.search("912-70-1234"))
        self.assertIsNotNone(self.ITIN.search("912-70-1234"))
        self.assertIsNotNone(self.SSN_MASKED.search("XXX-XX-6789"))

    def test_the_reference_states_the_patterns_and_the_floor(self) -> None:
        text = _reference("data-share-review", "references/data-share-method.md")
        for pattern in (
            render.KR_RRN_PATTERN, render.KR_RRN_MASKED_PATTERN, render.US_SSN_PATTERN, render.US_ITIN_PATTERN,
            render.US_SSN_MASKED_PATTERN, render.KR_MOBILE_PATTERN, render.KR_MOBILE_STRIPPED_PATTERN,
            render.SHAPE13_PATTERN, render.SHAPE9_PATTERN,
        ):
            self.assertIn(pattern, text)
        for fragment in ("NFKC", "`rg -P`", "Never use the check digit as a filter", "`data_state`",
                         "Zero hits never prove a file is `redacted`", "sample read by the reviewer"):
            self.assertIn(fragment, text)
        for line in text.splitlines():
            if line.startswith("|"):
                self.assertNotIn("(?<!", line)


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
