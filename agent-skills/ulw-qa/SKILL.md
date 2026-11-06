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

- Prompt: ultraqa that the profile page looks right on mobile
- Expected behavior: Route to `omh-visual-qa`; no changed behavior is being attacked.
- Why: The question is how a rendered page looks, which the viewport and state matrix answers.

## Completion Checklist

- The scenario, expected behavior, observed result, and pass/fail basis are named.
- Proposed fixes are separated from observed QA evidence.
- A failed scenario gets at most two fix-and-rerun rounds; after the second failed rerun it is reported as an open finding with its evidence, and the scenario is not redefined to pass.
- Everything the hostile scenarios created or changed (accounts, rows, files, processes, ports) was listed before the first one ran and removed or restored afterwards, with the command and its observed result as the cleanup receipt, or what remains is named.

## Recovery Notes

- If a scenario needs a real install or external service the harness cannot reach, retain other observed pass/fail evidence, mark that scenario not_observed, and hand back its manual test guide with setup, do, expect, and broken signals.
- If a hostile browser scenario would submit, buy, send, or delete on a live target without approval, retain read-only scenario results, mark that action not_observed, and hand back the target and exact action for user approval.
- If a failing browser scenario has no screenshot or console readback, keep its observed failure, mark diagnosis tentative, and hand back the scenario, target, and missing capture for a bounded rerun.



## When to Use

Use when the task needs adversarial test scenarios, verification, and fix loops.

    Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `敵対的QA`, `リリース前QA`, `障害シナリオ`, `장애 상황`, `쿠버네티스 장애`, `적절히 진단`, `검증 체크리스트`, `릴리즈 전 gate`, `злые сценарии`, `прогони e2e`, `e2e сценарий`, `e2e тест`, `адверсариальное тестирование`, `对抗式测试`, `发布前测试`, `故障场景`, `uji skenario ekstrem`, `lakukan QA adversarial`, `uji skenario kegagalan sebelum rilis`, `bantu cari celah lewat pengujian end to end`, `uji aplikasi dengan kondisi pengguna nyata`, `jalankan siklus pengujian dan perbaikan berulang`, `kiểm thử các tình huống cực đoan`, `tiến hành QA phản biện`, `kiểm thử các tình huống thất bại trước khi phát hành`, `giúp tìm lỗ hổng qua kiểm thử end to end`, `kiểm thử ứng dụng với điều kiện người dùng thực tế`, `chạy các chu kỳ kiểm thử và sửa lỗi lặp lại`

## Catalog Metadata

Category: `verification`
Phase: `qa`
Quality tier: `scenario-gated`
Reasoning demand: `standard`

Quality bar:

- Do not start this engine as an automatic continuation of another skill's output: an accepted plan, a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user explicitly invoked this engine themselves, restate in one line what will start (engine, scope, selected executor) and wait for the user's explicit go-ahead first.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval; persistence never broadens the authorized scope. A refused escalation gets a safer alternative inside the boundary, or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences for a simple change. Lead with the result and validation; omit abandoned approaches unless they explain a tradeoff, and internal bookkeeping. Disclose requested-but-not-done work and material prepared/unmerged work; omit unrelated non-action footers. Required accounting stays outside this scaling. Order: result -> relevant evidence/limits -> observed accounting (when required) -> specific question (if useful). For a real unresolved user decision or a useful briefing discussion, offer one specific, content-linked question. Completed work needs no question; discussion grants no authority. Never estimate usage.
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
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
