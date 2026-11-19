# With/without lift measurement

`omh skill-eval` answers whether a host loads a skill. Whether the skill makes the
agent's answers better is a separate question, and only this measurement answers it.
Until it has run, say "not measured"; never infer lift from a ✅ host row.

## Design

1. Fix a task set before running anything: 5 to 20 tasks the skill is meant for,
   plus 2 to 5 it should not change. Write each with a scripted check: a test, an
   exact expected value, a file that must exist, or a grep that must match. A check
   that needs a person's judgment is recorded as such, not scored by the agent.
2. Run every task twice, in separate fresh children, with the same prompt and model:
   - **with**: the child is told to load the skill (`skill_view(name)`) first;
   - **without**: the child gets the same prompt and is told not to load it.
   In Hermes each run is one `delegate_task` child; give the two arms the same
   toolsets and working copy, reset the working copy between runs, and record the
   model each child reports.
3. Run each arm at least twice per task when the check is noisy; report every run,
   not the best one.

## Cost

Children run on the session's model, which is the user's subscription by default:
cost 0 beyond that plan. Do not route an arm to a paid API model unless the user
approved that spend in this conversation, and name the model and its price first.

## Results table

| task | check | with: pass/runs | without: pass/runs | note |
|---|---|---|---|---|

Under the table: the model, the date, the skill's commit or file digest, and the
totals per arm. Lift is the difference in pass counts on the same tasks. A
difference of one task on a small set is noise; say so instead of calling it lift.

## What it does not show

- It does not show the skill loads on another host; `omh skill-eval` does that.
- It does not generalize past the task set and model it ran on.
- A task the skill should not change that now fails is a regression: report it
  next to the lift, not below it.
