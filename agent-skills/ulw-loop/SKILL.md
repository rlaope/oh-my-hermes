---
name: "ulw-loop"
description: "[omh] Ambitious project goal needing many build cycles: agentic interviewer -> planner -> researcher -> builder -> reviewer cycles until a real gate. Use when the user says: loop, goal loop, long horizon goal, never stop, research plan goal feedback, token exhaustion resume, permission profile, star 10k."
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, goal-loop]
    category: goal-loop
    phase: continuous-goal-loop
    role: planner
    quality_tier: loop-gated
---

# Loop

This is an OMH `loop` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`loop` exists for goals whose correct implementation cannot be known upfront but can be discovered through bounded cycles of definition, action, verification, and revision without confusing planned cycles with observed progress.

## Do Not Use When

- The user asks for one bounded delivery cycle; use `ultrawork`'s delivery-boundary capability instead.
- Scope and milestones are already known and only durable checkpoint/resume tracking is needed; use `ultrawork`'s durable-checkpoint capability.
- The user gives only a north-star outcome such as revenue, stars, or adoption and has not accepted a bounded first loop goal.
- The goal is too vague to name an observable problem, next artifact, verification signal, or stop condition.
- The goal depends mainly on external waiting, adoption, revenue, or community response without observable local next actions.
- The permission profile does not allow repeated research, handoff, queue, or feedback cycles.

## Examples

Good example:

- Prompt: ./loop make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles.
- Expected behavior: Start a permission-scoped loop, maintain loop_cycle/v2 selected-driver state, choose the next concrete task, and keep external outcomes as waiting states.
- Why: The request is long-horizon and needs repeated discovery, verification, feedback, and resume decisions.

Bad example:

- Prompt: ./loop merge this already reviewed one-line README fix.
- Expected behavior: Use a direct delivery or PR workflow instead of starting a persistent loop.
- Why: The task is bounded and should stop after merge evidence rather than create ongoing cycles.

## Completion Checklist

- The request is classified as task, project, north-star ambition, external-wait, or unclear before a loop starts.
- The current loop_status_card/v1 names the queue item, tick status, verification_plan, and next action.
- failure_mode_summary checks verification_gap, comprehension_debt, and cognitive_surrender before progress advances.
- Completion is backed by linked goal/runtime evidence; queued loop ticks alone are not observed work.
- Native goal activation remains unavailable unless independently observed in its owning runtime; host results never substitute for native activation or contiguous-turn evidence.

## Recovery Notes

- Drive the loop lifecycle through a native loop tool when this host offers one, submitting the revision the last read reported; the OMH native loop tool is unavailable in this projection, so keep the durable ledger with the host commands instead.
- If a queued tick is pending, show it as prepared queue state and use loop status/run-once before claiming progress.
- If feedback is unclear, ask one gate question or route back to research/plan rather than advancing the loop.
- If the goal turns into external waiting, record the waiting state and next observable signal instead of continuing locally.
- Checkpoint on context/budget exhaustion. Migrate loop_cycle/v1 with migrate-driver --apply before external binding.
- Resume the current host's durable checklist from observed evidence. If native goal control is requested on an unsupported host, report unavailable instead of inventing activation.
- If the loop runs out of next actions, re-read the scoped files, recombine the near-miss attempts, then escalate to a more radical change before declaring the loop blocked.



## Use When

Use when the user starts a high-level goal or invokes loop. Direct loop invocation means start/continue through interviewer, planner, researcher, builder, reviewer, and loop-controller lanes until a real gate stops it.

    Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan goal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `keep running until done`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`, `끝날 때까지 계속`, `계속 돌려줘`

## Catalog Metadata

Category: `goal-loop`
Phase: `continuous-goal-loop`
Quality tier: `loop-gated`
Reasoning demand: `heavy`

Quality bar:

- Treat direct `loop`, `./loop`, `$loop`, and OMH loop invocations as a start/continue signal rather than a picker or passive clarification path.
- Classify the goal as task, project, ambition, external-wait, or unclear inside the loop, then keep progressing until a real permission, evidence, verification, context, budget, or external-wait gate appears.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval; persistence never broadens the authorized scope. A refused escalation gets a safer alternative inside the boundary, or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences plus the observed validation for a simple change, more only when the complexity earns it. Lead with the result or decision; omit abandoned approaches unless they explain a tradeoff the reader needs; narrate no internal bookkeeping (todo transitions, follow-up declarations, waits). Required closing lines stay outside this scaling: the observed run summary, and any prepared-not-observed or unmerged work, are stated whatever the brief's length.
- Expose core OMH roles: interviewer, planner, researcher, builder, reviewer, and loop controller.
- Route tiny direct tasks to one-cycle delivery surfaces instead of forcing loop overhead.
- Reframe a north-star ambition into a bounded arena, observable problem, next loop goal, and next verification without shrinking its ambition.
- Separate task discovery, distribution, execution, verification, next-task decision, runtime tick queueing, durable-checkpoint/handoff, feedback, waiting, and resume decisions.
- Expose a permission profile before executor/runtime dispatch, repository mutation, PR, merge, or external publishing.
- Expose the automation, worktree, skill, connector, and subagent building-block states without treating planned blocks as observed work.
- Choose workflow patterns such as single-step, fan-out-and-synthesize, adversarial verification, tournament, or triage batch as orchestration metadata only.
- Keep repeated scaffold shape stable, summarize within bounded budgets, and add verifier lanes only when risk or evidence warrants them.
- Keep prepared worktree/subagent/connector plans, observed executor work, linked goal completion, and external waiting as distinct evidence states.
- Use cheap inner-loop checks frequently and expensive outer-loop checks sparingly.
- Keep the practical small-loop recipe visible: test as stop signal, plan -> execute -> verify, one task at a time.
- Surface verification_gap, comprehension_debt, and cognitive_surrender as warnings before a loop starts looking self-steering.
- Before a loop launches, or when asked whether one will hold, load `references/loop-design-review.md`: a finish line written beside the fence of files the loop may not edit, a judge other than the builder, and the pre-launch failure check.
- Use `omh loop assess`, `start`, `status`, `tick`, and `feedback` as local metadata control-plane commands. Execute authorized work through the current host. The default hermes_goal driver label is prepared metadata, not an available host goal controller. Do not invoke native /goal controls on another host.
- Only an explicitly selected coding owner with a session-bound host_observed resumable_goal capability may use the external goal-driver CLI path. Otherwise keep a host-owned evidence ledger; report unavailable native goal activation rather than fabricating it.
- Treat ticks as preparation only. Record host phase results separately; never manufacture native phase-transition evidence from a host task declaration.
- Treat a judge `done` verdict, a turn-ceiling pause, or a gate-retry pause as narration; completion still requires the linked goal ledger completion gate and observed evidence.
- Treat any future change to the default as a maintainer-reviewed product decision, not a runtime phase or automatic loop outcome.
- Compare only observed outcomes under matched task, model/provider, permissions, turn budget, and verification surface; unresolved evidence keeps the current default.
- Keep promotion governance separate from goal-ledger completion and ordinary measured-loop keep/discard decisions; do not invent subjective scorers, fixed numeric thresholds, minimum run counts, weighted percentages, or per-turn artifact quotas.
- Name the one element gating this loop from the `loop_constraint_assessment/v1` block before choosing the next action; if none is binding, say so from the recorded reason rather than assuming.
- When the goal is measurable, declare the evaluation contract before the first attempt - exact command, metric name, direction, and the rule that the loop may not modify the scoring harness - and bind every keep or discard decision to it; when no such contract exists, say the goal is unmeasured instead of scoring it by judgement.
- Run a measurable cycle as attempt, commit, measure, then keep or reset; a reset is the normal discard, and rewinding to an older commit is for a run of discards that traces to one bad ancestor.
- For a measurable loop, keep a human-scannable ledger the loop itself appends to - one tab-separated line per cycle carrying commit, metric, cost, keep or discard or crash, and a one-line description - beside the JSON loop artifacts.
- Send long-running cycle output to a log file and pull only the declared metric and error lines into context; read the whole log only when the cycle crashed.
- Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism. Ladder and terminal states: shared rail.
- On an equal metric keep the simpler change, always keep an improvement achieved by deletion, and do not let a small gain buy added complexity.

Required inputs:

- loopability assessment
- north-star goal summary when present
- bounded arena
- observable problem
- next verification
- goal reframe
- success criteria
- permission profile
- feedback or wait signal

Expected outputs:

- loopability_assessment/v1 task/project/ambition classification
- loop_start_card/v1 setup prompt
- loop_cycle/v2
- loop_engineering/v1 pipeline/building-block snapshot
- loop verification_policy for inner/outer checks
- loop failure_mode_summary over verification gap, comprehension debt, and cognitive surrender
- small-loop guidance: test as stop signal, plan -> execute -> verify, one task at a time
- loop_status_card/v1 next action
- loop_runtime/v1 queued tick with verification_plan refs
- loop_queue_handoff/v1 only when permitted
- executor-neutral handoff only when permitted
- external-wait or checkpoint boundary
- host-owned continuation ledger; optional external goal-driver handoff only with an observed supported capability
- observed host task results kept separate from unsupported native goal observations
- host phase ledger with evidence references, not fabricated native phase transitions

Artifact expectations:

- loop_cycle/v2: loop_driver/v1 and loopability_assessment/v1 metadata
- loop_engineering/v1 status over automation, worktree, skill, connector, subagent, verification policy, and failure modes
- loop_runtime/v1 queue entries with context_policy_ref, cost_policy_ref, and verification_plan
- loop_subagent_result_contract/v1 for prepared subagent handoffs
- loop_status_card/v1 local status; native-goal fields remain not_observed on other hosts
- loop_start_card/v1 wrapper setup card
- linked goal_ledger/v1 only when completion evidence is required
- optional external goal-driver handoff only with observed session-bound support
- optional advisory external snapshots via goal-driver-observe; no native history is inferred
- host-owned phase/result evidence ledger, separate from native loop_phase_transition/v1

Safety rules:

- Do not treat loop persistence as permission to bypass the selected permission profile.
- Do not treat a runtime tick as worktree creation, subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or completion evidence.
- Do not claim goal completion from loop state; require linked goal_ledger/v1 completion evidence.
- When context or token budget runs out, checkpoint or rely on resumable state instead of pretending the loop is complete.
- External results such as market response, stars, or adoption are waiting states unless observed evidence is supplied.
- Do not let unattended loop progress bypass verification; missing or failed verification returns to plan/research or waits for evidence.
- Do not let comprehension debt or cognitive surrender hide behind green-looking loop status.
- Do not claim a goal is complete because the upstream judge said done, the turn budget ran out, or a gate paused the loop.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a stop condition or a decision the user owns ends the turn,
offer the next action as a question rather than declaring what will not be done.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
