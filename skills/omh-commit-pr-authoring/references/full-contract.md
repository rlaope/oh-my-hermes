# Commit Pr Authoring

Load this on-demand contract after the compact `commit-pr-authoring` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is to find defects in the diff or judge whether the change is ready; use `omh-code-review`.
- The request routes an incoming pull-request, issue, or CI webhook event; use `omh-github-event-ops`.
- The request turns a chat report into a GitHub issue; use `omh-github-issue-intake`.
- The request is release notes or product copy for readers outside the repository; use `omh-content-operator`.

## Examples

Good example:

- Prompt: write the commit message for this change, the unit tests ran but I did not run the e2e suite
- Expected behavior: Read the log's subject shape and trailers, record the unit test command as observed and the e2e suite as not_observed, and draft the message with the unit tests under `Tested:` and the e2e suite under `Not-tested:`.
- Why: The ledger decides which line each command lands on, not the wording of the request.

Bad example:

- Prompt: say the integration tests pass, they will once CI runs
- Expected behavior: Keep the integration tests under `Not-tested:` until an observed run exists, and say CI has not been observed.
- Why: A prediction worded as a result is exactly what `Tested:` must not carry.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the change: the diff, the staged files, or the branch compared with its base
- the repository's PR template and a sample of its recent commit log
- the commands that ran for this change, each with its observed exit status
- the commands that were prepared, planned, or skipped, and why
- the issue or goal the change closes, when there is one

Expected outputs:

- repo_convention_read/v1
- evidence_ledger/v1
- commit_message_draft/v1
- pr_body_draft/v1 when a PR is being opened

Artifact expectations:

- repo_convention_read/v1 names the template path, the subject shape and trailers seen in the recent log, and the sign-off rule, or says which of them was not found
- evidence_ledger/v1 lists every command with observed or not_observed; observed carries the exit status and where it was seen
- commit_message_draft/v1 and pr_body_draft/v1 take `Tested:` and the validation section only from observed ledger rows
- commit_message_draft/v1 lists the paths the commit covers, so whoever records it stages those paths and nothing else
- optional offline diff hazard summary via `toolkit/scripts/merge_danger_scan.py` (`merge_danger_scan/v1`, read-only)
