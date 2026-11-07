# Git Repair Method

Load this while planning a conflict resolution, a bisect, a history rewrite, or a restack. OMH runs no git command: every command below is one the user or the executor runs, and the plan records only what its output showed.

## 1. Inventory what is pushed, first

| Branch | Local head | Remote head | Match | Others may have fetched |
| --- | --- | --- | --- | --- |
| `feature/x` | `git rev-parse feature/x` | `git rev-parse origin/feature/x` | yes / ahead / behind / diverged | yes when it is shared, has an open PR, or a CI run |

Run `git fetch` before reading the remote column; a stale remote-tracking ref makes every later step wrong. A commit that is on a remote someone else may have fetched is shared history: rewriting it is a decision for everyone who has it.

## 2. Recovery point before every rewrite

- Run `git status --porcelain` first. A dirty tree is a recovery point of its own: `git stash push -u`, or a WIP commit on a throwaway branch, and note it. `git reset --hard` discards uncommitted tracked changes with no way back.
- `git branch backup/<name>-<date> <branch>` before a rebase, reset, amend, or filter.
- Or note the reflog entry: `git reflog show <branch> -n 5`, and write down the entry to return to.
- Mid-rebase, run `git rebase --abort` first: `git switch -C` refuses while rebasing, and `reset --hard` leaves the rebase in progress.
- Recovery is `git switch -C <branch> backup/<name>-<date>` (or `git reset --hard backup/<name>-<date>` on a clean tree), or `git reset --hard <branch>@{N}` on a clean tree, and it comes before trying anything else.

## 3. Conflicts

- Read both sides before choosing: `git diff --merge`, or `git log --merge -p -- <file>` for what each side intended.
- Decide each hunk by what both changes were for, not by which side is newer.
- **Generated or counted files are never picked.** Take either side, finish the merge, then re-run the producer and commit its output. A count pinned in two places conflicts whenever both sides added a case, and neither side is right.
- Lockfiles: resolve the manifest, then regenerate the lockfile with the package manager.
- A rebase replays commits one at a time; the same hunk can conflict at every step. `git rerere` records resolutions so the repeats resolve themselves, once enabled with `git config rerere.enabled true`; by default it records nothing. The rebase still stops on a replayed resolution (`Resolved ... using previous resolution`): check the file, `git add` it and continue, or set `rerere.autoUpdate true` to stage it.
- Verify after resolving: the build and the tests that cover the conflicted files, observed.

## 4. Bisect

1. Name a known-good commit and a known-bad commit, each confirmed by one observed run.
2. Name the exact command that tells them apart. `git bisect run` reads its exit code: 0 is good, 125 skips the commit, 128 to 255 aborts the bisection, and every other code from 1 to 127 is bad. Wrap the test so a build failure exits 125 (otherwise a commit that does not build is named the culprit) and a missing tool or setup error exits 128 or higher (a tool that is missing only on later commits reads as bad; on a `good` revision git aborts with `bogus exit code 127`).
3. Bisect checks out commits in the working tree: use a clean tree or a throwaway worktree (`git worktree add --detach ../bisect <bad>`). `git bisect start <bad> <good>`, then `git bisect run <command>`.
4. Record the first bad commit and the command's output at it and at its parent.
5. `git bisect reset` to return.

A flaky command bisects to noise. Measure its failure rate first; if it is not 0% on good and 100% on bad, loop it inside the bisect command until it is.

## 5. History rewrite

| Goal | Command | Rewrites |
| --- | --- | --- |
| Squash or reorder before review | `git rebase -i <base>` (or `--autosquash` with `fixup!` commits) | every commit after `<base>` |
| Fix the last commit | `git commit --amend` | the last commit |
| Drop local commits | `git reset --hard <ref>` | the branch pointer |
| Undo a pushed commit without rewriting | `git revert <sha>` | nothing |

Pushing a rewrite: `git push --force-with-lease=<branch>:<expected-sha> origin <branch>`. The lease refuses the push when the remote moved since the inventory, which is exactly the case a bare `--force` would silently destroy. Never force-push a shared default branch; revert there instead.

## 6. Stacked branches

When the base of a stack is rebased or squash-merged, every branch above it still carries the old base commits.

- Record each branch's old base **before** the base moves: `git rev-parse <base-branch>`.
- Restack each branch onto the new head of the one below it: `git rebase --onto <new-base> <old-base> <branch>`.
- Never compute the old base with `git merge-base` after the base was rewritten; it finds a commit the rewrite no longer contains and replays the base's commits onto itself.
- Push each restacked branch with `--force-with-lease`, bottom-up.

## 7. Cherry-pick, detached HEAD, lost commits, committed secrets

Each starts with the pushed-state inventory and a recovery point.

- **Cherry-pick**: `git cherry-pick -x <sha>` records the source commit in the message. A merge commit needs `-m 1` (the parent to diff against). On a conflict resolve as in section 3, then `git cherry-pick --continue`, or `git cherry-pick --abort` to return.
- **Detached HEAD**: commits made there belong to no branch. Before switching away, `git switch -c rescue/<name>` keeps them.
- **A lost commit or deleted branch**: `git reflog` lists where HEAD was (a deleted branch's own reflog is deleted with it, so use the HEAD reflog); `git branch rescue/<name> <sha>` brings the commit back. Unreachable reflog entries expire (30 days by default; reachable ones 90), so do this first. When the reflog has nothing, `git fsck --lost-found` lists dangling commits.
- **Undo the last commit**: unpushed, keep the changes: `git reset --soft HEAD~1`; pushed: `git revert <sha>`.
- **A secret was committed**: rotate it first, because every clone and fork keeps the old history. Whether the value must also leave the repository, and how, belongs to `omh-security-event-response` (its containment order decides; GitHub's own procedure uses `git filter-repo --sensitive-data-removal` in a fresh clone, then a push of every rewritten ref as that page documents, and a request to Support for cached views and pull-request refs). `git filter-repo` refuses to run outside a fresh clone and, without `--sensitive-data-removal`, removes the `origin` remote (with that flag it keeps it, and GitHub's procedure pushes to it), so a bare `--force-with-lease` has nothing to compare against after a plain run. Do not improvise the rewrite here.

## 8. Shared checkouts and worktrees

- Two sessions in one checkout share `HEAD`: a `checkout` by one moves the other's next commit onto the wrong branch. Use one worktree per session.
- Removing a worktree mid-rebase loses the rebase state; finish or abort the rebase first.
- A commit that landed on the wrong branch is moved with `git branch -f` or a cherry-pick plus a reset on the wrong branch, and the other session's branch is repaired with `git update-ref`, never a `reset --hard` inside their checkout.
