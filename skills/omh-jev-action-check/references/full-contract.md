# Jev Action Check

Load this on-demand contract after the compact `jev-action-check` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`jev-action-check` exists so a risky command can get an extra, fail-closed screen from typed answers without Jev ever gaining the power to approve anything.

## Do Not Use When

- The user wants approval or permission policy written; use `omh-security-safety-review`.
- The user wants a command explained, prepared, or run; use `omh-terminal`.

## Examples

Good example:

- Prompt: ask jev if this rm -rf command is safe
- Expected behavior: Say the command, working directory, and task leave the machine, call `action_check/v1`, and report hold or no_extra_hold with the rule before anything runs.
- Why: The user addressed Jev about one command.

Bad example:

- Prompt: is this command risky to run?
- Expected behavior: Route to `omh-terminal`; the user did not ask for Jev.
- Why: A risk question without Jev is the ordinary command lane.

## Completion Checklist

- The outcome was one of hold, refuse_recommended, or no_extra_hold, with its rule.
- Nothing was run on the strength of `no_extra_hold` alone.

## Recovery Notes

- If `omh_jev_ask` is not in the tool list, say Jev is unavailable and the screen did not run (a `hold`, rule `tool_unavailable`), point at the `plugin_jev_sidekick` line of `omh doctor`, and run the command only if the user says so after that.
- If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.
- If the tool refuses `credential_like_content` because the command itself carries a credential, report a `hold` (the command carries a credential) first; screen a version with the value replaced by a placeholder only if the user asks, and say the screen did not see the real command.

## When to Use

Use before running a command or write the user asked Jev to screen, especially under a permissive approval mode.

Routing signals: `jev-action-check`, `jev action check`, `ask jev if this command is safe`, `jev risk check`

## Workflow Contract

Category: `review`
Phase: `jev-action-check`
Hermes role: `reviewer`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- `state` holds the command, the working directory path, and the stated task; the user was told all three leave the machine.
- The outcome and rule are reported before the command runs.

Handoff policy:

Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; the partner workflow keeps its own verdict and Jev's answers are one more input to it.

Required inputs:

- the command or write
- the working directory
- the task the user stated

Expected outputs:

- the `action_check/v1` outcome: hold, refuse_recommended, or no_extra_hold
- the rule that fired

Artifact expectations:

- one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text

Safety rules:

- Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.
- Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.
- A non-answer status is never an answer: report it as a `hold`, tell the user the screen did not run, and run the command only if they say so after that.
- The check can only add a hold: `no_extra_hold` means the host's normal approval still applies, never that the command is approved.
- Every non-answer is a hold labelled `not_answered:<status>`, so the user can see it came from a failure and not from Jev.
