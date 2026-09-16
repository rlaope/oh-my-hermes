"""A vendor glyph must not be mistaken for a signal, and must not move a column.

Three claims worth a test each. The glyph set cannot intersect the traffic
lights, because a red lane and a stopped lane would look the same. Every glyph
is two display cells, because a column of glyphs sits in front of an aligned
board. And every model this repository actually ships has one, derived from the
shipped table rather than from a list kept beside it.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.catalogs.model_chain_table import MODEL_DISPLAY_LABELS  # noqa: E402
from omh.catalogs.model_vendor_glyphs import (  # noqa: E402
    UNKNOWN_VENDOR,
    UNKNOWN_VENDOR_GLYPH,
    VENDOR_GLYPHS,
    vendor_for_model,
    vendor_glyph,
    vendor_text,
)
from omh.coding.status_board import render_status_board_text, status_board_messenger_body  # noqa: E402
from omh.system.display_width import display_width  # noqa: E402
from omh.wrapper.briefing import _SIGNAL_GLYPHS  # noqa: E402


class SeparationFromSignalTests(unittest.TestCase):
    def test_no_vendor_wears_a_traffic_light(self) -> None:
        """🔴 on a vendor would read as a stopped lane on every board."""
        collisions = set(VENDOR_GLYPHS.values()) & set(_SIGNAL_GLYPHS.values())
        self.assertEqual(collisions, set(), f"vendor glyphs colliding with signals: {collisions}")

    def test_the_unknown_glyph_is_not_a_traffic_light_either(self) -> None:
        self.assertNotIn(UNKNOWN_VENDOR_GLYPH, set(_SIGNAL_GLYPHS.values()))

    def test_every_vendor_glyph_is_distinct(self) -> None:
        self.assertEqual(len(set(VENDOR_GLYPHS.values())), len(VENDOR_GLYPHS))

    def test_the_unknown_glyph_is_not_a_vendor_glyph(self) -> None:
        self.assertNotIn(UNKNOWN_VENDOR_GLYPH, set(VENDOR_GLYPHS.values()))


class WidthTests(unittest.TestCase):
    def test_every_glyph_is_two_display_cells(self) -> None:
        """A one- or three-cell glyph looks fine in bullets and ragged in the
        fenced block the same rows render as on a narrow surface."""
        for vendor, glyph in {**VENDOR_GLYPHS, UNKNOWN_VENDOR: UNKNOWN_VENDOR_GLYPH}.items():
            with self.subTest(vendor=vendor):
                self.assertEqual(display_width(glyph), 2, f"{vendor} glyph {glyph!r} is not two cells")


class VendorResolutionTests(unittest.TestCase):
    def test_every_shipped_model_alias_resolves_to_a_vendor(self) -> None:
        """Derived from the shipped chain table, so a new model that joins a
        chain without a vendor entry fails here rather than rendering ⬜."""
        unresolved = sorted(alias for alias in MODEL_DISPLAY_LABELS if vendor_for_model(alias) == UNKNOWN_VENDOR)
        self.assertEqual(unresolved, [], f"shipped aliases with no vendor: {unresolved}")

    def test_a_generation_numbered_token_still_resolves(self) -> None:
        """`qwen3-coder` is why the token table is written out rather than
        matched by prefix."""
        self.assertEqual(vendor_for_model("qwen3-coder"), "qwen")

    def test_siblings_share_one_glyph(self) -> None:
        self.assertEqual(vendor_glyph("claude-opus-5"), vendor_glyph("claude-fable-5-1"))

    def test_a_label_with_an_effort_suffix_resolves(self) -> None:
        self.assertEqual(vendor_for_model("gpt-6-astra high"), "gpt")

    def test_a_bare_product_name_resolves(self) -> None:
        """The board carries what an executor reported, not an alias OMH chose,
        and Anthropic's product names arrive without the family prefix."""
        self.assertEqual(vendor_for_model("fable-5 high"), "claude")
        self.assertEqual(vendor_for_model("opus-5"), "claude")

    def test_a_provider_prefixed_id_resolves_to_the_model_vendor(self) -> None:
        """A gateway serving someone else's model: the vendor is the model's."""
        self.assertEqual(vendor_for_model("openrouter/qwen-3.5-coder high"), "qwen")
        self.assertEqual(vendor_for_model("anthropic/claude-sonnet-4"), "claude")

    def test_an_unknown_model_gets_the_neutral_square(self) -> None:
        self.assertEqual(vendor_glyph("some-future-model"), UNKNOWN_VENDOR_GLYPH)
        self.assertEqual(vendor_for_model("some-future-model"), UNKNOWN_VENDOR)

    def test_an_absent_model_gets_the_neutral_square(self) -> None:
        self.assertEqual(vendor_glyph(""), UNKNOWN_VENDOR_GLYPH)
        self.assertEqual(vendor_glyph("executor default"), UNKNOWN_VENDOR_GLYPH)

    def test_the_text_fallback_names_the_vendor(self) -> None:
        self.assertEqual(vendor_text("claude-opus-5"), "[claude]")
        self.assertEqual(vendor_text("nothing-known"), "[unknown]")


class BoardRenderingTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return {
            "claim_boundary": "b",
            "running_count": 3,
            "unit_count": 3,
            "observed_at": "04:00Z",
            "units": [
                {"label": "routing", "runtime": "claude-code", "model_label": "claude-opus-5 xhigh",
                 "status": "running", "elapsed_text": "12m", "tokens_text": "18420", "session_ref": "s1"},
                {"label": "tests", "runtime": "codex", "model_label": "gpt-6-astra high",
                 "status": "running", "elapsed_text": "8m", "tokens_text": "9100", "session_ref": "s2"},
                {"label": "docs", "runtime": "omo", "model_label": "deepseek-flash",
                 "status": "completed", "elapsed_text": "3m", "tokens_text": "unknown", "session_ref": "s3"},
            ],
        }

    def test_both_profiles_show_the_same_glyphs(self) -> None:
        aligned = render_status_board_text(self._payload())
        bullets = status_board_messenger_body(self._payload())
        for glyph in ("🟠", "⚪", "🔵"):
            self.assertIn(glyph, aligned)
            self.assertIn(glyph, bullets)

    def test_the_glyph_column_does_not_shift_the_columns_after_it(self) -> None:
        """The reason the two-cell rule is enforced: STATUS must still line up."""
        rows = [
            line for line in render_status_board_text(self._payload()).splitlines()
            if "Code · " in line or line.startswith("LABEL")
        ]
        self.assertEqual(len(rows), 4)
        offsets = {display_width(row[: row.index("Code · ")]) for row in rows if "Code · " in row}
        self.assertEqual(len(offsets), 1, f"STATUS column starts at {offsets}")

    def test_a_board_with_no_model_renders_the_neutral_square(self) -> None:
        payload = self._payload()
        payload["units"] = [{"label": "x", "runtime": "codex", "status": "running"}]  # type: ignore[index]
        self.assertIn(UNKNOWN_VENDOR_GLYPH, render_status_board_text(payload))


if __name__ == "__main__":
    unittest.main()
