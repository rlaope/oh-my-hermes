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

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.maintenance import advisory
from omh.maintenance.advisory import MEMORY_STALE_AFTER_DAYS, check_hermes_memory_staleness
from omh.plugin_bundle.omh.hermes_memory import (
    DEFAULT_MEMORY_FILE_CAP_CHARS,
    DEFAULT_USER_FILE_CAP_CHARS,
    HERMES_MEMORY_DELIMITER,
    memory_char_count,
    nearest_entry,
    parse_memory_entries,
    read_hermes_memory,
    resolve_memory_caps,
    similarity,
)
from omh.memory import (
    approve_project_memory_candidate,
    build_hermes_memory_bridge,
    build_project_memory_status,
    capture_project_memory_candidate,
)
from omh.paths import resolve_paths
from omh.plugin_bundle.omh.metadata import PROVIDED_TOOLS, TOOL_FILE_STEMS
from omh.plugin_bundle.omh.tools.memory_tool import OMH_MEMORY_SCHEMA, omh_memory_handler

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
        self.assertEqual(memory_char_count(entries), len("alpha\n§\nbeta\n§\ngamma"))

    def test_a_bare_section_sign_stays_inside_its_entry(self) -> None:
        # Hermes' `_parse_entries` splits on the full "\n§\n"; a bare "§" in
        # prose is part of the entry, never a boundary.
        text = "Contract: see § 4.2 for renewal terms; renews June 1\n§\nOther fact here"
        self.assertEqual(
            parse_memory_entries(text),
            ("Contract: see § 4.2 for renewal terms; renews June 1", "Other fact here"),
        )


class UnitTests(unittest.TestCase):
    """Characters, not bytes. The distinction only shows up outside ASCII."""

    def test_korean_memory_under_cap_is_not_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = _write_memory(home, KOREAN_ENTRY)
            self.assertGreater(path.stat().st_size, DEFAULT_MEMORY_FILE_CAP_CHARS)
            self.assertLess(len(KOREAN_ENTRY), DEFAULT_MEMORY_FILE_CAP_CHARS)

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
            self.assertEqual(reading.headroom_chars, DEFAULT_MEMORY_FILE_CAP_CHARS - reading.chars)


class CapTests(unittest.TestCase):
    def test_over_cap_is_advice_even_when_freshly_written(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_memory(home, "x" * (DEFAULT_MEMORY_FILE_CAP_CHARS + 1))
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
            self.assertEqual(reading.headroom_chars, DEFAULT_MEMORY_FILE_CAP_CHARS)


class ConfiguredCapTests(unittest.TestCase):
    """The cap is Hermes' config, not OMH's constant.

    Hermes builds its memory tool with ``mem_config.get("memory_char_limit",
    2200)``, so 2200/1375 are its fallbacks. OMH hardcoded them, which reported
    a file as over cap with no headroom left while Hermes was still accepting
    writes -- invisible on any host that had never changed the default.
    """

    def _home(self, tmp: str, config: str | None = None) -> Path:
        home = Path(tmp)
        if config is not None:
            home.mkdir(parents=True, exist_ok=True)
            (home / "config.yaml").write_text(config, encoding="utf-8")
        return home

    def test_a_raised_cap_leaves_headroom_the_default_would_deny(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "memory:\n  memory_char_limit: 5000\n")
            _write_memory(home, "x" * (DEFAULT_MEMORY_FILE_CAP_CHARS + 500))

            reading = read_hermes_memory(home)[0]
            self.assertEqual(reading.cap, 5000)
            self.assertEqual(reading.cap_source, "config")
            self.assertFalse(reading.over_cap)
            self.assertEqual(reading.headroom_chars, 5000 - reading.chars)

    def test_a_lowered_cap_is_honoured_too(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "memory:\n  memory_char_limit: 500\n")
            _write_memory(home, "x" * 600)

            reading = read_hermes_memory(home)[0]
            self.assertEqual(reading.cap, 500)
            self.assertTrue(reading.over_cap)
            self.assertEqual(reading.headroom_chars, 0)

    def test_each_file_reads_its_own_key(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "memory:\n  memory_char_limit: 5000\n  user_char_limit: 4000\n")
            self.assertEqual(
                resolve_memory_caps(home),
                (("MEMORY.md", 5000, "config"), ("USER.md", 4000, "config")),
            )

    def test_one_configured_key_leaves_the_other_on_its_default(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "memory:\n  user_char_limit: 4000\n")
            self.assertEqual(
                resolve_memory_caps(home),
                (
                    ("MEMORY.md", DEFAULT_MEMORY_FILE_CAP_CHARS, "default"),
                    ("USER.md", 4000, "config"),
                ),
            )

    def test_absent_config_falls_back_to_the_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(
                resolve_memory_caps(Path(tmp)),
                (
                    ("MEMORY.md", DEFAULT_MEMORY_FILE_CAP_CHARS, "default"),
                    ("USER.md", DEFAULT_USER_FILE_CAP_CHARS, "default"),
                ),
            )

    def test_the_dotted_config_form_is_read(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "memory.memory_char_limit: 3300\n")
            self.assertEqual(resolve_memory_caps(home)[0], ("MEMORY.md", 3300, "config"))

    def test_quotes_and_inline_comments_are_stripped(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, 'memory:\n  memory_char_limit: "3300"  # raised for Korean\n')
            self.assertEqual(resolve_memory_caps(home)[0], ("MEMORY.md", 3300, "config"))

    def test_a_key_outside_the_memory_section_is_not_borrowed(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "other:\n  memory_char_limit: 9999\n")
            self.assertEqual(resolve_memory_caps(home)[0][1], DEFAULT_MEMORY_FILE_CAP_CHARS)

    def test_an_unusable_value_reports_the_default_rather_than_a_measured_cap(self) -> None:
        # A malformed cap must not become a headroom figure that reads as observed.
        for value in ("abc", "0", "-1", "", "5000.5"):
            with self.subTest(value=value), TemporaryDirectory() as tmp:
                home = self._home(tmp, f"memory:\n  memory_char_limit: {value}\n")
                self.assertEqual(
                    resolve_memory_caps(home)[0],
                    ("MEMORY.md", DEFAULT_MEMORY_FILE_CAP_CHARS, "default"),
                )

    def test_an_unreadable_config_falls_back_instead_of_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").mkdir(parents=True)
            self.assertEqual(resolve_memory_caps(home)[0][2], "default")

    def test_advisory_does_not_flag_a_file_under_its_raised_cap(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(tmp, "memory:\n  memory_char_limit: 5000\n")
            _write_memory(home, "x" * (DEFAULT_MEMORY_FILE_CAP_CHARS + 500))
            # Hardcoding 2200 made this "advice" while Hermes still accepted writes.
            self.assertEqual(check_hermes_memory_staleness(home).status, "ok")

    def test_promotion_headroom_follows_the_configured_cap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            hermes_home = root / ".hermes"
            hermes_home.mkdir(parents=True, exist_ok=True)
            (hermes_home / "config.yaml").write_text(
                "memory:\n  memory_char_limit: 5000\n", encoding="utf-8"
            )
            capture = capture_project_memory_candidate(paths, "격리된 사실 " * 40, scope_ref="demo")
            approve_project_memory_candidate(paths, str(capture["candidate"]["candidate_id"]))
            _write_memory(hermes_home, "x" * (DEFAULT_MEMORY_FILE_CAP_CHARS - 10))

            bridge = build_hermes_memory_bridge(paths)
            # The same record does not fit under the default cap; it does under 5000.
            self.assertTrue(bridge["promotable"][0]["fits_headroom"])
            self.assertEqual(bridge["files"][0]["cap"], 5000)
            self.assertEqual(bridge["files"][0]["cap_source"], "config")


class SimilarityTests(unittest.TestCase):
    def test_reworded_fact_scores_above_the_duplicate_threshold(self) -> None:
        left = "document-harness: example 레포의 에이전트 하네스 기반 문서 작성 시스템"
        right = "document-harness는 example 레포의 에이전트 하네스 기반 문서 작성 시스템이다"
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
            _write_memory(root / ".hermes", "x" * (DEFAULT_MEMORY_FILE_CAP_CHARS - 10))

            promotable = build_hermes_memory_bridge(paths)["promotable"]
            self.assertEqual(len(promotable), 1)
            self.assertFalse(promotable[0]["fits_headroom"])

    def test_the_fit_boundary_counts_hermes_full_delimiter(self) -> None:
        # Headroom 30: a 27-char summary plus the 3-char "\n§\n" fits exactly,
        # 28 does not. A 1-char delimiter would have admitted 28 and 29.
        for length, fits in ((27, True), (28, False)):
            with self.subTest(length=length), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = resolve_paths(root / ".omh", root / ".hermes")
                self._approved(paths, "q" * length)
                _write_memory(root / ".hermes", "x" * (DEFAULT_MEMORY_FILE_CAP_CHARS - 30))
                self.assertIs(build_hermes_memory_bridge(paths)["promotable"][0]["fits_headroom"], fits)

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


class MemoryToolTests(unittest.TestCase):
    """The bridge was CLI-only, so Hermes could not reach it from chat."""

    def _payload(self, root: Path) -> dict:
        with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
            return json.loads(omh_memory_handler({}))

    def test_the_tool_is_registered_under_its_own_name(self) -> None:
        self.assertEqual(OMH_MEMORY_SCHEMA["name"], "omh_memory")
        self.assertIn("omh_memory", PROVIDED_TOOLS)
        self.assertEqual(TOOL_FILE_STEMS["omh_memory"], "memory_tool")

    def test_the_tool_returns_the_bridge_from_the_installed_package(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _write_memory(root / ".hermes", "커피 원두는 밀봉 용기에 보관한다")
            payload = self._payload(root)
            self.assertEqual(payload["source_backend"], "bundle_memory")
            self.assertEqual(payload["schema_version"], "hermes_memory_bridge/v1")
            self.assertEqual(payload["plugin_tool"], "omh_memory")

    def test_no_memory_entry_text_reaches_the_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            secret = "루트비밀번호는hunter2이다"
            _write_memory(root / ".hermes", secret)
            self.assertNotIn(secret, json.dumps(self._payload(root), ensure_ascii=False))

    def test_a_read_failure_stays_distinguishable_from_an_empty_comparison(self) -> None:
        with patch(
            "omh.plugin_bundle.omh.tools.memory_tool.build_hermes_memory_bridge",
            side_effect=RuntimeError("boom"),
        ):
            payload = json.loads(omh_memory_handler({}))
        # Answering with an empty comparison would read as "Hermes remembers
        # nothing" when the truth is that OMH could not read the file.
        self.assertEqual(payload["source_backend"], "bundle_memory_error")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["reason"], "RuntimeError")
        self.assertIn("not evidence", payload["claim_boundary"])
        self.assertNotIn("boom", json.dumps(payload))


class ExternalContextLabelTests(unittest.TestCase):
    def test_native_entries_are_not_omh_approved_and_disclose_prefetch_egress(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_memory(root / ".hermes", "native private memory")

            from omh.plugin_bundle.omh.hermes_memory import build_hermes_memory_bridge

            bridge = build_hermes_memory_bridge(root / ".omh", root / ".hermes")
            native = bridge["hermes_entries_without_omh_record"][0]
            self.assertEqual(native["source_class"], "hermes_native")
            self.assertEqual(native["admission_status"], "not_omh_reviewed")
            self.assertEqual(bridge["external_context"]["provider"]["admission_status"], "not_omh_reviewed")
            self.assertEqual(bridge["external_context"]["vector"]["admission_status"], "not_omh_reviewed")
            self.assertIn("may transmit rendered OMH prefetch", bridge["claim_boundary"])
