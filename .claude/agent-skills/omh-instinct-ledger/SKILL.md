---
name: "omh-instinct-ledger"
description: "[omh] Recurring lessons worth promoting: turn repeated project or cross-project lessons into atomic."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: instinct-ledger
    role: tracker
    quality_tier: workflow-surface-gated
---

# Instinct Ledger

This is an OMH `instinct-ledger` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`instinct-ledger` exists because a lesson seen once is an anecdote and one seen across runs or projects is a candidate rule: it records each as one atomic instinct with its trigger, action, scope, confidence, and evidence, and promotes one only through a reviewed store route, never by writing a host's memory or skills on its own.

## Do Not Use When

- A single missed route or one run's trace.
- Writing reviewed lessons into AGENTS guidance, prompts, or skills; use `omh-rules-distill`.
- A run that is stuck right now; use `omh-agent-debug` before drawing a lesson from it.

## Examples

Good example:

- Prompt: instinct-ledger turn these repeated OMH review lessons into project-scoped instincts and show which ones could be promoted globally.
- Expected behavior: Produce `prepare_instinct_ledger` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: instinct-ledger silently install hooks, learn from every prompt, and mutate all skills globally.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Each instinct is atomic: one trigger, one action, one scope, confidence, evidence refs, and review state.
- Confidence is the count of independent observations (different runs, sessions, or projects; one session counts once): 1 is an anecdote, 2 is tentative, 3 or more with no contradicting observation is a promotion candidate. Show the count and evidence refs beside every instinct. Instincts live only in this conversation's `instinct_candidate/v1` list until a store route accepts one; say so.
- Project-specific conventions, global practices, project/global promotion candidates, imports, and exports are separated.
- No hooks, memory writes, skill edits, global promotion, import/export, or behavior-change claims are made without observed approval and implementation evidence.
- A promoted instinct leaves as a store route, `memory_new_candidate/v1` for `omh-memory-new`, a `skill_update_candidate`, or a rule candidate for `omh-rules-distill` when the destination is AGENTS guidance or a prompt, never as a parallel store of its own.
- On Hermes, the skill audit ledger (`skills/.curator_ledger.jsonl` under the active profile's Hermes home) is observed evidence of what the agent or its background review already wrote; an instinct that matches a ledger entry no store route accounts for is reported as `unreviewed_native_write` (OMH holds no record of that write, which is not to say nobody reviewed it), never counted as repeated evidence for the instinct.

## Recovery Notes

- If the request is a single missed route or run trace, it is outside this skill.
- If the request is to mutate durable rules, prompts, skills, or AGENTS guidance, route to `omh-rules-distill` or implementation after review approval.
- If evidence comes from a stuck run, use `omh-agent-debug` before converting lessons into instincts.



## When to Use

Use when Hermes should review repeated observations, user corrections, workflow lessons, or failure patterns as atomic project-scoped or global instinct candidates with confidence, evidence, promotion, import, or export decisions.

    Strong routing signals: `instinct-ledger`, `instinct ledger`, `project instincts`, `project-scoped instincts`, `project scoped instincts`, `global instincts`, `instinct review`, `instinct candidate`, `instinct candidates`, `instinct promotion`, `promote instinct`, `promote learning`, `confidence scored learning`, `confidence-scored learning`, `project learning patterns`, `cross-project learning`, `export instincts`, `import instincts`, `학습 본능`, `프로젝트별 학습`, `프로젝트 스코프 학습`, `전역 학습 승격`, `학습 승격`, `학습 패턴 승격`

## Catalog Metadata

Category: `optimization`
Phase: `instinct-ledger`
Quality tier: `workflow-surface-gated`
Reasoning demand: `heavy`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- instinct_ledger_plan/v1
- instinct_candidate/v1
- project_instinct_scope_map/v1
- instinct_promotion_review/v1
- instinct_export_review/v1 when requested

Artifact expectations:

- instinct_candidate/v1 with trigger, action, confidence, domain, scope, source evidence, non-goals, and review state
- project_instinct_scope_map/v1 separating project, global, imported, and promotion-candidate instincts
- instinct_promotion_review/v1 with repeated evidence, confidence threshold, conflicts, and approval state
- instinct_export_review/v1 with redaction, destination, import/export trust gaps, and raw-observation exclusion when requested

Safety rules:

- An instinct ledger is not hook installation, automatic observation, model training, hidden memory mutation, skill mutation, prompt mutation, global rule promotion, import, export, or proof that future behavior changed. Record only reviewed candidate instincts, confidence, scope, promotion state, and evidence gaps.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

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
