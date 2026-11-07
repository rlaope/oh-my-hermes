# Jev Review Gate

Load this on-demand contract after the compact `jev-review-gate` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`jev-review-gate` exists so a reviewer can add Jev's typed flags to a review without handing it any authority to approve.

## Do Not Use When

- The user wants the review itself and its verdict; use `omh-code-review`.
- The user wants release evidence gathered before shipping; use `omh-verification-gate`.
- The user wants the agent's own tool and permission surface audited; use `omh-security-safety-review`.

## Examples

Good example:

- Prompt: ask jev to review this diff
- Expected behavior: Say the diff leaves the machine and the cost, call `review_flags/v1` once per file, and report the flags beside the ordinary review.
- Why: The user addressed Jev about a diff.

Bad example:

- Prompt: review the jev plugin PR before merge
- Expected behavior: Route to `omh-code-review`: the PR is about Jev, and nobody asked Jev anything.
- Why: Talking about Jev is not addressing it.

## Completion Checklist

- Every file sent was named to the user first.
- `omh-code-review` still owns the verdict.

## Recovery Notes

- If `omh_jev_ask` is not in the tool list, say Jev is unavailable, point at the `plugin_jev_sidekick` line of `omh doctor`, and continue as main_model through the partner workflow.
- If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.
- If the tool refuses a diff as `credential_like_content`, the diff adds credential-like text: report that as an OMH security flag on the file, and do not send a stripped diff as if it were the file.

## When to Use

Use when a diff is under review and the user asks Jev for typed flags as an extra reviewer signal.

Routing signals: `jev-review-gate`, `jev review gate`, `ask jev to review this diff`

## Workflow Contract

Category: `review`
Phase: `jev-review-gate`
Hermes role: `reviewer`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Each ask carries one file's diff with its matching test diff when one exists; the union of flags is reported per file.
- A non-answer is `not_observed`, never `no_flags`.

Handoff policy:

Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; the partner workflow keeps its own verdict and Jev's answers are one more input to it.

Required inputs:

- the diff, one file per ask with its matching test diff
- the review the flags feed

Expected outputs:

- `review_flags/v1` flags per file
- the union of flags and the highest severity across files

Artifact expectations:

- one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text

Safety rules:

- Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.
- Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.
- A non-answer status is never an answer: report it and continue without Jev.
- Send at most 8 files per review and state the cost before the first ask; source code leaves the machine.
- Flags are advisory evidence: `no_flags` never approves a merge and never satisfies a review item.
