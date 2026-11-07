from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.quality.skill_density import (  # noqa: E402
    COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT,
    DENSITY_FILLER_HIT_CEILING,
    DENSITY_PAYLOAD_MARKERS_PER_1K_FLOOR,
    DENSITY_REPEATED_SHARE_CEILING_PERCENT,
    DENSITY_REVIEWED_EXEMPTIONS,
    SKILL_DENSITY_RULE_IDS,
    SKILL_DENSITY_SCHEMA_VERSION,
    compression_verdict,
    format_skill_density_violations,
    instruction_prose,
    measure_skill_density,
    skill_density_measurements,
    skill_density_payload,
    skill_density_violations,
    trigger_surface,
)
from omh.skills.packaging import builtin_skill_templates  # noqa: E402


class SkillDensityGateTests(unittest.TestCase):
    """Standing density gate for the always-loaded skill bodies.

    `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` (src/maintenance/release.py) bounds
    the pack's total bytes. It cannot separate a body that grew because a
    workflow gained a rule from one that grew because the prose got wordier.
    This gate measures the second thing per skill.

    Measured distribution over all 108 catalog skills at the time these
    thresholds were set (`omh.quality.skill_density.skill_density_payload()`):

    | signal | min | median | max |
    | --- | --- | --- | --- |
    | `filler_hits` | 0 | 0 | 0 |
    | `repeated_share_percent` | 0.0 | 0.0 | 0.0 |
    | `payload_markers_per_1k` | 10.03 | 13.17 | 21.3 |

    Thresholds follow from those three rows:

    - Filler ceiling 0. The corpus carries zero hits from the reviewed phrase
      list today, so the gate is a ratchet on a clean corpus rather than a
      cleanup target. A non-zero tolerance here would only buy the first
      author who wants one.
    - Repeated-share ceiling 5.0%. Intra-skill repetition is also zero today,
      but the ceiling is deliberately not 0: repeating the single most
      important rule at the end of a long body is a positioning decision, not
      bloat, and a hard zero would forbid it. 5.0% leaves room for exactly one
      such repeat in a median-length body while still failing a section
      pasted twice.
    - Payload floor 9.0 markers per 1,000 prose chars, about 10% below the
      measured worst legitimate case (`llm-app-dev`, 10.03 -- the largest body
      with the most narrative framing). Set at today's worst it would fail on
      the next rounding; set at the median it would fail a third of the
      catalog for style. Now 7.9 by the same rule (`meeting-brief`, 8.79): the
      lane line's sample of sibling names had been counted as payload.

    Nothing is exempted: `DENSITY_REVIEWED_EXEMPTIONS` is empty and the gate
    passes on today's corpus.
    """

    def test_catalog_passes_the_density_gate(self) -> None:
        violations = skill_density_violations()
        self.assertEqual(violations, [], format_skill_density_violations(violations))

    def test_no_skill_is_silently_exempted(self) -> None:
        self.assertEqual(DENSITY_REVIEWED_EXEMPTIONS, {})
        catalog = {template.name for template in builtin_skill_templates()}
        for skill, reason in DENSITY_REVIEWED_EXEMPTIONS.items():
            with self.subTest(skill=skill):
                self.assertIn(skill, catalog)
                self.assertTrue(reason.strip(), "an exemption without a reason is a silent skip")

    def test_measured_distribution_still_matches_the_recorded_thresholds(self) -> None:
        """The thresholds are only defensible while the distribution behind them holds."""
        payload = skill_density_payload()
        self.assertEqual(payload["schema_version"], SKILL_DENSITY_SCHEMA_VERSION)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["skill_count"], len(builtin_skill_templates()))
        self.assertEqual(list(payload["rules"]), sorted(SKILL_DENSITY_RULE_IDS))

        distribution = payload["distribution"]
        self.assertEqual(distribution["filler_hits"]["max"], 0.0)
        self.assertEqual(distribution["repeated_share_percent"]["max"], 0.0)
        # Headroom, not a second ratchet: the floor stays meaningfully under the
        # worst measured body and the median stays well clear of the floor.
        self.assertGreater(distribution["payload_markers_per_1k"]["min"], DENSITY_PAYLOAD_MARKERS_PER_1K_FLOOR)
        self.assertGreater(distribution["payload_markers_per_1k"]["median"], 12.0)

    def test_failure_message_names_skill_value_threshold_and_excerpt(self) -> None:
        wordy = (
            '---\nname: "omh-demo"\ndescription: "[omh] demo"\n---\n\n'
            "# Demo\n\n"
            "In order to run the workflow the operator opens the workflow and then the "
            "workflow proceeds through the workflow stages of the workflow run.\n"
        )
        measurement = measure_skill_density("demo", wordy)
        violations = skill_density_violations([measurement])
        rules = {str(finding["rule"]) for finding in violations}
        self.assertIn("SKILL_DENSITY_FILLER", rules)
        self.assertIn("SKILL_DENSITY_PAYLOAD_FLOOR", rules)

        message = format_skill_density_violations(violations)
        self.assertIn("demo", message)
        self.assertIn("SKILL_DENSITY_FILLER", message)
        self.assertIn(f"threshold {DENSITY_FILLER_HIT_CEILING}", message)
        self.assertIn("In order to run the workflow", message)
        self.assertIn("src/quality/skill_density.py", message)
        self.assertIn("docs/ADDING-A-SKILL.md", message)

    def test_repeated_content_rule_fires_on_a_body_that_repeats_itself(self) -> None:
        sentence = "Record the accepted decision before any executor handoff is prepared."
        body = "---\nname: \"omh-demo\"\n---\n\n# Demo\n\n" + "\n\n".join([sentence] * 4) + "\n"
        measurement = measure_skill_density("demo", body)
        self.assertGreater(measurement.repeated_share_percent, DENSITY_REPEATED_SHARE_CEILING_PERCENT)
        rules = {str(finding["rule"]) for finding in skill_density_violations([measurement])}
        self.assertIn("SKILL_DENSITY_REPEATED_CONTENT", rules)


class TriggerSurfaceIsNotCompressibleTests(unittest.TestCase):
    """The description and routing signals are matched against user phrasing.

    `src/routing/` reads catalog triggers, so keyword-redundant alternatives are
    payload on the retrieval surface even where a human reader needs one. The
    density measurement must therefore never see them, or a wide trigger list
    would read as repetition and pressure an author to trim routing coverage.
    """

    def test_prose_excludes_frontmatter_and_routing_signals(self) -> None:
        template = next(item for item in builtin_skill_templates() if item.name == "plan")
        prose = instruction_prose(template.content)
        self.assertNotIn("Strong routing signals:", prose)
        self.assertNotIn("description:", prose)
        self.assertIn("Completion Checklist", prose)

        surface = trigger_surface(template.content)
        self.assertIn("Strong routing signals:", surface)
        self.assertIn("`implementation plan`", surface)


class CompressionDeltaGateTests(unittest.TestCase):
    """The gate that can say "stop" to a compression pass.

    A rewrite is only worth its re-review when it wins real tokens and loses
    nothing. Three refusals: an under-threshold delta, a touched trigger, and a
    dropped never-delete claim.
    """

    ORIGINAL = (
        '---\nname: "omh-demo"\ndescription: "[omh] demo. Use when the user says: demo, demo run."\n---\n\n'
        "# Demo\n\n"
        "The run must stop after 3 failed attempts and never reports prepared work as observed.\n"
        "Pass `--limit 3` when the batch exceeds the default.\n"
        "If the batch is empty, say so and stop instead of writing an empty report.\n"
        "Record the stop reason in the run summary before handing back to the caller.\n"
    )

    def test_small_delta_keeps_the_original(self) -> None:
        trimmed = self.ORIGINAL.replace("exceeds the default", "exceeds default")
        verdict = compression_verdict("demo", self.ORIGINAL, trimmed)
        self.assertEqual(verdict["verdict"], "keep_original")
        self.assertLess(verdict["delta_percent"], COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT)
        self.assertEqual(verdict["dropped_payload"], [])
        self.assertIn("under the", " ".join(verdict["reasons"]))

    def test_dropped_payload_is_named_not_counted(self) -> None:
        lossy = (
            '---\nname: "omh-demo"\ndescription: "[omh] demo. Use when the user says: demo, demo run."\n---\n\n'
            "# Demo\n\nThe run stops after failures.\n"
        )
        verdict = compression_verdict("demo", self.ORIGINAL, lossy)
        self.assertEqual(verdict["verdict"], "keep_original")
        self.assertGreater(verdict["delta_percent"], COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT)
        self.assertIn("modal:must", verdict["dropped_payload"])
        self.assertIn("modal:never", verdict["dropped_payload"])
        self.assertIn("exact_string:`--limit 3`", verdict["dropped_payload"])
        self.assertFalse(verdict["trigger_changed"])

    def test_touching_the_trigger_keeps_the_original(self) -> None:
        retriggered = self.ORIGINAL.replace(", demo run.", ".")
        verdict = compression_verdict("demo", self.ORIGINAL, retriggered)
        self.assertEqual(verdict["verdict"], "keep_original")
        self.assertTrue(verdict["trigger_changed"])
        self.assertIn("the trigger never does", " ".join(verdict["reasons"]))

    def test_a_real_win_that_loses_nothing_is_accepted(self) -> None:
        original = (
            '---\nname: "omh-demo"\ndescription: "[omh] demo."\n---\n\n'
            "# Demo\n\n"
            "It is important to note that, in order to keep things consistent across the board, "
            "and basically as you can see, at the end of the day the run must stop after 3 failed "
            "attempts, and with regard to prepared work, needless to say, it should be noted that "
            "prepared work is never reported as observed.\n"
        )
        tightened = (
            '---\nname: "omh-demo"\ndescription: "[omh] demo."\n---\n\n'
            "# Demo\n\n"
            "The run must stop after 3 failed attempts. Prepared work is never reported as "
            "observed.\n"
        )
        verdict = compression_verdict("demo", original, tightened)
        self.assertEqual(verdict["verdict"], "accept_draft")
        self.assertEqual(verdict["dropped_payload"], [])
        self.assertGreater(verdict["delta_percent"], COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT)
        self.assertGreater(
            verdict["after"]["payload_markers_per_1k"], verdict["before"]["payload_markers_per_1k"]
        )


class DensityMeasurementSourceTests(unittest.TestCase):
    def test_measurement_reads_the_catalog_producer_not_the_committed_files(self) -> None:
        """The generated `skills/*/SKILL.md` copies can be stale; the producer cannot."""
        measurements = {item.skill: item for item in skill_density_measurements()}
        self.assertEqual(set(measurements), {item.name for item in builtin_skill_templates()})
        for template in builtin_skill_templates():
            with self.subTest(skill=template.name):
                self.assertEqual(
                    measurements[template.name].prose_chars,
                    len(instruction_prose(template.content)),
                )


if __name__ == "__main__":
    unittest.main()
