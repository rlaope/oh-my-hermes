---
name: "omh-product-brief"
description: "[omh] PRD or roadmap priorities to decide: turn product evidence into a decision-ready PRD, prioritization frame, and roadmap brief. Use when the user says: product requirements document, PRD, roadmap prioritization, 제품 요구사항 문서, 제품 기획서, 로드맵 우선순위."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: product-brief
    role: planner
    quality_tier: planning-gated
    related_skills: [omh-feedback-triage, omh-product-discovery-validation, omh-lifecycle-growth, omh-decide, ulw-plan, ulw-work, omh-apps]
---

# Product Brief

Required: product evidence, problem and user, goal, non-goals, and success metric with baseline, decision owner, capacity or effort constraints. Output: problem, user, evidence, metric, goal, and non-goal brief, PRD with requirements, open questions, risks, dependencies, and acceptance shape, prioritization/roadmap options with tradeoffs and decision owner, explicit downstream route to `ulw-plan`, `omh-decide`, or `ulw-work` only when its prerequisite is satisfied.

## Why This Exists

`product-brief` turns product evidence into a reviewable PRD and prioritization frame before delivery planning without treating a draft as an accepted roadmap commitment.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Intent -> plan** - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

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

Expert clarification questions:
- `product evidence`
  - English: What product evidence should anchor this brief?
  - Korean: 이 브리프의 근거가 될 제품 증거는 무엇인가요?

Safety rules:

- Separate product evidence, assumptions, prioritization options, and stakeholder acceptance.
- Do not claim roadmap-system mutation, implementation, test evidence, delivery, or market commitment.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If the evidence is not external-human or behavioral-data evidence from the target segment, retain it as unvalidated, mark PRD readiness unresolved, and hand back the problem and user context to `omh-product-discovery-validation`.
- If the decision owner has not resolved prioritization tradeoffs, retain the drafted PRD and roadmap options, mark roadmap commitment unresolved, and hand back the tradeoffs and open questions for that owner.
- If Jira or Linear updates lack an explicit target and approval, retain the prepared PRD, mark roadmap-system mutation not_observed, and hand back the target and approval questions for `omh-apps`.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill product-brief --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
