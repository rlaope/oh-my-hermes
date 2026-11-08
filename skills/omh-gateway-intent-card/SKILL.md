---
name: "omh-gateway-intent-card"
description: "[omh] Bot replies via Discord, Slack, or Telegram: normalize Discord, Slack, Telegram, and other gateway sessions into origin, thread, delivery, silent, attachment, and status-update policy. Use when the user says: gateway-intent-card, gateway intent, discord thread, slack thread, telegram delivery, discord delivery policy, slack delivery policy, telegram delivery policy."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, gateway]
    category: gateway
    phase: intent-card
    role: guide
    quality_tier: workflow-surface-gated
    related_skills: [omh-automation-blueprint]
---

# Gateway Intent Card

This is a Hermes-native `gateway-intent-card` workflow skill.

## Why This Exists

`gateway-intent-card` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- The request names a cadence or a recurring job (every morning, a daily digest, a cron job); use `omh-automation-blueprint`.

## Examples

Good example:

- Prompt: gateway-intent-card route this Discord thread update silently unless action is needed.
- Expected behavior: Produce `prepare_gateway_intent_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: gateway-intent-card prove the Telegram attachment was sent.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The origin platform, thread/session boundary, delivery target, and update policy are named.
- Prepared card or command output is separate from platform registration, send, attachment, or delivery evidence.
- The next wrapper action is explicit and platform-safe.
- For `send_message` the delivery target is a bare platform name (its home channel), `platform:chat_id` (channel-level) or `platform:chat_id:thread_id` (thread-level); `origin` is only a cron job's `deliver` value and `send_message` refuses it, and a reply to the same chat is just the reply.
- An attachment is a `MEDIA:/absolute/path` line in the reply, and the platform adapter that cannot send it is named instead of promising the file.
- A silent update is a whole final reply of `[SILENT]` or `NO_REPLY`: a live gateway chat stays silent for an internal or heartbeat turn, a message known to expect no reply, or a healthy completed turn in a room with `allow_silence: true` (Hermes 0.22.6 and later); on any other human message Hermes 0.21.6 and later replaces the marker with a visible warning asking them to retry, an older Hermes drops it with no reply, and cron and webhook runs follow a looser rule.

## Recovery Notes

- If silent update conflicts with a status notice, keep the thread; hand back the silent-or-notify choice.
- If an action would touch a thread other than the named one, mark it unresolved; hand back the target.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes needs platform-neutral gateway policy for a chat session, thread, delivery target, attachment, or status update.

    Strong routing signals: `gateway-intent-card`, `gateway intent`, `discord thread`, `slack thread`, `telegram delivery`, `discord delivery policy`, `slack delivery policy`, `telegram delivery policy`, `discord status update`, `slack status update`, `telegram status update`, `gateway delivery`, `gateway notification`, `channel delivery`, `session delivery`, `silent update`, `attachment policy`, `status update policy`, `webhook delivery`, `게이트웨이`, `디스코드`, `슬랙`, `텔레그램`, `알림`, `전달`, `채널`, `조용히`, `스레드`, `보내줘`

## Catalog Metadata

Category: `gateway`
Phase: `intent-card`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

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

- gateway-intent-card/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- gateway-intent-card/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- A gateway intent card is not platform login, message send, thread mutation, attachment upload, or delivery evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `gateway-intent-card`.

```sh
omh runtime record --skill gateway-intent-card --harness gateway-intent-card --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
