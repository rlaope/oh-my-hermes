"""The dictionary must answer every name the briefing can put on screen.

`step_label` falls back to the id so a render never raises, which means a
missing row is invisible at runtime: the reader just sees `workspace_isolation`
again. These are the gate that makes the gap visible instead — every id
`_progress_steps` can produce, every blocker kind `_blockers` can emit, and
every locale either locale set can ask for.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.catalogs.briefing_vocabulary import (  # noqa: E402
    BLOCKER_KIND_LABELS,
    BRIEFING_VOCABULARY_LOCALES,
    DEFAULT_LOCALE,
    STATUS_BOARD_COPY,
    STEP_LABELS,
    blocker_kind_label,
    status_board_copy,
    step_label,
)
from omh.commands.language import LANGUAGE_CODES  # noqa: E402
from omh.wrapper.briefing import _BLOCKER_KINDS, BLOCKER_EXECUTOR_SESSION, _progress_steps  # noqa: E402
from omh.wrapper.localized_copy import SUPPORTED_COPY_LOCALES  # noqa: E402

_TABLES = (("STEP_LABELS", STEP_LABELS), ("BLOCKER_KIND_LABELS", BLOCKER_KIND_LABELS), ("STATUS_BOARD_COPY", STATUS_BOARD_COPY))


class LocaleCoverageTests(unittest.TestCase):
    def test_every_row_answers_every_locale(self) -> None:
        """A half-translated row reads as a bug in the sentence around it."""
        for table_name, table in _TABLES:
            for key, row in table.items():
                with self.subTest(table=table_name, key=key):
                    self.assertEqual(set(row), set(BRIEFING_VOCABULARY_LOCALES))
                    self.assertTrue(all(str(value).strip() for value in row.values()))

    def test_the_vocabulary_covers_both_locale_sets(self) -> None:
        """Two sets exist and they differ in size; the tables must span both.

        `LANGUAGE_CODES` is what `--language`/`OMH_LANG` accept;
        `SUPPORTED_COPY_LOCALES` is the chat-copy set resolved from the message.
        Covering only the narrower one would mean a chat surface in Spanish
        silently rendering English step names.
        """
        covered = set(BRIEFING_VOCABULARY_LOCALES)
        self.assertTrue(set(LANGUAGE_CODES) <= covered, f"missing CLI locales: {set(LANGUAGE_CODES) - covered}")
        self.assertTrue(
            set(SUPPORTED_COPY_LOCALES) <= covered,
            f"missing chat-copy locales: {set(SUPPORTED_COPY_LOCALES) - covered}",
        )

    def test_english_is_the_fallback_locale(self) -> None:
        self.assertIn(DEFAULT_LOCALE, BRIEFING_VOCABULARY_LOCALES)


class KeyCoverageTests(unittest.TestCase):
    def test_every_progress_step_id_has_a_label(self) -> None:
        """Derived from the producer, not from a list copied beside it."""
        step_ids = {str(step["id"]) for step in _progress_steps({}, {}, {}, {})}
        self.assertTrue(step_ids, "expected _progress_steps to return steps")
        missing = step_ids - set(STEP_LABELS)
        self.assertEqual(missing, set(), f"step ids with no label row: {sorted(missing)}")

    def test_the_executor_session_blocker_id_has_a_label(self) -> None:
        self.assertIn(BLOCKER_EXECUTOR_SESSION, STEP_LABELS)

    def test_every_blocker_kind_has_a_label(self) -> None:
        kinds = {kind for kind, _key in _BLOCKER_KINDS}
        missing = kinds - set(BLOCKER_KIND_LABELS)
        self.assertEqual(missing, set(), f"blocker kinds with no label row: {sorted(missing)}")

    def test_no_label_row_is_an_orphan(self) -> None:
        """A row for an id nothing produces is dead copy someone will translate."""
        produced = {str(step["id"]) for step in _progress_steps({}, {}, {}, {})} | {BLOCKER_EXECUTOR_SESSION}
        self.assertEqual(set(STEP_LABELS) - produced, set())


class LookupTests(unittest.TestCase):
    def test_a_known_id_renders_words_not_the_id(self) -> None:
        self.assertEqual(step_label("workspace_isolation"), "workspace isolation")
        self.assertEqual(step_label("workspace_isolation", locale="ko"), "작업 폴더 분리")

    def test_an_unknown_id_falls_back_to_itself(self) -> None:
        self.assertEqual(step_label("not_a_step"), "not_a_step")

    def test_an_unknown_locale_falls_back_to_english(self) -> None:
        self.assertEqual(step_label("merged", locale="xx"), STEP_LABELS["merged"]["en"])

    def test_a_regional_locale_resolves_to_its_base(self) -> None:
        self.assertEqual(step_label("merged", locale="ko_KR"), STEP_LABELS["merged"]["ko"])
        self.assertEqual(step_label("merged", locale="ko-KR"), STEP_LABELS["merged"]["ko"])

    def test_blocker_kinds_render_words(self) -> None:
        self.assertEqual(blocker_kind_label("cancelled", locale="ja"), "キャンセル")

    def test_status_board_copy_keeps_its_placeholders(self) -> None:
        """Every locale's header must accept the same named fields."""
        for locale in BRIEFING_VOCABULARY_LOCALES:
            with self.subTest(locale=locale):
                rendered = status_board_copy("header", locale=locale).format(
                    moving=1, stuck="", total=2, observed_at="now"
                )
                self.assertIn("1", rendered)
                self.assertIn("2", rendered)
                self.assertIn("now", rendered)

    def test_status_board_truncation_keeps_its_placeholders(self) -> None:
        for locale in BRIEFING_VOCABULARY_LOCALES:
            with self.subTest(locale=locale):
                rendered = status_board_copy("truncation", locale=locale).format(shown=3, total=9, dropped=6)
                for value in ("3", "9", "6"):
                    self.assertIn(value, rendered)


if __name__ == "__main__":
    unittest.main()
