## Why This Exists

`ultrawork` exists to choose one-owner, ordered-dependency, or independent-frontier execution for an accepted implementation plan without letting concurrency blur ownership, verification, worker protocol, worktree isolation, or observed runtime evidence. It also carries four named internal capabilities absorbed from sibling engines: `coordinated_scope` (coordinated worker lanes), `delivery_boundary` (one bounded plan-to-PR cycle), `single_owner_persistence` (one owner finishes and verifies), and `durable_checkpoint` (durable goal ledger with checkpoints and a final gate).

## First Steps

- Initialize an English phase checklist through the host's task mechanism or a durable file: bootstrap, each implementation/verification lane, independent review, and evidence/cleanup close. Keep one outcome active and update declarations from observed results.

## Do Not Use When

- Avoid conflicting parallel writers; use single-owner or ordered execution.
- Plan not accepted, lanes unclear or verification missing; use `omh-plan` (`ulw-plan` for a stated risk) unless a delivery cycle was asked for or it is one concrete change with its own acceptance criteria and verification command.
- The user expects Hermes to secretly execute coding lanes instead of preparing explicit selected-runtime handoffs.
- For a decision spike, use `omh-decision-prototype`.
- [capability:coordinated_scope] The lanes are exploratory research or QA coordination without an accepted implementation plan; frame them with the `coordinated_scope` capability before parallel delivery.
- [capability:single_owner_persistence] The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; use one direct owner instead of opening parallel delivery lanes, a finish-until-done loop, or a goal ledger.
- [capability:delivery_boundary] The user wants an open-ended feedback loop or long-horizon campaign; use `ulw-loop` instead.
- [capability:single_owner_persistence] Progress must survive sessions as a ledger with multiple checkpoints and a final gate; use the `durable_checkpoint` capability.
- [capability:durable_checkpoint] One concrete, already-scoped task only needs one owner to finish and verify; use the `single_owner_persistence` capability.
- [capability:durable_checkpoint] The next work must be discovered or reframed repeatedly through research and feedback cycles; use `ulw-loop`.
- [capability:durable_checkpoint] Acceptance criteria, current checkpoint, and final gate expectations are too vague to make a goal inspectable.

## Examples

Good example:

- Prompt: $ultrawork split the accepted docs refresh, CLI output polish, and test updates into parallel implementation lanes.
- Expected behavior: Create disjoint lane prompts with acceptance criteria, verification commands, and review evidence requirements.
- Why: The work can be split cleanly and benefits from parallel execution discipline.

Bad example:

- Prompt: $ultrawork refactor the central router in five agents at once.
- Expected behavior: Keep one owner or re-plan boundaries before parallelization.
- Why: Shared core logic makes parallel edits likely to conflict or hide regressions.

## Completion Checklist

- The phase checklist was declared before engine work started and every outcome reached a terminal state; a run that declared none, or that left outcomes pending, is not complete.
- Every concurrently runnable lane is disjoint by write scope, invariant, or responsibility, and every ordered unit carries an explicit acyclic dependency edge, before parallel handoffs are prepared.
- Each lane has acceptance criteria, verification command, worker protocol expectation, and review owner.
- Every lane's owner and routing were named before dispatch, never inferred from inheritance; a lane dispatched on inherited routing is unrouted.
- Builder, verifier, reviewer, documentation, and PR lanes have explicit host task owners and observed evidence.
- Worker ACK, dispatch, result, review, CI, and merge evidence are observed or explicitly missing.
- Integration verification ran after lane results before the final status claims completion.
- Changed behavior was exercised through the real user surface after diagnostics and relevant tests passed, and every spawned QA resource has a cleanup receipt.
- The closing brief includes observed host accounting or an explicit run-summary not_available statement, never estimated usage.
- [capability:coordinated_scope] The integrated status names which coordination lanes are observed, blocked, or still prepared_not_observed.
- [capability:coordinated_scope] Coordination teardown is explicit: released lanes are named and closed instead of lingering as implicit owners.
- [capability:durable_checkpoint] The goal_status_card/v1 or goal_continuation/v1 names the next action and the final status says complete, blocked, or continue with the exact remaining checkpoint.
- [capability:durable_checkpoint] All explicitly linked coding milestones have matching observed runtime evidence or stay prepared_not_observed and named as gaps without closing the goal.
- [capability:durable_checkpoint] Long-running or background executor milestones report observed handles, current state, changed-file summaries, missing checks, and prepared-vs-observed boundaries while work is running.
- [capability:durable_checkpoint] Branch, PR, CI, review, and merge claims are verified against local HEAD, remote branch SHA, PR head SHA, and merge commit before saying a fix landed.

## When to Use

Use when an accepted implementation plan can be split into independent, reviewable work lanes.

    Strong routing signals: `ultrawork`, `$ultrawork`, `ulw`, `$ulw`, `parallel work`, `parallel implementation`, `parallel then integrate`, `high throughput`, `coding team`, `coordinated workers`, `finish until done`, `persistent execution`, `implement`, `one-cycle delivery`, `single-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`, `plan implement review docs pr`, `prepare a pr`, `make a pr`, `open a pr`, `pr-ready`, `red green refactor`, `red-green refactor`, `red-green`, `failing test first`, `並列で実装`, `並列実装`, `並行して実装`, `コーディングチームで`, `并行实现`, `并行开发`, `并行推进`, `编码团队`, `implementasi paralel`

Required inputs:

- accepted plan, or one concrete change's acceptance criteria and verification command
- work units with read/write scopes
- dependency edges or shared invariants
- verification commands

Artifact expectations:

- prepared coding delegation record per implementation lane when wrappers can record them
- [capability:single_owner_persistence] goal-execution run record with checkpoint or final evidence when available
