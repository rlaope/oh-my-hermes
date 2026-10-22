---
name: "omh-people-ops"
description: "[omh] Company hiring or HR process to structure: turn hiring and people context into a fair, structured recruiting or people-operations brief. Use when the user says: recruiting plan, hiring scorecard, interview scorecard, candidate debrief, 채용 계획, 면접 평가표, 후보자 비교."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: people-operations
    role: operator
    quality_tier: evidence-gated
    related_skills: [omh-legal-compliance-review, omh-content-operator, omh-apps]
---

# People Ops

This is a Hermes-native `people-ops` workflow skill.

## Why This Exists

`people-ops` keeps recruiting and people-process guidance fair, structured, and evidence bounded before any human decision or external HR action.

## Do Not Use When

- The request asks for a jurisdiction-specific employment-law conclusion, policy compliance ruling, or contract interpretation; use `omh-legal-compliance-review`.
- The user only needs a one-off job-ad, rejection, or interview-email rewrite; use `omh-content-operator`.
- The user asks to create ATS records, send invitations, book interviews, change employment status, or modify HRIS settings; use `omh-apps` with explicit authorization and observed results.
- The prompt asks the workflow to make an unsupported candidate decision from protected characteristics or missing interview evidence; retain the process and evidence gap instead.

## Examples

Good example:

- Prompt: Create an interview scorecard and debrief plan for our first senior support hire.
- Expected behavior: Prepare role criteria, a structured scorecard, a debrief template, and decision-owner plan.
- Why: The request needs a fair hiring-process brief, not a claim that a candidate was evaluated or hired.

Bad example:

- Prompt: Send calendar invitations to every candidate for next Tuesday.
- Expected behavior: Route to `connector-operator`, not `people-ops`.
- Why: Sending invitations is an explicit external calendar action.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a team needs a role brief, hiring plan, interview rubric, candidate-debrief structure, onboarding outline, or people-process decision support.

    Strong routing signals: `recruiting plan`, `hiring scorecard`, `interview scorecard`, `candidate debrief`, `채용 계획`, `면접 평가표`, `후보자 비교`

## Catalog Metadata

Category: `operations`
Phase: `people-operations`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Distinguish role outcomes from proxy criteria and missing evidence.
- Keep inclusion, privacy, policy, and decision-owner gaps visible.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Hermes can prepare fair process guidance and interview artifacts; it cannot claim a candidate was contacted, evaluated, hired, rejected, or recorded in an HR system.

Required inputs:

- role or people-process outcome
- available evidence
- decision owner
- policy constraints

Expert clarification questions:
- `role or people-process outcome`
  - English: What role or people-process outcome should this work achieve?
  - Korean: 이 작업에서 어떤 역할 또는 인사 프로세스 결과를 달성해야 하나요?

Expected outputs:

- role/outcome and must-have versus trainable-criteria brief
- structured interview scorecard and evidence-based debrief template
- hiring-process, interviewer, and decision-owner plan
- inclusion, privacy, policy, and missing-evidence flags with a next route

Artifact expectations:

- prepared people-operations brief when a wrapper captures it

Safety rules:

- Keep protected characteristics and missing interview evidence out of unsupported candidate recommendations.
- Do not claim HRIS, ATS, outreach, interview, or employment-status actions occurred.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill people-ops --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
