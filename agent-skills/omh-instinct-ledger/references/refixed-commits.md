# Instinct Ledger: Lessons From Re-Fixed Commits

Load this when the evidence for an instinct is a repository's git history: a fix that came soon after another change to the same lines. The method idea of mining re-fixed commits is taken from `yetone/magpie` (MIT, commit `5e933e153a87c4017a19502e1d2e87aa714572b9`), concept only and written fresh for this skill.

## 1. What a re-fix is

A re-fix is a fix commit that replaces lines a different pull request landed shortly before. The first change was not enough, and the fix is the repository's own record of what the first author missed.

1. List the fix commits in the window (subjects that start with `fix` or `hotfix`, on the first-parent history of the default branch).
2. For each fix, find the lines it removes or changes, then blame exactly those lines in the fix's parent: `git blame --porcelain -L <start>,<end> <fix>^ -- <path>`. The blame names the commit that last wrote each line.
3. Split by how the blamed commit reached the branch. When it came in through the same first-parent merge as the fix, it is a review fixup before merge and not a signal. When it came in through another merge, the pair is a signal: one pull request left a fault that a later one repaired.
4. Keep the pairs where the blamed commit is recent (the window is the person's to choose, such as 48 hours) and discard pairs where only whitespace, comments, or generated files changed.

## 2. The count is an upper bound

Ordinary follow-up work also replaces recent lines: a feature built in two steps, a rename, a planned second half. Read each pair, both diffs and both pull request descriptions, and keep only the pairs where the first change had a defect the fix removed. Report how many pairs the search returned and how many were kept; the first number alone proves nothing.

## 3. One observation per pair, one per day

A kept pair is one observation, with the two commit ids as its evidence refs. Two pairs from the same day count once, the skill's own "one session counts once" rule applied to days: one busy day with one cause is one anecdote. The confidence thresholds are unchanged: 1 is an anecdote, 2 is tentative, 3 or more with no contradicting observation is a promotion candidate.

## 4. The ledger line

Each line carries four things and nothing else:

- the rule, as one sentence a reviewer can apply to a diff;
- why, naming the fault the pair showed;
- the two commits, the one that left the fault and the one that fixed it;
- the days seen, one date per counted observation.

Example shape: `rule: a fix reaches every place of the same shape | why: the same lookup fault was fixed for one agent and left in six others | commits: <first>, <fix> | days: <date>`.

## 5. Where a promoted rule goes

A rule with three or more days becomes a rule candidate for `omh-rules-distill`, with the destination the repository's own review instructions (`REVIEW.md`, or the review section of its agent guidance). It stays in `instinct_candidate/v1` until that store route accepts it; do not edit the review instructions from this skill.

## Boundary

The search reads history and writes nothing. A blame result is evidence of which commit wrote a line, not of why, and a listed pair is a candidate until someone has read both changes.
