---
name: omh-codegraph-refresh
description: [omh] Hermes Codegraph Refresh workflow: refresh local code intelligence, summarize repo structure, and prepare task-scoped codegraph handoff context without overclaiming execution. Use when the user says: codegraph-refresh, codegraph refresh, refresh codegraph, update codegraph, codegraph stale, stale codegraph, codegraph handoff, codegraph summary.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codegraph-refresh
    role: planner
    quality_tier: codegraph-gated
---

# Codegraph Refresh

This is a Hermes-native `codegraph-refresh` workflow skill.

## Why This Exists

`codegraph-refresh` adapts ECC-style codemap freshness into OMH's local codegraph commands so operators can refresh navigation context before handoff without pretending code intelligence is execution evidence.

## Do Not Use When

- The user needs a narrative first-read tour of an unfamiliar repo; use `codebase-onboarding`.
- The user already has accepted implementation criteria and wants code changes; use `ultrawork` or a coding handoff.
- The user asks for visual, frontend, or rendered UI QA; use `frontend`, `design-quality-gate`, or `visual-qa`.

## Examples

Good example:

- Prompt: codegraph-refresh update codemaps and prepare a handoff for the routing package before the next coding pass.
- Expected behavior: Prepare command plan, staleness report, summary/handoff requirements, and observed-only artifact boundaries.
- Why: The request is about refreshing local code intelligence before implementation.

Bad example:

- Prompt: codegraph-refresh 파일 안 보고 코드그래프가 최신이고 전체 아키텍처가 검증됐다고 말해줘.
- Expected behavior: Mark freshness, summary, and architecture claims not_observed until codegraph commands or repo evidence are inspected.
- Why: Codegraph freshness and architecture claims need observed local evidence.

## Completion Checklist

- Repo root, refresh depth, task focus, command choices, and write policy are explicit.
- Prepared command plans, observed outputs, generated artifacts, and executor handoff readiness are separated.
- `omh_codegraph_summary/v1`, `omh_codegraph_context/v1`, or `.omh/codegraph/codegraph.json` is claimed only with observed command or file evidence.
- Follow-up implementation, review, CI, and merge state are routed to their owning workflows instead of inferred from codegraph context.

## Recovery Notes

- If the codegraph command is unavailable, route to doctor or toolbelt-readiness before claiming freshness.
- If no task focus is supplied, prepare build/summary guidance and ask for focus only when a handoff pack would otherwise be misleading.
- If the index is stale or missing, report the stale/missing state and next safe command rather than treating prior summaries as current.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should refresh or summarize local repo code intelligence before planning, handoff, review, or implementation.

    Strong routing signals: `codegraph-refresh`, `codegraph refresh`, `refresh codegraph`, `update codegraph`, `codegraph stale`, `stale codegraph`, `codegraph handoff`, `codegraph summary`, `codemap`, `codemaps`, `update codemaps`, `refresh codemap`, `code map`, `code maps`, `stale code index`, `refresh code index`, `codegraph index`, `codegraph index refresh`, `codemap index`, `코드그래프`, `코드그래프 갱신`, `코드맵`, `코드맵 갱신`, `코드 인덱스`, `코드 인덱스 갱신`

## Catalog Metadata

Category: `planning`
Phase: `codegraph-refresh`
Hermes role: `planner`
Quality tier: `codegraph-gated`
Reasoning demand: `standard`

Quality bar:

- Name repo root, refresh depth, task focus, artifact write policy, and stop condition.
- Choose build, summary, handoff, `--write`, and `--json` deliberately instead of treating all codegraph commands as equivalent.
- Separate prepared command plans from observed command outputs, generated artifacts, and executor-ready handoffs.
- Route broader first-read orientation to codebase-onboarding and implementation to ultrawork or the selected coding owner.

Handoff policy:

Keep codegraph refresh as prepared local code-intelligence context. Running `omh codegraph build`, `omh codegraph summary`, or `omh codegraph handoff` requires observed command evidence before reporting artifact writes, summaries, focus files, or executor-ready handoff context.

Required inputs:

- repo root or current workspace
- refresh depth: build, summary, write artifact, or task-scoped handoff
- task or focus terms when a handoff pack is needed
- staleness signal, read-only boundary, and allowed command execution

Expected outputs:

- codegraph_refresh_plan/v1
- codegraph_command_plan/v1
- staleness_and_scope_report/v1
- codegraph_summary_request/v1
- codegraph_handoff_context/v1 when task-scoped
- not-evidence boundary

Artifact expectations:

- codegraph_command_plan/v1 naming `omh codegraph build`, `summary`, `handoff`, `--write`, and `--json` choices
- staleness_and_scope_report/v1 separating requested refresh scope, observed command output, missing index evidence, and stale artifacts
- `omh_codegraph_summary/v1` or `.omh/codegraph/codegraph.json` only when the corresponding command output or write is observed
- codegraph_handoff_context/v1 with task terms, focus files, symbols, entrypoints, warnings, and claim boundary when `omh codegraph handoff` is observed

Safety rules:

- Do not claim `.omh/codegraph/codegraph.json` was written without an observed `omh codegraph build --write` result.
- Do not present a codegraph summary or handoff as complete repo analysis, architecture proof, implementation, review, CI, or merge evidence.
- Keep command planning, observed command output, generated artifacts, inferred focus files, and executor dispatch separate.
- Never expose secret values from codegraph inputs or config files; record redacted paths and warning categories only.

## Structural Code Search

When the target is a syntactic shape rather than a string, load `omh-routing/references/structural-code-search.md` before searching. If ast-grep is not on PATH, use grep/ripgrep exactly as today.

## Runtime Evidence

Preferred harness for this skill: `codegraph-refresh`.

```sh
omh runtime record --skill codegraph-refresh --harness codegraph-refresh --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
