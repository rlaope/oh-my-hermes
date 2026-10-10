---
name: "omh-app-debugging"
description: "[omh] Application code misbehaves -- a wrong value, a flaky test, a lost update: reproduce it first, form competing hypotheses, discriminate them with the cheapest observation, and only then fix the demonstrated root cause. Use when the user says: app-debugging, app debugging, application debugging, root cause, root-cause, find the root cause, root cause analysis, flaky test."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: app-root-cause
    role: reviewer
    quality_tier: root-cause-evidence-gated
---

# App Debugging

This is a Hermes-native `app-debugging` workflow skill.

## Why This Exists

`app-debugging` exists because a wrong result in application code had no owner: `native-debugging` covers native binaries, `build-failure-triage` covers red builds, and `agent-debug` covers agent misbehaviour, so the most common debugging request dispatched straight to an execution lane that skipped the diagnosis.

## First Steps

- Ask for, or plan, the one command that shows the wrong behaviour, and record its observed output before naming a cause.
- Refuse to prepare a fix while the reproduction reads not_observed; plan the observation that would establish it instead.

## Do Not Use When

- The fault is a crash, memory corruption, or core dump in a compiled native binary that needs a debugger session; use `native-debugging`.
- The build, compile, or CI job fails the same way on every run; use `build-failure-triage`.
- The subject is an agent or workflow run that misbehaved rather than the application code; use `agent-debug`.
- The cause is already demonstrated and the request is to judge whether the fix is proven; use `verification-gate`.

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
- The fix handoff carries the reproduction as a regression test that fails before and passes after.

## Recovery Notes

- If the fault does not reproduce, make reproduction the first hypothesis and plan the loop, seed, or ordering that would establish it.
- If every hypothesis is eliminated, record that, widen the axes, and keep root cause unclaimed rather than promoting the last survivor.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+28 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when application code -- a Python, TypeScript, Go, or JVM service, library, or test -- behaves wrongly and the cause is unknown: a wrong value, an intermittent or order-dependent test, a race or lost update, or a bug that moves when observed. The work is a demonstrated root cause: an observed reproduction, competing hypotheses, the cheapest observation that separates them, and only then a fix.

    Strong routing signals: `app-debugging`, `app debugging`, `application debugging`, `root cause`, `root-cause`, `find the root cause`, `root cause analysis`, `flaky test`, `flaky tests`, `test is flaky`, `intermittent test failure`, `fails intermittently`, `fails one run in`, `passes locally but fails in ci`, `heisenbug`, `bug disappears`, `disappears when i add a print`, `race condition`, `lost update`, `update is lost`, `wrong return value`, `returns the wrong value`, `reproduce the bug`, `minimal reproduction`

## Catalog Metadata

Category: `verification`
Phase: `app-root-cause`
Hermes role: `reviewer`
Quality tier: `root-cause-evidence-gated`
Reasoning demand: `standard`

Quality bar:

- State the symptom and the expected behaviour separately from any suspected cause.
- Record the reproduction with its hit rate; an intermittent fault is reproduced when its rate over N runs is measured, not when it happened once.
- Load `references/hypothesis-and-race-method.md` for the hypothesis table, flaky-test tactics, and race patterns instead of improvising them.
- Pick the next observation by cost and by how many hypotheses its result eliminates, and record the eliminations.
- Keep reproduction, root cause, fix, and verification as separate observed states.
- Count a fix as failed when an executed run of the same reproduction command still shows the original symptom or shows a new symptom; planned runs and other commands do not count. After the third failed fix, prepare no fourth; re-examine the architecture assumptions every fix shared, per the method reference, and offer the user the next step as a question.

Handoff policy:

Keep the symptom statement, the hypothesis set, the discriminating observations, and the root-cause verdict in Hermes. Record every reproduction run, probe output, and fix verification only from executor or wrapper observed evidence.

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

- reproduction_record/v1 names the exact command, the input, the observed output, the expected output, and the hit rate over N runs; it reads observed or not_observed and nothing between
- competing_hypotheses/v1 spans distinct axes -- input and state, ordering and timing, environment and build, dependency behaviour -- rather than three phrasings of one guess
- discriminating_observation_plan/v1 orders the observations cheapest first and names, for each, which hypotheses its result eliminates
- root_cause_record/v1 cites the observation that demonstrated the cause and the one that ruled out each rival
- fix_handoff/v1 carries the reproduction as the regression test that must fail before the fix and pass after it

Safety rules:

- No fix before an observed reproduction: `fix_handoff/v1` stays blocked while `reproduction_record/v1` reads not_observed, and a proposed change without one is a guess, not a fix.
- Do not claim a reproduction, a probe result, a root cause, or a passing fix from a prepared plan.
- Require at least three hypotheses on distinct axes before planning observations; one hypothesis makes every reading confirmatory.
- Never treat a symptom's disappearance as a root cause; a bug that stops after a print statement, a retry, or a sleep is an open timing fault.
- Do not execute tests, debuggers, or commands from OMH core; the executor runs them and the record takes only what it observed.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill app-debugging --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
