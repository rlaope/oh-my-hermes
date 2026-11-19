## Why This Exists

`loop` exists for goals whose correct implementation cannot be known upfront but can be discovered through bounded cycles of definition, action, verification, and revision without confusing planned cycles with observed progress.

## Do Not Use When

- The user asks for one bounded delivery cycle; use `ulw-work`'s delivery-boundary capability instead.
- Scope and milestones are already known and only durable checkpoint/resume tracking is needed; use `ulw-work`'s durable-checkpoint capability.
- The user gives only a north-star outcome such as revenue, stars, or adoption and declines the bounded first loop goal you proposed; stop at the proposed arena, problem and verification and wait.
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

## When to Use

Use when the user starts a high-level goal or invokes loop. Direct loop invocation means start/continue through interviewer, planner, researcher, builder, reviewer, and loop-controller lanes until a real gate stops it.

    Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan goal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `keep running until done`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`, `끝날 때까지 계속`, `계속 돌려줘`

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
