---
name: "omh-decide"
description: "[omh] Team or business decision between options: tradeoffs, a recommendation, and a decision note you can act on. Use when the user says: strategy-brief, strategy brief, strategy memo, product strategy, strategic options, decision note, leadership strategy, next strategy."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: brief
    role: operator
    quality_tier: decision-gated
    related_skills: [omh-product-discovery-validation, omh-people-ops, omh-jev-ask]
---

# Strategy Brief

This is a Hermes-native `strategy-brief` workflow skill.

## Why This Exists

`strategy-brief` exists to keep `strategy` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The strategic question is whether an early idea's customer problem and segment are real, and no validated discovery receipt exists yet; use `omh-product-discovery-validation`.
- The question is how to run a hiring process — scorecards, interview loops, candidate comparison — rather than whether to hire at all; use `omh-people-ops`.
- The user wants Jev's typed probabilities for a yes/no, pick-one, or scored question over supplied text rather than tradeoffs and a recommendation; use `omh-jev-ask`.

## Examples

Good example:

- Prompt: strategy-brief: decide whether our onboarding should prioritize solo founders or enterprise buyers.
- Expected behavior: Frame options, tradeoffs, assumptions, rejected paths, and the decision evidence needed.
- Why: The request is strategy-shaped and should not jump directly into implementation.

Bad example:

- Prompt: strategy-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `strategy-brief`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The decision, options, tradeoffs, assumptions, and rejected alternatives are named.
- Observed signals are separated from strategic inference.
- Accepted decisions and implementation follow-ups are not conflated.

## Recovery Notes

- If evidence is mostly assumption, label it and recommend a research or feedback-triage pass.
- If the decision owner is missing, keep the output as options rather than accepted strategy.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should turn goals and evidence into options, tradeoffs, recommendations, and a decision-ready brief.

    Strong routing signals: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `capacity planning`, `hire or outsource`, `outsource or hire`, `cut scope`, `headcount plan`, `demand versus capacity`, `다음 전략`, `전략 정리`, `전략 메모`, `전략 옵션`, `의사결정`, `리더십 회의`

## Catalog Metadata

Category: `strategy`
Phase: `brief`
Hermes role: `operator`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Name the decision, constraints, options, tradeoffs, and rejected alternatives.
- Tie recommendations to observed evidence or mark them as assumptions.
- Keep coding handoff disabled until strategy is accepted and code work is explicit.
- When the decision is a resourcing one — hire, outsource, or cut scope — quantify demand and capacity against each other in one unit before comparing options, and price each option with the lag before it lands; a gap that exists this quarter is not closed by a hire that ramps next quarter. The worked example is `omh-decide/references/capacity-planning.md`.
- Ask whether the decision deserves a durable record - hard to reverse, surprising without its context, and carrying a real trade-off; all three or no record, a decision note in chat is enough.
- When a record is warranted, draft it per `omh-decide/references/decision-records.md` - the `docs/adr/` convention with Context, Drivers, Considered Options, Decision, Consequences with mitigations, and Related - and stop for the user's approval before any file is written.
- Never edit an accepted record: status moves Proposed to Accepted to Deprecated or Superseded, supersession is a new record pointing back at the old one, and a Rejected record is kept - it is what `decision-recall` reads later.

Handoff policy:

Keep strategy synthesis in Hermes; do not create implementation handoff until a decision is accepted and code work is explicit.

Required inputs:

- goal
- known evidence
- constraints
- decision owner

Expected outputs:

- options
- tradeoffs
- recommended direction
- decision note

Artifact expectations:

- strategy brief or decision note when a wrapper captures it

Safety rules:

- Do not treat a draft recommendation as an accepted decision.
- Keep unresolved assumptions visible.
- Separate strategy from implementation planning unless the user asks for execution.
- A drafted decision record stays a proposal: nothing is written under `docs/adr/` until the user approves the write.

## Runtime Evidence

Preferred harness for this skill: `strategy-synthesis`.

```sh
omh runtime record --skill strategy-brief --harness strategy-synthesis --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
