# Goal Constraint Discipline

Load this reference when a loop or durable-checkpoint goal needs constraint-first prioritization: deciding where the next unit of attention goes before deciding how to spend it.

## Why Constraint-First

At any moment, exactly one element gates how fast recorded work becomes observed goal progress. Effort spent anywhere else produces prepared artifacts, not progress. Naming that one element before acting is what keeps a goal-driven loop from optimizing a lane that was never the problem.

## Translation Table

Each concept on the left maps onto OMH state that already exists; nothing here invents new state.

| concept | OMH goal-engineering equivalent |
| --- | --- |
| the goal | observed, evidence-backed completion of goal-ledger criteria - never prepared artifact count, busy-ness, or judge narration |
| throughput | the rate at which required criteria become satisfied with evidence refs: observed completions per iteration |
| inventory | everything `prepared_not_observed`: pending queue items, unpasted handoffs, unreviewed plans - work that has consumed effort but produced no observed value |
| operating expense | turns, tokens, context budget, and executor dispatches spent converting prepared work into observed evidence |
| constraint | the single element currently gating goal progress: an unsatisfied required criterion, a blocked queue item, a closed permission envelope, an external wait, a `verification_gap` warning, or exhausted context or budget |
| drum-buffer-rope | the constraint sets the pace (drum), one prepared handoff ahead keeps it fed (buffer - small and deliberate, never a pile), and the `pending_queue_exists` refusal ties new work to constraint consumption (rope - a pacing device, not bureaucracy) |

## The Five Focusing Steps

1. **Identify** - name the single constraint gating the goal now, from recorded state: the completion gate's missing required criteria, blocked and pending queue counts, `wait_reason`, failure-mode warnings, and the permission envelope. The constraint is where `prepared_not_observed` work piles up.
2. **Exploit** - get everything out of the constraint before spending anything new: observe the pending item before preparing another, and aim the next iteration's full attention at the one unsatisfied criterion.
3. **Subordinate** - pace every non-constraint lane to the constraint. Non-constraint lanes do not need full utilization: idle-and-ready beats producing inventory. Never fan out more research, plans, or handoffs than the observation bottleneck can absorb.
4. **Elevate** - only after exploit and subordinate still leave the constraint binding, add capacity: raise the turn ceiling, widen the permission envelope, add an executor, request budget. Elevation is an explicit, costed escalation; most constraints resolve at step 3 and never justify it.
5. **Repeat** - after any constraint resolves, a new one exists by definition. Re-identify at every iteration boundary; never keep optimizing yesterday's constraint.

## Anti-Patterns

- **Robot-line fallacy** - celebrating a lane's output (plans drafted, handoffs prepared) while observed completions stay flat.
- **Inventory blindness** - treating `prepared_not_observed` growth as progress. It is cost.
- **Balanced-line fallacy** - trying to keep every lane equally busy. Constraint-first discipline deliberately runs non-constraint lanes below capacity.
- **Premature elevation** - asking for more turns, agents, or budget while the current constraint is under-exploited (step 4 before steps 2-3).
- **Constraint inertia** - still optimizing a constraint that already resolved (step 5 skipped).

## What The Deterministic Assessment Does And Does Not Say

The `loop_constraint_assessment/v1` block on every `loop_status_card/v1` answers **Identify** from recorded state. It walks a closed class tuple in rank order and emits at most one candidate per class:

- `capacity_exhausted`
- `permission_envelope`
- `goal_status_gap`
- `blocked_queue_item`
- `observation_backlog`
- `external_wait`
- `verification_gap`
- `unsatisfied_required_criterion`
- `active_blocker`
- `unsatisfied_runtime_check`
- `comprehension_debt`
- `human_judgment`
- `goal_link_missing`

When nothing fires, it says so with a derived reason naming every class it checked. The assessment is prepared analysis: it selects no route, dispatches nothing, and is never execution, review, CI, merge, or goal completion evidence. The constraint assessment explains why the loop is gated; the card's own next_action stays the recorded directive. When the two differ, the binding constraint names what to fix and next_action names the recorded step.

## Attribution

The constraint-first prioritization above adapts Eliyahu M. Goldratt's Theory of Constraints as presented in *The Goal* (1984). No upstream text is reproduced. OMH maps the mechanisms onto its own goal ledger, queue, permission envelope, and evidence vocabulary, and keeps prepared analysis separate from observed evidence.
