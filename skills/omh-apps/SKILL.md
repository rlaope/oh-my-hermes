---
name: "omh-apps"
description: "[omh] Email, Slack, or Jira action to perform: external app actions - email, Slack, Discord, Notion, Linear, Jira, CRM, and similar providers, scoped with auth, payload, confirmation, and result-evidence gates. Use when the user says: connector-operator, connector operator, external app action, external connector action, saas action, api action, send email, email customer."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, connector]
    category: connector
    phase: connector-task
    role: guide
    quality_tier: workflow-surface-gated
    related_skills: [omh-gateway-intent-card, omh-external-connector-readiness, omh-terminal]
---

# Connector Operator

This is a Hermes-native `connector-operator` workflow skill.

## Why This Exists

`connector-operator` exists because an email sent, a ticket written, or an invite delivered cannot be taken back: it scopes the provider, target, and payload, takes a missing connection to the host's own connection setup and respects a skip, and reports delivery only from a provider receipt.

## Do Not Use When

- Only the reply or thread policy of a Discord, Slack, or Telegram conversation is in question; use `omh-gateway-intent-card`.
- The user is choosing or adopting a new provider, MCP server, or integration rather than acting through one; use `omh-external-connector-readiness`.
- Launching or quitting a local desktop application; use `omh-terminal` or the host's computer-use tool.

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

- Provider, target object, allowed action, authority, confirmation policy, and stop condition are explicit; the confirmation shows the exact payload (recipients with cc/bcc, channel, subject, full body, attachments, attendees).
- Credentials, missing connector setup, external writes, sends, ticket mutations, calendar invites, CRM updates, and webhook delivery are gated, or marked missing and not run.
- With nobody to answer the confirmation (a scheduled job, a one-shot run, a webhook run), an irreversible or externally visible action is not run: it is handed to a person's turn and its confirmation is recorded as missing.
- Message ids, ticket ids, provider responses, delivery receipts, and API effects are reported only from observed connector evidence.

## Recovery Notes

- If the connector, credentials, or permission is missing: on Hermes, when `manage_connections` is in your tool list or tool_search finds it, use it for the app the user named (`status`, then `connect`) and take each app's answer as given: `connected` proceeds, `skipped` means continue without that app or ask in chat, never calling it again on your own or reaching the app another way, and `not_connected` stays a named gap. Otherwise route to `omh-toolbelt-readiness` before preparing action success claims.
- If the request is only chat thread delivery policy for Discord, Slack, or Telegram, route to `omh-gateway-intent-card` instead.
- If the external app action would create, send, invite, mutate, or delete provider state, require an explicit confirmation gate in chat before the call. Hermes asks the person before such a call only in some configurations (a write-capable tool on an MCP server set to `trust: untrusted`, or a plugin hook that escalates the call), so a host prompt that does appear is recorded as additional evidence and never replaces the chat confirmation.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should prepare or supervise a provider-backed external app action without claiming connector availability, credentials, API mutation, delivery, or success.

    Strong routing signals: `connector-operator`, `connector operator`, `external app action`, `external connector action`, `saas action`, `api action`, `send email`, `email customer`, `gmail draft`, `gmail send`, `create linear ticket`, `create linear issue`, `linear ticket`, `linear issue`, `update linear`, `jira ticket`, `jira issue`, `create jira issue`, `open jira ticket`, `create jira`, `notion page`, `update notion`, `crm update`, `salesforce update`, `hubspot update`, `create calendar event`, `calendar invite`, `google calendar`, `send slack dm`, `slack dm`, `discord dm`, `post to discord`, `post to slack`, `discord post`, `slack post`, `connector action`, `linear ticket`, `이메일 보내`, `이메일 발송`, `메일 보내`, `gmail 초안`, `linear 티켓`, `linear 이슈`, `jira 티켓`, `jira 이슈`, `notion 페이지`, `노션 페이지`, `캘린더 초대`, `외부 앱`, `외부 커넥터`, `커넥터 액션`

## Catalog Metadata

Category: `connector`
Phase: `connector-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

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
- connector_scope/v1 with provider, target object, allowed action, exact payload for any send or write, and stop condition
- connector_auth_boundary/v1 separating missing connector, missing credentials, user-supplied authority, and credential-use prohibition, with the host's own connection answer per app (`connected`, `skipped`, or `not_connected` on Hermes) when recorded
- connector_confirmation_gate/v1 for sending, ticket mutation, external write, webhook delivery, CRM/database update, or irreversible provider action
- connector_result_manifest/v1 only when provider response, message id, ticket id, API transcript, or delivery receipt is observed

Safety rules:

- A connector operator card is not connector availability, credential validation, API call, message send, ticket creation, ticket update, database/CRM mutation, external write, webhook delivery, or provider success evidence unless observed connector-result evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `connector-operator`.

```sh
omh runtime record --skill connector-operator --harness connector-operator --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
