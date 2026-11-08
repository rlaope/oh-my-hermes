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
        # Digest re-derived for architecture deepening: tech-debt-audit's index
        # line now opens "Accumulated tech debt or architecture deepening..."
        # at the same cut, so the length stays; restoring that one line
        # reproduces 4c6beb2a...076e.
        # 13326 -> 13416 and the digest re-derived: systematic-review adds one
        # index line (+90 with its newline); dropping only that line reproduces
        # 61fb0902...f7f9b / 13326.
        self.assertEqual(_digest(legacy), '4b82ff50629ea1e2db50d5994ab8bc0f65094b9e432f0f5c91aed98b046d5ca5')
        self.assertEqual(len('\n'.join(legacy)), 13416)
        delta = len('\n'.join(lines)) - 13416
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
            # Digest re-derived, length unchanged: rules-distill's destination
            # input names a check (same 85 characters) and its candidate-set
            # expectation names the class (past the preview cut); only that row
            # moves, and main's producer gives the previous pin d946e521...2173.
            # 529669 -> 529956 and the digest re-derived: the app-debugging row
            # gains its record and redaction lines (+287, #2499); no other row
            # moved, and main's producer gives the previous digest d946e521...2173.
            # Merged with #2499 after #2497: both rows' changes; the digest is re-derived from
            # the producer (#2497's pin before the merge was 2c6ea588...fdd3, #2499's 509aec41...ecd8).
                        # 529669 -> 530006 and the digest re-derived: the llm-app-dev
            # (+307) and rust (+30) quality-bar lines (#2498, itemized at
            # FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT). Merged with #2499 and #2497: both sides'
            # rows; the base and digest are re-derived from the producer (#2498's pin before the
            # merge was c409741a...73ca at 530006, #2497's 2f644f53...ec43 at 529956).
            # Architecture deepening (#2501) widens the refactor-plan row (+136) and the
            # tech-debt-audit row (-2), itemized at FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT; its
            # review moves the tech-debt-audit "+N more triggers" count (same length). Merged with
            # main: base and digest re-derived from the producer (#2501's pin before the merge was
            # b073f4fb...eda7 at 529803, main's 83828030...e82a at 530293).
            # #2501's second review moves only tech-debt-audit's "+N more triggers"
            # count (same length); the digest before it was 3a45e62c...32d7.
            # 530427 -> 530439 and the digest re-derived: ralplan's node-prompt line names
            # `dag-ulw` nodes beside `ultrawork` board rows (+12, itemized at
            # FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); no other row moved, and the pin
            # before it was 93de88ac...c1c0.
            # 530439 -> 530686 and the digest re-derived: dag-ulw's category-ladder line sends a
            # `role=review` node to `review`, keeps `role=baseline` low and has `role=verify` climb
            # the ladder (+247, itemized at FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); no other row moved, and
            # the pin before it was b8552607...5e6b.
            # 530686 -> 533897 and 143589 -> 144536: systematic-review adds one row to each
            # producer (+3211 full, +947 standalone); dropping only that row reproduces
            # 2cb9a1ff...ca80 and 7971eca9...7617.
            # 533897 -> 533907 and the digest re-derived: the dag-ulw row's handoff policy
            # names choosing an owner by naming it in a dag-ulw request and the per-owner
            # `exports` list (+10); no other row moved, and the pin before it was e6484100...d8b.
            # Digest re-derived, length unchanged: meta-router's shortlist line names the
            # catalog index as a `skill_view` call into omh-routing (the file is not its
            # own), which moves that row past the preview cut; no other row moved, and the
            # pin before it was ad1e9c0a...4aa5.
            # 533907 -> 536196 and the digest re-derived: the skill audit round's rows, +2,289
            # (itemized by lane at FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); the sum of the lanes'
            # readings is exact on the merged tree, and the pin before it was d6dfefff...fc71.
            # 536196 -> 537857 and the digest re-derived: the code-quality skills fix round, +1,661 on the merged
            # tree (itemized at FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); the pin before it was a5d1c988...3e03.
            # 537857 -> 537954 and the digest re-derived: the cross-lane rail fix writes sibling hand-offs in
            # backticks or as labels in the rows that carry them (itemized at
            # FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT); the pin before it was 41011a72...3bc7.
            # 537954 -> 537829 and the digest re-derived: the routing reach round, -125 (itemized at the same
            # limit); the pin before it was b1ad64a5...590b.
            (skill_capabilities, 537829, FULL_ROW_DELTA_CAP,
             'c5c17f8447a21a90f56652c76ca61560d12e987acf34f9d459d418765e562eb0',
             release.FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT),
            (standalone_skill_capability_items, 144536, STANDALONE_ROW_DELTA_CAP,
             '5f2c0396e3f9971d0389191a3f175f5d9232463eb5e4436eaae709fa32052d48',
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
        # 33317 -> 33593 and the digest re-derived: the systematic-review
        # trigger row (255 bytes) and its researcher token (+21); removing
        # only those reproduces 29ebe70f...7063.
        # Digest re-derived for the reach round: the registry rows of the triggers it drops.
        self.assertEqual(_digest(legacy), 'd32edf2216a679aa88fdffccdd9564a44443ea1336b663c24b8ae373e8634ea5')
        baseline = len(''.join(legacy).encode())
        self.assertEqual(baseline, 33564)
        # 33_100 -> 33_318: main's ru pack and repro-audit (+222 over 32874) used
        # the gate's room and sprite-forge adds its 221-byte row and token; each
        # side alone fit, the merged tree measures 33317. The gate stays exact.
        # 33_318 -> 33_594: systematic-review's 276 bytes; the gate stays exact.
        self.assertLess(baseline, 33_594)  # The existing content keeps its old gate.
        self.assertLessEqual(len(registry.encode()) - baseline, REGISTRY_DELTA_CAP)

    def test_repeated_growth_is_only_mandatory_rails_and_existing_bodies_survive(self) -> None:
        templates = builtin_skill_templates()
        refs = builtin_skill_reference_templates()
        feature = [t for t in templates if t.name == FEATURE]
        self.assertEqual(len(feature), 1)
        sections = dict(_split_sections(feature[0].content))
        # 497 -> 496: the hand-back line names the router by its loadable label,
        # `omh-routing`, one character shorter than `oh-my-hermes`.
        # 496 -> 341: the lane line drops its sample of member names, which did not load.
        self.assertEqual(len(sections['Workflow Lane']), 341)
        self.assertEqual(len(sections['Runtime Evidence']), 1446)
        self.assertLessEqual(len(feature[0].content.encode()), 5735)
        legacy_templates = [t for t in templates if t.name != FEATURE]
        legacy_hashes = {}
        for template in legacy_templates:
            # The lane line no longer carries a member count, so a new skill moves no sibling body.
            restored = ''.join(body for _heading, body in _split_sections(template.content))
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
        # Then frontend's observe-each-change quality-bar line; only frontend moves.
        # Then visual-qa's playable-check quality-bar line; only visual-qa moves, and its portable shadow pin is re-read.
        # Then show-reel's kinetic-type lane pointer (one opening-step line);
        # only show-reel moves, and main's producer gives the previous pin
        # 40cbc6d62e8eed6bf90ff03c3362ecf8bb6030ca055ceddc11150752cd84987f.
        # Then agent-debug's report line names silent turn ends and the
        # agent.log turn-exit read; only agent-debug moves, and main's
        # producer gives the previous pin
        # dea773e27e735e108611c1fe72c593375d3f70d89a79e0d3cd89bdef8b1f65e4.
        # Then plan's task shape and closing gate, and the shared follow-on
        # rule's `dag-ulw` clause; only plan and ralplan move, and main's
        # producer gives the previous pin
        # 19b756e55d0c861edce77c0d7c556a4aaa2bbfcc0104a691a3562ebb0bc0cbe9.
        # The review round (direct-edge write rule, dag-ulw conversion
        # wording, verification-task name) moves plan only.
        # Then dag-ulw names the node `role` field and reports the goal met only
        # on `verdict: verified`, and plan's closing gate becomes a `role: verify`
        # node in dag-ulw (Hermes projection only); only dag-ulw and plan move,
        # and main's producer gives the previous pin
        # 0e66028d94805874a359b8f53b05a866f8fb539893e78a615d09e83f8b0d9f77.
        # Then plan's done check is a command with the result that counts as passing, for a code task;
        # only plan moves, and main's producer gives the previous pin
        # 2f7f10cca0591d057e137b6a697cee02a77858695561d57043b0e26ed592b27c.
        # #2488 adds the short-promo line to show-reel's idea lane (only
        # show-reel moves); main's pin before it is
        # 52744725ec2b2ef602498d2da43ad02733857604efb0e28ea6686aa99e43f44c.
        # #2502 adds frontend's state-discipline, forms-and-input and
        # browser-support lines and frontend-refactor's visual-parity clause;
        # only frontend and frontend-refactor move, and main's producer gives
        # the previous pin
        # ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # Its second review round (dialog Escape under closedby="none", the
        # close-watcher wording, the support-target wording) moves frontend
        # only; the round before gives
        # 99bdb5f2edb3a7fd2f2f79dd3b2f9fb96c9a8ee5b560b05f837fbc6b27fc0f84.
        # Then plan's vertical-slice line and checklist item, and
        # decision-prototype's artifact-shapes pointer (body and quality bar);
        # only plan and decision-prototype move, and main's producer gives the
        # previous pin ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # The #2503 review round (the refactor-plan handoff named by its real
        # shape, every earlier same-file slice as a direct dependency, the
        # append-only file task, and the checklist matching the bar) moves
        # plan only; the round's first commit gives the previous pin
        # f0f941b8604a5e4680dad6819edb593cf59048d03d84c4567279dfad8908bf42.
        # Merged with main after #2502: both sides' bodies; main's pin before the
        # merge was e498851bd607d40942631386858a10c1ed1ea5ea8e3a17a033b866d2c1bbe956.
        # #2499 adds the debugging-record and regression-witness lines; only
        # app-debugging, native-debugging and verification-gate move, and
        # main's producer gives the previous pin
        # ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # Merged with #2503's branch: both sides' bodies; #2503's pin before the merge was
        # e352ad0c1c3d64e7f0fa179df5e11f9637816c2f628a2dd2d6434efb2566b230.
        # Then code-review's standards-discovery loader line and the own-output
        # checklists of codebase-onboarding and rules-distill; only those three
        # move, and main's producer gives the previous pin
        # ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # Merged with #2499's branch (carrying #2503): both sides' bodies; the pin before the merge was
        # 48c0ed82d69ebd2b692ed81fd74666257858f4e86a7ac384dabe8c685605f242.
        # #2498 adds the fake-adapter, stop-reason, and tool-argument rules to
        # llm-app-dev and names rust's binary and dependency sections; only
        # llm-app-dev and rust move, and main's producer gives the previous pin
        # ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # Merged with #2497's branch (carrying #2503, #2499): both sides' bodies; the pin before the merge was
        # 18d2ace67bd082ee6a0acef68039dec1aafb0b3dc9f7590a08c26118436755db.
        # Then backend's integrity and inbound-delivery quality-bar lines and
        # relational-db's concurrency and non-transactional-DDL lines; only
        # backend and relational-db move, and main's pin before it is
        # ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # Its review round (webhook receipt vs job transaction, the cursor
        # sections pointer) moves backend only.
        # Then backend, frontend, and app-debugging each gain one line loading
        # the shared test-authoring reference, and app-debugging's fix_handoff
        # gains the no-correct-seam expectation; only those three move, and
        # main's producer gives the previous pin
        # ede9f8f6bb352088bc25f14db195f47fd71070f98cd14cc2a18569b19296637b.
        # Its review round lets a none_correct regression seam pass
        # app-debugging's fix_handoff line and checklist, and names frontend's
        # fakes by the shared page's boundaries; only app-debugging and
        # frontend move again.
        # Then architecture deepening (#2501): only tech-debt-audit and
        # refactor-plan move, and main's producer gives the previous pin
        # e498851bd607d40942631386858a10c1ed1ea5ea8e3a17a033b866d2c1bbe956.
        # Merged with main after #2506 (the whole chain): both sides' bodies; main's pin before the merge was
        # 491fb471be66fac6154ef944b02563994a1ed46fbc59a89b79243c24d941fdff.
        # #2501's second review cuts tech-debt-audit's phrases to four and the
        # Korean ones to their request forms; only that body's routing-signal
        # line moves, and the pin before it was 81f862a9...97f5.
        # Merged with main after #2509: show-reel's launch-film lane pointer moves show-reel
        # only; main's pin before the merge was 8f5163156f133106895decf6e2a78fccd53eccc614e2e1025c86cfc0e3dee37a
        # and #2501's was 7a5aacd754cae58c4ef6c53739768abc1f4a323f0f53aaebd9e704b3b0d9ba1e.
        # omh/code-skills-round-followups: plan's append-only-file line and
        # verification-gate's none_correct clause move those two bodies only;
        # main's pin before it was fac0aeb1db64b01df8b9c2ed35c1e15c97d0ef4bcff316586c1f8d1b04e88048.
        # Its review round rewords verification-gate's none_correct clause
        # (reason recorded, intermittent rate kept); the pin before it was
        # 88077868a27032057348998ad1bd84d68b542c301010b45b6d2ac8fd3088c975.
        # Re-derived for scout-first, final-repair re-plan, loop re-plan and
        # outside-memory candidates: clean origin/main reproduces 098cb4a9...11f7d;
        # only dag-ulw (old 39dd80a2), loop (old dbfddeb5), and deep-interview
        # (old 00aff6d5) body digests move. Capability row digests are unchanged.
        # Planning skills offer dag-ulw after acceptance: oh-my-hermes (router lane map and
        # engine gate), ralplan (recovery note, node-prompt line), refactor-plan (whole-plan
        # go) and dag-ulw (graph from an accepted plan) move; nothing else. Re-derived on the
        # tree merged with main; the pin before it was 2050e228...df6b.
        # Its delta review rewords refactor-plan's dag-ulw line (fit condition back, no
        # rollback in STOP WHEN); only refactor-plan moves, and the pin before it was 354f7cf2...5e6b.
        # Research citation receipts: ulw-research, web-research and research-brief gain one receipts-verify
        # clause; only those three bodies move, and the pin before it was ab8d58ad...6258e7.
        # Bail points replace default Recovery Notes on the attributed skills; procedure bails and the shared rail move references only.
        # dag-ulw's category-ladder line sends a `role=review` node to `review`, keeps `role=baseline`
        # low and has `role=verify` climb the ladder; only dag-ulw moves. Re-derived on the tree merged
        # with main after the bail points; main's pin before it was fb4303cb...1fcf.
        # systematic-review joins the research lane (+27 -> +28 more) with its narrowed Korean pack;
        # restoring +28 -> +27 and dropping it reproduces 2b0982e6...8db3.
        # ulw-research's entity-match clause (answer only from a source on the exact named entity);
        # only ulw-research moves, and the pin before it was 5404bf98...ca32229.
        # dag-ulw's external-owner policy (per-owner choices named in a dag-ulw request, the node
        # `owner` field, `exports`); only dag-ulw moves, and the pin before it was 8ea92d7d...58d7.
        # Then the render rail: every body names its siblings by the label `skill_view`
        # loads, and the bodies that ended in a lost hand-back fragment gain the lane
        # section; the pin before it was 4f552dc5...a07a.
        # The skill audit round moves the bodies each lane edited and nothing else: the union of the
        # lanes' moved lists equals the merged tree's. Plan, ralplan and adversarial-consensus name
        # `--plan-file` / `--input-bundle`; the pin before it was 7e537e8d...4b2c. The code-quality skills fix round then moves
        # its lane's bodies (build-failure-triage, verification-gate, codebase-onboarding, codebase-uml, codegraph-refresh,
        # frontend-refactor, github-event-ops, github-issue-intake and ultraqa among them); the pin before it was 49189871...a29a. Its second review then reworded
        # the origin rerun rule, the lldb crash recipe's neighbours and a few sibling labels; the pin before that was 55b2226e...25eb. The third review's two command fixes (the codegraph reflog
        # time and the job-log endpoint) move build-failure-triage and codegraph-refresh only; the pin before it was 460133f6...abb.
        # The cross-lane rail fix then moves almost every body: the lane line drops its sample of member
        # names, and sibling hand-offs gain backticks or labels; the pin before it was ffca16e2...d704.
        # agent-instructions then names `ulw-context`, the label that loads, in place of `omh-context`
        # (same length); only that body moves, and the pin before it was 0ac3cd4c...17f7.
        # The routing reach round then moves the skills whose triggers or index text it narrows; the pin
        # before it was 0ae5f905...ebc5f.
        # memory-new's Reply then says a recapture retires the earlier held copy; only memory-new
        # moves, and the pin before it was d4eb4e54...7ed7.
        # ralplan's acceptance line says plan-accept refuses a scaffold-only file unless
        # `--allow-scaffold`; only ralplan moves, and the pin before it was b36ad311...1e91.
        # show-reel then sends its paid calls through spend-gate, and spend-gate counts subscription
        # credits as a spend; only those two move. Its review round (credits read from the provider's
        # own price, the credits receipt, the gate named at every paid run step) moves the same two.
        # Merged with main after #2652: both sides' bodies; main's pin before that merge was
        # b36ad311...1e91, and this branch's was f30c9ae0...ca61. Merged again after #2650: main's
        # pin was 51d4a5cf...9f51, and this branch's was a5bce194...90de.
        self.assertEqual(_digest(legacy_hashes), '62bebac1a0b2d516c936f3966ec321cdee21c66815b6b477b618473eda7abd0b')
        legacy = _skill_context_cost_profile('full', legacy_templates, refs)
        current = _skill_context_cost_profile('full', templates, refs)
        # Main's search guidance adds 305; repro-audit's mandatory rails 1,943.
        # Main's search guidance adds 305. 124650 -> 126657: sprite-forge's
        # mandatory Workflow Lane (519) + Runtime Evidence (1446) = 1965, plus
        # 42 bytes of sibling reinforcement rails (+2007).
        # Merged with main: 126593 + 2007 = 128600, re-derived from the producer.
        # 128600 -> 128099: codebase-onboarding's own Completion Checklist and
        # Recovery Notes replace the planning-category defaults it repeated
        # (-501); swapping only that body back to main's restores 128600.
        # Skill-specific bail notes remove duplicate Recovery Notes; the measured count falls, with all ceilings unchanged.
        # 120488 -> 122431: systematic-review's mandatory Workflow Lane (497) + Runtime Evidence (1446) = 1943.
        # 122431 -> 124814: the render rail writes each sibling under its loadable label
        # (`omh-` or `ulw-` prefixed) in the sections bodies repeat; the ceilings keep their headroom.
        # 124814 -> 115494: the skill audit round's own Completion Checklist, Why and Recovery
        # lines replace the defaults those bodies repeated (itemized by lane at
        # FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS); the ceilings are re-derived there.
        # 115494 -> 114629: agent-debug states its own Why and Do Not Use When, and github-event-ops and
        # github-issue-intake their own Completion Checklists, in place of the feature-surface defaults those
        # bodies repeated (-865).
        # 114629 -> 92262: the lane line's sample of member names was the same text in every lane mate.
        self.assertEqual(legacy['repeated']['bytes'], 92262)
        delta = current['repeated']['bytes'] - legacy['repeated']['bytes']
        self.assertEqual(delta, len(sections['Workflow Lane']) + len(sections['Runtime Evidence']))
        self.assertLessEqual(delta, REPEATED_DELTA_CAP)
        # 126,000 -> 127,943: repro-audit's 1,943 rails, bounded by its own test.
        # 126_000 -> 128_007: the same measured +2007 as above; no new headroom.
        # Merged with main: 126,000 + 1,943 + 2,007 = 129,950.
        # 129,950 -> 131,893: systematic-review's measured +1,943 rails.
        self.assertLess(current['repeated']['bytes'] - REPEATED_DELTA_CAP, 131_893)
        feature_refs = [t for t in refs if t.skill_name == FEATURE]
        self.assertEqual(len(feature_refs), 6)
        # 19397 -> 19800: the suspect-posting and interview-prep lines and real Korean questions
        # (measured 19,731 at the time; the cap keeps the headroom the other lines in this test carry).
        self.assertLessEqual(sum(len(t.content.encode()) for t in feature_refs), 19800)
        # 4039 -> 4164: procedure.md's Korean clarification questions were English text; real Korean
        # is three bytes a character (+125).
        self.assertLessEqual(max(len(t.content.encode()) for t in feature_refs), 4164)

    def test_hard_per_item_schema_and_injection_limits_do_not_move(self) -> None:
        # Career growth moves only the three catalog-total ratchets. Later
        # schema changes keep their own measured marginal caps; parked waits
        # are covered by test_per_turn_budgets, not funded from career slack.
        from omh.maintenance.drift import budget_metrics
        expected = {
            'skill_index_line_max_chars': 100,
            'plugin_tool_schema_chars': 72525,  # Parked DAG waits (+429), delegation backends (+245), six routing-recipe categories (+213), opt-in omh-lsp tools (+2187), opt-in lsp_diagnostics (+396), identity argument (+143), dag node role (+85), dag node owner (+70).
            'pre_llm_call_context_chars_max': 5977,  # The pi-family runtime rename (+6), the route-hint dedup (-154), then the console choices line (+409).
            'pre_llm_call_context_fallback_chars_max': 7529,  # The same rename (+6), the human-voice primer sentence (+116), the route-hint dedup (-154), then the console choices line (+409).
            'awareness_primer_markdown_chars': 4051,  # Human-voice reply sentence (+110), full skill names in the checkpoint (+55), then loadable labels there (+49), on the card and cue lines (+239) and in the lane keys (+78).
            'awareness_primer_context_chars': 1560,  # The same sentence (+120).
            'awareness_workflow_context_chars_max': 1500,
            'role_context_chars_max': 2600,
            'full_capability_skill_item_chars_max': 9000,
            'standalone_capability_skill_item_chars_max': 2200,
            'full_profile_skill_body_chars': 1650000,  # Re-derived from 1499208 measured, +10%, up to the next 50,000 (itemized at FULL_PROFILE_SKILL_BODY_MEASURED_CHARS).
            'full_profile_skill_body_repeated_chars': 110000,  # Re-derived from 94049 measured, +10%, up to the next 10,000.
            'skill_density_filler_hits': 0,
        }
        metrics = {m.name: m for m in budget_metrics()}
        for name, limit in expected.items():
            with self.subTest(metric=name):
                self.assertEqual(metrics[name].limit, limit)
                self.assertLessEqual(metrics[name].live(), limit)


if __name__ == '__main__':
    unittest.main()
