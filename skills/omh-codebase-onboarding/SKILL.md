---
name: "omh-codebase-onboarding"
description: "[omh] Unfamiliar repository needing a guided tour: create a repo map, reading path, glossary, risk map, and first-task runway for unfamiliar codebases. Use when the user says: codebase-onboarding, codebase onboarding, repo onboarding, repository onboarding, codebase tour, code tour, new repo orientation, understand this repo."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codebase-onboarding
    role: planner
    quality_tier: onboarding-gated
    related_skills: [ulw-work, omh-idea-to-deploy, omh-workspace-audit, omh-code-review, omh-codebase-uml, omh-codegraph-refresh]
---

# Codebase Onboarding

This is a Hermes-native `codebase-onboarding` workflow skill.

## Why This Exists

`codebase-onboarding` exists so an unfamiliar repo gets a reading order, a glossary, and a first task that cite files that were opened, before implementation pressure starts; the surface is adapted from ECC's code-tour and onboarding work.

## Do Not Use When

- The user already named a concrete implementation task and acceptance criteria; use `ulw-work` or `omh-idea-to-deploy`.
- The user needs a whole-workspace capability inventory; use `omh-workspace-audit`.
- The user wants a code diff review; use `omh-code-review`.
- The user wants a picture of the structure; use `omh-codebase-uml`. The user wants the code index refreshed or a task-scoped handoff pack; use `omh-codegraph-refresh`.

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

- repo_map/v1 cites an observed path for every directory, entrypoint, generated surface, and test location it names; what was inferred is marked inferred, and what was never opened is listed as unread.
- reading_path/v1 is an ordered list of real files, each with why it comes at that point and what the reader knows after it.
- Every domain_glossary/v1 term points to where it is defined or used; a term with no source is an open question, not an entry.
- risk_and_unknowns_map/v1 keeps observed risks, each with the file or command that shows it, apart from unknowns, each with how it would be resolved.
- Every first_task_runway/v1 task names the files it touches and its verification command, and says whether that command was run during onboarding.
- The stop condition named at the start is met, or the reply names what was left unread.

## Recovery Notes

- If the audience or depth is not given, assume a new contributor and an architecture tour, read-only, and state the assumption in the first line.
- If the repository is too large for the stated depth, narrow to the entrypoint the audience touches first and record the rest as unread rather than summarizing it from file names.
- If a build, test, or setup command could not run (read-only mode, missing toolchain, secrets), list it in first_task_runway/v1 as not run with the reason, never as a known-good command. A command that installs or syncs dependencies as a side effect (`npm ci`, `uv sync`, and `uv run`, which syncs first) counts as setup and stays not run.
- If docs and code disagree, report what the code does, cite both, and add the disagreement to risk_and_unknowns_map/v1 instead of trusting the docs.
- If the user names a concrete task mid-tour, stop at the current reading_path/v1 entry and hand the runway so far to `omh-plan`, or to `ulw-work` or `omh-idea-to-deploy` when the task already has acceptance criteria.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `adversarial-consensus`, `codebase-onboarding`, `+9 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should help an operator or coding executor understand an unfamiliar repository before planning implementation.

    Strong routing signals: `codebase-onboarding`, `codebase onboarding`, `repo onboarding`, `repository onboarding`, `codebase tour`, `code tour`, `new repo orientation`, `understand this repo`, `how this repo works`, `first task runway`, `개발자 온보딩`, `레포 온보딩`, `코드베이스 온보딩`, `처음 보는 레포`, `레포 구조 설명`, `разберись в репозитории`, `объясни репозиторий`, `как устроен репозиторий`, `тур по репо`, `изучи кодовую базу`, `карта репозитория`

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
- Take build, test, and lint commands in this order: CI config (`.github/workflows`, `.gitlab-ci.yml`), the task runner (`Makefile`, `justfile`, `package.json` scripts), the manifest, then contributor docs; read `CODEOWNERS` and the top-churn files for ownership; the README comes last, and where it disagrees with CI trust CI and record the disagreement.

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

When the target is a syntactic shape rather than a string, load `skill_view(name='omh-routing', file_path='references/structural-code-search.md')` before searching. If ast-grep is not on PATH, use grep/ripgrep exactly as today. Cap exploration to a few bounded, targeted queries before reading a full file, escalate to a wider query only when a bounded pass finds nothing or stays ambiguous, and stop once the target is found.

## Runtime Evidence

Preferred harness for this skill: `codebase-onboarding`.

```sh
omh runtime record --skill codebase-onboarding --harness codebase-onboarding --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
