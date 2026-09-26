# Contributing

Thanks for helping improve oh-my-hermes.

## Development Setup

```sh
uv sync --group lint
PYTHONPATH=tests uv run python -m unittest discover -s tests
```

The development install uses setuptools' strict editable mode. Its auxiliary
`build/__editable__.*` tree links to the implementation files through the same
`omh` package layout as a wheel. This makes the package's inline types and
definitions readable by basedpyright without evaluating runtime import hooks.
Select the project's `.venv` interpreter in your editor; `pyrightconfig.json`
gives tests their documented `PYTHONPATH=tests` import root.

After adding, renaming, or replacing source files, refresh the linked layout:

```sh
uv sync --group lint --reinstall-package oh-my-hermes
```

Keep the auxiliary editable tree while using that environment. This matters
especially on filesystems where setuptools uses hard links instead of symbolic
links. Contributors using pip can select the same layout with
`python -m pip install -e . --config-settings editable_mode=strict`.
The `py.typed` marker exposes the existing annotations; it is not a claim that
every repository file has passed a project-wide strict type check.

Run the static-analysis gate the same way CI does, using the pinned Ruff
version declared under `[dependency-groups] lint` in `pyproject.toml` (no
globally installed `ruff` needed):

```sh
uv run --group lint ruff check src tests
```

## Contribution Rules

- Keep Hermes as the runtime boundary.
- Keep installer behavior reversible and inspectable.
- Do not write workspace guidance files by default.
- Do not overwrite locally modified managed skills unless the caller passes
  `--force`.
- Add or update tests for routing, config edits, manifest behavior, and command
  output when those contracts change.
- Keep generated skill text conservative. It may guide routing, but it must not
  claim hidden control over Hermes core behavior.

## Pull Request Checklist

- The change is scoped and explained.
- Tests pass locally.
- `uv run --group lint ruff check src tests` passes locally.
- Public docs were updated when behavior changed.
- Generated docs were refreshed or `python -m omh.cli docs workflows --check`
  was run when catalog data changed.
- Release-channel impact was considered for installer, update, or packaging
  changes.
- Runtime or native capability claims are backed by artifact evidence, wrapper
  evidence, or explicit "not observed" language.
- The PR description includes risk, validation, and known gaps.
- New public strings avoid coupling the project to another agent runtime.

## Commit Messages

Use concise decision-oriented messages. Mention why the change exists, not just
what files changed.

### Sign your commits (required)

Every commit must carry a Developer Certificate of Origin sign-off. A `DCO`
check runs on each pull request and fails when any commit is missing one, so a
PR without sign-offs cannot merge.

Add it automatically with `-s`:

```sh
git commit -s -m "fix: stop the router matching bare 'plan'"
```

That appends a trailer built from your configured git identity:

```
Signed-off-by: Your Name <you@example.com>
```

The name and email must match the commit author, and `Signed-off-by:` must be
the **last** trailer in the message. If you forgot on the most recent commit:

```sh
git commit --amend -s --no-edit
```

To fix a whole branch at once:

```sh
git rebase --signoff origin/main
```

Both rewrite history, so force-push the branch afterwards
(`git push --force-with-lease`).

By signing off you certify the [Developer Certificate of
Origin](https://developercertificate.org/): that you wrote the patch or
otherwise have the right to submit it under this project's license.

### Decision trailers

Maintainer and agent commits also carry decision trailers — `Constraint`,
`Rejected`, `Confidence`, `Scope-risk`, `Directive`, `Tested`, `Not-tested` —
documented in `AGENTS.md`. They record why a change looks the way it does.
Outside contributions are welcome without them; only the sign-off is required.
Whatever else the message carries, `Signed-off-by:` stays last.

## Review and Labels

Pull requests are reviewed against [`REVIEW.md`](REVIEW.md), which defines what
counts as a blocking finding in this repository. Reading it before you open a
PR is the fastest way to avoid a round trip — most findings here are contract
drift, not ordinary bugs.

Two things catch outside contributions most often:

- **Generated files.** `skills/*/SKILL.md`, `docs/WORKFLOWS.md`,
  `docs/ROLES.md`, `examples/use-cases/g1-g10-demo-cards.json`, and
  `src/plugin_bundle/omh/tools/capability_families.json` are generated. Edit the
  source under `src/`, regenerate, and commit both. Byte-exact gates fail on a
  one-character drift.
- **Exact-count assertions.** Adding a routing case, skill, or demo card
  invalidates counts pinned in the tests. Update them in the same commit; they
  are the contract, not noise.

Labels are defined in [`.github/labels.yml`](.github/labels.yml) and applied by
the maintainer. You do not need to label your own PR.

## Test Sharding (CI)

CI splits the unit-test suite into deterministic shards per platform/version
(two for each Linux lane, four for the slower Windows lane, each lane from its
own plan over the same inventory) plus a serial quarantine, planned by
`tools/test_sharding/plan.py` and reconciled fail-closed by
`tools/test_sharding/aggregate.py`. This changes nothing for local
development: the full-suite command above
(`PYTHONPATH=tests uv run python -m unittest discover -s tests`) still runs
everything and remains the documented path.

To reproduce one CI shard locally:

```sh
python tools/test_sharding/plan.py --shards 2 \
  --durations tools/test_sharding/timings.json \
  --quarantine tools/test_sharding/quarantine.json --out /tmp/plan.json
python tools/test_sharding/run.py --plan /tmp/plan.json --lane local --shard 0 --out /tmp/result.json
python tools/test_sharding/run.py --plan /tmp/plan.json --lane local --quarantine --out /tmp/result-q.json
```

Rules that keep the plan green:

- Every discovered test is assigned exactly once. Renaming or deleting a
  test needs no shard bookkeeping; the plan is regenerated on every run.
- Tests that mutate process-wide state (signal handlers, spawned child
  processes, bound sockets, fixed ports) belong in
  `tools/test_sharding/quarantine.json`, never in the parallel shards. Each
  entry requires an `owner`, a `reason`, and an `added` date; an entry that
  matches no discovered test fails the plan, so the quarantine cannot grow
  silently or rot.
- `tools/test_sharding/timings.json` is the committed duration-history
  fallback used only to balance shards. It is performance data, never test
  or merge evidence. Successful `main` runs automatically save bounded
  immutable timing history; the next planner restores it over this fallback
  without executing test code or writing repository state.

### What gates a merge

The `aggregate` job is the gate. It depends on `test`, `test-windows`, and
`test-quarantine`, runs with `if: always()`, and fails unless every one of
them succeeded, so a failed, cancelled, or skipped shard cannot produce a
partial green. A green shard on its own proves only that slice ran; a green
`aggregate` is what proves the whole suite ran and reconciled.

This repository has no rulesets and no branch protection on `main` (verified
read-only on 2026-09-04), so nothing is enforced at the platform level today.
If protection is enabled later, require `aggregate` and nothing else: shard
job names change with the shard count, and the aggregate is already red
whenever any of them is.

The >=25% slowest-job speedup from issue #1294 is a target, not a result. It
is **NOT YET OBSERVED**, and the measurement procedure that would settle it,
including the metric, the 10-run corpora, exclusions, and the retry and flaky
comparison, lives in
[CI Test Sharding Rollout](docs/CI-TEST-SHARDING.md).
