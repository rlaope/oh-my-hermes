---
name: "ulw-qa"
description: "[omh] Hostile scenario testing: adversarial QA and fix loops. Use when the user says: ultraqa, adversarial qa, hostile scenarios, e2e qa, real-world qa, qa scenario, release qa, 敵対的QA."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: qa
    role: reviewer
    quality_tier: scenario-gated
---

# Ultraqa

This is an OMH `ultraqa` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ultraqa` exists because behavior that passes its own tests can still fail under inputs and conditions nobody wrote down: it turns the changed behavior and known risks into hostile scenarios, records each one's observed pass or fail apart from any proposed fix, and hands fixes to the selected coding executor.

## Do Not Use When

- Judging whether a rendered page, image, or terminal frame looks right across viewports and states; use `omh-visual-qa`.
- Confirming that a finished change meets its acceptance criteria with the smallest proving check, when no hostile scenarios are wanted; use `omh-verification-gate`.

## Examples

Good example:

- Prompt: $ultraqa test the setup wizard with hostile install paths, stale config, and missing PATH cases.
- Expected behavior: Generate adversarial QA scenarios, expected signals, observed results, and fix-or-retry routing.
- Why: The request asks for verification pressure and hostile scenarios.

Bad example:

- Prompt: ultraqa: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ultraqa`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The scenario, expected behavior, observed result, and pass/fail basis are named.
- Proposed fixes are separated from observed QA evidence.
- Missing or failed verification routes back to plan, fix, or a narrower test.

## Recovery Notes

- If the expected behavior is unclear, route back to plan before running adversarial checks.
- If verification fails, return to fix or research with the failed signal instead of advancing.



## When to Use

Use when the task needs adversarial test scenarios, verification, and fix loops.

    Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `敵対的QA`, `リリース前QA`, `障害シナリオ`, `장애 상황`, `쿠버네티스 장애`, `적절히 진단`, `검증 체크리스트`, `릴리즈 전 gate`, `对抗式测试`, `发布前测试`, `故障场景`, `uji skenario ekstrem`, `lakukan QA adversarial`, `uji skenario kegagalan sebelum rilis`, `bantu cari celah lewat pengujian end to end`, `uji aplikasi dengan kondisi pengguna nyata`, `jalankan siklus pengujian dan perbaikan berulang`

## Catalog Metadata

Category: `verification`
Phase: `qa`
Quality tier: `scenario-gated`
Reasoning demand: `standard`

Quality bar:

- Do not start this engine as an automatic continuation of another skill's output: an accepted plan, a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user explicitly invoked this engine themselves, restate in one line what will start (engine, scope, selected executor) and wait for the user's explicit go-ahead first.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval; persistence never broadens the authorized scope. A refused escalation gets a safer alternative inside the boundary, or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences plus the observed validation for a simple change, more only when the complexity earns it. Lead with the result or decision; omit abandoned approaches unless they explain a tradeoff the reader needs; narrate no internal bookkeeping (todo transitions, follow-up declarations, waits). Required closing lines stay outside this scaling: the observed run summary, and any prepared-not-observed or unmerged work, are stated whatever the brief's length.
- Generate hostile scenarios from changed behavior and known risk areas.
- Report pass/fail evidence separately from proposed fixes.
- Delegate code mutations discovered by QA to the selected coding executor.
- Read actual host/executor evidence before claiming build, verification, review, documentation, or PR-preparation results.
- On a web app, run hostile scenarios against the target the user named (local or staging unless stated); a scenario that would submit, buy, send, or delete on a live surface waits for the user's approval.
- Read the browser console after every navigation and interaction, and keep a failing scenario's screenshot and console errors as its observed evidence.

Required inputs:

- changed behavior
- acceptance criteria
- known risk areas

Expected outputs:

- adversarial scenarios
- pass/fail evidence
- fix recommendations

Artifact expectations:

- QA scenario evidence
- runtime verification summary

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

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
about one; and when a stop condition or a decision the user owns ends the turn,
offer the next action as a question rather than declaring what will not be done.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
