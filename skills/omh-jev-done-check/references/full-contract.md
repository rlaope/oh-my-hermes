# Jev Done Check

Load this on-demand contract after the compact `jev-done-check` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`jev-done-check` exists so a completion claim can meet a typed objection from observed evidence before it is reported, without Jev ever declaring anything done.

## Do Not Use When

- The user wants release evidence collected and recorded; use `omh-verification-gate`.
- A loop is deciding whether to stop; stop rules read record fields and belong to `ulw-loop`.

## Examples

Good example:

- Prompt: ask jev if this task is done given the test output
- Expected behavior: Say the claim and test excerpt leave the machine, call `done_check/v1` per claim, and report objections before claiming completion.
- Why: The user addressed Jev about a completion claim.

Bad example:

- Prompt: verify before merge
- Expected behavior: Route to `omh-verification-gate`; nobody asked Jev.
- Why: Verification without Jev is the ordinary gate.

## Completion Checklist

- Each claim has its own outcome and rule.
- No claim was reported done on `no_objection` alone.

## Recovery Notes

- If `omh_jev_ask` is not in the tool list, say Jev is unavailable, point at the `plugin_jev_sidekick` line of `omh doctor`, and continue as main_model through the partner workflow.
- If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.
- If the tool refuses `credential_like_content`, remove the secret-looking text from `state` rather than redacting it silently, and tell the user what was removed.

## When to Use

Use before claiming a task complete, when the user asks Jev to test each completion claim against observed output rather than the agent's own summary.

Routing signals: `jev-done-check`, `jev done check`, `ask jev if this is done`, `jev evidence check`

## Workflow Contract

Category: `review`
Phase: `jev-done-check`
Hermes role: `reviewer`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Every objection names its claim and rule.
- A non-answer is `not_observed`, never `no_objection`.

Handoff policy:

Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; the partner workflow keeps its own verdict and Jev's answers are one more input to it.

Required inputs:

- each completion claim
- an excerpt of the observed evidence
- the goal

Expected outputs:

- one `done_check/v1` outcome per claim
- the objections, if any

Artifact expectations:

- one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text

Safety rules:

- Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.
- Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.
- A non-answer status is never an answer: report it and continue without Jev.
- One ask per claim, at most 6 claims; the evidence excerpt is observed output, never the agent's summary.
- `no_objection` never satisfies a verification item and never stops a loop; stop criteria read record fields.
