---
name: workspace-audit
description: [omh] Hermes Workspace Audit workflow: map repository, skill, prompt, plugin, MCP, hook, config, and runtime surfaces before strengthening or operating OMH.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: workspace-audit
    role: operator
    quality_tier: workspace-audit-gated
---

# Workspace Audit

This is a Hermes-native `workspace-audit` workflow skill.

## Why This Exists

`workspace-audit` gives OMH an ECC-inspired but OMH-native front door for understanding a large agent workspace before strengthening it, without turning inventory into hidden mutation or runtime proof.

## Do Not Use When

- The user already named a concrete implementation task with files and acceptance criteria; use the coding handoff or delivery workflow.
- The request is local OMH installation health only; use `doctor`.
- The request is a source acquisition or current web lookup; use `source-finder` or `web-research`.

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

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+12 more`) - schedules, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should inspect the local repo/workspace/operator surface and produce a safe inventory, risk map, and gap list before planning, routing, or feature strengthening.

    Strong routing signals: `workspace-audit`, `workspace audit`, `repo surface audit`, `repository surface audit`, `workspace surface audit`, `repo inventory`, `surface inventory`, `skill inventory`, `prompt inventory`, `plugin inventory`, `mcp inventory`, `hook inventory`, `config audit`, `what are we missing`, `audit this repo`, `레포 감사`, `워크스페이스 감사`, `설정 감사`, `스킬 인벤토리`

## Catalog Metadata

Category: `operations`
Phase: `workspace-audit`
Hermes role: `operator`
Quality tier: `workspace-audit-gated`

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

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `workspace-audit`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill workspace-audit --harness workspace-audit --status started
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
