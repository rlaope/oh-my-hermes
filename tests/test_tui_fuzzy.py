"""Subsequence matching (`omh.tui.fuzzy`) in the slash menu and the three pickers' filters."""

from __future__ import annotations

import unittest

from omh.tui import slash
from omh.tui.fuzzy import subsequence_score, subsequence_tail
from omh.tui.keys import CHAR, Key
from omh.tui.model_picker import ModelPicker, ModelRow
from omh.tui.rewind_picker import RewindPicker, RewindRow
from omh.tui.session_picker import SessionPicker, SessionRow


class SubsequenceScoreTests(unittest.TestCase):
    def test_characters_in_order_match_and_others_do_not(self) -> None:
        self.assertIsNotNone(subsequence_score("rld", "reload-skills"))
        self.assertIsNotNone(subsequence_score("RLD", "Reload-Skills"))
        self.assertIsNone(subsequence_score("xyz", "reload-skills"))
        self.assertIsNone(subsequence_score("dlr", "reload-skills"))
        self.assertIsNone(subsequence_score("rll", "rel"))

    def test_an_empty_needle_matches_everything_alike(self) -> None:
        self.assertEqual(subsequence_score("", "a"), subsequence_score("", "bcd"))

    def test_prefix_beats_substring_beats_segment_starts_beats_scattered(self) -> None:
        prefix = subsequence_score("rel", "reload-skills")
        inner = subsequence_score("rel", "a-reload")
        initials = subsequence_score("rs", "reload-skills")
        scattered = subsequence_score("rs", "carousel")
        for higher, lower in ((prefix, inner), (inner, initials), (initials, scattered)):
            self.assertIsNotNone(higher)
            self.assertIsNotNone(lower)
            self.assertGreater(higher, lower)

    def test_a_tighter_run_scores_above_a_looser_one(self) -> None:
        self.assertGreater(subsequence_score("ac", "xabcx") or 0, 0)
        self.assertGreater(subsequence_score("sn", "claude-sonnet") or 0, subsequence_score("sn", "xsxxxxn") or 0)

    def test_is_deterministic(self) -> None:
        self.assertEqual(subsequence_score("rld", "reload-skills"), subsequence_score("rld", "reload-skills"))


class SlashTests(unittest.TestCase):
    CATALOG = [("restart-thing", "r"), ("omh-research", "s"), ("my-res", "m"), ("rest-api", "x")]

    def test_a_scattered_name_is_offered_after_the_matches_it_used_to_have(self) -> None:
        self.assertIn("reload-skills", [c.name for c in slash.completions("rld")])
        names = [c.name for c in slash.completions("rld")]
        self.assertEqual(names[0], "reload-skills")

    def test_the_prefix_and_substring_groups_keep_their_order(self) -> None:
        names = [c.name for c in slash.completions("res", self.CATALOG)]
        # Prefix (the TUI's own, then the catalog), then substring; nothing the old menu offered moves.
        self.assertEqual(names[:5], ["resume", "restart-thing", "rest-api", "omh-research", "my-res"])

    def test_scattered_matches_come_last_by_score_then_name(self) -> None:
        names = [c.name for c in slash.completions("rs", self.CATALOG)]
        direct = [n for n in names if "rs" in n]
        self.assertEqual(names[: len(direct)], direct)
        self.assertEqual(len(names), len(set(names)))

    def test_no_match_is_still_none(self) -> None:
        self.assertEqual(slash.completions("qqqq", self.CATALOG), [])

    def test_an_empty_prefix_still_offers_everything_once(self) -> None:
        names = [c.name for c in slash.completions("", self.CATALOG)]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("restart-thing", names)


class ModelPickerTests(unittest.TestCase):
    ROWS = [
        ModelRow("gpt-5", "openai", "OpenAI", False),
        ModelRow("claude-sonnet-4-5", "anthropic", "Anthropic", True),
    ]

    def picker(self, query: str) -> ModelPicker:
        return ModelPicker(list(self.ROWS), current="gpt-5", query=query)

    def test_scattered_letters_find_a_row(self) -> None:
        self.assertEqual([row.model for row in self.picker("snt").visible()], ["claude-sonnet-4-5"])

    def test_substring_rows_come_before_subsequence_only_rows(self) -> None:
        rows = [ModelRow("a-s-n-t", "p", "P", False), ModelRow("xsntx", "p", "P", False)]
        shown = ModelPicker(rows, current="", query="snt").visible()
        self.assertEqual([row.model for row in shown], ["xsntx", "a-s-n-t"])
        self.assertEqual([row.model for row in ModelPicker(rows, current="", query="sn").visible()], ["xsntx", "a-s-n-t"])

    def test_nothing_matching_shows_the_empty_text(self) -> None:
        chooser = self.picker("zzq")
        self.assertEqual(chooser.visible(), [])
        from _tui_lines import line_text
        from omh.tui.theme import DEFAULT_THEME

        self.assertIn("no model matches", " ".join(line_text(line) for line in chooser.lines(70, DEFAULT_THEME, 6)))

    def test_an_empty_query_lists_every_row_in_order(self) -> None:
        self.assertEqual(self.picker("").visible(), self.ROWS)


class SessionPickerTests(unittest.TestCase):
    ROWS = [
        SessionRow("a", "Reply with ok", "", 0.0, 1),
        SessionRow("b", "Release notes", "", 0.0, 1),
        SessionRow("c", "Refactor the router", "", 0.0, 1),
    ]

    def test_scattered_letters_of_a_title_find_it(self) -> None:
        chooser = SessionPicker(list(self.ROWS), current="", query="rfr")
        self.assertEqual([row.id for row in chooser.visible()], ["c"])

    def test_substring_matches_come_first(self) -> None:
        chooser = SessionPicker(list(self.ROWS), current="", query="rel")
        self.assertEqual([row.id for row in chooser.visible()][0], "b")
        self.assertEqual(sorted(row.id for row in chooser.visible()), ["a", "b"])

    def test_typing_filters_the_same_way(self) -> None:
        chooser = SessionPicker(list(self.ROWS), current="")
        for char in "rfr":
            chooser.handle_key(Key(CHAR, char))
        self.assertEqual([row.id for row in chooser.visible()], ["c"])

    def test_no_match_stays_empty(self) -> None:
        self.assertEqual(SessionPicker(list(self.ROWS), current="", query="zzq").visible(), [])


class RewindPickerTests(unittest.TestCase):
    ROWS = [RewindRow(1, "fix the router", 2, 4, 0.0), RewindRow(2, "write docs", 1, 0, 0.0)]

    def test_scattered_letters_find_a_prompt_and_substring_stays_first(self) -> None:
        self.assertEqual([row.row_id for row in RewindPicker(list(self.ROWS), query="fxr").visible()], [1])
        self.assertEqual([row.row_id for row in RewindPicker(list(self.ROWS), query="zzq").visible()], [])


class TailTests(unittest.TestCase):
    def test_substring_rows_keep_their_order_then_scattered_by_score(self) -> None:
        rows = ["x-a-b", "ab", "zab", "a_b", "qq"]
        self.assertEqual(subsequence_tail(rows, "ab", lambda r: (r,)), ["ab", "zab", "x-a-b", "a_b"])


if __name__ == "__main__":
    unittest.main()
