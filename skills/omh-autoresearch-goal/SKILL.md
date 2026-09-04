---
name: "omh-autoresearch-goal"
description: "[omh] Hermes adaptation for durable research-goal execution. Use when the user says: autoresearch-goal, research goal, durable research, critic research."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: durable-research
    role: researcher
    quality_tier: validator-gated
---

# Autoresearch Goal

This is a Hermes-native `autoresearch-goal` workflow skill.

## Why This Exists

`autoresearch-goal` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: autoresearch-goal: keep researching AI agent memory practices until the evidence gaps are closed or logged.
- Expected behavior: Run a durable research loop with critic checks, source gaps, and a stop or checkpoint condition.
- Why: The request is research that needs persistence and review, not a one-shot brief.

Bad example:

- Prompt: autoresearch-goal: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `autoresearch-goal`.
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

Use for validator-gated research that needs durable artifacts.

    Strong routing signals: `autoresearch-goal`, `research goal`, `durable research`, `critic research`

## Catalog Metadata

Category: `research`
Phase: `durable-research`
Hermes role: `researcher`
Quality tier: `validator-gated`
Reasoning demand: `standard`

Quality bar:

- Define validator criteria before gathering evidence.
- Run each cycle as evidence-gap closure: name the open gaps the cycle targets, then stop at the validator criteria or the declared iteration budget, whichever comes first.
- Keep durable research artifacts separate from coding execution evidence.
- Stop with next questions or a source-backed synthesis when validation is incomplete.

Handoff policy:

Keep durable research in Hermes-managed artifacts; do not convert to executor handoff unless the research produces an accepted coding task.

Required inputs:

- research objective
- validator criteria
- source boundaries

Expected outputs:

- research artifact
- validator result
- next questions

Artifact expectations:

- durable research ledger or checklist

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `research`.

```sh
omh runtime record --skill autoresearch-goal --harness research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
