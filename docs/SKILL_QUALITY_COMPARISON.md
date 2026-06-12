# OMH Skill Quality Comparison Against Oh My Codex

Date: 2026-06-11

## Scope

This report compares the repository-root OMH skill set against the open-source
Oh My Codex (OMX) skill set.

Evidence used:

- OMH repository: `67aa040` plus this skill-rubric working tree
- OMH skill source: `skills/*/SKILL.md`, `src/skills/catalog.py`,
  `docs/HARNESS_QUALITY.md`, `docs/WORKFLOWS.md`
- OMX upstream repository at `0332e47`
  (`ci: configure npm auth for manual publish (#2766)`)
- OMX skill source: `/tmp/omx-compare/skills/*/SKILL.md`,
  `/tmp/omx-compare/templates/AGENTS.md`,
  `/tmp/omx-compare/docs/skills.html`

The comparison focuses on skill quality as agent-facing product surface:
discoverability, routing clarity, execution fidelity, evidence discipline,
maintainability, and reviewability.

## Executive Summary

OMH skills are more consistent and safer as Hermes-native wrapper guidance.
They have stronger metadata, harness quality contracts, evidence boundaries,
artifact expectations, and generated consistency. That makes them a better fit
for Hermes TUI discovery, chat-wrapper rendering, and avoiding overclaims such
as treating a prepared handoff as observed work.

OMX skills are stronger as direct Codex execution protocols. The best OMX
skills read like executable operating manuals: they include when not to use the
mode, why the mode exists, phase-level steps, state management, examples, final
checklists, and detailed recovery rules. Their weak point is unevenness: some
skills are rich and operational, while others are short deprecated shims or
thin aliases.

The main OMH gap was not safety or catalog quality. The gap was per-skill
specificity: prior generated skills had reliable wrapper contracts, but weak
negative routing boundaries, few concrete examples, and little explanation of
why a skill exists. This PR closes the largest catalog-level gap by generating
`Why This Exists`, `Do Not Use When`, and good/bad examples for every skill,
with bespoke examples for the flagship workflows.

## Measured Inventory

| Surface | Skill count | Average lines | Median lines | Shortest | Longest |
| --- | ---: | ---: | ---: | ---: | ---: |
| OMH repo-root skills | 30 | 128.8 | 125 | 120 | 217 |
| OMX open-source skills | 46 | 156.8 | 110 | 11 | 837 |

Common skill names: 18

`ai-slop-cleaner`, `ask`, `autoresearch-goal`, `best-practice-research`,
`cancel`, `code-review`, `deep-interview`, `doctor`, `performance-goal`,
`plan`, `ralph`, `ralplan`, `skill`, `team`, `ultragoal`, `ultraqa`,
`ultrawork`, `wiki`

OMH-only skills: 12

`cto-loop`, `deploy-and-monitor`, `feedback-triage`, `idea-to-deploy`, `loop`,
`meeting-brief`, `oh-my-hermes`, `ops-review`, `research-brief`,
`strategy-brief`, `ultraprocess`, `web-research`

OMX-only skills: 28

`analyze`, `ask-claude`, `ask-gemini`, `autopilot`, `autoresearch`,
`build-fix`, `configure-notifications`, `deepsearch`, `design`, `ecomode`,
`frontend-ui-ux`, `git-master`, `help`, `hud`, `note`, `omx-setup`,
`pipeline`, `prometheus-strict`, `ralph-init`, `review`, `security-review`,
`swarm`, `tdd`, `trace`, `visual-ralph`, `visual-verdict`, `web-clone`,
`worker`

## Structural Feature Coverage

| Quality feature | OMH | OMX | Interpretation |
| --- | ---: | ---: | --- |
| Frontmatter description | 30 / 30 | 46 / 46 | Both are discoverable. OMH descriptions are additionally namespaced with `[omh]`. |
| `Use When` style activation guidance | 30 / 30 | 11 / 46 | OMH is now consistent for skill picker routing. |
| `Do Not Use When` guidance | 30 / 30 | 14 / 46 | OMH now has broader negative routing coverage; OMX remains deeper in some hand-authored modes. |
| Explicit purpose or why section | 30 / 30 | 16 / 46 | OMH now exposes a generated reason for every skill. |
| Step or execution procedure | 29 / 30 | 17 / 46 | OMH has procedure stubs everywhere; OMX has deeper procedures in fewer skills. |
| State management guidance | 30 / 30 | 26 / 46 | OMH is broad; OMX is deeper for stateful modes. |
| Examples or good/bad patterns | 30 / 30 | 5 / 46 | OMH now has examples everywhere; flagship skills have bespoke good/bad examples. |
| Final checklist | 0 / 30 | 7 / 46 | OMX is stronger for completion discipline in major workflows. |
| Quality bar | 29 / 30 | 1 / 46 | OMH is much stronger at machine-readable quality contracts. |
| Harness/runtime evidence language | 30 / 30 | 15 / 46 | OMH is stronger for wrapper-safe evidence rendering. |
| Safety rules | 29 / 30 | 0 / 46 | OMH is stronger at anti-overclaim framing. |
| Artifact expectations | 30 / 30 | 18 / 46 | OMH is stronger at prepared vs observed artifact boundaries. |

## Quality Scorecard

Scores are relative to the intended product shape, not generic skill length.

| Dimension | OMH | OMX | Notes |
| --- | ---: | ---: | --- |
| TUI and skill-picker discoverability | 9 | 7 | OMH has uniform metadata, `[omh]` descriptions, category, phase, role, and quality tier. |
| Routing clarity | 8 | 7 | OMH has strong positive triggers; OMX has better negative boundaries. |
| Execution specificity | 5 | 9 | OMX deep modes such as `deep-interview`, `team`, and `skill` are operational runbooks. OMH often stays generic. |
| Evidence discipline | 9 | 7 | OMH consistently separates prepared, requested, observed, and not-observed states. |
| Runtime-state depth | 6 | 9 | OMH names state artifacts; OMX often gives exact state commands, schemas, phases, and recovery rules. |
| Maintainability | 9 | 6 | OMH generated catalog plus tests prevents drift. OMX is powerful but uneven and hand-authored. |
| User/operator explanation | 7 | 8 | OMH is clearer for wrapper status; OMX is clearer for "what do I do now" in advanced modes. |
| Example quality | 6 | 7 | OMH now has generated examples everywhere and bespoke examples for flagship skills; OMX still has deeper long-form examples in some execution modes. |
| Coverage breadth | 7 | 9 | OMX covers more Codex-native roles and utility modes. OMH adds business/Hermes wrapper lanes OMX does not target. |
| Product fit for Hermes Agent | 9 | 5 | OMH avoids pretending Hermes is a hidden executor and adapts to Hermes-native surfaces. |

Overall:

- OMH: strong B+ today, A- for wrapper safety and catalog discipline.
- OMX: A- for Codex-native execution protocol, B for consistency across the full catalog.

## What OMH Does Better

### 1. Generated consistency

OMH skills are generated from catalog data and locked by tests. The repo has a
root tap-skill equality test that compares `skills/*/SKILL.md` with generated
templates. This means catalog updates, docs, and installable skills move
together instead of drifting.

Impact: safer release behavior and fewer stale skill files.

### 2. Hermes-native product boundary

OMH skills repeatedly state that Hermes should orchestrate, clarify, research,
plan, and narrate status, while coding work becomes selected executor/runtime handoff
evidence. This is aligned with the project direction and prevents the most
dangerous wrapper error: claiming implementation, review, CI, or merge evidence
from a prepared prompt.

Impact: better trust model for chat users and wrappers.

### 3. Harness quality contracts

OMH has `harness_quality/v1` and a workflow reference that exposes quality
tiers, quality bars, wrapper actions, evidence ladders, and overclaim guards.
OMX has strong runtime mode state for Codex, but it does not expose an
equivalent wrapper-oriented quality contract across the skill catalog.

Impact: stronger downstream UI and status-card integration.

### 4. Business and company workflow coverage

OMH includes skills such as `meeting-brief`, `feedback-triage`,
`strategy-brief`, `ops-review`, `cto-loop`, `idea-to-deploy`, and
`deploy-and-monitor`. These are not just coding modes; they position Hermes as
work-context orchestration for business workflows.

Impact: OMH has a broader non-coding product story than OMX.

## What OMX Does Better

### 1. Deep mode-specific runbooks

OMX's strongest skills are not just descriptions. They are executable
protocols. Examples:

- `deep-interview` has depth profiles, ambiguity thresholds, preflight context
  intake, one-question rules, state persistence, and handoff criteria.
- `team` explains tmux preconditions, launch contracts, worker lifecycle,
  Ultragoal bridging, and coordination gates.
- `ultrawork` has explicit acceptance criteria, self-vs-delegate rules,
  examples, final checklist, and stop conditions.

OMH equivalents are safer for Hermes but usually shorter and more generic.

Impact: OMX is easier for an execution agent to follow without hidden context.

### 2. Negative routing boundaries

OMX frequently says when not to use a skill. Before this PR, OMH mostly said
when to use it. That created ambiguity when two OMH workflows were plausible,
for example:

- `loop` vs `ultraprocess`
- `ralph` vs `ultragoal`
- `research-brief` vs `web-research` vs `best-practice-research`
- `ops-review` vs `deploy-and-monitor`

Impact: the new generated `Do Not Use When` sections give OMH broader
negative routing boundaries while preserving its catalog consistency.

### 3. Examples and completion checklists

OMX includes good/bad examples and final checklists in important modes. OMH
now has generated good/bad examples for every skill and bespoke examples for
the flagship workflows, but still lacks mode-specific final checklists.

Impact: OMH now gives much better first-read intuition in the TUI, while the
next quality jump is richer per-mode completion and recovery guidance.

### 4. Recovery and stale-state handling

OMX skills often address stale state, resume behavior, cancellation, and
runtime preconditions directly inside the skill. OMH mentions runtime evidence
and wrapper state, but many skills do not yet explain recovery paths in
mode-specific terms.

Impact: OMH has the right evidence model but weaker operator recovery guidance.

## Implemented In This PR

### P0: Add generated `Why This Exists`

Status: implemented.

This PR adds a `why_this_exists` field to `SkillDefinition` and renders it into
every skill. It explains the product problem in one paragraph instead of
repeating the description.

Example:

```text
`feedback-triage` exists because customer input often arrives as mixed bugs,
feature requests, strategy signals, and support noise. The workflow clusters
that signal without pretending it is an accepted roadmap or implemented fix.
```

Effect: better TUI comprehension and better PR-style feature reporting.

### P0: Add generated `Do Not Use When`

Status: implemented.

This PR adds a `do_not_use_when` tuple to the catalog and renders it near
`Use When`. Flagship workflows get skill-specific negative routing boundaries;
non-flagship workflows receive a conservative generated fallback.

High-priority pairs:

- `loop` should not be used for one PR-ready delivery cycle; use
  `ultraprocess`.
- `ultraprocess` should not be used for ongoing north-star iteration; use
  `loop`.
- `ultrawork` should not be used when lanes are not disjoint; use a single
  executor or `ultragoal`.
- `web-research` should not be used when the source is repo-local only; use
  `research-brief` or normal repo inspection.
- `meeting-brief` should not claim meeting outcomes; it only prepares the
  agenda and record template.

Effect: lower accidental route collisions.

### P0: Add examples for flagship skills

Status: implemented with full coverage.

This PR renders generated good/bad examples for all 30 skills and bespoke
examples for high-confusion, high-value workflows:

- `oh-my-hermes`
- `loop`
- `ultraprocess`
- `ultragoal`
- `ultrawork`
- `deep-interview`
- `code-review`
- `doctor`
- `feedback-triage`
- `meeting-brief`

Each should have one good example and one bad example. The examples should
show:

- user prompt shape
- chosen workflow
- evidence boundary
- stop condition

Effect: much better TUI learning and lower agent overreach.

### P0: Add a skill quality rubric test

Status: implemented.

The router/content tests now lock the minimum quality schema across the full
catalog and add a stricter flagship rubric that rejects placeholder examples.

Effect: future additions cannot regress to thin generated prose.

## Remaining High-Value Improvements

### P1: Split generic compatibility text from skill-specific guidance

The generated skills repeat a long Hermes compatibility section. Keep the
contract, but make the top half of each skill more distinct:

1. One-line capability summary
2. Why this exists
3. Use when
4. Do not use when
5. Evidence boundary
6. Skill-specific runbook
7. Shared compatibility contract

Expected effect: users see what makes a skill unique before reading generic
wrapper rules.

### P1: Add mode-specific state and recovery guidance

For durable or runtime-sensitive skills, add compact recovery notes:

- `loop`: where loop cycle artifacts live, what a queued tick is not, how to
  resume after context exhaustion.
- `ultragoal`: completion gate, checkpoint evidence, blocker handling.
- `doctor`: what to inspect first for install, setup, tap, plugin bridge, and
  Hermes registration failures.
- `team` and `ultrawork`: what to do when parallel lanes are not truly
  independent.

Expected effect: closer to OMX's operational depth without making Hermes a
hidden Codex runtime.

### P2: Add an installed-surface comparison doc

OMX open-source and local installed skill inventories can expose different
managed-skill counts. OMH should document which skills are public, internal,
compatibility-only, deprecated, or not installed by default.

Expected effect: less confusion between repository inventory and user-visible
TUI inventory.

## Suggested Target Bar

OMH does not need to copy OMX's full Codex-native execution depth. The target
should be:

```text
OMX-level operational clarity
+ OMH-level wrapper safety
+ Hermes-native evidence boundaries
+ business workflow coverage
```

For each flagship OMH skill, the reader should understand within 60 seconds:

1. What this workflow is for.
2. Why it exists.
3. When not to use it.
4. What artifact or state it may produce.
5. What it must not claim as observed evidence.
6. What the next user/operator action looks like.

## Recommended Next PR

The highest leverage next PR is mode-specific operational depth:

1. Add compact final checklists to `loop`, `ultraprocess`, `ultragoal`,
   `ultrawork`, `doctor`, and `code-review`.
2. Add recovery notes for stale goal state, queued loop ticks, non-disjoint
   parallel lanes, and setup/doctor repair paths.
3. Keep the shared Hermes compatibility contract generated, but move more
   distinctive guidance into skill-specific runbooks.
4. Add tests that flagship skills include completion and recovery guidance
   without duplicating long generic runtime text.

This would close the next practical quality gap against OMX while preserving
OMH's strongest difference: Hermes-native wrapper discipline.
