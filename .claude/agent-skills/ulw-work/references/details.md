## Catalog Metadata

Category: `execution`
Phase: `parallel-delivery`
Quality tier: `handoff-gated`
Reasoning demand: `heavy`

Quality bar:

- Do not start this engine as an automatic continuation of another skill's output: an accepted plan, a clarified brief, or a routing recommendation is planning evidence, not permission. Unless the user explicitly invoked this engine themselves, restate in one line what will start (engine, scope, selected executor) and wait for the user's explicit go-ahead first.
- Resolve the dependency_topology decision before any dispatch: work coupled by a shared invariant or inseparable edit boundary collapses to one owner; separable but ordered units get explicit acyclic dependency edges; independent units form the dependency-ready parallel frontier; no unit dispatches without scope, acceptance criteria, a verification command, and an owner route - load `references/dependency-topology.md` for the full discipline.
- When adapting an existing capability, read `../omh-verification-gate/references/adaptation-quality.md` before accepting a plan, dispatching work, or claiming completion; carry its criteria and comparisons into tasks and evidence.
- Attach acceptance criteria, verification commands, and review expectations to each lane.
- Keep dispatch, execution, review, CI, and merge status evidence separate.
- After final brief composition and before unattended coding handoff, explicitly run `omh handoff-risk-scan --brief-file <final-brief> --repo <workspace> --strict --json`. Route high_risk (exit 1) to existing confirmation or `omh-security-safety-review`; scan_error (exit 2) requires repaired input and a new scan. Clear never grants permission or bypasses metadata preflight, approval, or host policy.
- Write every lane or node prompt standalone with TASK, DELIVERABLE, SCOPE, VERIFY, and STOP WHEN in that order, exact paths and binary pass/fail observables, and one role per node; a dependency edge orders execution only and never substitutes upstream output.
- End every code-changing run with a verification fan-in that depends on all producer lanes, runs the repository's real test/build command, and reports captured binary pass/fail output; downstream consumers re-check upstream claims before trusting them.
- For each behavioral increment follow PIN -> RED -> GREEN -> SURFACE -> CLEAN: pin behavior a refactor could hide, capture the intended failing proof before implementation, make the smallest change, exercise the real user surface, and tear down every QA resource with a cleanup receipt; tests alone never prove completion.
- Keep one inspectable, append-only evidence ledger for the run using the available goal/runtime records: record the tier decision, dependency topology, todo transitions, command outputs, real-surface artifacts, and cleanup receipts when each occurs.
- For tests-first work, capture the new test's failing nonzero output before implementation and its passing zero output plus the full suite before done; never edit, delete, skip, or weaken a test to make it pass.
- [capability:coordinated_scope] Keep the current host as coordinator and narrator; delegate through the host's own subagent/task mechanism with explicit ownership, or run lanes sequentially when unavailable.
- [capability:delivery_boundary] Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.
- [capability:delivery_boundary] Start a delivery cycle with codebase/source research and a ralplan-style decision record before implementation handoff.
- [capability:delivery_boundary] Run `omh-code-review` as a gate after implementation evidence exists; review preparation alone is not review evidence.
- [capability:delivery_boundary] End a delivery cycle with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.
- [capability:delivery_boundary] Use the host's own subagent/task mechanism with explicit owner, acceptance criteria, verification commands, and a resumable ledger for durable checkpoints. Never imply hidden execution.
- When the user explicitly selects an external coding owner, use the host's authorized task mechanism, verify its actual capabilities, and capture its session/task handle. Missing delegation means sequential work or a named blocker, never fabricated dispatch.
- Name each lane owner and its actual host capabilities before dispatch; do not infer model or tool routing from inheritance.
- Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism. Ladder and terminal states: shared rail.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval; persistence never broadens the authorized scope. A refused escalation gets a safer alternative inside the boundary, or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences for a simple change. Lead with the result and validation; omit abandoned approaches unless they explain a tradeoff, and internal bookkeeping. Disclose requested-but-not-done work and material prepared/unmerged work; omit unrelated non-action footers. Required accounting stays outside this scaling. Order: result -> relevant evidence/limits -> observed accounting (when required) -> specific question (if useful). For a real unresolved user decision or a useful briefing discussion, offer one specific, content-linked question. Completed work needs no question; discussion grants no authority. Never estimate usage.
- Close with observed host accounting when available, or explicitly report run-summary not_available, before any specific next-action question. Never estimate token counts, elapsed time, or models used.
- [capability:single_owner_persistence] Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
- [capability:single_owner_persistence] For single-owner coding edits, prepare and track the selected runtime path instead of implying unobserved work happened or hiding execution inside chat narration.
- [capability:single_owner_persistence] Report single-owner completion only from observed execution and verification evidence, with remaining risks named.
- [capability:durable_checkpoint] Keep goal state durable, inspectable, and separate from chat narration in the metadata-only .omh/goals goal_ledger/v1.
- [capability:durable_checkpoint] Create a code-changing goal with `omh goal create --obligation slop-cleanup`; it completes only after a checkpoint cites one completed `omh-ai-slop-cleaner` run for it, recorded and cited with the commands that skill closes on (`--cleanup-outcome passed|skipped|reverted` and an outputs or verification summary the integrity check accepts; placeholders are refused). Without the flag the goal is not gated.
- [capability:durable_checkpoint] Checkpoint every success, blocker, and final quality gate with fresh evidence.
- [capability:durable_checkpoint] Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.
- [capability:durable_checkpoint] Name the one element gating goal progress from the linked loop's loop_constraint_assessment/v1 before checkpointing the next step; load `ulw-loop/references/goal-constraint-discipline.md` for the method.

Required inputs:

- accepted plan, or one concrete change's acceptance criteria and verification command
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
- [capability:delivery_boundary] Do not continue into a repeated feedback loop; recommend `ulw-loop` when the user wants ongoing cycles.
- [capability:delivery_boundary] Do not skip planning when the delivery request is broad, risky, or user-visible; a ralplan-style or reviewed plan names acceptance criteria, risks, and verification commands.
- [capability:delivery_boundary] Run docs sync only when behavior, setup, commands, examples, or public claims changed.
- [capability:delivery_boundary] Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.
