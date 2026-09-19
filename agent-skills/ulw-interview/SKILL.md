---
name: "ulw-interview"
description: "[omh] Hermes Deep Interview workflow: one-question-at-a-time clarification. Use when the user says: deep-interview, interview me, clarify, feature shaping, ambiguous product request, one question, 要件を詰めて, 曖昧な要求."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, clarification]
    category: clarification
    phase: discovery
    role: planner
    quality_tier: clarity-gated
---

# Deep Interview

This is an OMH `deep-interview` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`deep-interview` exists to stop the host from guessing through ambiguous product, workflow, or implementation intent; it converts uncertainty into a clarified brief before planning or handoff.

## Do Not Use When

- The request already has concrete scope, acceptance criteria, and verification commands.
- The missing information is discoverable from the repository or local artifacts without asking the user.
- The user asked for immediate read-only analysis and the ambiguity does not change the answer.
- The ambiguity is specifically repository terminology or project-language alignment; use `context` and its direct-lookup/frontier boundary.
- The open question is answerable by a small reversible experiment rather than another interview round; use `decision-prototype`.

## Examples

Good example:

- Prompt: $deep-interview before planning Discord and Slack routing, ask what each channel owns and what evidence counts.
- Expected behavior: Ask one decision-changing question at a time, then produce goals, non-goals, and acceptance criteria.
- Why: The request explicitly rejects assumptions and needs product boundaries before implementation.

Bad example:

- Prompt: $deep-interview fix this failing test; the traceback and expected behavior are attached.
- Expected behavior: Proceed to diagnosis or implementation instead of interviewing.
- Why: The required facts are already available, so more questions would slow the workflow.

## Completion Checklist

- The clarified brief names goals, non-goals, constraints, and one next planning or handoff path.
- Remaining ambiguity is listed only when it changes the plan, risk, or stop condition.
- No implementation handoff is prepared until the blocking decision is resolved.

## Recovery Notes

- If an answer surfaces new ambiguity, file it under one of the three clarity dimensions and keep asking only while the round budget allows; once round 6 is reached, record the rest as assumptions and plan.
- If repo evidence can answer the question, inspect it before asking the user.



## Use When

Use before planning or execution when requirements are materially ambiguous.

    Strong routing signals: `deep-interview`, `$deep-interview`, `interview me`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `要件を詰めて`, `曖昧な要求`, `一問一答で確認`, `オンボーディング`, `온보딩`, `부드럽게`, `모호한 제품 요청`, `기획자`, `개발자 사이`, `澄清需求`, `需求不明确`, `一次问一个问题`

## Catalog Metadata

Category: `clarification`
Phase: `discovery`
Quality tier: `clarity-gated`
Reasoning demand: `light`

Quality bar:

- Ask exactly one blocking question per turn unless the wrapper explicitly supports a structured batch.
- Offer two to four candidate answers plus a free-input option with every question, and accept free text over the list at any time.
- Tie each question to a missing decision that changes the plan, handoff, or stop condition.
- Before the first question, load `references/ambiguity-taxonomy.md` and score every category Clear/Partial/Missing, then spend the round budget worst-first and write each accepted answer back into the artifact being clarified.
- Emit a clarified brief with non-goals and acceptance criteria before planning or delegation.

Required inputs:

- initial request
- known repo facts
- current ambiguity

Expected outputs:

- clarified brief
- non-goals
- decision boundaries

Artifact expectations:

- A host-owned clarity summary: outcome, constraints/non-goals, and success criteria are the three fixed dimensions; report resolved/3, never an expanding denominator.
- Track the round in the current thread, ask one decision-changing question with two to four candidate answers plus free input, and honor the catalog round ceiling. Stop on clarity, user stop, or budget exhaustion; summarize unresolved assumptions rather than restarting after lost context. Summary confirmation is not execution approval.

Safety rules:

- Ask one question at a time.
- Gather discoverable repo facts before asking the user.
- Stop interviewing when all three clarity dimensions are resolved, the user asks to stop, or round 6 is reached.

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
