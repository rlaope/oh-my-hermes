---
name: "omh-codebase-onboarding"
description: "[omh] Unfamiliar repository needing a guided tour: create a repo map, reading path, glossary, risk map, and first-task runway for unfamiliar codebases."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codebase-onboarding
    role: planner
    quality_tier: onboarding-gated
---

# Codebase Onboarding

This is an OMH `codebase-onboarding` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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



## When to Use

Use when Hermes should help an operator or coding executor understand an unfamiliar repository before planning implementation.

    Strong routing signals: `codebase-onboarding`, `codebase onboarding`, `repo onboarding`, `repository onboarding`, `codebase tour`, `code tour`, `new repo orientation`, `understand this repo`, `how this repo works`, `first task runway`, `개발자 온보딩`, `레포 온보딩`, `코드베이스 온보딩`, `처음 보는 레포`, `레포 구조 설명`, `разберись в репозитории`, `объясни репозиторий`, `как устроен репозиторий`, `тур по репо`, `изучи кодовую базу`, `карта репозитория`

## Catalog Metadata

Category: `planning`
Phase: `codebase-onboarding`
Quality tier: `onboarding-gated`
Reasoning demand: `standard`

Quality bar:

- Name the audience, depth, repo root, read-only boundary, and stop condition.
- Separate observed files and commands from inferred architecture and unknowns.
- Produce a practical reading path and first-task runway rather than a flat file tour.
- Route follow-up implementation to `omh-plan`, `ulw-work`, `omh-verification-gate`, or `omh-workspace-audit` as needed.
- Take build, test, and lint commands in this order: CI config (`.github/workflows`, `.gitlab-ci.yml`), the task runner (`Makefile`, `justfile`, `package.json` scripts), the manifest, then contributor docs; read `CODEOWNERS` and the top-churn files for ownership; the README comes last, and where it disagrees with CI trust CI and record the disagreement.

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
