---
name: "ulw-work"
description: "[omh] Ultrawork - split an accepted plan into disjoint parallel lanes with per-lane acceptance criteria, verification commands, and owners; prevents two lanes editing the same file. Aliases: ulw. Use when the user says: ultrawork, parallel work, parallel implementation, parallel then integrate, high throughput, coding team, coordinated workers, finish until done."
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: parallel-delivery
    role: handoff-guide
    quality_tier: handoff-gated
---

# Ultrawork

This is an OMH `ultrawork` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ultrawork` exists to choose one-owner, ordered-dependency, or independent-frontier execution for an accepted implementation plan without letting concurrency blur ownership, verification, worker protocol, worktree isolation, or observed runtime evidence. It also carries four named internal capabilities absorbed from sibling engines: `coordinated_scope` (coordinated worker lanes), `delivery_boundary` (one bounded plan-to-PR cycle), `single_owner_persistence` (one owner finishes and verifies), and `durable_checkpoint` (durable goal ledger with checkpoints and a final gate).

## First Steps

- Initialize an English phase checklist through the host's task mechanism or a durable file: bootstrap, each implementation/verification lane, independent review, and evidence/cleanup close. Keep one outcome active and update declarations from observed results.

## Do Not Use When

- The work touches the same files or invariants in ways that need one owner.
- The plan is not accepted, lane boundaries are unclear, or verification commands are missing.
- The user expects Hermes to secretly execute coding lanes instead of preparing explicit selected-runtime handoffs.
- For a decision spike, use `decision-prototype`.
- [capability:coordinated_scope] The lanes are exploratory research or QA coordination without an accepted implementation plan; frame them with the `coordinated_scope` capability before parallel delivery.
- [capability:single_owner_persistence] The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; use one direct owner instead of opening parallel delivery lanes, a finish-until-done loop, or a goal ledger.
- [capability:delivery_boundary] The user wants an open-ended feedback loop or long-horizon campaign; use `loop` instead.
- [capability:single_owner_persistence] Progress must survive sessions as a ledger with multiple checkpoints and a final gate; use the `durable_checkpoint` capability.
- [capability:durable_checkpoint] One concrete, already-scoped task only needs one owner to finish and verify; use the `single_owner_persistence` capability.
- [capability:durable_checkpoint] The next work must be discovered or reframed repeatedly through research and feedback cycles; use `loop`.
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

## Recovery Notes

- If lanes are non-disjoint, collapse to one owner or route back to the durable-checkpoint goal ledger before coding starts.
- If a worker does not ACK or return a result, keep that lane blocked/not_observed and expose the retry or reassignment action.
- If a worktree or shared-file conflict appears, pause parallel delivery and re-plan ownership before more edits.
- If a node fails, recover node-locally: the failure blocks only its dependents; read its error and retry first, amend the node definition when its prompt or contract is wrong, and steer a live lane instead of duplicating its owner - never rebuild the graph.
- Do not read a quiet or scheduled node as stalled; inspect returned output because a returned blocked response still completes the node and carries the blocker to report.
- [capability:coordinated_scope] If a coordinated worker has no ACK or result, mark that lane not_observed or blocked rather than infer progress.
- [capability:durable_checkpoint] If the goal ledger is stale or missing, inspect .omh/goals and ask which checkpoint to resume before continuing.
- [capability:durable_checkpoint] If a blocker checkpoint exists, keep the goal open and record the blocker plus the smallest unblock action.



## Use When

Use when an accepted implementation plan can be split into independent, reviewable work lanes.

    Strong routing signals: `ultrawork`, `$ultrawork`, `ulw`, `$ulw`, `parallel work`, `parallel implementation`, `parallel then integrate`, `high throughput`, `coding team`, `coordinated workers`, `finish until done`, `persistent execution`, `implement`, `one-cycle delivery`, `single-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`, `plan implement review docs pr`, `prepare a pr`, `make a pr`, `open a pr`, `pr-ready`, `red green refactor`, `red-green refactor`, `red-green`, `failing test first`, `並列で実装`, `並列実装`, `並行して実装`, `コーディングチームで`, `并行实现`, `并行开发`, `并行推进`, `编码团队`

## Catalog Metadata

Category: `execution`
Phase: `parallel-delivery`
Quality tier: `handoff-gated`
Reasoning demand: `heavy`

Quality bar:

- Do not start this engine as an automatic continuation of another skill's output: an accepted plan, a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user explicitly invoked this engine themselves, restate in one line what will start (engine, scope, selected executor) and wait for the user's explicit go-ahead first.
- Resolve the dependency_topology decision before any dispatch: work coupled by a shared invariant or inseparable edit boundary collapses to one owner; separable but ordered units get explicit acyclic dependency edges; independent units form the dependency-ready parallel frontier; no unit dispatches without scope, acceptance criteria, a verification command, and an owner route - load `references/dependency-topology.md` for the full discipline.
- Attach acceptance criteria, verification commands, and review expectations to each lane.
- Keep dispatch, execution, review, CI, and merge status evidence separate.
- After final brief composition and before unattended coding handoff, explicitly run `omh handoff-risk-scan --brief-file <final-brief> --repo <workspace> --strict --json`. Route high_risk (exit 1) to existing confirmation or security-safety-review; scan_error (exit 2) requires repaired input and a new scan. Clear never grants permission or bypasses metadata preflight, approval, or host policy.
- Write every lane or node prompt standalone with TASK, DELIVERABLE, SCOPE, VERIFY, and STOP WHEN in that order, exact paths and binary pass/fail observables, and one role per node; a dependency edge orders execution only and never substitutes upstream output.
- End every code-changing run with a verification fan-in that depends on all producer lanes, runs the repository's real test/build command, and reports captured binary pass/fail output; downstream consumers re-check upstream claims before trusting them.
- For each behavioral increment follow PIN -> RED -> GREEN -> SURFACE -> CLEAN: pin behavior a refactor could hide, capture the intended failing proof before implementation, make the smallest change, exercise the real user surface, and tear down every QA resource with a cleanup receipt; tests alone never prove completion.
- Keep one inspectable, append-only evidence ledger for the run using the available goal/runtime records: record the tier decision, dependency topology, todo transitions, command outputs, real-surface artifacts, and cleanup receipts when each occurs.
- For tests-first work, capture the new test's failing nonzero output before implementation and its passing zero output plus the full suite before done; never edit, delete, skip, or weaken a test to make it pass.
- [capability:coordinated_scope] Keep the current host as coordinator and narrator; delegate through the host's own subagent/task mechanism with explicit ownership, or run lanes sequentially when unavailable.
- [capability:delivery_boundary] Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.
- [capability:delivery_boundary] Start a delivery cycle with codebase/source research and a ralplan-style decision record before implementation handoff.
- [capability:delivery_boundary] Run code-review as a gate after implementation evidence exists; review preparation alone is not review evidence.
- [capability:delivery_boundary] End a delivery cycle with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.
- [capability:delivery_boundary] Use the host's own subagent/task mechanism with explicit owner, acceptance criteria, verification commands, and a resumable ledger for durable checkpoints. Never imply hidden execution.
- When the user explicitly selects an external coding owner, use the host's authorized task mechanism, verify its actual capabilities, and capture its session/task handle. Missing delegation means sequential work or a named blocker, never fabricated dispatch.
- Name each lane owner and its actual host capabilities before dispatch; do not infer model or tool routing from inheritance.
- Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism. Ladder and terminal states: shared rail.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval; persistence never broadens the authorized scope. A refused escalation gets a safer alternative inside the boundary, or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences plus the observed validation for a simple change, more only when the complexity earns it. Lead with the result or decision; omit abandoned approaches unless they explain a tradeoff the reader needs; narrate no internal bookkeeping (todo transitions, follow-up declarations, waits). Required closing lines stay outside this scaling: the observed run summary, and any prepared-not-observed or unmerged work, are stated whatever the brief's length.
- Close with observed host accounting when available, or explicitly report run-summary not_available. Never estimate token counts, elapsed time, or models used.
- [capability:single_owner_persistence] Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
- [capability:single_owner_persistence] For single-owner coding edits, prepare and track the selected runtime path instead of implying unobserved work happened or hiding execution inside chat narration.
- [capability:single_owner_persistence] Report single-owner completion only from observed execution and verification evidence, with remaining risks named.
- [capability:durable_checkpoint] Keep goal state durable, inspectable, and separate from chat narration in the metadata-only .omh/goals goal_ledger/v1.
- [capability:durable_checkpoint] Checkpoint every success, blocker, and final quality gate with fresh evidence.
- [capability:durable_checkpoint] Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.
- [capability:durable_checkpoint] Name the one element gating goal progress from the linked loop's loop_constraint_assessment/v1 before checkpointing the next step; load `ulw-loop/references/goal-constraint-discipline.md` for the method.

Required inputs:

- accepted plan
- work units with read/write scopes
- dependency edges or shared invariants
- verification commands

Expected outputs:

- runtime handoff prompts or lane instructions
- status summary
- review/CI evidence requirements
- [capability:delivery_boundary] `durable_checkpoint` or selected executor/runtime handoff

Artifact expectations:

- prepared coding delegation record per implementation lane when wrappers can record them
- [capability:single_owner_persistence] goal-execution run record with checkpoint or final evidence when available

Safety rules:

- Do not run two concurrently runnable lanes with overlapping write scopes; a shared file requires an ordering edge or one owner.
- Keep orchestration/status and implementation ownership explicit in the current host; preserve prepared versus observed evidence boundaries.
- Record unobserved executor work as prepared_not_observed or not_observed.
- [capability:coordinated_scope] Use coordination lanes only when work is independent; if two lanes are not independent, collapse them under one owner or re-plan before dispatch.
- [capability:coordinated_scope] Keep shared-file edits under one owner; if integration reveals a shared-file conflict, stop lane fan-out and reassign ownership before continuing.
- [capability:coordinated_scope] Record unobserved delegation as not_observed; a delegation record exists only when separate participants are observed.
- [capability:delivery_boundary] Do not continue into a repeated feedback loop; recommend `loop` when the user wants ongoing cycles.
- [capability:delivery_boundary] Do not skip planning when the delivery request is broad, risky, or user-visible; a ralplan-style or reviewed plan names acceptance criteria, risks, and verification commands.
- [capability:delivery_boundary] Run docs sync only when behavior, setup, commands, examples, or public claims changed.
- [capability:delivery_boundary] Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Report actual tool results or
`not_observed` / `not_available`; never invent dispatch or host accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
