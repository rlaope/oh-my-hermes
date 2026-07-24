# Fanout: Parallel Split, Dispatch Bridge, and Merge Contract

Audience: operators, wrappers, and coding agents. Normal users describe the
goal to Hermes in chat; these commands are the backend surface.

## Lifecycle

1. **Propose** — Hermes (the LLM) proposes the unit split in chat: unit ids,
   titles, owners, file boundaries, dependencies.
2. **Freeze** — `omh coding fanout prepare --goal <words> --units units.json
   --record` validates the split deterministically (boundary overlaps without
   a `depends_on` edge are hard errors; dependency cycles are hard errors) and
   freezes it as `fanout_contract/v1` under `~/.omh/coding/fanout/<id>/`. The
   goal is stored as a digest only.
3. **Dispatch (opt-in bridge)** — `omh coding fanout dispatch <id>
   --goal-file goal.txt` spawns each spawnable unit's local agent CLI in an
   isolated per-unit worktree, dependency-aware, with bounded concurrency.
4. **Observe** — `omh coding fanout show <id>` joins the frozen contract with
   per-unit run records; unit status is `not_observed` until real evidence
   exists.
5. **Merge (human/agent-gated)** — dispatch never merges. The summary lists
   merge-ready units in the contract's `merge_order`; merging and the final
   integration gate remain the operator's or reviewing agent's job.

## Dispatch bridge semantics

- **Spawnability is data.** `DISPATCH_COMMAND_TEMPLATES` in
  `src/coding/fanout_dispatch.py` maps profiles with a local headless CLI to
  fixed argv templates. Profiles without a template (hermes, omx/omo/omc
  runtimes, generic, unassigned) are reported
  `unsupported_for_local_dispatch` with the unit handoff as a prepared-prompt
  fallback — no profile is privileged.
- **Bridge dispatch is a separate axis from chat prompt-handoff.** Chat
  surfaces keep their prompt-only semantics for prompt-only profiles; the
  bridge is an operator-invoked command on a different surface.
- **Goal integrity.** `--goal-file` must hash to the digest frozen in the
  contract; a diverged goal is refused.
- **Worktrees.** One per unit at `<repo>-fanout-<unit>` on branch
  `agent/<unit>`, all branched from one SHA resolved at dispatch start
  (`--base-ref`, default HEAD). Pre-existing paths or branches are errors,
  never silently reused. Worktrees are never auto-deleted; reconcile with
  `git worktree list`.
- **Evidence.** Each dispatched unit gets a run named by its `run_ref`;
  spawn and exit are recorded as journal observations
  (`worker_dispatch`/`worker_result`, canonicalized to
  `executor_dispatch_observed`/`executor_result_observed`).
- **Dependency bar.** A satisfied dependency means only that the owner agent
  process exited 0. It is not verified, reviewed, or correct work. Failed
  units block their dependents, never their independents.
- **Blocked-by-design cascades.** An `unsupported_for_local_dispatch` or
  `executor_not_ready` dependency also blocks its dependents — dependents must
  never build on an unstarted base. Recovery: complete that unit manually (or
  via its owner's own tooling), record its observed result on the unit's
  `run_ref` run, then re-run `dispatch --unit <dependent>`; completed units
  satisfy dependencies even when not re-selected. Blocked entries carry a
  `blocked_on` list naming the offending units.
- **First-use validation note.** `codex exec` has in-repo precedent; the
  `claude -p ... --permission-mode acceptEdits` template does not — validate
  it interactively on first real use before relying on it in bulk fanouts.
  Template drift in either CLI surfaces as a clean readiness or exit-code
  failure recorded as observed evidence, and the fix is a one-line data edit
  in `DISPATCH_COMMAND_TEMPLATES`.
- **Resume.** Re-running dispatch skips units whose runs already carry an
  observed successful result. `--unit <id>` selects subsets.
- **Never**: auto-merge, default-on execution, network calls by omh itself,
  raw-prompt persistence under `.omh`.

## Command reference

```sh
omh coding fanout prepare --goal <words...> --units units.json [--record] [--source discord]
omh coding fanout validate --units units.json
omh coding fanout show <fanout-id>
omh coding fanout dispatch <fanout-id> --goal-file goal.txt \
  [--repo-root .] [--base-ref HEAD] [--concurrency 2] [--timeout 1800] \
  [--unit <id> ...] [--dry-run]
```

`--units` and `--goal-file` accept `-` for stdin. `--dry-run` resolves
readiness, planned argv, and worktree paths without spawning anything or
creating any runs.
