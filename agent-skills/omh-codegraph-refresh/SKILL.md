---
name: "omh-codegraph-refresh"
description: "[omh] Outdated code index or codemap: refresh local code intelligence, summarize repo structure, and prepare task-scoped codegraph handoff context without overclaiming execution. Use when the user says: codegraph-refresh, codegraph refresh, refresh codegraph, update codegraph, codegraph stale, stale codegraph, codegraph handoff, codegraph summary."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codegraph-refresh
    role: planner
    quality_tier: codegraph-gated
---

# Codegraph Refresh

This is an OMH `codegraph-refresh` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`codegraph-refresh` adapts ECC-style codemap freshness into OMH's local codegraph commands so operators can refresh navigation context before handoff without pretending code intelligence is execution evidence.

## Do Not Use When

- The user needs a narrative first-read tour of an unfamiliar repo; use `omh-codebase-onboarding`.
- The user already has accepted implementation criteria and wants code changes; use `ulw-work` or a coding handoff.
- The user asks for visual, frontend, or rendered UI QA; use `omh-frontend`, `omh-design-quality-gate`, or `omh-visual-qa`.

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

- If the codegraph command is unavailable, route to toolbelt-readiness before claiming freshness.
- If no task focus is supplied, prepare build/summary guidance and ask for focus only when a handoff pack would otherwise be misleading.
- If the index is stale or missing, report the stale/missing state and next safe command rather than treating prior summaries as current.



## When to Use

Use when Hermes should refresh or summarize local repo code intelligence before planning, handoff, review, or implementation.

    Strong routing signals: `codegraph-refresh`, `codegraph refresh`, `refresh codegraph`, `update codegraph`, `codegraph stale`, `stale codegraph`, `codegraph handoff`, `codegraph summary`, `codemap`, `codemaps`, `update codemaps`, `refresh codemap`, `code map`, `code maps`, `stale code index`, `refresh code index`, `codegraph index`, `codegraph index refresh`, `codemap index`, `코드그래프`, `코드그래프 갱신`, `코드맵`, `코드맵 갱신`, `코드 인덱스`, `코드 인덱스 갱신`

## Catalog Metadata

Category: `planning`
Phase: `codegraph-refresh`
Quality tier: `codegraph-gated`
Reasoning demand: `standard`

Quality bar:

- Name repo root, refresh depth, task focus, artifact write policy, and stop condition.
- Choose build, summary, handoff, `--write`, and `--json` deliberately instead of treating all codegraph commands as equivalent.
- Separate prepared command plans from observed command outputs, generated artifacts, and executor-ready handoffs.
- Route broader first-read orientation to codebase-onboarding and implementation to ultrawork or the selected coding owner.

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
