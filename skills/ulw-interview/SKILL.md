---
name: ulw-interview
description: [omh] Hermes Deep Interview workflow: one-question-at-a-time clarification. Use when the user says: deep-interview, interview, clarify, feature shaping, ambiguous product request, one question, 온보딩, 부드럽게.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, clarification]
    category: clarification
    phase: discovery
    role: planner
    quality_tier: clarity-gated
---

# Deep Interview

This is a Hermes-native `deep-interview` workflow skill.

## Why This Exists

`deep-interview` exists to stop Hermes from guessing through ambiguous product, workflow, or implementation intent; it converts uncertainty into a clarified brief before planning or handoff.

## Do Not Use When

- The request already has concrete scope, acceptance criteria, and verification commands.
- The missing information is discoverable from the repository or local artifacts without asking the user.
- The user asked for immediate read-only analysis and the ambiguity does not change the answer.
- The ambiguity is specifically repository terminology or project-language alignment; use `context` and its direct-lookup/frontier boundary.

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

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Interview Round Protocol

This interview is bounded: at most 6 rounds, one question per round.

Before each question, find the most recent round header you emitted in this thread and add 1.
If there is no header, you are at Round 1. If you have already asked questions here but cannot
recover the number (for example after context compaction), do not restart at Round 1 — run the
mid-interview check now and continue from Round 4.

**Every question is preceded by this header on its own line, then a blank line, then the question:**

    Round {n}/6 · Clarity: {percent}% ({resolved}/3) · Targeting: {dimension}

- Clarity is scored against exactly three fixed dimensions: **outcome** (what is true when this
  is done), **constraints and non-goals** (what bounds the work), and **success criteria** (how
  anyone would verify it). `{resolved}` counts how many you could restate in one sentence
  without a qualifier. The denominator is always 3; `{percent}` is 0, 33, 67, or 100.
- `{dimension}` names the unresolved dimension this question targets — the one that most
  changes the plan, not the easiest one.
- A new concern raised in an answer files under one of the three dimensions. It never extends
  the denominator and never extends the round budget. Once the budget is spent, record it as an
  assumption instead of asking about it.

**Voice — the header is instrumentation; the question is a conversation.**

- Never fold counters, ratios, or dimension names into the question sentence.
- Ask the way a senior colleague would ask out loud: one sentence, no preamble, no restating
  what the user just said, no numbered sub-parts. If it reads like a form field, rewrite it.
- Outside the header line, the user never hears the words round, budget, dimension, or resolved.
- Mirror the user's language in the header labels and the question. Korean header:
  `라운드 {n}/6 · 명확도: {percent}% ({resolved}/3) · 확인 중: {목표/제약과 비목표/성공 기준}`.
  Never mix languages in one message.
- The clarified brief follows the same rule: write its headings and labels in the user's
  language. Translate those terms, never transliterate them.

**Mid-interview check — this is not a stop rule.**

Before asking the question that would be Round 4, offer the choice instead: say where
things stand and ask whether to keep going or plan now — your own words, the user's language,
one short sentence. The check is not a round: emit it without a header. If the user chooses to
continue, the next question is Round 4; if they choose to plan, stop rule 2 applies.

**Stop rules — the first match ends the interview.**

1. **All three dimensions resolved.** Emit the clarified brief and continue to planning.
2. **The user asks to stop.** "Just plan it", "그냥 해줘", or any explicit request to proceed ends
   questioning immediately, at any round. Emit the brief and record each unresolved dimension as
   an assumption with the value you are assuming.
3. **Budget reached at Round 6.** After the Round 6 answer, do not ask another
   question. Say plainly that you are moving to the brief with what you have, name what stayed
   unresolved, and continue.

These are stop rules you follow, not caps OMH enforces. When torn between one more question and
stopping, stop and plan.

## Use When

Use before planning or execution when requirements are materially ambiguous.

    Strong routing signals: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `온보딩`, `부드럽게`, `모호한 제품 요청`, `기획자`, `개발자 사이`

## Catalog Metadata

Category: `clarification`
Phase: `discovery`
Hermes role: `planner`
Quality tier: `clarity-gated`
Reasoning demand: `light`

Quality bar:

- Ask exactly one blocking question per turn unless the wrapper explicitly supports a structured batch.
- Tie each question to a missing decision that changes the plan, handoff, or stop condition.
- Emit a clarified brief with non-goals and acceptance criteria before planning or delegation.

Handoff policy:

Run directly in Hermes or the chat wrapper; produce a clarified brief before any coding handoff is prepared.

Required inputs:

- initial request
- known repo facts
- current ambiguity

Expected outputs:

- clarified brief
- non-goals
- decision boundaries

Artifact expectations:

- clarity summary or transcript when the wrapper supports it

Safety rules:

- Ask one question at a time.
- Gather discoverable repo facts before asking the user.
- Stop interviewing when all three clarity dimensions are resolved, the user asks to stop, or round 6 is reached.

## Runtime Evidence

Preferred harness for this skill: `deep-interview`.

```sh
omh runtime record --skill deep-interview --harness deep-interview --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
