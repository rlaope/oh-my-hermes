# Automation Blueprint

Load this on-demand contract after the compact `automation-blueprint` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- An undecided lifecycle journey or growth experiment needs audience, consent, and measurement design before any schedule; use `omh-lifecycle-growth` first.
- The user needs a one-off report or deck; use `omh-report-package` or `omh-materials-package`.
- The user asks to review incident metrics once; use `omh-reliability-review`.
- The user needs actual code changes; prepare a selected executor/runtime handoff after the blueprint or plan is accepted.
- The request is one message, thread reply, or attachment delivered now with no schedule; use `omh-gateway-intent-card`.
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

## Full Input, Output, and Artifact Expectations

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
