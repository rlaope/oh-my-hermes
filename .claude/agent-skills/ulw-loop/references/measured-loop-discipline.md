# Measured Loop Discipline

Load this reference when a loop's goal has a score: one command that judges the work and reports a number the loop is trying to move. Constraint discipline decides where the next unit of attention goes; this decides what survives once it has been spent.

## When A Loop Is Measurable

All three conditions must hold:

- A command runs unattended to completion - no prompts, no manual setup, no human reading the output to decide.
- It reports exactly one number. Several signals may feed it, but the loop compares one value.
- The number has a declared direction: higher is better, or lower is better.

If any condition fails, the loop is unmeasured. It says so plainly and keeps deciding on its verification gates - tests, review, named acceptance criteria - instead of inventing a score. A fabricated metric is worse than none: it makes arbitrary discard decisions look principled.

## The Evaluation Contract

Fix the contract before the first attempt and record it as loop-held state beside the `loop_cycle/v1` artifact the loop already maintains.

| field | meaning |
| --- | --- |
| `command` | the exact unattended command that produces the score |
| `metric` | what the single number counts |
| `direction` | `higher_is_better` or `lower_is_better` |
| `harness_mutable: false` | the contract is fixed for the run - see below |
| `baseline` | the metric value before the first attempt |

Non-gameability: the loop may not edit the scoring harness, its fixtures, or the metric definition. Raising the score by changing what the score means is not an improvement. If the contract genuinely must change, that starts a new baseline, and every earlier ledger line is labelled as measured under the old contract rather than compared across the boundary.

OMH validates no such field today. The contract is a discipline the loop keeps in its own state; no schema enforces `harness_mutable`, and no gate rejects a loop that edits the harness judging it. This is a deliberate deferral, stated here because a reader would otherwise assume the enforcement exists.

## The Attempt-Commit Cycle

One cycle: make one attempt, commit it, run the command, keep or reset - all on a branch or worktree the loop owns, so a reset never discards work that is not the loop's own.

The commit precedes the measurement. A committed attempt has a stable name, so a discard is a reset to a known parent instead of an effort to remember what was edited, and a keep needs no second step. Measuring first leaves the winning state living only in the working tree.

Rewinding past the immediate parent to an older ancestor is justified only when a run of discards traces to one bad ancestor that every later attempt inherited. It stays rare, because repeated discards usually mean a bad idea rather than a bad ancestor, and rewinding throws away kept work.

This is not a workflow pattern. A workflow pattern says how many agents run per step inside one cycle; this says what happens across cycles.

## Keep And Discard Rules

- Better metric: keep.
- Worse metric: discard, reset, next attempt.
- Crash or non-zero exit from the scoring command: discard and log the cycle with status `crash`. Never silently retry - a crash that repeats is a finding.
- Equal metric: keep the simpler change. Less code at the same score is a win.
- A deletion that holds the metric is always kept.
- A gain inside measurement noise is not a gain. If the command is nondeterministic, establish its spread first and treat anything smaller as equal.

## The Experiment Ledger

One append-only, tab-separated line per cycle, maintained by the loop itself:

| column | meaning |
| --- | --- |
| `commit` | the commit the attempt produced |
| `metric` | the measured value |
| `cost` | what the cycle spent - turns, tokens, or wall time |
| `status` | `kept`, `discarded`, or `crash` |
| `description` | one line naming what was tried |

OMH emits no such ledger. It is the loop's own running record and a companion to the JSON artifacts, never a replacement for them, and its rows stay `prepared` until they carry evidence refs.

## Log Hygiene

Send full command output to a file. Bring only the declared metric line and any error lines into context. Read the whole log only when the status is `crash`.

Context spent re-reading a passing cycle's log is context not spent on the next attempt: a loop that pastes a green log every cycle exhausts its budget before it exhausts its ideas.

## Idea Exhaustion

When attempts stop producing gains, climb in order:

1. Re-read the scoped files. Most exhaustion is stale context, not a solved problem.
2. Recombine the near misses - the discards that came closest. Two partial ideas often compose into one that keeps.
3. Escalate to a more radical change: replace the approach instead of tuning it.
4. Only then record the loop as blocked, naming the reason and the ladder step it stopped on.

Declaring blocked before step 3 is premature; skipping step 4 and cycling on noise is worse.

## What This Does Not Change

- The permission profile still gates every dispatch and every repository mutation - committing an attempt or resetting to discard one needs `repo_edit` in the loop's authority envelope. A metric win authorizes nothing the profile forbids.
- A metric win is not execution, review, CI, merge, or completion evidence. It stays `prepared_not_observed` until an evidence ref exists.
- The goal closes only on linked `goal_ledger/v1` evidence.
- The binding constraint from `references/goal-constraint-discipline.md` still chooses which attempt to make. The metric only chooses whether that attempt is kept.

## Attribution

The measured-loop discipline above adapts the operating practices of the `karpathy/autoresearch` project. No upstream text is reproduced. OMH maps the mechanisms onto its own loop cycle, queue, permission envelope, and evidence vocabulary, and keeps a metric decision separate from completion evidence.
