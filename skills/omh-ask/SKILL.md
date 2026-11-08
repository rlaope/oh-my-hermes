---
name: "omh-ask"
description: "[omh] Outside AI critique wanted: consulting an external advisor when configured. Use when the user says: ask, external advisor, ask claude, ask gemini, consult claude, consult gemini, opinion from claude, opinion from gemini."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: external-advice
    role: reviewer
    quality_tier: evidence-gated
    related_skills: [omh-jev-ask, omh-adversarial-consensus]
---

# Ask

This is a Hermes-native `ask` workflow skill.

## Why This Exists

`ask` exists to put one outside model's critique beside the agent's own answer when the user wants it, as advice the agent weighs in the open rather than a verdict it adopts, from the advisor the user named or configured and never from a default one.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- The user wants typed yes/no, pick-one, or scored probabilities from Jev over supplied text; use `omh-jev-ask`.
- The user wants several perspectives to attack a proposal and a distilled constraint bundle; use `omh-adversarial-consensus`. Use this skill for one named outside advisor.

## Examples

Good example:

- Prompt: ask: ask Claude as an external advisor to critique this plugin bridge plan before implementation.
- Expected behavior: Prepare an advisor prompt, capture the response boundary, and summarize reusable critique.
- Why: The user wants outside review before committing to a direction.

Bad example:

- Prompt: ask: should I rename this variable?
- Expected behavior: Answer directly; no outside advisor would change the answer.
- Why: An outside critique is worth its cost only when it could change the decision.

## Completion Checklist

- Findings or no-issue results are grounded in concrete file, artifact, command, or source evidence.
- Open questions, residual risk, and missing verification are named.
- Fixes or follow-up work are separate handoffs unless the user explicitly asked to implement them.

## Recovery Notes

- If no advisor is configured, retain the question and context summary, mark external advice not_observed, and hand back the agent's own answer without choosing a default advisor.
- If the named advisor returns no response, retain the prepared advisor prompt, mark external advice not_observed, and hand back the question and context summary for a later consultation.
- If advisor claims lack file, artifact, command, or source evidence, retain the captured advice as advice only, mark those conclusions tentative, and hand back accepted/rejected points and unresolved questions in the decision note.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use only when an external advisor is configured and would materially improve the answer.

    Strong routing signals: `ask`, `$ask`, `external advisor`, `ask claude`, `ask gemini`, `consult claude`, `consult gemini`, `opinion from claude`, `opinion from gemini`, `second opinion`, `claude 의견`, `gemini 의견`

## Catalog Metadata

Category: `review`
Phase: `external-advice`
Hermes role: `reviewer`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Before consulting, name the question, why an outside answer could change yours, and the advisor the user named or configured (named in this request or earlier in this conversation, never inferred from an installed CLI; if none, ask once); with none, say so and answer without one.
- Report the advice as one input: which points you accept, which you reject and why, and none of it as a verdict, a review, or a verified fact.
- When the advisor is a coding CLI the user named and Hermes' bundled skill for it (`claude-code`, `codex`, or `opencode`) is in your skill list, take only the invocation from that skill and keep the run to advice, with no edits; load `references/cli-advisors.md`. None of these CLIs is the default advisor.

Handoff policy:

Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.

Required inputs:

- question
- context summary
- why external advice helps

Expected outputs:

- advisor summary
- accepted/rejected advice
- decision note

Artifact expectations:

- advisor transcript reference only when explicitly captured

Safety rules:

- Use only when configured and materially useful.
- Treat advisor output as evidence to evaluate, not authority.
- Do not send secrets or private prompts without explicit opt-in.

## Runtime Evidence

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill ask --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
