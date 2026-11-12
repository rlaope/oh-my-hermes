"""Rules added to show-reel's OMH-original references keep their mechanism.

Each test names the mechanism of the added rules, read from the producer. The
translated `craft-*` pages are outside the change: their bytes must still equal
the digests in the toolkit's provenance manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.skills.show_reel_references import show_reel_reference_templates

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/skills/show_reel_toolkit/scripts"


def reference(name: str) -> str:
    """One produced reference with its soft line wraps collapsed."""
    path = f"references/{name}.md"
    return " ".join(next(t.content for t in show_reel_reference_templates() if t.relative_path == path).split())


class ShowReelGapRuleTests(unittest.TestCase):
    def assert_tokens(self, name: str, *tokens: str) -> None:
        text = reference(name)
        for token in tokens:
            with self.subTest(reference=name, token=token):
                self.assertIn(token, text)

    def test_the_no_context_judge_is_named_asked_about_content_and_bounded(self):
        self.assert_tokens("art-direction", "`judged_by`", "`maker` or `no_context`", "from the frames alone",
                           "two rounds by default", "Each round is a new session", "goes to the person")

    def test_a_frame_zero_value_a_vertical_layout_and_a_repeated_arc_are_checked(self):
        self.assert_tokens("art-direction", "already at its final state", "--poster", "authored 9:16 frame",
                           "shrunk landscape layout", "both build one value and then rest")

    def test_numbers_narrated_items_and_camera_moves_carry_content(self):
        self.assert_tokens("motion-techniques", "every intermediate value was true", "a ratio or a multiplier",
                           "strike it", "when the growth ends", "enters the next scene at that value",
                           "on the cue of the word that names it", "at most one camera move", "end pose")

    def test_the_theme_and_a_recurring_entity_are_written_down(self):
        self.assert_tokens("storyboard-and-evidence", "one sentence with a verb", "what breaks it", "entity legend",
                           "Every renderer")

    def test_the_brief_sets_motion_limits_before_scenes(self):
        self.assert_tokens("brief-and-locales", "motion_limits", "before any scene is authored")

    def test_every_failure_name_the_checkers_print_maps_to_an_edit(self):
        text = reference("render-qa-delivery")
        self.assertIn("## From a failed check to an edit", text)
        self.assertIn("`FAIL` on a `finish.py` row", text)
        qa = (SCRIPTS / "qa_check.py").read_text(encoding="utf-8")
        motion = (SCRIPTS / "motion_check.py").read_text(encoding="utf-8")
        self.assertIn('"probe_decode_measure"', qa)
        printed = set(re.findall(r'failures\.append\("([^"]+)"\)', qa)) | set(re.findall(r'"kind": "([a-z_]+)"', motion))
        # Both patterns still read the scripts; an empty set would pass the loop below.
        self.assertLessEqual({"max_bytes", "true_peak ceiling", "unannotated_stillness", "flash_review_required"}, printed)
        # `failures.append(key)` prints the policy key itself for the exact-match keys.
        for name in sorted(printed | {"probe_decode_measure", "duration", "fps", "frames", "width", "height"}):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", text)

    def test_tool_reports_are_passed_on_as_emitted(self):
        self.assert_tokens("render-qa-delivery", "as it was emitted", "word for word", "never in its place")

    def test_translated_craft_pages_still_match_their_provenance_digests(self):
        manifest = json.loads((ROOT / "src/skills/show_reel_toolkit/upstream-manifest.json").read_text(encoding="utf-8"))
        pages = sorted((ROOT / "src/skills/show_reel_craft").glob("craft-*.md"))
        self.assertEqual({f"references/{page.name}" for page in pages}, set(manifest["references"]))
        for page in pages:
            with self.subTest(page=page.name):
                self.assertEqual(hashlib.sha256(page.read_bytes()).hexdigest(),
                                 manifest["references"][f"references/{page.name}"]["local_sha256"])


if __name__ == "__main__":
    unittest.main()
