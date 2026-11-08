---
name: "omh-jev-route"
description: "[omh] Undecided OMH route handed to Jev: Jev route pick: answer an OMH route question about which workflow fits, recorded without re-routing. Use when the user says: jev-route, ask jev which workflow, jev pick the workflow."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, gateway]
    category: gateway
    phase: jev-route
    role: guide
    quality_tier: evidence-gated
    related_skills: [omh-model-setup]
    requires_tools: [omh_jev_ask]
---

# Jev Route

Required: an undecidable route's `route_question` block and the user's message. Output: Jev's pick as a clarification and a recorded answer.

Read `skill_view(name='omh-routing', file_path='references/jev-rail.md')` before the first ask: consent, what leaves the machine, limits, and non-answer statuses. Prepared OMH routing is not execution or approval. Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Contract: `references/full-contract.md`.

## Procedure

1. Confirm the route carries `route_question` and the ladder lists `omh_jev_ask`; tell the user their message leaves the machine. With no `route_question` block, say there is no open route question and continue the normal route; offer `omh-jev-ask` with a typed Choice if they want Jev's pick among named options.
2. Call `omh_jev_ask` with the block unchanged as `route_question` and the message as `state`.
3. Offer Jev's top pick to the user as a question; the block's thresholds only shape the wording.
4. Record it with `omh_route_answer`: the block's `question_digest`, `answered_by: omh_jev_ask`, the returned `ask_id`, and Jev's `route_choice`, probabilities, and fits exactly as returned.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.
- Report the tool's status, ask_id, served model, and cost source; a non-answer is reported as its status and is never an answer.
- Record observed delegation results; use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.

## Recovery Notes

- Tool missing, `consent_not_observed`, or refused: follow the rail's recovery section; never simulate an answer.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
