---
name: "omh-git-workflow"
description: "[omh] Git branch in trouble -- a merge conflict, a commit that broke something, history to repair: plan the resolution, the bisect, or the rewrite, name what is already pushed first, and force-push only with `--force-with-lease`. Use when the user says: git-workflow, git workflow, merge conflict, merge conflicts, rebase conflict, resolve the conflict, resolve this conflict, conflict markers."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: git-repair
    role: reviewer
    quality_tier: history-safety-gated
---

# Git Workflow

This is an OMH `git-workflow` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`git-workflow` exists because conflict resolution, bisect, and history repair had no owner: "resolve this merge conflict" reached a file operator and "clean up this branch's history" a live-information lane, while this repository's own incidents -- a stack that replayed its base commits, a commit landing on another session's branch -- each had a known correct procedure.

## First Steps

- Name what is already pushed: each branch involved with its local head, its remote head, and whether others may have fetched it.
- Before any step that rewrites history, name its recovery point.

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

## Completion Checklist

- The pushed-state inventory names every branch the plan touches.
- Every rewriting step has a recovery point in front of it.
- Every force-push in the plan uses `--force-with-lease`.
- Generated and counted files in a conflict are re-derived, not picked.
- Resolution, bisect verdict, and push are reported only from observed output.

## Recovery Notes

- If the remote state is unknown, plan `git fetch` and the inventory first and rewrite nothing until it is observed.
- If a rewrite went wrong, recover from the recovery point or the reflog entry before trying anything else.



## When to Use

Use when a git branch needs repair rather than new code: a merge or rebase conflict to resolve, a regression to bisect to the commit that introduced it, or history to rewrite, squash, recover, or rebase -- including a stack of branches. The work is a plan that names what is already pushed, what each step rewrites, and how to get back.

    Strong routing signals: `git-workflow`, `git workflow`, `merge conflict`, `merge conflicts`, `rebase conflict`, `resolve the conflict`, `resolve this conflict`, `conflict markers`, `git bisect`, `bisect`, `which commit broke`, `find the commit that broke`, `rewrite history`, `rewrite the history`, `branch history`, `branch's history`, `clean up the history`, `interactive rebase`, `squash commits`, `squash the commits`, `force push`, `force-push`, `force-with-lease`, `reflog`, `git reset`, `lost commit`, `recover the commit`, `undo the last commit`, `cherry-pick`, `stacked prs`, `stacked branches`, `rebase the stack`, `detached head`

## Catalog Metadata

Category: `verification`
Phase: `git-repair`
Quality tier: `history-safety-gated`
Reasoning demand: `standard`

Quality bar:

- Start with the pushed-state inventory; a plan without it cannot say which steps are safe.
- Mark every step that rewrites history and put its recovery point in front of it.
- Load `references/git-repair-method.md` for the conflict, bisect, rewrite, and stacked-branch procedures instead of improvising them.
- For a stack of branches, rebase each onto the new head of the one below with `--onto` and the old base, never with a merge-base computed after the base moved.
- Report each step's observed output, and keep resolved, verified, and pushed as separate states.

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

Safety rules:

- Name what is already pushed before planning any rewrite; a rewrite of pushed commits is a decision for everyone who fetched them, not a local cleanup.
- Force-push only with `--force-with-lease`; a bare `--force` or `-f` push is never part of the plan.
- Create a recovery point -- a backup branch or a noted reflog entry -- before every step that rewrites history.
- Never resolve a conflict in a generated or counted file by picking a side; re-derive it from its producer after the merge.
- Do not run git commands from OMH core, and do not claim a resolution, a bisect verdict, or a pushed rewrite until its output is observed.

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
