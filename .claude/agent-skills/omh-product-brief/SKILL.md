---
name: "omh-product-brief"
description: "[omh] PRD or roadmap priorities to decide: turn product evidence into a decision-ready PRD, prioritization frame, and roadmap brief."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: product-brief
    role: planner
    quality_tier: planning-gated
---

# Product Brief

This is an OMH `product-brief` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`product-brief` turns product evidence into a reviewable PRD and prioritization frame before delivery planning without treating a draft as an accepted roadmap commitment.

## Do Not Use When

- The input is unprocessed feedback, bug reports, or feature asks that first need clustering and evidence boundaries; use `omh-feedback-triage`.
- The product evidence is unvalidated, synthetic, or a founder belief rather than external-human or behavioral-data evidence from the target segment (usage data, support contacts and interviews count); use `omh-product-discovery-validation` before a PRD.
- The input is a growth hypothesis that still needs an experiment and readout before it becomes a product requirement; use `omh-lifecycle-growth`.
- The user needs a company or product strategy decision across high-level options rather than a requirements or roadmap artifact; use `omh-decide`.
- The request is an accepted, code-ready change with repository constraints and verification needs; use `ulw-plan` or `ulw-work` rather than recreating a PRD.
- The user asks to create or update Jira, Linear, Aha!, or a roadmap system directly; use `omh-apps` with explicit target, approval, and observed evidence.

## Examples

Good example:

- Prompt: Create a PRD and prioritization options for reducing first-time user drop-off in onboarding.
- Expected behavior: Prepare the product problem, user and metric brief, PRD, roadmap options, tradeoffs, and downstream prerequisites.
- Why: The request needs a decision-ready requirements and prioritization artifact before delivery planning.

Bad example:

- Prompt: Implement the accepted onboarding PRD and open a PR.
- Expected behavior: Route to `ulw-work` or `ulw-plan`, not `product-brief`.
- Why: Accepted implementation work should move into planning or delivery rather than recreate a PRD.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If the evidence is not external-human or behavioral-data evidence from the target segment, retain it as unvalidated, mark PRD readiness unresolved, and hand back the problem and user context to `omh-product-discovery-validation`.
- If the decision owner has not resolved prioritization tradeoffs, retain the drafted PRD and roadmap options, mark roadmap commitment unresolved, and hand back the tradeoffs and open questions for that owner.
- If Jira or Linear updates lack an explicit target and approval, retain the prepared PRD, mark roadmap-system mutation not_observed, and hand back the target and approval questions for `omh-apps`.



## When to Use

Use when a product owner needs a problem frame, user/outcome definition, PRD, prioritization/roadmap options, dependencies, acceptance shape, and decision record before delivery planning.

    Strong routing signals: `product requirements document`, `PRD`, `roadmap prioritization`, `제품 요구사항 문서`, `제품 기획서`, `로드맵 우선순위`

## Catalog Metadata

Category: `planning`
Phase: `product-brief`
Quality tier: `planning-gated`
Reasoning demand: `standard`

Quality bar:

- Name problem, user, metric, goals, non-goals, requirements, dependencies, risks, and acceptance shape.
- Preserve decision owner and downstream prerequisite boundaries.

Required inputs:

- product evidence
- problem and user
- goal, non-goals, and success metric with baseline
- decision owner
- capacity or effort constraints

Expert clarification questions:
- `product evidence`
  - English: What product evidence should anchor this brief?
  - Korean: 이 브리프의 근거가 될 제품 증거는 무엇인가요?

Expected outputs:

- problem, user, evidence, metric, goal, and non-goal brief
- PRD with requirements, open questions, risks, dependencies, and acceptance shape
- prioritization/roadmap options with tradeoffs and decision owner
- explicit downstream route to `ulw-plan`, `omh-decide`, or `ulw-work` only when its prerequisite is satisfied

Artifact expectations:

- prepared product brief or PRD when a wrapper captures it

Safety rules:

- Separate product evidence, assumptions, prioritization options, and stakeholder acceptance.
- Do not claim roadmap-system mutation, implementation, test evidence, delivery, or market commitment.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
