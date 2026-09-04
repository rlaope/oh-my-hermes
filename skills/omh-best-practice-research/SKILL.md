---
name: "omh-best-practice-research"
description: "[omh] Hermes adaptation for bounded official/upstream best-practice research. Use when the user says: best-practice-research, best practice, official docs, upstream guidance, what do the docs say, check the docs."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: evidence
    role: researcher
    quality_tier: source-gated
---

# Best Practice Research

This is a Hermes-native `best-practice-research` workflow skill.

## Why This Exists

`best-practice-research` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The work needs a market or literature comparison, or a decision-grounding dossier, rather than one technology's upstream guidance; use `research`.
- The question is a current-facts lookup one cited retrieval round settles rather than a versioned guidance question; use `web-research`.

## Examples

Good example:

- Prompt: best-practice-research: check official docs and upstream examples before we choose the plugin packaging pattern.
- Expected behavior: Gather primary-source guidance, compare options, and separate evidence from recommendation.
- Why: The request needs citation-backed best-practice research before implementation.

Bad example:

- Prompt: best-practice-research: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `best-practice-research`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The research question, source boundaries, recency assumptions, and confidence level are named.
- Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.
- Follow-up planning or handoff uses the research summary without calling it execution evidence.

## Recovery Notes

- If sources cannot be accessed, state the retrieval gap and use only observed local context.
- If evidence is thin or one-sided, lower confidence and ask for a narrower source boundary.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when correctness depends on current official or upstream guidance.

    Strong routing signals: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`, `what do the docs say`, `check the docs`

## Catalog Metadata

Category: `research`
Phase: `evidence`
Hermes role: `researcher`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- Use official or upstream sources first and name the version/environment assumptions.
- Map applicability to the user's local context before recommending action.
- Preserve residual uncertainty instead of overstating best practice.
- Upstream guidance is the strongest source class and still not completion evidence: that the docs prescribe something is never that it was done, verified, or is passing here.

Handoff policy:

Run as Hermes-side evidence gathering; hand coding to the selected executor/runtime only after source-backed guidance is summarized.

Required inputs:

- chosen technology
- question
- version or environment constraints

Expected outputs:

- source-backed guidance
- applicability notes
- residual uncertainty

Artifact expectations:

- research notes or citations when the wrapper captures them

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `research`.

```sh
omh runtime record --skill best-practice-research --harness research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
