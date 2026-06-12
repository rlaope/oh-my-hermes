---
name: research-brief
description: [omh] Hermes Research Brief workflow: source-backed business research without pretending evidence was fetched.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: business-brief
    role: retained-cognition
    quality_tier: source-gated
---

# Research Brief

This is a Hermes-native `research-brief` workflow skill.

## Why This Exists

`research-brief` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: research-brief: handle a research request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `research-brief` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: research-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `research-brief`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use when Hermes should scope a business question, gather or summarize source-backed evidence, and preserve evidence/inference boundaries before strategy or handoff.

    Strong routing signals: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`, `market evidence`, `data search`, `source scan`, `자료 조사`, `데이터 서치`, `근거 조사`, `피드백 추세`, `고객 피드백 추세`

## Catalog Metadata

Category: `research`
Phase: `business-brief`
Hermes role: `retained-cognition`
Quality tier: `source-gated`

Quality bar:

- State the research question, source boundaries, and recency assumptions before synthesis.
- Separate observed sources from inferred trends and unresolved uncertainty.
- Use the brief to feed strategy or meeting work without calling it execution evidence.

Handoff policy:

Keep business research in Hermes; prepare a selected executor/runtime handoff only after a later accepted plan requires code changes.

Required inputs:

- business question
- source boundary
- recency or market scope

Expected outputs:

- evidence table
- inference summary
- confidence and uncertainty

Artifact expectations:

- research brief or source ledger when the wrapper captures observed sources

Safety rules:

- Do not claim sources were fetched unless Hermes or the wrapper observed them.
- Separate evidence, inference, confidence, and missing-source gaps.
- Route later implementation separately through an accepted plan and coding handoff.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `business-research`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill research-brief --harness business-research --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
