---
name: "omh-harness-session-inventory"
description: "[omh] Lost track of agent sessions and worktrees: normalize Codex, Claude Code, Hermes, OpenCode, Cursor, MCP host, worktree, and wrapper session metadata into one drift-aware inventory. Use when the user says: harness-session-inventory, harness session inventory, session inventory, session adapter, session adapters, harness sessions, mcp inventory, mcp config inventory."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: harness-session-inventory
    role: tracker
    quality_tier: workflow-surface-gated
---

# Harness Session Inventory

This is an OMH `harness-session-inventory` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`harness-session-inventory` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

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



## When to Use

Use when operators need a cross-harness/session/MCP/worktree inventory and drift summary before claiming any host loaded, connector ran, or agent session progressed.

    Strong routing signals: `harness-session-inventory`, `harness session inventory`, `session inventory`, `session adapter`, `session adapters`, `harness sessions`, `mcp inventory`, `mcp config inventory`, `mcp drift`, `harness drift`, `connector drift`, `worktree inventory`, `worktree lifecycle`, `operator inventory`, `control pane inventory`, `codex session inventory`, `claude code session inventory`, `find previous coding session`, `recover coding session`, `previous codex coding session`, `coding session recall`, `세션 인벤토리`, `지난 코딩 세션`, `코딩 세션 복구`, `세션 기억 복구`, `하네스 세션`, `하네스 드리프트`, `MCP 인벤토리`, `MCP 설정 드리프트`, `워크트리 인벤토리`, `커넥터 드리프트`, `сессии агентов`, `инвентарь харнессов`, `восстанови сессию агента`, `инвентарь сессий`, `каждый харнесс`, `харнесс подхватывает`, `харнес подхватывает`

## Catalog Metadata

Category: `observability`
Phase: `harness-session-inventory`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- harness_session_inventory/v1 card or guidance
- harness_session_adapter_matrix/v1
- mcp_inventory_drift_report/v1
- mcp_tool_name_compatibility/v1
- worktree_lifecycle_snapshot/v1
- session_progress_slots/v1
- next action
- prepared-vs-observed boundary

Artifact expectations:

- harness_session_inventory/v1 metadata-only runtime or wrapper card when recorded
- harness_session_adapter_matrix/v1 with observed, prepared, missing, and stale adapters
- mcp_inventory_drift_report/v1 with secret-redacted config/source drift only
- mcp_tool_name_compatibility/v1 with secret-redacted config/source drift only: agents use `omh harness mcp-tool-name-compatibility --snapshot <path>` for supplied naming metadata; config-only and unsupported adapters stay unobserved, ambiguous names are never selected, and no tools are invoked
- worktree_lifecycle_snapshot/v1 with merge-conflict and cleanup candidates when observed

Safety rules:

- A harness session inventory is not host load, MCP tool-call, connector availability, executor dispatch, worktree cleanup, merge-conflict resolution, or session progress evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

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
