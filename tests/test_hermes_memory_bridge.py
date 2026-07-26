"""OMH reads Hermes memory in Hermes' own unit, and relates it to its own store.

Two defects motivate this file:

- The advisory lane compared `stat().st_size` against a character cap. Korean
  memory costs three bytes per syllable, so a file well under the cap reported
  as over it. Only a non-ASCII fixture can catch that, so every size assertion
  here uses Hangul.
- OMH deduplicated approved records against itself only. A fact approved in OMH
  and restated by hand in MEMORY.md lived in both stores with nothing linking
  them, because Hermes' memory tool rejects exact strings and nothing compared
  the rewordings.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.maintenance import advisory
from omh.maintenance.advisory import MEMORY_STALE_AFTER_DAYS, check_hermes_memory_staleness
from omh.maintenance.hermes_memory import (
    HERMES_MEMORY_DELIMITER,
    MEMORY_FILE_CAP_CHARS,
    memory_char_count,
    nearest_entry,
    parse_memory_entries,
    read_hermes_memory,
    similarity,
)
from omh.memory import (
    approve_project_memory_candidate,
    build_hermes_memory_bridge,
    build_project_memory_status,
    capture_project_memory_candidate,
)
from omh.paths import resolve_paths

# 1,119 characters but 2,631 UTF-8 bytes: comfortably under the 2,200-character
# cap, and comfortably over it if bytes are counted by mistake. Stripped here
# because Hermes stores entries stripped.
KOREAN_ENTRY = ("문서 하네스는 에이전트가 HTML을 먼저 작성하고 변환하는 시스템이다. " * 28).strip()


def _write_memory(home: Path, *entries: str) -> Path:
    path = home / "memories" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HERMES_MEMORY_DELIMITER.join(entries), encoding="utf-8")
    return path


class EntryParsingTests(unittest.TestCase):
    def test_entries_split_on_the_delimiter_and_drop_blanks(self) -> None:
        text = f"first{HERMES_MEMORY_DELIMITER}\n  second  {HERMES_MEMORY_DELIMITER}{HERMES_MEMORY_DELIMITER}"
        self.assertEqual(parse_memory_entries(text), ("first", "second"))

    def test_empty_file_has_no_entries_and_costs_nothing(self) -> None:
        self.assertEqual(parse_memory_entries(""), ())
        self.assertEqual(memory_char_count(()), 0)

    def test_char_count_matches_hermes_delimiter_join(self) -> None:
        entries = ("alpha", "beta", "gamma")
        # Hermes computes len(ENTRY_DELIMITER.join(entries)) before allowing a
        # write, so OMH's headroom is wrong unless it counts the delimiters too.
        self.assertEqual(memory_char_count(entries), len("alpha§beta§gamma"))


class UnitTests(unittest.TestCase):
    """Characters, not bytes. The distinction only shows up outside ASCII."""

    def test_korean_memory_under_cap_is_not_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = _write_memory(home, KOREAN_ENTRY)
            self.assertGreater(path.stat().st_size, MEMORY_FILE_CAP_CHARS)
            self.assertLess(len(KOREAN_ENTRY), MEMORY_FILE_CAP_CHARS)

            entry = check_hermes_memory_staleness(home)
            self.assertEqual(entry.status, "ok")
            self.assertIn("chars", entry.observed)
            self.assertNotIn("bytes", entry.observed)

    def test_reading_reports_characters_and_entry_count(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_memory(home, "alpha", KOREAN_ENTRY)
            reading = read_hermes_memory(home)[0]
            self.assertEqual(reading.label, "MEMORY.md")
            self.assertEqual(len(reading.entries), 2)
            self.assertEqual(reading.chars, memory_char_count(("alpha", KOREAN_ENTRY)))
            self.assertFalse(reading.over_cap)
            self.assertEqual(reading.headroom_chars, MEMORY_FILE_CAP_CHARS - reading.chars)


class CapTests(unittest.TestCase):
    def test_over_cap_is_advice_even_when_freshly_written(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_memory(home, "x" * (MEMORY_FILE_CAP_CHARS + 1))
            entry = check_hermes_memory_staleness(home)
            # Age alone used to decide this, so a full file touched today read
            # as ok while Hermes was already rejecting the next write.
            self.assertEqual(entry.status, "advice")

    def test_stale_mtime_is_still_advice(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = _write_memory(home, "short note")
            old = advisory._now_seconds() - (MEMORY_STALE_AFTER_DAYS + 5) * 86400
            os.utime(path, (old, old))
            self.assertEqual(check_hermes_memory_staleness(home).status, "advice")

    def test_headroom_is_the_cap_when_no_file_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            reading = read_hermes_memory(Path(tmp))[0]
            self.assertFalse(reading.exists)
            self.assertEqual(reading.headroom_chars, MEMORY_FILE_CAP_CHARS)


class SimilarityTests(unittest.TestCase):
    def test_reworded_fact_scores_above_the_duplicate_threshold(self) -> None:
        left = "document-harness: sionic-ai 레포의 에이전트 하네스 기반 문서 작성 시스템"
        right = "document-harness는 sionic-ai 레포의 에이전트 하네스 기반 문서 작성 시스템이다"
        self.assertGreaterEqual(similarity(left, right), 0.6)

    def test_unrelated_texts_score_low(self) -> None:
        self.assertLess(similarity("release script dry run flag", "커피 원두 보관 방법"), 0.6)

    def test_nearest_entry_reports_no_match_against_an_empty_store(self) -> None:
        self.assertEqual(nearest_entry("anything", ()), (-1, 0.0))


class BridgeTests(unittest.TestCase):
    def _approved(self, paths, summary: str) -> None:
        capture = capture_project_memory_candidate(paths, summary, scope_ref="demo")
        approve_project_memory_candidate(paths, str(capture["candidate"]["candidate_id"]))

    def test_record_already_in_hermes_is_not_offered_for_promotion(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            summary = "document-harness는 HTML을 먼저 작성하고 PPTX로 변환하는 문서 시스템이다"
            self._approved(paths, summary)
            _write_memory(root / ".hermes", "document-harness: HTML을 먼저 작성하고 PPTX로 변환하는 문서 시스템")

            bridge = build_hermes_memory_bridge(paths)
            self.assertEqual(bridge["approved_records"], 1)
            self.assertEqual(len(bridge["already_in_hermes"]), 1)
            self.assertEqual(bridge["promotable"], [])
            self.assertEqual(bridge["already_in_hermes"][0]["nearest_entry_index"], 0)

    def test_novel_record_is_promotable_when_it_fits_the_headroom(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            self._approved(paths, "release 스크립트는 --dry-run 플래그로 계획만 출력한다")
            _write_memory(root / ".hermes", "커피 원두는 밀봉 용기에 보관한다")

            bridge = build_hermes_memory_bridge(paths)
            self.assertEqual(bridge["already_in_hermes"], [])
            self.assertEqual(len(bridge["promotable"]), 1)
            self.assertTrue(bridge["promotable"][0]["fits_headroom"])

    def test_record_larger_than_the_headroom_does_not_fit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            self._approved(paths, "격리된 사실 " * 40)
            _write_memory(root / ".hermes", "x" * (MEMORY_FILE_CAP_CHARS - 10))

            promotable = build_hermes_memory_bridge(paths)["promotable"]
            self.assertEqual(len(promotable), 1)
            self.assertFalse(promotable[0]["fits_headroom"])

    def test_hermes_entries_without_a_record_are_reported_as_metadata_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            secret = "루트 비밀번호는 hunter2 이다"
            _write_memory(root / ".hermes", secret)

            bridge = build_hermes_memory_bridge(paths)
            rows = bridge["hermes_entries_without_omh_record"]
            self.assertEqual([row["entry_index"] for row in rows], [0])
            self.assertEqual(rows[0]["chars"], len(secret))
            # The rows describe entries; they must never carry their text.
            self.assertNotIn("hunter2", repr(bridge))

    def test_bridge_is_attached_to_memory_status(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            bridge = build_project_memory_status(paths)["hermes_memory"]
            self.assertEqual(bridge["schema_version"], "hermes_memory_bridge/v1")
            self.assertIn("cannot change it", str(bridge["claim_boundary"]))

    def test_unreadable_memory_is_unobserved_rather_than_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / "memories" / "MEMORY.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xff\xfe not utf-8")
            entry = check_hermes_memory_staleness(home)
            # Guessing "ok" here would report a healthy memory OMH never read.
            self.assertEqual(entry.status, "unobserved")


if __name__ == "__main__":
    unittest.main()
