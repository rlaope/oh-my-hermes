---
name: "omh-workspace-audit"
description: "[omh] Workspace setup inventory and gaps: map repository, skill, prompt, plugin, MCP, hook, config, and runtime surfaces before strengthening or operating OMH. Use when the user says: workspace-audit, workspace audit, repo surface audit, repository surface audit, workspace surface audit, repo inventory, surface inventory, skill inventory."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: workspace-audit
    role: operator
    quality_tier: workspace-audit-gated
    related_skills: [omh-doctor, omh-source-finder, ulw-research, omh-harness-session-inventory]
---

# Workspace Audit

This is a Hermes-native `workspace-audit` workflow skill.

## Why This Exists

`workspace-audit` gives OMH an ECC-inspired but OMH-native front door for understanding a large agent workspace before strengthening it, without turning inventory into hidden mutation or runtime proof.

## Do Not Use When

- The user already named a concrete implementation task with files and acceptance criteria; use the coding handoff or delivery workflow.
- The request is local OMH installation health only; use `omh-doctor`.
- The request is a source acquisition or current web lookup; use `omh-source-finder` or `ulw-research`.
- The request compares several harnesses, sessions, MCP hosts, or worktrees for drift; use `omh-harness-session-inventory`.

## Examples

Good example:

- Prompt: workspace-audit OMH에 스킬/프롬프트/플러그인 표면이 어디 비어있는지 먼저 점검해줘.
- Expected behavior: Prepare workspace_audit_plan/v1, observed surface_inventory/v1, gap matrix, redacted config findings, and downstream workflow recommendation.
- Why: The user asks for repo/workspace capability strengthening based on observed local surfaces.

Bad example:

- Prompt: workspace-audit 발견한 config 파일을 바로 고치고 secret 값도 출력해줘.
- Expected behavior: Refuse secret disclosure, keep the audit read-only, and prepare a separate remediation handoff if needed.
- Why: Workspace audit is inventory and risk mapping, not unsafe config mutation or secret extraction.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If an in-scope plugin, MCP, or runtime surface cannot be inspected, retain the observed surface_inventory/v1 entries, mark that surface not_observed, and hand back the evidence gap rather than call it a missing capability.
- If config risks cannot be checked without exposing secret values, retain redacted key names and paths, mark those checks unresolved, and hand back config_security_findings/v1 with risk categories for later remediation.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should inspect the local repo/workspace/operator surface and produce a safe inventory, risk map, and gap list before planning, routing, or feature strengthening.

    Strong routing signals: `workspace-audit`, `workspace audit`, `repo surface audit`, `repository surface audit`, `workspace surface audit`, `repo inventory`, `surface inventory`, `skill inventory`, `prompt inventory`, `plugin inventory`, `hook inventory`, `config audit`, `what are we missing`, `audit this repo`, `레포 감사`, `워크스페이스 감사`, `설정 감사`, `스킬 인벤토리`, `аудит репозитория`, `аудит воркспейса`, `инвентаризация репо`, `инвентарь скиллов`, `аудит харнессов`, `аудит харнесов`, `проверь конфиги`

## Catalog Metadata

Category: `operations`
Phase: `workspace-audit`
Hermes role: `operator`
Quality tier: `workspace-audit-gated`
Reasoning demand: `light`

Quality bar:

- Name the audit scope, root, exclusions, and downstream decision before inspecting.
- Separate discovered surfaces, inferred relationships, missing evidence, risks, and candidate fixes.
- Rank gaps by user impact, operational risk, and reviewability rather than by file count.
- Route code changes, setup repair, security fixes, or skill updates into later explicit workflows.

Handoff policy:

Keep the audit as Hermes-retained local evidence gathering. Prepare executor handoff only for later code changes, and record file reads, tool availability, config checks, and runtime observations only when observed.

Required inputs:

- workspace or repo root
- audit scope: repo, skills, prompts, plugins, MCP/tools, hooks, config, docs, runtime artifacts
- known constraints such as no secrets, no network, or read-only mode
- desired downstream decision or strengthening goal

Expected outputs:

- workspace_audit_plan/v1
- surface_inventory/v1
- capability_gap_matrix/v1
- config_security_findings/v1
- downstream_workflow_recommendation/v1
- not-evidence boundary

Artifact expectations:

- workspace_audit_plan/v1 with target root, scopes, exclusions, and read-only boundary
- surface_inventory/v1 with repo, skill, prompt, plugin, MCP/tool, hook, config, docs, and runtime surfaces when observed
- capability_gap_matrix/v1 with missing, duplicate, stale, risky, and high-leverage strengthening candidates
- redacted config_security_findings/v1 when secrets, permissions, or external integrations are mentioned

Safety rules:

- Do not mutate repo files, installed skills, prompts, configs, plugins, MCP servers, hooks, secrets, or runtime state from the audit lane.
- Never print secret values; record only redacted key names, file paths, and risk categories.
- Do not claim a surface exists, is loaded, or is reachable unless file, CLI, wrapper, or supplied evidence was observed.
- Keep audit findings separate from implementation, setup repair, security remediation, or skill mutation.

## Runtime Evidence

Preferred harness for this skill: `workspace-audit`.

```sh
omh runtime record --skill workspace-audit --harness workspace-audit --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
