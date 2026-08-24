---
name: ulw-goal-experiment
description: [omh] Native goal experiment: shape an ULW loop contract, require explicit Hermes activation, and compare observed results before changing the loop default. Aliases: ulw-goal-experiment. Use when the user says: goal experiment, goal-experiment, compare ulw loop and native goal, native goal benchmark, goal completion contract experiment, 목표 실험, ulw loop와 goal 비교, 네이티브 goal 비교.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, goal-loop]
    category: goal-loop
    phase: native-goal-experiment
    role: planner
    quality_tier: experiment-gated
---

# Goal Experiment

This is a Hermes-native `goal-experiment` workflow skill.

## Why This Exists

`goal-experiment` exists to test whether ulw-loop goal shaping plus Hermes native /goal continuation improves real outcomes without reversing retired skill contracts or turning prepared slash text into hidden execution.

## Do Not Use When

- The user wants ordinary durable checkpoints; use the `ultrawork` durable_checkpoint capability.
- The user only needs a bounded loop without native /goal comparison; use `loop`.
- The user expects OMH to activate private Hermes queues, GoalManager, or judge APIs automatically.

## Examples

Good example:

- Prompt: $ulw-goal-experiment compare a release-fix task against ulw-loop with the same verification command.
- Expected behavior: Prepare the native /goal contract, keep activation explicit, collect paired observed scores, and evaluate the absorption gate without changing the default early.
- Why: The request explicitly asks for the opt-in paired experiment and names a deterministic verification surface.

Bad example:

- Prompt: $ulw-goal-experiment remember this project milestone for next month.
- Expected behavior: Use the durable checkpoint capability instead of starting a native-goal comparison experiment.
- Why: Checkpoint persistence alone does not need the paired native /goal benchmark.

## Completion Checklist

- The generated card says requires_user_activation and executed=false before Hermes accepts /goal.
- The completion contract names outcome, verification, constraints, boundaries, and stop_when.
- The paired-run evaluation separates observed activation, continuation, verification, and OMH completion evidence.
- The absorption decision keeps ulw-loop default unless every experiment gate passes.

## Recovery Notes

- If the desktop palette does not show `/ulw-goal-experiment`, run `omh update` or setup from the source checkout, then reload skills or start a new session.
- If Hermes /goal cannot be activated on the current surface, keep the experiment prepared and use ulw-loop without claiming a live comparison.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when the user explicitly wants to prepare and evaluate the opt-in ulw-goal-experiment without changing the durable checkpoint compatibility route or ulw-loop by default.

    Strong routing signals: `goal experiment`, `goal-experiment`, `ulw-goal-experiment`, `$ulw-goal-experiment`, `compare ulw loop and native goal`, `native goal benchmark`, `goal completion contract experiment`, `목표 실험`, `ulw loop와 goal 비교`, `네이티브 goal 비교`

## Catalog Metadata

Category: `goal-loop`
Phase: `native-goal-experiment`
Hermes role: `planner`
Quality tier: `experiment-gated`
Reasoning demand: `heavy`

Quality bar:

- Separate preparation, activation, continuation, deterministic verification, OMH completion, and absorption decisions into distinct evidence states.
- Compare the same task, model/provider, permissions, turn budget, and verification surface across ulw-loop and ulw-goal-experiment.
- Refuse absorption when any hard gate fails, any core axis is below three, or observed evidence is missing.

Handoff policy:

Keep goal shaping and evidence policy in Hermes/OMH, return prepared native /goal slash text with requires_user_activation, and treat live Hermes activation and continuation as observed only after the host reports evidence.

Required inputs:

- objective
- outcome
- verification
- constraints and boundaries
- stop condition
- optional deterministic quality gates

Expected outputs:

- ulw_goal_experiment/v1 prepared card
- native Hermes /goal completion contract
- requires_user_activation boundary
- paired-run evaluation rubric
- absorption decision that keeps ulw-loop default until gates pass

Artifact expectations:

- prepared native goal handoff with executed=false
- reviewed paired-run scores for `omh loop ulw-goal-evaluate`
- observed activation and verification evidence only when supplied by Hermes runtime

Safety rules:

- Do not alter retired durable-goal compatibility aliases or install a competing legacy skill label.
- Run the preparation surface with `terminal(command="omh loop ulw-goal ...")`; the CLI alias is not a Hermes slash command and does not activate GoalManager.
- Treat prepared slash text as requires_user_activation with executed=false until the target Hermes session reports activation evidence.
- Hermes native judge output is observation only; final completion authority remains `omh_goal_completion_gate/v1` with linked evidence.
- Keep `ulw-loop` as the default until at least five paired runs, every hard gate, at least twenty percent weighted improvement, and a minimum score of three on every axis pass.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill goal-experiment --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
