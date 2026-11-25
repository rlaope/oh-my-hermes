# App Debugging

Load this on-demand contract after the compact `app-debugging` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The fault is a crash, memory corruption, or core dump in a compiled native binary that needs a debugger session; use `omh-native-debugging`.
- The build, compile, or CI job fails the same way on every run; use `omh-build-failure-triage`.
- The subject is an agent or workflow run that misbehaved rather than the application code; use `omh-agent-debug`.
- The cause is already demonstrated and the request is to judge whether the fix is proven; use `omh-verification-gate`.
- Hermes' bundled `systematic-debugging` skill is already loaded for this bug; follow its phases instead of loading this one too, unless the reproduction, the rival hypotheses, and the observation that separated them must be kept as a record.

## Examples

Good example:

- Prompt: a test fails one run in five in CI, how do I find out why
- Expected behavior: Prepare reproduction_record/v1 with the loop that measures the failure rate, competing_hypotheses/v1 across ordering, shared state, timing, and environment, and the cheapest observation that splits them; no fix yet.
- Why: The failure is intermittent, so the first deliverable is a measured reproduction rather than a patch.

Bad example:

- Prompt: add a sleep before the assertion so the flaky test passes
- Expected behavior: Record the sleep as a symptom mask, keep root cause open, and plan the observation that names the race.
- Why: A timing change that hides the failure leaves the fault in place and removes the reproduction.

## Full Input, Output, and Artifact Expectations

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
