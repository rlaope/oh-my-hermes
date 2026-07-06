---
name: connector-operator
description: [omh] Hermes connector operator workflow: scope external app actions across email, Slack, Discord, Notion, Linear, Jira, CRM, and similar providers with auth, payload, confirmation, and result-evidence gates.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, connector]
    category: connector
    phase: connector-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Connector Operator

This is a Hermes-native `connector-operator` workflow skill.

## Why This Exists

`connector-operator` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: connector-operator draft an email to the customer and prepare a confirmation gate before sending.
- Expected behavior: Produce `prepare_connector_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: connector-operator send the Jira update with hidden credentials and claim it was delivered.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Provider, target object, allowed action, payload summary, authority, confirmation policy, and stop condition are explicit.
- Credentials, missing connector setup, external writes, sends, ticket mutations, calendar invites, CRM updates, and webhook delivery are gated or marked missing.
- Message ids, ticket ids, provider responses, delivery receipts, and API effects are reported only from observed connector evidence.

## Recovery Notes

- If the connector, credentials, or permission is missing, route to toolbelt-readiness before preparing action success claims.
- If the request is only chat thread delivery policy for Discord, Slack, or Telegram, route to gateway-intent-card instead.
- If the external app action would create, send, invite, mutate, or delete provider state, require an explicit confirmation gate.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+23 more`) - schedules, status, health, and ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should prepare or supervise a provider-backed external app action without claiming connector availability, credentials, API mutation, delivery, or success.

    Strong routing signals: `connector-operator`, `connector operator`, `external app action`, `external connector action`, `saas action`, `api action`, `send email`, `email customer`, `gmail draft`, `gmail send`, `create linear ticket`, `linear ticket`, `update linear`, `jira ticket`, `create jira`, `notion page`, `update notion`, `crm update`, `salesforce update`, `hubspot update`, `create calendar event`, `calendar invite`, `google calendar`, `send slack dm`, `slack dm`, `discord dm`, `connector action`, `이메일 보내`, `이메일 발송`, `메일 보내`, `gmail 초안`, `linear ticket`, `linear 티켓`, `jira 티켓`, `notion 페이지`, `노션 페이지`, `캘린더 초대`, `외부 앱`, `외부 커넥터`, `커넥터 액션`

## Catalog Metadata

Category: `connector`
Phase: `connector-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- connector_task_card/v1
- connector_scope/v1
- connector_auth_boundary/v1
- connector_confirmation_gate/v1 when mutating or sending
- connector_result_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- connector_task_card/v1 metadata-only wrapper card when prepared
- connector_scope/v1 with provider, target object, allowed action, payload summary, and stop condition
- connector_auth_boundary/v1 separating missing connector, missing credentials, user-supplied authority, and credential-use prohibition
- connector_confirmation_gate/v1 for sending, ticket mutation, external write, webhook delivery, CRM/database update, or irreversible provider action
- connector_result_manifest/v1 only when provider response, message id, ticket id, API transcript, or delivery receipt is observed

Safety rules:

- A connector operator card is not connector availability, credential validation, API call, message send, ticket creation, ticket update, database/CRM mutation, external write, webhook delivery, or provider success evidence unless observed connector-result evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `connector-operator`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill connector-operator --harness connector-operator --status started
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
