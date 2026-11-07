from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.skills.context_cost import skill_context_cost_payload, skill_context_cost_profile


class SkillContextCostTests(unittest.TestCase):
    def test_full_profile_moves_common_rails_out_of_skill_bodies(self) -> None:
        profile = skill_context_cost_profile("full")
        headings = {row["heading"]: row for row in profile["headings"]}

        self.assertEqual(headings.get("OMH Context Rail", {"duplicate_bytes": 0})["duplicate_bytes"], 0)
        self.assertEqual(
            headings.get("Hermes Compatibility Contract", {"duplicate_bytes": 0})["duplicate_bytes"],
            0,
        )
        # 100,000 -> 104,000: the reply rule (the user's words, the host's
        # voice, record terms stay in records, a stop offers the next action)
        # is read at the moment the reply is written, so it rides every body's
        # tail on purpose; the substitution table stays in the rail. Repeated
        # bytes measure 101,024 with it. Warranted always-loaded growth.
        # 104,000 -> 107,000: the six `jev-*` bodies each carry the lines
        # every workflow body must (the reply rule, completion checklist,
        # fallback contract, lane footer), taking repeated bytes to 104,214;
        # their shared Jev rules live once in `jev-rail.md` instead.
        # 107,000 -> 111,000: `app-debugging`, `commit-pr-authoring`,
        # `git-workflow`, and `relational-db` (#1709, #1711, #1695, #1692)
        # each join the coding_handoff lane, whose `Workflow Lane` line is
        # stamped into every lane body, and the two without a declared harness
        # carry the shared `Runtime Evidence` section verbatim, as 14 skills
        # already do. Repeated bytes measure 107,916 with the first three and
        # 108,400 with all four; ~2.4% headroom kept.
        # 111,000 -> 114,000: `iac-change` (#1566) joins the same lane, whose
        # member list is stamped into every lane body; with `release-cut` and
        # `agent-instructions` already there, repeated bytes measure 111,136.
        # ~2.5% headroom kept.
        # 114,000 -> 121,000: the tail reply rule now names what the persona
        # owns (reply language, tone, speech level, endings, progress
        # updates) and the user's language as the fallback, on every body;
        # repeated bytes measure 117,742. ~2.7% headroom kept.
        # Three science methods carry their lane/evidence rails: 122343
        # producer bytes. 126000 retains approximately 3% headroom; toolkit
        # bytes remain on-demand and do not enter this measurement.
        # 126,000 -> 127,943: clean 85673e100 measures 124,345; adding the
        # career method measures 126,288. The exact +1,943 is only mandatory
        # Workflow Lane (497) and Runtime Evidence (1,446), not copied optional
        # method text. Preserve the old allowance (1,655 bytes), rather than
        # expanding to the roughly 3% headroom prior entries permitted.
        # The feature-cost regression pins legacy body bytes, bounds these
        # two sections and also enforces (current - 1,943) < 126,000.
        # 127,943 -> 129,886: main measures 126,593; repro-audit's mandatory
        # Workflow Lane and Runtime Evidence rails measure +1,943 (128,536).
        # The old allowance (1,350 bytes) is preserved, not widened; the
        # increment and body caps below bound the audit itself.
        # 127,943 -> 129,950: HEAD c532cd5c4 measures 126,593; adding sprite-forge
        # and the visual-qa/show-reel/deliverable-package rails measures 128,600.
        # The exact +2,007 is sprite-forge's mandatory Workflow Lane (519) and
        # Runtime Evidence (1,446) plus 42 sibling rail bytes. The old allowance
        # (1,350 bytes) is preserved, not widened.
        # Merged with main: 126,593 + 1,943 + 2,007 = 130,543 measured, plus the
        # same 1,350 allowance = 131,893.
        # 131,893 -> 133,335: the tree now measures 131,985 with systematic-review's
        # mandatory Workflow Lane (497) and Runtime Evidence (1,446) rails (+1,943
        # over 130,042); the same 1,350 allowance is kept, not widened.
        self.assertLess(profile["repeated"]["bytes"], 133_335)

    def test_repro_audit_context_increment_stays_bounded(self) -> None:
        from omh.skills.context_cost import _skill_context_cost_profile
        from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates

        templates = builtin_skill_templates()
        references = builtin_skill_reference_templates()
        full = _skill_context_cost_profile("full", templates, references)
        without = _skill_context_cost_profile(
            "full", [template for template in templates if template.name != "repro-audit"], references
        )
        audit = next(template for template in templates if template.name == "repro-audit")
        increment = full["repeated"]["bytes"] - without["repeated"]["bytes"]
        self.assertGreaterEqual(increment, 0)
        self.assertLessEqual(increment, 2_000)
        self.assertLessEqual(len(audit.content.encode("utf-8")), 8_000)

    def test_ulw_context_reports_bounded_static_body_and_progressive_references(self) -> None:
        payload = skill_context_cost_payload()

        self.assertEqual(payload["schema_version"], "omh_skill_context_cost/v1")
        context = payload["catalog_increment"]["ulw-context"]
        self.assertGreater(context["skill_body_bytes"], 0)
        self.assertGreater(context["reference_bytes"], 0)
        self.assertEqual(context["reference_file_count"], 2)
        self.assertEqual(context["project_specific_bytes"], 0)
        self.assertTrue(context["ceilings_pass"])
        self.assertLessEqual(context["skill_body_bytes"], context["ceilings"]["skill_body_bytes"])
        self.assertLessEqual(context["reference_bytes"], context["ceilings"]["reference_bytes"])

        serialized = str(payload).casefold()
        self.assertNotIn("dispatch packet", serialized)
        self.assertNotIn("핸드오프", serialized)

    def test_search_guidance_keeps_nested_fields_progressive_without_index_growth(self) -> None:
        from omh.skills.skill_index import skill_index_chars
        from omh.skills.skill_record import skill_record

        # Pre-feature producer measurements, not token/latency estimates. This
        # feature changes opening actions only, never indexed descriptions.
        # Career adds its bounded 86-character entry; repro-audit its 84-character one;
        # sprite-forge its line + newline (13,243 -> 13,328); merged with main's
        # repro-audit line, 13,327 + 85 = 13,412; systematic-review its line +
        # newline (+90).
        self.assertEqual(skill_index_chars(), 13_502)
        # research and web-research add the shipped `ru` trigger pack's routing
        # signals (+446 and +316 bytes, after its review dropped the everyday
        # and nested phrases) to their pre-feature bodies; the search guidance
        # increment itself (286 and 305) is unchanged. The citation receipts rule
        # (`omh research receipts verify`, 262 bytes) joins both bodies.
        # research's entity-match clause (answer only from a source on the exact
        # named entity; a different name is a different entity) adds 222 bytes.
        # The render rail writes `research` as `ulw-research` and the like in these
        # bodies. Each pin moved by the body's measured growth against main
        # (research +3, web-research +7, source-finder +19), plus the research-lane fixes'
        # own lines (web-research +181, source-finder +169), not by a figure chosen to fit the cap; the increment above stays the feature's own.
        # 20,520 -> 20,902: `research` takes defaults when no human can answer its opening questions
        # (+382, not search guidance).
        baseline = {'research': 20_902, 'web-research': 12_261, 'source-finder': 9_409}
        for name, before in baseline.items():
            record = skill_record(name)
            body = record.body().content
            increment = len(body.encode('utf-8')) - before
            with self.subTest(name=name):
                self.assertGreater(increment, 0)
                self.assertLessEqual(increment, 320)
                self.assertNotIn('"$defs"', body)
                references = [ref for ref in record.references() if '/search-' in ref.relative_path]
                self.assertEqual(len(references), 3)
                self.assertLessEqual(sum(len(ref.content.encode('utf-8')) for ref in references), 70_000)


if __name__ == "__main__":
    unittest.main()
