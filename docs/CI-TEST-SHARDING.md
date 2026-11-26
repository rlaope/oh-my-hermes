# CI test sharding

How the sharded unit-test workflow gates a merge, and how the repository
ruleset requires that gate. Nothing here is a performance claim.

## The Gate Lives in the Workflow

The required gate is the `aggregate` job in `.github/workflows/ci.yml`. It
declares `needs: [test, test-windows]` with `if: always()`, then reads each
dependency's `result` and exits non-zero unless both are `success`. Failure, cancellation, or a skipped leg is red. A missing result
artifact is red, because the aggregate also re-proves that every discovered
test was assigned exactly once and accounted for exactly once across every
lane.

Two consequences worth stating plainly:

- Adding or removing a shard changes the matrix, not the gate. `test` is one
  matrix job with results collapsed into a single `needs.test.result`, so no
  check name has to be re-registered when the shard count changes.
- A green `aggregate` is the only signal that means "the whole suite ran".
  Reading an individual shard's green tick tells you about that slice only.

## The Offline Benchmark Framework Runs in the Shards

The live-model benchmark framework's own tests live under
`benchmarks/live-model-tools/v1/tests/`, outside `tests/`, so the static
inventory that builds the shard plan could not see them. They now run in the
same lanes as everything else.

`tests/test_live_model_benchmark_framework.py` declares one statically
discoverable delegator per upstream case and executes the real upstream
implementation through an explicit path load. It duplicates no assertion, so
the delegated run exercises the upstream contract itself, including the
paid-live authorization blocks. Nothing here requests live authorization: the
framework's offline `fake` harness is what runs, and no provider call is made.

An AST parity check compares the upstream file's declarations against this
file's. An upstream case that is added, removed, or renamed fails loudly in the
wrapper instead of silently dropping out of the shard plan, which is the exact
failure this arrangement exists to prevent.

Because the delegators are ordinary discoverable tests, they inherit the
properties the rest of the suite already has: every one is assigned exactly once
across the shards and the quarantine list, every lane (`test`,
`test-windows`) consumes a plan generated from the same inventory and
quarantine, and the `aggregate` job re-proves the exact-once
accounting. Benchmark coverage is
therefore gated by the same green tick as everything else, with no detached
workflow step to keep in sync.

What has been observed locally is the offline framework running green and the
generated plan carrying each delegator exactly once. Execution on the Windows
lane is observed in pull-request CI, from the same plan, and nowhere earlier.

## An omher-Only Pull Request Plans a Slice

A pull request whose every changed path is under `apps/omher/` (or is
`CHANGELOG.md`) cannot change the Python package. The `plan` job diffs the PR
against its base and passes `--changed-paths` to `plan.py`; for such a change
`tools/test_sharding/scope.py` keeps the test modules whose source names omher,
the changelog, `apps/`, or walks the whole repository tree, about 6% of the
inventory. Both lanes plan the same slice, and the aggregate reconciles it
exactly once as usual. Any other change, an empty diff, and every main push plan
the full inventory, and main re-runs the whole suite on the merged tree, so a
slice that misses a test fails there. The quarantine is validated against the
full inventory before it is cut to the slice, so a stale entry still fails the
plan.

## Per-Lane Shard Counts

The Windows lane runs the same suite more than twice as slowly as the Linux
lanes, so it gets its own plan. The `plan` job writes two files into the
`shard-plan` artifact from the same inventory, timing history, and quarantine:
`plan.json` with 3 shards for each Linux lane, and `plan-windows.json` with
6 shards for `windows-3.12`. Both are deterministic, so identical inputs give
byte-identical plans.

`aggregate.py` binds each lane to the plan it ran (`--lane-plan
windows-3.12=shard-plan/plan-windows.json`; every other lane uses `--plan`).
It refuses a lane plan that does not assign the same discovered tests and the
same quarantine as the default plan, and then requires every shard of each
lane's own plan to be reported, so a missing Windows shard 5 is red even though
the Linux lanes have no shard 5.

Two loads besides the shard list are seeded into the plan before balancing,
so the LPT partition accounts for them:

- **Shard 0 gates.** Each lane's shard 0 also runs non-test gates: the native
  fanout smoke, compile, and the PowerShell installer checks on Windows, and
  the docs, compile and smoke gates on Linux. `plan.py --shard0-offset` takes
  their duration as a declared constant: 90 s for Windows and 25 s for Linux,
  from step-duration medians read on 2026-09-26. The comment beside the `plan`
  step in `ci.yml` records where the numbers came from. The number is not
  measured at plan time, so re-read it when those gates change.
- **Serial quarantine.** The quarantined tests no longer have their own
  `test-quarantine` jobs. Each lane runs them in a separate `run.py
  --quarantine` process, serially, after its last shard's tests: shard 2 on
  Linux, shard 5 on Windows. That job uses the same OS and Python as the rest
  of the lane. The planner seeds the quarantine's duration onto the last
  shard, which leaves that shard the lightest share of parallel tests. The
  aggregate still requires each lane's quarantine result to account for every
  quarantined test, and fails closed when the result is missing. This removed
  3 jobs per run: at 0.5 to 0.9 minutes each they were cheap to execute, but
  under the account's 20-concurrent-job cap they queued for 10 to 17 minutes
  in bursts.

## Lanes Per Event

Which Linux lanes run depends on the event that started the workflow:

| event | lanes |
| --- | --- |
| `pull_request` | `linux-3.11` (3 shards), `windows-3.12` (6 shards) |
| `push` to `main`, `workflow_dispatch` | `linux-3.11`, `linux-3.13` (3 shards each), `windows-3.12` (6 shards) |

A pull request runs the supported floor, 3.11, on Linux. A main push adds 3.13,
the newest supported interpreter, where 3.12 used to run; Windows keeps 3.12 on
every event. The evidence at the time of the change (2026-09-26, the 7 days
before it): 0 of 40 failed runs were red only on Linux 3.12, while a defect only
CPython 3.13 shows (`Path.resolve` on a symlink loop, fixed by 13696e5d) had
merged with every lane green.

`aggregate.py --event ${{ github.event_name }}` looks the lane set up in
`EXPECTED_LANES`, refuses an event it does not know, and requires every shard
and the quarantine of each expected lane. So a main run that lost its 3.13
lane is red with `missing result for linux-3.13 shard 0`, and a pull request
run that reported a lane it should not have is red too.
`tests/test_test_sharding.py` pins the `test` matrix expression and the
workflow's triggers to that table.

A 3.13-only failure is first seen on main, not on the pull request. To see
the main lane set before merging, dispatch the workflow on the branch:
`gh workflow run ci.yml --ref <branch>`.

## Superseded Runs Are Cancelled

`concurrency` groups a pull request run by its number and every other run by its
ref, and cancels the run in progress when a newer one starts. On main this
trades per-commit attribution for runner time. At the time of the change
(2026-09-26, the 7 days before it), 32 of 86 main runs were superseded by a
later main push before they finished, at ~140 job-minutes each, and one 5-push
burst left test jobs queued for 13 to 17 minutes. A red main is now attributed
to the range of merges since the last completed run. The tip run still tests
every merged commit, because its tree contains them all.

Nothing depends on every main run completing:

- **Timing history.** Only a green main run's `aggregate` saves a cache entry,
  keyed by run id. A cancelled run saves nothing, and the next `plan` restores
  the newest `test-sharding-timings-` entry, which the burst's tip run wrote.
  History would stall only if main never went quiet for one full run; the
  committed `timings.json` fallback covers the time before any entry exists.
- **Pages** and **Cut Release** are separate workflows with their own triggers
  and concurrency groups; neither reads a CI run's result. Cut Release runs
  its own full suite on the tree it tags.
- **The rollout metric** below already counts only successful push runs, so
  cancelled runs drop out of both corpora on their own.

`aggregate` keeps `if: always()`, so it still starts in a cancelled run and
goes red at its first step. That costs one short job, and it keeps a skipped
`aggregate` from ever standing in for a green one.

## Re-running Failed Jobs

"Re-run failed jobs" (`gh run rerun --failed`) re-executes only the failed
shard jobs and the jobs that depend on them, `aggregate` among them. The
shards that passed are carried over, and so are their result artifacts. The
re-run shard uploads a new result into the same run. The earlier attempt's
artifact stays: GitHub numbers the new attempt `github.run_attempt` 2 (the
[`github` context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context)),
and `upload-artifact`'s one-artifact-per-name rule did not stop attempt 2
from uploading a second `shard-result-windows-3.12-0` in run 36302750878.

Before #1894, both attempts used the same artifact name. `download-artifact`
downloads a pattern with `latest: true`, which keeps one artifact per name,
choosing the highest artifact ID
(`filterLatest` in [`actions/toolkit` `list-artifacts.ts`](https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/find/list-artifacts.ts)).
Artifact IDs are not issued in creation order. In run 36302750878, attempt 2's
green result got ID 10926093432, lower than attempt 1's red result at
10926586117. `aggregate` therefore reconciled the stale red result and
reported "windows-3.12 shard 0 reports 0 failures, 1 errors" over a green
re-run. `overwrite: true` was rejected. Its delete filters by the current job
run's backend ID and picks among same-name artifacts by the same ID order
(`deleteArtifactInternal` in
[`delete-artifact.ts`](https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/delete/delete-artifact.ts)).
Nobody has observed what that filter returns across attempts. Where it does
remove the earlier artifact, it also erases that attempt's record.

Now every shard and quarantine result carries the attempt in three places: the
artifact name (`...-attempt-${{ github.run_attempt }}`), the file name, and
the result JSON (`run.py --attempt`). No two attempts share a name, so the
download keeps them all. `aggregate.py` keeps each lane shard's newest
attempt, and every other check stays fail-closed:

- The newest attempt wins in both directions. A fresh green result replaces a
  stale red one, and a stale green result can never hide a fresh red one.
- A shard with no result in any attempt is red (`missing result`).
- Two results for one shard in the same attempt are red (`duplicate result
  ... in attempt N`).
- A result without a positive integer `attempt` is red at the JSON boundary.
- A re-run shard job that fails before it uploads is still red, because
  `Require green shard jobs` reads the job's result for this attempt.

A green `aggregate` lists each superseded result as
`superseded: <lane> shard <n> attempt 1 by attempt 2`.

## Repository Settings

`main` is governed by the active ruleset "main: merge only on green aggregate
and DCO". It blocks deletion and non-fast-forward pushes and requires two
status checks: `aggregate` and `DCO`. There is no separate branch-protection
object; `gh api repos/rlaope/oh-my-hermes/branches/main/protection` returns 404,
and `gh api repos/rlaope/oh-my-hermes/rulesets` is the place to read the gate.

`aggregate` is the only CI check the ruleset needs. Pinning individual shard
jobs such as `test (3.11, 0)` would break the moment the shard count changes,
and pinning them alongside `aggregate` adds nothing: the aggregate is already
red whenever any of them is.

## Unrun measurement plan (#1294)

Issue #1294 asks for a median slowest-test-job reduction of at least 25%; that
is a target, not a result, and it has not been measured. The plan: take the
slowest test-executing job's `completed_at - started_at` (not `created_at`) per
run, over two corpora of at least ten successful, non-re-run `push` runs of
`ci.yml` on `main` from before and after the sharding merge, excluding runs that
touch `tools/test_sharding/` or `.github/workflows/ci.yml`; the target is met
when `(baseline_median - post_median) / baseline_median >= 0.25` and neither the
retry rate nor the flaky-failure rate rose. Timing data is performance evidence
only, never test, review, merge-readiness, or merge evidence.

## Rolling Back

Revert the `plan` and `aggregate` jobs and the quarantine steps in
`.github/workflows/ci.yml`, and in the same step change the ruleset's required
checks from `aggregate` to the restored full-suite matrix jobs (named
`test (<version>)` and `test-windows`, one per matrix leg), keeping `DCO`.
