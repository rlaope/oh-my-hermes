---
name: "omh-cto-loop"
description: "[omh] Engineering leadership over roadmap and risk: roadmap, PM, technical tradeoffs, risk, delivery, release, and follow-up operating cadence. Use when the user says: cto-loop, cto loop, cto, cto pm, pm dev qa security ops, roadmap technical tradeoffs, technical tradeoff, delivery risk."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, leadership]
    category: leadership
    phase: operating-loop
    role: operator
    quality_tier: decision-gated
    related_skills: [omh-decide, omh-production-audit]
---

# Cto Loop

This is a Hermes-native `cto-loop` workflow skill.

## Why This Exists

`cto-loop` exists because roadmap, architecture and release decisions made in chat lose their owners and evidence; it keeps priority, tradeoff, risk and owner separate.

## Do Not Use When

- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; handle it directly or use `omh-decide` for a decision brief instead of starting a leadership operating loop.
- A launch-readiness audit of one service; use `omh-production-audit`.

## Examples

Good example:

- Prompt: cto-loop: run the PM, dev, QA, security, and ops loop for this risky billing launch.
- Expected behavior: Prepare the CTO operating model with role responsibilities, gates, blockers, and status boundaries.
- Why: The request needs a leadership operating loop, not just a generic plan.

Bad example:

- Prompt: Tell me whether we should rewrite the billing service in Rust.
- Expected behavior: Route to `omh-decide`, not `cto-loop`: one decision between options is a decision brief.
- Why: A single decision with options does not need a multi-function leadership operating loop.

## Completion Checklist

- Priority, tradeoff, delivery and release risk are separate rows.
- Each risk has an owner and source or is marked assumption; accepted decisions and drafts are separate lists.

## Recovery Notes

- If operating signals do not support an architecture tradeoff, retain the cited signals, mark that tradeoff tentative, and hand back the decision note with assumptions and delivery risks.
- If the decision owner has not accepted implementation follow-ups, retain the priority frame and risk ranking, mark follow-up authority unresolved, and hand back the decision note and handoff candidates for acceptance.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+28 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should run a leadership-style operating loop that turns signals into roadmap decisions, technical tradeoffs, delivery risk, release readiness, and explicit follow-up handoffs.

    Strong routing signals: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`, `technical leadership loop`, `leadership operating loop`, `engineering leadership`, `CTO 구조`, `PM 구조`, `로드맵`, `아키텍처 트레이드오프`, `기술 리더십`, `출시 준비`

## Catalog Metadata

Category: `leadership`
Phase: `operating-loop`
Hermes role: `operator`
Quality tier: `decision-gated`
Reasoning demand: `heavy`

Quality bar:

- Separate product priority, architecture tradeoff, delivery risk, release risk, and follow-up owner.
- Tie recommendations to observed signals or mark assumptions.
- Record accepted decisions separately from draft recommendations.
- Prepare executor handoffs only for accepted implementation follow-ups.
- A release decision lists, with evidence or not_observed: tested rollback, staged rollout, alerts and an on-call owner, security review outcome, open severity-1/2 defects, and for billing a ledger reconciliation; each residual risk has a named accepter.

Handoff policy:

Keep CTO/PM-style synthesis, tradeoffs, risk ranking, decision notes, and status in Hermes; convert accepted implementation follow-ups into executor-neutral handoffs.

Required inputs:

- operating signals
- roadmap or release scope
- known risks
- decision owner

Expected outputs:

- priority frame
- architecture tradeoffs
- delivery risks
- decision note
- follow-up handoff candidates

Artifact expectations:

- leadership loop record or status summary when a wrapper captures decisions and follow-ups

Safety rules:

- Do not treat a CTO loop recommendation as an accepted roadmap decision.
- Do not imply CTO, PM, QA, Security, or Ops runtime agents exist without observed wrapper evidence.
- Separate strategy decisions from implementation handoffs and release evidence.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

```sh
omh runtime record --skill cto-loop --harness app-delivery-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
