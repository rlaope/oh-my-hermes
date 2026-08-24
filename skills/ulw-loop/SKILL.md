---
name: ulw-loop
description: [omh] Hermes Loop workflow: agentic interviewer -> planner -> researcher -> builder -> reviewer cycles until a real gate. Use when the user says: loop, goal loop, long horizon goal, never stop, research plan goal feedback, token exhaustion resume, permission profile, star 10k.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, goal-loop]
    category: goal-loop
    phase: continuous-goal-loop
    role: planner
    quality_tier: loop-gated
---

# Loop

This is a Hermes-native `loop` workflow skill.

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
- Expected behavior: Start a permission-scoped loop, maintain loop_cycle/v1 state, choose the next concrete task, and keep external outcomes as waiting states.
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

## Recovery Notes

- If a queued tick is pending, show it as prepared queue state and use loop status/run-once before claiming progress.
- If feedback is unclear, ask one gate question or route back to research/plan rather than advancing the loop.
- If the goal turns into external waiting, record the waiting state and next observable signal instead of continuing locally.
- If context or budget is exhausted, checkpoint the loop artifact and continue from the latest loop_cycle/v1 state.
- If the upstream goal loop paused on its turn ceiling or a failing gate, record the pause as a loop wait state, not as completion, re-prepare the driver handoff, and re-register every gate after re-setting the goal, because setting a goal discards the previous gates.
- If the loop runs out of next actions, re-read the scoped files, recombine the near-miss attempts, then escalate to a more radical change before declaring the loop blocked.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when the user starts a high-level goal or invokes loop. Direct loop invocation means start/continue through interviewer, planner, researcher, builder, reviewer, and loop-controller lanes until a real gate stops it.

    Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan goal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`, `끝날 때까지 계속`, `계속 돌려줘`, `keep running until done`

## Catalog Metadata

Category: `goal-loop`
Phase: `continuous-goal-loop`
Hermes role: `planner`
Quality tier: `loop-gated`
Reasoning demand: `heavy`

Quality bar:

- Treat direct `loop`, `./loop`, `$loop`, and OMH loop invocations as a start/continue signal rather than a picker or passive clarification path.
- Classify the goal as task, project, ambition, external-wait, or unclear inside the loop, then keep progressing until a real permission, evidence, verification, context, budget, or external-wait gate appears.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or state exactly what the run is waiting on (for example, lanes still in flight that resume when their results return). Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it.
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
- Drive iteration with the upstream `/goal` loop from the prepared loop_goal_driver_handoff/v1, and register OMH's inner-tier checks as `/goal gate add` commands so verification runs before the judge.
- Treat a judge `done` verdict, a turn-ceiling pause, or a gate-retry pause as narration; completion still requires the linked goal ledger completion gate and observed evidence.
- Name the one element gating this loop from the `loop_constraint_assessment/v1` block before choosing the next action; if none is binding, say so from the recorded reason rather than assuming.
- When the goal is measurable, declare the evaluation contract before the first attempt - exact command, metric name, direction, and the rule that the loop may not modify the scoring harness - and bind every keep or discard decision to it; when no such contract exists, say the goal is unmeasured instead of scoring it by judgement.
- Run a measurable cycle as attempt, commit, measure, then keep or reset; a reset is the normal discard, and rewinding to an older commit is for a run of discards that traces to one bad ancestor.
- For a measurable loop, keep a human-scannable ledger the loop itself appends to - one tab-separated line per cycle carrying commit, metric, cost, keep or discard or crash, and a one-line description - beside the JSON loop artifacts.
- Send long-running cycle output to a log file and pull only the declared metric and error lines into context; read the whole log only when the cycle crashed.
- On an equal metric keep the simpler change, always keep an improvement achieved by deletion, and do not let a small gain buy added complexity.

Handoff policy:

Keep loop orchestration, role sequencing, verification-tier selection, deterministic runtime ticks, loop_engineering/v1 status, feedback evaluation, and permission narration in Hermes; prepare executor/runtime/worktree/connector/verifier handoffs only for concrete work and record completion only from linked evidence.

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
- loop_cycle/v1 state
- loop_engineering/v1 pipeline/building-block snapshot
- loop verification_policy for inner/outer checks
- loop failure_mode_summary over verification gap, comprehension debt, and cognitive surrender
- small-loop guidance: test as stop signal, plan -> execute -> verify, one task at a time
- loop_status_card/v1 next action
- loop_runtime/v1 queued tick with verification_plan refs
- loop_queue_handoff/v1 only when permitted
- executor-neutral handoff only when permitted
- external-wait or checkpoint boundary
- loop_goal_driver_handoff/v1 prepared /goal driver text with gates and turn-ceiling guidance

Artifact expectations:

- metadata-only .omh/loops loop_cycle/v1 artifact with loopability_assessment/v1
- loop_engineering/v1 status over automation, worktree, skill, connector, subagent, verification policy, and failure modes
- loop_runtime/v1 queue entries with context_policy_ref, cost_policy_ref, and verification_plan
- loop_subagent_result_contract/v1 for prepared subagent handoffs
- loop_status_card/v1 wrapper payload with loopability_assessment, failure_mode_summary, and small_loop_guidance
- loop_start_card/v1 wrapper setup card
- linked goal_ledger/v1 only when completion evidence is required
- loop_goal_driver_handoff/v1 prepared upstream /goal command, gate lines, and completion ownership

Safety rules:

- Do not treat loop persistence as permission to bypass the selected permission profile.
- Do not treat a runtime tick as worktree creation, subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or completion evidence.
- Do not claim goal completion from loop state; require linked goal_ledger/v1 completion evidence.
- When context or token budget runs out, checkpoint or rely on resumable state instead of pretending the loop is complete.
- External results such as market response, stars, or adoption are waiting states unless observed evidence is supplied.
- Do not let unattended loop progress bypass verification; missing or failed verification returns to plan/research or waits for evidence.
- Do not let comprehension debt or cognitive surrender hide behind green-looking loop status.
- Do not claim a goal is complete because the upstream judge said done, the turn budget ran out, or a gate paused the loop.

## Constraint Discipline

Before choosing the next action, name the one element gating this loop's goal progress - the binding constraint - then work it in order:

- **Identify** - read the binding constraint from recorded state: `wait_reason`, blocked and `prepared_not_observed` queue counts, failure-mode warnings, and the linked goal completion gate.
- **Exploit** - convert work the loop has already paid for: observe the prepared item or satisfy the one open criterion before preparing anything new.
- **Subordinate** - pace every other lane to the constraint; an idle non-constraint lane is healthy, a growing prepared pile is cost.
- **Elevate** - only after exploit and subordinate still leave it binding, escalate: more budget, a wider permission envelope, another executor - named as a costed last resort.
- **Repeat** - re-identify at the next iteration boundary; resolving one constraint surfaces the next.

The `loop_constraint_assessment/v1` block on the `loop_status_card/v1` answers **Identify** deterministically from recorded state. The constraint assessment explains why the loop is gated; the card's own next_action stays the recorded directive. When the two differ, the binding constraint names what to fix and next_action names the recorded step.

Load `references/goal-constraint-discipline.md` for the full method: the translation table, the five focusing steps, and the anti-patterns.

## Measured Loops

The measured-loop rules in the quality bar above apply when a loop has a score.

A loop is measurable when one command produces one number and a direction. Fix that evaluation contract before the first attempt, declare it in the loop's own state, and let it decide what is kept - the loop never edits the scoring harness that judges it. A loop with no such command says it is unmeasured and keeps deciding on verification evidence instead of inventing a score.

The two disciplines compose and do not compete: the binding constraint chooses which attempt to make, and the metric chooses whether that attempt is kept.

The metric never decides completion. The loop still stops at its permission, evidence, verification, context, budget, and external-wait gates, and closing the goal still requires linked `goal_ledger/v1` evidence.

Load `references/measured-loop-discipline.md` for the full method: the contract fields, the keep and discard rules, the ledger columns, the log rail, and the idea-exhaustion ladder.

## Runtime Evidence

Preferred harness for this skill: `goal-loop`.

```sh
omh runtime record --skill loop --harness goal-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
