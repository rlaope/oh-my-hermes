# Git Workflow

Load this on-demand contract after the compact `git-workflow` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is to write the commit message or the PR body for a finished change; use `omh-commit-pr-authoring`.
- The request is to find defects in a diff before merging it; use `omh-code-review`.
- The build or CI job fails and the question is why; use `omh-build-failure-triage`.
- The request is a code change to deliver rather than branch or history repair; use `ulw-work`.

## Examples

Good example:

- Prompt: clean up this branch's history before review
- Expected behavior: Prepare pushed_state_inventory/v1 first, then history_rewrite_plan/v1 with a backup branch before the interactive rebase and `--force-with-lease` for the push, naming who must re-fetch.
- Why: Whether the branch is pushed decides whether the cleanup is local or shared.

Bad example:

- Prompt: just force push my rebased branch over main
- Expected behavior: Refuse the bare force-push: inventory what is pushed on main, and plan `--force-with-lease` onto the feature branch only.
- Why: A bare force-push over a shared branch discards other people's commits without a check.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the branch or branches involved and their upstreams
- what is already pushed, and who else may have fetched it
- the conflict, the regression, or the history problem as observed
- for a bisect: a known good commit, a known bad commit, and the command that tells them apart
- the repository's merge policy: merge commits, squash, or rebase

Expected outputs:

- pushed_state_inventory/v1
- git_repair_plan/v1
- conflict_resolution_plan/v1 when files conflict
- bisect_plan/v1 when a regression is hunted
- history_rewrite_plan/v1 when commits are rewritten
- observed_git_result/v1 when observed

Artifact expectations:

- pushed_state_inventory/v1 lists each branch with its local head, its remote head, whether they match, and whether anyone else may have the remote commits
- git_repair_plan/v1 orders the steps, marks each one that rewrites history, and names the recovery point (a backup ref or reflog entry) before it
- conflict_resolution_plan/v1 decides each conflicted hunk by what both sides intended, and re-derives generated or counted files from their producer instead of picking a side
- bisect_plan/v1 names the good and bad commits and the exact test command, so each step is a run rather than a judgement
- history_rewrite_plan/v1 uses `--force-with-lease` for every force-push and says which collaborators must re-fetch
