from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.skills.duplicate_content import (
    ALLOWLISTED_DUPLICATE_BLOCKS,
    Surface,
    assembled_surfaces_for_measurement,
    cross_surface_duplicate_profile,
    detect_cross_surface_duplicates,
    normalize_block,
    paragraph_blocks,
    suppress_duplicates,
)

SHARED_PARAGRAPH = (
    "This is a shared paragraph long enough to clear the minimum block size "
    "so the detector treats it as owned content rather than a stray phrase."
)


class DuplicateContentSuppressionTests(unittest.TestCase):
    def test_detects_duplicate_block_across_different_surface_kinds(self) -> None:
        surfaces = [
            Surface("primer", "awareness_primer", f"Intro.\n\n{SHARED_PARAGRAPH}\n\nPrimer tail."),
            Surface("skill_body:x", "skill_body", f"Skill x.\n\n{SHARED_PARAGRAPH}\n\nUnique x content."),
        ]
        duplicates = detect_cross_surface_duplicates(surfaces)
        self.assertEqual(len(duplicates), 1)
        duplicate = duplicates[0]
        self.assertEqual(duplicate.owner_surface, "primer")
        self.assertEqual(duplicate.duplicate_surface, "skill_body:x")
        self.assertEqual(duplicate.byte_len, len(SHARED_PARAGRAPH))
        self.assertFalse(duplicate.allowlisted)

    def test_same_kind_repetition_is_not_a_cross_surface_duplicate(self) -> None:
        # Two skill bodies sharing a paragraph is `context_cost.py`'s per-heading
        # measurement, not this module's concern -- only a different `kind` counts.
        surfaces = [
            Surface("skill_body:a", "skill_body", f"A.\n\n{SHARED_PARAGRAPH}\n\nA tail."),
            Surface("skill_body:b", "skill_body", f"B.\n\n{SHARED_PARAGRAPH}\n\nB tail."),
        ]
        duplicates = detect_cross_surface_duplicates(surfaces)
        self.assertEqual(duplicates, [])

    def test_blocks_below_minimum_size_are_ignored(self) -> None:
        surfaces = [
            Surface("primer", "awareness_primer", "Short.\n\nAlso short."),
            Surface("skill_body:x", "skill_body", "Short.\n\nAlso short."),
        ]
        self.assertEqual(detect_cross_surface_duplicates(surfaces), [])

    def test_pointer_replacement_removes_duplicate_text_and_names_the_owner(self) -> None:
        surfaces = [
            Surface("primer", "awareness_primer", f"Intro.\n\n{SHARED_PARAGRAPH}\n\nPrimer tail."),
            Surface("skill_body:x", "skill_body", f"Skill x.\n\n{SHARED_PARAGRAPH}\n\nUnique x content."),
        ]
        duplicates = detect_cross_surface_duplicates(surfaces)
        suppressed = suppress_duplicates(surfaces, duplicates)
        by_id = {surface.surface_id: surface for surface in suppressed}

        # The owner keeps its full text untouched.
        self.assertIn(SHARED_PARAGRAPH, by_id["primer"].content)
        # The later surface loses the duplicate text and gets a pointer naming the owner.
        self.assertNotIn(SHARED_PARAGRAPH, by_id["skill_body:x"].content)
        self.assertIn("`primer`", by_id["skill_body:x"].content)
        self.assertIn("Unique x content.", by_id["skill_body:x"].content)

        # Exactly one surface still carries the real text: no semantic loss.
        carriers = [s for s in suppressed if SHARED_PARAGRAPH in s.content]
        self.assertEqual(len(carriers), 1)
        self.assertEqual(carriers[0].surface_id, "primer")

    def test_suppression_is_deterministic_across_runs(self) -> None:
        surfaces = [
            Surface("primer", "awareness_primer", f"Intro.\n\n{SHARED_PARAGRAPH}\n\nPrimer tail."),
            Surface("skill_body:x", "skill_body", f"Skill x.\n\n{SHARED_PARAGRAPH}\n\nUnique x content."),
            Surface("skill_body:y", "skill_body", f"Skill y.\n\n{SHARED_PARAGRAPH}\n\nUnique y content."),
        ]
        duplicates = detect_cross_surface_duplicates(surfaces)
        first = suppress_duplicates(surfaces, duplicates)
        second = suppress_duplicates(surfaces, duplicates)
        self.assertEqual(first, second)

    def test_allowlisted_block_is_left_untouched_in_every_surface(self) -> None:
        allowlisted_normalized = next(iter(ALLOWLISTED_DUPLICATE_BLOCKS))
        surfaces = [
            Surface("primer", "awareness_primer", f"Intro.\n\n{allowlisted_normalized}\n\nTail."),
            Surface("reference:common-rail", "reference", f"Rail.\n\n{allowlisted_normalized}\n\nRail tail."),
        ]
        duplicates = detect_cross_surface_duplicates(surfaces)
        self.assertEqual(len(duplicates), 1)
        self.assertTrue(duplicates[0].allowlisted)
        self.assertIsNotNone(duplicates[0].allowlist_reason)

        suppressed = suppress_duplicates(surfaces, duplicates)
        for surface in suppressed:
            self.assertIn(allowlisted_normalized, surface.content)
            self.assertNotIn("duplicate content suppressed", surface.content)

    def test_normalize_and_paragraph_helpers_are_whitespace_insensitive(self) -> None:
        text = (
            "first block here that is long enough on its own to clear the minimum block size.\n"
            "line   two of the first block.\n"
            "\n\n"
            "second block here that is also long enough to count as its own block on its own."
        )
        blocks = paragraph_blocks(text)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(normalize_block("a\n\tb   c"), "a b c")

    def test_real_corpus_has_no_unallowlisted_cross_surface_duplicates(self) -> None:
        """Standing regression gate for backlog item E.

        If a future change makes the same instruction text appear verbatim in
        two simultaneously-loaded surfaces (skill body, reference, awareness
        primer, or the workspace router-profile snippet) without allowlisting
        it, `suppressible_bytes` goes non-zero here -- the failure names both
        surfaces so the fix is "move it to the surface that already owns it."
        """
        profile = cross_surface_duplicate_profile()
        self.assertEqual(
            profile["suppressible_bytes"],
            0,
            f"unallowlisted cross-surface duplicates found: {profile['duplicates']}",
        )
        # The one known, deliberate duplicate (delegation transparency rules,
        # commit ad62b9a1) stays allowlisted and accounted for. Its size moved
        # 2466 -> 2470 when #2018 reworded the permission preflight rule's
        # settings path so the Hermes install scanner stops reading it as a
        # shell redirect.
        self.assertEqual(profile["duplicate_count"], 1)
        # 2470 -> 2306 when the delegation prompt rule dropped its rationale tail (-82 per copy, two copies).
        self.assertEqual(profile["allowlisted_bytes"], 2306)
        self.assertEqual(profile["bytes_saved"], 0)
        self.assertEqual(
            profile["surface_kinds"],
            ["awareness_primer", "reference", "router_profile", "skill_body"],
        )

    def test_real_corpus_measurement_is_stable_across_two_runs(self) -> None:
        first = cross_surface_duplicate_profile()
        second = cross_surface_duplicate_profile()
        self.assertEqual(first, second)

    def test_assembled_surfaces_cover_expected_kinds_and_counts(self) -> None:
        from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates

        surfaces = assembled_surfaces_for_measurement()
        kinds = [surface.kind for surface in surfaces]
        self.assertEqual(kinds.count("awareness_primer"), 2)
        self.assertEqual(kinds.count("router_profile"), 1)
        self.assertEqual(kinds.count("skill_body"), len(builtin_skill_templates()))
        self.assertEqual(kinds.count("reference"), len(builtin_skill_reference_templates()))


if __name__ == "__main__":
    unittest.main()
