---
name: "omh-jev-failure-triage"
description: "[omh] Failing run handed to Jev for a next move: Jev failure triage: retry, fix a dependency, ask for access, or change approach on a failing run. Use when the user says: jev-failure-triage, jev failure triage, ask jev if this failure is transient."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: jev-failure-triage
    role: reviewer
    quality_tier: evidence-gated
    related_skills: [omh-build-failure-triage, omh-agent-debug, omh-live-incident-response]
    requires_tools: [omh_jev_ask]
---

# Jev Failure Triage

Required: the failing command, an error excerpt, and the retry count. Output: `failure_triage/v1` next move with its rule.

Read `skill_view(name='omh-routing', file_path='references/jev-rail.md')` before the first ask: consent, what leaves the machine, limits, and non-answer statuses. Prepared OMH routing is not execution or approval. Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Contract: `references/full-contract.md`. Preset: `references/preset.md`.

## Procedure

1. Name what leaves the machine: the command and an error excerpt (plus earlier attempt excerpts when repeating).
2. Call `omh_jev_ask` with `preset: failure_triage/v1`, `state` {error_excerpt, last_command, earlier_attempts}, and `attempts_so_far`.
3. Report `policy_result.outcome` and its rule beside the raw answers.
4. Hand the fix to `omh-build-failure-triage` or `omh-agent-debug`; a rerun still needs the host's approval.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.
- Report the tool's status, ask_id, served model, and cost source; a non-answer is `not_observed` with `rule: not_answered:<status>`, never Jev's answer.
- Record observed delegation results; use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.

## Recovery Notes

- Tool missing, `consent_not_observed`, or refused: follow the rail's recovery section; never simulate an answer.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
