---
name: web-research
description: Hermes Web Research workflow: source-backed current information gathering.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: current-evidence
    role: retained-cognition
    quality_tier: source-gated
---

# Web Research

This is a Hermes-native `web-research` workflow skill.

## Use When

Use when the user needs current web evidence, links, citations, or source comparison before planning or handoff.

    Strong routing signals: `web-research`, `web research`, `latest`, `current sources`, `source-backed research`, `investigate`, `research plan`, `조사`, `근거`, `출처`, `고객 피드백`

## Catalog Metadata

Category: `research`
Phase: `current-evidence`
Hermes role: `retained-cognition`
Quality tier: `source-gated`

Quality bar:

- Use official or primary sources first when current or external facts matter.
- Separate direct evidence, inference, confidence, and residual uncertainty.
- Summarize research before any coding handoff; research is not implementation evidence.

Handoff policy:

Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.

Required inputs:

- research question
- source boundaries
- recency or jurisdiction constraints

Expected outputs:

- source-backed synthesis
- links or citations
- confidence and residual uncertainty

Artifact expectations:

- research notes with source URLs when the wrapper captures them

Safety rules:

- Prefer official or primary sources when they can answer the question.
- Separate quoted evidence from inference.
- State retrieval limits and dates for unstable facts.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `research`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill web-research --harness research --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
