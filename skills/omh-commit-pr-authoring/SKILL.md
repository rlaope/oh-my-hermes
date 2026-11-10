---
name: "omh-commit-pr-authoring"
description: "[omh] Commit message or pull-request body to write for a change: draft it in the repository's own convention, with `Tested:` listing only commands observed to run and everything prepared but not run under `Not-tested:`. Use when the user says: commit-pr-authoring, commit message, commit messages, write the commit message, draft the commit message, commit body, squash message, pr body."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: commit-pr-authoring
    role: reviewer
    quality_tier: evidence-ledger-gated
    related_skills: [omh-code-review, omh-github-event-ops, omh-github-issue-intake, omh-content-operator]
---

# Commit Pr Authoring

This is a Hermes-native `commit-pr-authoring` workflow skill.

## Why This Exists

`commit-pr-authoring` exists because nothing in the catalog authored the commit or the PR body. `omh-code-review` reads a commit message as a thing to review and `omh-github-event-ops` routes PR events, so the text an engineer writes several times a day had no owner, and nothing applied the observed-versus-prepared split to it.

## First Steps

- Read the PR template and the recent log, and record the convention before drafting.
- Build the evidence ledger: each command, observed with its exit status or not_observed.

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

## Completion Checklist

- The convention read names the template and log sample it drew from.
- Every `Tested:` entry (or the validation line of a repository whose log has no such trailer) maps to an observed ledger row with its exit status.
- Every prepared, skipped, or unobserved command is under `Not-tested:` (or "Not run" where the log has no trailers) with its reason.
- The draft lists the paths to stage, and any state-claiming subject prefix maps to an observed ledger row.
- Nothing was committed, pushed, or opened by OMH.
- The commit text and the reply say what was not run in plain words; run record and evidence ledger are bookkeeping terms that stay out of both.

## Recovery Notes

- If no command run was observed, draft with an empty `Tested:` and every command under `Not-tested:`, and ask for the observed output.
- If the repository has no template or visible convention, say so and use a plain subject and body rather than importing one.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a change is ready to record and the user wants its commit message or pull-request body written: the repository's template and recent log read first, the subject and body in that convention, the trailers the repo requires, and a `Tested:` line that lists only commands observed to run, with everything prepared but not run under `Not-tested:`. OMH prepares the text; the commit, the push, and the PR are the user's or the executor's.

    Strong routing signals: `commit-pr-authoring`, `commit message`, `commit messages`, `write the commit message`, `draft the commit message`, `commit body`, `squash message`, `pr body`, `pr description`, `pull request body`, `pull request description`, `draft the pr`, `write the pr`, `pr template`, `tested trailer`, `not-tested trailer`, `lore trailers`, `напиши коммит`, `сообщение коммита`, `описание пул реквеста`, `текст коммита`

## Catalog Metadata

Category: `verification`
Phase: `commit-pr-authoring`
Hermes role: `reviewer`
Quality tier: `evidence-ledger-gated`
Reasoning demand: `standard`

Quality bar:

- Read the template and at least the last few commits before writing a word, and record what was found.
- Build the evidence ledger first; the `Tested:` and validation sections are projections of it, not prose.
- Write the subject in the repository's shape and the body as why the change exists, not a restated diff.
- Load `references/commit-and-pr-conventions.md` for trailer, sign-off, and template-section mapping instead of improvising them.
- Put `Closes #N` on its own line only when every success criterion of that issue is met.

Handoff policy:

Keep the convention read, the drafted text, and the evidence ledger in Hermes. The commit, the push, and opening the PR are executor or user actions; OMH never performs them, and a command reaches `Tested:` only from an observed run record.

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

Safety rules:

- List a command under `Tested:` only when the evidence ledger records it as observed; a command that was prepared, planned, or described as passing without a run record goes under `Not-tested:`, whatever the wording says.
- Never commit, amend, push, or open the PR; OMH prepares the text and the user or the executor records it.
- Name the paths a commit covers and have them staged by path; never write or recommend `git add -A` or `git add .`, which sweeps unrelated dirty files into the commit.
- A subject prefix that claims a state, such as `[verified]`, `[reviewed]`, or `[tested]`, is a projection of the evidence ledger: write it only when the repository's log uses that prefix and the ledger holds the observed row it claims, never as a default.
- Read the repository's own template and recent log before drafting; impose no convention the repository does not use.
- Do not claim CI, review, or merge state in the text unless it was observed, and name what was not.
- Never put credentials, tokens, private URLs, or raw transcripts into a commit message or PR body.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
