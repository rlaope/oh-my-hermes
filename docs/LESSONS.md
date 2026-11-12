# Lessons from re-fixed commits

What a fix commit taught, after it replaced lines that a different pull request
had landed shortly before. A lesson is one rule a reviewer can check, with the
commit pairs that taught it. A lesson seen on three separate days moves into
[`REVIEW.md`](../REVIEW.md) and is marked moved here.

The practice of keeping lessons from re-fixed commits and promoting the one seen
on three separate days comes from reading `yetone/magpie` (MIT) at commit
`5e933e153a87c4017a19502e1d2e87aa714572b9`: concept only, nothing copied or
translated; the script and this file are written fresh against this repository's
own history.

## How this file is made

1. [`tools/refix_report.py`](../tools/refix_report.py) reads git history only.
   For each non-merge commit in the last `--days` (default 7) whose subject starts
   with `fix` or `hotfix`, it blames the lines that commit removes or replaces at
   its parent. A line is young when the commit that wrote it landed at most
   `--window-hours` (default 48) before the fix landed; "landed" is the time of
   the first-parent merge that brought the commit in. It prints every pair of a
   fix and an earlier commit from a different pull request, with the age and the
   files, and the counts.
2. A person or an agent reads the pairs and keeps only those where the first
   change left a real defect that the second repaired. Follow-up features, planned
   second steps, version bumps and wording changes are dropped. The script cannot
   tell them apart: its count of "another pull request" is an upper bound.
3. What is kept is grouped into lessons below. **Nothing runs this on a
   schedule**: a maintainer or an agent runs the script and edits this file by
   hand, when someone chooses to.

"Seen on N days" counts distinct UTC calendar dates of the fix commits, not
pairs. UTC is fixed here because the count decides a promotion and the commits
carry the author's local offset.

## Promotion rule

A lesson seen on 3 or more separate days moves into `REVIEW.md` as a rule and is
marked **moved** here, with the commit that moved it. Fewer than 3 days: it stays
here and is counted again on the next run. A lesson is not rewritten to reach the
bar.

## First run

Revision `65796e68ff3ff5daad7852e98a29f5352814d7e0`, last 7 days, window 48 h,
run on 2026-11-12 with `uv run python tools/refix_report.py 65796e68f --days 7`.
Re-run after the file-name fix (paths read with `git diff -z --name-only`, so
names with a space, a quote or non-ASCII letters are no longer dropped): the same
totals, and 0 files failed to blame.

| | Count |
| --- | --- |
| Non-merge commits landed in the range | 679 |
| Fix or hotfix commits | 179 |
| No young line replaced | 24 |
| Young lines only from the fix's own pull request | 75 |
| Young lines from another pull request | 80 |
| Pairs listed (fix commit, earlier commit) | 217 |
| Files git could not blame (`blame failed`) | 0 |
| Pairs kept | 8 |
| Pairs dropped | 209 |

How the pairs were read: for each of the 80 fix commits, the subject and the
first lines of the message were read (a few have none), and the diff and the
blame of the replaced lines were opened for every commit behind a kept pair and
for the borderline ones. The remaining pairs were sorted by their fix commit's
message and file list, not opened one by one, so a dropped pair may hide a
defect its message does not name. Why the 209 were dropped:

| Reason | Fix commits | Pairs |
| --- | --- | --- |
| UI review or visual polish of the earlier commit's own feature | 20 | 61 |
| Another pair of a fix that has a kept pair: these lines are not what the lesson is about | 6 | 25 |
| Skill-audit round editing earlier skill prose | 5 | 23 |
| Site preview rebuilt for a new omher release (planned follow-up) | 9 | 22 |
| A new case, platform or install layout added; the earlier lines were not wrong | 7 | 18 |
| Review round, QA finding or CI finding on the same feature in the same sprint | 9 | 15 |
| The owner changed a decision; nothing was broken | 5 | 15 |
| Pinned digest, count or schema size re-derived after a rebase or a wording change | 2 | 7 |
| Real defect, one instance, no rule a reviewer can check beyond its own test | 4 | 7 |
| Wording or documentation only | 2 | 5 |
| A step of the same planned work (the Windows port), not a defect | 1 | 3 |
| The defect predates the earlier commit (the blamed lines were wording or a condition made conditional) | 2 | 2 |
| The fix was itself wrong and was reversed within the hour | 2 | 2 |
| Repairs a regression its message attributes to a different commit than the one blamed | 2 | 2 |
| Already in `REVIEW.md`: a generated artifact left behind | 1 | 1 |
| The replaced line is only a visibility change; the defect was a spawn site another pull request added | 1 | 1 |

Three lessons survived. Fewer pairs would have meant fewer lessons; none was
written to fill a gap.

## Lessons

### 1. Another program's behaviour is recorded, not recalled — moved to `REVIEW.md`

**Rule.** When a change encodes how another program behaves (its protocol, its
method names, its output shape, what a host loads), the pull request carries a
fixture recorded from that program, or says no run against it was made.

**Why.** In each pair below the first version was written from documentation or
memory of the other side, and the repair followed the first time someone ran the
real thing. A `Not-tested:` line that names the real counterpart is the prompt to
ask which of the two the change did. The trailer alone does not flag these
changes: on this run 290 of the 679 commits (42.7%) and 44 of the 110 earlier
commits in range (40.0%) have a `Not-tested:` line containing the word `live`,
`real` or `actual` (a plain word match, not a reading of each line), so the rule
is about what the change encodes, not about the trailer.

**Evidence.**
- `8e2497ee5` (#2710, `folder.close` through the gateway; Not-tested: a live
  gateway) then `4bb220647` (#2797), 47.6 h: Hermes' gateway has no
  `session.close`, so the close came back `unknown_method` and the conversation
  stayed open; the repair checked the close against a live gateway.
- `763cfd0da` (#2710, chat adapters for five agent CLIs; Not-tested: the real
  Codex app-server and pi) then `61d463135` (#2737), 11.9 h: adapters rewritten
  to match streams recorded from each CLI, and replayed as fixtures; then
  `dacedac51` (#2782), 39.1 h: OmO and pi send statuses of their own after a turn
  ends, which the adapter had read as a new turn.
- `9ea185de4` (#2657, a pointer to the shared rail's turn-ending sections) then
  `ad0cc9e13` (#2680), 11.7 h: a live measurement found the rail was never
  loaded, so the pointer carried no rule.

**Seen on 3 days** (2026-11-08, 2026-11-10, 2026-11-11): fix commits
`ad0cc9e13`, `61d463135`, `4bb220647` and `dacedac51`. **Moved** to
[`REVIEW.md`](../REVIEW.md) ("Lessons from re-fixed commits") by the pull request
that added this file.

### 2. A lookup that takes the first match names how it ranks

**Rule.** Code that picks the first candidate (the first program of that name on
`PATH`, the first interpreter found) states in a comment or a table how
candidates rank, and a test puts two candidates present at once.

**Why.** Each time, the first candidate was the wrong one on a machine that had
two: a same-named program, or an older environment left behind by an upgrade.
The test with one candidate passes either way.

**Evidence.**
- `eec1ea026` (#2766, DSH added to the session list) then `2da525c11` (#2787),
  17.2 h: the first `dsh` on `PATH`, which on a machine with deepseek-bot is its
  launcher, was started.
- `2da525c11` then `d473b1135` (#2797), landed 0.4 h apart (the commits are
  2 h 43 min apart): the same fix for the other six agents; Homebrew's `grok`, a
  regex tool, was started as Grok.
- `06c5f2e3e` (#2677) then `fa07d89f7` (#2742), 42.7 h: the old `venv` was
  checked before the launcher Hermes runs on, so an upgraded install ran the
  bridge on the wrong Python.

**Seen on 2 days** (2026-11-10, 2026-11-11): fix commits `fa07d89f7`,
`2da525c11`, `d473b1135`. Not promoted. The date basis decides this one: in the
commits' own +0900 dates `d473b1135` falls on 2026-11-12 (01:03, 2 h 43 min after
`2da525c11`) and the count would be 3. Both are one working session, so they are
counted as one day here; a maintainer who counts local dates promotes it.

### 3. A fix for one of several sites lists the others

**Rule.** A pull request that fixes a defect at one call site says how the other
sites of the same defect were found (the search, or the list of sites) and what
it did with each.

**Why.** Both fixes here were correct where they landed, and the same defect
stayed alive one call site away until the next change.

**Evidence.**
- `04b4b75a8` (#2765, the host environment for the link opener only) then
  `8c3676dd8` (#2778), 8.6 h: the bridge's own spawn passed `PYTHONHOME` from
  the AppImage to the host Python, and 0.2.4 was published with it; the repair
  moved the environment into one helper used at every host-program spawn.
- `2da525c11` then `d473b1135` (above), the second one counted here too.

**Seen on 1 day** (2026-11-11): fix commits `8c3676dd8`, `d473b1135`. Not
promoted.

## What this file does not show

- It reads seven days of one repository. Three lessons from 8 kept pairs is a
  small sample, and each count above is from that one run.
- It finds a fix only when its subject starts with `fix` or `hotfix`, and only
  when the replaced lines were written inside the window by another pull request.
  A repair that adds lines and removes none is not listed.
- It does not say that a rule in `REVIEW.md` changed what later changes did.
  Nothing has measured that.
