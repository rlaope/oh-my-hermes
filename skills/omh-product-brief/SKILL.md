---
name: omh-product-brief
description: [omh] Turn product evidence into a decision-ready PRD, prioritization frame, and roadmap brief. Use when the user says: product requirements document, PRD, roadmap prioritization, 제품 요구사항 문서, 제품 기획서, 로드맵 우선순위.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: product-brief
    role: planner
    quality_tier: planning-gated
---

# Product Brief

This is a Hermes-native `product-brief` workflow skill.

## Why This Exists

`product-brief` turns product evidence into a reviewable PRD and prioritization frame before delivery planning without treating a draft as an accepted roadmap commitment.

## Do Not Use When

- The input is unprocessed feedback, bug reports, or feature asks that first need clustering and evidence boundaries; use `feedback-triage`.
- The user needs a company or product strategy decision across high-level options rather than a requirements or roadmap artifact; use `strategy-brief`.
- The request is an accepted, code-ready change with repository constraints and verification needs; use `ralplan` or `ultrawork` rather than recreating a PRD.
- The user asks to create or update Jira, Linear, Aha!, or a roadmap system directly; use `connector-operator` with explicit target, approval, and observed evidence.

## Examples

Good example:

- Prompt: Create a PRD and prioritization options for reducing first-time user drop-off in onboarding.
- Expected behavior: Prepare the product problem, user and metric brief, PRD, roadmap options, tradeoffs, and downstream prerequisites.
- Why: The request needs a decision-ready requirements and prioritization artifact before delivery planning.

Bad example:

- Prompt: Implement the accepted onboarding PRD and open a PR.
- Expected behavior: Route to `ultrawork` or `ralplan`, not `product-brief`.
- Why: Accepted implementation work should move into planning or delivery rather than recreate a PRD.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If acceptance criteria or verification are missing, route back to clarification before handoff.
- If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when a product owner needs a problem frame, user/outcome definition, PRD, prioritization/roadmap options, dependencies, acceptance shape, and decision record before delivery planning.

    Strong routing signals: `product requirements document`, `PRD`, `roadmap prioritization`, `제품 요구사항 문서`, `제품 기획서`, `로드맵 우선순위`

## Catalog Metadata

Category: `planning`
Phase: `product-brief`
Hermes role: `planner`
Quality tier: `planning-gated`
Reasoning demand: `standard`

Quality bar:

- Name problem, user, metric, goals, non-goals, requirements, dependencies, risks, and acceptance shape.
- Preserve decision owner and downstream prerequisite boundaries.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. A PRD or roadmap is prepared planning, not stakeholder acceptance, Jira or Linear mutation, implementation, test evidence, delivery, or a market commitment.

Required inputs:

- product evidence
- problem and user
- goal and non-goals
- decision owner

Expert clarification questions:
- `product evidence`
  - English: What product evidence should anchor this brief?
  - Korean: 이 브리프의 근거가 될 제품 증거는 무엇인가요?

Expected outputs:

- problem, user, evidence, metric, goal, and non-goal brief
- PRD with requirements, open questions, risks, dependencies, and acceptance shape
- prioritization/roadmap options with tradeoffs and decision owner
- explicit downstream route to ralplan, strategy-brief, or ultrawork only when its prerequisite is satisfied

Artifact expectations:

- prepared product brief or PRD when a wrapper captures it

Safety rules:

- Separate product evidence, assumptions, prioritization options, and stakeholder acceptance.
- Do not claim roadmap-system mutation, implementation, test evidence, delivery, or market commitment.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill product-brief --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
