---
name: "omh-decide"
description: "[omh] Decide between options: tradeoffs, a recommendation, and a decision note you can act on. Use when the user says: strategy-brief, strategy brief, strategy memo, product strategy, strategic options, decision note, leadership strategy, next strategy."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: brief
    role: operator
    quality_tier: decision-gated
---

# Strategy Brief

This is an OMH `strategy-brief` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`strategy-brief` exists to keep `strategy` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The strategic question is whether an early idea's customer problem and segment are real, and no validated discovery receipt exists yet; use `product-discovery-validation`.
- The question is how to run a hiring process — scorecards, interview loops, candidate comparison — rather than whether to hire at all; use `people-ops`.

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



## Use When

Use when Hermes should turn goals and evidence into options, tradeoffs, recommendations, and a decision-ready brief.

    Strong routing signals: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `capacity planning`, `hire or outsource`, `outsource or hire`, `cut scope`, `headcount plan`, `demand versus capacity`, `다음 전략`, `전략 정리`, `전략 메모`, `전략 옵션`, `의사결정`, `리더십 회의`

## Catalog Metadata

Category: `strategy`
Phase: `brief`
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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Report actual tool results or
`not_observed` / `not_available`; never invent dispatch or host accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
