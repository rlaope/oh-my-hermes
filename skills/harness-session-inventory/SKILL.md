---
name: harness-session-inventory
description: [omh] Hermes harness session inventory workflow: normalize Codex, Claude Code, Hermes, OpenCode, Cursor, MCP host, worktree, and wrapper session metadata into one drift-aware inventory.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: harness-session-inventory
    role: tracker
    quality_tier: workflow-surface-gated
---

# Harness Session Inventory

This is a Hermes-native `harness-session-inventory` workflow skill.

## Why This Exists

`harness-session-inventory` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: harness-session-inventory compare Codex, Claude Code, Hermes, MCP configs, and worktrees for drift before we dispatch agents.
- Expected behavior: Produce `prepare_harness_session_inventory` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: harness-session-inventory claim every MCP host loaded and every agent session is healthy from config files alone.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The inventory scope names the harnesses, sessions, MCP hosts, connector configs, and worktrees being compared.
- Prepared, observed, missing, stale, and drifted entries are separated before any health or progress claim.
- The next action says whether to load a host, verify a connector, inspect a worktree, dispatch an executor, or stay blocked.

## Recovery Notes

- If config sources are unavailable, report only the discovered surfaces and mark the missing hosts not_observed.
- If cleanup, host load, connector execution, or session progress is requested, route to the owning workflow instead of folding it into inventory.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+16 more`) - schedules, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when operators need a cross-harness/session/MCP/worktree inventory and drift summary before claiming any host loaded, connector ran, or agent session progressed.

    Strong routing signals: `harness-session-inventory`, `harness session inventory`, `session inventory`, `session adapter`, `session adapters`, `harness sessions`, `mcp inventory`, `mcp config inventory`, `mcp drift`, `harness drift`, `connector drift`, `worktree inventory`, `worktree lifecycle`, `operator inventory`, `control pane inventory`, `codex session inventory`, `claude code session inventory`, `세션 인벤토리`, `하네스 세션`, `하네스 드리프트`, `MCP 인벤토리`, `MCP 설정 드리프트`, `워크트리 인벤토리`, `커넥터 드리프트`

## Catalog Metadata

Category: `observability`
Phase: `harness-session-inventory`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- harness_session_inventory/v1 card or guidance
- harness_session_adapter_matrix/v1
- mcp_inventory_drift_report/v1
- worktree_lifecycle_snapshot/v1
- session_progress_slots/v1
- next action
- prepared-vs-observed boundary

Artifact expectations:

- harness_session_inventory/v1 metadata-only runtime or wrapper card when recorded
- harness_session_adapter_matrix/v1 with observed, prepared, missing, and stale adapters
- mcp_inventory_drift_report/v1 with secret-redacted config/source drift only
- worktree_lifecycle_snapshot/v1 with merge-conflict and cleanup candidates when observed

Safety rules:

- A harness session inventory is not host load, MCP tool-call, connector availability, executor dispatch, worktree cleanup, merge-conflict resolution, or session progress evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `harness-session-inventory`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill harness-session-inventory --harness harness-session-inventory --status started
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
