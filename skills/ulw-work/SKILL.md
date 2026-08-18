---
name: ulw-work
description: [omh] Ultrawork - split an accepted plan into disjoint parallel lanes with per-lane acceptance criteria, verification commands, and owners; prevents two lanes editing the same file. Aliases: ulw. Use when the user says: ultrawork, parallel work, parallel implementation, high throughput, coding team, coordinated workers, finish until done, persistent execution.
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

`ultrawork` exists to split an accepted implementation plan into independent lanes without letting parallelism blur ownership, verification, worker protocol, worktree isolation, or observed runtime evidence. It also carries four named internal capabilities absorbed from sibling engines: `coordinated_scope` (coordinated worker lanes), `delivery_boundary` (one bounded plan-to-PR cycle), `single_owner_persistence` (one owner finishes and verifies), and `durable_checkpoint` (durable goal ledger with checkpoints and a final gate).

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

- All work lanes are disjoint by file, invariant, or responsibility before preparing parallel handoffs.
- Each lane has acceptance criteria, verification command, worker protocol expectation, and review owner.
- When Hermes owns the coding path, use `hermes_coding_harness/v1` to separate builder, verifier, reviewer, docs, and PR lanes.
- Worker ACK, dispatch, result, review, CI, and merge evidence are observed or explicitly missing.
- Integration verification ran after lane results before the final status claims completion.
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
- [capability:coordinated_scope] If a coordinated worker has no ACK or result, mark that lane not_observed or blocked rather than infer progress.
- [capability:durable_checkpoint] If the goal ledger is stale or missing, inspect .omh/goals and ask which checkpoint to resume before continuing.
- [capability:durable_checkpoint] If a blocker checkpoint exists, keep the goal open and record the blocker plus the smallest unblock action.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `ultrawork`, `+6 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when an accepted implementation plan can be split into independent, reviewable work lanes.

    Strong routing signals: `ultrawork`, `$ultrawork`, `ulw`, `$ulw`, `parallel work`, `parallel implementation`, `high throughput`, `coding team`, `coordinated workers`, `finish until done`, `persistent execution`, `implement`, `one-cycle delivery`, `single-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`, `plan implement review docs pr`, `prepare a pr`, `make a pr`, `open a pr`, `pr-ready`

## Catalog Metadata

Category: `execution`
Phase: `parallel-delivery`
Hermes role: `handoff-guide`
Quality tier: `handoff-gated`
Reasoning demand: `heavy`

Quality bar:

- Do not start this engine as an automatic continuation of another skill's output: an accepted plan, a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user explicitly invoked this engine themselves, restate in one line what will start (engine, scope, selected executor) and wait for the user's explicit go-ahead first.
- Require disjoint lane ownership before preparing multiple coding runtime handoffs.
- Attach acceptance criteria, verification commands, and review expectations to each lane.
- Keep dispatch, execution, review, CI, and merge status evidence separate.
- [capability:coordinated_scope] Keep Hermes as coordinator and status narrator for lane framing and status while coding lanes become runtime handoffs with explicit ownership.
- [capability:delivery_boundary] Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.
- [capability:delivery_boundary] Start a delivery cycle with codebase/source research and a ralplan-style decision record before implementation handoff.
- [capability:delivery_boundary] Run code-review as a gate after implementation evidence exists; review preparation alone is not review evidence.
- [capability:delivery_boundary] End a delivery cycle with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.
- [capability:delivery_boundary] For implementation, default to Hermes-native delegation with a per-lane `omh_delegate_route` mixture route and acceptance criteria and verification commands attached; hand off to the `durable_checkpoint` capability for work that must survive sessions, and prepare a selected external executor/runtime path only on the user's explicit owner acceptance.
- Route each Hermes-native lane before dispatch: an inherit-labeled delegation wave is an unrouted wave, not mixture routing — re-route it or state why parent inheritance is intended.
- [capability:single_owner_persistence] Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
- [capability:single_owner_persistence] For single-owner coding edits, prepare and track the selected runtime path instead of implying unobserved work happened or hiding execution inside chat narration.
- [capability:single_owner_persistence] Report single-owner completion only from observed execution and verification evidence, with remaining risks named.
- [capability:durable_checkpoint] Keep goal state durable, inspectable, and separate from chat narration in the metadata-only .omh/goals goal_ledger/v1.
- [capability:durable_checkpoint] Checkpoint every success, blocker, and final quality gate with fresh evidence.
- [capability:durable_checkpoint] Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.

Handoff policy:

Keep the workflow name for compatibility. The default implementation owner is the Hermes coding harness itself: run coding lanes as Hermes-native delegate_task subagents with OMH skills loaded, each lane given disjoint scope, verification, and review expectations, and each lane routed through the mixture categories — set the route with the `omh_delegate_route` tool before dispatch (research/scan lanes quick or unspecified-low; ideation, architecture, and hard debugging ultrabrain or deep; visual work visual-engineering or artistry; docs writing) and name the routed category and reasoning effort in the lane's status. [capability:delivery_boundary] Convert implementation into an external executor/runtime handoff such as Codex, Claude Code, OMX/OMO/OMC, or another coding agent only when the user accepts that owner; no external CLI is the default owner, and external handoff is a separate opt-in path, never the default recommendation.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Delegation transparency:

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]` — the user must see WHAT was asked, not just that something was.
- Name every delegated or parallel lane's model and reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; write the literal `unknown` when the host does not expose a value, never empty parentheses, and carry token and elapsed figures the same way.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it — a plain-text one-shot that hides its session id strands the work when the run stalls or times out.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is `~/.claude/settings.json` and project scope is `<dispatch cwd>/.claude/settings.local.json` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

Required inputs:

- accepted plan
- lane list
- disjoint file or responsibility scopes
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

- Do not start parallel coding without disjoint ownership boundaries.
- Keep Hermes responsible for orchestration/status; when Hermes itself is selected for coding, still preserve runtime evidence boundaries.
- Record unobserved executor work as prepared_not_observed or not_observed.
- [capability:coordinated_scope] Use coordination lanes only when work is independent; if two lanes are not independent, collapse them under one owner or re-plan before dispatch.
- [capability:coordinated_scope] Keep shared-file edits under one owner; if integration reveals a shared-file conflict, stop lane fan-out and reassign ownership before continuing.
- [capability:coordinated_scope] Record unobserved delegation as not_observed; a delegation record exists only when separate participants are observed.
- [capability:delivery_boundary] Do not continue into a repeated feedback loop; recommend `loop` when the user wants ongoing cycles.
- [capability:delivery_boundary] Do not skip planning when the delivery request is broad, risky, or user-visible; a ralplan-style or reviewed plan names acceptance criteria, risks, and verification commands.
- [capability:delivery_boundary] Run docs sync only when behavior, setup, commands, examples, or public claims changed.
- [capability:delivery_boundary] Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.

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
