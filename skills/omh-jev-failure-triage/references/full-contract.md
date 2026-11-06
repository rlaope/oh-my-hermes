# Jev Failure Triage

Load this on-demand contract after the compact `jev-failure-triage` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`jev-failure-triage` exists so a failing run gets a fixed-rule next move from typed answers, computed by OMH code rather than by the model eyeballing numbers.

## Do Not Use When

- The user wants the root cause of a failing build and a fix; use `omh-build-failure-triage`.
- The agent itself is looping or misbehaving and needs a diagnosis; use `omh-agent-debug`.
- Production is down; use `omh-live-incident-response`.

## Examples

Good example:

- Prompt: use jev to triage this failing test
- Expected behavior: Say the command and error excerpt leave the machine, call the `failure_triage/v1` preset with `attempts_so_far`, and report the outcome and rule.
- Why: The user addressed Jev about a failing run.

Bad example:

- Prompt: triage this failing build
- Expected behavior: Route to `omh-build-failure-triage`; the user did not ask for Jev.
- Why: Mentioning a failure is not asking Jev.

## Completion Checklist

- The preset outcome and its rule are reported beside the raw answers.
- `omh-build-failure-triage` or `omh-agent-debug` still owns the fix.

## Recovery Notes

- If `omh_jev_ask` is not in the tool list, say Jev is unavailable, point at the `plugin_jev_sidekick` line of `omh doctor`, and continue as main_model through the partner workflow.
- If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.
- If the tool refuses `credential_like_content`, remove the secret-looking text from `state` rather than redacting it silently, and tell the user what was removed.

## When to Use

Use when a command, test, or build failed or keeps failing, the user asked Jev, and a quick typed signal should pick the next move before the ordinary triage prepares a fix.

Routing signals: `jev-failure-triage`, `jev failure triage`, `ask jev if this failure is transient`

## Workflow Contract

Category: `review`
Phase: `jev-failure-triage`
Hermes role: `reviewer`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- `state` holds the command and an error excerpt, not the whole log.
- A non-answer is reported as `not_observed`, never as `no_signal`.

Handoff policy:

Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; the partner workflow keeps its own verdict and Jev's answers are one more input to it.

Required inputs:

- the failing command
- an excerpt of its error output
- how many times it was already retried

Expected outputs:

- the `failure_triage/v1` policy result
- the next move with the rule that fired

Artifact expectations:

- one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text

Safety rules:

- Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.
- Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.
- A non-answer status is never an answer: report it and continue without Jev.
- `retry_once_suggested` is a suggestion: the host's own approval still applies to the rerun.
- You supply `attempts_so_far`; never ask Jev to count attempts.
