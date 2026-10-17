---
name: "omh-automation-blueprint"
description: "[omh] Recurring Hermes job on a schedule (cron, digests): design recurring Hermes operations with schedule, delivery, silence policy, context chain, and prepared-vs-observed status. Use when the user says: automation-blueprint, scheduled ops, scheduled operation, scheduled operations, automation blueprint, cron blueprint, cron-ready, recurring ops."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: scheduled-ops-blueprint
    role: operator
    quality_tier: ops-blueprint-gated
    related_skills: [omh-lifecycle-growth, omh-report-package, omh-materials-package, omh-reliability-review, omh-spend-gate]
---

# Automation Blueprint

This is a Hermes-native `automation-blueprint` workflow skill.

## Why This Exists

`automation-blueprint` exists so a recurring request reaches Hermes' own Automation Blueprints and cron with the decisions they leave open (overlap, missed run, retry, backfill, failure pause, silence) settled first, without OMH becoming a hidden cron runner, transport bot, source retriever, or executor.

## Do Not Use When

- An undecided lifecycle journey or growth experiment needs audience, consent, and measurement design before any schedule; use `omh-lifecycle-growth` first.
- The user needs a one-off report or deck; use `omh-report-package` or `omh-materials-package`.
- The user asks to review incident metrics once; use `omh-reliability-review`.
- The user needs actual code changes; prepare a selected executor/runtime handoff after the blueprint or plan is accepted.
- The person is inside Hermes' own /blueprint setup for one of its catalog automations; answer the questions that flow asks and let it create the job instead of preparing a second blueprint.
- The recurring job would move money -- a purchase, a renewal, a top-up, or a transfer; use `omh-spend-gate`, because an agent run on a schedule never spends, and a no-agent script that pays is a spend set up now: its card, typed yes, and cap come before the job exists.

## Examples

Good example:

- Prompt: automation-blueprint every weekday run an uptime check and send a Slack digest only if status changes.
- Expected behavior: Draft prepared_native_blueprint/v1 with schedule intent, Slack delivery, a `[SILENT]` reply for unchanged runs, research/report skills, missing evidence, and the next confirmation.
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

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should turn a natural recurring/cron-like request into a scheduled ops blueprint without claiming host automation, platform delivery, source retrieval, or no-agent execution.

    Strong routing signals: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`, `recurring ops`, `recurring workflow`, `keep watching`, `keep monitoring`, `watch continuously`, `monitor continuously`, `every morning`, `every day`, `daily digest`, `weekly digest`, `automate this`, `automate workflow`, `send to slack`, `send to discord`, `post to telegram`, `only if changed`, `silent if nothing changed`, `schedule this`, `ずっと監視`, `監視し続け`, `継続的に監視`, `매일`, `매주`, `정기`, `예약`, `반복`, `자동화`, `자동화해줘`, `스케줄`, `슬랙`, `디스코드`, `텔레그램`, `보내`, `공유`, `변화 없으면`, `조용히`, `계속 감시`, `계속 모니터링`, `계속 지켜봐`, `持续监控`, `持續監控`, `一直监控`, `rancang otomatisasi terjadwal`, `bikin alur kerja otomatis setiap hari`, `rancang pengiriman ringkasan otomatis`

## Catalog Metadata

Category: `operations`
Phase: `scheduled-ops-blueprint`
Hermes role: `operator`
Quality tier: `ops-blueprint-gated`
Reasoning demand: `light`

Quality bar:

- Recommend one of cron, heartbeat, loop, and native goal, say why the other three lost, and carry its stop condition; a recommendation with no stop condition is not an answer, because what ends it is the only thing that separates the four — load `references/recurring-surface-choice.md` for the comparison, retry, and delivery rules.
- Name cadence/timezone uncertainty, delivery target, silence/no-change rule, selected skills, and context chain.
- When the recurring work is saved, say it is paused and name what activation needs: explicit overlap, missed-run, retry, backfill, and failure-pause decisions, an approval reference, and an observer from the approved runtime surface.
- Before activation, say what the policy does when a prior run is still active, when a window is missed, and when failures repeat; after a safety pause, report the applied policy and that resuming needs a policy revision.
- Project the prepared native blueprint onto Hermes' own fields: the `metadata.hermes.blueprint` block (schedule, deliver, prompt, no_agent) and the matching `cronjob_manage` create call when `cronjob_manage` is in your tool list or tool_search finds it, otherwise give the user the equivalent `hermes cron create` command; report-on-change is a `[SILENT]` final reply. A model pin is the user's to set: the block's own `model` and `provider` keys, `hermes cron create` or `hermes cron edit` with `--model` and `--provider`, or `pinned=true` only on the user's explicit request where `cronjob_manage` offers it.
- Map overlap, missed-run, retry, backfill, and failure-pause onto what Hermes cron does natively and say which choices it cannot honour, so nobody is asked for a policy the runtime ignores; the map is in `references/recurring-surface-choice.md`.
- After activation, read status from Hermes, not from the blueprint: `cronjob_manage` list (state, last_status, next_run_at), `hermes cron runs`, and open `hermes cron incidents` (detected or alerted).
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

- prepared_native_blueprint/v1 projection
- recurring_surface_comparison/v1 naming the recommended surface and why the other three lost
- hermes_recurring_intent/v1 paused lifecycle record when the user wants the recurring work saved
- schedule/delivery/silence confirmation needs
- status-card boundary
- not-evidence list

Artifact expectations:

- prepared_native_blueprint/v1 under .omh/hermes-ops/blueprints when a wrapper or CLI records it
- recurring_surface_comparison/v1 with the recommended surface among cron, heartbeat, loop, and native goal, its stop condition, and a per-surface reason the other three were not chosen
- hermes_recurring_intent/v1 under .omh/hermes-ops/recurring-intents when the user asks to save the recurring work

Safety rules:

- Do not claim host cron, Hermes automation, gateway delivery, source retrieval, no-agent execution, plugin load, or connector work from a prepared blueprint.
- Keep scheduled operations as projection metadata until the host runtime supplies observed evidence.
- A saved recurring intent is paused; never report that an occurrence ran without a runtime run reference recorded against that exact intent revision.
- A prepared failure policy is not enforcement: OMH never starts, skips, queues, retries, or backfills an occurrence, and a policy decision is not proof the runtime honoured it.
- Route later coding, material generation, or report delivery into separate accepted handoffs when needed.
- OMH creates, pauses, and removes no cron job: activation is the user's or Hermes' (`/blueprint`, an accepted Suggested Cron Job, a `cronjob_manage` create the user asked for in this conversation, or a `hermes cron create` the user runs), and a job Hermes lists is observed status, not proof that a run delivered.

## Runtime Evidence

Preferred harness for this skill: `scheduled-ops-blueprint`.

```sh
omh runtime record --skill automation-blueprint --harness scheduled-ops-blueprint --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
