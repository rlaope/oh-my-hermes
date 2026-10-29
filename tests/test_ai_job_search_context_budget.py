"""Measured marginal cost of the complete career feature, not general budget slack.

Baseline: 245d34d7135ba0fba18afbf7f4151d5c4f6a5f37 (integration main).
Legacy body hashes match main's producer-derived digest fixture after restoring
only the research lane cardinality; integration-1/merged-measurements.json
records the combined repeated-byte measurement. The index pin retains its
original 85673e100 measurement; the capability and registry pins are re-derived
for the ru trigger pack's sibling-row triggers. Hashes pin existing
content, not just its size, so removing a safeguard cannot finance this feature.
"""
from __future__ import annotations

import hashlib
import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.capabilities.skills import skill_capabilities
from omh.maintenance import release
from omh.plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items
from omh.skills.context_cost import _skill_context_cost_profile, _split_sections
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.skills.skill_index import full_profile_skill_index_lines


# No optional career duplication was found in the aggregate failures: registry
# growth is the intact retrieval vocabulary + role membership; repeated growth
# is only the mandatory Workflow Lane and Runtime Evidence sections. Do not
# rename headings, truncate triggers, hide the skill or remove these rails.
FEATURE = 'ai-job-search'
INDEX_DELTA_CAP = 86  # One 85-character line and its joining newline.
FULL_ROW_DELTA_CAP = 3072  # One 3070-character JSON row + comma/space.
STANDALONE_ROW_DELTA_CAP = 935  # One 933-character row + comma/space.
REGISTRY_DELTA_CAP = 244  # 227-character trigger row + 17-character role entry.
REPEATED_DELTA_CAP = 1943  # Workflow Lane 497 + Runtime Evidence 1446.


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AiJobSearchContextBudgetTests(unittest.TestCase):
    def test_index_growth_is_only_the_new_visible_entry(self) -> None:
        lines = full_profile_skill_index_lines()
        added = [line for line in lines if line.startswith('    - omh-ai-job-search: ')]
        self.assertEqual(len(added), 1)
        legacy = [line for line in lines if line not in added]
        # 13157 -> 13241 and the digest re-derived: repro-audit adds its own
        # 84-character entry, which test_skill_context_cost pins.
        # Re-derived 2026-10-27: the sprite-forge skill adds one 84-character
        # index line (+85 with its newline); dropping only that line reproduces
        # the previous pin 08c0a6fc44b47bde948aee6ff427eb2e7312bffb627deeb31b32304747d754df / 13157.
        # Merged with main: 13241 + 85 = 13326 and the digest re-derived; dropping
        # the sprite-forge line reproduces main's cea493d3...aa33 / 13241.
        # Digest re-derived for show-reel's idea-video scope: its index line
        # now opens "Video to make from an idea..." at the same 57-character
        # cut, so the length stays 13326; restoring that one line reproduces
        # 7086c90b...06cd3.
        self.assertEqual(_digest(legacy), '4c6beb2acd99dc18299bdede1b94152ab846757057e8307bbe1c7bbb787e076e')
        self.assertEqual(len('\n'.join(legacy)), 13326)
        delta = len('\n'.join(lines)) - 13326
        self.assertGreater(delta, 0)
        self.assertLessEqual(delta, INDEX_DELTA_CAP)
        # A catalog ratchet is exact; do not carry the old row's unused slack.
        self.assertEqual(release.SKILL_INDEX_CHAR_LIMIT, len('\n'.join(lines)))

    def test_capability_growth_is_one_bounded_row_without_sibling_edits(self) -> None:
        # Re-derived 2026-10-27 from both producers. Full: the sprite-forge row
        # (+3174 with separator) plus deliverable-package's `archived, and
        # published` states (+21): 522307 -> 525502. Standalone: the sprite-forge
        # summary (+960): 141700 -> 142660. Dropping the sprite-forge row and
        # reverting that one description reproduces the previous digests
        # 774f8789...982a and a108c8d1...6e20.
        for producer, base, cap, expected_hash, limit in (
            # 522307 -> 522331 and the sibling digest re-derived: the pi-family
            # runtime rename moved four sibling rows by +6 each, and the
            # executor-runtime-readiness row's trigger count went +35 -> +34
            # when its runtime names became scoring-only (same length).
            # 522331 -> 522328 and the digest re-derived again for the
            # model-setup row refresh (-3); no other row moved.
            # Then the promo postmortem's visual-qa quality-bar rule grows that
            # sibling row: 522328 -> 523199.
            # 523199 -> 523243 and the digest re-derived: the ru trigger pack,
            # after its review, moves sibling rows' trigger previews and `+N more`
            # counts (itemized at FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); the
            # career row is unchanged.
            # 523243 -> 526233 and the digest re-derived: repro-audit adds one
            # row to each producer (+2990 full, +929 standalone).
            # 526233 -> 526234 and the digest re-derived: the show-reel
            # row's trigger count went +5 -> +13 (+1); no other row moved.
            # Merged with main: 526234 + 3195 (sprite-forge row and the
            # deliverable-package states) = 529429 and 142629 + 960 = 143589,
            # both digests re-derived from the producers on the merged tree.
            # The rendered-scene lane moves only the frontend row (same length).
            # 529429 -> 529669 and the digest re-derived: show-reel's idea-video
            # scope widens its row (+240, itemized at
            # FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); no other row moved.
            (skill_capabilities, 529669, FULL_ROW_DELTA_CAP,
             'd946e521363bf140d24edb97f2a769f4e0a2bc46f3921f45c67a386afc972173',
             release.FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT),
            (standalone_skill_capability_items, 143589, STANDALONE_ROW_DELTA_CAP,
             '7971eca9f1c5df22ac9edb2065bc66e967fed6471a7400c016d0beb166617476',
             release.STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT),
        ):
            with self.subTest(producer=producer.__name__):
                items = producer()
                rows = {str(row['id']): row for row in items}
                self.assertEqual(len(items), len(rows))
                self.assertIn(FEATURE, rows)
                added = rows.pop(FEATURE)
                self.assertEqual(_digest(rows), expected_hash)
                cost = len(json.dumps(added, sort_keys=True, ensure_ascii=False)) + 2
                self.assertLessEqual(cost, cap)
                measured = len(json.dumps(items, sort_keys=True, ensure_ascii=False))
                self.assertEqual(measured - base, cost)
                self.assertEqual(limit, measured)

    def test_registry_growth_preserves_all_existing_rows_and_trigger_coverage(self) -> None:
        registry = next(t.content for t in builtin_skill_reference_templates()
                        if t.skill_name == 'oh-my-hermes'
                        and t.relative_path == 'references/workflow-registry.md')
        lines = registry.splitlines(keepends=True)
        added = [line for line in lines if line.startswith('- `ai-job-search`:')]
        self.assertEqual(len(added), 1)
        self.assertEqual(len(added[0].encode()), 227)
        # Remove only the new row and the explicit operator membership token.
        legacy = [line.replace(', `ai-job-search`', '') for line in lines if line not in added]
        # Re-derived for the ru trigger pack: `running-work-board` gains
        # `что сейчас делается` and `dag-ulw` three Cyrillic triggers (+123 bytes).
        # The pack review replaces `что сейчас делается` with `что делают
        # агенты` (-4 bytes).
        # 32993 -> 33096 and the digest re-derived: repro-audit adds its
        # trigger row and its researcher membership (+103).
        # Re-derived 2026-10-27: the sprite-forge trigger row (205 bytes) and its
        # `, `sprite-forge`` operator token (+16): 32874 -> 33095. Removing only
        # those reproduces the previous pin 6c130e8ecad1e2ea6fada96a8f3b555b3b80f40d63ec64ea6872c1c49bf941e4.
        # Merged with main: 33096 + 221 = 33317 and the digest re-derived.
        self.assertEqual(_digest(legacy), '29ebe70fe2183974cd9c8d8ad9859f93d5e2ca3f3c442d3e81be2ddb635b7063')
        baseline = len(''.join(legacy).encode())
        self.assertEqual(baseline, 33317)
        # 33_100 -> 33_318: main's ru pack and repro-audit (+222 over 32874) used
        # the gate's room and sprite-forge adds its 221-byte row and token; each
        # side alone fit, the merged tree measures 33317. The gate stays exact.
        self.assertLess(baseline, 33_318)  # The existing content keeps its old gate.
        self.assertLessEqual(len(registry.encode()) - baseline, REGISTRY_DELTA_CAP)

    def test_repeated_growth_is_only_mandatory_rails_and_existing_bodies_survive(self) -> None:
        templates = builtin_skill_templates()
        refs = builtin_skill_reference_templates()
        feature = [t for t in templates if t.name == FEATURE]
        self.assertEqual(len(feature), 1)
        sections = dict(_split_sections(feature[0].content))
        self.assertEqual(len(sections['Workflow Lane']), 497)
        self.assertEqual(len(sections['Runtime Evidence']), 1446)
        self.assertLessEqual(len(feature[0].content.encode()), 5735)
        legacy_templates = [t for t in templates if t.name != FEATURE]
        legacy_hashes = {}
        for template in legacy_templates:
            parts = _split_sections(template.content)
            # The renderer changes only research lane cardinality +25 -> +26.
            # Reconstruct that one measured, same-length membership change.
            # The vi trigger rewording also moved five lane bodies, which is
            # why this digest is no longer the clean-base one.
            # repro-audit's own lane membership makes it +27 -> +26.
            restored = ''.join(body.replace('`+27 more`', '`+26 more`')
                               if heading == 'Workflow Lane' and '**Research and company ops**' in body
                               else body for heading, body in parts)
            legacy_hashes[template.name] = hashlib.sha256(restored.encode()).hexdigest()
        # Re-derived from both sources: the vi rewordings above plus
        # model-setup's nine Kimi K3 -> Kimi K3.1 Pro mentions on main.
        # Re-derived from both main sources above plus the bounded dag-ulw
        # baseline-verification guidance, then the pi-family runtime rename in
        # model-setup, maestro, ultrawork, and executor-runtime-readiness.
        # Re-derived again for the model-setup body refresh (retired provider
        # and role-slot wording); only model-setup moves versus main.
        # Then the promo postmortem in content-operator, design-quality-gate,
        # show-reel, and visual-qa.
        # Re-derived for the ru trigger pack: the 49 bodies it covers gain
        # Cyrillic phrases on their routing-signal line; repeated bytes do not move.
        # Re-derived again for repro-audit: its own body joins the legacy set
        # (and again for its review's confirmation-wording fix).
        # Re-derived 2026-10-27: the new sprite-forge body plus the visual-qa /
        # show-reel / deliverable-package reinforcement rails, which move 15
        # sibling bodies; HEAD c532cd5c4 reproduces the previous pin
        # 5db03a78a37d515ad0f54df6fd2eab2533b9f80c800aed8619a9debd78bce9b3.
        # Re-derived again on the tree merged with main (both sides' bodies).
        # Then the rendered-scene lane in frontend and visual-qa; on the merged
        # tree both sides' bodies (tests/fixtures/agent_skills_hermes_digests.json).
        # Re-derived for the human-voice pass: the router body gains one
        # Progressive Disclosure pointer to `references/human-voice.md`;
        # removing that line alone restores main's digest (db2c9bd4...).
        # Re-derived for the plan-ambition lines: only plan and ralplan move.
        # Re-derived again on the tree merged with sprite-forge (both sides' bodies).
        # Then dag-ulw's delegation-backend guidance; only dag-ulw moves.
        # Then model-setup's chain sentence names the six routing-recipe
        # categories (2026-10-28); only model-setup moves.
        # Then model-setup names Gemini 4 Argon where it named Gemini 3.1 Pro
        # and lists 3.1 Pro as superseded (2026-10-28); reverting only that
        # edit reproduces the previous pin 48d98811b4a4c7ceea14d1b5995065c37420b6c46b1e16bb4b3081906cbc07d3.
        # Then show-reel's idea-video lane (its Idea Videos section and the
        # bundled `manim-video`/`ascii-video` boundary); only show-reel moves,
        # and reverting it reproduces c68f1cca2df78a15c4822345f421b1aab01c43d8f4ae0944accb41065bef384c.
        self.assertEqual(_digest(legacy_hashes), 'd95a932bee5465e280ea09653a5f741813f0dcadf0fa17f6e76dddfc45789a72')
        legacy = _skill_context_cost_profile('full', legacy_templates, refs)
        current = _skill_context_cost_profile('full', templates, refs)
        # Main's search guidance adds 305; repro-audit's mandatory rails 1,943.
        # Main's search guidance adds 305. 124650 -> 126657: sprite-forge's
        # mandatory Workflow Lane (519) + Runtime Evidence (1446) = 1965, plus
        # 42 bytes of sibling reinforcement rails (+2007).
        # Merged with main: 126593 + 2007 = 128600, re-derived from the producer.
        self.assertEqual(legacy['repeated']['bytes'], 128600)
        delta = current['repeated']['bytes'] - legacy['repeated']['bytes']
        self.assertEqual(delta, len(sections['Workflow Lane']) + len(sections['Runtime Evidence']))
        self.assertLessEqual(delta, REPEATED_DELTA_CAP)
        # 126,000 -> 127,943: repro-audit's 1,943 rails, bounded by its own test.
        # 126_000 -> 128_007: the same measured +2007 as above; no new headroom.
        # Merged with main: 126,000 + 1,943 + 2,007 = 129,950.
        self.assertLess(current['repeated']['bytes'] - REPEATED_DELTA_CAP, 129_950)
        feature_refs = [t for t in refs if t.skill_name == FEATURE]
        self.assertEqual(len(feature_refs), 6)
        self.assertLessEqual(sum(len(t.content.encode()) for t in feature_refs), 19397)
        self.assertLessEqual(max(len(t.content.encode()) for t in feature_refs), 4039)

    def test_hard_per_item_schema_and_injection_limits_do_not_move(self) -> None:
        # Career growth moves only the three catalog-total ratchets. Later
        # schema changes keep their own measured marginal caps; parked waits
        # are covered by test_per_turn_budgets, not funded from career slack.
        from omh.maintenance.drift import budget_metrics
        expected = {
            'skill_index_line_max_chars': 100,
            'plugin_tool_schema_chars': 71831,  # Parked DAG waits (+429), delegation backends (+245), six routing-recipe categories (+213), opt-in omh-lsp tools (+2187).
            'pre_llm_call_context_chars_max': 5632,  # The pi-family runtime rename (+6), then the route-hint dedup (-154).
            'pre_llm_call_context_fallback_chars_max': 7184,  # The same rename (+6), the human-voice primer sentence (+116), then the route-hint dedup (-154).
            'awareness_primer_markdown_chars': 3630,  # Human-voice reply sentence (+110).
            'awareness_primer_context_chars': 1560,  # The same sentence (+120).
            'awareness_workflow_context_chars_max': 1500,
            'role_context_chars_max': 2600,
            'full_capability_skill_item_chars_max': 9000,
            'standalone_capability_skill_item_chars_max': 2200,
            'full_profile_skill_body_chars': 1500000,
            'full_profile_skill_body_repeated_chars': 140000,
            'skill_density_filler_hits': 0,
        }
        metrics = {m.name: m for m in budget_metrics()}
        for name, limit in expected.items():
            with self.subTest(metric=name):
                self.assertEqual(metrics[name].limit, limit)
                self.assertLessEqual(metrics[name].live(), limit)


if __name__ == '__main__':
    unittest.main()
