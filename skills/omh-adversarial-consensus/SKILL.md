---
name: "omh-adversarial-consensus"
description: "[omh] Technical proposal facing adversarial scrutiny: independent perspectives attack a proposal, then distill into a bundle a separate planner consumes. Use when the user says: adversarial-consensus, adversarial planning, adversarial plan review, red team this plan, red-team this plan, red team the proposal, multi-perspective review, multiple perspectives."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: adversarial-consensus
    role: planner
    quality_tier: reviewed-plan-gated
    related_skills: [ulw-plan, ulw-interview, omh-code-review, ulw-qa]
---

# Adversarial Consensus

This is a Hermes-native `adversarial-consensus` workflow skill.

## Why This Exists

`adversarial-consensus` exists because agreement reached by perspectives that read each other is not review — it is convergence. Independent findings, an attack round nobody is allowed to defend against, and a distillation that may only subtract produce objections a single planning pass never surfaces, and the mandatory handoff keeps that bundle from being mistaken for the plan.

## Do Not Use When

- The user wants the plan itself, with options, acceptance criteria, and verification commands; use `ulw-plan`, which this workflow feeds.
- The request is still too ambiguous to state the proposal being attacked; use `ulw-interview` first.
- The user wants completed code reviewed for defects rather than a proposal attacked before it is built; use `omh-code-review`.
- The user wants hostile runtime scenarios against a built change; use `ulw-qa`.
- One perspective would do: a small local change with no contested decision does not earn three rounds.

## Examples

Good example:

- Prompt: $adversarial-consensus we plan to move session state into Redis before the launch — attack it from every angle before I write the plan.
- Expected behavior: Name the roster and their distinct angles, take blind findings from each, run one attack-only round, resolve each objection to defend/refine/concede, distill only into the four buckets, and hand the bundle to `ralplan` as planning input.
- Why: The decision is contested and pre-plan, which is exactly where independent objections are worth more than one planner's confidence.

Bad example:

- Prompt: $adversarial-consensus give me the migration plan with the steps and the rollout order.
- Expected behavior: Produce the distilled bundle and hand it to `ralplan`; the steps and rollout order are the planner's output, not this workflow's.
- Why: The bundle is INPUT to planning. Emitting a plan here skips the reviewed-plan gate and turns the buckets into a task list.

## Completion Checklist

- The roster is named with 3-5 distinct angles, and no two seats argue the same one.
- Round-one findings were produced blind, and any perspective that could not be kept blind is named as a broken-independence caveat instead of being presented as independent.
- Every cross-attack objection targets another perspective's finding, and no perspective defended itself in that round.
- Every objection carries exactly one verdict — defended, refined, or conceded — and conceded findings are struck, not softened.
- The bundle contains only Hard Constraints, Decisions, Risks, Open Questions, every line traces to a surviving finding, and nothing new was added at distillation.
- The closing message states that the bundle is input, names the follow-on planning workflow, and claims no plan, acceptance, implementation, or verification evidence.

## Recovery Notes

- If the proposal under review cannot be stated in one paragraph, route back to `deep-interview` before opening round one.
- If independence was broken — a perspective saw another's findings, or the same seat produced two angles — say so, re-run that perspective on a restated problem, and mark the round's independence as caveated rather than silently continuing.
- If a round produces no objections at all, treat that as a roster defect rather than consensus: state which angle is missing and add or replace a seat before distilling.
- If distillation would need a fifth bucket, the extra content is a plan trying to escape; move it to the planner handoff instead of widening the bucket set.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `adversarial-consensus`, `codebase-onboarding`, `+8 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a proposal, plan, or direction needs independent perspectives to attack it before a plan is written, and the distilled result is meant as input to planning rather than as the plan.

    Strong routing signals: `adversarial-consensus`, `$adversarial-consensus`, `adversarial planning`, `adversarial plan review`, `red team this plan`, `red-team this plan`, `red team the proposal`, `multi-perspective review`, `multiple perspectives`, `independent perspectives`, `attack this proposal`, `poke holes in this`, `hyperplan`, `敵対的レビュー`, `多角的レビュー`, `レッドチームレビュー`, `この計画に反論`, `穴を探して`, `적대적 검토`, `다관점 검토`, `여러 관점에서 검토`, `레드팀 검토`, `이 계획 반박`, `허점 찾아`, `对抗式评审`, `多视角评审`, `红队评审`, `反驳这个方案`, `找出漏洞`, `kritisi proposal ini dari berbagai sudut pandang`, `cari kelemahan proposal teknis ini`, `uji rencana ini dengan pendekatan red team`, `minta pendapat independen untuk menguji proposal`, `bantu bantah asumsi dalam rancangan ini`, `tinjau proposal secara adversarial`

## Catalog Metadata

Category: `planning`
Phase: `adversarial-consensus`
Hermes role: `planner`
Quality tier: `reviewed-plan-gated`
Reasoning demand: `standard`

Quality bar:

- Name the roster before round one: 3-5 perspectives, each with a stated angle that no other seat covers. The suggested roster is skeptic, validator, researcher, architect, creative; substitute a domain seat when the problem needs one, but two seats arguing the same angle is a duplicate, not a perspective.
- Run the rounds in order — independent findings; cross-attack; defend, refine, or concede — and state which round is active in every message, because the independence rule and the no-self-defense rule only mean anything relative to the current round. Load `references/consensus-protocol.md` for the per-round procedure, the per-seat angle table, and the failure modes that make a run look adversarial while producing agreement.
- Round one is blind: each perspective produces findings without seeing any other perspective's output, and each finding names its evidence or labels itself an assumption.
- Round two attacks only: every perspective attacks other perspectives' findings and never defends or restates its own. A perspective with no objection to any other seat says so explicitly rather than filling the round with agreement.
- Round three answers each objection with exactly one verdict — defend with evidence, refine the finding, or concede it — and a conceded finding is struck from the record instead of being softened.
- The lead distills only. Nothing new enters at distillation: every line in the bundle traces to a surviving finding, and it goes into one of Hard Constraints, Decisions, Risks, Open Questions — never into a fifth bucket, a recommendation, a sequence of steps, or a task list.
- End with the mandatory handoff: state that the bundle is INPUT to planning, name the follow-on planning workflow (`ralplan` for a reviewed plan, `plan` when the shape is already agreed), and stop. Treating the bundle as the plan is the anti-pattern this workflow exists to prevent.
- Keep round transitions and perspective outputs as declarations: a stated round change is not evidence that the round happened, and a distilled bundle is not plan acceptance, implementation, review, CI, or merge evidence.

Handoff policy:

Keep every round in Hermes as prepared prompt contracts. The distilled bundle is planning input: hand it to `ulw-plan` or `omh-plan` for the plan itself, and prepare a selected executor/runtime handoff only after that separate planning pass produces an accepted plan.

Required inputs:

- the proposal, plan draft, or direction under review
- the decision the review must inform
- known constraints and non-negotiables
- the perspective roster and why each angle is distinct

Expected outputs:

- per-perspective independent findings
- cross-attack objections attributed to their author
- defend, refine, or concede verdict per objection
- distilled bundle in the fixed buckets Hard Constraints, Decisions, Risks, Open Questions
- mandatory planner handoff naming the follow-on planning workflow

Artifact expectations:

- record the distilled bundle with `omh hermes plan --record`, which writes `<repo>/.omh/plans/<slug>.md` inside a repository and the user-scope OMH store outside one, so the planner pass consumes a file rather than scrollback

Safety rules:

- Do not write the plan here. This workflow produces the input a planner consumes, never the plan itself.
- Do not let a perspective read another perspective's findings before its own are recorded; a perspective that saw the others is not an independent objection.
- Do not let a perspective defend its own findings during the cross-attack round; that round attacks other perspectives only.
- Do not add, rename, or drop a distillation bucket; the closed set is Hard Constraints, Decisions, Risks, Open Questions.
- Do not invent evidence on behalf of a perspective; an unsupported objection is recorded as an Open Question, not as a Hard Constraint.
- Do not report a round transition, a perspective's output, or the distilled bundle as executed, reviewed, or accepted work; every phase output is a declaration until the user or a wrapper observes it.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill adversarial-consensus --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
