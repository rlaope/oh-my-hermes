---
name: omh-codebase-onboarding
description: [omh] Hermes Codebase Onboarding workflow: create a repo map, reading path, glossary, risk map, and first-task runway for unfamiliar codebases. Use when the user says: codebase-onboarding, codebase onboarding, repo onboarding, repository onboarding, codebase tour, code tour, new repo orientation, understand this repo.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codebase-onboarding
    role: planner
    quality_tier: onboarding-gated
---

# Codebase Onboarding

This is a Hermes-native `codebase-onboarding` workflow skill.

## Why This Exists

`codebase-onboarding` adapts ECC's code-tour and onboarding surfaces into an OMH-native first-read workflow so unfamiliar repos become navigable before implementation pressure starts.

## Do Not Use When

- The user already named a concrete implementation task and acceptance criteria; use `ultrawork` or `idea-to-deploy`.
- The user needs a whole-workspace capability inventory; use `workspace-audit`.
- The user wants a code diff review; use `code-review`.

## Examples

Good example:

- Prompt: codebase-onboarding 처음 보는 레포라서 구조, 주요 모듈, 테스트, 첫 작업 후보를 잡아줘.
- Expected behavior: Prepare repo_map/v1, reading_path/v1, domain_glossary/v1, risk map, and first_task_runway/v1 from observed files.
- Why: The request is repo orientation before implementation.

Bad example:

- Prompt: codebase-onboarding 파일 안 읽고 이 레포 아키텍처를 확정해줘.
- Expected behavior: Mark architecture as unobserved and inspect source evidence before making claims.
- Why: Onboarding is only useful when grounded in current repo evidence.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If acceptance criteria or verification are missing, route back to clarification before handoff.
- If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should help an operator or coding executor understand an unfamiliar repository before planning implementation.

    Strong routing signals: `codebase-onboarding`, `codebase onboarding`, `repo onboarding`, `repository onboarding`, `codebase tour`, `code tour`, `new repo orientation`, `understand this repo`, `how this repo works`, `first task runway`, `개발자 온보딩`, `레포 온보딩`, `코드베이스 온보딩`, `처음 보는 레포`, `레포 구조 설명`

## Catalog Metadata

Category: `planning`
Phase: `codebase-onboarding`
Hermes role: `planner`
Quality tier: `onboarding-gated`
Reasoning demand: `standard`

Quality bar:

- Name the audience, depth, repo root, read-only boundary, and stop condition.
- Separate observed files and commands from inferred architecture and unknowns.
- Produce a practical reading path and first-task runway rather than a flat file tour.
- Route follow-up implementation to plan, ultrawork, verification-gate, or workspace-audit as needed.

Handoff policy:

Keep codebase orientation in Hermes as prepared local context. File reads, generated maps, and first-task recommendations need observed repo evidence; code edits and executor handoffs happen only after onboarding identifies a concrete task.

Required inputs:

- repo root or supplied source context
- target audience: operator, new contributor, maintainer, or executor
- desired depth: quick map, architecture tour, first issue, or handoff pack
- known constraints such as no network, no secrets, or read-only mode

Expected outputs:

- codebase_onboarding_plan/v1
- repo_map/v1
- reading_path/v1
- domain_glossary/v1
- risk_and_unknowns_map/v1
- first_task_runway/v1
- not-evidence boundary

Artifact expectations:

- repo_map/v1 with observed directories, entrypoints, generated surfaces, tests, docs, scripts, and runtime artifacts
- reading_path/v1 ordered from product direction to architecture, core modules, tests, and operational docs
- domain_glossary/v1 with repo-specific terms, owners, artifacts, and evidence references
- first_task_runway/v1 with low-risk starter tasks, verification commands, and handoff readiness

Safety rules:

- Do not invent architecture, ownership, maturity, or runtime behavior without observed repo evidence.
- Do not mutate files, run setup, install dependencies, or dispatch an executor from onboarding alone.
- Keep onboarding findings, inferred risks, first-task suggestions, and implementation handoffs separate.
- Never expose secrets from config or environment files; record only redacted paths and risk categories.

## Structural Code Search

When the target is a syntactic shape rather than a string, load `omh-routing/references/structural-code-search.md` before searching. If ast-grep is not on PATH, use grep/ripgrep exactly as today.

## Runtime Evidence

Preferred harness for this skill: `codebase-onboarding`.

```sh
omh runtime record --skill codebase-onboarding --harness codebase-onboarding --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
