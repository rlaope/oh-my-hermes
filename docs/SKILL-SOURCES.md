# Skill Upstream Sources

Provenance registry for OMH skills whose content was **reconstructed** from
external skill ecosystems. This file lives outside the generated skill bodies
on purpose: it is the input for the upstream-tracking automation that checks
whether a referenced source changed since the recorded review, and raises an
issue when a change looks worth folding back into our skill.

Rules:

- One row per (OMH skill, upstream source) pair; a skill may have several rows.
- `reviewed_ref` is the upstream commit the reconstruction was reviewed
  against. The tracker diffs upstream HEAD against it and, when the diff
  touches the listed paths, raises an issue labeled `upstream-skill-update`.
- Reconstruction, never copying: our skill text is OMH's own wording and
  contract language. The license column records what made close study
  acceptable; `none` means link-only reference.
- When a tracker issue is resolved (folded in or rejected), update
  `reviewed_ref` and `reviewed_on` in the same PR that resolves it, and append
  the closure receipt that records the decision. Both halves or neither; see
  [Closure receipts](#closure-receipts), which is what now enforces this rule.
- This file is hand-written; no generator owns it.
- A license read from the GitHub API can be a false negative: the API answers
  `other` for `Effeilo/claude-code-frontend-skills` because its `LICENSE.md`
  opens with a logo block above the MIT text. That repository is MIT across
  every row that cites it, and a tracker run must not "correct" those rows to
  unlicensed off the API field.

## Closure receipts

The rule above used to be prose, and prose does not fail a build. A merged
capability change could resolve a tracker finding and leave the matching row
untouched, so the next run re-evaluated a range that had already been reviewed
and presented resolved work as fresh risk.

The receipt is what binds the two halves. `docs/skill-source-receipts.json`
holds an append-only ledger; each entry names one candidate, the checkpoint it
moved from, the checkpoint it moved to, and the terminal disposition:

```json
{
  "receipt_id": "ssc-2026-09-14-lifecycle-growth-posthog",
  "candidate_key": "lifecycle-growth@github.com/posthog/posthog",
  "prior_checkpoint": "ae880d309f33eaf236cb4e46991f249a88e1c16e",
  "next_checkpoint": "4f1c0b77a2e5d1c6b93a0f2e8d47b5c1a6e3d902",
  "disposition": "adopted",
  "decision_ref": "#1543",
  "reviewed_on": "2026-09-14",
  "rationale": "Adopted the reviewed exposure semantics; upstream product copy rejected.",
  "supersedes": null
}
```

- `candidate_key` is `<omh unit>@<upstream source>`: the first backticked token
  of the **OMH skill** cell, lowercased, then the source URL with its scheme,
  trailing slash, and any trailing prose removed. It must identify exactly one
  row in the table below.
- `disposition` is `adopted`, `rejected`, or `duplicate`. All three settle a
  finding and all three advance the checkpoint, because a rejected or duplicate
  range was still reviewed and must not be rediscovered forever.
- `decision_ref` names the OMH issue or pull request that records the decision,
  as `#N`. Closure of that issue is not itself review evidence.
- `rationale` is one line of at most 240 characters stating the OMH decision.
  Watch evidence -- what the tracker saw upstream, which commits were in range
  -- stays in the private continuity record and in the cited OMH issue, never
  in this public ledger.
- `supersedes` names an earlier receipt for the **same** candidate when a later
  review corrects it. Receipts are append-only: a correction is appended, and
  the earlier decision stays readable exactly as it was recorded.

A row is `closed` when its receipt chain terminates at the row's current
`reviewed_ref` **and** `reviewed_on`. Half an atomic change fails from either
side.

Check it locally, the same command CI runs:

```sh
uv run python -m omh.cli docs skill-sources --check
```

Add `--json` for the `skill_source_closure_audit/v1` payload. The check is
offline and deterministic: it never fetches a watched repository, runs a
scheduled job, closes an issue, or merges a pull request, and it never decides
whether a capability should be adopted. It validates OMH-owned continuity after
a human or an authorized workflow already decided.

Every failure carries a stable reason code, so CI output is grepped rather than
read: `closure_checkpoint_missing` (the decision landed, the row did not move),
`closure_receipt_missing` (the row moved, no receipt records why),
`checkpoint_prior_stale`, `checkpoint_not_superseding`,
`ambiguous_candidate_match`, `unmatched_candidate_key`, `receipt_id_reused`,
`supersede_reference_unknown`, `supersede_reference_unrelated`,
`receipt_field_invalid`, `rationale_over_budget`, `ledger_order_violation`,
`unenrolled_registry_row`, `stale_baseline_entry`, `registry_row_unparsed`,
`ledger_unreadable`, and `baseline_census_modified`. Passing rows carry a code
too: `receipt_chain_settled` or `pre_receipt_baseline`.

A row in the table that cannot be read as a candidate is reported
`registry_row_unparsed`, never skipped. This is a hand-written table, so an
indented row, or a skill cell that forgets its backticks, is the expected
accident; a row quietly leaving the audit is the one failure this gate must not
have. A cell may carry a literal pipe written as `\|`.

Only the **Shipped skills** table is audited. Parsing stops where that table
ends, so the candidate-rows section below is neither enrolled nor rejected: a
researched lead carries no checkpoint for a receipt to bind to, and recording
one must never fail the build.

### Rows that predate receipts

No receipt was fabricated for work reviewed before this contract existed. Every
row in the table below is enrolled at the state it stood in, by an entry in
`pre_receipt_baselines()` in `src/catalogs/skill_source_closure.py`. Such a row
reports `not_applicable` while it stays there, and already hands the next run a
starting boundary.

That census is closed and frozen. It records where rows stood **once**, so that
a receipt has somewhere to start. It is not a running mirror of where they stand
now: after a candidate has receipts its row moves and its baseline does not, and
the two are then supposed to disagree.

The migration is a one-way door. The first time an enrolled row moves, the move
needs a receipt whose `prior_checkpoint` equals the baseline value, or the check
fails `closure_receipt_missing`. Editing the baseline instead would relabel that
unrecorded advance as `not_applicable` and pass, so the census is pinned by
`PRE_RECEIPT_CENSUS_DIGEST` and any change to a candidate key, review date, or
checkpoint fails `baseline_census_modified`. The digest is pinned a second time
as a literal in `tests/test_skill_source_closure.py`, so recomputing the
constant to match an edit does not clear the gate either. Entry wording sits
outside the digest and stays free to improve.

A new row added to the table needs either a receipt with a null
`prior_checkpoint` or a new baseline entry carrying its own reason, or it fails
`unenrolled_registry_row`.

## Shipped skills

| OMH skill | Category | Upstream repo | Paths studied | License | reviewed_on | reviewed_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `codebase-uml` (PR #1230) | planning | https://github.com/plantuml/plantuml | CLI flags/pragmas/size limits (docs, `src/main/java/net/sourceforge/plantuml/cli/CliFlag.java`) | GPL-3.0 (external tool, invoked not vendored) | 2026-09-04 | b2392e6230a1782e477a45d250b7cb9a569f95da |
| `code-review` spec axis + smell baseline (PR #1237) | review | https://github.com/mattpocock (code-review skill, plugin dist 1.2.3) | `skills/engineering/code-review/SKILL.md` | plugin dist | 2026-09-01 | plugin 1.2.3 |
| `ai-slop-cleaner` taxonomy + passes (PR #1239) | maintenance | https://github.com/Effeilo/claude-code-frontend-skills | `front-refactor/SKILL.md`, `front-refactor/front-refactor-rules.md` | MIT | 2026-09-01 | 3c9d5a0501ff |
| `frontend-refactor` (PR #1238) | maintenance | https://github.com/Effeilo/claude-code-frontend-skills | `front-refactor/*` (preview/apply mode contract, DEAD→NAMING→SIMPLIFY→MODERN) | MIT | 2026-09-01 | 3c9d5a0501ff |
| `frontend-refactor` (PR #1238) | maintenance | https://github.com/pproenca/dot-skills | `skills/.experimental/react-refactor/` (40 impact-ordered rules) | MIT | 2026-09-01 | cf93c57cac89 |
| `frontend-refactor` state-discipline (PR #1238) | maintenance | https://github.com/Cst2989/react-tips-skill | `skills/react-tips/SKILL.md`, `skills/no-unnecessary-effects/SKILL.md` | MIT | 2026-09-01 | 8c42b9e6390c |
| `frontend-refactor` state-discipline (PR #1238) | maintenance | https://github.com/mickeyyaya/refactoring-skills | `skills/state-management-patterns/SKILL.md` | MIT | 2026-09-01 | cd0c22762849 |
| `refactor-plan` (PR #1241) | planning | https://github.com/github/awesome-copilot | refactor-plan skill (phase order, files table, stop-for-confirmation gate) | MIT | 2026-09-01 | 5eaae7e2cde2 |
| `inference-serving` (PR #1243) | operations | https://github.com/vllm-project/vllm-skills | deploy (docker/k8s) + bench (serve, prefix-cache) skills | Apache-2.0 | 2026-09-01 | c99623410c15 |
| `inference-serving` (PR #1243) | operations | https://github.com/Orchestra-Research/AI-Research-SKILLs | `12-inference-serving/` vLLM + llama.cpp skills | MIT | 2026-09-01 | 773a52944ba4 |
| `agent-ops-review` instrumentation ladder (PR #1246) | operator | https://github.com/nexus-labs-automation/agent-observability | audit + instrument skills, tier methodology, anti-patterns | MIT | 2026-09-01 | 1714a4b38d7f |
| `ops-observability-card` span vocabulary (PR #1246) | observability | https://github.com/nexus-labs-automation/agent-observability | llm-call-tracing, token-cost-tracking skills | MIT | 2026-09-01 | 1714a4b38d7f |
| `llm-app-dev` harness budgets (PR #1246) | delivery | https://github.com/DenisSergeevitch/agents-best-practices | `SKILL.md`, `references/tools-and-permissions.md`, `references/context-memory-compaction.md`, `references/evals.md`, `references/skills-and-connectors.md` | MIT | 2026-09-07 | 8ae085045bd6cddfab22c740c95dd2d764117ffc |
| `lifecycle-growth` exposure and launch controls (issue #1374, review #1399) | strategy | https://github.com/PostHog/posthog | `README.md` and feature-flag/experiment concepts: targeting, actual-display exposure, holdouts, staged rollout, launch/pause/stop/archive; #1399 review of community commits 8a7cc173 (ordered audience rules, reachability, person/group/device bucketing), d63178e9 (read-only promotion preflight, disabled target, explicit carry approval), 7c47a0cd (separate post-GA gate cleanup), f3bff4e0 (deleted reference is a validation error), 66ce2596 (zero-exposure baseline is no-data, not a server error); rationale in `docs/LIFECYCLE-GROWTH.md` (concepts only; `ee/` excluded and unused) | MIT outside `ee/` (concepts only, no code) | 2026-09-09 | ae880d309f33eaf236cb4e46991f249a88e1c16e |
| `lifecycle-growth` experiment validity (issue #1374) | strategy | https://github.com/growthbook/growthbook | `README.md` and experiment concepts: sticky assignment, primary/guardrail metrics, minimum runtime, data-quality gates, holdouts, ship/rollback/review/insufficient-data decisions, analysis-run state (queued/running/completed/failed/canceled) kept distinct from a missing result (concepts only; enterprise directories excluded) | MIT outside listed enterprise directories (concepts only, no code) | 2026-09-09 | 095f61643e148f03ce0b442c78e6030c045f6d7b |
| `lifecycle-growth` audience and journey policy (issue #1374) | strategy | https://github.com/dittofeed/dittofeed | `README.md` and journey concepts: event/segment entry, journey graphs, re-entry/idempotency, subscription eligibility, deterministic cohorts (concepts only) | MIT (concepts only, no code) | 2026-09-07 | 52b2bee909744d07dd5d409fd3974d4b95c66766 |
| `lifecycle-growth` safety policy (issue #1374) | strategy | https://github.com/novuhq/novu | `README.md` and notification-workflow concepts: trigger validation, preference precedence, digest/throttle windows, throttle grouping identity, transaction identity, per-step matched/skipped status, production read-only workflow content (concepts only; enterprise packages excluded) | MIT community code (concepts only, no code) | 2026-09-08 | c7bc772fc0b7722909ef1bdb9bcf04991996fdd8 |
| `product-discovery-validation` validation track (issue #1375) | planning | https://gitlab.com/gitlab-com/content-sites/handbook | `content/handbook/product-development/how-we-work/product-development-flow/_index.md` (validation separate from build; problem validation before solution) | MIT (concepts only, no code) | 2026-09-07 | 4165803c1cf9adeae2826f1af918668be5c942f6 |
| `product-discovery-validation` evidence and falsification (issue #1375) | planning | https://github.com/haabe/mycelium | `README.md` (evidence source classes, external-human/data gates, falsification propagation, precommitted assumption tests, audience-before-build invariant) | MIT (concepts only, no code) | 2026-09-09 | 8e958f82141e6cd38e0cc8046e8eb9f21df777b0 |
| `product-discovery-validation` disconfirming tests (issue #1375) | planning | https://github.com/shinpr/claude-code-discover | `README.md` (hypothesis states, smallest disconfirming test, hard budgets, honest inconclusive results, outcome-bounded MVP) | MIT (concepts only, no code) | 2026-09-07 | a414fc7a978bb2deaec5c71dd399cf63708378ee |
| `product-discovery-validation` evidence ledger (issue #1375) | planning | https://github.com/lenar-amirov/product-pipeline-public | `README.md` (persistent hypotheses, evidence typing, decision history, contradiction flags, state-based next actions) | MIT (concepts only, no code) | 2026-09-07 | a0997741f4c9b68ba298796c83197a4ab66ba3d9 |
| `product-discovery-validation` interview and GTM concepts (issue #1375) | planning | https://github.com/phuryn/pm-skills | `README.md` (assumption categories, past-behavior interviews, demand tests, beachhead/ICP, messaging, channel planning) | MIT (concepts only, no code) | 2026-09-07 | 18468a95b427e70e258b51389796367c6f684e7d |
| `sales-pipeline-review` stage and forecast review (issue #1376) | operations | https://gitlab.com/gitlab-com/content-sites/handbook | `content/handbook/sales/revenue-analytics/_index.md` (pipeline health/coverage, stage conversion and stalls, aging, forecast accuracy, win/loss, renewals) and `content/handbook/sales/commercial/comm-sales-opp-stages/_index.md` (stage activities and exit criteria) | MIT (concepts only, no code) | 2026-09-07 | 4165803c1cf9adeae2826f1af918668be5c942f6 |
| `sales-pipeline-review` CRM field semantics (issue #1376) | operations | https://github.com/odoo/odoo | `addons/crm/models/crm_lead.py` (expected/recurring revenue, close date, manual/automated probability, won/lost state, loss reason, stale thresholds) | LGPL-3.0 (concepts only, no code) | 2026-09-07 | 1a13ceeaee12fe5cc50f287c31f217d4be2a2eaf |
| `sales-pipeline-review` opportunity field semantics (issue #1376) | operations | https://github.com/frappe/erpnext | `erpnext/crm/doctype/opportunity/opportunity.json` (stage, owner, amount, expected close, supplied probability, competitors, loss reasons) | GPL-3.0 (concepts only, no code) | 2026-09-07 | 72fa7d0b1091e1a66450ebb4dc9fb6de1c8d3c1a |
| `sales-pipeline-review` CRM-runtime boundary (issue #1376) | operations | https://github.com/twentyhq/twenty | `packages/twenty-server/src/modules/opportunity/standard-objects/opportunity.workspace-entity.ts` (minimal opportunity substrate; identifies CRM-runtime concerns not adopted into guidance) | AGPL-3.0 with application exception (concepts only, no code) | 2026-09-07 | c8fc76650231ca3640276f75f071670b20e51e75 |
| `award-bar-score` judging model | materials | https://www.cssdesignawards.com/ | published judging axes, weights, and award thresholds — factual reporting of public rules, no site text reproduced | n/a — public rules, not code | 2026-09-03 | — |
| `tech-debt-audit` (issue #1235) | maintenance | https://github.com/ksimback/tech-debt-skill | none — no license published, so link-only reference; content built from OMH's own audit spec | none | 2026-09-02 | 5a15c1ca4a92 |
| `strategy-brief` decision records (issue #1236) | strategy | https://github.com/wshobson/agents | `plugins/documentation-generation/skills/architecture-decision-records/SKILL.md` | MIT | 2026-09-02 | a30778f8c4e6 |
| `accessibility-audit` rule IDs + fix partition (issue #1261) | accessibility | https://github.com/Effeilo/claude-code-frontend-skills | `front-a11y/front-a11y-rules.md` (rule-ID scheme, severity split, auto-fixable partition) | MIT (see the API false-negative rule above) | 2026-09-02 | 3c9d5a0501ff |
| `agent-evaluation` self-evaluation loops (issue #1263) | evaluation | https://github.com/github/awesome-copilot | `skills/agentic-eval/SKILL.md` (loop shapes, stop rules, judging strategies) | MIT | 2026-09-02 | 6a8fa297b0fe |
| `frontend` web-vitals budgets (issue #1262) | frontend | https://github.com/rohitg00/awesome-claude-code-toolkit | `skills/frontend-excellence/SKILL.md` (CWV threshold table, field-vs-lab note) | Apache-2.0 | 2026-09-02 | ebdf1d596d2c |
| `apple-design` | materials | https://github.com/dickwu/apple-design-skill | `README.md`, `SKILL.md`, `references/hig-lookup.md`, `references/hig/` reviewed as link-only context; no source text or bundled references reproduced | none | 2026-09-05 | d0bac1e765a27a696839e62962e36330ce72f0b7 |
| `apple-design` product-visual references | materials | https://www.apple.com/macbook-pro/ | MacBook Pro, AirPods Pro, and Apple Vision Pro pages reviewed as link-only visual-reference context; no Apple assets or page text reproduced | n/a — primary web references | 2026-09-05 | — |
| `apple-design` native icon boundary | materials | https://developer.apple.com/icon-composer/ | Icon Composer reviewed as native multilayer icon-pipeline context; not used as a marketing-renderer claim | n/a — primary documentation | 2026-09-05 | — |
| `apple-design` GSAP integration boundary | materials | https://github.com/greensock/gsap | `README.md`, `package.json`, and type declarations reviewed for existing-project animation, match-media, and cleanup guidance; no source reproduced | GreenSock Standard no-charge license; not labeled OSI | 2026-09-05 | 13e2b790546426a1a2e0e9b409f3f8dc6d6611f2 |
| `apple-design` liquid-logo research boundary | materials | https://github.com/paper-design/liquid-logo | `README.md`, `package.json`, canvas, shader-parameter, and lifecycle code reviewed as link-only technical context; no source reproduced | PolyForm Shield 1.0.0; not labeled OSI | 2026-09-05 | 689bb38a1e0d5a6a8baf2d34847635eefde19994 |
| `apple-design` liquid-glass-js integration boundary | materials | https://github.com/dashersw/liquid-glass-js | `README.md`, `container.js`, and `button.js` reviewed for web-only class, capture, and lifecycle guidance; no source reproduced | MIT | 2026-09-05 | 78cb6ccb0b9987bb60a88b14ccbd13a9e6e8ab2a |
| `verification-gate` requirement coverage map (issue #1714) | verification | https://github.com/github/spec-kit | `templates/commands/analyze.md` (stable FR-/SC- requirement ids, requirement-to-task coverage mapping, six named detection passes, four-level severity, per-category finding ids, 50-finding cap with overflow, strictly read-only report) | MIT | 2026-09-19 | d4229c071c7ea3885b43e8a7739847300f618f13 |
| `deep-interview` ambiguity taxonomy (issue #1714) | clarification | https://github.com/github/spec-kit | `templates/commands/clarify.md` (category taxonomy scanned as a Clear/Partial/Missing coverage map, five-question session cap, one-question-per-round format rules, per-answer write-back into the spec with contradiction removal) | MIT | 2026-09-19 | d4229c071c7ea3885b43e8a7739847300f618f13 |
| `todo-checklist` requirements-quality checklist (issue #1714) | planning | https://github.com/github/spec-kit | `templates/commands/checklist.md` (checklists as requirement-quality validation rather than behaviour verification, CHK id scheme, quality category tags, generator-may-not-tick ownership rule) | MIT | 2026-09-19 | d4229c071c7ea3885b43e8a7739847300f618f13 |
| `plan` project constitution (issue #1714) | planning | https://github.com/github/spec-kit | `templates/commands/constitution.md` (principles at a fixed path, MUST/SHOULD normative split, semantic-versioned amendment with an impact summary, downstream artifacts checked against the principles) | MIT | 2026-09-19 | d4229c071c7ea3885b43e8a7739847300f618f13 |
| `ultrawork` file-ownership manifest (issue #1714) | execution | https://github.com/automazeio/ccpm | `skill/ccpm/references/execute.md` (per-issue parallel-stream analysis artifact: named streams with scope and explicit file lists, start conditions, coordination points for shared files, and a conflict-risk section) | MIT | 2026-09-19 | 7d7e4623bc6d4c0c9ba66ca6bfecd7e5261dc697 |
| `ultrawork` file-ownership manifest (issue #1714) | execution | https://github.com/wshobson/agents | `plugins/agent-teams/skills/parallel-feature-development/references/file-ownership.md` (enumerate-cluster-assign ownership derivation, designated owner for shared interface files, four-step overlap resolution ending in never-concurrent) | MIT | 2026-09-19 | 4236bb91f8395b0435f1d8b8baf9e8e4c69a8620 |
| `ai-slop-cleaner` prose lexicon (issue #1714) | maintenance | https://github.com/wshobson/agents | `plugins/avoid-ai-writing/skills/avoid-ai-writing/references/word-tiers.md`, `references/pattern-catalog.md`, `references/profiles.md` (tiered word list with the 1A/1B evidence split, three-severity pattern catalog, per-register tolerance profiles) | MIT | 2026-09-19 | 4236bb91f8395b0435f1d8b8baf9e8e4c69a8620 |
| `code-review` verification-gap lens (issue #1714) | review | https://github.com/bmad-code-org/BMAD-METHOD | `skills/bmad-review/SKILL.md` and `skills/bmad-review/references/lens-*.md` (five lenses run as separate passes; the verification-gap lens contributes the three gap shapes, the read-the-test-first evidence rules, and the what-does-not-count test list) | MIT (API answers NOASSERTION; `LICENSE` is the MIT text with an added contributions line) | 2026-09-19 | f033e70a2c0a3751aaab17dfdd29839ac621f541 |
| `jev-ask` (issue #1795) | gateway | https://github.com/typesafe-ai/skills | `skills/typesafe-ai/SKILL.md` (primitive table, independent questions over one state, a no-match option, confidence is not permission, policy lives in code) | MIT | 2026-09-23 | 65a39f393687675ce170e6094757de20370365b9 |
| `jev-ask` (issue #1795) | gateway | https://github.com/ajensenwaud/hermes-jev-plugin | `skills/jev-questions/SKILL.md` (atomic questions, state is evidence, combine answers in code, mid-range is uncertain) | MIT | 2026-09-23 | b3d29f71770a3447ad0b3db00658f64a8edc7dd3 |
| `jev-ask` (issue #1795) | gateway | https://github.com/ourines/hermes-jev | `skills/decision-sidekick/SKILL.md` (when not to call, advisory only, a failure is never a synthetic answer) | MIT | 2026-09-23 | de6f674a99ea03e11cfb1830dd1527ae208e3fea |
| `jev-route` (issue #1795) | gateway | https://github.com/DECRUX9812/typesafe-skill-router | `README.md` "How it works" (wide Choice with none plus per-candidate fits, a wrong name costs more than none, stable ordering, one log line per ask) | MIT | 2026-09-23 | 94fe114b3c53b3d6b81ba72890eb6db596cbaa12 |
| `jev-route` (issue #1795) | gateway | https://github.com/Pinutss/jev-agent-router | `README.md` (abstain plus one fallback hop over a candidate set) | MIT | 2026-09-23 | 8cb6d67a81d4545502750c4599b427d98acf3120 |
| `jev-failure-triage` (issue #1795) | review | https://github.com/ourines/hermes-jev | `presets.py` (`next_step`, `stuck`: next-move Choice with ask and escalate exits, repeat detection) | MIT | 2026-09-23 | de6f674a99ea03e11cfb1830dd1527ae208e3fea |
| `jev-failure-triage` (issue #1795) | review | https://github.com/ajensenwaud/hermes-jev-plugin | `skills/jev-questions/SKILL.md` failure-triage pattern (transient, dependency, permission Nouls) | MIT | 2026-09-23 | b3d29f71770a3447ad0b3db00658f64a8edc7dd3 |
| `jev-review-gate` (issue #1795) | review | https://github.com/ajensenwaud/hermes-jev-plugin | `skills/jev-questions/SKILL.md` review gating and severity (per-file Nouls, a severity Score, code-side combination) | MIT | 2026-09-23 | b3d29f71770a3447ad0b3db00658f64a8edc7dd3 |
| `jev-action-check` (issue #1795) | review | https://github.com/anpicasso/hermes-jev-approvals | `plugin/jev_policy.py`, `plugin/__init__.py` question set (six typed questions, ordered rule ladder, fail-to-escalate; the 0.6, 0.7, 0.7 and 0.55 cuts and the rule order adopted from `jev-approval-rules/1`, blast cut 1.5 against its 1.6, calibration not transferred) | MIT | 2026-09-23 | 530fdb006f1637f9771ccf24049bf6588485c871 |
| `jev-done-check` (issue #1795) | review | https://github.com/keeltrace/hermes-jev | `contracts/verify-v1.json`, `planning/vnext-1119/tickets/T26-*.md` (verdict shape, evidence over self-report) | MIT | 2026-09-23 | 375f17872bb59c2de1e7102e9bc7471774150c62 |
| `frontend` registry ownership + semantic color pairs | frontend | https://github.com/shadcn-ui/ui | `apps/v4/content/docs/(root)/theming.mdx`, `apps/v4/content/docs/components/radix/chart.mdx` (surface/foreground pairs, ring token, one radius knob, `chart-1..5`, the CLI-registry open-code ownership model; concepts only, no code) | MIT | 2026-10-07 | efa11781f756c86debb0392fbea4fe468250b41b |
| `frontend` marquee contract | frontend | https://github.com/magicuidesign/magicui | `apps/www/registry/magicui/marquee.tsx` (duplicated children, CSS-variable speed and gap, hover-only pause; the missing `aria-hidden` and reduced-motion branch recorded as gaps; no source reproduced) | MIT | 2026-10-07 | cdb348cb4c72a9b54b554d8617801e479fbc8714 |
| `frontend` split-text contract | frontend | https://github.com/DavidHDev/react-bits | `src/content/TextAnimations/SplitText/SplitText.jsx` (stagger, duration, easing, offset defaults; `document.fonts.ready` wait; split revert and trigger teardown; the missing ARIA and reduced-motion branch recorded as gaps; no source reproduced) | MIT with Commons Clause condition (not OSI; concepts only, no code) | 2026-10-07 | ca44b3f9ee180676a06d7de8ec6bea84cddff85b |
| `frontend` chart styling | frontend | https://github.com/mui/mui-x | `docs/data/charts/styling/styling.md` (palette as a function of mode, piecewise/continuous/ordinal color maps with `unknownColor`, `tickLabelStyle`/`labelStyle` as the layout-measured path, loading and no-data overlays; concepts only) | MIT (`@mui/x-charts` community package) | 2026-10-07 | b3b49d90634d862cb9f0091b8c9c30cbca132846 |
| `frontend` neobrutalism preset | frontend | https://github.com/ekmas/neobrutalism-components | published style description at https://www.neobrutalism.com/docs (outlined elements, zero-blur offset shadows, flat loud fills, no gradients or glass, active press into the shadow; the offset value is not published; no text reproduced) | MIT | 2026-10-07 | 3306a802724874a85f93079702b2795370a279d4 |
| `frontend` semantic color pairs (daisyUI) | frontend | https://github.com/saadeghi/daisyui | themes documentation and `llms.txt` (`X`/`X-content` pairs, `data-theme` switching, semantic colors over raw palette, no `dark:` on semantic colors; concepts only) | MIT | 2026-10-07 | 9adbeaa259816be46b98bf497a09cd2ab127e3cf |
| `ultrawork` TDD red/green (issue #2049) | execution | https://github.com/obra/superpowers | `skills/test-driven-development/SKILL.md` (the tests-first iron law, watch-it-fail verification, the rationalization table, and the red flags, rewritten in OMH's evidence vocabulary as `references/tdd-red-green.md`; no text reproduced) | MIT | 2026-10-10 | 8ca22dba9a94f28898bbce59f2537ff4d87c747d |
| `code-review` review dispatch and response halves (issue #2049) | review | https://github.com/obra/superpowers | `skills/requesting-code-review/SKILL.md`, `skills/receiving-code-review/SKILL.md` (a named commit range per review request, verify before implementing, an all-or-nothing clarification gate, push-back and fix ordering, rewritten as `references/review-dispatch.md` and `references/review-response.md`; no text reproduced) | MIT | 2026-10-10 | 8ca22dba9a94f28898bbce59f2537ff4d87c747d |
| `frontend` design-system contract and taste direction (issue #2049) | frontend | https://github.com/code-yeongyu/oh-my-openagent | `packages/shared-skills/skills/frontend/SKILL.md`, `packages/shared-skills/skills/frontend/references/design/README.md` (a `DESIGN.md` contract before component code, paired with taste-direction material and an evidence-bound critique lane; concepts only, no text reproduced) | Sustainable Use License 1.0 (concepts only, link-only) | 2026-10-10 | 9c62b6278bbe322f1629ad50564d54c7adca4c40 |
| `visual-qa` reference-fidelity verdict (issue #2049) | materials | https://github.com/code-yeongyu/oh-my-openagent | `packages/shared-skills/skills/frontend/SKILL.md` final visual-QA step and `packages/shared-skills/skills/visual-qa/SKILL.md` (a verdict against the reference as the visual contract, pixel diff as evidence that aims the review rather than decides it; concepts only, no text reproduced) | Sustainable Use License 1.0 (concepts only, link-only) | 2026-10-10 | 9c62b6278bbe322f1629ad50564d54c7adca4c40 |
| `design-quality-gate` critique lane (issue #2049) | materials | https://github.com/code-yeongyu/oh-my-openagent | `packages/shared-skills/skills/frontend/SKILL.md` and `packages/shared-skills/skills/frontend/references/designpowers/lane-c-review.md` (critique as its own evidence-bound lane with pass/fail behavior; concepts only, no text reproduced) | Sustainable Use License 1.0 (concepts only, link-only) | 2026-10-10 | 9c62b6278bbe322f1629ad50564d54c7adca4c40 |
| `plan` Review Focus and proportion check (issue #2049) | planning | https://github.com/obra/superpowers | `skills/writing-plans/SKILL.md` (a capped Review Focus list of requirement-implied inputs that no planned test covers, each assigned to an owning task; single-action steps with a checkable outcome; a proportion check of plan size against the code it leads to; rewritten as `plan` quality-bar lines scoped to plans that describe code changes; no text reproduced) | MIT | 2026-10-10 | 8ca22dba9a94f28898bbce59f2537ff4d87c747d |
| `ralplan` ideal-state anchoring and fidelity check (issue #2049) | planning | https://github.com/code-yeongyu/oh-my-openagent | `packages/shared-skills/skills/ulw-plan/SKILL.md` (named consumers and their target state before options, every difference from today mapped to a task and a verification scenario, a closing coverage check that adds a task for an unmapped difference, no scope reduction the user did not request; sizing bands from `packages/shared-skills/skills/ulw-plan/references/full-workflow.md`; the `CHANGELOG.md` `ulw-plan` entry read as context only; concepts only, no text reproduced) | Sustainable Use License 1.0 (concepts only, link-only) | 2026-10-10 | 657ea5a2a73e69506df16cc8ce50f07874d1e37d |
| `app-debugging` escalation after three failed fixes (issue #2049) | verification | https://github.com/obra/superpowers | `skills/systematic-debugging/SKILL.md` (upstream material: a count of fixes tried, a return to investigation while fewer than three have failed, a stop after the third to question the architecture, the signals that point at an architecture fault, and a discussion with the human before any fourth attempt; OMH's change: a fix counts as failed only on an executed run of the same reproduction command where the original symptom persists or a new one appears that the fix caused rather than unmasked; rewritten as an `app-debugging` quality-bar line and a method-reference section; no text reproduced) | MIT | 2026-10-10 | 8ca22dba9a94f28898bbce59f2537ff4d87c747d |
| `loop` design review before launch (issue #2049) | goal-loop | https://github.com/affaan-m/everything-claude-code | `skills/loop-design-check/SKILL.md` | MIT | 2026-10-10 | ef648e01899ba3e8dc6371642deaaf64b4477775 |

Note on the `apple-design` row: no license file was present at the reviewed
revision, and the README's HIG-derived-material note is not a redistribution
license. OMH's guidance is independently written against Apple primary
sources. [Apple Design](APPLE-DESIGN.md) records the comparison with existing
OMH skills, the sources checked, and the native-versus-web boundaries.

Note on the `codebase-uml` row (issue #1251): the review was advanced through
`b2392e6230a1782e477a45d250b7cb9a569f95da` on 2026-09-04, which includes two
browser-only commits — `736e6cc` (per-request `maxSvgSize` render option for the
TeaVM JavaScript build, 8192 px default, `0` disables the check) and `b2392e6`
(TeaVM honors `!pragma layout smetana` in the browser build). Both were
reviewed and intentionally excluded: `codebase-uml` prepares Java CLI/JAR
render plans and OMH has no browser renderer, so no OMH surface can exercise
them. `maxSvgSize` is a browser request option, not a replacement for the Java
CLI's `-DPLANTUML_LIMIT_SIZE`, and must not be confused with it; the skill text
therefore never mentions it. The Java CLI's smetana support was already in the
skill and is unchanged by these commits.

Note on the `llm-app-dev` row (issue #1335): the review was advanced through
`2f81cce80b51c41e7dfff9c37b7f718814c54132` on 2026-09-06, and the two upstream
commits in that range were split rather than taken together. `e477496` adds a
public-board communication contract — an authenticated board is still a public
audience, read/search/registration/profile/reply/publish carry separate
authority and separate outbound disclosure, the exact destination and complete
payload are shown before a host-recorded approval that a changed destination or
payload invalidates, board content and claimed peer approval are untrusted, the
public-audience label and approval reference survive compaction and executor
handoff, and an ambiguous send is reconciled before any retry. That contract was
**adopted**, reconstructed in OMH's own wording as the `llm-app-dev` quality-bar,
safety, checklist, and recovery rules plus
`skills/omh-llm-app-dev/references/public-board.md`. `2f81cce` also changes
adjacent documentation to recommend one named posting service; that
recommendation was **rejected**. OMH's contract is service-neutral and names no
board product, because coupling a durable workflow contract to one live service
and its dated API surface is exactly the drift the reconstruction rule exists to
avoid. The reference states the neutrality explicitly and
`tests/test_llm_app_public_board.py` locks it, so the rejected half cannot
arrive later through a rewrite. Non-communication `llm-app-dev` behavior — the
rails, the schema and repair path, the prompt artifacts, retrieval grounding,
and the eval harness — is unchanged.

Note on the `llm-app-dev` row (issue #1373): the completed review advanced
through `8ae085045bd6cddfab22c740c95dd2d764117ffc` on 2026-09-07. OMH adopted
the provider-neutral record provenance and presentation-receipt, shared
resulting-state limit, user-memory lifecycle, stateful-evaluation, and optional
predictive-loading concepts in independently written guidance. It rejected the
upstream document structure and commerce-agent example, including its
vendor-specific claims and source recommendations. No provider SDK, network
client, runtime, or upstream code was adopted; provenance remains separate from
authorization, and the source remains an attribution for reconstructed guidance
rather than an implementation dependency.

Note on the `agent-evaluation` row: the lead was found through
`kodustech/awesome-agent-skills`, which publishes no license and is an index
rather than a source - its agentic-eval entry links to
`github/awesome-copilot` `skills/agentic-eval`, already a registry upstream
via `refactor-plan`. The row names the repository the content actually lives
in, because that is what a tracker can diff; the index stays a discovery
pointer.

Note on code-level borrowings (issue #2049): the table audits skill rows
only, so a borrowing that lives in code carries no row and is recorded here and
in the module's own docstring. `src/quality/completion_integrity.py` takes its
placeholder evidence values and its negative-case naming vocabulary from
oh-my-openagent (omo), and `src/plugin_bundle/omh/engagement_nudges.py` takes
the shape of omo's `agent-usage-reminder` hook, and the block-quote, relay-header
and URL masks in `src/plugin_bundle/omh/reference_regions.py` take their mask
list from omo's skill-pointer arming guard. omo is published under the
Sustainable Use License 1.0, which is not OSI-approved, so all three are
link-only concept borrowings. The nine skills whose "Why This Exists" line
credits ECC (`affaan-m/everything-claude-code`) were compared section by
section against ECC at `ef648e01899ba3e8dc6371642deaaf64b4477775`; they share a
posture rather than a section structure, a rule list, or ECC's own terms, so
they carry no row. `tests/test_skill_source_attribution_coverage.py` lists each
of them with that reason and fails when a new upstream credit lands without a
row or a listed reason.

## Candidate rows (researched, not yet shipped)

None open: every researched lead has shipped and moved to the table above.

When a new lead is researched, add a row here with the proposed OMH unit, the
upstream repo and paths, the license (checked, not assumed), and the issue
that owns it — then move the row up on the PR that ships it, filling in
`reviewed_on` and `reviewed_ref`.
