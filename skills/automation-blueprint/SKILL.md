---
name: automation-blueprint
description: [omh] Hermes Scheduled Ops Blueprint workflow: design recurring Hermes operations with schedule, delivery, silence policy, context chain, and prepared-vs-observed status.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: scheduled-ops-blueprint
    role: operator
    quality_tier: ops-blueprint-gated
---

# Automation Blueprint

This is a Hermes-native `automation-blueprint` workflow skill.

## Why This Exists

`automation-blueprint` exists so Hermes can make recurring operational work feel native and scheduled without OMH becoming a hidden cron runner, transport bot, source retriever, or executor.

## Do Not Use When

- The user needs a one-off report or deck; use `report-package` or `materials-package`.
- The user asks to review incident metrics once; use `reliability-review`.
- The user needs actual code changes; prepare a selected executor/runtime handoff after the blueprint or plan is accepted.

## Examples

Good example:

- Prompt: automation-blueprint every morning check competitor news and send a Slack digest only if something changed.
- Expected behavior: Prepare hermes_ops_blueprint/v1 with schedule intent, Slack delivery policy, silence rule, research/report skills, missing evidence, and next confirmation.
- Why: The request is recurring, delivery-shaped, and must stay prepared until host automation and gateway delivery are observed.

Bad example:

- Prompt: automation-blueprint prove the Slack digest was delivered this morning.
- Expected behavior: Ask for observed Hermes/gateway delivery evidence or report the delivery as not_observed instead of claiming it happened.
- Why: A blueprint can prepare the scheduled operation, but it cannot prove runtime execution or delivery.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `toolbelt-readiness`, `ops-observability-card`, `agent-ops-review`, `memory-curation-review`, `workflow-learning`, `doctor`, `skill`, `ask`, `cancel`) - scheduled ops, gateway cards, boards, tool readiness, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: Across every OMH skill: match intent to a lane, name adjacent workflows, and do not dismiss OMH because a generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; supplied paper->paper-learning; file->materials-package; search->web-research; code->ultraprocess/ralplan/review.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should turn a natural recurring/cron-like request into a scheduled ops blueprint without claiming host automation, platform delivery, source retrieval, or no-agent execution.

    Strong routing signals: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`, `recurring ops`, `recurring workflow`, `every morning`, `every day`, `daily digest`, `weekly digest`, `send to slack`, `send to discord`, `post to telegram`, `only if changed`, `silent if nothing changed`, `schedule this`, `매일`, `매주`, `정기`, `예약`, `반복`, `스케줄`, `슬랙`, `디스코드`, `텔레그램`, `보내`, `공유`, `변화 없으면`, `조용히`

## Catalog Metadata

Category: `operations`
Phase: `scheduled-ops-blueprint`
Hermes role: `operator`
Quality tier: `ops-blueprint-gated`

Quality bar:

- Name cadence/timezone uncertainty, delivery target, silence/no-change rule, selected skills, and context chain.
- Expose whether a no-agent watchdog is a candidate without claiming it exists or ran.
- List host automation, gateway delivery, source retrieval, and no-agent execution as not evidence until observed.

Handoff policy:

Keep schedule intent, delivery policy, silence rules, context-chain selection, and status narration in Hermes; prepare host automation or no-agent follow-up only after an operator/wrapper records observed runtime evidence.

Required inputs:

- recurring request
- schedule or cadence hint
- delivery target or current-thread default
- silence/no-change preference

Expected outputs:

- hermes_ops_blueprint/v1 projection
- schedule/delivery/silence confirmation needs
- status-card boundary
- not-evidence list

Artifact expectations:

- hermes_ops_blueprint/v1 under .omh/hermes-ops/blueprints when a wrapper or CLI records it

Safety rules:

- Do not claim host cron, Hermes automation, gateway delivery, source retrieval, no-agent execution, plugin load, or connector work from a prepared blueprint.
- Keep scheduled operations as projection metadata until the host runtime supplies observed evidence.
- Route later coding, material generation, or report delivery into separate accepted handoffs when needed.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `scheduled-ops-blueprint`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill automation-blueprint --harness scheduled-ops-blueprint --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
