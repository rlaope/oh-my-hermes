from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.surfaces.evidence_copy import (  # noqa: E402
    first_not_evidence_item,
    not_evidence_action_suffix,
    not_evidence_reply_suffix,
)


class EvidenceCopyTests(unittest.TestCase):
    def test_first_not_evidence_item_normalizes_underscore_labels(self) -> None:
        self.assertEqual(first_not_evidence_item(["visual_QA", "delivery"]), "visual QA")
        self.assertEqual(first_not_evidence_item([]), "")

    def test_reply_suffix_prefers_concrete_evidence_gap(self) -> None:
        suffix = not_evidence_reply_suffix(
            ["plan acceptance"],
            fallback=" This is guidance, not execution evidence.",
        )

        self.assertEqual(suffix, " This is still not evidence of plan acceptance.")

    def test_reply_suffix_uses_surface_specific_fallback(self) -> None:
        suffix = not_evidence_reply_suffix([], fallback=" This is routing guidance, not execution evidence.")

        self.assertEqual(suffix, " This is routing guidance, not execution evidence.")

    def test_action_suffix_keeps_claim_boundary_natural(self) -> None:
        self.assertEqual(
            not_evidence_action_suffix(["execution"]),
            "; do not claim execution until observed",
        )
        self.assertEqual(not_evidence_action_suffix([]), "; keep evidence claims separate")


if __name__ == "__main__":
    unittest.main()
