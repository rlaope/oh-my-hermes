---
name: codegraph-refresh
description: [omh] Hermes Codegraph Refresh workflow: refresh local code intelligence, summarize repo structure, and prepare task-scoped codegraph handoff context without overclaiming execution.
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
- The user already has accepted implementation criteria and wants code changes; use `ultraprocess` or a coding handoff.
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

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Intent -> plan** (`oh-my-hermes`, `deep-interview`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `ultragoal`, `ultraprocess`, `+3 more`) - clarify, plan, ship, or loop goals.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/accessibility-audit/visual-qa; paper->paper-learning; content->content-operator; file->materials-package; search->web-research; live info->live-info-operator; audit->workspace-audit/production-audit/security-safety-review; failures->build-failure-triage; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should refresh or summarize local repo code intelligence before planning, handoff, review, or implementation.

    Strong routing signals: `codegraph-refresh`, `codegraph refresh`, `refresh codegraph`, `update codegraph`, `codegraph stale`, `stale codegraph`, `codegraph handoff`, `codegraph summary`, `codemap`, `codemaps`, `update codemaps`, `refresh codemap`, `code map`, `code maps`, `stale code index`, `refresh code index`, `codegraph index`, `codegraph index refresh`, `codemap index`, `코드그래프`, `코드그래프 갱신`, `코드맵`, `코드맵 갱신`, `코드 인덱스`, `코드 인덱스 갱신`

## Catalog Metadata

Category: `planning`
Phase: `codegraph-refresh`
Hermes role: `planner`
Quality tier: `codegraph-gated`

Quality bar:

- Name repo root, refresh depth, task focus, artifact write policy, and stop condition.
- Choose build, summary, handoff, `--write`, and `--json` deliberately instead of treating all codegraph commands as equivalent.
- Separate prepared command plans from observed command outputs, generated artifacts, and executor-ready handoffs.
- Route broader first-read orientation to codebase-onboarding and implementation to ultraprocess or the selected coding owner.

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

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `codegraph-refresh`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill codegraph-refresh --harness codegraph-refresh --status started
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
