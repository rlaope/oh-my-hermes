---
name: "omh-app-debugging"
description: "[omh] Application code misbehaves -- a wrong value, a flaky test, a lost update: reproduce it first, form competing hypotheses."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: app-root-cause
    role: reviewer
    quality_tier: root-cause-evidence-gated
---

# App Debugging

This is an OMH `app-debugging` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`app-debugging` exists because a wrong result in application code had no owner: `omh-native-debugging` covers native binaries, `omh-build-failure-triage` covers red builds, and `omh-agent-debug` covers agent misbehaviour, so the most common debugging request dispatched straight to an execution lane that skipped the diagnosis.

## First Steps

- Ask for, or plan, the one command that shows the wrong behaviour, and record its observed output before naming a cause.
- Refuse to prepare a fix while the reproduction reads not_observed; plan the observation that would establish it instead.

## Do Not Use When

- The fault is a crash, memory corruption, or core dump in a compiled native binary that needs a debugger session; use `omh-native-debugging`.
- The build, compile, or CI job fails the same way on every run; use `omh-build-failure-triage`.
- The subject is an agent or workflow run that misbehaved rather than the application code; use `omh-agent-debug`.
- The cause is already demonstrated and the request is to judge whether the fix is proven; use `omh-verification-gate`.

## Examples

Good example:

- Prompt: a test fails one run in five in CI, how do I find out why
- Expected behavior: Prepare reproduction_record/v1 with the loop that measures the failure rate, competing_hypotheses/v1 across ordering, shared state, timing, and environment, and the cheapest observation that splits them; no fix yet.
- Why: The failure is intermittent, so the first deliverable is a measured reproduction rather than a patch.

Bad example:

- Prompt: add a sleep before the assertion so the flaky test passes
- Expected behavior: Record the sleep as a symptom mask, keep root cause open, and plan the observation that names the race.
- Why: A timing change that hides the failure leaves the fault in place and removes the reproduction.

## Completion Checklist

- The reproduction names its command, observed output, expected output, and hit rate, and reads observed before any fix is prepared.
- At least three hypotheses on distinct axes were written before the first observation was chosen.
- Each observation records which hypotheses its result eliminated.
- The root cause cites the demonstrating observation and the observation that ruled out each rival.
- The fix handoff carries the reproduction as a regression test that fails before and passes after, or records `regression_seam: none_correct` with the reason, with the reproduction loop observed red before the fix and green after it.
- An observed search for the session's probe tag returns nothing, and every throwaway harness file is deleted or listed.

## Recovery Notes

- If the fault does not reproduce, make reproduction the first hypothesis and plan the loop, seed, or ordering that would establish it; when no test reaches the fault, choose a loop from the method reference's loop table; if none can be built, the record stays not_observed with each attempt and what stopped it, and the request to the user is for an environment, a redacted capture, or permission for tagged temporary instrumentation.
- If every hypothesis is eliminated, record that, widen the axes, and keep root cause unclaimed rather than promoting the last survivor.



## When to Use

Use when application code -- a Python, TypeScript, Go, or JVM service, library, or test -- behaves wrongly and the cause is unknown: a wrong value, an intermittent or order-dependent test, a race or lost update, or a bug that moves when observed. The work is a demonstrated root cause: an observed reproduction, competing hypotheses, the cheapest observation that separates them, and only then a fix.

    Strong routing signals: `app-debugging`, `app debugging`, `application debugging`, `root cause`, `root-cause`, `find the root cause`, `root cause analysis`, `flaky test`, `flaky tests`, `test is flaky`, `intermittent test failure`, `fails intermittently`, `fails one run in`, `passes locally but fails in ci`, `heisenbug`, `bug disappears`, `disappears when i add a print`, `race condition`, `lost update`, `update is lost`, `wrong return value`, `returns the wrong value`, `reproduce the bug`, `minimal reproduction`, `почини баг`, `найди баг`, `приложение падает с ошибкой`, `флаки тест`, `исправь баг`, `баг в коде`, `исправить баг`, `найди ошибку в коде`, `отладь`

## Catalog Metadata

Category: `verification`
Phase: `app-root-cause`
Quality tier: `root-cause-evidence-gated`
Reasoning demand: `standard`

Quality bar:

- State the symptom and the expected behaviour separately from any suspected cause.
- Record the reproduction with its hit rate; an intermittent fault is reproduced when its rate over N runs is measured, not when it happened once.
- A reproduction counts for this bug only when its `symptom_match` shows the failure the user reported; a different failure near the same code is another bug, and this record stays not_observed.
- `minimised` is filled before `competing_hypotheses/v1`: an input, caller, config value, or step leaves the reproduction only when the loop rerun without it still shows the symptom (for an intermittent fault, the same rate at the same N), and the record lists what left and what stayed; `fix_handoff/v1` builds the regression test from what stayed.
- Load `references/hypothesis-and-race-method.md` for the hypothesis table, flaky-test tactics, and race patterns instead of improvising them.
- Pick the next observation by cost and by how many hypotheses its result eliminates, and record the eliminations.
- Keep reproduction, root cause, fix, and verification as separate observed states.
- Count a fix as failed when an executed run of the same reproduction command still shows the original symptom or shows a new symptom the fix caused rather than unmasked; planned runs and other commands do not count. After the third failed fix, prepare no fourth; re-examine the architecture assumptions every fix shared, per the method reference, and offer the user the next step as a question.
- Before the fix handoff names a regression test, read `../omh-verification-gate/references/test-authoring.md` for the seam, the shapes of tests that guard nothing, fakes only at system boundaries, and the no-correct-seam outcome.

Required inputs:

- the wrong behaviour as observed, and the behaviour that was expected
- the command, request, or test that shows it, and how often it shows it
- language, framework, and what changed recently when known
- logs, stack traces, or failing assertions already captured
- observed reproduction and verification evidence for any root-cause or fix claim

Expected outputs:

- reproduction_record/v1
- competing_hypotheses/v1 with at least three hypotheses on distinct axes
- discriminating_observation_plan/v1
- root_cause_record/v1
- fix_handoff/v1 blocked until reproduction_record/v1 reads observed
- observed_fix_verification/v1 when observed

Artifact expectations:

- reproduction_record/v1 names the exact command, the input, the observed output, the expected output, and the hit rate over N runs, plus `symptom_match` (the observed failure quoted beside the reported one), `loop_cost` (wall time per run, and what was pinned or, for an intermittent fault, how the rate was raised), and `minimised` (the cuts made and the load-bearing form left); it reads observed or not_observed and nothing between
- competing_hypotheses/v1 spans distinct axes -- input and state, ordering and timing, environment and build, dependency behaviour -- rather than three phrasings of one guess
- discriminating_observation_plan/v1 orders the observations cheapest first and names, for each, which hypotheses its result eliminates
- root_cause_record/v1 cites the observation that demonstrated the cause and the one that ruled out each rival, and the fix's commit or pull-request body states that confirmed hypothesis and the rivals it eliminated, because the next debugger reads history, not this record
- fix_handoff/v1 carries the reproduction as the regression test that must fail before the fix and pass after it, or records `regression_seam: none_correct` with the reason, with the reproduction loop observed red before the fix and green after it
- fix_handoff/v1 names the seam the regression test drives and how it runs the pattern that produced the bug (callers, ordering, call chain); when the pattern cannot run at any reachable seam, it records `regression_seam: none_correct` with the reason and what was tried, keeps the reproduction loop as the fix's verification, and reports the missing seam as an `omh-refactor-plan` candidate instead of a shallow test that passes before and after the fix

Safety rules:

- No fix before an observed reproduction: `fix_handoff/v1` stays blocked while `reproduction_record/v1` reads not_observed, and a proposed change without one is a guess, not a fix.
- Do not claim a reproduction, a probe result, a root cause, or a passing fix from a prepared plan.
- Require at least three hypotheses on distinct axes before planning observations; one hypothesis makes every reading confirmatory.
- Never treat a symptom's disappearance as a root cause; a bug that stops after a print statement, a retry, or a sleep is an open timing fault.
- Do not execute tests, debuggers, or commands from OMH core; the executor runs them and the record takes only what it observed.
- Redact before recording: reproduction commands read credentials from environment variables by name, quoted output keeps only the lines that carry the signal with each secret replaced by `<redacted>`, and a capture too redacted to diagnose is reported as such, never recorded unredacted.

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
