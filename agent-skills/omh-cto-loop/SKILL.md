---
name: "omh-cto-loop"
description: "[omh] Engineering leadership over roadmap and risk: roadmap, PM, technical tradeoffs, risk, delivery, release, and follow-up operating cadence. Use when the user says: cto-loop, cto loop, cto, cto pm, pm dev qa security ops, roadmap technical tradeoffs, technical tradeoff, delivery risk."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, leadership]
    category: leadership
    phase: operating-loop
    role: operator
    quality_tier: decision-gated
---

# Cto Loop

This is an OMH `cto-loop` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`cto-loop` exists because roadmap, architecture and release decisions made in chat lose their owners and evidence; it keeps priority, tradeoff, risk and owner separate.

## Do Not Use When

- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; handle it directly or use `omh-decide` for a decision brief instead of starting a leadership operating loop.
- A launch-readiness audit of one named service or release with deploy, security, observability and rollback evidence; use `omh-production-audit`. Prioritisation and risk ranking across workstreams stays here.
- An accepted plan is ready for build; use `ulw-plan` or `omh-idea-to-deploy`.

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



## When to Use

Use when Hermes should run a leadership-style operating loop that turns signals into roadmap decisions, technical tradeoffs, delivery risk, release readiness, and explicit follow-up handoffs.

    Strong routing signals: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`, `technical leadership loop`, `leadership operating loop`, `engineering leadership`, `CTO 구조`, `PM 구조`, `로드맵`, `아키텍처 트레이드오프`, `기술 리더십`, `출시 준비`

## Catalog Metadata

Category: `leadership`
Phase: `operating-loop`
Quality tier: `decision-gated`
Reasoning demand: `heavy`

Quality bar:

- Separate product priority, architecture tradeoff, delivery risk, release risk, and follow-up owner.
- Tie recommendations to observed signals or mark assumptions.
- Record accepted decisions separately from draft recommendations.
- Prepare executor handoffs only for accepted implementation follow-ups.
- A release decision lists, with evidence or not_observed: tested rollback, staged rollout, alerts and an on-call owner, security review outcome, open severity-1/2 defects, and for billing a ledger reconciliation; each residual risk has a named accepter.

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
