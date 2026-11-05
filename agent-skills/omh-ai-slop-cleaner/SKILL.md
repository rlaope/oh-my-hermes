---
name: "omh-ai-slop-cleaner"
description: "[omh] Messy or AI-generated code to clean up: delete AI-generated slop, dead code, and duplication while observable behavior stays identical. Use when the user says: ai-slop-cleaner, cleanup, deslop, refactor, risky, behavior-preserving refactor, risk analysis, refactor workflow."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, maintenance]
    category: maintenance
    phase: cleanup
    role: handoff-guide
    quality_tier: regression-gated
---

# Ai Slop Cleaner

This is an OMH `ai-slop-cleaner` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ai-slop-cleaner` exists to keep `maintenance` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The goal is new or changed behavior rather than removing existing code; a plain refactor, feature, or fix request belongs to `ulw-work`.
- The cleanup would change architecture or module boundaries and needs its execution shaped into phases first; use `omh-refactor-plan`, or `ulw-plan` when the direction itself is still contested.
- The user wants code judged for bugs or merge readiness with no drafted slop removal to inspect; use `omh-code-review` for a bug-first review and `omh-failure-signal-audit` for swallowed failures.

## Examples

Good example:

- Prompt: $ai-slop-cleaner remove duplicated router branches and lock behavior with regression tests before refactoring.
- Expected behavior: Plan cleanup, preserve behavior, delete or simplify code, and prove it with targeted tests.
- Why: The request is maintenance cleanup with regression risk.

Bad example:

- Prompt: ai-slop-cleaner: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ai-slop-cleaner`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The selected coding or runtime owner is named before any implementation claim.
- Prepared handoff, dispatch, execution, verification, review, CI, and merge states are separated.
- The final status cites observed runtime evidence or keeps the work prepared_not_observed.
- When Hermes is the selected coding owner, use `hermes_coding_harness/v1` to keep builder, verifier, reviewer, docs, and PR lanes separate.
- Report the current harness stage, owner, next action, and missing evidence without claiming PR creation, review, CI, merge-readiness, or merge until matching runtime observations exist.

## Recovery Notes

- If baseline regression checks cannot run, retain the categorized smell inventory, mark the behavior lock unresolved, and hand back the cleanup plan and missing before-checks without starting risky edits.
- If verification fails between single-smell passes, retain the last verified pass's evidence, mark the new pass unresolved, and hand back its small diff and failed check for a fix or revert before the next pass.
- If the cleanup has no runtime record, retain its observed diff and before/after checks, mark the cleaner run not_observed, and hand back the four-part closing report for recording before an AC-SLOP checkpoint.



## When to Use

Use when the goal is removing existing low-quality, duplicated, or AI-generated code and the observable behavior must not change; lock behavior with tests before and after the edits.

    Strong routing signals: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `behavior-preserving refactor`, `risk analysis`, `refactor workflow`, `legacy refactor`, `anti-slop pass`, `anti-slop review`, `anti-slop sweep`, `ai slop`, `deslop review`, `리팩터링`, `리팩토링`, `위험 분석`, `변경 범위 제한`, `회귀 테스트`, `деслоп`, `убери мусор из кода`, `почисти код`, `убери лишнее в коде`, `зачисти код`, `мёртвый код`, `анслоп`, `деблоат`, `почистить код`

## Catalog Metadata

Category: `maintenance`
Phase: `cleanup`
Quality tier: `regression-gated`
Reasoning demand: `heavy`

Quality bar:

- Lock current behavior with regression checks before non-trivial cleanup.
- Classify before deleting: every finding names one category from the slop taxonomy - duplication, dead code, needless abstraction, boundary violation, missing tests, or templated defaults - so the pass order below can own it.
- Run single-smell passes in fixed order, re-verifying between passes and never bundling categories: dead-code deletion, then duplicate removal, then naming and error handling, then test reinforcement; the full contract is `omh-ai-slop-cleaner/references/cleanup-passes.md`.
- When the user names no target smell, run detection first and hand back the inventory: prepared linter and dead-code commands are named per stack in the reference and stay prepared_not_observed until run.
- When the cleanup target is written English rather than code, load `omh-ai-slop-cleaner/references/prose-lexicon.md` for the word tiers, the pattern severities, and the context profile that decides which rules apply.
- Review mode (`deslop review`, or a request to judge a drafted cleanup without editing) edits nothing: read the writer pass's plan, its diff, and the before/after checks it ran against the six taxonomy categories and return findings in the `code-review` shape - P0-P3 severity and a ship or no_ship verdict - never a new verdict format; the checklist is in `cleanup-passes.md`.
- Fixes found in review go back to a separate writer pass: the pass that wrote a cleanup is never the one that approves it, and a review pass that starts editing has stopped being a review.
- When the cleanup target is UI code, load `omh-ai-slop-cleaner/references/ui-review-checklist.md`; its items are review prompts a stated rationale closes, not bans.
- Prefer deletion, reuse, and boundary repair over new abstractions.
- Rerun verification after cleanup before claiming behavior is preserved, and close with the four-part report: changed files, simplifications, behavior lock, remaining risks.
- Close every run with `omh runtime record --skill ai-slop-cleaner --harness coding-handling --status completed` (or `failed` / `blocked`), adding `--goal <goal_id> --cleanup-outcome passed|skipped|reverted` when the pass serves a goal: a cleanup run carries changed files, simplifications, and remaining risks in `--outputs-summary` and the behavior lock in `--verification-summary`; a review-mode run carries the ship or no_ship verdict and the finding count per priority in `--outputs-summary`. A caller that says the cleaner ran cites that record, and without one the pass is not_observed. A goal carrying AC-SLOP completes only after `omh goal checkpoint --goal <goal_id> --summary <outcome> --criterion AC-SLOP --evidence-ref run:<run_id>` cites a `completed` record; a failed or blocked run never satisfies it, so a decided skip is `--status completed --cleanup-outcome skipped`. One accepted record covers the goal, and `skipped` and `reverted` are reported as recorded, never as passed.

Required inputs:

- target smell, or a scoped file list when the user has not named one
- current behavior
- regression checks

Expected outputs:

- smell inventory naming each finding's category before any edit
- small cleanup diff, one pass at a time
- before/after verification
- closing report: changed files, simplifications, behavior lock, remaining risks

Artifact expectations:

- cleanup plan and regression evidence for non-trivial work

Safety rules:

- Lock behavior with tests before risky cleanup.
- Prefer deletion and existing utilities over new layers.
- Do not add dependencies for cleanup unless explicitly requested.
- A scoped file list is a boundary: never widen it silently; out-of-scope findings are reported, not edited.

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
