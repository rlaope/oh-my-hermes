# CI Test Sharding Rollout

How the sharded unit-test workflow gates a merge, what still has to change in
repository settings, and the exact procedure for deciding whether the speedup
target from issue #1294 was met.

Nothing here is a performance claim. As of this document's merge, **no
post-rollout measurement has been taken: NOT YET OBSERVED.**

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

## Per-Lane Shard Counts

The Windows lane runs the same suite more than twice as slowly as the Linux
lanes, so it gets its own plan. The `plan` job writes two files into the
`shard-plan` artifact from the same inventory, timing history, and quarantine:
`plan.json` with 2 shards for `linux-3.11` and `linux-3.12`, and
`plan-windows.json` with 4 shards for `windows-3.12`. Both are deterministic,
so identical inputs give byte-identical plans.

`aggregate.py` binds each lane to the plan it ran (`--lane-plan
windows-3.12=shard-plan/plan-windows.json`; every other lane uses `--plan`).
It refuses a lane plan that does not assign the same discovered tests and the
same quarantine as the default plan, and then requires every shard of each
lane's own plan to be reported, so a missing Windows shard 3 is red even though
the Linux lanes have no shard 3.

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
  --quarantine` process, serially, after its last shard's tests: shard 1 on
  Linux, shard 3 on Windows. That job uses the same OS and Python as the rest
  of the lane. The planner seeds the quarantine's duration onto the last
  shard, which leaves that shard the lightest share of parallel tests. The
  aggregate still requires each lane's quarantine result to account for every
  quarantined test, and fails closed when the result is missing. This removed
  3 jobs per run: at 0.5 to 0.9 minutes each they were cheap to execute, but
  under the account's 20-concurrent-job cap they queued for 10 to 17 minutes
  in bursts.

## Repository Settings

Read-only inspection of `rlaope/oh-my-hermes` on 2026-09-04:

```sh
gh api repos/rlaope/oh-my-hermes/rulesets            # => []
gh api repos/rlaope/oh-my-hermes/branches/main/protection  # => 404 Not Found
```

There are no rulesets and no branch-protection object on `main`. So there is
no required-status-check list to migrate, and this repository does **not**
currently enforce any check at the platform level. Do not read the workflow's
fail-closed behavior as branch protection; they are separate mechanisms.

If a maintainer later enables branch protection or a ruleset, the required
check to select is `aggregate`, and only `aggregate`. Pinning individual shard
jobs such as `test (3.12, 0)` would break the moment the shard count changes,
and pinning them alongside `aggregate` adds nothing: the aggregate is already
red whenever any of them is.

## Measuring the >=25% Target

Issue #1294 asks for a median slowest-test-job reduction of at least 25% over
at least ten comparable successful push runs, with no increase in retry or
flaky-failure rate. Run this after the sharded workflow has landed on `main`
and accumulated enough history. Until then the result is NOT YET OBSERVED.

### Metric

For a single run, the **slowest test-job duration** is the maximum, over the
test-executing jobs in that run, of `completed_at - started_at` in seconds.

Test-executing jobs are exactly:

- Baseline (pre-sharding): `test (3.11)`, `test (3.12)`, `test-windows`.
- Post-rollout: every `test (<version>, <shard>)` and every
  `test-windows (<shard>)` job (before the quarantine was folded into the last
  shard, also every `test-quarantine (...)` job).

Excluded from the metric in both corpora: `plan`, `aggregate`, `distribution`,
and any job that is not one of the above. `plan` and `aggregate` are counted
separately as rollout overhead (see below) because they are new serial hops,
not test execution.

Use `started_at`, not `created_at`. Queue wait belongs to runner availability,
not to the suite, and mixing them makes the comparison noise-dominated.

### Corpus

Two corpora of at least 10 runs each:

- **Baseline**: the last 10 `workflow_dispatch`-free `push` runs of `ci.yml` on
  `main` with `conclusion == success` whose commit predates the sharding merge.
- **Post-rollout**: the first 10 `push` runs of `ci.yml` on `main` with
  `conclusion == success` whose commit is the sharding merge or later.

Comparable means all of: same workflow file name, `event == push`,
`head_branch == main`, `conclusion == success`, and standard GitHub-hosted
runners. Exclude any run that is a re-run (`run_attempt > 1`), any run whose
diff touches `tools/test_sharding/` or `.github/workflows/ci.yml`, and any run
during a declared GitHub Actions incident. If exclusions leave fewer than 10
runs on either side, the measurement is not yet available; say so instead of
comparing smaller corpora.

### Procedure

```sh
REPO=rlaope/oh-my-hermes

# 1. List candidate runs, newest first, and record run IDs + head SHAs.
gh run list --repo "$REPO" --workflow=ci.yml --branch main \
  --event push --status success --limit 40 \
  --json databaseId,headSha,createdAt,attempt

# 2. For each selected run ID, pull per-job timings.
gh api "repos/$REPO/actions/runs/<RUN_ID>/jobs" \
  --jq '.jobs[] | [.name, .conclusion, .started_at, .completed_at] | @tsv'
```

For each run, keep only the test-executing job names above, compute each job's
duration in seconds, and take the maximum. That single number is the run's
slowest test-job duration. Then take the median across the 10 runs in each
corpus, and:

```
reduction = (baseline_median - post_median) / baseline_median
```

The target is met when `reduction >= 0.25`.

### Retry and Flaky Comparison

The speed number is meaningless if reliability dropped, so compute both of
these over the same two corpora and require neither to increase:

- **Retry rate**: the share of `push` runs on `main` in the window that have
  any job with `run_attempt > 1`, or any manual re-run recorded against the
  run. Compare the post-rollout window's rate against the baseline window's
  rate over an equal number of runs.
- **Flaky-failure rate**: the share of `push` runs on `main` in the window
  that failed and then passed on re-run with no intervening code change to
  `src/`, `tools/`, or `tests/`. Include failed runs here, unlike the timing
  corpus, which is success-only.

If either rate rises, the target is not met regardless of the timing number.
Rebalance or reduce the shard count and re-measure rather than reporting a
partial pass.

### Rollout Overhead

Record, but do not net against the timing result: the added wall-clock of the
serial `plan` job and the `aggregate` job, and the added billable minutes from
running more jobs in parallel. Sharding trades CI minutes for wall-clock time
by design. Both numbers belong in the rollout report so the tradeoff is visible
rather than implied.

### Reporting

State the two medians, the computed reduction, both reliability rates, the run
IDs used on each side, and every exclusion applied. Timing data is performance
evidence only. It is never test, review, merge-readiness, or merge evidence.

## Rolling Back

Revert the workflow's `plan` and `aggregate` jobs and the quarantine steps and
restore the single full-suite `unittest discover` invocation per matrix job.
Nothing outside `.github/workflows/ci.yml` and `tools/test_sharding/` has to
change, and because no branch protection references these job names, no
settings change is needed to roll back.
