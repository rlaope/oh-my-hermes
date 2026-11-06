---
name: "omh-ask"
description: "[omh] Outside AI critique wanted: consulting an external advisor when configured. Use when the user says: ask, external advisor, ask claude, ask gemini, consult claude, consult gemini, opinion from claude, opinion from gemini."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: external-advice
    role: reviewer
    quality_tier: evidence-gated
---

# Ask

This is an OMH `ask` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ask` exists to put one outside model's critique beside the agent's own answer when the user wants it, as advice the agent weighs in the open rather than a verdict it adopts, from the advisor the user named or configured and never from a default one.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- The user wants typed yes/no, pick-one, or scored probabilities from Jev over supplied text.
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



## When to Use

Use only when an external advisor is configured and would materially improve the answer.

    Strong routing signals: `ask`, `$ask`, `external advisor`, `ask claude`, `ask gemini`, `consult claude`, `consult gemini`, `opinion from claude`, `opinion from gemini`, `second opinion`, `claude 의견`, `gemini 의견`

## Catalog Metadata

Category: `review`
Phase: `external-advice`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Before consulting, name the question, why an outside answer could change yours, and the advisor the user named or configured (named in this request, or already set up on this machine; if neither, ask once); with none, say so and answer without one.
- Report the advice as one input: which points you accept, which you reject and why, and none of it as a verdict, a review, or a verified fact.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
