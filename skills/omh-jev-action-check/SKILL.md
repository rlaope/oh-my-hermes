---
name: "omh-jev-action-check"
description: "[omh] Risky command screened by Jev: Jev action check before a risky command: secrets, outbound sends, blast radius; can only add a hold. Use when the user says: jev-action-check, jev action check, ask jev if this command is safe, jev risk check."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: jev-action-check
    role: reviewer
    quality_tier: evidence-gated
    related_skills: [omh-security-safety-review, omh-terminal]
    requires_tools: [omh_jev_ask]
---

# Jev Action Check

Required: the command, working directory, and stated task. Output: hold, refuse_recommended, or no_extra_hold with its rule.

Read `skill_view(name='omh-routing', file_path='references/jev-rail.md')` before the first ask: consent, what leaves the machine, limits, and non-answer statuses. Prepared OMH routing is not execution or approval. Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Contract: `references/full-contract.md`. Preset: `references/preset.md`.

## Procedure

1. Name what leaves the machine: the command, the working directory, and the stated task.
2. Call `omh_jev_ask` with `preset: action_check/v1` and `state` {command, cwd, stated_task} before anything runs.
3. Report the outcome and rule; on `hold` or `refuse_recommended` ask the user before running, and on `no_extra_hold` the host's normal approval still applies. A non-answer is a `hold` too.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.
- Report the tool's status, ask_id, served model, and cost source; a non-answer is `hold` with `rule: not_answered:<status>`, never Jev's answer.
- Record observed delegation results; use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.

## Recovery Notes

- Tool missing, `consent_not_observed`, or refused: follow the rail's recovery section; never simulate an answer.
- Here a missing tool, a non-answer, or a command refused as credential-like is a `hold`, not permission to continue without the screen: tell the user it did not run.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
