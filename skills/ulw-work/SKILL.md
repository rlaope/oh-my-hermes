---
name: "ulw-work"
description: "[omh] Ultrawork - split an accepted plan into disjoint parallel lanes with per-lane acceptance criteria, verification commands, and owners; prevents two lanes editing the same file. Aliases: ulw. Use when the user says: ultrawork, parallel work, parallel implementation, parallel then integrate, high throughput, coding team, coordinated workers, finish until done."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: parallel-delivery
    role: handoff-guide
    quality_tier: handoff-gated
---

# Ultrawork

This is a Hermes-native `ultrawork` workflow skill.

## Why This Exists

`ultrawork` exists to choose one-owner, ordered-dependency, or independent-frontier execution for an accepted implementation plan without letting concurrency blur ownership, verification, worker protocol, worktree isolation, or observed runtime evidence. It also carries four named internal capabilities absorbed from sibling engines: `coordinated_scope` (coordinated worker lanes), `delivery_boundary` (one bounded plan-to-PR cycle), `single_owner_persistence` (one owner finishes and verifies), and `durable_checkpoint` (durable goal ledger with checkpoints and a final gate).

## Do Not Use When

- The work touches the same files or invariants in ways that need one owner.
- The plan is not accepted, lane boundaries are unclear, or verification commands are missing.
- The user expects Hermes to secretly execute coding lanes instead of preparing explicit selected-runtime handoffs.
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

- Every concurrently runnable lane is disjoint by write scope, invariant, or responsibility, and every ordered unit carries an explicit acyclic dependency edge, before parallel handoffs are prepared.
- Each lane has acceptance criteria, verification command, worker protocol expectation, and review owner.
- When Hermes owns the coding path, use `hermes_coding_harness/v1` to separate builder, verifier, reviewer, docs, and PR lanes.
- Worker ACK, dispatch, result, review, CI, and merge evidence are observed or explicitly missing.
- Integration verification ran after lane results before the final status claims completion.
- Changed behavior was exercised through the real user surface after diagnostics and relevant tests passed, and every spawned QA resource has a cleanup receipt.
- The closing brief ends with the observed `omh_run_summary` line (elapsed seconds and token usage) or an explicit run-summary not_available statement — never a model-estimated number.
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

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+13 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when an accepted implementation plan can be split into independent, reviewable work lanes.

    Strong routing signals: `ultrawork`, `$ultrawork`, `ulw`, `$ulw`, `parallel work`, `parallel implementation`, `parallel then integrate`, `high throughput`, `coding team`, `coordinated workers`, `finish until done`, `persistent execution`, `implement`, `one-cycle delivery`, `single-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`, `plan implement review docs pr`, `prepare a pr`, `make a pr`, `open a pr`, `pr-ready`, `red green refactor`, `red-green refactor`, `red-green`, `failing test first`, `並列で実装`, `並列実装`, `並行して実装`, `コーディングチームで`, `并行实现`, `并行开发`, `并行推进`, `编码团队`

## Catalog Metadata

Category: `execution`
Phase: `parallel-delivery`
Hermes role: `handoff-guide`
Quality tier: `handoff-gated`
Reasoning demand: `heavy`

Quality bar:

- Do not start this engine as an automatic continuation of another skill's output: an accepted plan, a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user explicitly invoked this engine themselves, restate in one line what will start (engine, scope, selected executor) and wait for the user's explicit go-ahead first.
- Resolve the dependency_topology decision before any dispatch: work coupled by a shared invariant or inseparable edit boundary collapses to one owner; separable but ordered units get explicit acyclic dependency edges; independent units form the dependency-ready parallel frontier; no unit dispatches without scope, acceptance criteria, a verification command, and an owner route - load `references/dependency-topology.md` for the full discipline.
- Attach acceptance criteria, verification commands, and review expectations to each lane.
- Keep dispatch, execution, review, CI, and merge status evidence separate.
- Write every lane or node prompt standalone with TASK, DELIVERABLE, SCOPE, VERIFY, and STOP WHEN in that order, exact paths and binary pass/fail observables, and one role per node; a dependency edge orders execution only and never substitutes upstream output.
- End every code-changing run with a verification fan-in that depends on all producer lanes, runs the repository's real test/build command, and reports captured binary pass/fail output; downstream consumers re-check upstream claims before trusting them.
- For each behavioral increment follow PIN -> RED -> GREEN -> SURFACE -> CLEAN: pin behavior a refactor could hide, capture the intended failing proof before implementation, make the smallest change, exercise the real user surface, and tear down every QA resource with a cleanup receipt; tests alone never prove completion.
- Keep one inspectable, append-only evidence ledger for the run using the available goal/runtime records: record the tier decision, dependency topology, todo transitions, command outputs, real-surface artifacts, and cleanup receipts when each occurs.
- For a tests-first (TDD or red-green) run, hold every implementation lane to the observed red/green contract: the new test's failing (non-zero) output is pasted before any implementation edit, the passing (zero) output plus full-suite result before any done claim, and a test is never edited, deleted, skipped, xfail-marked, or weakened to make it pass - load `references/tdd-red-green.md` for the full discipline.
- [capability:coordinated_scope] Keep Hermes as coordinator and status narrator for lane framing and status while coding lanes become runtime handoffs with explicit ownership.
- [capability:delivery_boundary] Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.
- [capability:delivery_boundary] Start a delivery cycle with codebase/source research and a ralplan-style decision record before implementation handoff.
- [capability:delivery_boundary] Run code-review as a gate after implementation evidence exists; review preparation alone is not review evidence.
- [capability:delivery_boundary] End a delivery cycle with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.
- [capability:delivery_boundary] For implementation, default to Hermes-native delegation with a per-lane `omh_delegate_route` mixture route and acceptance criteria and verification commands attached; hand off to the `durable_checkpoint` capability for work that must survive sessions, and prepare a selected external executor/runtime path only on the user's explicit owner acceptance.
- When a lane's coding owner is an external CLI rather than the Hermes harness, that lane's handoff runs under `ulw-maestro`'s contract — load it and follow its explicit-owner precondition, skill-set-informed prompt composition, readiness and permission probes, and session-id capture; a lane with an external owner is never a Hermes-native `delegate_task` lane. Lane framing, disjointness, integration verification, and the closing brief stay here.
- Route each Hermes-native lane before dispatch: an inherit-labeled delegation wave is an unrouted wave, not mixture routing — re-route it or state why parent inheritance is intended.
- Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism. Ladder and terminal states: shared rail.
- Initialize the phase todo before engine work: declare numbered phases in delivery order with `omh_todo` (todo init) — bootstrap, one implement/verify/deliver task per lane or work unit, independent review lanes, and an evidence-and-cleanup close, with one task per observable outcome — keep exactly one item active while working, and update states as lanes complete; the run walks a bounded, HUD-visible checklist instead of an open-ended reasoning loop. Phase names and task titles are written in English — short, operator-legible labels — even when the conversation runs in another language, since the HUD todo checklist is an operator surface under the repo's English-by-default output contract.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it.
- Close a completed run with the localized run summary: call `omh_run_summary` with the conversation's language and print its summary_text verbatim as the final lines (elapsed seconds, token usage, and models used from observed host accounting — never numbers the model estimated); when the tool reports a non-observed status (no session id, no accounting row), print an explicit run-summary not_available line instead of omitting it or estimating the numbers.
- [capability:single_owner_persistence] Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
- [capability:single_owner_persistence] For single-owner coding edits, prepare and track the selected runtime path instead of implying unobserved work happened or hiding execution inside chat narration.
- [capability:single_owner_persistence] Report single-owner completion only from observed execution and verification evidence, with remaining risks named.
- [capability:durable_checkpoint] Keep goal state durable, inspectable, and separate from chat narration in the metadata-only .omh/goals goal_ledger/v1.
- [capability:durable_checkpoint] Checkpoint every success, blocker, and final quality gate with fresh evidence.
- [capability:durable_checkpoint] Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.
- [capability:durable_checkpoint] Name the one element gating goal progress from the linked loop's loop_constraint_assessment/v1 before checkpointing the next step; load `ulw-loop/references/goal-constraint-discipline.md` for the method.

Handoff policy:

Keep the workflow name for compatibility. The default implementation owner is the Hermes coding harness itself: run coding lanes as Hermes-native delegate_task subagents with OMH skills loaded, each lane given disjoint scope, verification, and review expectations, and each lane routed through the mixture categories — set the route with the `omh_delegate_route` tool before dispatch (research/scan lanes quick or unspecified-low; ideation and hard debugging ultrabrain or deep; architecture and system-design lanes architect; visual work visual-engineering or artistry; docs writing) and name the routed category and reasoning effort in the lane's status. When the user names a model for the run (for example 'use fable' or 'fable로 해줘'), pin it: keep the fitting category for each lane's label but pass the user's model and reasoning effort as explicit overrides in `omh_delegate_route` on every lane, so each dispatch runs the named model and the lane status shows it. [capability:delivery_boundary] Convert implementation into an external executor/runtime handoff such as Codex, Claude Code, OMX/OMO/OMC, or another coding agent only when the user accepts that owner; no external CLI is the default owner, and external handoff is a separate opt-in path, never the default recommendation.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Delegation transparency:

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]` — the user must see WHAT was asked, not just that something was.
- Name every delegated or parallel lane's model and, when the host exposes it, its reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; when no effort is exposed, show the model alone as `(model)` rather than writing a placeholder like `unknown` beside a known model, and never emit empty parentheses. Carry token and elapsed figures the same way in these narration lines: report observed figures and omit unobserved ones — when the user asks for a figure directly, say it was not observed instead of omitting it; a rendered status-board column keeps its own `unknown` cell.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it — a plain-text one-shot that hides its session id strands the work when the run stalls or times out.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is `~/.claude/settings.json` and project scope is `<dispatch cwd>/.claude/settings.local.json` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

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
- Keep Hermes responsible for orchestration/status; when Hermes itself is selected for coding, still preserve runtime evidence boundaries.
- Record unobserved executor work as prepared_not_observed or not_observed.
- [capability:coordinated_scope] Use coordination lanes only when work is independent; if two lanes are not independent, collapse them under one owner or re-plan before dispatch.
- [capability:coordinated_scope] Keep shared-file edits under one owner; if integration reveals a shared-file conflict, stop lane fan-out and reassign ownership before continuing.
- [capability:coordinated_scope] Record unobserved delegation as not_observed; a delegation record exists only when separate participants are observed.
- [capability:delivery_boundary] Do not continue into a repeated feedback loop; recommend `loop` when the user wants ongoing cycles.
- [capability:delivery_boundary] Do not skip planning when the delivery request is broad, risky, or user-visible; a ralplan-style or reviewed plan names acceptance criteria, risks, and verification commands.
- [capability:delivery_boundary] Run docs sync only when behavior, setup, commands, examples, or public claims changed.
- [capability:delivery_boundary] Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.

## Tests-First Delivery

When the user asks for TDD, tests first, or red-green delivery, every implementation lane runs under the red/green contract. The iron law: no implementation line before a failing test - write the test that describes the missing behavior, run it, and watch it fail for the right reason before any implementation edit. A cycle is observed only when a failing (non-zero) run of the lane's test command precedes a passing (zero) run, both with pasted output; a lane that shows only green is `prepared_not_observed` on its red phase and does not count as tests-first delivery. Never edit, delete, skip, xfail, or weaken a test to make it pass - a failing test means fix the code - and a test that passes on its first run proves nothing: make it fail first. Commit the failing test as a checkpoint before implementing, so any later test edit is diff-visible.

Hermes bundles the superpowers `test-driven-development` skill; when it is loaded, follow its cycle - this contract reinforces it with OMH's evidence vocabulary and never overrides it. Load `references/tdd-red-green.md` for the full discipline: the evidence ledger, forbidden moves, the rationalization table, and the observed red-before-green rule.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

```sh
omh runtime record --skill ultrawork --harness goal-execution --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
